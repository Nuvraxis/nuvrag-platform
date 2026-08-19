"""Human takeover: tickets and staff replies

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-13

A ticket wraps an existing conversation rather than carrying a thread of its own, so the
only change to `message` is the two things a staff reply needs: `staff` as a permitted role,
and the author.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_GUC = "app.current_org_id"
POLICY_NAME = "tenant_isolation"

_UUID = postgresql.UUID(as_uuid=True)
_TS = sa.DateTime(timezone=True)

TICKET_STATUSES = ("open", "pending", "resolved", "closed")
TICKET_PRIORITIES = ("low", "normal", "high", "urgent")
TICKET_SOURCES = ("ai_escalation", "visitor_contact_form")

# Written as raw SQL rather than `op.create_check_constraint` for the same reason as
# migration 0004: that helper feeds the name back through the metadata naming convention,
# which would expand an already-expanded name into `ck_message_ck_message_role`.
MESSAGE_ROLE_CONSTRAINT = "ck_message_role"


def _enum_check(column: str, values: tuple[str, ...]) -> sa.CheckConstraint:
    """Enums are stored as checked VARCHAR; the naming convention expands `name`."""
    rendered = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({rendered})", name=column)


def _swap_message_role(values: str) -> None:
    op.execute(f"ALTER TABLE message DROP CONSTRAINT {MESSAGE_ROLE_CONSTRAINT}")
    op.execute(
        f"ALTER TABLE message ADD CONSTRAINT {MESSAGE_ROLE_CONSTRAINT} CHECK (role IN ({values}))"
    )


def upgrade() -> None:
    op.create_table(
        "ticket",
        sa.Column("created_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", _TS, server_default=sa.func.now(), nullable=False),
        sa.Column("org_id", _UUID, nullable=False),
        sa.Column("id", _UUID, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chatbot_id", _UUID, nullable=False),
        sa.Column("conversation_id", _UUID, nullable=False),
        sa.Column("visitor_email", sa.String(length=320), nullable=False),
        sa.Column("visitor_name", sa.String(length=200), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("escalation_reason", sa.String(length=100), nullable=True),
        sa.Column("assigned_to", _UUID, nullable=True),
        sa.Column("resolved_at", _TS, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ticket"),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.id"],
            name="fk_ticket_org_id_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chatbot_id"], ["chatbot.id"], name="fk_ticket_chatbot_id_chatbot", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.id"],
            name="fk_ticket_conversation_id_conversation",
            ondelete="CASCADE",
        ),
        # SET NULL rather than CASCADE: removing a staff member must not delete the tickets
        # they were holding, exactly as `document.uploaded_by` keeps their uploads.
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["app_user.id"],
            name="fk_ticket_assigned_to_app_user",
            ondelete="SET NULL",
        ),
        _enum_check("status", TICKET_STATUSES),
        _enum_check("priority", TICKET_PRIORITIES),
        _enum_check("source", TICKET_SOURCES),
    )
    op.create_index("ix_ticket_org_id", "ticket", ["org_id"])
    op.create_index("ix_ticket_chatbot_id", "ticket", ["chatbot_id"])
    # Not unique: a conversation can be escalated again after an earlier ticket is resolved.
    op.create_index("ix_ticket_conversation_id", "ticket", ["conversation_id"])
    op.create_index("ix_ticket_assigned_to", "ticket", ["assigned_to"])
    op.create_index("ix_ticket_org_id_status", "ticket", ["org_id", "status"])
    op.create_index("ix_ticket_chatbot_id_created_at", "ticket", ["chatbot_id", "created_at"])

    op.execute("ALTER TABLE ticket ENABLE ROW LEVEL SECURITY")
    # The same fail-closed predicate as every other tenant table: an unset GUC is NULL, so the
    # table reads as empty rather than as everyone's. These rows carry visitor email
    # addresses, so a leak here is a leak of someone else's customers.
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME} ON ticket
        USING (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)
        """
    )

    _swap_message_role("'user', 'assistant', 'staff'")
    op.add_column("message", sa.Column("staff_user_id", _UUID, nullable=True))
    op.create_foreign_key(
        "fk_message_staff_user_id_app_user",
        "message",
        "app_user",
        ["staff_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_message_staff_user_id", "message", ["staff_user_id"])


def downgrade() -> None:
    op.drop_index("ix_message_staff_user_id", table_name="message")
    op.drop_constraint("fk_message_staff_user_id_app_user", "message", type_="foreignkey")
    op.drop_column("message", "staff_user_id")
    # Staff replies would violate the narrower constraint. They are real transcript content
    # written by a human, so they are kept and reclassified as assistant turns — the role the
    # widget and the prompt builder already treat as "not the visitor".
    op.execute("UPDATE message SET role = 'assistant' WHERE role = 'staff'")
    _swap_message_role("'user', 'assistant'")

    op.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON ticket")
    op.drop_index("ix_ticket_chatbot_id_created_at", table_name="ticket")
    op.drop_index("ix_ticket_org_id_status", table_name="ticket")
    op.drop_index("ix_ticket_assigned_to", table_name="ticket")
    op.drop_index("ix_ticket_conversation_id", table_name="ticket")
    op.drop_index("ix_ticket_chatbot_id", table_name="ticket")
    op.drop_index("ix_ticket_org_id", table_name="ticket")
    op.drop_table("ticket")
