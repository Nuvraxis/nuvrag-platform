"""Usage caps: per-chatbot ceilings on ingestion and retrieval spend

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-29

Two nullable caps and a message on `chatbot`, plus `chatbot_usage_period` — one row per
chatbot per UTC calendar month, holding the running totals the caps are compared against.

Both caps are nullable with **no default**, and that is load-bearing rather than incidental:
NULL means unlimited, so a default would state the opposite of what an explicit NULL says.
Migration 0013 exists because that exact contradiction was shipped once already on
`nuvrag_mem_retention_days`. `usage_cap_message` is different — NULL means nothing there, so
it takes a server default, which is also what backfills the rows that already exist.

`chatbot_usage_period` is keyed on `(chatbot_id, period_start)` rather than one current row
per chatbot. A month boundary is then an insert rather than an update that has to work out
whether it is continuing a period or starting one, and the rows left behind are the history a
later iteration would otherwise have to reconstruct. It carries `org_id` even though
`chatbot_id` implies it, so its RLS policy reads exactly like every other one in this schema
rather than joining to `chatbot` to find the tenant.

Counters deliberately start at zero for every chatbot. Nothing is backfilled from documents
already ingested: a cap is a ceiling on what happens next, and charging a tenant on day one
for a corpus they uploaded last year would be the wrong reading of it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)
_TS = sa.DateTime(timezone=True)

TENANT_GUC = "app.current_org_id"
POLICY_NAME = "tenant_isolation"
USAGE_TABLE = "chatbot_usage_period"

# Mirrors `USAGE_CAP_MIN` / `USAGE_CAP_MAX` in app/models/chatbot.py.
CAP_MIN = 1
CAP_MAX = 1_000_000_000

CAP_COLUMNS = ("monthly_ingestion_unit_cap", "monthly_retrieval_call_cap")

DEFAULT_USAGE_CAP_MESSAGE = (
    "Sorry — I can't answer questions right now. Please try again later, or ask for a human "
    "if you need help sooner."
)


def _sql_literal(value: str) -> str:
    """Mirrors the helper in app/models/chatbot.py — see it for why the default is quoted."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _cap_check(column: str) -> str:
    return f"{column} IS NULL OR {column} BETWEEN {CAP_MIN} AND {CAP_MAX}"


def upgrade() -> None:
    for column in CAP_COLUMNS:
        op.add_column("chatbot", sa.Column(column, sa.Integer(), nullable=True))
        # Raw rather than `op.create_check_constraint`, matching 0009 and 0012: the helper
        # feeds the name back through the metadata naming convention and expands an
        # already-expanded name a second time.
        op.execute(
            f"ALTER TABLE chatbot ADD CONSTRAINT ck_chatbot_{column} CHECK ({_cap_check(column)})"
        )

    op.add_column(
        "chatbot",
        sa.Column(
            "usage_cap_message",
            sa.Text(),
            nullable=False,
            server_default=sa.text(_sql_literal(DEFAULT_USAGE_CAP_MESSAGE)),
        ),
    )

    op.create_table(
        USAGE_TABLE,
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", _UUID, nullable=False),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("ingestion_units_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrieval_calls_used", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("chatbot_id", "period_start", name=f"pk_{USAGE_TABLE}"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name=f"fk_{USAGE_TABLE}_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"],
            ["chatbot.id"],
            name=f"fk_{USAGE_TABLE}_chatbot_id_chatbot",
            ondelete="CASCADE",
        ),
        # A counter can only ever go up, and a negative one would mean the increment
        # statement had been asked to subtract — worth failing loudly rather than storing.
        sa.CheckConstraint("ingestion_units_used >= 0", name="ingestion_units_used"),
        sa.CheckConstraint("retrieval_calls_used >= 0", name="retrieval_calls_used"),
    )
    op.create_index(f"ix_{USAGE_TABLE}_org_id", USAGE_TABLE, ["org_id"])

    op.execute(f"ALTER TABLE {USAGE_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME} ON {USAGE_TABLE}
        USING (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {USAGE_TABLE}")
    op.drop_column("chatbot", "usage_cap_message")
    for column in CAP_COLUMNS:
        op.execute(f"ALTER TABLE chatbot DROP CONSTRAINT IF EXISTS ck_chatbot_{column}")
        op.drop_column("chatbot", column)
