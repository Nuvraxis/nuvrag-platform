import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.exceptions import UpstreamServiceError
from app.core.logging import get_logger
from app.core.security import hash_api_key
from app.db.session import tenant_session
from app.models import Conversation, Message, MessageRole
from app.repositories import (
    ConversationRepository,
    DocumentChunkRepository,
    MessageRepository,
    RetrievedChunk,
    TicketRepository,
)
from app.services.ai import factory
from app.services.ai.prompts import Citation, build_chat_messages, build_citations

logger = get_logger(__name__)

# How much of the session digest reaches a log line. Enough to correlate one visitor's turns
# with each other; far too little to reconstruct the value it came from.
_SESSION_LOG_ID_CHARS = 12


def session_log_id(external_session_id: str) -> str:
    """A correlator for logs, never the session id itself.

    Since iteration 7 the session id also replays a conversation's transcript, which makes it
    a bearer capability rather than a label — and a capability does not belong in a log line
    that ships to an aggregator and outlives the session by months. A truncated digest
    correlates the turns of one conversation exactly as well and grants nothing.
    """
    return hash_api_key(external_session_id)[:_SESSION_LOG_ID_CHARS]


@dataclass(frozen=True, slots=True)
class ChatContext:
    org_id: UUID
    chatbot_id: UUID
    system_prompt: str
    generation_config: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PersistedTurn:
    conversation_id: UUID
    message_id: UUID
    # Whether this visitor has ever asked for a human, read in the same transaction that
    # wrote the turn. It decides only whether memory extraction is worth queueing; the task
    # asks the question again for itself, because that is where the write happens.
    subject_is_durable: bool


@dataclass(frozen=True, slots=True)
class ChatOutcome:
    conversation_id: UUID
    message_id: UUID
    answer: str
    citations: list[Citation]
    latency_ms: int


def _retrieval_params(generation_config: dict[str, Any]) -> tuple[int, float]:
    retrieval = settings.retrieval
    top_k = int(generation_config.get("top_k", retrieval.top_k))
    min_similarity = float(generation_config.get("min_similarity", retrieval.min_similarity))
    return max(1, min(top_k, 20)), min_similarity


async def _ensure_conversation(
    session, org_id: UUID, chatbot_id: UUID, external_session_id: str
) -> Conversation:
    repo = ConversationRepository(session)
    conversation = await repo.get_by_session(chatbot_id, external_session_id)
    if conversation is None:
        conversation = await repo.add(
            Conversation(
                org_id=org_id,
                chatbot_id=chatbot_id,
                external_session_id=external_session_id,
            )
        )
    return conversation


async def retrieve(context: ChatContext, question: str) -> list[RetrievedChunk]:
    """Embed the question and pull the closest chunks belonging to this chatbot only.

    The question has to be embedded by the same provider and model the documents were, or the
    two sets of vectors describe different spaces and the distances between them mean nothing.
    That is the same constraint the dimension lock exists to keep.
    """
    top_k, min_similarity = _retrieval_params(context.generation_config)

    embedder = await factory.get_embedding_provider(context.org_id, context.chatbot_id)
    if embedder.dimension is None:
        # No width recorded means nothing has ever been embedded for this chatbot, so there is
        # nothing to search and no point paying to embed the question. An empty result is the
        # honest answer: the prompt already tells the model to say it does not know.
        return []

    query_vector = (await embedder.embed_batch([question]))[0]

    # Retrieval is read-only, so it can be served from a replica when one is configured.
    async with tenant_session(context.org_id, readonly=True) as session:
        return await DocumentChunkRepository(session).search(
            chatbot_id=context.chatbot_id,
            embedding=query_vector,
            dimension=embedder.dimension,
            top_k=top_k,
            min_similarity=min_similarity,
            ef_search=settings.retrieval.hnsw_ef_search,
        )


async def _load_history(context: ChatContext, conversation_id: UUID) -> list[Message]:
    async with tenant_session(context.org_id, readonly=True) as session:
        return await MessageRepository(session).recent_history(
            conversation_id, window=settings.retrieval.history_window_messages
        )


async def _persist_turn(
    context: ChatContext,
    *,
    external_session_id: str,
    question: str,
    answer: str,
    citations: list[Citation],
    latency_ms: int,
) -> PersistedTurn:
    async with tenant_session(context.org_id) as session:
        conversation = await _ensure_conversation(
            session, context.org_id, context.chatbot_id, external_session_id
        )
        message_repo = MessageRepository(session)

        await message_repo.add(
            Message(
                org_id=context.org_id,
                conversation_id=conversation.id,
                chatbot_id=context.chatbot_id,
                role=MessageRole.USER,
                content=question,
            )
        )
        assistant = await message_repo.add(
            Message(
                org_id=context.org_id,
                conversation_id=conversation.id,
                chatbot_id=context.chatbot_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                sources_json=[asdict(citation) for citation in citations],
                latency_ms=latency_ms,
            )
        )

        conversation.message_count += 2
        if conversation.title is None:
            conversation.title = question[:300]
        session.add(conversation)

        return PersistedTurn(
            conversation_id=conversation.id,
            message_id=assistant.id,
            subject_is_durable=await TicketRepository(session).exists_for_conversation(
                conversation.id
            ),
        )


def _enqueue_memory_extraction(org_id: UUID, conversation_id: UUID) -> None:
    """Hand the turn to the worker, best effort.

    Only ids cross the broker. The session id has been a bearer capability since iteration 7
    and a Celery message body sits in Redis for as long as the broker keeps it, so the task
    reads the session id from the conversation row under RLS instead of being handed it.

    A broker that is down costs a memory, never an answer: the visitor has already been sent
    every token of theirs by the time this runs.
    """
    from app.worker.tasks import extract_visitor_memory_task

    try:
        extract_visitor_memory_task.apply_async(args=[str(org_id), str(conversation_id)])
    except Exception as exc:  # noqa: BLE001 - a broker outage must not fail a delivered answer
        logger.warning(
            "nuvrag_mem.enqueue_failed", conversation_id=str(conversation_id), error=str(exc)
        )


async def stream_answer(
    context: ChatContext, *, question: str, external_session_id: str
) -> AsyncIterator[dict[str, Any]]:
    """Drive one chat turn, yielding SSE-shaped events.

    The turn is persisted only once the stream completes, so an aborted connection does not
    leave a half-written assistant message in the transcript.
    """
    started = time.perf_counter()
    log = logger.bind(
        chatbot_id=str(context.chatbot_id), session=session_log_id(external_session_id)
    )

    # Built before the first token is retrieved so a missing provider surfaces as a clean
    # error rather than after the visitor has already seen a `sources` event.
    chat = await factory.get_chat_provider(
        context.org_id, context.chatbot_id, context.generation_config
    )

    matches = await retrieve(context, question)
    citations = build_citations(matches)
    yield {"event": "sources", "data": {"sources": [asdict(c) for c in citations]}}

    async with tenant_session(context.org_id) as session:
        conversation = await _ensure_conversation(
            session, context.org_id, context.chatbot_id, external_session_id
        )
        conversation_id = conversation.id

    history = await _load_history(context, conversation_id)
    messages = build_chat_messages(
        question=question,
        system_prompt=context.system_prompt,
        matches=matches,
        history=history,
        max_context_characters=settings.retrieval.max_context_characters,
    )

    parts: list[str] = []
    async for delta in chat.stream(messages):
        parts.append(delta)
        yield {"event": "token", "data": {"content": delta}}

    answer = "".join(parts).strip()
    if not answer:
        # A model can finish a stream having said nothing: a reasoning model given a modest
        # `max_tokens` spends the whole budget thinking and emits no content at all. Silence
        # is the one outcome the visitor cannot interpret, and persisting it would leave an
        # empty assistant turn in the transcript for the next question to build on.
        log.warning("chat.empty_answer", retrieved=len(matches))
        raise UpstreamServiceError(
            "The model returned an empty answer. If it is a reasoning model, raise "
            "`max_tokens` or turn `think` off for this chatbot."
        )

    latency_ms = int((time.perf_counter() - started) * 1000)

    turn = await _persist_turn(
        context,
        external_session_id=external_session_id,
        question=question,
        answer=answer,
        citations=citations,
        latency_ms=latency_ms,
    )

    if settings.nuvrag_mem.enabled and turn.subject_is_durable:
        _enqueue_memory_extraction(context.org_id, turn.conversation_id)

    log.info(
        "chat.completed",
        latency_ms=latency_ms,
        retrieved=len(matches),
        answer_chars=len(answer),
    )
    yield {
        "event": "done",
        "data": {
            "conversation_id": str(conversation_id),
            "message_id": str(turn.message_id),
            "latency_ms": latency_ms,
            # Zero retrieved chunks is the same condition the prompt turns into "I do not
            # have information about that in the available documents", so it is already the
            # honest signal that a human would do better. Surfaced as an additive field
            # rather than by parsing the answer text or inventing an intent classifier.
            "can_escalate": not matches,
        },
    }
