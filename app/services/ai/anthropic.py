"""Anthropic's Claude models. Chat only.

There is no `build_embeddings` here because Anthropic publishes no embeddings API. That is
not an omission to be filled in later: `EmbeddingProviderName` has no member for it, so the
schema, the database check constraint and the factory's dispatch table all agree without any
of them special-casing anything.

Extended thinking is out of scope for this iteration. It needs a `budget_tokens` parameter
and different response-block handling, and half-wiring it silently would be worse than
leaving it off — `think` in `chat_config_json` is therefore ignored here rather than obeyed
approximately.
"""

from typing import Any

from langchain_anthropic import ChatAnthropic

from app.core.config import settings
from app.services.ai.base import ChatProvider, GenerationParams, LangChainChat

PROVIDER = "anthropic"


def build_chat(
    *,
    model: str,
    config: dict[str, Any],
    credentials: dict[str, str],
    params: GenerationParams,
) -> ChatProvider:
    return LangChainChat(
        ChatAnthropic(
            model=model,
            api_key=credentials.get("api_key"),
            temperature=params.temperature,
            max_tokens=params.max_tokens,
            timeout=settings.ai.request_timeout_seconds,
            max_retries=settings.ai.max_retries,
        ),
        provider=PROVIDER,
    )
