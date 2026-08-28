from uuid import UUID

from sqlalchemy import exists
from sqlmodel import func, select

from app.models import Ticket, TicketStatus
from app.repositories.base import BaseRepository


class TicketRepository(BaseRepository[Ticket]):
    model = Ticket

    def _filtered(self, statement, *, chatbot_id, status, assigned_to):
        """The three list filters, applied identically to the page and to its count.

        Sharing them is what stops the total disagreeing with the rows beneath it.
        """
        if chatbot_id is not None:
            statement = statement.where(Ticket.chatbot_id == chatbot_id)
        if status is not None:
            statement = statement.where(Ticket.status == status)
        if assigned_to is not None:
            statement = statement.where(Ticket.assigned_to == assigned_to)
        return statement

    async def list_for_org(
        self,
        org_id: UUID,
        *,
        chatbot_id: UUID | None = None,
        status: TicketStatus | None = None,
        assigned_to: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Ticket]:
        statement = self._filtered(
            select(Ticket).where(Ticket.org_id == org_id),
            chatbot_id=chatbot_id,
            status=status,
            assigned_to=assigned_to,
        )
        result = await self.session.execute(
            statement.order_by(Ticket.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars())

    async def count_for_org(
        self,
        org_id: UUID,
        *,
        chatbot_id: UUID | None = None,
        status: TicketStatus | None = None,
        assigned_to: UUID | None = None,
    ) -> int:
        statement = self._filtered(
            select(func.count()).select_from(Ticket).where(Ticket.org_id == org_id),
            chatbot_id=chatbot_id,
            status=status,
            assigned_to=assigned_to,
        )
        result = await self.session.execute(statement)
        return int(result.scalar_one())

    async def exists_for_conversation(self, conversation_id: UUID) -> bool:
        """Whether this conversation has ever been escalated to a human.

        The one signal that says a visitor is durable. Opening a ticket is what promotes their
        session id from `sessionStorage` to `localStorage` (iteration 7), so a visitor with a
        ticket is the only kind this platform can recognise on a later visit — which makes
        this, rather than a flag of its own, the gate on writing and reading their memory.

        `EXISTS` rather than `latest_for_conversation`: the answer is a yes or a no, and the
        newest ticket's columns are not wanted for it.
        """
        result = await self.session.execute(
            select(exists(select(Ticket.id).where(Ticket.conversation_id == conversation_id)))
        )
        return bool(result.scalar())

    async def latest_for_conversation(self, conversation_id: UUID) -> Ticket | None:
        """The ticket a returning visitor is waiting on.

        A conversation can be escalated more than once, so "the ticket" is the newest one.
        """
        result = await self.session.execute(
            select(Ticket)
            .where(Ticket.conversation_id == conversation_id)
            .order_by(Ticket.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()
