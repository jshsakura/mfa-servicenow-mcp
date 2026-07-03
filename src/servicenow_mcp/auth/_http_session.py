"""HTTP session factory, TLS impersonation, and cross-origin redirect safety.

Extracted verbatim from auth_manager.py (v1.18.25) as part of decomposing the
module-level helper surface into focused, individually-tested modules. Behavior
is unchanged — auth_manager re-imports every symbol here so its namespace (and
the tests that patch/import it) stay byte-identical.
"""

import logging
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("servicenow_mcp.auth.auth_manager")

_SESSION_POOL_SIZE = 20  # Max connections per host (default urllib3 is 10)
_SESSION_MAX_RETRIES_CONNECT = 0  # Connection-level retries handled by make_request


# v1.12.21: TLS impersonation default-ON via the
# SERVICENOW_TLS_IMPERSONATE environment variable, with tri-state semantics:
#
#   unset  → use ``chrome120`` profile (the default, after field evidence
#            on a JA3-gated customer instance showed rejection of stock Python
#            ``requests``; turning this on by default catches the next
#            user hitting the symptom without forcing them to find an
#            env-var flag).
#   off / false / 0 / disable / no  → stock requests.Session, explicit
#            opt-out for instances where impersonation either isn't
#            needed or causes regressions.
#   anything else  → use the value as the curl_cffi impersonation profile
#            name (e.g. ``chrome131``, ``chrome120_arm64``, ``safari17_0``).
#
# curl_cffi routes through libcurl-impersonate (BoringSSL fork). That
# makes our TLS handshake byte-for-byte identical to a real browser —
# matching JA3/JA4 fingerprint, TLS extension order, GREASE values, HTTP/2
# SETTINGS frames, and ALPN. ServiceNow instances fronted by JA3-based
# bot detection (Cloudflare, Akamai, ServiceNow's own) reject Python's
# stock requests with 302→/logout_success.do regardless of whether the
# session cookies are valid; impersonation is the only client-side fix.
_TLS_IMPERSONATE_ENV_VAR = "SERVICENOW_TLS_IMPERSONATE"
_TLS_IMPERSONATE_DEFAULT_PROFILE = "chrome120"
_TLS_IMPERSONATE_OFF_VALUES = frozenset({"off", "false", "0", "disable", "disabled", "no", "none"})


def _describe_http_session(session) -> str:
    """Return a short label for the active HTTP session: 'curl_cffi:<profile>'
    when libcurl-impersonate is in play, otherwise 'requests'.

    Used by ``_auth_event`` so every emitted auth_event line carries the
    wire-layer identity. Two events with identical cookies but different
    ``http_client`` values mean a wire-layer switch (default-ON flipped
    off, or curl_cffi failed init and we fell back); a routing or
    fingerprint regression then localizes to that boundary.
    """
    cls = type(session)
    module = getattr(cls, "__module__", "") or ""
    if "curl_cffi" in module:
        impersonate = (
            getattr(session, "impersonate", None) or getattr(session, "_impersonate", None) or "?"
        )
        return f"curl_cffi:{impersonate}"
    return "requests"


def _resolve_tls_impersonate_profile():
    """Apply the tri-state env var semantics; returns the curl_cffi profile
    name to use, or ``None`` for the explicit-off branch.

    Pulled out so tests and tooling can read the resolution without
    spinning up a full session.
    """
    import os

    raw = (os.environ.get(_TLS_IMPERSONATE_ENV_VAR) or "").strip()
    if not raw:
        return _TLS_IMPERSONATE_DEFAULT_PROFILE
    if raw.lower() in _TLS_IMPERSONATE_OFF_VALUES:
        return None
    return raw


# Request headers that carry credentials and MUST NOT be re-sent when a
# redirect leaves the ServiceNow origin. requests strips Authorization on a
# cross-host redirect, but NOT a manually-set Cookie / X-UserToken / custom key
# header — and curl_cffi (libcurl) re-sends every custom header regardless of
# host. Both leak without this. Lowercased for case-insensitive matching.
_CROSS_ORIGIN_STRIP_HEADERS = frozenset({"cookie", "authorization", "x-usertoken", "x-csrf-token"})
_MAX_MANUAL_REDIRECTS = 10


def _same_origin(from_url: str, to_url: str) -> bool:
    """True if *to_url* stays on the same scheme://host:port as *from_url*.

    A relative Location (no scheme/netloc) is same-origin by definition. Default
    ports are normalised so ``https://x`` and ``https://x:443`` compare equal.
    """
    a, b = urlparse(from_url), urlparse(to_url)
    if not b.netloc:
        return True
    _default = {"https": 443, "http": 80}

    def _key(p):
        scheme = (p.scheme or "").lower()
        host = (p.hostname or "").lower()
        port = p.port or _default.get(scheme)
        return (scheme, host, port)

    return _key(a) == _key(b)


def _strip_sensitive_headers(headers, extra_sensitive):
    """Return a copy of *headers* with credential headers removed (case-insensitive)."""
    if not headers:
        return headers
    blocked = _CROSS_ORIGIN_STRIP_HEADERS | extra_sensitive
    return {k: v for k, v in dict(headers).items() if k.lower() not in blocked}


class _SafeRedirectSession:
    """Wraps an HTTP session so ``request()`` follows redirects MANUALLY and
    strips credential headers on any hop that leaves the ServiceNow origin.

    Why a wrapper and not ``allow_redirects=False`` at every call site: the
    codebase inspects ``response.history`` to detect logout/session-death, so
    redirects must still be followed and history preserved — just not with the
    auth headers leaking cross-origin. Only ``request()`` is wrapped (the
    authenticated API path); ``get``/``post`` (probe, OAuth token, login) are
    delegated untouched. Healthy 200s never redirect, so normal traffic takes
    the same single call as before — the manual loop only engages on the 3xx
    (already session-dead) path this protects.
    """

    def __init__(self, inner):
        self._inner = inner
        self._extra_sensitive: set = set()

    def __getattr__(self, name):
        # Non-verb attributes (headers, cookies, close, impersonate, ...) delegate
        # to the wrapped session unchanged.
        return getattr(self._inner, name)

    # HTTP verb helpers route through THIS wrapper's request() — exactly like
    # requests.Session, whose .get/.post call self.request. Without them, verb
    # calls would reach inner.request directly, bypassing the redirect safety
    # (and, in tests, any patch of the wrapper's request).
    def get(self, url, **kwargs):
        kwargs.setdefault("allow_redirects", True)
        return self.request("GET", url, **kwargs)

    def options(self, url, **kwargs):
        kwargs.setdefault("allow_redirects", True)
        return self.request("OPTIONS", url, **kwargs)

    def head(self, url, **kwargs):
        kwargs.setdefault("allow_redirects", False)
        return self.request("HEAD", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)

    def register_sensitive_header(self, name: str) -> None:
        """Also strip *name* cross-origin (e.g. a custom API-key header)."""
        if name:
            self._extra_sensitive.add(name.lower())

    def request(self, method, url, **kwargs):
        follow = kwargs.pop("allow_redirects", True)
        history = []
        cur_method, cur_url = method, url
        while True:
            resp = self._inner.request(cur_method, cur_url, allow_redirects=False, **kwargs)
            location = resp.headers.get("Location") if resp.headers else None
            is_redirect = 300 <= resp.status_code < 400 and bool(location)
            if not follow or not is_redirect or len(history) >= _MAX_MANUAL_REDIRECTS:
                try:
                    resp.history = history
                except Exception:  # pragma: no cover — Response without settable history
                    pass
                return resp
            history.append(resp)
            next_url = urljoin(cur_url, location)
            if not _same_origin(cur_url, next_url):
                # THE FIX: never forward credentials to another origin.
                kwargs["headers"] = _strip_sensitive_headers(
                    kwargs.get("headers"), self._extra_sensitive
                )
                kwargs.pop("cookies", None)
            # Redirect method semantics (mirrors requests): 303 and a non-idempotent
            # 301/302 downgrade to GET and drop the body; 307/308 preserve.
            if resp.status_code in (301, 302, 303) and cur_method.upper() not in ("GET", "HEAD"):
                cur_method = "GET"
                for body_key in ("data", "json", "files", "content"):
                    kwargs.pop(body_key, None)
            cur_url = next_url


def _build_http_session():
    """Create the HTTP session for ServiceNow API calls.

    Env-var-driven (v1.12.21 default-ON, tri-state):
      - unset       → curl_cffi.Session(impersonate='chrome120')
      - off/false/0 → stock requests.Session (explicit opt-out)
      - <name>      → curl_cffi.Session(impersonate=<name>)

    See _resolve_tls_impersonate_profile for the resolution rules. The
    return type is intentionally untyped — curl_cffi's Session is API-
    compatible with ``requests.Session`` for the methods we actually call
    (``.request``, ``.headers``, ``.cookies``, ``.close``) but is NOT a
    subclass, so typing it as ``requests.Session`` would lie. Callers stay
    duck-typed.

    Benefits of pooling (stock-requests path):
    - TCP keep-alive: avoids 3-way handshake on every call
    - TLS session resumption: saves ~100-300ms per request
    - urllib3 connection pool: reuses sockets across threads
    """
    import os

    raw_env = (os.environ.get(_TLS_IMPERSONATE_ENV_VAR) or "").strip()
    impersonate = _resolve_tls_impersonate_profile()
    if impersonate:
        # Default ON path or explicit profile name. Any failure (import,
        # wrong profile, init error) logs a clear warning and falls
        # through to stock requests, so a bad env var never breaks a
        # working install.
        try:
            from curl_cffi import requests as cffi_requests  # type: ignore
        except ImportError:
            logger.warning(
                "TLS impersonation requested (profile=%s, %s=%r) but "
                "curl_cffi is not importable. curl_cffi is a regular "
                "dependency as of v1.12.20; if this fires, the install "
                "is incomplete. Falling back to stock requests — "
                "JA3-gated ServiceNow instances will reject. To suppress "
                "this attempt entirely, set %s=off.",
                impersonate,
                _TLS_IMPERSONATE_ENV_VAR,
                raw_env or "<unset (default)>",
                _TLS_IMPERSONATE_ENV_VAR,
            )
        else:
            try:
                session = cffi_requests.Session(impersonate=impersonate)
            except Exception as exc:  # noqa: BLE001 — bad profile name etc.
                logger.warning(
                    "curl_cffi.Session(impersonate=%r) failed: %s. "
                    "Falling back to stock requests. Set %s=off to skip "
                    "this attempt, or pick a different profile (chrome131, "
                    "chrome120_arm64, safari17_0, etc.).",
                    impersonate,
                    exc,
                    _TLS_IMPERSONATE_ENV_VAR,
                )
            else:
                session.headers.update({"Accept-Encoding": "gzip, deflate"})
                logger.info(
                    "HTTP session: curl_cffi impersonate=%s (TLS "
                    "handshake matches a real browser to defeat JA3-based "
                    "bot detection on hardened ServiceNow instances). "
                    "Env source: %s=%r%s",
                    impersonate,
                    _TLS_IMPERSONATE_ENV_VAR,
                    raw_env,
                    " (default applied: empty value → chrome120)" if not raw_env else "",
                )
                return _SafeRedirectSession(session)
    else:
        logger.info(
            "HTTP session: stock requests (TLS impersonation explicitly "
            "disabled via %s=%r). Switch back on by unsetting the env "
            "var if a hardened instance starts rejecting calls.",
            _TLS_IMPERSONATE_ENV_VAR,
            raw_env,
        )

    session = requests.Session()
    # Enable gzip/deflate — reduces payload 60-80% on large JSON responses.
    # NOTE: Do NOT set Accept or Content-Type here — individual requests set
    # these via get_headers(). Setting Accept: application/json at session
    # level breaks browser auth (login page expects HTML negotiation).
    session.headers.update({"Accept-Encoding": "gzip, deflate"})
    # Disable automatic cookie handling — browser auth manages cookies manually
    # via the Cookie header. Session-level cookie jar would conflict.
    session.cookies.clear()
    session.trust_env = False  # Skip .netrc / env proxy cookies
    # urllib3 retries are deliberately disabled (connect=0, read=0). Transient
    # network errors (ConnectionError / Timeout, including ReadTimeout) and
    # transient upstream 5xx responses (502/503/504) are retried at the
    # application layer in AuthManager.make_request, which gives us:
    #   - identical backoff/logging across both exception and 5xx paths,
    #   - awareness of browser-session re-auth for 401, and
    #   - the ability to surface intermediate state to the LLM caller.
    # See make_request's `for attempt in range(1 + max_transient_retries)` loop.
    adapter = HTTPAdapter(
        pool_connections=_SESSION_POOL_SIZE,
        pool_maxsize=_SESSION_POOL_SIZE,
        max_retries=Retry(connect=_SESSION_MAX_RETRIES_CONNECT, read=0),
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return _SafeRedirectSession(session)
