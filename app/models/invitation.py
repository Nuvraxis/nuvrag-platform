from datetime import datetime
from uuid import UUID

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

from app.models.base import (
    UTC_TIMESTAMP,
    OrgScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    enum_column,
)
from app.models.enums import InvitationStatus, UserRole


class Invitation(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    """A pending offer to join an organisation.

    Only the hash of the invitation token is stored. The plaintext exists once, in the
    response that created it, and travels to the invitee out of band — so a leaked database
    does not hand an attacker a set of working join links.
    """

    __tablename__ = "invitation"
    __table_args__ = (
        # Partial rather than plain unique: one *live* invitation per address, while any
        # number of accepted or revoked rows stay behind as the audit trail.
        Index(
            "uq_invitation_org_id_email_pending",
            "org_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_invitation_org_id_status", "org_id", "status"),
        enum_check("role", UserRole),
        enum_check("status", InvitationStatus),
    )

    email: str = Field(max_length=320, index=True, nullable=False)
    role: UserRole = Field(
        default=UserRole.MEMBER, sa_type=enum_column(UserRole, name="role"), nullable=False
    )
    token_hash: str = Field(max_length=64, unique=True, index=True, nullable=False)
    status: InvitationStatus = Field(
        default=InvitationStatus.PENDING,
        sa_type=enum_column(InvitationStatus, name="status"),
        nullable=False,
    )
    expires_at: datetime = Field(sa_type=UTC_TIMESTAMP, nullable=False)
    invited_by: UUID | None = Field(default=None, foreign_key="app_user.id", ondelete="SET NULL")
    accepted_at: datetime | None = Field(default=None, sa_type=UTC_TIMESTAMP)
