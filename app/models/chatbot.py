from typing import Any

from pydantic import ConfigDict
from sqlalchemy import CheckConstraint, Column, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import (
    OrgScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    enum_column,
)
from app.models.enums import ChatbotStatus

DEFAULT_GENERATION_CONFIG: dict[str, Any] = {
    "temperature": 0.2,
    "max_tokens": 1024,
    "top_k": 5,
    "min_similarity": 0.25,
}

# Bounds for `retention_days`, defined once and reused by the request schema, the check
# constraint below and migration 0010. A day is the smallest unit worth offering — an hour
# would promise a precision a once-daily sweep cannot keep — and ten years is past the point
# where "keep forever" is the honest answer instead.
RETENTION_MIN_DAYS = 1
RETENTION_MAX_DAYS = 3650

RETENTION_CHECK = (
    f"retention_days IS NULL OR "
    f"retention_days BETWEEN {RETENTION_MIN_DAYS} AND {RETENTION_MAX_DAYS}"
)

# Footer links. Long enough for a real policy URL with a path and a query, short enough that
# the column is not somewhere to put a document.
LINK_MAX_LENGTH = 500


class Chatbot(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "chatbot"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_chatbot_org_id_slug"),
        Index("ix_chatbot_org_id_status", "org_id", "status"),
        enum_check("status", ChatbotStatus),
        # The naming convention expands `name` into `ck_chatbot_retention_days`.
        CheckConstraint(RETENTION_CHECK, name="retention_days"),
    )

    # `model_config_json` collides with Pydantic's reserved `model_` namespace.
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(max_length=200, nullable=False)
    slug: str = Field(max_length=100, nullable=False)
    description: str | None = Field(default=None, max_length=1000)
    system_prompt: str = Field(default="", sa_type=Text, nullable=False)

    model_config_json: dict[str, Any] = Field(
        default_factory=lambda: dict(DEFAULT_GENERATION_CONFIG),
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    allowed_origins: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    # Only what the tenant has actually chosen is stored. An absent key means "whatever the
    # widget's own stylesheet does", which is what lets the default theme change with a
    # widget release instead of being frozen into every row at creation time.
    theme_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    # How long visitor transcripts are kept, counted from a conversation's last activity.
    # NULL means keep them forever — which is what every row predating this column means, and
    # what the platform did unconditionally before it existed. Retention therefore never
    # switches itself on: deleting a tenant's history is an explicit choice they make.
    retention_days: int | None = Field(default=None, nullable=True)

    # Shown in the widget footer, above the branding. Deliberately *not* in `theme_json`:
    # "Reset to the default theme" empties that column outright, and quietly deleting a
    # tenant's privacy notice because they changed their mind about a colour would be a bug
    # with legal consequences. Empty string means no link, matching `description`.
    privacy_url: str = Field(
        default="",
        max_length=LINK_MAX_LENGTH,
        nullable=False,
        sa_column_kwargs={"server_default": ""},
    )
    terms_url: str = Field(
        default="",
        max_length=LINK_MAX_LENGTH,
        nullable=False,
        sa_column_kwargs={"server_default": ""},
    )

    public_key: str = Field(max_length=128, unique=True, index=True, nullable=False)
    secret_key_hash: str = Field(max_length=128, nullable=False)
    status: ChatbotStatus = Field(
        default=ChatbotStatus.ACTIVE,
        sa_type=enum_column(ChatbotStatus, name="status"),
        nullable=False,
    )
