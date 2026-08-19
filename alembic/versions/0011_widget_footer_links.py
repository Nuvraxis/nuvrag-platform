"""Widget footer links: privacy policy and terms

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-19

Their own columns rather than two more members of `theme_json`, because resetting the theme
empties that column and a tenant's privacy notice must not disappear with their colours.

Empty string rather than NULL for "no link", matching `description`: the dashboard clears a
field by sending an empty string, and a patch that dropped nulls would otherwise make the
setting one-way.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("privacy_url", "terms_url")


def upgrade() -> None:
    for column in COLUMNS:
        op.add_column(
            "chatbot",
            sa.Column(column, sa.String(length=500), nullable=False, server_default=""),
        )


def downgrade() -> None:
    for column in COLUMNS:
        op.drop_column("chatbot", column)
