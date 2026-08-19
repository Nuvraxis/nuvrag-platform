from datetime import datetime
from uuid import UUID

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.models.base import (
    UTC_TIMESTAMP,
    OrgScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    enum_check,
    enum_column,
)
from app.models.enums import TicketPriority, TicketSource, TicketStatus


class Ticket(UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SQLModel, table=True):
    """A human takeover of one conversation.

    Deliberately thin: the thread itself stays in `conversation` / `message`, and a staff
    reply is a `Message` with `role='staff'`. A parallel message table would duplicate
    history, citations and the transcript UI that all already exist.
    """

    __tablename__ = "ticket"
    __table_args__ = (
        Index("ix_ticket_org_id_status", "org_id", "status"),
        Index("ix_ticket_chatbot_id_created_at", "chatbot_id", "created_at"),
        enum_check("status", TicketStatus),
        enum_check("priority", TicketPriority),
        enum_check("source", TicketSource),
    )

    chatbot_id: UUID = Field(
        foreign_key="chatbot.id", ondelete="CASCADE", index=True, nullable=False
    )
    # Not unique: one conversation can be escalated more than once over its life — resolved
    # in March, stuck again in June — and each escalation is its own piece of work.
    conversation_id: UUID = Field(
        foreign_key="conversation.id", ondelete="CASCADE", index=True, nullable=False
    )
    # The one piece of PII the visitor is asked for, and only so a human can reach them if
    # they have closed the tab by the time someone replies. Nothing is sent to it
    # automatically — the platform has no outbound mail transport.
    visitor_email: str = Field(max_length=320, nullable=False)
    visitor_name: str | None = Field(default=None, max_length=200)
    subject: str | None = Field(default=None, max_length=300)
    status: TicketStatus = Field(
        default=TicketStatus.OPEN,
        sa_type=enum_column(TicketStatus, name="status"),
        nullable=False,
    )
    priority: TicketPriority = Field(
        default=TicketPriority.NORMAL,
        sa_type=enum_column(TicketPriority, name="priority"),
        nullable=False,
    )
    source: TicketSource = Field(sa_type=enum_column(TicketSource, name="source"), nullable=False)
    # e.g. "no_grounded_answer" when the zero-chunk signal is what offered the escalation.
    escalation_reason: str | None = Field(default=None, max_length=100)
    # Nullable reference for the same reason as `document.uploaded_by`: removing a colleague
    # must not destroy the queue they were working.
    assigned_to: UUID | None = Field(
        default=None, foreign_key="app_user.id", ondelete="SET NULL", index=True
    )
    resolved_at: datetime | None = Field(default=None, sa_type=UTC_TIMESTAMP)
