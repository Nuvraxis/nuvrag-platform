from typing import Any
from uuid import UUID

from sqlalchemy import Column, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import (
    CreatedAtMixin,
    OrgScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    enum_column,
)
from app.models.enums import MessageRole


class Conversation(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "conversation"
    __table_args__ = (
        UniqueConstraint(
            "chatbot_id", "external_session_id", name="uq_conversation_chatbot_session"
        ),
        Index("ix_conversation_chatbot_id_created_at", "chatbot_id", "created_at"),
    )

    chatbot_id: UUID = Field(
        foreign_key="chatbot.id", ondelete="CASCADE", index=True, nullable=False
    )
    # Widget-generated and anonymous: no PII is required to talk to a bot.
    external_session_id: str = Field(max_length=128, index=True, nullable=False)
    title: str | None = Field(default=None, max_length=300)
    message_count: int = Field(default=0, sa_column_kwargs={"server_default": "0"}, nullable=False)


class Message(UUIDPrimaryKeyMixin, OrgScopedMixin, CreatedAtMixin, SQLModel, table=True):
    __tablename__ = "message"
    __table_args__ = (
        Index("ix_message_conversation_id_created_at", "conversation_id", "created_at"),
        enum_check("role", MessageRole),
    )

    conversation_id: UUID = Field(
        foreign_key="conversation.id", ondelete="CASCADE", index=True, nullable=False
    )
    chatbot_id: UUID = Field(
        foreign_key="chatbot.id", ondelete="CASCADE", index=True, nullable=False
    )
    role: MessageRole = Field(sa_type=enum_column(MessageRole, name="role"), nullable=False)
    content: str = Field(sa_type=Text, nullable=False)
    # Who wrote a `role='staff'` reply. Nullable and SET NULL on delete, the same pattern as
    # `document.uploaded_by`: attribution is worth keeping, but never at the cost of blocking
    # a staff member's removal. Null on every AI and visitor turn.
    staff_user_id: UUID | None = Field(
        default=None, foreign_key="app_user.id", ondelete="SET NULL", index=True
    )
    # Cited chunks, denormalised so the widget can render sources without a join.
    sources_json: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    prompt_tokens: int | None = Field(default=None)
    completion_tokens: int | None = Field(default=None)
    latency_ms: int | None = Field(default=None)
