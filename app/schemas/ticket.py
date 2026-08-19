from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import TicketPriority, TicketSource, TicketStatus
from app.schemas.chat import MessageRead, session_id_field


class TicketCreate(BaseModel):
    """What the widget's contact form posts.

    `conversation_id` is absent when the visitor asked for a human before saying anything, in
    which case the conversation is created from `session_id` the same way a first message
    would create it.
    """

    email: EmailStr
    name: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default=None, max_length=4000)
    subject: str | None = Field(default=None, max_length=300)
    session_id: str = session_id_field()
    source: TicketSource = TicketSource.VISITOR_CONTACT_FORM
    escalation_reason: str | None = Field(default=None, max_length=100)


class TicketCreated(BaseModel):
    """Deliberately thin.

    The widget needs to know the request landed and which conversation it belongs to; it has
    no business knowing who the ticket was routed to or what else is in the queue.
    """

    ticket_id: UUID
    conversation_id: UUID
    status: TicketStatus


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    chatbot_id: UUID
    conversation_id: UUID
    visitor_email: str
    visitor_name: str | None
    subject: str | None
    status: TicketStatus
    priority: TicketPriority
    source: TicketSource
    escalation_reason: str | None
    assigned_to: UUID | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TicketDetail(BaseModel):
    """A ticket plus the conversation it wraps, which is where the thread actually lives."""

    ticket: TicketRead
    messages: list[MessageRead]


class TicketUpdate(BaseModel):
    """Every field optional; `assigned_to` distinguishes "unassign" from "leave alone".

    Pydantic cannot tell an omitted nullable field from one explicitly set to null, so
    unassignment is its own flag rather than a null that would be indistinguishable from
    silence.
    """

    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assigned_to: UUID | None = None
    unassign: bool = False


class TicketReply(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
