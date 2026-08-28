from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, MetaData, func, text
from sqlmodel import Field, SQLModel

from app.core.security import utcnow

# Deterministic constraint names keep Alembic autogenerate diffs stable and make
# `op.drop_constraint` calls writable by hand.
SQLModel.metadata.naming_convention = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
).naming_convention

# `sa_type` + `sa_column_kwargs` are safe to share across subclasses; a concrete `sa_column`
# instance is not, since SQLAlchemy binds a Column to exactly one Table.
UTC_TIMESTAMP = DateTime(timezone=True)


def enum_column(enum_cls: type[StrEnum], *, name: str) -> Enum:
    """Store enums as VARCHAR rather than a native Postgres enum type.

    Native enums would persist member *names* (``FREE``) instead of values (``free``), and
    every new member would need an ``ALTER TYPE``. The value constraint is declared separately
    by :func:`enum_check` — a type-bound constraint is invisible to Alembic autogenerate,
    which would make every future migration propose dropping it.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        length=32,
        values_callable=lambda cls: [member.value for member in cls],
    )


def enum_check(column: str, enum_cls: type[StrEnum]) -> CheckConstraint:
    """Database-level guard that a column only ever holds known enum values.

    The naming convention expands `name` into ``ck_<table>_<column>``.
    """
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return CheckConstraint(f"{column} IN ({values})", name=column)


class UUIDPrimaryKeyMixin(SQLModel):
    id: UUID = Field(
        default_factory=uuid4,
        primary_key=True,
        sa_column_kwargs={"server_default": text("gen_random_uuid()")},
    )


class CreatedAtMixin(SQLModel):
    """Append-only rows carry only a creation stamp.

    Values are produced in Python; `server_default` is a safety net for rows inserted by raw
    SQL (migrations, backfills) rather than the ORM.
    """

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTC_TIMESTAMP,
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )


class TimestampMixin(CreatedAtMixin):
    # `onupdate` is a Python callable rather than `func.now()` on purpose: a SQL-side
    # onupdate leaves the attribute expired after flush, so reading it once the session has
    # closed raises DetachedInstanceError in every endpoint that returns an updated row.
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTC_TIMESTAMP,
        sa_column_kwargs={"server_default": func.now(), "onupdate": utcnow},
        nullable=False,
    )


class OrgScopedMixin(SQLModel):
    """Every tenant-owned row carries org_id; RLS policies and future partitioning key on it."""

    org_id: UUID = Field(
        foreign_key="organization.id", ondelete="CASCADE", index=True, nullable=False
    )


# Tables guarded by Row-Level Security. Kept here so the migration and the session-level
# tenant guard can never drift apart.
TENANT_SCOPED_TABLES = (
    "app_user",
    "invitation",
    "chatbot",
    "chatbot_ai_config",
    "document",
    "document_chunk",
    "conversation",
    "message",
    "ticket",
    # Partitioned, like `document_chunk`: the policy goes on the parent *and* on every
    # partition, because a partition is a table a role could reach directly. Migration 0012
    # does both.
    "memory_entry",
)
