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
