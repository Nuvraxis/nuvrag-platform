import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import SecuritySettings
from app.core.exceptions import AuthenticationError

TokenType = Literal["access", "refresh"]

_password_hash = PasswordHash.recommended()

PUBLIC_KEY_PREFIX = "pk"
SECRET_KEY_PREFIX = "sk"


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """A stored hash that is corrupt or was written by a retired hasher must fail the login,
    not raise — otherwise one bad row turns into a 500 on the auth path."""
    try:
        return _password_hash.verify(password, hashed)
    except UnknownHashError, ValueError, TypeError:
        return False


def create_token(
    *,
    subject: UUID,
    org_id: UUID,
    role: str,
    token_type: TokenType,
    config: SecuritySettings,
) -> str:
    ttl = (
        config.access_token_ttl_seconds
        if token_type == "access"
        else config.refresh_token_ttl_seconds
    )
    issued_at = utcnow()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "org": str(org_id),
        "role": role,
        "type": token_type,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=ttl),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)


def decode_token(
    token: str, *, expected_type: TokenType, config: SecuritySettings
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret,
            algorithms=[config.jwt_algorithm],
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Token is invalid") from exc

    if payload.get("type") != expected_type:
        raise AuthenticationError(f"Expected a {expected_type} token")
    return payload


def generate_public_key(environment: str) -> str:
    """Widget-facing identifier. Embedded in tenant HTML, so it is an identifier, not a secret."""
    scope = "live" if environment == "production" else "test"
    return f"{PUBLIC_KEY_PREFIX}_{scope}_{secrets.token_urlsafe(24)}"


def generate_secret_key(environment: str) -> str:
    scope = "live" if environment == "production" else "test"
    return f"{SECRET_KEY_PREFIX}_{scope}_{secrets.token_urlsafe(32)}"


def hash_api_key(key: str) -> str:
    """Secret keys are high-entropy, so a fast digest is appropriate (unlike passwords)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_api_key(key: str, hashed: str) -> bool:
    return hmac.compare_digest(hash_api_key(key), hashed)


# How much of a session digest reaches a log line. Enough to correlate one visitor's turns
# with each other; far too little to reconstruct the value it came from.
_SESSION_LOG_ID_CHARS = 12


def session_log_id(external_session_id: str) -> str:
    """A correlator for logs, never the session id itself.

    Since iteration 7 the session id also replays a conversation's transcript, which makes it
    a bearer capability rather than a label — and a capability does not belong in a log line
    that ships to an aggregator and outlives the session by months. A truncated digest
    correlates the turns of one conversation exactly as well and grants nothing.

    Lives here, beside the hash it is built from, rather than in whichever service happened to
    need it first: two of them do now, and it was the import back into one of those that made
    the memory module and the chat path circular.
    """
    return hash_api_key(external_session_id)[:_SESSION_LOG_ID_CHARS]
