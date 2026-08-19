"""Enable required Postgres extensions

Revision ID: 0001
Revises:
Create Date: 2026-08-10

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pgvector backs similarity search; pgcrypto supplies gen_random_uuid() on Postgres < 13.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")


def downgrade() -> None:
    # Extensions are left in place: dropping `vector` would cascade into any table that still
    # holds a vector column, which is never what a rollback intends.
    pass
