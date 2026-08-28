from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import MemoryType, TicketPriority, TicketSource, TicketStatus
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


class MemoryNoteRead(BaseModel):
    """One remembered note, as the dashboard is allowed to see it.

    No `subject_id` and no `embedding`. The subject is the visitor's session id, which since
    iteration 7 replays their transcript — a bearer capability has no business travelling in a
    dashboard response, where it would reach browser history, error reports and screenshots.
    Staff already read the transcript through the ticket itself.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    memory_type: MemoryType
    created_at: datetime
    last_referenced_at: datetime


class VisitorMemory(BaseModel):
    """What is remembered about the person who opened a ticket.

    `total` is separate from `len(notes)` because the list is capped: a panel showing fifty of
    two hundred notes with no way to say so would understate what is held about someone.
    """

    notes: list[MemoryNoteRead]
    total: int


class TicketDetail(BaseModel):
    """A ticket plus the conversation it wraps, which is where the thread actually lives."""

    ticket: TicketRead
    messages: list[MessageRead]
    memory: VisitorMemory


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
