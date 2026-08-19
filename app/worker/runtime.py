import asyncio
import threading
from collections.abc import Coroutine
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None

SHUTDOWN_TIMEOUT_SECONDS = 30


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread

    with _lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            _thread = threading.Thread(target=_loop.run_forever, name="worker-asyncio", daemon=True)
            _thread.start()
        return _loop


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Execute a coroutine on this process's long-lived event loop.

    Celery tasks are synchronous, so the obvious implementation is `asyncio.run()` per task.
    That is wrong here: the SQLAlchemy engine, its asyncpg connections and the Redis pool are
    module-level singletons, and asyncpg binds every connection to the loop that opened it.
    A per-task loop means the second task in a worker inherits pooled connections belonging
    to a loop that has already closed, which surfaces as "attached to a different loop" or
    "Event loop is closed".

    One loop per process keeps every connection on the loop that created it, and works the
    same under the prefork, threads and solo pools.
    """
    return asyncio.run_coroutine_threadsafe(coro, _ensure_loop()).result()


async def _release_resources() -> None:
    from app.db.session import dispose_engines
    from app.services.redis_client import close_redis
    from app.services.storage import close_object_storage

    await dispose_engines()
    await close_redis()
    await close_object_storage()


def shutdown() -> None:
    """Close pooled connections on the loop that owns them, then stop that loop."""
    global _loop, _thread

    with _lock:
        loop, thread = _loop, _thread
        _loop, _thread = None, None

    if loop is None or loop.is_closed():
        return

    try:
        asyncio.run_coroutine_threadsafe(_release_resources(), loop).result(
            timeout=SHUTDOWN_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 - shutdown must not raise out of a signal handler
        logger.warning("worker.resource_release_failed", error=str(exc))
    finally:
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=5)
        loop.close()
