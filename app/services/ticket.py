from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.session import tenant_session
from app.models import (
    Conversation,
    Message,
    MessageRole,
    Ticket,
    TicketSource,
    TicketStatus,
    User,
)
from app.models.memory_entry import MemoryEntry
from app.repositories import (
    ConversationRepository,
    MessageRepository,
    TicketRepository,
    UserRepository,
)
from app.schemas.ticket import TicketCreate, TicketUpdate
from app.services.nuvrag_mem import forget_visitor_in, notes_for_subject

logger = get_logger(__name__)

# How much of a returning visitor's transcript bootstrap replays. Long enough to carry a
# conversation plus the reply it earned, bounded so a session id can never be turned into a
# request for an unbounded amount of work.
SESSION_REPLAY_LIMIT = 100

# Recorded on the ticket when the zero-chunk grounding-miss signal is what offered the
# escalation, rather than the visitor asking unprompted.
NO_GROUNDED_ANSWER = "no_grounded_answer"

# How many remembered notes the detail page carries. A visitor is capped at
# `NUVRAG_MEM_MAX_ENTRIES_PER_SUBJECT` rows, so this is a page rather than the lot — the total
# travels with it so the panel can say which it is showing.
MEMORY_PANEL_LIMIT = 50


@dataclass(frozen=True, slots=True)
class TicketView:
    """Everything the detail page renders, gathered in one read transaction.

    `notes` is deliberately not keyed by anything the caller could use to look the visitor up
    again: the subject id is their session id, which is a bearer capability, and it has no
    business in a dashboard response.
    """

    ticket: Ticket
    messages: list[Message]
    notes: list[MemoryEntry]
    notes_total: int


async def create_ticket(
    org_id: UUID, chatbot_id: UUID, payload: TicketCreate
) -> tuple[Ticket, Conversation]:
    """Open a ticket from the widget's contact form.

    The conversation comes first: a visitor who asks for a human before typing anything still
    gets a thread, because the ticket wraps a conversation rather than carrying its own.
    """
    async with tenant_session(org_id) as session:
        conversation_repo = ConversationRepository(session)
        conversation = await conversation_repo.get_by_session(chatbot_id, payload.session_id)
        if conversation is None:
            conversation = await conversation_repo.add(
                Conversation(
                    org_id=org_id,
                    chatbot_id=chatbot_id,
                    external_session_id=payload.session_id,
                )
            )

        subject = (payload.subject or "").strip() or _subject_from(conversation, payload)

        ticket = await TicketRepository(session).add(
            Ticket(
                org_id=org_id,
                chatbot_id=chatbot_id,
                conversation_id=conversation.id,
                visitor_email=str(payload.email).strip().lower(),
                visitor_name=(payload.name or "").strip() or None,
                subject=subject,
                source=payload.source,
                escalation_reason=payload.escalation_reason,
            )
        )

        # The visitor's own words go into the transcript as a normal visitor turn, so the
        # staff member reads one thread rather than a note bolted to the side of it.
        body = (payload.message or "").strip()
        if body:
            await MessageRepository(session).add(
                Message(
                    org_id=org_id,
                    conversation_id=conversation.id,
                    chatbot_id=chatbot_id,
                    role=MessageRole.USER,
                    content=body,
                )
            )
            conversation.message_count += 1
            if conversation.title is None:
                conversation.title = body[:300]
            session.add(conversation)

    logger.info(
        "ticket.created",
        org_id=str(org_id),
        ticket_id=str(ticket.id),
        chatbot_id=str(chatbot_id),
        source=str(payload.source),
    )
    return ticket, conversation


def _subject_from(conversation: Conversation, payload: TicketCreate) -> str | None:
    """A subject nobody typed, derived from what there is to derive it from."""
    body = (payload.message or "").strip()
    if body:
        return body[:300]
    if conversation.title:
        return conversation.title[:300]
    if payload.source == TicketSource.AI_ESCALATION:
        return "Escalated from chat"
    return None


async def list_tickets(
    org_id: UUID,
    *,
    chatbot_id: UUID | None = None,
    status: TicketStatus | None = None,
    assigned_to: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Ticket], int]:
    async with tenant_session(org_id, readonly=True) as session:
        repo = TicketRepository(session)
        items = await repo.list_for_org(
            org_id,
            chatbot_id=chatbot_id,
            status=status,
            assigned_to=assigned_to,
            limit=limit,
            offset=offset,
        )
        total = await repo.count_for_org(
            org_id, chatbot_id=chatbot_id, status=status, assigned_to=assigned_to
        )
    return items, total


async def get_ticket(org_id: UUID, ticket_id: UUID) -> TicketView:
    """The ticket, the conversation it wraps, and what the assistant remembers about whoever
    opened it.

    All three in one read transaction. The memory is looked up by the conversation's session
    id, which is the same `(chatbot_id, subject_id)` pair the chat path recalls on — a staff
    member reading the ticket sees the material the assistant had, not a second version of it.
    """
    async with tenant_session(org_id, readonly=True) as session:
        ticket = await _load(session, org_id, ticket_id)
        messages = await MessageRepository(session).list_for_conversation(
            ticket.conversation_id, limit=SESSION_REPLAY_LIMIT
        )

        conversation = await ConversationRepository(session).get(ticket.conversation_id)
        notes: list[MemoryEntry] = []
        notes_total = 0
        if conversation is not None:
            notes, notes_total = await notes_for_subject(
                session,
                chatbot_id=ticket.chatbot_id,
                subject_id=conversation.external_session_id,
                limit=MEMORY_PANEL_LIMIT,
            )

    return TicketView(ticket=ticket, messages=messages, notes=notes, notes_total=notes_total)


async def update_ticket(org_id: UUID, ticket_id: UUID, payload: TicketUpdate) -> Ticket:
    """Status, priority and assignment in one call, the shape the detail page PATCHes."""
    if (
        payload.status is None
        and payload.priority is None
        and payload.assigned_to is None
        and not payload.unassign
    ):
        raise ValidationError("Nothing to update")

    async with tenant_session(org_id) as session:
        ticket = await _load(session, org_id, ticket_id)

        if payload.unassign:
            ticket.assigned_to = None
        elif payload.assigned_to is not None:
            await _assign(session, org_id, ticket, payload.assigned_to)

        if payload.priority is not None:
            ticket.priority = payload.priority
        if payload.status is not None:
            _apply_status(ticket, payload.status)
        elif payload.assigned_to is not None and ticket.status == TicketStatus.OPEN:
            # Claiming an unclaimed ticket is what `pending` means, so the queue reflects the
            # work being picked up without anyone having to say so twice.
            ticket.status = TicketStatus.PENDING

        session.add(ticket)

    logger.info("ticket.updated", org_id=str(org_id), ticket_id=str(ticket_id))
    return ticket


async def assign_ticket(org_id: UUID, ticket_id: UUID, user_id: UUID) -> Ticket:
    return await update_ticket(org_id, ticket_id, TicketUpdate(assigned_to=user_id))


async def update_ticket_status(org_id: UUID, ticket_id: UUID, status: TicketStatus) -> Ticket:
    return await update_ticket(org_id, ticket_id, TicketUpdate(status=status))


async def reply_to_ticket(org_id: UUID, ticket_id: UUID, actor: User, content: str) -> Message:
    """Append a staff reply to the conversation the ticket wraps.

    The reply is a `Message` with `role='staff'`, so it renders in the widget's existing log
    and in the dashboard transcript without either learning a new shape.
    """
    body = content.strip()
    if not body:
        raise ValidationError("A reply cannot be empty")

    async with tenant_session(org_id) as session:
        ticket = await _load(session, org_id, ticket_id)

        message = await MessageRepository(session).add(
            Message(
                org_id=org_id,
                conversation_id=ticket.conversation_id,
                chatbot_id=ticket.chatbot_id,
                role=MessageRole.STAFF,
                content=body,
                staff_user_id=actor.id,
            )
        )

        conversation = await ConversationRepository(session).get(ticket.conversation_id)
        if conversation is not None:
            conversation.message_count += 1
            session.add(conversation)

        # Replying to something nobody had claimed is itself the act of claiming it. A
        # resolved or closed ticket is left where it is: reopening is a deliberate choice
        # someone makes with the status control, not a side effect of adding a note.
        if ticket.status == TicketStatus.OPEN:
            ticket.status = TicketStatus.PENDING
        if ticket.assigned_to is None:
            ticket.assigned_to = actor.id
        session.add(ticket)

    logger.info(
        "ticket.replied", org_id=str(org_id), ticket_id=str(ticket_id), user_id=str(actor.id)
    )
    return message


async def forget_ticket_visitor(org_id: UUID, ticket_id: UUID) -> int:
    """Erase everything remembered about whoever opened this ticket.

    Keyed on a ticket rather than on the subject itself, and that is deliberate. The subject
    *is* the visitor's session id, which since iteration 7 replays their transcript — putting
    it in a URL would write a bearer capability into ingress access logs, browser history and
    `Referer`, which is the leak iteration 7 removed. The dashboard is not given it either
    (see `MemoryNoteRead`), so it could not name one here even if the route asked for it.

    What gets erased is still the *person*, not the conversation: every note for that subject
    on that chatbot, whatever conversation each was learned in and whether or not that
    conversation still exists. The ticket only says who.
    """
    async with tenant_session(org_id) as session:
        ticket = await _load(session, org_id, ticket_id)
        conversation = await ConversationRepository(session).get(ticket.conversation_id)
        if conversation is None:
            return 0
        forgotten = await forget_visitor_in(
            session,
            chatbot_id=ticket.chatbot_id,
            subject_id=conversation.external_session_id,
        )

    logger.info(
        "nuvrag_mem.ticket_visitor_forgotten",
        org_id=str(org_id),
        ticket_id=str(ticket_id),
        deleted=forgotten,
    )
    return forgotten


async def session_state(
    org_id: UUID, chatbot_id: UUID, external_session_id: str
) -> tuple[Conversation, list[Message], TicketStatus | None] | None:
    """Everything bootstrap replays for a returning visitor, or None if there is nothing.

    Scoped by `chatbot_id` as well as the session id: the id identifies a conversation only
    within the chatbot whose public key authorised the call, never across tenants.
    """
    async with tenant_session(org_id, readonly=True) as session:
        conversation = await ConversationRepository(session).get_by_session(
            chatbot_id, external_session_id
        )
        if conversation is None:
            return None

        messages = await MessageRepository(session).list_for_conversation(
            conversation.id, limit=SESSION_REPLAY_LIMIT
        )
        ticket = await TicketRepository(session).latest_for_conversation(conversation.id)

    return conversation, messages, ticket.status if ticket else None


async def _load(session, org_id: UUID, ticket_id: UUID) -> Ticket:
    ticket = await TicketRepository(session).get(ticket_id)
    # The org check is belt to RLS's braces: "missing" and "someone else's" are deliberately
    # the same answer, so an id cannot be probed for existence across tenants.
    if ticket is None or ticket.org_id != org_id:
        raise NotFoundError(f"Ticket {ticket_id} not found")
    return ticket


async def _assign(session, org_id: UUID, ticket: Ticket, user_id: UUID) -> None:
    """Assignment has to prove the target is a colleague, not merely a valid UUID.

    Without this the FK alone would happily accept another organisation's user id and hand
    them a queue position in a tenant they have no part in.
    """
    member = await UserRepository(session).get(user_id)
    if member is None or member.org_id != org_id:
        raise ValidationError("That user is not a member of this organisation")
    ticket.assigned_to = member.id


def _apply_status(ticket: Ticket, status: TicketStatus) -> None:
    if status == TicketStatus.RESOLVED:
        ticket.resolved_at = utcnow()
    elif ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
        # Reopening drops the resolution stamp, so `resolved_at` always describes the state
        # the row is actually in rather than the last time it happened to be finished.
        ticket.resolved_at = None
    ticket.status = status


__all__ = [
    "MEMORY_PANEL_LIMIT",
    "NO_GROUNDED_ANSWER",
    "SESSION_REPLAY_LIMIT",
    "TicketView",
    "assign_ticket",
    "create_ticket",
    "forget_ticket_visitor",
    "get_ticket",
    "list_tickets",
    "reply_to_ticket",
    "session_state",
    "update_ticket",
    "update_ticket_status",
]
