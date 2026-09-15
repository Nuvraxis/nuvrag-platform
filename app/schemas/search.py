from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

SEARCH_TOP_K_MAX = 20


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=SEARCH_TOP_K_MAX)
    # Costs a call to the chatbot's chat model, so it is asked for rather than assumed. A
    # chatbot with no usable chat provider silently gets the fused order instead — reranking
    # is an improvement on a result that is already worth returning, never a precondition.
    rerank: bool = Field(default=False)


class SearchHit(BaseModel):
    """One passage, with every score that put it where it is.

    Three separate numbers rather than one, because they answer different questions and are
    not interchangeable. `score` is the fused rank score and orders this list; `similarity` is
    the cosine the vector half measured; `lexical_score` is what the text index scored. A null
    on either half means that half did not return this passage at all, which is not the same
    as returning it with a low score — a passage found only lexically has no cosine, rather
    than a cosine of zero.
    """

    chunk_id: UUID
    document_id: UUID
    content: str
    metadata: dict[str, Any]
    score: float
    similarity: float | None
    lexical_score: float | None
    vector_rank: int | None
    lexical_rank: int | None


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    # Whether anything cleared a floor. The same signal the chat path turns into
    # `can_escalate`, reported here so a caller building its own answer can tell "nothing
    # matched" from "these are the best of a bad set".
    grounded: bool
    # Whether reranking was asked for *and* happened. False after a parse failure or an
    # unreachable provider, which is how a caller learns the order is the fused one.
    reranked: bool
