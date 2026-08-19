"""Partition document_chunk by embedding dimension

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-13

Different providers return different vector widths, and Postgres refuses to compare vectors
of different lengths at all — a mismatch is an error, not a bad result. Partitioning on the
width makes that structural: each partition holds one width and carries an HNSW index built
for it, and every retrieval query names the width so the planner reaches exactly one
partition.

Two shapes here are forced by Postgres rather than chosen. A partition must have precisely
its parent's column types, so `embedding` loses its declared width and the width is pinned
per partition by the index instead — pgvector cannot index a column with no dimensions, but
it will happily index `embedding::vector(N)`. And every unique constraint on a partitioned
table must contain the partition key, which is why `embedding_dim` joins both keys.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_TS = sa.DateTime(timezone=True)

TENANT_GUC = "app.current_org_id"
POLICY_NAME = "tenant_isolation"

# Ollama nomic-embed-text, Bedrock Titan v2, and Azure text-embedding-3-small / Titan v1.
DIMENSIONS = (768, 1024, 1536)
DEFAULT_PARTITION = "document_chunk_pdefault"
# The width the single-provider schema hardcoded, and therefore the only width any existing
# row can have.
LEGACY_DIMENSION = 1536

HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64

_CARRY_TABLE = "document_chunk_carry"


def _partition(dimension: int) -> str:
    return f"document_chunk_p{dimension}"


def _row_count(table: str) -> int:
    return int(op.get_bind().execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one())


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME} ON {table}
        USING (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        """
    )


def upgrade() -> None:
    # `document_chunk` is expected to be empty wherever this runs, but "expected" is no reason
    # to write a migration that loses rows if it is not. The data is staged, copied back and
    # counted before the staging table is released; when there is nothing to carry, none of
    # that work happens.
    carried = _row_count("document_chunk")
    if carried:
        op.execute(f"CREATE TABLE {_CARRY_TABLE} AS TABLE document_chunk")

    op.drop_table("document_chunk")
    _create_partitioned_chunks()

    if carried:
        op.execute(
            f"""
            INSERT INTO document_chunk (
                id, org_id, document_id, chatbot_id, chunk_index, content, token_count,
                embedding_dim, embedding, metadata_json, created_at
            )
            SELECT id, org_id, document_id, chatbot_id, chunk_index, content, token_count,
                   vector_dims(embedding), embedding, metadata_json, created_at
            FROM {_CARRY_TABLE}
            """
        )
        restored = _row_count("document_chunk")
        if restored != carried:
            raise RuntimeError(
                f"Carried {carried} chunks into the partitioned table but found {restored}; "
                f"{_CARRY_TABLE} has been left in place."
            )
        op.execute(f"DROP TABLE {_CARRY_TABLE}")


def _create_partitioned_chunks() -> None:
    op.create_table(
        "document_chunk",
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", _UUID, nullable=False),
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", _UUID, nullable=False),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_dim", sa.SmallInteger(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", "embedding_dim", name="pk_document_chunk"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_document_chunk_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_document_chunk_document_id_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"],
            ["chatbot.id"],
            name="fk_document_chunk_chatbot_id_chatbot",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_id", "chunk_index", "embedding_dim", name="uq_document_chunk_doc_index"
        ),
        postgresql_partition_by="LIST (embedding_dim)",
    )

    for dimension in DIMENSIONS:
        op.execute(
            f"CREATE TABLE {_partition(dimension)} PARTITION OF document_chunk "
            f"FOR VALUES IN ({dimension})"
        )
    # A width nobody anticipated should slow retrieval down, not fail ingestion outright. The
    # pipeline logs when a chunk lands here so the partition can be added deliberately.
    op.execute(f"CREATE TABLE {DEFAULT_PARTITION} PARTITION OF document_chunk DEFAULT")

    # Declared on the parent, so Postgres creates and maintains the matching index on every
    # partition, including ones added later.
    op.create_index("ix_document_chunk_org_id", "document_chunk", ["org_id"])
    op.create_index("ix_document_chunk_document_id", "document_chunk", ["document_id"])
    op.create_index("ix_document_chunk_chatbot_id", "document_chunk", ["chatbot_id"])
    op.create_index(
        "ix_document_chunk_chatbot_id_document_id", "document_chunk", ["chatbot_id", "document_id"]
    )
    op.create_index(
        "ix_document_chunk_chatbot_id_embedding_dim",
        "document_chunk",
        ["chatbot_id", "embedding_dim"],
    )

    for dimension in DIMENSIONS:
        op.execute(
            f"""
            CREATE INDEX ix_{_partition(dimension)}_embedding_hnsw
            ON {_partition(dimension)}
            USING hnsw ((embedding::vector({dimension})) vector_cosine_ops)
            WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
            """
        )

    # The parent's policy covers every query that goes through the parent, which is all of
    # them. The partitions get their own because a partition is also a table in its own right,
    # and a role that can reach it directly would otherwise read every tenant's chunks.
    for table in ("document_chunk", *(_partition(d) for d in DIMENSIONS), DEFAULT_PARTITION):
        _enable_rls(table)


def downgrade() -> None:
    carried = _row_count("document_chunk")
    if carried:
        unsupported = int(
            op.get_bind()
            .execute(
                sa.text("SELECT count(*) FROM document_chunk WHERE embedding_dim <> :legacy"),
                {"legacy": LEGACY_DIMENSION},
            )
            .scalar_one()
        )
        if unsupported:
            # The unpartitioned table is a single fixed width. Silently dropping the rows that
            # do not fit would be the worst of the available outcomes.
            raise RuntimeError(
                f"{unsupported} chunks use an embedding width other than {LEGACY_DIMENSION} "
                "and cannot be moved back into an unpartitioned document_chunk. Delete those "
                "chatbots' documents first."
            )
        op.execute(f"CREATE TABLE {_CARRY_TABLE} AS TABLE document_chunk")

    op.execute("DROP TABLE document_chunk CASCADE")

    op.create_table(
        "document_chunk",
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", _UUID, nullable=False),
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", _UUID, nullable=False),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(LEGACY_DIMENSION), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunk"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_document_chunk_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.id"],
            name="fk_document_chunk_document_id_document",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"],
            ["chatbot.id"],
            name="fk_document_chunk_chatbot_id_chatbot",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_doc_index"),
    )
    op.create_index("ix_document_chunk_org_id", "document_chunk", ["org_id"])
    op.create_index("ix_document_chunk_document_id", "document_chunk", ["document_id"])
    op.create_index("ix_document_chunk_chatbot_id", "document_chunk", ["chatbot_id"])
    op.create_index(
        "ix_document_chunk_chatbot_id_document_id", "document_chunk", ["chatbot_id", "document_id"]
    )
    op.execute(
        f"""
        CREATE INDEX ix_document_chunk_embedding_hnsw
        ON document_chunk
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
        """
    )
    _enable_rls("document_chunk")

    if carried:
        op.execute(
            f"""
            INSERT INTO document_chunk (
                id, org_id, document_id, chatbot_id, chunk_index, content, token_count,
                embedding, metadata_json, created_at
            )
            SELECT id, org_id, document_id, chatbot_id, chunk_index, content, token_count,
                   embedding::vector({LEGACY_DIMENSION}), metadata_json, created_at
            FROM {_CARRY_TABLE}
            """
        )
        op.execute(f"DROP TABLE {_CARRY_TABLE}")
