from typing import Any
from uuid import UUID

from sqlalchemy import Column, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import (
    OrgScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    enum_column,
)
from app.models.enums import ChatProviderName, EmbeddingProviderName

# Partitions of `document_chunk` exist for these widths; anything else lands in the DEFAULT
# partition, which works but has no index sized for it. Kept beside the model so the list and
# the migration that creates the partitions are read together.
PARTITIONED_EMBEDDING_DIMENSIONS = (768, 1024, 1536)


class ChatbotAIConfig(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    """Which providers one chatbot talks to, and the credentials for them.

    Chat and embedding are configured independently because they are not the same market: a
    tenant may well want Anthropic answering questions over vectors that Bedrock produced,
    and Anthropic cannot produce vectors at all.
    """

    __tablename__ = "chatbot_ai_config"
    __table_args__ = (
        enum_check("chat_provider", ChatProviderName),
        enum_check("embedding_provider", EmbeddingProviderName),
    )

    chatbot_id: UUID = Field(
        foreign_key="chatbot.id", ondelete="CASCADE", unique=True, index=True, nullable=False
    )

    chat_provider: ChatProviderName = Field(
        sa_type=enum_column(ChatProviderName, name="chat_provider"), nullable=False
    )
    chat_model: str = Field(max_length=200, nullable=False)
    # Null until someone supplies a key. Ollama never needs one, so null is also the steady
    # state for a self-hosted chatbot rather than only a half-finished one.
    chat_credentials_encrypted: str | None = Field(default=None, sa_type=Text)
    # Non-secret connection detail only: endpoint URL, AWS region, Ollama base URL, `think`.
    chat_config_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    embedding_provider: EmbeddingProviderName = Field(
        sa_type=enum_column(EmbeddingProviderName, name="embedding_provider"), nullable=False
    )
    embedding_model: str = Field(max_length=200, nullable=False)
    embedding_credentials_encrypted: str | None = Field(default=None, sa_type=Text)
    embedding_config_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # Measured from a real call rather than looked up from the model name, then locked: every
    # vector already written for this chatbot is this wide, and comparing vectors of different
    # widths is an error at the database level, not a quality problem.
    embedding_dimension: int | None = Field(default=None, sa_column=Column(SmallInteger))
