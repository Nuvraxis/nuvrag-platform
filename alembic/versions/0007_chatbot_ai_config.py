"""Per-chatbot AI provider configuration

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "app.current_org_id"
POLICY_NAME = "tenant_isolation"

_UUID = postgresql.UUID(as_uuid=True)
_TS = sa.DateTime(timezone=True)

CHAT_PROVIDERS = ("azure", "bedrock", "anthropic", "ollama")
# Anthropic publishes no embeddings API, so the database refuses it here as well as the
# schema layer above — a provider that cannot produce vectors must not be storable as the
# thing that produces them.
EMBEDDING_PROVIDERS = ("azure", "bedrock", "ollama")


def _enum_check(column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    rendered = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({rendered})", name=column)


def upgrade() -> None:
    op.create_table(
        "chatbot_ai_config",
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", _UUID, nullable=False),
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("chat_provider", sa.String(length=32), nullable=False),
        sa.Column("chat_model", sa.String(length=200), nullable=False),
        sa.Column("chat_credentials_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "chat_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("embedding_provider", sa.String(length=32), nullable=False),
        sa.Column("embedding_model", sa.String(length=200), nullable=False),
        sa.Column("embedding_credentials_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "embedding_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("embedding_dimension", sa.SmallInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_chatbot_ai_config"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_chatbot_ai_config_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"],
            ["chatbot.id"],
            name="fk_chatbot_ai_config_chatbot_id_chatbot",
            ondelete="CASCADE",
        ),
        _enum_check("chat_provider", CHAT_PROVIDERS),
        _enum_check("embedding_provider", EMBEDDING_PROVIDERS),
    )
    op.create_index("ix_chatbot_ai_config_org_id", "chatbot_ai_config", ["org_id"])
    op.create_index(
        "ix_chatbot_ai_config_chatbot_id", "chatbot_ai_config", ["chatbot_id"], unique=True
    )

    op.execute("ALTER TABLE chatbot_ai_config ENABLE ROW LEVEL SECURITY")
    # The same fail-closed predicate as every other tenant table: an unset GUC is NULL, so the
    # table reads as empty rather than as everyone's. It matters more here than most — these
    # rows carry other tenants' provider credentials.
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME} ON chatbot_ai_config
        USING (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON chatbot_ai_config")
    op.drop_index("ix_chatbot_ai_config_chatbot_id", table_name="chatbot_ai_config")
    op.drop_index("ix_chatbot_ai_config_org_id", table_name="chatbot_ai_config")
    op.drop_table("chatbot_ai_config")
