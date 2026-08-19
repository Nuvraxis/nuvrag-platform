from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists
from sqlmodel import select

from app.models import Conversation, Message, Ticket, TicketStatus
from app.repositories.base import BaseRepository

# A ticket in either of these states is still someone's open piece of work, and the
# conversation is the whole of its content. Retention therefore steps over it rather than
# deleting a support request out from under the person handling it — resolve or close the
# ticket and the conversation ages out on the next sweep.
UNRESOLVED_TICKET_STATUSES = (TicketStatus.OPEN, TicketStatus.PENDING)


class ConversationRepository(BaseRepository[Conversation]):
    model = Conversation

    async def get_by_session(
        self, chatbot_id: UUID, external_session_id: str
    ) -> Conversation | None:
        result = await self.session.execute(
            select(Conversation).where(
                Conversation.chatbot_id == chatbot_id,
                Conversation.external_session_id == external_session_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_chatbot(
        self, chatbot_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[Conversation]:
        result = await self.session.execute(
            select(Conversation)
            .where(Conversation.chatbot_id == chatbot_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def expired_ids(self, chatbot_id: UUID, *, cutoff: datetime, limit: int) -> list[UUID]:
        """Conversations idle since `cutoff` that no unresolved ticket is holding open.

        `updated_at` rather than `created_at`: a thread still being added to has not aged,
        and cutting a live conversation off mid-way is the behaviour that would surprise
        someone. Oldest first, so a backlog drains in the order it accumulated.
        """
        pinned = (
            select(Ticket.id)
            .where(Ticket.conversation_id == Conversation.id)
            .where(Ticket.status.in_(UNRESOLVED_TICKET_STATUSES))
        )
        result = await self.session.execute(
            select(Conversation.id)
            .where(Conversation.chatbot_id == chatbot_id)
            .where(Conversation.updated_at < cutoff)
            .where(~exists(pinned))
            .order_by(Conversation.updated_at)
            .limit(limit)
        )
        return list(result.scalars())

    async def delete_by_ids(self, conversation_ids: Sequence[UUID]) -> int:
        """Bulk delete. Messages and tickets follow through their `ON DELETE CASCADE`
        foreign keys, which Postgres enforces as the table owner and which therefore works
        the same under RLS as without it."""
        if not conversation_ids:
            return 0
        result = await self.session.execute(
            delete(Conversation).where(Conversation.id.in_(conversation_ids))
        )
        return int(result.rowcount or 0)


class MessageRepository(BaseRepository[Message]):
    model = Message

    async def list_for_conversation(
        self, conversation_id: UUID, *, limit: int = 100, offset: int = 0
    ) -> list[Message]:
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars())

    async def recent_history(self, conversation_id: UUID, *, window: int) -> list[Message]:
        """Newest `window` messages, returned oldest-first for prompt assembly."""
        result = await self.session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(window)
        )
        return list(reversed(list(result.scalars())))
