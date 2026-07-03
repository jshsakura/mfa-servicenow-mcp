"""Auth-event diagnostic helpers: value redaction + response forensics.

Extracted verbatim from auth_manager.py (v1.18.25).

v1.12.16: comprehensive auth-event diagnostic helpers.

Cookie *names* alone don't reveal whether values rotated between events;
when ServiceNow kills a session by minting a fresh JSESSIONID and our
captured one becomes stale, names-only logs hide the smoking gun. These
helpers redact values to short prefixes (enough to compare across log
lines without leaking the live credential) and pack the full response
forensics into a single grep-able dict.

auth_manager re-imports every symbol so its namespace stays byte-identical.
"""

from typing import Dict, Optional

import requests

_LOG_COOKIE_VALUE_PREFIX_LEN = 8
_LOG_TOKEN_VALUE_PREFIX_LEN = 8
_LOG_BODY_PREVIEW_LEN = 200
_LOG_HEADER_VALUE_MAX = 240


def _redact_value(value: Optional[str], n: int = _LOG_COOKIE_VALUE_PREFIX_LEN) -> str:
    if not value:
        return "<empty>"
    value = str(value)
    if len(value) <= n:
        return value
    return f"{value[:n]}..."


def _format_cookie_values_for_log(cookie_header: Optional[str]) -> str:
    """Return cookies as 'name=valpref... | name=valpref...' for diagnostics.

    Two log lines emitted seconds apart with identical cookie *names* but
    different prefixes prove the server rotated session cookies between
    capture and use — which is exactly the failure mode we cannot diagnose
    from names-only logs.
    """
    if not cookie_header:
        return "<none>"
    pairs = []
    for piece in cookie_header.split(";"):
        piece = piece.strip()
        if not piece:
            continue
        if "=" in piece:
            name, _, value = piece.partition("=")
            pairs.append(f"{name.strip()}={_redact_value(value.strip())}")
        else:
            pairs.append(piece)
    return " | ".join(pairs) if pairs else "<none>"


def _format_request_cookies_dict_for_log(cookie_map: Optional[Dict[str, str]]) -> str:
    """Same shape as _format_cookie_values_for_log but for the dict form
    used when cookies live in ``kwargs['cookies']`` instead of the Cookie
    header."""
    if not cookie_map:
        return "<none>"
    return " | ".join(f"{n}={_redact_value(v)}" for n, v in cookie_map.items())


def _format_response_diagnostic(
    response: requests.Response,
    body_chars: int = _LOG_BODY_PREVIEW_LEN,
) -> Dict[str, str]:
    """Capture every shred of forensic info a logout/401/302 response can
    carry. Designed to be passed as ``**context`` to ``_auth_event``.

    Fields:
    - status: HTTP status code
    - final_url: requests' resolved URL after redirect-follow (or the
      original URL when allow_redirects=False, which is the more honest
      shape for 302 responses)
    - location: Location header (truncated)
    - set_cookie: Set-Cookie header value (truncated) — server's attempt
      to rotate / revoke / refresh cookies
    - x_usertoken_resp: X-UserToken response header (rotated g_ck), so we
      can see if the server tried to hand back a fresh token even on
      failure
    - content_type: Content-Type header
    - hops: redirect chain as 'NNN Location -> NNN Location'
    - body_head: first N chars of body (newlines stripped)
    """
    out: Dict[str, str] = {
        "status": str(response.status_code),
        "final_url": str(getattr(response, "url", "<n/a>")),
        "location": str(response.headers.get("Location", "-"))[:_LOG_HEADER_VALUE_MAX],
        "set_cookie_resp": str(response.headers.get("Set-Cookie", "-"))[:_LOG_HEADER_VALUE_MAX],
        "x_usertoken_resp": _redact_value(
            response.headers.get("X-UserToken"), _LOG_TOKEN_VALUE_PREFIX_LEN
        ),
        "content_type": str(response.headers.get("Content-Type", "-")),
    }
    hops = []
    try:
        for hop in response.history or ():
            hops.append(f"{hop.status_code} {(hop.headers.get('Location') or '-')[:80]}")
    except Exception:  # noqa: BLE001
        pass
    out["hops"] = " -> ".join(hops) if hops else "-"
    try:
        body = (response.text or "")[:body_chars]
        out["body_head"] = body.replace("\n", " ").replace("\r", " ")
    except Exception:  # noqa: BLE001
        out["body_head"] = "<unreadable>"
    return out
