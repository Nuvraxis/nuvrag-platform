"""nuvrag_mem: per-visitor memory across sessions

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-26

Adds `memory_entry` and `chatbot.nuvrag_mem_retention_days`.

`memory_entry` is partitioned by LIST (embedding_dim) for exactly the reason `document_chunk`
is (migration 0008): Postgres refuses to compare vectors of different widths at all, so a
mixed-width table is not slow, it is an error. The same three shapes follow from that and are
forced rather than chosen — the partition key joins the primary key, `embedding` carries no
declared width because a partition must match its parent's column types, and the width is
pinned per partition by an HNSW index over `embedding::vector(N)`.

RLS goes on the parent *and* on every partition. A partition is a table in its own right, and
a role that reached one directly would otherwise read every tenant's memories.

`chatbot.nuvrag_mem_retention_days` defaults to 30 rather than to NULL, which is deliberately
unlike `retention_days` next to it. A transcript is a record of one conversation; a memory is
a standing summary of a person across visits. Existing rows therefore get 30 too — safe here
because `memory_entry` is created empty by this same migration, so nothing can be swept that
a tenant did not knowingly accumulate afterwards.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_TS = sa.DateTime(timezone=True)

TENANT_GUC = "app.current_org_id"
POLICY_NAME = "tenant_isolation"

# The same widths `document_chunk` partitions on, and for the same providers: Ollama
# nomic-embed-text, Bedrock Titan v2, Azure text-embedding-3-small / Titan v1. Written out
# rather than imported — a migration has to keep describing the schema it produced even after
# the model moves on.
DIMENSIONS = (768, 1024, 1536)
DEFAULT_PARTITION = "memory_entry_pdefault"

HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64

SUBJECT_TYPES = ("visitor", "staff_user")
MEMORY_TYPES = ("preference", "fact", "context")

# Mirrors `NUVRAG_MEM_RETENTION_CHECK` in app/models/chatbot.py.
RETENTION_CONSTRAINT = "ck_chatbot_nuvrag_mem_retention_days"
RETENTION_SQL = "nuvrag_mem_retention_days IS NULL OR nuvrag_mem_retention_days BETWEEN 1 AND 3650"
RETENTION_DEFAULT_DAYS = 30


def _partition(dimension: int) -> str:
    return f"memory_entry_p{dimension}"


def _enum_check(column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    """Raw name, matching 0009: `op.create_check_constraint` would feed it back through the
    metadata naming convention and expand an already-expanded name a second time."""
    rendered = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({rendered})", name=column)


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
    op.create_table(
        "memory_entry",
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", _UUID, nullable=False),
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False, server_default="visitor"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False, server_default="fact"),
        sa.Column("embedding_dim", sa.SmallInteger(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("source_conversation_id", _UUID, nullable=True),
        sa.Column("last_referenced_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", "embedding_dim", name="pk_memory_entry"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_memory_entry_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"],
            ["chatbot.id"],
            name="fk_memory_entry_chatbot_id_chatbot",
            ondelete="CASCADE",
        ),
        # SET NULL, not CASCADE. A memory must outlive the conversation it was learned in:
        # the visitor is the same person after their transcript ages out, and tying the two
        # lifecycles together would make retention silently an erasure mechanism.
        sa.ForeignKeyConstraint(
            ["source_conversation_id"],
            ["conversation.id"],
            name="fk_memory_entry_source_conversation_id_conversation",
            ondelete="SET NULL",
        ),
        _enum_check("subject_type", SUBJECT_TYPES),
        _enum_check("memory_type", MEMORY_TYPES),
        postgresql_partition_by="LIST (embedding_dim)",
    )

    for dimension in DIMENSIONS:
        op.execute(
            f"CREATE TABLE {_partition(dimension)} PARTITION OF memory_entry "
            f"FOR VALUES IN ({dimension})"
        )
    # An unanticipated width should make retrieval slow, not make extraction fail outright.
    op.execute(f"CREATE TABLE {DEFAULT_PARTITION} PARTITION OF memory_entry DEFAULT")

    # Declared on the parent, so Postgres creates and maintains the match on every partition,
    # including any added later.
    op.create_index("ix_memory_entry_org_id", "memory_entry", ["org_id"])
    op.create_index("ix_memory_entry_chatbot_id", "memory_entry", ["chatbot_id"])
    op.create_index(
        "ix_memory_entry_source_conversation_id", "memory_entry", ["source_conversation_id"]
    )
    # The retrieval predicate, in the order it filters.
    op.create_index(
        "ix_memory_entry_chatbot_id_subject_id_embedding_dim",
        "memory_entry",
        ["chatbot_id", "subject_id", "embedding_dim"],
    )
    # What the retention sweep scans on: ages on last use, not on creation.
    op.create_index(
        "ix_memory_entry_chatbot_id_last_referenced_at",
        "memory_entry",
        ["chatbot_id", "last_referenced_at"],
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

    for table in ("memory_entry", *(_partition(d) for d in DIMENSIONS), DEFAULT_PARTITION):
        _enable_rls(table)

    op.add_column(
        "chatbot",
        sa.Column(
            "nuvrag_mem_retention_days",
            sa.Integer(),
            nullable=True,
            server_default=str(RETENTION_DEFAULT_DAYS),
        ),
    )
    op.execute(f"ALTER TABLE chatbot ADD CONSTRAINT {RETENTION_CONSTRAINT} CHECK ({RETENTION_SQL})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE chatbot DROP CONSTRAINT {RETENTION_CONSTRAINT}")
    op.drop_column("chatbot", "nuvrag_mem_retention_days")
    # CASCADE takes the partitions and their indexes with it; dropping them individually first
    # would only be a longer way to reach the same place.
    op.execute("DROP TABLE memory_entry CASCADE")
