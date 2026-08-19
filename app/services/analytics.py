from datetime import timedelta
from uuid import UUID

from app.core.security import utcnow
from app.db.session import tenant_session
from app.models import DocumentStatus, MessageRole
from app.repositories.analytics import AnalyticsRepository
from app.schemas.analytics import (
    ChatbotAnalytics,
    DailyActivityPoint,
    DocumentTotals,
    MessageTotals,
)

MIN_WINDOW_DAYS = 1
MAX_WINDOW_DAYS = 90


async def chatbot_analytics(org_id: UUID, chatbot_id: UUID, *, days: int) -> ChatbotAnalytics:
    window = max(MIN_WINDOW_DAYS, min(days, MAX_WINDOW_DAYS))
    # The series ends today, so a 30-day window starts 29 days ago, midnight UTC.
    since = (utcnow() - timedelta(days=window - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    async with tenant_session(org_id, readonly=True) as session:
        repo = AnalyticsRepository(session)
        usage = await repo.usage(chatbot_id)
        activity = await repo.daily_activity(chatbot_id, since=since)

    by_status = usage.documents_by_status
    by_role = usage.messages_by_role

    return ChatbotAnalytics(
        chatbot_id=chatbot_id,
        window_days=window,
        documents=DocumentTotals(
            pending=by_status.get(DocumentStatus.PENDING, 0),
            processing=by_status.get(DocumentStatus.PROCESSING, 0),
            ready=by_status.get(DocumentStatus.READY, 0),
            failed=by_status.get(DocumentStatus.FAILED, 0),
            total=usage.documents,
            chunks=usage.chunks,
        ),
        conversations=usage.conversations,
        messages=MessageTotals(
            user=by_role.get(MessageRole.USER, 0),
            assistant=by_role.get(MessageRole.ASSISTANT, 0),
            total=usage.messages,
            average_latency_ms=usage.average_latency_ms,
        ),
        daily=[
            DailyActivityPoint(
                day=point.day, conversations=point.conversations, messages=point.messages
            )
            for point in activity
        ],
    )
