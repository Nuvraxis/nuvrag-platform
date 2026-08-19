"""Deny-list for issued tokens.

JWTs are stateless, which is what keeps the API horizontally scalable — but it also means a
signed-out session, a removed teammate or a compromised token stays valid until it expires.
The deny-list is the smallest thing that closes that gap: one Redis key per revoked `jti`,
expiring exactly when the token would have anyway, so the list is bounded by the refresh TTL
rather than growing without limit.

Only refresh tokens are checked on the hot path. Access tokens live fifteen minutes and are
verified on every request, so checking them too would add a Redis round trip to each call to
shave at most fifteen minutes off an already-short window. Revoking a user's refresh token
stops the session at its next renewal, and `get_active_user` already refuses a deactivated
account immediately.
"""

from datetime import datetime
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import utcnow
from app.services.redis_client import get_redis

logger = get_logger(__name__)

_USER_EPOCH_PREFIX = "auth:user-epoch:"


def _token_key(jti: str) -> str:
    return f"{settings.security.revocation_key_prefix}{jti}"


def _user_key(user_id: UUID) -> str:
    return f"{_USER_EPOCH_PREFIX}{user_id}"


def _seconds_until(expires_at: datetime | None) -> int:
    """How long the deny-list entry has to outlive the token it revokes.

    A token with no readable expiry is pinned for the full refresh lifetime, which is the
    longest it could possibly have been valid for.
    """
    if expires_at is None:
        return settings.security.refresh_token_ttl_seconds
    remaining = int((expires_at - utcnow()).total_seconds())
    return max(1, min(remaining, settings.security.refresh_token_ttl_seconds))


async def revoke_token(jti: str, *, expires_at: datetime | None = None) -> None:
    await get_redis().set(_token_key(jti), "1", ex=_seconds_until(expires_at))


async def is_token_revoked(jti: str | None) -> bool:
    if not jti:
        # A token minted before `jti` was issued cannot be revoked individually. Treating it
        # as live rather than dead avoids signing everyone out on deploy; the user-level
        # cut-off below still covers it.
        return False
    return await get_redis().exists(_token_key(jti)) == 1


async def revoke_all_for_user(user_id: UUID) -> None:
    """Invalidate every token this user currently holds.

    Individual `jti`s are not tracked per user — that would need a set per user with its own
    cleanup. Instead a cut-off timestamp is recorded, and any token issued before it is
    rejected. One key per user, expiring with the longest-lived token it could affect.
    """
    await get_redis().set(
        _user_key(user_id),
        str(int(utcnow().timestamp())),
        ex=settings.security.refresh_token_ttl_seconds,
    )


async def issued_before_cutoff(user_id: UUID, issued_at: int | None) -> bool:
    raw = await get_redis().get(_user_key(user_id))
    if raw is None:
        return False
    if issued_at is None:
        return True
    # `<=` rather than `<`: a token minted in the same second as the cut-off is on the wrong
    # side of it, since JWT `iat` has one-second resolution.
    return issued_at <= int(raw)
