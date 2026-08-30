from typing import Any

from pydantic import ConfigDict
from sqlalchemy import CheckConstraint, Column, Index, Text, UniqueConstraint, text
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

# The same bounds for nuvrag_mem, declared separately so the two can diverge without one
# quietly dragging the other with it.
NUVRAG_MEM_RETENTION_MIN_DAYS = 1
NUVRAG_MEM_RETENTION_MAX_DAYS = 3650

# Deliberately 30 rather than the NULL that `retention_days` defaults to, and the contrast is
# the point rather than an oversight. A transcript is a record of one conversation; a memory
# is a standing summary of a person across visits, which is the more sensitive of the two and
# the one a tenant is less likely to think to configure. So memory ships with a window
# already on, and a tenant who genuinely wants it kept forever clears the field — the same
# blank-means-forever spelling, reached from the opposite direction.
NUVRAG_MEM_RETENTION_DEFAULT_DAYS = 30

NUVRAG_MEM_RETENTION_CHECK = (
    f"nuvrag_mem_retention_days IS NULL OR "
    f"nuvrag_mem_retention_days BETWEEN "
    f"{NUVRAG_MEM_RETENTION_MIN_DAYS} AND {NUVRAG_MEM_RETENTION_MAX_DAYS}"
)

# Footer links. Long enough for a real policy URL with a path and a query, short enough that
# the column is not somewhere to put a document.
LINK_MAX_LENGTH = 500

# Usage caps. NULL means unlimited, which is what every chatbot starts at — this is a ceiling
# an operator opts into, not a tier anyone is sold.
#
# The lower bound is 1 rather than 0 for the same reason retention's is: a zero would read as
# "allow nothing", which is what `status = paused` already says properly. The upper bound is
# well under int4's range so that `used + amount <= cap` cannot overflow the column it is
# compared against.
USAGE_CAP_MIN = 1
USAGE_CAP_MAX = 1_000_000_000

USAGE_CAP_CHECKS = {
    "monthly_ingestion_unit_cap": (
        f"monthly_ingestion_unit_cap IS NULL OR "
        f"monthly_ingestion_unit_cap BETWEEN {USAGE_CAP_MIN} AND {USAGE_CAP_MAX}"
    ),
    "monthly_retrieval_call_cap": (
        f"monthly_retrieval_call_cap IS NULL OR "
        f"monthly_retrieval_call_cap BETWEEN {USAGE_CAP_MIN} AND {USAGE_CAP_MAX}"
    ),
}

# What a visitor is told when the chatbot has spent its month. Deliberately says nothing about
# quotas or billing: that is the operator's business, and a visitor can only act on the part
# that concerns them.
USAGE_CAP_MESSAGE_MAX_LENGTH = 1000
DEFAULT_USAGE_CAP_MESSAGE = (
    "Sorry — I can't answer questions right now. Please try again later, or ask for a human "
    "if you need help sooner."
)


def _sql_literal(value: str) -> str:
    """A SQL string literal for a `server_default`.

    Alembic's `compare_server_default` renders the metadata's default straight into a
    comparison query, so a plain Python string containing an apostrophe produces a syntax
    error rather than a diff. Handing it an already-quoted literal is what makes the default
    comparable at all.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


class Chatbot(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    __tablename__ = "chatbot"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_chatbot_org_id_slug"),
        Index("ix_chatbot_org_id_status", "org_id", "status"),
        enum_check("status", ChatbotStatus),
        # The naming convention expands `name` into `ck_chatbot_retention_days`.
        CheckConstraint(RETENTION_CHECK, name="retention_days"),
        CheckConstraint(NUVRAG_MEM_RETENTION_CHECK, name="nuvrag_mem_retention_days"),
        *(CheckConstraint(sql, name=column) for column, sql in USAGE_CAP_CHECKS.items()),
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

    # How long nuvrag_mem entries are kept, counted from `last_referenced_at`. NULL still
    # means forever, but unlike `retention_days` this starts at 30 — see the constant's note
    # for why the two neighbouring columns deliberately disagree.
    # No default of any kind here, deliberately — not a Python one and, since migration 0013,
    # not a server one either. A column whose NULL is *meaningful* cannot carry a non-NULL
    # default, because SQLAlchemy treats None at insert time as "nothing to say" and lets the
    # default fill it in: a tenant who chose "keep visitor memory forever" while creating a
    # chatbot silently got 30 days instead. `retention_days` next door is immune only because
    # it never had a default to begin with.
    #
    # The 30 a new chatbot starts at lives in `ChatbotCreate` instead, which sends it as a
    # value like any other. See `NUVRAG_MEM_RETENTION_DEFAULT_DAYS`.
    nuvrag_mem_retention_days: int | None = Field(default=None, nullable=True)

    # No default of any kind on either cap, for the reason migration 0013 spells out: NULL is
    # meaningful here — it means unlimited — and SQLAlchemy treats a None at insert time as
    # "nothing to say" and lets any default overwrite it.
    monthly_ingestion_unit_cap: int | None = Field(default=None, nullable=True)
    monthly_retrieval_call_cap: int | None = Field(default=None, nullable=True)

    usage_cap_message: str = Field(
        default=DEFAULT_USAGE_CAP_MESSAGE,
        max_length=USAGE_CAP_MESSAGE_MAX_LENGTH,
        sa_type=Text,
        nullable=False,
        sa_column_kwargs={"server_default": text(_sql_literal(DEFAULT_USAGE_CAP_MESSAGE))},
    )

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
