"""Hybrid retrieval: a vector list, a lexical list, and one ranking out of the two.

Dense retrieval cannot match what the embedding does not distinguish. A part number, an
acronym, a rare proper noun — `XR-7742B` sits in much the same region of embedding space as
`XR-7743B`, and a question naming one will happily retrieve the other. Lexical search has the
opposite shape: it is exact where embeddings are fuzzy, and useless where the visitor's words
and the document's words are different words for the same thing.

Fusing them is therefore not about weighing one against the other. It is about taking two
lists that are each right about different questions and producing one order.
"""

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.document_chunk import TEXT_SEARCH_CONFIG
from app.repositories import DocumentChunkRepository, LexicalChunk, RetrievedChunk
from app.services.ai.base import ChatProvider
from app.services.ai.prompts import build_rerank_messages

logger = get_logger(__name__)

# Reciprocal Rank Fusion: a chunk's score is the sum over the lists containing it of
# 1 / (RRF_K + rank), counting from rank 1. Fixed at 60, which is the value the method was
# published with and the one every implementation uses.
#
# Rank rather than score is the whole point. A cosine similarity and a `ts_rank_cd` are not on
# the same scale, are not on the *same kind* of scale, and no constant converts one into the
# other — blending them linearly would need a weight nobody could set correctly, on a platform
# that has already been bitten once this cycle by exactly that (see iteration 17). Position in
# a list is the one thing the two halves genuinely have in common.
#
# What K does is flatten the top: at K=60 the gap between rank 1 and rank 2 is small, so a
# chunk both halves agree is *roughly* relevant outranks one that either half alone loves.
# That is the intended bias — agreement across two different notions of relevance is better
# evidence than a strong opinion from one.
RRF_K = 60

# Why `lexical_min_rank` defaults to 0.2, in one place so the setting does not have to carry
# it. `ts_rank_cd` with default weights scores 0.1 per matched lexeme occurrence in the best
# cover, so the scale is a count of matches wearing a decimal point: 0.1 is one word of the
# question appearing once, 0.2 is two. Measured across a twenty-passage support corpus, the
# passage that actually answered a question scored 0.2 to 0.6, and a passage that merely shared
# a word scored 0.1 — so the floor sits exactly at "more than one isolated word matched".
#
# Small talk clears nothing at all here, which is the property that matters most: "hi there",
# "thanks that is great", "ok bye thanks" and "tell me more about that" produce no lexical
# match whatsoever against ordinary documentation, because every one of their words is either
# an English stopword or absent. Iteration 13's problem — a conversational turn being read as
# a question nobody could answer — is therefore untouched by this gate.
LEXICAL_FLOOR_NOTE = "0.1 per matched term; 0.2 means more than one isolated word"

# Lexemes to build the tsquery from. Postgres's own `websearch_to_tsquery` ANDs its terms,
# which is right for a search box and wrong here: a visitor asks "how long does a refund take
# to arrive", and requiring every one of those words to appear finds nothing. The terms are
# ORed instead and `ts_rank_cd` sorts out how many actually landed.
_LEXEME = re.compile(r"'([^']+)'")

# Any run of digits. Deliberately forgiving about what surrounds them — a model that answers
# `[3, 1, 2]` or `3, 1, 2.` has done what was asked, and refusing that would send a usable
# ranking to the fallback over punctuation. What is *not* forgiving is `parse_rerank_order`,
# which requires the numbers themselves to be a genuine permutation.
_INDEX = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class FusedMatch:
    """One chunk in the fused ranking, and the evidence behind its position."""

    chunk_match: RetrievedChunk
    score: float
    # Where this chunk came in each half, 1-based, or None if that half did not return it.
    # Kept because a fused score on its own says nothing about *why* something ranked.
    vector_rank: int | None
    lexical_rank: int | None
    lexical_score: float | None

    @property
    def similarity(self) -> float:
        return self.chunk_match.similarity


@dataclass(frozen=True, slots=True)
class HybridResult:
    matches: list[RetrievedChunk]
    fused: list[FusedMatch]
    # Whether anything cleared *either* floor — see `_grounded`.
    grounded: bool
    reranked: bool


async def build_tsquery(session: AsyncSession, question: str) -> str:
    """Turn a visitor's sentence into an OR of its lexemes, using Postgres's own analyser.

    Done in the database rather than in Python on purpose: the stemming, stopword list and
    token rules have to be exactly the ones that built `content_tsv`, and the only thing that
    knows them is the text-search configuration itself. Reimplementing an approximation here
    would drift the moment either side changed.
    """
    stripped = await session.scalar(
        select(func.strip(func.to_tsvector(TEXT_SEARCH_CONFIG, question)))
    )
    lexemes = _LEXEME.findall(str(stripped or ""))
    # Each lexeme is quoted rather than pasted in bare. `to_tsquery` re-parses what it is
    # given, so an unquoted `xr-7742b` comes back out as the phrase `xr-7742b <-> xr <-> 7742b`
    # — and a lexeme that happened to contain an operator character would be a syntax error
    # raised on the chat path. Quoting makes each one a literal, which is what it already is:
    # these came out of `to_tsvector`, so they are analysed terms, not text to analyse again.
    return " | ".join(f"'{lexeme.replace(chr(39), chr(39) * 2)}'" for lexeme in lexemes)


def fuse(
    vector: list[RetrievedChunk], lexical: list[LexicalChunk], *, limit: int
) -> list[FusedMatch]:
    """Reciprocal Rank Fusion over the two ranked lists."""
    scores: dict[str, float] = {}
    positions: dict[str, tuple[int | None, int | None]] = {}
    lexical_scores: dict[str, float] = {}
    found: dict[str, RetrievedChunk] = {}

    for position, match in enumerate(vector, start=1):
        key = str(match.chunk.id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + position)
        positions[key] = (position, None)
        found[key] = match

    for position, hit in enumerate(lexical, start=1):
        key = str(hit.chunk.id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + position)
        vector_position = positions.get(key, (None, None))[0]
        positions[key] = (vector_position, position)
        lexical_scores[key] = hit.rank
        # A chunk the vector half never returned still needs a `RetrievedChunk` to travel in.
        # Its similarity is 0.0 and that is not a measurement: it is "the vector search did not
        # rank this, so no cosine was computed for it". `vector_rank is None` is what says so
        # without pretending to a number.
        found.setdefault(key, RetrievedChunk(chunk=hit.chunk, similarity=0.0))

    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [
        FusedMatch(
            chunk_match=found[key],
            score=score,
            vector_rank=positions[key][0],
            lexical_rank=positions[key][1],
            lexical_score=lexical_scores.get(key),
        )
        for key, score in ordered[:limit]
    ]


def _grounded(vector: list[RetrievedChunk], lexical: list[LexicalChunk]) -> bool:
    """Did anything clear either floor?

    An OR of two gates that each mean something on their own, rather than one threshold over
    the fused score. A fused score is a sum of reciprocal ranks: its magnitude depends on how
    many candidates came back and in what order, not on how good the best one is, so there is
    no value of it that means "we found an answer". The two floors do mean that, each in its
    own currency — and keeping them separate is also what makes the disabled path provably
    unchanged, because with hybrid search off the lexical half is never run and the condition
    collapses to exactly today's `not matches`.
    """
    floor = settings.retrieval.min_similarity
    if any(match.similarity >= floor for match in vector):
        return True
    return any(hit.rank >= settings.retrieval.lexical_min_rank for hit in lexical)


async def hybrid_search(
    session: AsyncSession,
    *,
    chatbot_id: UUID,
    question: str,
    embedding: list[float],
    dimension: int,
    top_k: int,
    ef_search: int | None = None,
) -> HybridResult:
    """Both halves, fused. The caller reranks afterwards if the chatbot asks for it."""
    config = settings.retrieval
    candidates = max(top_k, config.hybrid_candidates)
    repo = DocumentChunkRepository(session)

    # No similarity floor on the vector half here, unlike the pure-vector path. Fusion needs
    # the full ranked list: a chunk below the floor that the lexical half puts first is exactly
    # the case hybrid search exists for, and pre-filtering would throw it away before fusion
    # could see it. The floor still applies, in `_grounded`, where it decides escalation.
    vector = await repo.search(
        chatbot_id=chatbot_id,
        embedding=embedding,
        dimension=dimension,
        top_k=candidates,
        min_similarity=-1.0,
        ef_search=ef_search,
    )
    lexical = await repo.search_lexical(
        chatbot_id=chatbot_id,
        tsquery=await build_tsquery(session, question),
        dimension=dimension,
        top_k=candidates,
    )

    fused = fuse(vector, lexical, limit=top_k)
    return HybridResult(
        matches=[item.chunk_match for item in fused],
        fused=fused,
        grounded=_grounded(vector, lexical),
        reranked=False,
    )


def parse_rerank_order(reply: str, *, count: int) -> list[int] | None:
    """The model's reply as zero-based positions, or None if it cannot be trusted.

    Strict about the thing that matters: the numbers must be a permutation of 1..count. A
    reply that drops a candidate, repeats one or invents one is not a partial ranking to be
    salvaged — it is evidence the model did not do the task, and acting on half of it would
    silently discard passages the fused ranking had already earned.
    """
    found = [int(value) for value in _INDEX.findall(reply)]
    if sorted(found) != list(range(1, count + 1)):
        return None
    return [value - 1 for value in found]


async def rerank(
    chat: ChatProvider, *, question: str, fused: list[FusedMatch]
) -> tuple[list[FusedMatch], bool]:
    """Reorder the fused candidates with the chatbot's own chat model.

    Returns the list and whether the reordering actually happened. Every failure — an
    unreachable provider, an unparseable reply, a reply that is not a permutation — returns
    the fused order unchanged rather than raising: reranking is an improvement on an answer
    that is already good enough to serve, so it is never worth failing a request over.
    """
    config = settings.retrieval
    candidates = fused[: config.rerank_max_candidates]
    if len(candidates) < 2:
        return fused, False

    messages = build_rerank_messages(
        question=question,
        passages=[item.chunk_match.chunk.content for item in candidates],
        excerpt_characters=config.rerank_excerpt_characters,
    )

    try:
        parts = [delta async for delta in chat.stream(messages)]
    except Exception as exc:  # noqa: BLE001 - any provider failure is one fallback
        logger.warning("rerank.provider_failed", error_type=type(exc).__name__, error=str(exc))
        return fused, False

    order = parse_rerank_order("".join(parts), count=len(candidates))
    if order is None:
        logger.info("rerank.unusable_reply", candidates=len(candidates))
        return fused, False

    # Anything beyond the rerank window keeps its fused position, after everything reranked.
    return [candidates[position] for position in order] + fused[len(candidates) :], True
