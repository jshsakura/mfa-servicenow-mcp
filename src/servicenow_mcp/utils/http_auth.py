"""Auth policy for the HTTP transport.

The HTTP transport mounts the full ServiceNow tool surface (including writes)
and drives it with the server's stored ServiceNow credentials. On loopback that
is fine — only local processes reach it. But a non-loopback bind
(``--http-host 0.0.0.0`` / a LAN IP) exposes that surface to the network with no
identity check. This module centralises the two rules:

1. A non-loopback bind REQUIRES a bearer token — refuse to start otherwise
   (fail closed, with an actionable message).
2. When a token is configured, every MCP request must present
   ``Authorization: Bearer <token>`` (constant-time compared). ``/health`` stays
   open (liveness only, no data).

Pure functions here; the CLI wires them to argparse + the ASGI app.
"""

from __future__ import annotations

import hmac

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", ""})


def is_loopback_host(host: str | None) -> bool:
    """True if *host* only accepts connections from the local machine.

    ``0.0.0.0`` / ``::`` are NOT loopback — they bind every interface. An empty
    host is treated as loopback (uvicorn's own default is 127.0.0.1)."""
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


class HttpAuthError(ValueError):
    """Raised when the HTTP transport is configured insecurely."""


def resolve_http_auth_token(host: str | None, token: str | None) -> str | None:
    """Validate the (host, token) pair and return the effective token.

    - non-loopback host + no token → HttpAuthError (fail closed).
    - token given → returned (enforced even on loopback; defence in depth).
    - loopback + no token → None (frictionless local default).
    A whitespace-only token counts as no token.
    """
    token = (token or "").strip() or None
    if token is None and not is_loopback_host(host):
        raise HttpAuthError(
            f"HTTP transport bound to non-loopback host '{host}' without an auth token. "
            "Anyone who can reach this port would drive all tools with your ServiceNow "
            "credentials. Set --http-auth-token / SERVICENOW_MCP_HTTP_AUTH_TOKEN, or bind "
            "to 127.0.0.1."
        )
    return token


def is_authorized(auth_header: str | None, expected_token: str) -> bool:
    """Constant-time check of an ``Authorization: Bearer <token>`` header."""
    if not auth_header:
        return False
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    return hmac.compare_digest(parts[1].strip(), expected_token)
