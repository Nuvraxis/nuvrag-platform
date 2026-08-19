"""Work out which client a public request came from, for rate limiting.

The widget's own identifiers are all chosen by the caller. `session_id` is generated in the
browser, the public key is in the tenant's page source, and `Origin` is set by browsers rather
than by the network — so a script can present a fresh one of each on every request and walk
straight past a bucket keyed on any of them. The client address is the one identifier a
caller cannot simply pick, which is what makes it worth keying on.

Behind a proxy it has to be read from a header, and which header matters:

  * `X-Forwarded-For` is **appended to**. A client that sends one of its own leaves its value
    at the front of the list, so the leftmost entry — the one uvicorn hands back as
    `request.client.host` under `--forwarded-allow-ips '*'` — is caller-controlled.
  * `CF-Connecting-IP` is **overwritten** by Cloudflare on every proxied request, so a value
    the caller supplies is discarded rather than believed.

Hence the default. It carries one assumption, and it is load-bearing: **the origin must not be
reachable except through the proxy.** If it is, a caller can skip the proxy and set the header
itself, and every guarantee here evaporates. Cloudflare Tunnel, or a firewall restricted to
the proxy's address ranges, is what holds that up — see the README.
"""

import ipaddress
from typing import TYPE_CHECKING

from app.core.config import settings
from app.core.security import hash_api_key

if TYPE_CHECKING:
    from fastapi import Request

# Enough to tell two visitors apart in a log; far too little to recover the address, which is
# personal data under every regime this is likely to run in. Same reasoning, and the same
# length, as `session_log_id`.
_IP_LOG_ID_CHARS = 12

# The bucket every unidentifiable caller shares. Deliberately not "allow": a request with no
# usable address behind a correctly configured proxy is anomalous, and letting it opt out of
# the per-client limit by presenting nothing would be a hole rather than a fallback.
UNKNOWN_CLIENT = "unknown"


def client_ip(request: Request) -> str:
    """The caller's address, or `UNKNOWN_CLIENT`.

    Parsed rather than pattern-matched, and never passed through unvalidated: this value ends
    up in a Redis key, and an unbounded string from a header is not something to concatenate
    into one.
    """
    header = settings.security.client_ip_header
    candidate = request.headers.get(header) if header else None

    # Cloudflare sends a bare address here. A comma-separated list means something upstream is
    # behaving like `X-Forwarded-For`, and only the last entry can have been added by a proxy
    # this side of the caller.
    if candidate and "," in candidate:
        candidate = candidate.rsplit(",", 1)[-1]

    if not candidate and request.client is not None:
        candidate = request.client.host

    return _validated(candidate)


def _validated(candidate: str | None) -> str:
    if not candidate:
        return UNKNOWN_CLIENT
    try:
        return ipaddress.ip_address(candidate.strip()).compressed
    except ValueError:
        return UNKNOWN_CLIENT


def client_log_id(address: str) -> str:
    """A correlator for logs, never the address itself."""
    if address == UNKNOWN_CLIENT:
        return address
    return hash_api_key(address)[:_IP_LOG_ID_CHARS]
