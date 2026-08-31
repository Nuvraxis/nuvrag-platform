"""`POST /api/v1/search`: retrieval on its own, without a conversation around it.

The chat path retrieves in order to answer. This returns what it found and stops — no
generation, no transcript, no memory. It is the same engine either way; what differs is that
here hybrid search is unconditional, because there is no existing behaviour to preserve.
"""

from app.core.config import settings
from app.core.exceptions import UsageCapExceededError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models import Chatbot
from app.schemas.search import SearchHit, SearchRequest, SearchResponse
from app.services.ai import factory
from app.services.retrieval import FusedMatch, hybrid_search, rerank
from app.services.usage import UsageKind, consume

logger = get_logger(__name__)


def _hit(item: FusedMatch) -> SearchHit:
    chunk = item.chunk_match.chunk
    return SearchHit(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        content=chunk.content,
        metadata=chunk.metadata_json or {},
        score=round(item.score, 6),
        # None rather than 0.0 when the vector half never ranked this chunk: no cosine was
        # computed for it, which is a different statement from one that came out near zero.
        similarity=round(item.similarity, 6) if item.vector_rank is not None else None,
        lexical_score=round(item.lexical_score, 6) if item.lexical_score is not None else None,
        vector_rank=item.vector_rank,
        lexical_rank=item.lexical_rank,
    )


async def search(chatbot: Chatbot, payload: SearchRequest) -> SearchResponse:
    """One retrieval round, charged as one.

    Charged through iteration 16's counter at the same weight a chat turn costs, because it
    spends the same thing: one embedding call over the tenant's own provider. Reserved before
    the embedding call for the same reason the chat path does it there — a cap that let the
    spend through and refused afterwards would not be a cap.
    """
    spend = await consume(
        chatbot.org_id,
        chatbot.id,
        kind=UsageKind.RETRIEVAL,
        amount=1,
        cap=chatbot.monthly_retrieval_call_cap,
    )
    if not spend.allowed:
        raise UsageCapExceededError(
            "This chatbot has reached its monthly retrieval limit. It resets at the start of "
            "next month, or an administrator can raise the limit.",
            kind=str(UsageKind.RETRIEVAL),
            used=spend.used,
            cap=spend.cap,
        )

    embedder = await factory.get_embedding_provider(chatbot.org_id, chatbot.id)
    if embedder.dimension is None:
        # Nothing has ever been embedded for this chatbot, so there is nothing at any width to
        # search and no reason to pay to embed the query. An empty result is the honest answer.
        return SearchResponse(query=payload.query, hits=[], grounded=False, reranked=False)

    query_vector = (await embedder.embed_batch([payload.query]))[0]

    async with tenant_session(chatbot.org_id, readonly=True) as session:
        result = await hybrid_search(
            session,
            chatbot_id=chatbot.id,
            question=payload.query,
            embedding=query_vector,
            dimension=embedder.dimension,
            top_k=payload.top_k,
            ef_search=settings.retrieval.hnsw_ef_search,
        )

    fused, reranked = result.fused, False
    if payload.rerank and fused:
        fused, reranked = await _reranked(chatbot, payload.query, fused)

    logger.info(
        "search.completed",
        chatbot_id=str(chatbot.id),
        hits=len(fused),
        grounded=result.grounded,
        reranked=reranked,
    )
    return SearchResponse(
        query=payload.query,
        hits=[_hit(item) for item in fused],
        grounded=result.grounded,
        reranked=reranked,
    )


async def _reranked(
    chatbot: Chatbot, query: str, fused: list[FusedMatch]
) -> tuple[list[FusedMatch], bool]:
    """Reranking is best-effort here in a second way the chat path is not.

    A chatbot may have no usable chat provider at all — configured for embeddings only, or
    holding a credential that no longer works — and a search request is still perfectly
    answerable without one. So a provider that cannot even be built falls back to the fused
    order rather than failing a request that has already retrieved successfully.
    """
    try:
        chat = await factory.get_chat_provider(
            chatbot.org_id, chatbot.id, chatbot.model_config_json
        )
    except Exception as exc:  # noqa: BLE001 - no chat provider is a fallback, not an error
        logger.info(
            "search.rerank_unavailable",
            chatbot_id=str(chatbot.id),
            error_type=type(exc).__name__,
        )
        return fused, False

    return await rerank(chat, question=query, fused=fused)
