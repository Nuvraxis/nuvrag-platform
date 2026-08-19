"""The shape every provider presents to the rest of the platform.

Two protocols, one adapter for each, and the machinery both need: a batching, retrying embed
loop, and a filter that keeps a model's private reasoning out of the answer a visitor reads.
"""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import UpstreamServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Providers that separate reasoning structurally hand back typed blocks, and LangChain's
# `.text` already drops those. Models that do not — several of the Ollama reasoning models —
# inline it in the text as a tag pair, which is what the filter below is for.
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


@dataclass(frozen=True, slots=True)
class GenerationParams:
    """Per-chatbot generation settings — the same ones `model_config_json` has always held."""

    temperature: float = 0.2
    max_tokens: int = 1024

    @classmethod
    def from_config(cls, generation_config: dict[str, Any] | None) -> GenerationParams:
        values = generation_config or {}
        return cls(
            temperature=float(values.get("temperature", 0.2)),
            max_tokens=int(values.get("max_tokens", 1024)),
        )


@runtime_checkable
class ChatProvider(Protocol):
    """Streams an answer. Reasoning, if the model produces any, does not come out of here."""

    def stream(self, messages: list[BaseMessage]) -> AsyncIterator[str]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Turns text into vectors.

    `dimension` is the width this chatbot is locked to once anything has been embedded, and
    None before that — which is exactly when a test call is about to discover it.
    """

    dimension: int | None

    async def embed_batch(self, texts: list[str], *, attempts: int = 4) -> list[list[float]]: ...


class ReasoningFilter:
    """Removes `<think>…</think>` spans from a stream of deltas.

    A stream splits wherever the provider chose to, so the tags arrive in pieces: `<th`, then
    `ink>`. Anything that could still become a tag is held back until it either completes one
    or proves it will not, which is why this is a state machine and not a regular expression.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False

    def feed(self, delta: str) -> str:
        self._buffer += delta
        out: list[str] = []

        while self._buffer:
            if self._inside:
                end = self._buffer.find(_THINK_CLOSE)
                if end == -1:
                    self._buffer = _partial_tag_suffix(self._buffer, _THINK_CLOSE)
                    break
                self._buffer = self._buffer[end + len(_THINK_CLOSE) :]
                self._inside = False
                continue

            start = self._buffer.find(_THINK_OPEN)
            if start == -1:
                held = _partial_tag_suffix(self._buffer, _THINK_OPEN)
                out.append(self._buffer[: len(self._buffer) - len(held)])
                self._buffer = held
                break

            out.append(self._buffer[:start])
            self._buffer = self._buffer[start + len(_THINK_OPEN) :]
            self._inside = True

        return "".join(out)

    def flush(self) -> str:
        """Whatever was held back when the stream ended.

        An unterminated `<think>` means the model never closed the tag; its contents stay
        suppressed rather than being released as if they were the answer.
        """
        remainder = "" if self._inside else self._buffer
        self._buffer = ""
        return remainder


def _partial_tag_suffix(text: str, tag: str) -> str:
    """The longest tail of `text` that is a prefix of `tag`, so a split tag survives."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:size]):
            return text[-size:]
    return ""


class LangChainChat:
    """Adapts any LangChain chat model to :class:`ChatProvider`."""

    def __init__(self, model: BaseChatModel, *, provider: str) -> None:
        self._model = model
        self._provider = provider

    async def stream(self, messages: list[BaseMessage]) -> AsyncIterator[str]:
        reasoning = ReasoningFilter()
        try:
            async for chunk in self._model.astream(messages):
                if visible := reasoning.feed(chunk.text):
                    yield visible
        except Exception as exc:
            logger.error("ai.chat_stream_failed", provider=self._provider, error=str(exc))
            raise UpstreamServiceError("Chat completion failed") from exc

        if trailing := reasoning.flush():
            yield trailing


class LangChainEmbeddings:
    """Adapts any LangChain embeddings model to :class:`EmbeddingProvider`."""

    def __init__(self, model: Embeddings, *, provider: str, dimension: int | None = None) -> None:
        self._model = model
        self._provider = provider
        self.dimension = dimension

    async def embed_batch(self, texts: list[str], *, attempts: int = 4) -> list[list[float]]:
        """Embed many chunks per request.

        Batching is the single biggest lever on ingestion latency and cost — one call per
        chunk would multiply round trips by three orders of magnitude on a large PDF.

        `attempts` is 1 for a connection test, where the caller is waiting and a backed-off
        retry of an address that does not answer just makes them wait longer for the same
        verdict. Ingestion, which nobody is watching, keeps the full set.
        """
        if not texts:
            return []

        vectors: list[list[float]] = []
        for batch in _batches(texts, settings.ai.embedding_batch_size):
            try:
                vectors.extend(await self._embed_once(batch, attempts))
            except Exception as exc:
                logger.error(
                    "ai.embed_batch_failed",
                    provider=self._provider,
                    size=len(batch),
                    error=str(exc),
                )
                raise UpstreamServiceError("Embedding request failed") from exc

        if len(vectors) != len(texts):
            raise UpstreamServiceError(
                f"Embedding count mismatch: expected {len(texts)}, received {len(vectors)}"
            )
        return vectors

    async def _embed_once(self, texts: list[str], attempts: int) -> list[list[float]]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                return await self._model.aembed_documents(texts)
        raise UpstreamServiceError("Embedding request failed")  # unreachable: reraise=True


def _batches(items: list[str], size: int) -> Iterator[list[str]]:
    return (items[start : start + size] for start in range(0, len(items), size))
