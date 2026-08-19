"""Reading, saving and testing a chatbot's AI provider configuration."""

import asyncio
from collections.abc import Awaitable
from typing import Any
from uuid import UUID

from langchain_core.messages import HumanMessage

from app.core.config import settings
from app.core.crypto import decrypt_credentials, encrypt_credentials
from app.core.exceptions import ConflictError, DomainError, NotFoundError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models import ChatbotAIConfig
from app.repositories import (
    ChatbotAIConfigRepository,
    ChatbotRepository,
    DocumentChunkRepository,
)
from app.schemas.ai_config import (
    AIConfigRead,
    AIConfigTest,
    AIConfigTestResult,
    AIConfigUpdate,
    ChatTarget,
    EmbeddingTarget,
    ProviderRead,
)
from app.services.ai import factory
from app.services.ai.registry import (
    Requirements,
    chat_requirements,
    embedding_requirements,
    is_ready,
    missing_credential_fields,
)

logger = get_logger(__name__)

# Long enough to prove the round trip, short enough that nobody is billed for testing.
_TEST_PROMPT = [HumanMessage(content="Reply with the single word: ok")]
_TEST_GENERATION = {"temperature": 0.0, "max_tokens": 16}
_TEST_EMBEDDING_INPUT = ["connection test"]


async def get_config(org_id: UUID, chatbot_id: UUID) -> AIConfigRead:
    async with tenant_session(org_id, readonly=True) as session:
        await _require_chatbot(session, org_id, chatbot_id)
        config = await ChatbotAIConfigRepository(session).get_for_chatbot(chatbot_id)
        if config is None:
            raise NotFoundError("This chatbot has no AI provider configured yet")
        locked = await _has_chunks(session, chatbot_id)
    return _read(config, locked=locked)


async def save_config(org_id: UUID, chatbot_id: UUID, payload: AIConfigUpdate) -> AIConfigRead:
    async with tenant_session(org_id) as session:
        await _require_chatbot(session, org_id, chatbot_id)
        repo = ChatbotAIConfigRepository(session)
        existing = await repo.get_for_chatbot(chatbot_id)
        locked = await _has_chunks(session, chatbot_id)

        if existing is not None and locked and _embedding_changed(existing, payload.embedding):
            raise ConflictError(
                f"This chatbot already has documents embedded with "
                f"{existing.embedding_provider}/{existing.embedding_model}. Delete them before "
                "changing the embedding provider or model — existing vectors cannot be "
                "compared against a different model's.",
                details={"field": "embedding.provider"},
            )

        config = existing or ChatbotAIConfig(
            org_id=org_id,
            chatbot_id=chatbot_id,
            chat_provider=payload.chat.provider,
            chat_model=payload.chat.model,
            embedding_provider=payload.embedding.provider,
            embedding_model=payload.embedding.model,
        )
        _apply(config, payload)
        await repo.add(config)

    await factory.invalidate(chatbot_id)
    if config.embedding_dimension is None:
        await _discover_dimension(org_id, chatbot_id, config)
    return _read(config, locked=locked)


async def _discover_dimension(org_id: UUID, chatbot_id: UUID, config: ChatbotAIConfig) -> None:
    """Record the vector width now, so a saved configuration knows its own shape.

    A test discovers the width, but on first-time setup there is no row yet to write it to —
    the configuration being tested is the one about to be created. Measuring once here closes
    that gap. Best effort on purpose: ingestion measures it too and is the authority, so a
    provider that is briefly unreachable costs nothing more than a later discovery.
    """
    try:
        provider = factory.build_embedding_provider(
            provider=config.embedding_provider,
            model=config.embedding_model,
            config=config.embedding_config_json,
            credentials=decrypt_credentials(config.embedding_credentials_encrypted)
            if config.embedding_credentials_encrypted
            else {},
        )
        vectors = await _timed(provider.embed_batch(_TEST_EMBEDDING_INPUT, attempts=1))
    except Exception as exc:  # noqa: BLE001 - a save must not fail on an optional measurement
        logger.info(
            "ai.dimension_deferred_to_ingestion",
            chatbot_id=str(chatbot_id),
            error_type=type(exc).__name__,
        )
        return

    if vectors and vectors[0]:
        await factory.record_embedding_dimension(org_id, chatbot_id, len(vectors[0]))
        config.embedding_dimension = len(vectors[0])


def _apply(config: ChatbotAIConfig, payload: AIConfigUpdate) -> None:
    embedding_moved = _embedding_changed(config, payload.embedding)

    config.chat_provider = payload.chat.provider
    config.chat_model = payload.chat.model
    config.chat_config_json = payload.chat.connection.model_dump()
    config.embedding_provider = payload.embedding.provider
    config.embedding_model = payload.embedding.model
    config.embedding_config_json = payload.embedding.connection.model_dump()

    # Omitted credentials keep whatever is stored. A key that cannot be read back has to be
    # re-typeable without being re-required, or correcting a model name would mean fetching
    # the key out of a password manager every time.
    if payload.chat.credentials is not None:
        config.chat_credentials_encrypted = _sealed(payload.chat.credentials.as_dict())
    if payload.embedding.credentials is not None:
        config.embedding_credentials_encrypted = _sealed(payload.embedding.credentials.as_dict())

    if embedding_moved:
        # The recorded width described the old model. It is not a fact about the new one.
        config.embedding_dimension = None


def _sealed(credentials: dict[str, str]) -> str | None:
    """An explicit empty object clears the stored credentials rather than keeping them."""
    return encrypt_credentials(credentials) if credentials else None


def _embedding_changed(config: ChatbotAIConfig, target: EmbeddingTarget) -> bool:
    return (
        str(config.embedding_provider) != str(target.provider)
        or config.embedding_model != target.model
    )


async def test_config(org_id: UUID, chatbot_id: UUID, payload: AIConfigTest) -> AIConfigTestResult:
    """Call the providers for real, with the values the caller is holding.

    Nothing is saved except one thing: if the embedding half being tested is exactly what is
    already stored and no width has been recorded, this is where it gets recorded — the
    dimension is a fact proven about a specific configuration, so it is written only when the
    proof was about that configuration.
    """
    stored = await _stored(org_id, chatbot_id)

    if payload.chat is not None:
        credentials = _resolve_credentials(
            payload.chat,
            requirements=chat_requirements(payload.chat.provider),
            stored_provider=str(stored.chat_provider) if stored else None,
            stored_encrypted=stored.chat_credentials_encrypted if stored else None,
        )
        if credentials is None:
            return _missing_credentials("chat", payload.chat.provider)
        try:
            await _timed(_chat_probe(payload.chat, credentials))
        except Exception as exc:  # noqa: BLE001 - every provider failure becomes one verdict
            return _failure("chat", payload.chat.provider, exc)

    dimension: int | None = None
    if payload.embedding is not None:
        credentials = _resolve_credentials(
            payload.embedding,
            requirements=embedding_requirements(payload.embedding.provider),
            stored_provider=str(stored.embedding_provider) if stored else None,
            stored_encrypted=stored.embedding_credentials_encrypted if stored else None,
        )
        if credentials is None:
            return _missing_credentials("embedding", payload.embedding.provider)
        try:
            dimension = await _timed(_embedding_probe(payload.embedding, credentials))
        except Exception as exc:  # noqa: BLE001 - as above
            return _failure("embedding", payload.embedding.provider, exc)
        _record = stored is not None and stored.embedding_dimension is None
        if _record and not _embedding_changed(stored, payload.embedding):
            await factory.record_embedding_dimension(org_id, chatbot_id, dimension)

    return AIConfigTestResult(ok=True, embedding_dimension=dimension)


def _resolve_credentials(
    target: ChatTarget | EmbeddingTarget,
    *,
    requirements: Requirements,
    stored_provider: str | None,
    stored_encrypted: str | None,
) -> dict[str, str] | None:
    """What this half would actually be called with. None means "nothing usable".

    Supplied credentials win. Omitting them means "keep what is saved", which is the same
    thing a save means — but only while the provider is unchanged, since a key stored for one
    provider says nothing about another.
    """
    if target.credentials is not None:
        supplied = target.credentials.as_dict()
        return supplied if not missing_credential_fields(requirements, supplied) else None

    if not requirements.credentials:
        return {}
    if stored_encrypted is None or stored_provider != str(target.provider):
        return None
    return decrypt_credentials(stored_encrypted)


def _missing_credentials(capability: str, provider: str) -> AIConfigTestResult:
    return AIConfigTestResult(
        ok=False,
        failed=capability,
        error=f"No credentials were supplied for {provider}, and none are stored for it yet.",
    )


async def _stored(org_id: UUID, chatbot_id: UUID) -> ChatbotAIConfig | None:
    async with tenant_session(org_id, readonly=True) as session:
        return await ChatbotAIConfigRepository(session).get_for_chatbot(chatbot_id)


async def _chat_probe(target: ChatTarget, credentials: dict[str, str]) -> None:
    # Reasoning is turned off for the probe whatever the chatbot's own setting is. The
    # question here is whether these credentials reach that model, and a reasoning model
    # asked to think would spend the whole token budget doing so and return nothing —
    # a green light that proved the connection while looking exactly like a broken one.
    connection = target.connection.model_dump() | {"think": False}
    provider = factory.build_chat_provider(
        provider=target.provider,
        model=target.model,
        config=connection,
        credentials=credentials,
        generation_config=_TEST_GENERATION,
    )
    spoken = "".join([delta async for delta in provider.stream(_TEST_PROMPT)])
    if not spoken.strip():
        raise ValueError("the model produced no output")


async def _embedding_probe(target: EmbeddingTarget, credentials: dict[str, str]) -> int:
    provider = factory.build_embedding_provider(
        provider=target.provider,
        model=target.model,
        config=target.connection.model_dump(),
        credentials=credentials,
    )
    vectors = await provider.embed_batch(_TEST_EMBEDDING_INPUT, attempts=1)
    if not vectors or not vectors[0]:
        raise ValueError("empty embedding")
    return len(vectors[0])


async def _timed[T](awaitable: Awaitable[T]) -> T:
    return await asyncio.wait_for(awaitable, timeout=settings.ai.test_timeout_seconds)


def _failure(capability: str, provider: str, exc: BaseException) -> AIConfigTestResult:
    status = _status_code(exc)
    logger.warning(
        "ai.connection_test_failed",
        capability=capability,
        provider=str(provider),
        # The type and the status code, never the message: a provider rejecting a key
        # routinely quotes it back, and that text would end up in the log pipeline.
        error_type=type(exc).__name__,
        status=status,
    )
    return AIConfigTestResult(ok=False, failed=capability, error=_explain(exc, status))


# Matched on type name rather than message, because a message is where a rejected credential
# would be quoted back at us.
_UNREACHABLE_TYPES = {
    "APIConnectionError",
    "ConnectError",
    "ConnectionError",
    "ConnectionRefusedError",
    "ConnectTimeout",
    "EndpointConnectionError",
    "ReadTimeout",
    "ResponseError",
    "ResponseStreamingError",
}


def _explain(exc: BaseException, status: int | None) -> str:
    """A fixed phrase per failure class. Never the provider's own words."""
    if isinstance(exc, TimeoutError):
        return "The provider did not respond in time."
    if status in {401, 403}:
        return "The provider rejected these credentials."
    if status == 404:
        return "The provider has no such model or deployment at that address."
    if status == 429:
        return "The provider is rate limiting this account right now."
    if status is not None and 500 <= status < 600:
        return "The provider reported an error of its own. Try again shortly."
    if any(type(item).__name__ in _UNREACHABLE_TYPES for item in _causes(exc)):
        return "Could not reach the provider at that address."
    return "The call failed. Check the model name and the connection details."


def _status_code(exc: BaseException) -> int | None:
    """Dig an HTTP status out of whichever SDK raised, without reading any message text."""
    for item in _causes(exc):
        # Our own domain errors carry a `status_code` describing the response *we* would
        # send. Reading it here reported every wrapped failure as the provider's own 502.
        if isinstance(item, DomainError):
            continue
        direct = getattr(item, "status_code", None)
        if isinstance(direct, int):
            return direct
        response = getattr(item, "response", None)
        if isinstance(response, dict):
            metadata = response.get("ResponseMetadata")
            if isinstance(metadata, dict) and isinstance(metadata.get("HTTPStatusCode"), int):
                return int(metadata["HTTPStatusCode"])
        nested = getattr(response, "status_code", None)
        if isinstance(nested, int):
            return nested
    return None


def _causes(exc: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _read(config: ChatbotAIConfig, *, locked: bool) -> AIConfigRead:
    return AIConfigRead(
        chat=ProviderRead(
            provider=str(config.chat_provider),
            model=config.chat_model,
            connection=config.chat_config_json,
            credentials_set=bool(config.chat_credentials_encrypted),
            ready=is_ready(
                chat_requirements(config.chat_provider),
                has_stored_credentials=bool(config.chat_credentials_encrypted),
                connection=config.chat_config_json,
            ),
        ),
        embedding=ProviderRead(
            provider=str(config.embedding_provider),
            model=config.embedding_model,
            connection=config.embedding_config_json,
            credentials_set=bool(config.embedding_credentials_encrypted),
            ready=is_ready(
                embedding_requirements(config.embedding_provider),
                has_stored_credentials=bool(config.embedding_credentials_encrypted),
                connection=config.embedding_config_json,
            ),
        ),
        embedding_dimension=config.embedding_dimension,
        embedding_locked=locked,
    )


async def _require_chatbot(session: Any, org_id: UUID, chatbot_id: UUID) -> None:
    if await ChatbotRepository(session).get_for_org(chatbot_id, org_id) is None:
        raise NotFoundError(f"Chatbot {chatbot_id} not found")


async def _has_chunks(session: Any, chatbot_id: UUID) -> bool:
    return await DocumentChunkRepository(session).count(chatbot_id=chatbot_id) > 0
