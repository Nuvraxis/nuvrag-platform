"""A self-hosted Ollama server. No credentials, just an address."""

from typing import Any

from langchain_ollama import ChatOllama, OllamaEmbeddings

from app.core.config import settings
from app.services.ai.base import (
    ChatProvider,
    EmbeddingProvider,
    GenerationParams,
    LangChainChat,
    LangChainEmbeddings,
)

PROVIDER = "ollama"
DEFAULT_BASE_URL = "http://localhost:11434"


def _base_url(config: dict[str, Any]) -> str:
    return str(config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")


def _reasoning(config: dict[str, Any]) -> bool | None:
    """Map the stored `think` flag onto what Ollama will actually accept.

    Measured against Ollama, sending `think` to a model whose capabilities do not include
    `thinking` is a 400 — but only in the affirmative:

        think=true   thinking model: reasons     other model: 400 does not support thinking
        think=false  thinking model: no reasoning  other model: answers
        omitted      thinking model: reasons     other model: answers

    So "on" is expressed by sending nothing, which is the only spelling that lets one setting
    cover both kinds of model: a reasoning model reasons as it normally would, and a plain
    one still answers instead of erroring. "Off" is sent explicitly, because that is the case
    where the caller means to override a reasoning model's own default.

    Either way none of it reaches the visitor: `LangChainChat.stream` strips reasoning from
    the deltas whatever this returns. The toggle decides whether the model reasons, not
    whether the reasoning is shown.
    """
    return None if config.get("think", True) else False


def build_chat(
    *,
    model: str,
    config: dict[str, Any],
    credentials: dict[str, str],
    params: GenerationParams,
) -> ChatProvider:
    return LangChainChat(
        ChatOllama(
            model=model,
            base_url=_base_url(config),
            temperature=params.temperature,
            num_predict=params.max_tokens,
            reasoning=_reasoning(config),
            client_kwargs={"timeout": settings.ai.request_timeout_seconds},
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
    return LangChainEmbeddings(
        OllamaEmbeddings(
            model=model,
            base_url=_base_url(config),
            client_kwargs={"timeout": settings.ai.request_timeout_seconds},
        ),
        provider=PROVIDER,
        dimension=dimension,
    )
