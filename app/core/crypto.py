"""Provider credentials at rest.

Tenants type their own API keys into the dashboard, so the platform holds other people's
secrets. Unlike a password these are encrypted rather than hashed: the plaintext has to come
back out to make the call the tenant is paying for.

Nothing in this module logs a key, a ciphertext or a decrypted mapping at any level. The
values pass through as arguments and return values only.
"""

import json
from collections.abc import Mapping
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.exceptions import CredentialsUnreadableError


@lru_cache(maxsize=1)
def _cipher() -> Fernet:
    return Fernet(settings.ai.credentials_encryption_key.encode())


def encrypt_credentials(values: Mapping[str, str]) -> str:
    payload = json.dumps(dict(values), separators=(",", ":")).encode()
    return _cipher().encrypt(payload).decode()


def decrypt_credentials(token: str) -> dict[str, str]:
    try:
        return json.loads(_cipher().decrypt(token.encode()))
    except (InvalidToken, ValueError) as exc:
        # Almost always a rotated AI_CREDENTIALS_ENCRYPTION_KEY: the row is intact, the key
        # that would read it is gone. Nothing can recover it, so say so and ask for the
        # credentials again rather than retrying into the same wall.
        raise CredentialsUnreadableError(
            "Stored provider credentials could not be decrypted. Re-enter them on the "
            "chatbot's AI provider settings."
        ) from exc
