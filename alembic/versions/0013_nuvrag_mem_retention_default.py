"""nuvrag_mem: drop the column default that contradicts a meaningful NULL

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-28

`chatbot.nuvrag_mem_retention_days` was given `DEFAULT 30` in 0012 so that chatbots which
already existed got a retention window rather than silently keeping visitor memory forever.
That was a one-time backfill, and the default should not have outlived it: NULL in this column
means "keep forever", so a non-NULL default states the opposite of what an explicit NULL is
trying to say.

It is worth being precise about what this migration does and does not fix. The bug found
during iteration 15 — a tenant clearing "Delete visitor memory after" while *creating* a
chatbot silently getting 30 days — was caused by the model's **Python-side** column default,
which SQLAlchemy applies whenever the value is None at insert time. Removing that is what
fixed it, and with it gone the ORM sends an explicit NULL which would override a server
default anyway. This migration changes no behaviour the application can currently reach.

It is here because the contradiction is a trap rather than a bug: the table description in psql would tell the
next person that new rows default to 30, a backfill or a psql insert would find that true, and
anything that reintroduced a client-side default would fail the same way again with nothing to
point at. `retention_days` next door has never had a default, and this column now matches it.
The invariant is asserted in `TestMemoryRetentionSetting`.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "chatbot"
COLUMN = "nuvrag_mem_retention_days"
# What 0012 set, restored on the way back down so a downgrade returns the schema it found.
BACKFILL_DEFAULT = "30"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} DROP DEFAULT")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN {COLUMN} SET DEFAULT {BACKFILL_DEFAULT}")
