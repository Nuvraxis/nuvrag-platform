"""Initial tenant, chatbot, document and conversation schema

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 1536

_UUID = postgresql.UUID(as_uuid=True)
_TS = sa.DateTime(timezone=True)


def _created_at() -> sa.Column:
    return sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False)


def _updated_at() -> sa.Column:
    return sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False)


def _pk() -> sa.Column:
    return sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False)


def _enum_check(column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    """Enums are stored as checked VARCHAR. The metadata naming convention expands `name`
    into `ck_<table>_<name>`, so only the bare name is supplied here."""
    rendered = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({rendered})", name=column)


def upgrade() -> None:
    op.create_table(
        "organization",
        _created_at(),
        _updated_at(),
        _pk(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_organization"),
        _enum_check("plan", ("free", "pro", "enterprise")),
    )
    op.create_index("ix_organization_slug", "organization", ["slug"], unique=True)

    op.create_table(
        "app_user",
        _created_at(),
        _updated_at(),
        sa.Column("org_id", _UUID, nullable=False),
        _pk(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_app_user_org_id_organization",
            ondelete="CASCADE",
        ),
        _enum_check("role", ("owner", "admin", "member")),
    )
    op.create_index("ix_app_user_org_id", "app_user", ["org_id"])
    op.create_index("ix_app_user_email", "app_user", ["email"], unique=True)
    op.create_index("ix_app_user_org_id_email", "app_user", ["org_id", "email"])

    op.create_table(
        "chatbot",
        _created_at(),
        _updated_at(),
        sa.Column("org_id", _UUID, nullable=False),
        _pk(),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "model_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "allowed_origins",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("public_key", sa.String(length=128), nullable=False),
        sa.Column("secret_key_hash", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_chatbot"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_chatbot_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "slug", name="uq_chatbot_org_id_slug"),
        _enum_check("status", ("active", "paused", "archived")),
    )
    op.create_index("ix_chatbot_org_id", "chatbot", ["org_id"])
    op.create_index("ix_chatbot_public_key", "chatbot", ["public_key"], unique=True)
    op.create_index("ix_chatbot_org_id_status", "chatbot", ["org_id", "status"])

    op.create_table(
        "document",
        _created_at(),
        _updated_at(),
        sa.Column("org_id", _UUID, nullable=False),
        _pk(),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("uploaded_by", _UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_document"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_document_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"],
            ["chatbot.id"],
            name="fk_document_chatbot_id_chatbot",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["app_user.id"],
            name="fk_document_uploaded_by_app_user",
            ondelete="SET NULL",
        ),
        _enum_check("status", ("pending", "processing", "ready", "failed")),
        _enum_check("file_type", ("pdf", "docx", "md", "txt")),
    )
    op.create_index("ix_document_org_id", "document", ["org_id"])
    op.create_index("ix_document_chatbot_id", "document", ["chatbot_id"])
    op.create_index("ix_document_checksum_sha256", "document", ["checksum_sha256"])
    op.create_index("ix_document_chatbot_id_status", "document", ["chatbot_id", "status"])
    op.create_index("ix_document_chatbot_id_created_at", "document", ["chatbot_id", "created_at"])

    op.create_table(
        "document_chunk",
        _created_at(),
        sa.Column("org_id", _UUID, nullable=False),
        _pk(),
        sa.Column("document_id", _UUID, nullable=False),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
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
        "ix_document_chunk_chatbot_id_document_id",
        "document_chunk",
        ["chatbot_id", "document_id"],
    )

    op.create_table(
        "conversation",
        _created_at(),
        _updated_at(),
        sa.Column("org_id", _UUID, nullable=False),
        _pk(),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("external_session_id", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id", name="pk_conversation"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_conversation_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"],
            ["chatbot.id"],
            name="fk_conversation_chatbot_id_chatbot",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "chatbot_id", "external_session_id", name="uq_conversation_chatbot_session"
        ),
    )
    op.create_index("ix_conversation_org_id", "conversation", ["org_id"])
    op.create_index("ix_conversation_chatbot_id", "conversation", ["chatbot_id"])
    op.create_index("ix_conversation_external_session_id", "conversation", ["external_session_id"])
    op.create_index(
        "ix_conversation_chatbot_id_created_at", "conversation", ["chatbot_id", "created_at"]
    )

    op.create_table(
        "message",
        _created_at(),
        sa.Column("org_id", _UUID, nullable=False),
        _pk(),
        sa.Column("conversation_id", _UUID, nullable=False),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_message"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_message_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name="fk_message_conversation_id_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"],
            ["chatbot.id"],
            name="fk_message_chatbot_id_chatbot",
            ondelete="CASCADE",
        ),
        _enum_check("role", ("user", "assistant")),
    )
    op.create_index("ix_message_org_id", "message", ["org_id"])
    op.create_index("ix_message_chatbot_id", "message", ["chatbot_id"])
    op.create_index("ix_message_conversation_id", "message", ["conversation_id"])
    op.create_index(
        "ix_message_conversation_id_created_at", "message", ["conversation_id", "created_at"]
    )


def downgrade() -> None:
    for table in (
        "message",
        "conversation",
        "document_chunk",
        "document",
        "chatbot",
        "app_user",
        "organization",
    ):
        op.drop_table(table)
