"""Reading back what a visitor told us on an earlier visit.

Pure vector search. No model is called here — the question has already been embedded for
document retrieval, and this reuses that same vector rather than paying for a second one.
That reuse is only sound because memory is embedded through the chatbot's own embedding
provider at its own locked width, which is exactly what the write path enforces.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories import MemoryEntryRepository, RetrievedMemory, TicketRepository


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
