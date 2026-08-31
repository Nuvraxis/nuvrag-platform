"""Per-chatbot ceilings on what a month may spend with an AI provider.

Separate from the rate limiter on purpose, and not a replacement for it. That one shapes
requests per second and forgets everything a minute later; this one counts cumulative spend
and remembers it until the month turns over. A chatbot can be well inside its token bucket and
still have burned its budget, which is exactly the case nothing covered before.

Nothing here is on by default: both caps are NULL until an operator sets one, and a NULL cap
skips the counter entirely rather than counting toward a ceiling that does not exist.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from math import ceil
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.models import ChatbotUsagePeriod
from app.observability.metrics import usage_cap_blocks_total

logger = get_logger(__name__)

# Roughly a chunk's worth of text. The point of the unit is that it tracks what ingestion
# actually spends — embedding calls scale with bytes, not with documents — so a 200-page PDF
# and a one-line note cannot cost the same.
INGESTION_UNIT_BYTES = 4000


class UsageKind(StrEnum):
    """What is being counted. One member per column on `chatbot_usage_period`.

    Iteration 17's `/v1/search` increments RETRIEVAL from a second call site; that is why
    `consume` takes a kind and an amount rather than being two functions.
    """

    INGESTION = "ingestion"
    RETRIEVAL = "retrieval"


_COUNTER_COLUMN = {
    UsageKind.INGESTION: "ingestion_units_used",
    UsageKind.RETRIEVAL: "retrieval_calls_used",
}


@dataclass(frozen=True, slots=True)
class UsageVerdict:
    allowed: bool
    used: int
    cap: int | None
    # True when the counters could not be read or written at all. Distinct from `allowed`,
    # because "we let this through without knowing" is a different thing to report than
    # "we checked and there was room", and the caller logs them differently.
    counters_unavailable: bool = False


def ingestion_units(size_bytes: int) -> int:
    """Rounded up, so the smallest document still costs something.

    An empty upload never reaches this — `_MeteredStream` rejects it — so the zero case is
    unreachable rather than special.
    """
    return ceil(size_bytes / INGESTION_UNIT_BYTES)


def period_start(moment: datetime | None = None) -> date:
    """The first day of the UTC month a moment belongs to.

    UTC rather than anything local: a cap is the operator's budget, and the operator's
    calendar is the only one every tenant shares.
    """
    now = moment or datetime.now(UTC)
    return now.astimezone(UTC).date().replace(day=1)


# Rollover, the cap check and the increment, in one statement.
#
# The INSERT is the rollover: the first write of a new month finds no row for its
# `period_start` and creates one, so nothing has to notice the boundary or be scheduled to.
# The ON CONFLICT branch is every subsequent write in that month.
#
# The cap check lives in the conflict branch's WHERE, which is what makes it atomic. Two
# concurrent turns cannot both read "under cap" and both write, because neither reads: the
# comparison happens against the row's own value inside the same statement that updates it,
# under the row lock the update already takes. A separate SELECT then UPDATE is the race; this
# has no gap to race in.
#
# Returning no rows therefore means exactly one thing — the row existed and the cap predicate
# was false — because the INSERT branch cannot fail the predicate (a fresh row starts at zero,
# and the caller has already refused an amount larger than the whole cap).
_CONSUME = """
INSERT INTO chatbot_usage_period AS usage_period (
    org_id, chatbot_id, period_start,
    ingestion_units_used, retrieval_calls_used, created_at, updated_at
)
VALUES (
    :org_id, :chatbot_id, :period_start,
    :ingestion, :retrieval, now(), now()
)
ON CONFLICT (chatbot_id, period_start) DO UPDATE
   SET ingestion_units_used = usage_period.ingestion_units_used + :ingestion,
       retrieval_calls_used = usage_period.retrieval_calls_used + :retrieval,
       updated_at = now()
 WHERE CAST(:cap AS integer) IS NULL
    OR usage_period.{counter} + :amount <= CAST(:cap AS integer)
RETURNING ingestion_units_used, retrieval_calls_used
"""

_CURRENT = """
SELECT ingestion_units_used, retrieval_calls_used
  FROM chatbot_usage_period
 WHERE chatbot_id = :chatbot_id AND period_start = :period_start
"""


async def consume(
    org_id: UUID, chatbot_id: UUID, *, kind: UsageKind, amount: int, cap: int | None
) -> UsageVerdict:
    """Charge `amount` against this month, unless that would pass the cap.

    Returns rather than raising, because the two callers want different things from a refusal:
    the upload endpoint turns it into a 429 and the chat path turns it into an answer.
    """
    if cap is not None and amount > cap:
        # Bigger than the whole month's allowance, so no amount of headroom would admit it.
        # Checked here because the statement's INSERT branch has no row to compare against.
        used = await _read_used(org_id, chatbot_id, kind=kind)
        return _blocked(chatbot_id, kind=kind, used=used, cap=cap)

    counter = _COUNTER_COLUMN[kind]
    parameters = {
        "org_id": org_id,
        "chatbot_id": chatbot_id,
        "period_start": period_start(),
        "ingestion": amount if kind is UsageKind.INGESTION else 0,
        "retrieval": amount if kind is UsageKind.RETRIEVAL else 0,
        "amount": amount,
        "cap": cap,
    }

    try:
        async with tenant_session(org_id) as session:
            result = await session.execute(text(_CONSUME.format(counter=counter)), parameters)
            row = result.first()
    except SQLAlchemyError as exc:
        return _unavailable(chatbot_id, kind=kind, cap=cap, error=exc)

    if row is None:
        used = await _read_used(org_id, chatbot_id, kind=kind)
        return _blocked(chatbot_id, kind=kind, used=used, cap=cap)

    ingestion_used, retrieval_used = row
    used = ingestion_used if kind is UsageKind.INGESTION else retrieval_used
    return UsageVerdict(allowed=True, used=used, cap=cap)


async def headroom(
    org_id: UUID, chatbot_id: UUID, *, kind: UsageKind, cap: int | None
) -> UsageVerdict:
    """Whether this chatbot has any allowance left at all, without charging for it.

    The upload path needs this because the true cost of an upload is not known until the file
    has been streamed — see `size_bytes` — and a chatbot that is *already* at its cap should
    be turned away before a byte moves rather than after.
    """
    if cap is None:
        return UsageVerdict(allowed=True, used=0, cap=None)

    try:
        used = await _read_used(org_id, chatbot_id, kind=kind, reraise=True)
    except SQLAlchemyError as exc:
        return _unavailable(chatbot_id, kind=kind, cap=cap, error=exc)

    if used >= cap:
        return _blocked(chatbot_id, kind=kind, used=used, cap=cap)
    return UsageVerdict(allowed=True, used=used, cap=cap)


async def current_period(session: AsyncSession, chatbot_id: UUID) -> ChatbotUsagePeriod | None:
    """This month's row, for the dashboard. Absent until the first charge of the month."""
    return await session.get(ChatbotUsagePeriod, (chatbot_id, period_start()))


async def _read_used(
    org_id: UUID, chatbot_id: UUID, *, kind: UsageKind, reraise: bool = False
) -> int:
    """This month's total, or zero if the month has no row yet."""
    try:
        async with tenant_session(org_id, readonly=True) as session:
            result = await session.execute(
                text(_CURRENT),
                {"chatbot_id": chatbot_id, "period_start": period_start()},
            )
            row = result.first()
    except SQLAlchemyError:
        if reraise:
            raise
        # Only reached while reporting a refusal that has already been decided, so the number
        # is cosmetic and a wrong one must not turn a refusal into an error.
        return 0

    if row is None:
        return 0
    ingestion_used, retrieval_used = row
    return ingestion_used if kind is UsageKind.INGESTION else retrieval_used


def _blocked(chatbot_id: UUID, *, kind: UsageKind, used: int, cap: int | None) -> UsageVerdict:
    usage_cap_blocks_total.labels(chatbot_id=str(chatbot_id), kind=str(kind)).inc()
    logger.warning(
        "usage_cap.blocked", chatbot_id=str(chatbot_id), kind=str(kind), used=used, cap=cap
    )
    return UsageVerdict(allowed=False, used=used, cap=cap)


def _unavailable(
    chatbot_id: UUID, *, kind: UsageKind, cap: int | None, error: Exception
) -> UsageVerdict:
    fail_closed = settings.usage_cap.fail_closed
    logger.warning(
        "usage_cap.counters_unavailable",
        chatbot_id=str(chatbot_id),
        kind=str(kind),
        fail_closed=fail_closed,
        error=str(error),
    )
    return UsageVerdict(allowed=not fail_closed, used=0, cap=cap, counters_unavailable=True)
