from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import uuid4

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool: ConnectionPool | None = None
_client: Redis | None = None


def get_redis() -> Redis:
    """One shared pool per process; the client itself is cheap and safe to reuse."""
    global _pool, _client
    if _client is None:
        _pool = ConnectionPool.from_url(
            str(settings.redis.url),
            max_connections=settings.redis.max_connections,
            decode_responses=True,
        )
        _client = Redis(connection_pool=_pool)
    return _client


async def close_redis() -> None:
    global _pool, _client
    if _client is not None:
        await _client.aclose()
        _client = None
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def check_redis_health() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:  # noqa: BLE001 - health probes must never raise
        return False


# Compare-and-delete. A holder that overran its TTL must not release a lock that by then
# belongs to the run which replaced it — a plain DEL would let a third run start alongside
# the second.
_RELEASE_IF_HELD = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


@asynccontextmanager
async def held_lock(key: str, *, ttl_seconds: int) -> AsyncGenerator[bool]:
    """Try to take a mutually exclusive lock, and always give back only your own.

    Yields whether it was acquired rather than blocking or raising: every caller so far wants
    to skip its work when someone else is already doing it, not to queue behind them. The
    token is generated here because it exists solely to make the release safe.
    """
    redis = get_redis()
    token = uuid4().hex
    acquired = bool(await redis.set(key, token, nx=True, ex=ttl_seconds))
    try:
        yield acquired
    finally:
        if acquired:
            await redis.eval(_RELEASE_IF_HELD, 1, key, token)
