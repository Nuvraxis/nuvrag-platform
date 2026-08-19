import re
import secrets
import unicodedata
from collections.abc import Awaitable, Callable

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

# Beyond this many sequential attempts the name is pathologically common, so a random
# suffix ends the search instead of walking the counter upward forever.
_MAX_SEQUENTIAL_ATTEMPTS = 25


def slugify(value: str, *, max_length: int = 100, fallback: str = "item") -> str:
    """URL-safe identifier derived from a display name.

    Accented characters are folded to their ASCII base rather than dropped, so "Café Wörld"
    becomes "cafe-world" instead of "caf-rld".
    """
    normalised = unicodedata.normalize("NFKD", value)
    ascii_only = normalised.encode("ascii", "ignore").decode("ascii")
    slug = _NON_ALPHANUMERIC.sub("-", ascii_only.lower()).strip("-")
    return slug[:max_length].strip("-") or fallback


def _with_suffix(base: str, suffix: str, max_length: int) -> str:
    trimmed = base[: max_length - len(suffix)].rstrip("-")
    return f"{trimmed}{suffix}"


async def unique_slug(
    base: str,
    exists: Callable[[str], Awaitable[bool]],
    *,
    max_length: int = 100,
) -> str:
    """Find a free slug near `base`, appending -2, -3, … until one is available.

    `exists` narrows the search to the right scope — organisation slugs are globally unique
    while chatbot slugs only need to be unique within their organisation.
    """
    if not await exists(base):
        return base

    for attempt in range(2, _MAX_SEQUENTIAL_ATTEMPTS + 2):
        candidate = _with_suffix(base, f"-{attempt}", max_length)
        if not await exists(candidate):
            return candidate

    return _with_suffix(base, f"-{secrets.token_hex(4)}", max_length)


def randomised_slug(base: str, *, max_length: int = 100) -> str:
    """Fallback for when a unique-constraint race beats the pre-flight check."""
    return _with_suffix(base, f"-{secrets.token_hex(4)}", max_length)
