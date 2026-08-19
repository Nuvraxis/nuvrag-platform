"""Allow .mdx documents

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-10

File types are stored as VARCHAR with a CHECK constraint rather than a native enum, so
widening the set is a constraint swap instead of an ALTER TYPE that cannot run inside a
transaction.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written as raw SQL rather than `op.create_check_constraint`: that helper feeds the name
# back through the metadata naming convention, which would expand an already-expanded name
# into `ck_document_ck_document_file_type`.
CONSTRAINT = "ck_document_file_type"


def _swap(values: str) -> None:
    op.execute(f"ALTER TABLE document DROP CONSTRAINT {CONSTRAINT}")
    op.execute(f"ALTER TABLE document ADD CONSTRAINT {CONSTRAINT} CHECK (file_type IN ({values}))")


def upgrade() -> None:
    _swap("'pdf', 'docx', 'md', 'mdx', 'txt'")


def downgrade() -> None:
    # Rows written while mdx was allowed would violate the narrower constraint, so they are
    # reclassified as markdown — which mdx is a superset of, and which the existing extractor
    # handles without complaint.
    op.execute("UPDATE document SET file_type = 'md' WHERE file_type = 'mdx'")
    _swap("'pdf', 'docx', 'md', 'txt'")
