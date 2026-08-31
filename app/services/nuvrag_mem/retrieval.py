"""Reading back what a visitor told us on an earlier visit.

Vector search, and on all but one turn per chatbot no model is called here — the question has
already been embedded for document retrieval, and this reuses that same vector rather than
paying for a second one. That reuse is only sound because memory is embedded through the
chatbot's own embedding provider at its own locked width, which is exactly what the write path
enforces.

The exception is the first recall for a chatbot with no similarity floor recorded, which
embeds the fixed calibration set once through that same provider. See `calibration`.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models import MemoryEntry
from app.repositories import (
    MemoryEntryRepository,
    RetrievedMemory,
    TicketRepository,
)
from app.services.ai.base import EmbeddingProvider
from app.services.nuvrag_mem.calibration import CalibrationState, calibrate

logger = get_logger(__name__)


async def recall(
    session: AsyncSession,
    *,
    org_id: UUID,
    chatbot_id: UUID,
    subject_id: str,
    embedding: list[float],
    dimension: int,
    state: CalibrationState,
    embedder: EmbeddingProvider,
) -> list[RetrievedMemory]:
    """What is worth telling the model about this visitor, or nothing.

    Takes the caller's session rather than opening its own, so the memory search and the
    document search share one read transaction, one connection and one snapshot.

    Gated on the visitor having a ticket, the same signal the write path uses. The gate is
    not what keeps other people's memories out — `chatbot_id` and `subject_id` do that, under
    RLS — it is what keeps this feature to the visitors it was scoped to.

    The similarity floor comes from `state`, and calibration happens here rather than earlier
    because here is where it is known to be needed: the ticket gate has already turned away
    every visitor who has nothing to recall, and calibrating for them would embed a fixed
    set of sentences through a provider on behalf of a chatbot that may never use memory at
    all.
    """
    config = settings.nuvrag_mem
    if not config.enabled:
        return []

    if not await TicketRepository(session).exists_for_session(chatbot_id, subject_id):
        return []

    floor = state.effective
    if floor is None:
        floor = await calibrate(org_id, chatbot_id, embedder=embedder)
    if floor is None:
        # Calibration could not be taken, and there is deliberately no default to fall back
        # on — a shared constant is the bug this whole mechanism replaces. Skipping recall
        # for one turn costs the visitor some context; guessing a floor costs them the
        # assistant asserting something untrue about them. The column stays NULL, so the
        # next message tries again.
        logger.info("nuvrag_mem.recall_skipped_uncalibrated", chatbot_id=str(chatbot_id))
        return []

    return await MemoryEntryRepository(session).search(
        chatbot_id=chatbot_id,
        subject_id=subject_id,
        embedding=embedding,
        dimension=dimension,
        top_k=config.retrieval_top_k,
        min_similarity=floor,
    )


async def notes_for_subject(
    session: AsyncSession, *, chatbot_id: UUID, subject_id: str, limit: int
) -> tuple[list[MemoryEntry], int]:
    """What is remembered about one visitor, and how much of it there is.

    For the dashboard rather than for a prompt, so there is no similarity floor and no ticket
    gate: a staff member reading a ticket is entitled to see what the assistant was working
    from, including notes too weak to have been recalled for any particular question. The
    tenant scoping is the same as everywhere else — RLS, plus `chatbot_id` in the predicate.

    The count is returned alongside because the list is capped: a panel that silently showed
    the first fifty of two hundred would misrepresent what is held about a person.
    """
    repo = MemoryEntryRepository(session)
    return (
        await repo.list_for_subject(chatbot_id, subject_id, limit=limit),
        await repo.count_for_subject(chatbot_id, subject_id),
    )
