"""Deleting visitor conversations, on request and on a schedule.

Two callers, one rule about tenancy. The dashboard's delete runs under `tenant_session`, so
RLS is what proves the conversation belongs to the caller. The scheduled sweep has no tenant
to run as, so it enumerates opted-in chatbots once under `system_session` and then re-enters
`tenant_session` per organisation to do the actual deleting — the privileged connection never
issues a DELETE. That split is the point: a bug in the age predicate can destroy one tenant's
history, but it cannot reach into another's.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.session import system_session, tenant_session
from app.repositories import ChatbotRepository, ConversationRepository
from app.services.nuvrag_mem import forget_visitor_in
from app.services.redis_client import held_lock

logger = get_logger(__name__)


async def delete_conversation(org_id: UUID, chatbot_id: UUID, conversation_id: UUID) -> None:
    """Remove one conversation and everything hanging off it.

    Messages and any tickets cascade at the database level. Unlike the scheduled sweep this
    does not step over an unresolved ticket: a human has asked for this specific transcript
    to go, which is how an erasure request arrives, and refusing would leave them no way to
    honour it.
    """
    async with tenant_session(org_id) as session:
        repo = ConversationRepository(session)
        conversation = await repo.get(conversation_id)
        # `chatbot_id` is checked rather than assumed: RLS proves the row is this tenant's,
        # not that it belongs to the chatbot named in the path.
        if conversation is None or conversation.chatbot_id != chatbot_id:
            raise NotFoundError(f"Conversation {conversation_id} not found")

        # Memory does not cascade — `source_conversation_id` is SET NULL precisely so that a
        # transcript ageing out is not silently an erasure. But this is not the sweep: someone
        # has asked for this transcript to go, and leaving behind a standing summary of the
        # person who wrote it would not honour that. Same transaction, so either both go or
        # neither does.
        forgotten = await forget_visitor_in(
            session, chatbot_id=chatbot_id, subject_id=conversation.external_session_id
        )
        await repo.delete(conversation)

    logger.info(
        "conversation.deleted",
        conversation_id=str(conversation_id),
        chatbot_id=str(chatbot_id),
        memory_forgotten=forgotten,
    )


@dataclass(slots=True)
class PurgeReport:
    """What one sweep did. Returned rather than only logged so the Celery result — and the
    tests — can assert on it."""

    chatbots_considered: int = 0
    conversations_deleted: int = 0
    # Chatbots still holding expired conversations when the per-chatbot batch ceiling was
    # reached. Never silently empty: a truncated sweep says so, here and in the log.
    incomplete: list[str] = field(default_factory=list)
    skipped_locked: bool = False


async def purge_expired_conversations() -> PurgeReport:
    """Delete conversations past their chatbot's `retention_days`.

    Returns immediately if another sweep holds the lock, which is what keeps a beat restart
    or an overrunning run from producing two passes over the same rows.
    """
    lock = held_lock(settings.retention.lock_key, ttl_seconds=settings.retention.lock_ttl_seconds)
    async with lock as acquired:
        if not acquired:
            logger.info("retention.sweep_already_running")
            return PurgeReport(skipped_locked=True)
        return await _sweep()


async def _sweep() -> PurgeReport:
    async with system_session() as session:
        targets = await ChatbotRepository(session).with_retention()

    report = PurgeReport(chatbots_considered=len(targets))
    if not targets:
        return report

    for org_id, chatbot_id, retention_days in targets:
        deleted, complete = await _purge_chatbot(org_id, chatbot_id, retention_days)
        report.conversations_deleted += deleted
        if not complete:
            report.incomplete.append(str(chatbot_id))

    logger.info(
        "retention.sweep_finished",
        chatbots_considered=report.chatbots_considered,
        conversations_deleted=report.conversations_deleted,
        incomplete=len(report.incomplete),
    )
    return report


async def _purge_chatbot(org_id: UUID, chatbot_id: UUID, retention_days: int) -> tuple[int, bool]:
    """Delete one chatbot's expired conversations in batches.

    Each batch is its own transaction. A single statement over a long-neglected chatbot would
    hold locks on rows the chat path is still writing to, and would roll the whole sweep back
    on one failure instead of keeping the work already done.
    """
    cutoff = utcnow() - timedelta(days=retention_days)
    config = settings.retention
    deleted = 0

    for _ in range(config.purge_max_batches_per_chatbot):
        async with tenant_session(org_id) as session:
            repo = ConversationRepository(session)
            expired = await repo.expired_ids(
                chatbot_id, cutoff=cutoff, limit=config.purge_batch_size
            )
            if not expired:
                return deleted, True
            deleted += await repo.delete_by_ids(expired)

        # Short of a full batch there is nothing left to find, so stop without paying for a
        # second query that would return empty.
        if len(expired) < config.purge_batch_size:
            return deleted, True

    logger.warning(
        "retention.batch_ceiling_reached",
        chatbot_id=str(chatbot_id),
        org_id=str(org_id),
        conversations_deleted=deleted,
    )
    return deleted, False
