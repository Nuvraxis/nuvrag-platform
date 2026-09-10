"""Turns a chatbot's stored configuration into something that can be called.

Every embedding and every completion in the platform comes through here. Nothing else builds
a provider client, and nothing else reads a credential.
"""

import importlib
from dataclasses import asdict, dataclass
from typing import Any, Protocol
from uuid import UUID

from app.core.config import settings
from app.core.crypto import decrypt_credentials
from app.core.exceptions import ProviderNotConfiguredError
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models import ChatbotAIConfig, ChatProviderName, EmbeddingProviderName
from app.repositories import ChatbotAIConfigRepository
from app.services.ai import clients
from app.services.ai.base import ChatProvider, EmbeddingProvider, GenerationParams
from app.services.ai.registry import chat_requirements, embedding_requirements, is_ready
from app.services.cache import AIConfigCache
from app.services.redis_client import get_redis

logger = get_logger(__name__)


class _ChatBuilder(Protocol):
    def __call__(
        self,
        *,
        model: str,
        config: dict[str, Any],
        credentials: dict[str, str],
        params: GenerationParams,
    ) -> ChatProvider: ...


class _EmbeddingBuilder(Protocol):
    def __call__(
        self,
        *,
        model: str,
        config: dict[str, Any],
        credentials: dict[str, str],
        dimension: int | None,
    ) -> EmbeddingProvider: ...


# Module paths rather than functions, so importing this module imports no provider SDK. The
# four of them together are 107 MiB of resident memory and over half of everything the API
# process loads, and a chatbot uses at most two — the same reasoning `get_object_storage`
# already applies to the storage backends. A pod that never serves a Bedrock tenant never
# pays for boto3.
CHAT_MODULES: dict[ChatProviderName, str] = {
    ChatProviderName.AZURE: "app.services.ai.azure",
    ChatProviderName.BEDROCK: "app.services.ai.bedrock",
    ChatProviderName.ANTHROPIC: "app.services.ai.anthropic",
    ChatProviderName.OLLAMA: "app.services.ai.ollama",
}

# No Anthropic entry, because there is no Anthropic embeddings API to point at.
EMBEDDING_MODULES: dict[EmbeddingProviderName, str] = {
    EmbeddingProviderName.AZURE: "app.services.ai.azure",
    EmbeddingProviderName.BEDROCK: "app.services.ai.bedrock",
    EmbeddingProviderName.OLLAMA: "app.services.ai.ollama",
}


def chat_builder(provider: ChatProviderName) -> _ChatBuilder:
    module = importlib.import_module(CHAT_MODULES[ChatProviderName(provider)])
    return module.build_chat  # type: ignore[no-any-return]


def embedding_builder(provider: EmbeddingProviderName) -> _EmbeddingBuilder:
    module = importlib.import_module(EMBEDDING_MODULES[EmbeddingProviderName(provider)])
    return module.build_embeddings  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class AIConfigSummary:
    """Everything about a chatbot's providers that is safe to cache and safe to return."""

    chat_provider: str
    chat_model: str
    chat_ready: bool
    embedding_provider: str
    embedding_model: str
    embedding_ready: bool
    embedding_dimension: int | None


def _cache() -> AIConfigCache:
    return AIConfigCache(get_redis(), settings.redis.chatbot_cache_ttl_seconds)


def summarise(config: ChatbotAIConfig) -> AIConfigSummary:
    return AIConfigSummary(
        chat_provider=str(config.chat_provider),
        chat_model=config.chat_model,
        chat_ready=is_ready(
            chat_requirements(config.chat_provider),
            has_stored_credentials=bool(config.chat_credentials_encrypted),
            connection=config.chat_config_json,
        ),
        embedding_provider=str(config.embedding_provider),
        embedding_model=config.embedding_model,
        embedding_ready=is_ready(
            embedding_requirements(config.embedding_provider),
            has_stored_credentials=bool(config.embedding_credentials_encrypted),
            connection=config.embedding_config_json,
        ),
        embedding_dimension=config.embedding_dimension,
    )


async def load_config(org_id: UUID, chatbot_id: UUID) -> ChatbotAIConfig:
    async with tenant_session(org_id, readonly=True) as session:
        config = await ChatbotAIConfigRepository(session).get_for_chatbot(chatbot_id)
    if config is None:
        raise ProviderNotConfiguredError(
            "No AI provider is configured for this chatbot. Choose one on its AI provider "
            "settings before uploading documents or sending messages."
        )
    return config


async def get_summary(org_id: UUID, chatbot_id: UUID) -> AIConfigSummary | None:
    """The cached, credential-free view. Used wherever only the shape of the setup matters."""
    cached = await _cache().get(chatbot_id)
    if cached is not None:
        return AIConfigSummary(**cached)

    async with tenant_session(org_id, readonly=True) as session:
        config = await ChatbotAIConfigRepository(session).get_for_chatbot(chatbot_id)
    if config is None:
        return None

    summary = summarise(config)
    await _cache().set(chatbot_id, asdict(summary))
    return summary


async def invalidate(chatbot_id: UUID) -> None:
    """Everything held about one chatbot's providers, dropped together.

    The Redis summary and the in-process clients are invalidated on the same call so that a
    caller cannot clear one and leave the other: a rotated key that stays live in a worker
    process for an hour is the failure this exists to prevent.
    """
    await _cache().invalidate(chatbot_id)
    await clients.invalidate(chatbot_id)


async def require_embedding_ready(org_id: UUID, chatbot_id: UUID) -> AIConfigSummary:
    """The guard on every path that is about to produce vectors."""
    summary = await get_summary(org_id, chatbot_id)
    if summary is None:
        raise ProviderNotConfiguredError(
            "No AI provider is configured for this chatbot. Choose one on its AI provider "
            "settings before uploading documents."
        )
    if not summary.embedding_ready:
        raise ProviderNotConfiguredError(
            f"The {summary.embedding_provider} embedding provider for this chatbot is missing "
            "its connection details. Complete them before uploading documents.",
            details={"field": "embedding_provider"},
        )
    return summary


async def require_chat_ready(org_id: UUID, chatbot_id: UUID) -> AIConfigSummary:
    summary = await get_summary(org_id, chatbot_id)
    if summary is None:
        raise ProviderNotConfiguredError(
            "No AI provider is configured for this chatbot, so it cannot answer questions yet."
        )
    if not summary.chat_ready:
        raise ProviderNotConfiguredError(
            f"The {summary.chat_provider} chat provider for this chatbot is missing its "
            "connection details.",
            details={"field": "chat_provider"},
        )
    return summary


def build_chat_provider(
    *,
    provider: ChatProviderName,
    model: str,
    config: dict[str, Any],
    credentials: dict[str, str],
    generation_config: dict[str, Any] | None = None,
) -> ChatProvider:
    """Assemble a client from already-decrypted parts. The test endpoint uses this too.

    Uncached on purpose: the caller is holding credentials that may be wrong and is asking
    whether they work. Caching a client built from an unproven key would keep it alive for an
    hour after a single failed attempt. Callers of this own what it returns and close it.
    """
    return chat_builder(provider)(
        model=model,
        config=config,
        credentials=credentials,
        params=GenerationParams.from_config(generation_config),
    )


def build_embedding_provider(
    *,
    provider: EmbeddingProviderName,
    model: str,
    config: dict[str, Any],
    credentials: dict[str, str],
    dimension: int | None = None,
) -> EmbeddingProvider:
    return embedding_builder(provider)(
        model=model,
        config=config,
        credentials=credentials,
        dimension=dimension,
    )


async def get_chat_provider(
    org_id: UUID, chatbot_id: UUID, generation_config: dict[str, Any] | None = None
) -> ChatProvider:
    """The chatbot's chat client. Shared, so callers must not close what they get back."""
    config = await load_config(org_id, chatbot_id)
    # Decrypted here and nowhere else. The plaintext exists as an argument to the builder and
    # then only inside the SDK client that is about to make the call — it is not logged, and
    # it reaches the cache only as part of the digest that identifies the client.
    credentials = _credentials(config.chat_credentials_encrypted)
    params = GenerationParams.from_config(generation_config)

    # Everything the client is built from goes into the key, not only the four fields that
    # identify the endpoint: two chatbots sharing one Anthropic key but set to different
    # temperatures are different clients, and keying on the endpoint alone would silently
    # serve one of them the other's settings.
    key = clients.cache_key(
        "chat",
        str(config.chat_provider),
        config.chat_model,
        config.chat_config_json,
        credentials,
        asdict(params),
    )
    return await clients.acquire(
        key,
        owner=chatbot_id,
        build=lambda: chat_builder(config.chat_provider)(
            model=config.chat_model,
            config=config.chat_config_json,
            credentials=credentials,
            params=params,
        ),
    )


async def get_embedding_provider(org_id: UUID, chatbot_id: UUID) -> EmbeddingProvider:
    """The chatbot's embedding client. Shared, so callers must not close what they get back."""
    config = await load_config(org_id, chatbot_id)
    credentials = _credentials(config.embedding_credentials_encrypted)

    # The recorded width is part of the key because the adapter carries it: a shared client
    # that reported the wrong dimension would be a silent correctness bug rather than a
    # memory one.
    key = clients.cache_key(
        "embedding",
        str(config.embedding_provider),
        config.embedding_model,
        config.embedding_config_json,
        credentials,
        config.embedding_dimension,
    )
    return await clients.acquire(
        key,
        owner=chatbot_id,
        build=lambda: embedding_builder(config.embedding_provider)(
            model=config.embedding_model,
            config=config.embedding_config_json,
            credentials=credentials,
            dimension=config.embedding_dimension,
        ),
    )


async def record_embedding_dimension(org_id: UUID, chatbot_id: UUID, dimension: int) -> None:
    """Lock a chatbot to the width its provider actually returned.

    Written once, from a real call, and never guessed from a model name — the same model can
    be served at different widths, and a wrong guess here would not fail until a query tried
    to compare vectors of two lengths.
    """
    async with tenant_session(org_id) as session:
        repo = ChatbotAIConfigRepository(session)
        config = await repo.get_for_chatbot(chatbot_id)
        if config is None or config.embedding_dimension == dimension:
            return
        config.embedding_dimension = dimension
        session.add(config)

    logger.info("ai.embedding_dimension_locked", chatbot_id=str(chatbot_id), dimension=dimension)
    await invalidate(chatbot_id)


def _credentials(encrypted: str | None) -> dict[str, str]:
    return decrypt_credentials(encrypted) if encrypted else {}
