from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentPrincipal, Pagination
from app.models import TicketStatus
from app.schemas.chat import MessageRead
from app.schemas.common import Page
from app.schemas.ticket import (
    MemoryNoteRead,
    TicketDetail,
    TicketRead,
    TicketReply,
    TicketUpdate,
    VisitorMemory,
)
from app.services import ticket as ticket_service

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("", response_model=Page[TicketRead])
async def list_tickets(
    principal: CurrentPrincipal,
    page: Pagination,
    chatbot_id: UUID | None = Query(default=None),
    status_filter: TicketStatus | None = Query(default=None, alias="status"),
    assigned_to: UUID | None = Query(default=None),
) -> Page[TicketRead]:
    """Readable by any member: the support queue is shared work, not privileged information."""
    items, total = await ticket_service.list_tickets(
        principal.org_id,
        chatbot_id=chatbot_id,
        status=status_filter,
        assigned_to=assigned_to,
        limit=page.limit,
        offset=page.offset,
    )
    return Page(
        items=[TicketRead.model_validate(item) for item in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: UUID, principal: CurrentPrincipal) -> TicketDetail:
    view = await ticket_service.get_ticket(principal.org_id, ticket_id)
    return TicketDetail(
        ticket=TicketRead.model_validate(view.ticket),
        messages=[MessageRead.model_validate(message) for message in view.messages],
        memory=VisitorMemory(
            notes=[MemoryNoteRead.model_validate(note) for note in view.notes],
            total=view.notes_total,
        ),
    )


@router.patch("/{ticket_id}", response_model=TicketRead)
async def update_ticket(
    ticket_id: UUID, payload: TicketUpdate, principal: CurrentPrincipal
) -> TicketRead:
    ticket = await ticket_service.update_ticket(principal.org_id, ticket_id, payload)
    return TicketRead.model_validate(ticket)


@router.post(
    "/{ticket_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED
)
async def reply_to_ticket(
    ticket_id: UUID, payload: TicketReply, principal: CurrentPrincipal
) -> MessageRead:
    """The reply lands in the conversation the ticket wraps, as `role='staff'`."""
    message = await ticket_service.reply_to_ticket(
        principal.org_id, ticket_id, principal.user, payload.content
    )
    return MessageRead.model_validate(message)
