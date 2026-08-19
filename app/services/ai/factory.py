"""Turns a chatbot's stored configuration into something that can be called.

Every embedding and every completion in the platform comes through here. Nothing else builds
a provider client, and nothing else reads a credential.
"""

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
from app.services.ai import anthropic, azure, bedrock, ollama
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


CHAT_BUILDERS: dict[ChatProviderName, _ChatBuilder] = {
    ChatProviderName.AZURE: azure.build_chat,
    ChatProviderName.BEDROCK: bedrock.build_chat,
    ChatProviderName.ANTHROPIC: anthropic.build_chat,
    ChatProviderName.OLLAMA: ollama.build_chat,
}

# No Anthropic entry, because there is no Anthropic embeddings API to point at.
EMBEDDING_BUILDERS: dict[EmbeddingProviderName, _EmbeddingBuilder] = {
    EmbeddingProviderName.AZURE: azure.build_embeddings,
    EmbeddingProviderName.BEDROCK: bedrock.build_embeddings,
    EmbeddingProviderName.OLLAMA: ollama.build_embeddings,
}


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
    await _cache().invalidate(chatbot_id)


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
    """Assemble a client from already-decrypted parts. The test endpoint uses this too."""
    return CHAT_BUILDERS[ChatProviderName(provider)](
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
    return EMBEDDING_BUILDERS[EmbeddingProviderName(provider)](
        model=model,
        config=config,
        credentials=credentials,
        dimension=dimension,
    )


async def get_chat_provider(
    org_id: UUID, chatbot_id: UUID, generation_config: dict[str, Any] | None = None
) -> ChatProvider:
    config = await load_config(org_id, chatbot_id)
    return build_chat_provider(
        provider=config.chat_provider,
        model=config.chat_model,
        config=config.chat_config_json,
        # Decrypted here and nowhere else. The plaintext exists as an argument to the builder
        # and then only inside the SDK client that is about to make the call — it is not
        # cached, logged, or returned to a caller.
        credentials=_credentials(config.chat_credentials_encrypted),
        generation_config=generation_config,
    )


async def get_embedding_provider(org_id: UUID, chatbot_id: UUID) -> EmbeddingProvider:
    config = await load_config(org_id, chatbot_id)
    return build_embedding_provider(
        provider=config.embedding_provider,
        model=config.embedding_model,
        config=config.embedding_config_json,
        credentials=_credentials(config.embedding_credentials_encrypted),
        dimension=config.embedding_dimension,
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
