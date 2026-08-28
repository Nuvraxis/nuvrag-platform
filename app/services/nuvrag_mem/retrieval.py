"""Reading back what a visitor told us on an earlier visit.

Pure vector search. No model is called here — the question has already been embedded for
document retrieval, and this reuses that same vector rather than paying for a second one.
That reuse is only sound because memory is embedded through the chatbot's own embedding
provider at its own locked width, which is exactly what the write path enforces.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import MemoryEntry
from app.repositories import (
    MemoryEntryRepository,
    RetrievedMemory,
    TicketRepository,
)


async def recall(
    session: AsyncSession,
    *,
    chatbot_id: UUID,
    subject_id: str,
    embedding: list[float],
    dimension: int,
) -> list[RetrievedMemory]:
    """What is worth telling the model about this visitor, or nothing.

    Takes the caller's session rather than opening its own, so the memory search and the
    document search share one read transaction, one connection and one snapshot.

    Gated on the visitor having a ticket, the same signal the write path uses. The gate is
    not what keeps other people's memories out — `chatbot_id` and `subject_id` do that, under
    RLS — it is what keeps this feature to the visitors it was scoped to.
    """
    config = settings.nuvrag_mem
    if not config.enabled:
        return []

    if not await TicketRepository(session).exists_for_session(chatbot_id, subject_id):
        return []

    return await MemoryEntryRepository(session).search(
        chatbot_id=chatbot_id,
        subject_id=subject_id,
        embedding=embedding,
        dimension=dimension,
        top_k=config.retrieval_top_k,
        min_similarity=config.retrieval_min_similarity,
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
