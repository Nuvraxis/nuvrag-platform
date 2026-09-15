from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import UUID

from pydantic import ValidationError

from app.core.client_ip import client_log_id
from app.core.config import settings
from app.core.exceptions import (
    ChatbotUnavailableError,
    NotFoundError,
    OriginNotAllowedError,
    RateLimitExceededError,
)
from app.core.logging import get_logger
from app.db.session import system_session
from app.models import ChatbotStatus
from app.models.chatbot import DEFAULT_USAGE_CAP_MESSAGE
from app.repositories import ChatbotRepository
from app.schemas.chatbot import WidgetTheme, validate_link
from app.services.cache import ChatbotConfigCache
from app.services.rag import ChatContext
from app.services.rate_limit import RateLimiter
from app.services.redis_client import get_redis

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WidgetSession:
    """A widget request that has passed key lookup, origin check and status check."""

    context: ChatContext
    name: str
    status: str
    allowed_origin: str
    theme: WidgetTheme
    # Footer links. Validated again on the way out for the same reason as the theme: the
    # values have been through a Redis round trip since they were checked on the way in, and
    # they end up as an `href` in a visitor's browser.
    privacy_url: str
    terms_url: str


def _normalise_origin(origin: str) -> str:
    parsed = urlparse(origin.strip().rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


async def resolve_chatbot(public_key: str) -> dict:
    """Look up a chatbot by its widget key, preferring the Redis cache.

    The lookup is deliberately unscoped: the public key *is* how the tenant is identified,
    before any org context exists.
    """
    cache = ChatbotConfigCache(get_redis(), settings.redis.chatbot_cache_ttl_seconds)
    cached = await cache.get_by_public_key(public_key)
    if cached is not None:
        return cached

    async with system_session() as session:
        chatbot = await ChatbotRepository(session).get_by_public_key(public_key)

    if chatbot is None:
        raise NotFoundError("Unknown chatbot key")

    await cache.set_by_public_key(chatbot)
    return {
        "id": str(chatbot.id),
        "org_id": str(chatbot.org_id),
        "name": chatbot.name,
        "system_prompt": chatbot.system_prompt,
        "model_config_json": chatbot.model_config_json,
        "allowed_origins": chatbot.allowed_origins,
        "theme_json": chatbot.theme_json,
        "privacy_url": chatbot.privacy_url,
        "terms_url": chatbot.terms_url,
        "status": str(chatbot.status),
        "monthly_retrieval_call_cap": chatbot.monthly_retrieval_call_cap,
        "usage_cap_message": chatbot.usage_cap_message,
        "nuvrag_mem_similarity_override": chatbot.nuvrag_mem_similarity_override,
        "nuvrag_mem_similarity_calibrated": chatbot.nuvrag_mem_similarity_calibrated,
        "hybrid_search_enabled": chatbot.hybrid_search_enabled,
        "hybrid_rerank_enabled": chatbot.hybrid_rerank_enabled,
    }


def resolve_site_origin(
    *, declared: str | None, origin: str | None, referer: str | None
) -> str | None:
    """Work out which site the visitor is actually on.

    The widget runs in an iframe served from the CDN, so the browser's `Origin` on its calls
    is the CDN's, not the tenant's — checking that would authorise every tenant identically.
    The loader runs on the tenant page and hands its origin to the frame over `postMessage`,
    where the browser fills in `event.origin` itself; a hostile embedder cannot forge it, and
    the frame relays only what it was told. That is what `declared` carries.

    It is honoured only when the browser also says the caller is our frame, so the claim is
    ignored for everyone else rather than being an alternative way to name a site. Note what
    this does *not* buy: `Origin` is set by browsers, not by the network, so a client that is
    not a browser can send whatever it likes here and always could. The allow-list keeps a
    scraped key from working on another site; it is not an authentication boundary.
    """
    if declared and _normalise_origin(origin or "") == _normalise_origin(
        settings.widget_cdn_base_url
    ):
        return declared
    return origin or referer


def enforce_origin(config: dict, site_origin: str | None) -> str:
    """The real security boundary for the widget.

    The public key is embedded in tenant HTML and therefore is not a secret; restricting
    which sites may call the API is what stops a scraped key being used elsewhere.

    Returns the matched origin, which is the tenant's site rather than the widget's own.
    """
    allowed = [_normalise_origin(item) for item in config.get("allowed_origins") or []]
    if not allowed:
        raise OriginNotAllowedError("This chatbot has no allowed origins configured yet")

    candidate = _normalise_origin(site_origin or "")
    if not candidate or candidate not in allowed:
        logger.warning("widget.origin_rejected", chatbot_id=config.get("id"), origin=site_origin)
        raise OriginNotAllowedError("Requests from this origin are not permitted")
    return candidate


def ensure_active(config: dict) -> None:
    """Paused and archived chatbots serve nothing at all.

    This guards every widget entry point — bootstrap, chat and tickets — because it sits in
    the `widget_session` dependency they share. Bootstrap is the one that matters most: it is
    the first call the frame makes, and this answer is what tells it to take itself off the
    page rather than show a launcher that cannot do anything.
    """
    if config.get("status") != ChatbotStatus.ACTIVE:
        raise ChatbotUnavailableError("This chatbot is not currently available")


async def enforce_rate_limits(chatbot_id: str, session_id: str) -> None:
    limiter = RateLimiter(get_redis(), settings.rate_limit)

    chatbot_verdict = await limiter.check_chatbot(chatbot_id)
    if not chatbot_verdict.allowed:
        raise RateLimitExceededError(
            "This chatbot is receiving too many requests right now",
            retry_after_seconds=chatbot_verdict.retry_after_seconds,
        )

    session_verdict = await limiter.check_session(chatbot_id, session_id)
    if not session_verdict.allowed:
        raise RateLimitExceededError(
            "Too many messages from this session",
            retry_after_seconds=session_verdict.retry_after_seconds,
        )


async def enforce_ticket_limits(chatbot_id: str, address: str) -> None:
    """The extra gate on opening a ticket, on top of the chat limits it already passes.

    Two buckets, because they answer different attacks. The per-address one stops one caller
    hammering the form; the per-chatbot one stops a distributed attempt where every request
    arrives from somewhere new and the first bucket therefore never fills.

    The address is refused as one bucket rather than allowed when it cannot be determined —
    see `UNKNOWN_CLIENT`. Behind a correctly configured proxy every real request has one.
    """
    limiter = RateLimiter(get_redis(), settings.rate_limit)

    verdict = await limiter.check_ticket_ip(chatbot_id, address)
    if not verdict.allowed:
        logger.warning(
            "widget.ticket_rate_limited",
            chatbot_id=chatbot_id,
            client=client_log_id(address),
            scope="address",
        )
        raise RateLimitExceededError(
            "Too many requests have been sent from here. Please try again later.",
            retry_after_seconds=verdict.retry_after_seconds,
        )

    chatbot_verdict = await limiter.check_ticket_chatbot(chatbot_id)
    if not chatbot_verdict.allowed:
        logger.warning("widget.ticket_rate_limited", chatbot_id=chatbot_id, scope="chatbot")
        raise RateLimitExceededError(
            "This chatbot is receiving too many requests right now",
            retry_after_seconds=chatbot_verdict.retry_after_seconds,
        )


def build_session(config: dict, allowed_origin: str) -> WidgetSession:
    return WidgetSession(
        context=ChatContext(
            org_id=UUID(config["org_id"]),
            chatbot_id=UUID(config["id"]),
            system_prompt=config.get("system_prompt") or "",
            generation_config=config.get("model_config_json") or {},
            # Carried on the cached config rather than read per turn, so enforcing a cap costs
            # the chat path no query it was not already making. The cost is that raising or
            # clearing a cap takes effect within the cache TTL rather than instantly, which is
            # true of every other chatbot setting the widget reads.
            retrieval_call_cap=config.get("monthly_retrieval_call_cap"),
            usage_cap_message=config.get("usage_cap_message") or DEFAULT_USAGE_CAP_MESSAGE,
            # Same reasoning, and the same TTL caveat — with one difference: an inline
            # calibration evicts this entry itself, so a chatbot cannot spend a whole TTL
            # measuring the same floor on every message.
            nuvrag_mem_similarity_override=config.get("nuvrag_mem_similarity_override"),
            nuvrag_mem_similarity_calibrated=config.get("nuvrag_mem_similarity_calibrated"),
            hybrid_search_enabled=bool(config.get("hybrid_search_enabled")),
            hybrid_rerank_enabled=bool(config.get("hybrid_rerank_enabled")),
        ),
        name=config.get("name") or "Assistant",
        status=config.get("status") or str(ChatbotStatus.ACTIVE),
        allowed_origin=allowed_origin,
        theme=_theme(config.get("theme_json")),
        privacy_url=_link(config.get("privacy_url")),
        terms_url=_link(config.get("terms_url")),
    )


def _link(stored: object) -> str:
    """Re-check a footer link on the way out, and drop it rather than fail if it is bad.

    Same reasoning as `_theme`: this was validated when it was saved, but it has crossed a
    Redis cache since and it becomes an `href` in a visitor's browser. A link that no longer
    parses is dropped — a widget with one fewer footer link is a far better outcome than a
    bootstrap that 500s and leaves the visitor with no chat at all.
    """
    if not isinstance(stored, str):
        return ""
    try:
        return validate_link(stored)
    except ValueError:
        logger.warning("widget.link_rejected", link=stored)
        return ""


def _theme(stored: dict | None) -> WidgetTheme:
    """Validate on the way out as well as on the way in.

    These values end up in a `style` attribute inside the widget frame. They were checked when
    they were saved, but the row has been through a JSONB column and a Redis round trip since;
    parsing again here means only the shapes this schema allows can reach a browser, whatever
    happened in between.
    """
    try:
        return WidgetTheme.model_validate(stored or {})
    except ValidationError:
        logger.warning("widget.theme_rejected", theme=stored)
        return WidgetTheme()
