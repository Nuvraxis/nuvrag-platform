from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index, SmallInteger, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import CreatedAtMixin, OrgScopedMixin, UUIDPrimaryKeyMixin


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
    token_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"}, nullable=False)

    embedding_dim: int = Field(sa_column=Column(SmallInteger, primary_key=True, nullable=False))
    embedding: Any = Field(default=None, sa_column=Column(Vector(), nullable=False))
    # Page number, section heading and anything else needed to render a citation.
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
