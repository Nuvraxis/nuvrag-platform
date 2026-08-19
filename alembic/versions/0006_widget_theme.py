"""Per-chatbot widget theme

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing rows get `{}`, which the widget reads as "use the stylesheet's own defaults" —
    # so no chatbot changes appearance because this column arrived.
    op.add_column(
        "chatbot",
        sa.Column(
            "theme_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("chatbot", "theme_json")
