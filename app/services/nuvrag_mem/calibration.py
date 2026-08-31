"""Deciding, per chatbot, how close a note has to be before it is recalled.

The gate itself is one number: a cosine floor a stored note must clear against the visitor's
question. What this module exists for is that the number cannot be a constant. Cosine
similarity distributions are a property of an embedding model, not of the task, and every
chatbot here picks its own embedding provider and model independently of its chat one. Two
measurements of the same note and the same questions:

    nomic-embed-text (768d)     paraphrase 0.542    unrelated 0.373-0.431
    qwen3-embedding:8b (4096d)  paraphrase 0.720    unrelated 0.476-0.526

A floor of 0.45 separates the bands on the first model and sits below *both* on the second,
where every unrelated question recalls every note. Moving it to a number that suits
qwen3-embedding does not fix that; it relocates the bug to whichever model somebody
configures next. So the floor is measured against the model actually in use, once, and
stored.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.session import tenant_session
from app.models import Chatbot
from app.models.chatbot import SIMILARITY_MAX, SIMILARITY_MIN
from app.repositories import ChatbotRepository
from app.services.ai import factory
from app.services.ai.base import EmbeddingProvider
from app.services.cache import ChatbotConfigCache
from app.services.redis_client import get_redis

logger = get_logger(__name__)

# The calibration set. Each entry is a note of the kind extraction actually writes — a short
# first-person statement — paired with the question that should recall it and a question that
# should not. Both questions are measured against the same note, so the two bands describe one
# text rather than two unrelated samples.
#
# The distractors are ordinary product-support questions on purpose. That is overwhelmingly
# what a visitor asks, so it is the distribution the floor has to hold up against; a set of
# arbitrary unrelated sentences would measure a distance nobody ever actually queries at.
CALIBRATION_PAIRS: tuple[tuple[str, str, str], ...] = (
    (
        "My favourite colour is blue.",
        "What colour do I like best?",
        "How do I reset my password?",
    ),
    (
        "I live in Amsterdam.",
        "Where am I based?",
        "What are your opening hours on public holidays?",
    ),
    (
        "I prefer to be contacted by email rather than by phone.",
        "What is the best way to get in touch with me?",
        "Does this product come with a warranty?",
    ),
    (
        "I am allergic to peanuts.",
        "Which foods do I need to avoid?",
        "How much does shipping to Germany cost?",
    ),
    (
        "I work as a primary school teacher.",
        "What do I do for a living?",
        "Can I export my invoices as a CSV file?",
    ),
    (
        "My subscription renews in March.",
        "When is my plan next billed?",
        "Is there a mobile app for Android?",
    ),
    (
        "I speak Dutch and English.",
        "Which languages can I read?",
        "What is your refund policy?",
    ),
    (
        "I have two cats.",
        "Do I have any pets?",
        "How do I add a second user to my account?",
    ),
)

# The smallest gap that still counts as being *above* a measured distractor. It exists only so
# the threshold is strictly greater than the worst distractor on a model whose distractor band
# has no spread at all; the caution proper comes from that band's own width, below.
CALIBRATION_MIN_MARGIN = 0.01

# How hard each caller tries. The inline path is a visitor waiting on an answer, so a backed-off
# retry chain would stall the turn to salvage a measurement the next message can take again for
# free. The manual path is an operator watching a button, where one flaky response is worth
# retrying rather than reporting back as a failure they have to trigger again themselves.
INLINE_ATTEMPTS = 1
MANUAL_ATTEMPTS = 4


@dataclass(frozen=True, slots=True)
class Calibration:
    """A measured threshold and the two bands it was read off."""

    threshold: float
    min_paraphrase: float
    max_distractor: float
    # Whether the lowest paraphrase actually cleared the highest distractor. False means the
    # threshold came from the conservative branch and this model separates the two poorly.
    separated: bool


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """The same quantity `MemoryEntryRepository.search` compares against.

    pgvector returns cosine *distance* and the repository turns it into `1 - distance`. This
    computes that directly, so a threshold measured here means the same thing there.
    """
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def threshold_from_scores(paraphrase: Sequence[float], distractor: Sequence[float]) -> Calibration:
    """Where to put the floor, given what the two kinds of question actually scored.

    Kept apart from the embedding call so the decision can be tested against score
    distributions no locally available model happens to produce.
    """
    min_paraphrase = min(paraphrase)
    max_distractor = max(distractor)

    if min_paraphrase > max_distractor:
        threshold = (min_paraphrase + max_distractor) / 2
        separated = True
    else:
        # The bands overlap, so no threshold gets both kinds right and the only choice left is
        # which error to make. A fact wrongly forgotten costs a visitor one convenience; a fact
        # wrongly recalled has the assistant tell them something untrue about themselves, which
        # is the failure this floor exists for. So the threshold goes above the worst distractor
        # rather than anywhere between the bands, and recall turns conservative — possibly
        # silent — on a model that cannot tell the two apart.
        #
        # The margin is the distractor band's own spread. `max - mean` is the only measured
        # evidence of how far a distractor this fixed set did not sample might reach past the
        # worst one it did: a tight band earns a small step and a scattered one a large step,
        # which is exactly when caution is worth most.
        mean_distractor = sum(distractor) / len(distractor)
        margin = max(CALIBRATION_MIN_MARGIN, max_distractor - mean_distractor)
        threshold = max_distractor + margin
        separated = False

    return Calibration(
        threshold=min(SIMILARITY_MAX, max(SIMILARITY_MIN, threshold)),
        min_paraphrase=min_paraphrase,
        max_distractor=max_distractor,
        separated=separated,
    )


async def measure(embedder: EmbeddingProvider, *, attempts: int) -> Calibration:
    """Score the fixed pairs through one chatbot's embedding model.

    One `embed_batch` call for the whole set — notes, then paraphrases, then distractors — so
    the request count does not grow with the pair count.
    """
    notes = [note for note, _, _ in CALIBRATION_PAIRS]
    paraphrases = [question for _, question, _ in CALIBRATION_PAIRS]
    distractors = [question for _, _, question in CALIBRATION_PAIRS]

    vectors = await embedder.embed_batch(notes + paraphrases + distractors, attempts=attempts)
    count = len(CALIBRATION_PAIRS)
    note_vectors = vectors[:count]
    paraphrase_vectors = vectors[count : count * 2]
    distractor_vectors = vectors[count * 2 :]

    return threshold_from_scores(
        [_cosine(note, ask) for note, ask in zip(note_vectors, paraphrase_vectors, strict=True)],
        [_cosine(note, ask) for note, ask in zip(note_vectors, distractor_vectors, strict=True)],
    )


async def calibrate(
    org_id: UUID,
    chatbot_id: UUID,
    *,
    embedder: EmbeddingProvider | None = None,
    attempts: int = INLINE_ATTEMPTS,
) -> float | None:
    """Measure this chatbot's floor and store it, or None if the provider could not be reached.

    `embedder` is passed in on the chat path, where one has already been built for the
    question's own vector — calibrating through a second instance would risk measuring a
    different model than the one the recall vector came from.

    `attempts` defaults to `INLINE_ATTEMPTS` because the caller that does not pass one is the
    chat path; see that constant.
    """
    try:
        # Building the provider is inside the guard, not before it: a missing credential or an
        # unreadable configuration is a calibration failure in exactly the same way an
        # unreachable endpoint is, and both have to reach the caller as one outcome.
        if embedder is None:
            embedder = await factory.get_embedding_provider(org_id, chatbot_id)
        calibration = await measure(embedder, attempts=attempts)
    except Exception as exc:  # noqa: BLE001 - any provider failure is the one degraded outcome
        logger.warning(
            "nuvrag_mem.calibration_failed",
            chatbot_id=str(chatbot_id),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None

    await _store(org_id, chatbot_id, calibration.threshold)
    logger.info(
        "nuvrag_mem.calibrated",
        chatbot_id=str(chatbot_id),
        threshold=round(calibration.threshold, 4),
        min_paraphrase=round(calibration.min_paraphrase, 4),
        max_distractor=round(calibration.max_distractor, 4),
        separated=calibration.separated,
    )
    return calibration.threshold


def _cache() -> ChatbotConfigCache:
    return ChatbotConfigCache(get_redis(), settings.redis.chatbot_cache_ttl_seconds)


async def _store(org_id: UUID, chatbot_id: UUID, threshold: float) -> None:
    async with tenant_session(org_id) as session:
        chatbot = await ChatbotRepository(session).get_for_org(chatbot_id, org_id)
        if chatbot is None:
            return
        chatbot.nuvrag_mem_similarity_calibrated = threshold
        chatbot.nuvrag_mem_similarity_calibrated_at = utcnow()
        session.add(chatbot)
        public_key = chatbot.public_key

    # The widget config cache carries the calibration so the chat path pays no query to read
    # it. Without this eviction the next turn would read `calibrated: null` again and
    # recalibrate on every message until the TTL ran out.
    await _cache().invalidate(public_key)


def clear(session: AsyncSession, chatbot: Chatbot) -> None:
    """Forget a calibration, because it described an embedding model this chatbot has left.

    Takes the caller's session and row rather than looking either up: the only caller is the
    AI configuration save, which holds both and has to clear in the same transaction that
    moves the model — otherwise a failed save leaves behind a threshold measured for a model
    nobody is using.
    """
    chatbot.nuvrag_mem_similarity_calibrated = None
    chatbot.nuvrag_mem_similarity_calibrated_at = None
    session.add(chatbot)


@dataclass(frozen=True, slots=True)
class CalibrationState:
    """One chatbot's floor, as the dashboard and the API report it."""

    override: float | None
    calibrated: float | None
    calibrated_at: datetime | None

    @property
    def effective(self) -> float | None:
        """An override always wins and is never recalculated; otherwise the measurement.

        None means no floor is known yet, which is not the same as a floor of zero — it is
        the state that makes the next recall attempt calibrate, and until it does, recall
        returns nothing at all.
        """
        return self.override if self.override is not None else self.calibrated

    @property
    def source(self) -> str:
        if self.override is not None:
            return "override"
        if self.calibrated is not None:
            return "calibrated"
        return "uncalibrated"
