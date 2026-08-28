from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Index, SmallInteger, Text, func
from sqlmodel import Field, SQLModel

from app.core.security import utcnow
from app.models.base import (
    UTC_TIMESTAMP,
    CreatedAtMixin,
    OrgScopedMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    enum_column,
)
from app.models.enums import MemorySubjectType, MemoryType

# Short by construction. A memory is a sentence about someone, not a passage — anything
# longer is a document, and `document_chunk` is the table built for those.
CONTENT_MAX_LENGTH = 500
SUBJECT_MAX_LENGTH = 128


class MemoryEntry(UUIDPrimaryKeyMixin, OrgScopedMixin, CreatedAtMixin, SQLModel, table=True):
    """One remembered fact about one visitor, on one chatbot.

    Partitioned by LIST (embedding_dim) exactly like `document_chunk` — see migration 0012 —
    and for the same reason: Postgres refuses to compare vectors of different widths at all,
    so the width has to be structural. The three consequences that show up here are the same
    three: `embedding_dim` joins the primary key because a partitioned table needs its
    partition key in every unique constraint, `embedding` carries no declared width because a
    partition must match its parent's column types exactly, and the width is pinned per
    partition by an HNSW index built over `embedding::vector(N)`.

    Keyed on `(chatbot_id, subject_id)` rather than on a conversation, which is the whole
    point of the table: it outlives the session it was learned in.
    """

    __tablename__ = "memory_entry"
    __table_args__ = (
        # The retrieval predicate, in the order it filters: the chatbot keeps one tenant's bot
        # out of another's memories, the subject narrows to one visitor, and the width lets
        # the planner prune to a single partition before the index scan.
        Index(
            "ix_memory_entry_chatbot_id_subject_id_embedding_dim",
            "chatbot_id",
            "subject_id",
            "embedding_dim",
        ),
        # What the retention sweep scans on.
        Index("ix_memory_entry_chatbot_id_last_referenced_at", "chatbot_id", "last_referenced_at"),
        enum_check("subject_type", MemorySubjectType),
        enum_check("memory_type", MemoryType),
        {"postgresql_partition_by": "LIST (embedding_dim)"},
    )

    chatbot_id: UUID = Field(
        foreign_key="chatbot.id", ondelete="CASCADE", index=True, nullable=False
    )

    # Text rather than UUID: a visitor's subject is an `external_session_id`, a
    # browser-generated hex string, while a staff subject is an `app_user.id`. One column
    # holding both is what lets a single index serve both lookups.
    subject_id: str = Field(max_length=SUBJECT_MAX_LENGTH, nullable=False)
    subject_type: MemorySubjectType = Field(
        default=MemorySubjectType.VISITOR,
        sa_column=Column(
            enum_column(MemorySubjectType, name="memory_subject_type"),
            nullable=False,
            server_default=MemorySubjectType.VISITOR.value,
        ),
    )

    content: str = Field(max_length=CONTENT_MAX_LENGTH, sa_type=Text, nullable=False)
    memory_type: MemoryType = Field(
        default=MemoryType.FACT,
        sa_column=Column(
            enum_column(MemoryType, name="memory_type"),
            nullable=False,
            server_default=MemoryType.FACT.value,
        ),
    )

    embedding_dim: int = Field(sa_column=Column(SmallInteger, primary_key=True, nullable=False))
    embedding: Any = Field(default=None, sa_column=Column(Vector(), nullable=False))

    # SET NULL, deliberately not CASCADE. A memory must not vanish the moment the conversation
    # it was learned in ages out of retention: the visitor is the same person either way, and
    # tying the two lifecycles together would mean a transcript expiring silently erased what
    # was known about them. Erasing a visitor is a separate, explicit action.
    # Indexed because the SET NULL fires per deleted conversation, and both the retention
    # sweep and a manual conversation delete do that in batches.
    source_conversation_id: UUID | None = Field(
        default=None,
        foreign_key="conversation.id",
        ondelete="SET NULL",
        index=True,
        nullable=True,
    )

    # The sweep ages on this rather than `created_at`, the same way a conversation ages on
    # `updated_at`: a memory still being retrieved has not gone stale just because it was
    # written a while ago. Set on insert, moved forward whenever retrieval returns the row.
    last_referenced_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTC_TIMESTAMP,
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )
