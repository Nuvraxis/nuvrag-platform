from uuid import UUID

from sqlmodel import select

from app.models import Chatbot, ChatbotStatus
from app.repositories.base import BaseRepository


class ChatbotRepository(BaseRepository[Chatbot]):
    model = Chatbot

    async def get_for_org(self, chatbot_id: UUID, org_id: UUID) -> Chatbot | None:
        result = await self.session.execute(
            select(Chatbot).where(Chatbot.id == chatbot_id, Chatbot.org_id == org_id)
        )
        return result.scalar_one_or_none()

    async def get_by_public_key(self, public_key: str) -> Chatbot | None:
        """Widget entry point. Runs unscoped by design: the key *is* the tenant lookup."""
        result = await self.session.execute(select(Chatbot).where(Chatbot.public_key == public_key))
        return result.scalar_one_or_none()

    async def with_retention(self) -> list[tuple[UUID, UUID, int]]:
        """`(org_id, chatbot_id, retention_days)` for every chatbot that has opted in.

        Unscoped by design, like `get_by_public_key`: the retention sweep is platform
        maintenance and there is no one tenant it could run as. What it reads is deliberately
        thin — two ids and a day count, no transcript content — and the deletes themselves go
        back through `tenant_session`, so a mistake in a predicate downstream still cannot
        reach across tenants.
        """
        result = await self.session.execute(
            select(Chatbot.org_id, Chatbot.id, Chatbot.retention_days)
            .where(Chatbot.retention_days.is_not(None))
            .order_by(Chatbot.org_id, Chatbot.id)
        )
        return [(org_id, chatbot_id, int(days)) for org_id, chatbot_id, days in result.all()]

    async def slug_exists(self, org_id: UUID, slug: str, *, exclude_id: UUID | None = None) -> bool:
        stmt = select(Chatbot.id).where(Chatbot.org_id == org_id, Chatbot.slug == slug)
        if exclude_id is not None:
            stmt = stmt.where(Chatbot.id != exclude_id)
        result = await self.session.execute(stmt.limit(1))
        return result.first() is not None

    async def list_for_org(
        self,
        org_id: UUID,
        *,
        status: ChatbotStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Chatbot]:
        stmt = select(Chatbot).where(Chatbot.org_id == org_id)
        if status is not None:
            stmt = stmt.where(Chatbot.status == status)
        stmt = stmt.order_by(Chatbot.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def with_nuvrag_mem_retention(self) -> list[tuple[UUID, UUID, int]]:
        """`(org_id, chatbot_id, nuvrag_mem_retention_days)` for every chatbot that keeps
        visitor memory for a bounded time.

        Unscoped for the same reason `with_retention` is, and just as thin: two ids and a day
        count, never any remembered content. The deletes themselves go back through
        `tenant_session`. Note that most chatbots appear here — memory ships with a 30-day
        window — whereas most are absent from `with_retention`, which starts at forever.
        """
        result = await self.session.execute(
            select(Chatbot.org_id, Chatbot.id, Chatbot.nuvrag_mem_retention_days)
            .where(Chatbot.nuvrag_mem_retention_days.is_not(None))
            .order_by(Chatbot.org_id, Chatbot.id)
        )
        return [(org_id, chatbot_id, int(days)) for org_id, chatbot_id, days in result.all()]
