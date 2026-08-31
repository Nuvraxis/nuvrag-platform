from fastapi import APIRouter

from app.api.deps import SecretKeyChatbot
from app.core.config import settings
from app.core.exceptions import RateLimitExceededError
from app.core.logging import get_logger
from app.schemas.search import SearchRequest, SearchResponse
from app.services import search as search_service
from app.services.rate_limit import RateLimiter
from app.services.redis_client import get_redis

router = APIRouter(prefix="/search", tags=["search"])

logger = get_logger(__name__)


@router.post("", response_model=SearchResponse, summary="Search a chatbot's indexed passages")
async def search(payload: SearchRequest, chatbot: SecretKeyChatbot) -> SearchResponse:
    """Retrieval without a conversation: no answer is generated and nothing is written.

    Always hybrid — vector and lexical, fused — regardless of the chatbot's chat-path toggle.
    That toggle exists to keep an existing chatbot's *answers* from changing underneath it,
    and this endpoint has no existing answers to preserve.

    Charged against the chatbot's monthly retrieval allowance, one per call, because it spends
    the same embedding call a chat turn does.
    """
    limiter = RateLimiter(get_redis(), settings.rate_limit)
    verdict = await limiter.check_search(str(chatbot.id))
    if not verdict.allowed:
        logger.warning("search.rate_limited", chatbot_id=str(chatbot.id))
        raise RateLimitExceededError(
            "Too many search requests for this chatbot right now",
            retry_after_seconds=verdict.retry_after_seconds,
        )

    return await search_service.search(chatbot, payload)
