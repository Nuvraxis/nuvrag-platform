from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, func, select

from app.core.security import utcnow
from app.models import Conversation, Document, Message, MessageRole


@dataclass(frozen=True, slots=True)
class DailyActivity:
    day: date
    conversations: int
    messages: int


@dataclass(slots=True)
class ChatbotUsage:
    documents_by_status: dict[str, int] = field(default_factory=dict)
    chunks: int = 0
    conversations: int = 0
    messages_by_role: dict[str, int] = field(default_factory=dict)
    average_latency_ms: int | None = None

    @property
    def documents(self) -> int:
        return sum(self.documents_by_status.values())

    @property
    def messages(self) -> int:
        return sum(self.messages_by_role.values())


class AnalyticsRepository:
    """Read-only aggregates behind the dashboard overview.

    Every query is scoped by `chatbot_id`, which the ingestion and chat paths already index,
    so none of this needs an index of its own.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def usage(self, chatbot_id: UUID) -> ChatbotUsage:
        usage = ChatbotUsage()

        documents = await self.session.execute(
            select(Document.status, func.count(), func.coalesce(func.sum(Document.chunk_count), 0))
            .where(Document.chatbot_id == chatbot_id)
            .group_by(Document.status)
        )
        for status, count, chunks in documents.all():
            usage.documents_by_status[str(status)] = int(count)
            usage.chunks += int(chunks)

        conversations = await self.session.execute(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.chatbot_id == chatbot_id)
        )
        usage.conversations = int(conversations.scalar_one())

        messages = await self.session.execute(
            select(Message.role, func.count(), func.avg(Message.latency_ms))
            .where(Message.chatbot_id == chatbot_id)
            .group_by(Message.role)
        )
        for role, count, latency in messages.all():
            usage.messages_by_role[str(role)] = int(count)
            # Only assistant rows carry a latency, so the average is read from that group
            # rather than across all messages, where NULL user rows make it ambiguous.
            if str(role) == MessageRole.ASSISTANT and latency is not None:
                usage.average_latency_ms = int(latency)

        return usage

    async def daily_activity(self, chatbot_id: UUID, *, since: datetime) -> list[DailyActivity]:
        """Conversations started and messages sent per UTC day, empty days included.

        The two tables are counted separately and stitched together here. One SQL statement
        would need a lateral join per day or a full outer join against a generated series —
        both slower and harder to read than two indexed group-bys over a bounded window.
        """
        conversations = await self._count_by_day(
            Conversation, Conversation.chatbot_id == chatbot_id, since=since
        )
        messages = await self._count_by_day(Message, Message.chatbot_id == chatbot_id, since=since)

        return [
            DailyActivity(
                day=day,
                conversations=conversations.get(day, 0),
                messages=messages.get(day, 0),
            )
            for day in _days_between(since.date(), utcnow().date())
        ]

    async def _count_by_day(
        self, model: type[SQLModel], predicate: ColumnElement[bool], *, since: datetime
    ) -> dict[date, int]:
        bucket = func.date_trunc("day", model.created_at).label("day")
        result = await self.session.execute(
            select(bucket, func.count())
            .where(predicate, model.created_at >= since)
            .group_by(bucket)
        )
        return {row[0].date(): int(row[1]) for row in result.all()}


def _days_between(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
