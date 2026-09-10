"""One provider client per distinct configuration, kept for as long as it is worth keeping.

Before this, every embedding and every completion built a fresh SDK client and dropped it —
three per chat turn — each carrying its own connection pool and none of them closed. The
pools were released only when the garbage collector reached them, which is what made an idle
API pod's memory a record of how much traffic it had served rather than how much it was
serving.

The cache is keyed by the *configuration* and not by the chatbot, so two chatbots pointing at
the same endpoint with the same key share one client, and a chatbot that changes any part of
its setup gets a different key rather than a stale client. The entry still remembers which
chatbots are using it, because a configuration change has to evict the old client rather than
wait an hour for it to expire: a revoked key must stop working when it is revoked.

Worth being explicit about the trade this makes. A decrypted credential used to exist inside
an SDK client for the length of one request; it now lives in one for as long as the client
does. That is what invalidation and the TTL are for, and it is why the key is a digest —
the plaintext is never a dict key, a log field or a metric label — but the plaintext is
resident either way, and this makes it resident for longer.
"""

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)

# A client is a connection pool and a few hundred kilobytes of SDK state, so the cap is about
# bounding the tail rather than saving space: 256 distinct provider configurations live at
# once is already far more than any single pod serves, and past that the least recently used
# one is the one nobody is coming back for.
CAPACITY = 256
# Long enough that a busy chatbot never rebuilds, short enough that a pod idle overnight is
# not still holding sockets to an endpoint in the morning.
TTL_SECONDS = 3600


@dataclass(slots=True)
class _Entry:
    client: Any
    expires_at: float
    owners: set[UUID] = field(default_factory=set)


# Ordered by last use: the front is the eviction end.
_entries: OrderedDict[str, _Entry] = OrderedDict()


def cache_key(*parts: object) -> str:
    """A stable digest of everything a client was built from.

    Credentials are part of what identifies a client and so have to be part of the key, which
    is exactly why the key is a digest: the plaintext is hashed here and never becomes a dict
    key, a log field or a metric label. Only the first 12 characters are ever logged.
    """
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _take(key: str, owner: UUID, build: Callable[[], Any]) -> tuple[Any, list[Any]]:
    """Look up or build, without awaiting once.

    That is the whole of the concurrency argument, and it is why this is not an `async def`:
    a coroutine yields only at an `await`, so a lookup, a construction and an insert with no
    await between them cannot interleave with another request doing the same. Closing an
    evicted client *does* await, so the victims are handed back to be closed once the cache is
    consistent again rather than half-way through making it so.
    """
    now = time.monotonic()
    victims: list[Any] = []

    entry = _entries.get(key)
    if entry is not None and entry.expires_at <= now:
        _entries.pop(key, None)
        victims.append(entry.client)
        entry = None

    if entry is None:
        entry = _Entry(client=build(), expires_at=now + TTL_SECONDS)
        _entries[key] = entry
        logger.debug("ai.client_built", key=key[:12], size=len(_entries))

    entry.owners.add(owner)
    _entries.move_to_end(key)

    while len(_entries) > CAPACITY:
        _, evicted = _entries.popitem(last=False)
        victims.append(evicted.client)

    return entry.client, victims


async def acquire(key: str, *, owner: UUID, build: Callable[[], Any]) -> Any:
    """The cached client for `key`, building one if this configuration is new here."""
    client, victims = _take(key, owner, build)
    await _close_all(victims)
    return client


async def invalidate(owner: UUID) -> None:
    """Drop every client a chatbot is using, because its configuration just changed.

    A scan of at most `CAPACITY` entries, on a path that runs when someone saves a form. The
    alternative — a second index from chatbot to key — would be a structure to keep in step
    with this one, and getting that wrong is how a revoked credential stays live.
    """
    doomed = [key for key, entry in _entries.items() if owner in entry.owners]
    victims = [_entries.pop(key).client for key in doomed]
    if victims:
        logger.info("ai.clients_invalidated", chatbot_id=str(owner), count=len(victims))
    await _close_all(victims)


async def close_all() -> None:
    """Release everything, on process shutdown and between tests."""
    victims = [entry.client for entry in _entries.values()]
    _entries.clear()
    await _close_all(victims)


def size() -> int:
    return len(_entries)


async def _close_all(victims: list[Any]) -> None:
    for victim in victims:
        await victim.aclose()
