"""Per-chatbot conversation retention

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-19

Adds `chatbot.retention_days`. Nullable, and null means "keep forever" — so every existing
row keeps the behaviour it had, and no tenant's history starts disappearing because a
migration ran.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors `RETENTION_CHECK` in app/models/chatbot.py. Written out rather than imported: a
# migration has to keep describing the schema it produced even after the model moves on.
CONSTRAINT_NAME = "ck_chatbot_retention_days"
CONSTRAINT_SQL = "retention_days IS NULL OR retention_days BETWEEN 1 AND 3650"


def upgrade() -> None:
    op.add_column("chatbot", sa.Column("retention_days", sa.Integer(), nullable=True))
    # Raw SQL rather than `op.create_check_constraint`, for the same reason as migrations
    # 0004 and 0009: that helper feeds the name back through the metadata naming convention,
    # which would expand an already-expanded name into `ck_chatbot_ck_chatbot_retention_days`.
    op.execute(f"ALTER TABLE chatbot ADD CONSTRAINT {CONSTRAINT_NAME} CHECK ({CONSTRAINT_SQL})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE chatbot DROP CONSTRAINT {CONSTRAINT_NAME}")
    op.drop_column("chatbot", "retention_days")
