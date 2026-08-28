"""Forgetting a visitor, on request and on a schedule.

Two callers with deliberately different manners. An erasure request is unconditional: it does
not care whether a ticket is open, whether the transcript still exists, or which conversation
each note came from. The sweep is careful: it ages notes individually and steps over anyone
whose ticket is still being worked on.

That asymmetry is the same one `delete_conversation` already has against the conversation
sweep, and it exists for the same reason. A request from a person has to be honourable when it
arrives; a schedule has all the time in the world to be cautious.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import session_log_id, utcnow
from app.db.session import system_session, tenant_session
from app.repositories import ChatbotRepository, MemoryEntryRepository
from app.services.redis_client import held_lock

logger = get_logger(__name__)


async def forget_visitor_in(session: AsyncSession, *, chatbot_id: UUID, subject_id: str) -> int:
    """Erase inside a transaction the caller already owns.

    Used by the conversation-delete path so that erasing a transcript and erasing what was
    learned from it either both happen or neither does.
    """
    return await MemoryEntryRepository(session).delete_for_subject(chatbot_id, subject_id)


async def forget_visitor(org_id: UUID, chatbot_id: UUID, subject_id: str) -> int:
    """Erase every note about one visitor on one chatbot.

    Independent of conversation state by design. A visitor can hold notes learned in a
    conversation that has since been swept — that is exactly what `source_conversation_id
    ON DELETE SET NULL` is for — so an erasure keyed on a transcript could not promise to have
    removed everything. This is keyed on the person.
    """
    async with tenant_session(org_id) as session:
        deleted = await forget_visitor_in(session, chatbot_id=chatbot_id, subject_id=subject_id)

    logger.info(
        "nuvrag_mem.visitor_forgotten",
        org_id=str(org_id),
        chatbot_id=str(chatbot_id),
        session=session_log_id(subject_id),
        deleted=deleted,
    )
    return deleted


@dataclass(slots=True)
class MemoryPurgeReport:
    """What one sweep did. Returned rather than only logged so the Celery result — and the
    tests — can assert on it."""

    chatbots_considered: int = 0
    entries_deleted: int = 0
    # Chatbots still holding expired notes when the per-chatbot ceiling was reached. Never
    # silently empty: a truncated sweep says so, here and in the log.
    incomplete: list[str] = field(default_factory=list)
    skipped_locked: bool = False


async def purge_expired_memory() -> MemoryPurgeReport:
    """Delete notes past their chatbot's `nuvrag_mem_retention_days`.

    Its own lock key, never the conversation sweep's. One key for two sweeps would let
    whichever ran first make the other a no-op for the rest of the window, and the failure
    would look exactly like a sweep that had nothing to do.
    """
    config = settings.nuvrag_mem
    async with held_lock(config.lock_key, ttl_seconds=config.lock_ttl_seconds) as acquired:
        if not acquired:
            logger.info("nuvrag_mem.sweep_already_running")
            return MemoryPurgeReport(skipped_locked=True)
        return await _sweep()


async def _sweep() -> MemoryPurgeReport:
    # One unscoped read to find the work, then per-tenant sessions to do it. The privileged
    # connection never issues a DELETE, so a mistake in the age predicate can cost one tenant
    # their notes but cannot reach into another's.
    async with system_session() as session:
        targets = await ChatbotRepository(session).with_nuvrag_mem_retention()

    report = MemoryPurgeReport(chatbots_considered=len(targets))
    if not targets:
        return report

    for org_id, chatbot_id, retention_days in targets:
        deleted, complete = await _purge_chatbot(org_id, chatbot_id, retention_days)
        report.entries_deleted += deleted
        if not complete:
            report.incomplete.append(str(chatbot_id))

    logger.info(
        "nuvrag_mem.sweep_finished",
        chatbots_considered=report.chatbots_considered,
        entries_deleted=report.entries_deleted,
        incomplete=len(report.incomplete),
    )
    return report


async def _purge_chatbot(org_id: UUID, chatbot_id: UUID, retention_days: int) -> tuple[int, bool]:
    """Delete one chatbot's expired notes in batches.

    Each batch is its own transaction, for the reason the conversation sweep gives: a single
    statement over a long-neglected chatbot would hold locks on rows the chat path is still
    reading, and would roll back the whole sweep on one failure instead of keeping the work
    already done.
    """
    cutoff = utcnow() - timedelta(days=retention_days)
    config = settings.nuvrag_mem
    deleted = 0

    for _ in range(config.purge_max_batches_per_chatbot):
        async with tenant_session(org_id) as session:
            repo = MemoryEntryRepository(session)
            expired = await repo.expired_ids(
                chatbot_id, cutoff=cutoff, limit=config.purge_batch_size
            )
            if not expired:
                return deleted, True
            deleted += await repo.delete_by_ids(expired)

        # Short of a full batch there is nothing left to find, so stop rather than paying for
        # a second query that would come back empty.
        if len(expired) < config.purge_batch_size:
            return deleted, True

    logger.warning(
        "nuvrag_mem.batch_ceiling_reached",
        chatbot_id=str(chatbot_id),
        org_id=str(org_id),
        entries_deleted=deleted,
    )
    return deleted, False
