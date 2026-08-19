"""Team invitations

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "app.current_org_id"
POLICY_NAME = "tenant_isolation"


def _enum_check(column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    """Enums are stored as checked VARCHAR; the naming convention expands `name`."""
    rendered = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({rendered})", name=column)


def upgrade() -> None:
    op.create_table(
        "invitation",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _enum_check("role", ("owner", "admin", "member")),
        _enum_check("status", ("pending", "accepted", "revoked")),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by"], ["app_user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invitation_org_id", "invitation", ["org_id"])
    op.create_index("ix_invitation_email", "invitation", ["email"])
    op.create_index("ix_invitation_token_hash", "invitation", ["token_hash"], unique=True)
    op.create_index("ix_invitation_org_id_status", "invitation", ["org_id", "status"])
    # Partial rather than plain unique: one *live* invitation per address, while accepted and
    # revoked rows accumulate freely as the audit trail.
    op.create_index(
        "uq_invitation_org_id_email_pending",
        "invitation",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.execute("ALTER TABLE invitation ENABLE ROW LEVEL SECURITY")
    # Same fail-closed predicate as every other tenant table: an unset GUC is NULL, so the
    # table reads as empty rather than as everyone's.
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME} ON invitation
        USING (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON invitation")
    op.drop_index("uq_invitation_org_id_email_pending", table_name="invitation")
    op.drop_index("ix_invitation_org_id_status", table_name="invitation")
    op.drop_index("ix_invitation_token_hash", table_name="invitation")
    op.drop_index("ix_invitation_email", table_name="invitation")
    op.drop_index("ix_invitation_org_id", table_name="invitation")
    op.drop_table("invitation")
