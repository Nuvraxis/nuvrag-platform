from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Computed, Index, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlmodel import Field, SQLModel

from app.models.base import CreatedAtMixin, OrgScopedMixin, UUIDPrimaryKeyMixin

# The Postgres text-search configuration the lexical half of hybrid search indexes and queries
# with. One value for the whole deployment, and structurally so: a generated column's
# expression must be immutable, so the configuration cannot vary by row, by tenant or by the
# language a document happens to be written in.
#
# `english` rather than `simple` because stemming is what makes an ordinary question match an
# ordinary sentence — "refunds" finding "refund". The cost is that English stopwords are
# stripped from every language, and no other language is stemmed. It is a real limitation for
# a platform whose widget answers in whatever language it is asked in; see the checklist.
TEXT_SEARCH_CONFIG = "english"


class DocumentChunk(UUIDPrimaryKeyMixin, OrgScopedMixin, CreatedAtMixin, SQLModel, table=True):
    """One embedded passage.

    The table is partitioned by LIST (embedding_dim) — see migration 0008. Two consequences
    show up here: `embedding_dim` is part of both keys, because Postgres requires the
    partition key in every unique constraint, and `embedding` carries no declared width,
    because every partition of a table must share the parent's column types exactly. The
    width is instead pinned per partition, by the check the partition bound already implies
    and by an HNSW index built over `embedding::vector(N)`.
    """

    __tablename__ = "document_chunk"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index", "embedding_dim", name="uq_document_chunk_doc_index"
        ),
        # Both columns together: the first keeps similarity search off other tenants' rows,
        # the second is what lets the planner prune to a single partition.
        Index("ix_document_chunk_chatbot_id_embedding_dim", "chatbot_id", "embedding_dim"),
        Index("ix_document_chunk_chatbot_id_document_id", "chatbot_id", "document_id"),
        # Both columns, in that order, and it needs `btree_gin` to hold the uuid. Measured on
        # 60k chunks across twelve chatbots: with a plain GIN over `content_tsv` alone the
        # planner ignored it entirely and filtered the tenant's 5,000 rows in the heap, because
        # a question ORed into its lexemes matches most of a corpus and is not selective. The
        # composite is what makes one index answer both halves of the predicate.
        #
        # Declared on the parent, like every btree index here, so Postgres builds and keeps it
        # on every partition — including ones added later. Unlike the HNSW index it needs no
        # per-partition DDL, because what it covers does not depend on the width.
        Index(
            "ix_document_chunk_chatbot_id_content_tsv",
            "chatbot_id",
            "content_tsv",
            postgresql_using="gin",
        ),
        {"postgresql_partition_by": "LIST (embedding_dim)"},
    )

    document_id: UUID = Field(
        foreign_key="document.id", ondelete="CASCADE", index=True, nullable=False
    )
    chatbot_id: UUID = Field(
        foreign_key="chatbot.id", ondelete="CASCADE", index=True, nullable=False
    )
    chunk_index: int = Field(nullable=False)
    content: str = Field(sa_type=Text, nullable=False)
    # Maintained by Postgres rather than by the ingestion pipeline: a generated column cannot
    # drift from the text it describes, and a re-indexed chunk cannot be left with the search
    # terms of the passage it replaced. `english` is a literal because a generated column has
    # to be immutable; see TEXT_SEARCH_CONFIG for what that costs.
    content_tsv: Any = Field(
        default=None,
        sa_column=Column(
            TSVECTOR,
            Computed(f"to_tsvector('{TEXT_SEARCH_CONFIG}', content)", persisted=True),
            nullable=True,
        ),
    )
    token_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"}, nullable=False)

    embedding_dim: int = Field(sa_column=Column(SmallInteger, primary_key=True, nullable=False))
    embedding: Any = Field(default=None, sa_column=Column(Vector(), nullable=False))
    # Page number, section heading and anything else needed to render a citation.
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
