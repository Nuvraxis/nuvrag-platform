from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import IngestionSettings
from app.services.ingestion.extractors import TextSection

# text-embedding-3-small shares cl100k_base with the gpt-4 family, so one encoder measures
# both the chunks we store and the prompt we later build from them.
_ENCODING_NAME = "cl100k_base"


@lru_cache(maxsize=1)
def _encoder() -> tiktoken.Encoding:
    return tiktoken.get_encoding(_ENCODING_NAME)


def count_tokens(text: str) -> int:
    return len(_encoder().encode(text, disallowed_special=()))


@dataclass(slots=True)
class Chunk:
    index: int
    content: str
    token_count: int
    metadata: dict[str, Any]


@lru_cache(maxsize=8)
def _splitter(chunk_size: int, chunk_overlap: int) -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=count_tokens,
        # Prefer breaking on paragraph, then sentence, then word boundaries so a chunk
        # rarely ends mid-thought.
        separators=["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""],
        keep_separator=True,
    )


def chunk_sections(sections: list[TextSection], config: IngestionSettings) -> list[Chunk]:
    """Split extracted sections into overlapping, token-bounded chunks.

    Section metadata (page, heading) rides along on every chunk so the chat response can
    cite where an answer came from.
    """
    splitter = _splitter(config.chunk_size_tokens, config.chunk_overlap_tokens)

    chunks: list[Chunk] = []
    for section in sections:
        for piece in splitter.split_text(section.content):
            body = piece.strip()
            if not body:
                continue
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=body,
                    token_count=count_tokens(body),
                    metadata=dict(section.metadata),
                )
            )
            if len(chunks) >= config.max_chunks_per_document:
                return chunks
    return chunks
