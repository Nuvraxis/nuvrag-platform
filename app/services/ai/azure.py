"""Azure AI Foundry, through its OpenAI-compatible deployments."""

from typing import Any

from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

from app.core.config import settings
from app.services.ai.base import (
    ChatProvider,
    EmbeddingProvider,
    GenerationParams,
    LangChainChat,
    LangChainEmbeddings,
)

PROVIDER = "azure"
DEFAULT_API_VERSION = "2024-10-21"


def _endpoint(config: dict[str, Any]) -> str:
    """The resource root, with no `/openai` suffix.

    The SDK appends `/openai/deployments/<deployment>` itself, so a suffix here produces a
    doubled path and every call 404s.
    """
    return str(config.get("endpoint") or "").rstrip("/")


def build_chat(
    *,
    model: str,
    config: dict[str, Any],
    credentials: dict[str, str],
    params: GenerationParams,
) -> ChatProvider:
    # Azure names a *deployment*, not a model. `chat_model` holds whatever the tenant called
    # theirs, which need not match the underlying model's name at all.
    return LangChainChat(
        AzureChatOpenAI(
            azure_endpoint=_endpoint(config),
            azure_deployment=model,
            api_key=credentials.get("api_key"),
            api_version=str(config.get("api_version") or DEFAULT_API_VERSION),
            temperature=params.temperature,
            max_tokens=params.max_tokens,
            timeout=settings.ai.request_timeout_seconds,
            max_retries=settings.ai.max_retries,
            streaming=True,
        ),
        provider=PROVIDER,
    )


def build_embeddings(
    *,
    model: str,
    config: dict[str, Any],
    credentials: dict[str, str],
    dimension: int | None,
) -> EmbeddingProvider:
    # `dimensions` is deliberately not passed. text-embedding-3 will shorten its output on
    # request, and asking for the width we already recorded would make the discovered
    # dimension a self-fulfilling prophecy instead of a fact about the deployment.
    return LangChainEmbeddings(
        AzureOpenAIEmbeddings(
            azure_endpoint=_endpoint(config),
            azure_deployment=model,
            api_key=credentials.get("api_key"),
            api_version=str(config.get("api_version") or DEFAULT_API_VERSION),
            chunk_size=settings.ai.embedding_batch_size,
            timeout=settings.ai.request_timeout_seconds,
            max_retries=0,
        ),
        provider=PROVIDER,
        dimension=dimension,
    )
