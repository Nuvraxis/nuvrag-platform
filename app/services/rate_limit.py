from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import RateLimitSettings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Token bucket evaluated atomically inside Redis. Time comes from the Redis server so that
# API replicas with skewed clocks cannot refill a bucket early. Redis replicates script
# effects rather than the script itself, so calling TIME here is deterministic downstream.
_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local time = redis.call('TIME')
local now = tonumber(time[1]) + (tonumber(time[2]) / 1000000)

local bucket = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts = tonumber(bucket[2])

if tokens == nil or ts == nil then
  tokens = capacity
  ts = now
end

tokens = math.min(capacity, tokens + math.max(0, now - ts) * refill_rate)

local allowed = 0
local retry_after = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry_after = math.ceil((cost - tokens) / refill_rate)
end

redis.call('HSET', key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', key, ttl)

return {allowed, tostring(tokens), retry_after}
"""


@dataclass(frozen=True, slots=True)
class RateLimitVerdict:
    allowed: bool
    remaining: float
    retry_after_seconds: int


class RateLimiter:
    def __init__(self, redis: Redis, config: RateLimitSettings) -> None:
        self._redis = redis
        self._config = config
        self._script = redis.register_script(_TOKEN_BUCKET_SCRIPT)

    async def _consume(
        self, key: str, *, capacity: int, refill_rate: float, cost: int
    ) -> RateLimitVerdict:
        # A bucket that has been idle long enough to refill completely carries no state
        # worth keeping, so the TTL is the time to go from empty to full.
        ttl = max(60, int(capacity / refill_rate) + 60)
        try:
            allowed, tokens, retry_after = await self._script(
                keys=[key], args=[capacity, refill_rate, cost, ttl]
            )
        except RedisError as exc:
            # Rate limiting is a guardrail, not a correctness requirement: if Redis is down,
            # serving traffic beats failing every request.
            logger.warning("rate_limit.unavailable", key=key, error=str(exc))
            return RateLimitVerdict(allowed=True, remaining=0.0, retry_after_seconds=0)

        return RateLimitVerdict(
            allowed=bool(allowed),
            remaining=float(tokens),
            retry_after_seconds=int(retry_after),
        )

    async def check_chatbot(self, chatbot_id: str, *, cost: int = 1) -> RateLimitVerdict:
        if not self._config.enabled:
            return RateLimitVerdict(True, 0.0, 0)
        return await self._consume(
            f"ratelimit:chatbot:{chatbot_id}",
            capacity=self._config.chatbot_capacity,
            refill_rate=self._config.chatbot_refill_per_second,
            cost=cost,
        )

    async def check_session(
        self, chatbot_id: str, session_id: str, *, cost: int = 1
    ) -> RateLimitVerdict:
        """Note what this is and is not worth.

        `session_id` is generated in the browser, so a caller that wants a fresh bucket simply
        sends a fresh id. This shapes an ordinary visitor's traffic and stops a runaway page
        script; it is not a defence against anything deliberate. `check_ticket_ip` is the one
        that keys on something the caller cannot pick.
        """
        if not self._config.enabled:
            return RateLimitVerdict(True, 0.0, 0)
        return await self._consume(
            f"ratelimit:session:{chatbot_id}:{session_id}",
            capacity=self._config.session_capacity,
            refill_rate=self._config.session_refill_per_second,
            cost=cost,
        )

    async def check_ticket_ip(
        self, chatbot_id: str, address: str, *, cost: int = 1
    ) -> RateLimitVerdict:
        """One client address, one chatbot. Keyed per chatbot so a visitor throttled on one
        tenant's site is not thereby throttled on another's."""
        if not self._config.enabled:
            return RateLimitVerdict(True, 0.0, 0)
        return await self._consume(
            f"ratelimit:ticket:ip:{chatbot_id}:{address}",
            capacity=self._config.ticket_ip_capacity,
            refill_rate=self._config.ticket_ip_refill_per_second,
            cost=cost,
        )

    async def check_ticket_chatbot(self, chatbot_id: str, *, cost: int = 1) -> RateLimitVerdict:
        """The backstop for a distributed attempt, where every request is a new address and
        the per-address bucket therefore never fills."""
        if not self._config.enabled:
            return RateLimitVerdict(True, 0.0, 0)
        return await self._consume(
            f"ratelimit:ticket:chatbot:{chatbot_id}",
            capacity=self._config.ticket_chatbot_capacity,
            refill_rate=self._config.ticket_chatbot_refill_per_second,
            cost=cost,
        )
