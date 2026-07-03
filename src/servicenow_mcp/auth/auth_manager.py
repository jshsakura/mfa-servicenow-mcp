"""
Authentication manager for the ServiceNow MCP server.
"""

import base64
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urljoin, urlparse

import requests

from ..utils.config import AuthConfig, AuthType, BrowserAuthConfig
from ._browser_dom import (  # noqa: F401
    _PROFILE_LOCK_HINTS,
    PASSWORD_SELECTORS,
    SUBMIT_SELECTORS,
    USERNAME_SELECTORS,
    _click_first_matching,
    _ensure_private_dir,
    _fill_first_matching,
    _is_debug_mode,
    _launch_persistent_with_retry,
    _selector_exists,
    _target_label,
)
from ._cookies import (  # noqa: F401
    _cookie_header_to_dict,
    _extract_cookie_names,
    _replace_cookie_value_in_header,
)
from ._diagnostics import (  # noqa: F401
    _LOG_BODY_PREVIEW_LEN,
    _LOG_COOKIE_VALUE_PREFIX_LEN,
    _LOG_HEADER_VALUE_MAX,
    _LOG_TOKEN_VALUE_PREFIX_LEN,
    _format_cookie_values_for_log,
    _format_request_cookies_dict_for_log,
    _format_response_diagnostic,
    _redact_value,
)
from ._http_session import (  # noqa: F401
    _CROSS_ORIGIN_STRIP_HEADERS,
    _MAX_MANUAL_REDIRECTS,
    _SESSION_MAX_RETRIES_CONNECT,
    _SESSION_POOL_SIZE,
    _TLS_IMPERSONATE_DEFAULT_PROFILE,
    _TLS_IMPERSONATE_ENV_VAR,
    _TLS_IMPERSONATE_OFF_VALUES,
    _build_http_session,
    _describe_http_session,
    _resolve_tls_impersonate_profile,
    _SafeRedirectSession,
    _same_origin,
    _strip_sensitive_headers,
)
from ._response_predicates import (  # noqa: F401
    _STALE_PROFILE_COOKIE_NAMES,
    _extract_bigip_routing_hint,
    _response_confirms_browser_probe_session,
    _response_indicates_acl_block,
    _response_indicates_authenticated_session,
    _response_indicates_login_redirect,
    _response_redirected_through_logout,
)
from ._url_predicates import (  # noqa: F401
    USER_CLOSE_ERROR_MARKERS,
    _is_login_page_url,
    _is_mfa_challenge_url,
    _looks_like_user_close,
)

logger = logging.getLogger(__name__)

# Bounded retries for capturing window.g_ck after the post-login navigation.
# Module-level constants so tests can monkeypatch them down to keep the
# polling loop fast under mocked time.sleep. See _login_with_browser_sync.
GCK_CAPTURE_MAX_ATTEMPTS = 8
GCK_CAPTURE_INTERVAL_SECONDS = 1.0

# v1.11.48: circuit breaker threshold for consecutive 302→/logout_success.do
# responses. Once the server has rejected this many sessions in a row —
# including ones minted via fresh full-MFA login — keep re-authenticating
# is hopeless and just punishes the user with repeated MFA prompts. After
# the threshold, raise SELF_HEAL_CIRCUIT_OPEN instead. Counter resets on
# any successful response via _mark_browser_session_recently_valid, so a
# transient server hiccup never trips the breaker.
_SELF_HEAL_CIRCUIT_THRESHOLD = 3

# v1.12.0: hard minimum interval between two browser-login attempts. Even
# below the circuit-breaker threshold, firing login.do repeatedly inside
# a few seconds looks like brute-force from the server's side and can
# get the account flagged. This cooldown enforces a "safe zone" — at
# least this many seconds must elapse between successive login attempts.
_MIN_LOGIN_INTERVAL_SECONDS = 60.0

# v1.12.1: throttle interval for the circuit-breaker escape probe.
# When the self-heal circuit is open, BEFORE refusing the next call we
# attempt one cheap session probe to /sys_user_preference. If the session
# has recovered (instance policy cleared, idle timer reset, etc.), reset
# the counter and let the call through. Throttle so we probe at most
# once every N seconds — avoids hammering the server when it really is
# rejecting everything. Prior to v1.12.1, an open circuit could only be
# cleared by restarting MCP, which made transient policy hiccups feel
# like permanent failures.
# v1.12.11: dropped 30s → 10s. The probe is one cheap GET; the previous
# value made an open circuit feel like a 30-second blackout even when the
# session had already recovered. 10s is still well above any sane retry
# storm yet recovers fast enough that the user does not perceive it as
# a hard block.
_CIRCUIT_ESCAPE_PROBE_INTERVAL_SECONDS = 10.0


# Auto-download the matching Chromium build when it's missing at startup (e.g.
# uvx pulled a newer Playwright than the cached browser). Background-only, so it
# never blocks the MCP handshake. Opt out with SERVICENOW_AUTO_INSTALL_CHROMIUM.
_AUTO_INSTALL_CHROMIUM_ENV_VAR = "SERVICENOW_AUTO_INSTALL_CHROMIUM"
_AUTO_INSTALL_CHROMIUM_OFF_VALUES = _TLS_IMPERSONATE_OFF_VALUES
_AUTO_INSTALL_CHROMIUM_TIMEOUT_SECONDS = 600.0


class AuthManager:
    """
    Authentication manager for ServiceNow API.

    This class handles authentication with the ServiceNow API using
    different authentication methods.
    """

    def __init__(self, config: AuthConfig, instance_url: Optional[str] = None):
        """
        Initialize the authentication manager.

        Args:
            config: Authentication configuration.
            instance_url: ServiceNow instance URL.
        """
        self.config = config
        self.instance_url = instance_url
        self.logger = logger
        # Annotated requests.Session for static analysis: it lets mypy resolve
        # the .request()/.headers/.cookies call sites across this file to the
        # structural interface we use. At runtime this is usually a curl_cffi
        # Session (default; not a requests.Session subclass) which is API-
        # compatible for those methods — see _build_http_session's docstring.
        self._http_session: requests.Session = _build_http_session()
        # An API-key custom header is also a credential — strip it cross-origin.
        if config.type == AuthType.API_KEY and config.api_key:
            register = getattr(self._http_session, "register_sensitive_header", None)
            if callable(register):
                register(config.api_key.header_name)
        self.token: Optional[str] = None
        self.token_type: Optional[str] = None
        self.token_expires_at: Optional[float] = None
        self._browser_cookie_header: Optional[str] = None
        self._browser_cookie_expires_at: Optional[float] = None
        self._browser_session_key: Optional[str] = None
        self._browser_last_validated_at: Optional[float] = None
        self._browser_last_reauth_attempt_at: Optional[float] = None
        self._browser_user_agent: Optional[str] = None
        self._browser_session_token: Optional[str] = None
        # v1.12.4: probe interval effectively disabled (1500s ≈ 25 min, just
        # below the default 30-min TTL). Periodic re-validation churn was the
        # main cause of "every few minutes I get a new login window" — a
        # single transient probe failure invalidated a perfectly fine session.
        # Trust the token once captured; rely on real-API 401 detection in
        # make_request for re-auth. The probe still runs on disk-adoption
        # (probe-before-trust for sessions written by sibling processes).
        self._browser_validation_interval_seconds = 1500
        self._browser_last_login_at: Optional[float] = None
        self._browser_post_login_grace_seconds = 90
        self._browser_reauth_cooldown_seconds = 15  # Start short, back off on repeated failures
        self._browser_reauth_cooldown_base = 15
        # v1.12.11: 120 → 60. Cap was an internal heuristic, not a server
        # requirement; 60s is enough headroom for the slowest sane retry and
        # avoids the "stuck for 2 minutes" feeling on repeated walk-aways.
        self._browser_reauth_cooldown_max = 60
        self._browser_reauth_failure_count = 0
        self._browser_login_in_progress = False  # True while browser window is open for MFA
        self._browser_login_lock = threading.Lock()  # Prevent concurrent browser login attempts
        # Coalesce concurrent probes so N parallel tool calls trigger only 1
        # session-validation round-trip instead of N. The leader probes; others
        # wait, then re-check the validation timestamp and skip their own probe.
        self._browser_probe_lock = threading.Lock()
        # When True, the next persistent-context launch must purge stale
        # session cookies from the Chromium profile before navigating to
        # login.do. Set by invalidate_browser_session() and also when the
        # wait loop detects ServiceNow redirecting probes to logout_success.
        self._needs_profile_cookie_purge: bool = False
        # v1.11.46: when True, the next purge ALSO drops
        # glide_mfa_remembered_browser. Normal invalidation preserves that
        # cookie so the user is not forced to re-MFA after a routine
        # session expiry. But after a self-heal (server tore us down with
        # 302→/logout_success.do), re-using mfa_remembered skips MFA →
        # no `factor` cookie set on the new session → server-side policy
        # rejects the cookie-jar as "not MFA'd" → 302 loop forever. Force
        # full MFA in that case to re-mint the `factor` cookie.
        self._needs_full_profile_purge: bool = False
        # v1.11.47: how many self-heals (302→logout_success.do) have fired
        # consecutively without a successful response in between. The first
        # self-heal preserves mfa_remembered so a transient server hiccup
        # doesn't punish the user with re-MFA. Only when we get TWO+ in a
        # row — meaning the mfa_remembered-cookie path is producing
        # repeatedly-rejected sessions — do we full-purge and force MFA.
        # This was the v1.11.46 UX regression: every self-heal forced MFA,
        # even when the test instance's 302s weren't actually caused by
        # mfa_remembered. Counter resets to 0 on any successful response.
        self._consecutive_self_heal_count: int = 0
        # v1.12.0: timestamp of the last browser-login attempt. Used to
        # enforce _MIN_LOGIN_INTERVAL_SECONDS — back-to-back login.do
        # submissions within seconds look like brute-force to the server
        # and put the account at risk of being flagged. Initial value 0
        # means "no attempt yet"; the first login is unthrottled.
        self._last_login_started_at: float = 0.0
        # v1.12.12 → v1.12.17: born-dead bypass field retained as a no-op
        # for downstream code that still touches it via the auth-event
        # snapshot. The flag is never set anywhere now — v1.12.17 removed
        # the auto-recovery cascade that used to arm it, so the rate-limit
        # gate applies uniformly and the user retries on a normal cadence.
        self._last_login_was_born_dead: bool = False
        # v1.12.1: timestamp of the last circuit-escape probe. Used to
        # throttle the per-request escape attempt once the self-heal
        # circuit is open. Without throttling, a tight retry loop in
        # the caller would fire a probe on every call — that's still
        # better than the pre-v1.12.1 "stuck forever" but it spams the
        # server when nothing has changed.
        self._browser_circuit_last_escape_at: float = 0.0
        self._session_cache_path = self._get_session_cache_path()
        self._login_lock_path = self._session_cache_path.replace(".json", ".lock")
        # Garbage-collect a stale legacy cache that lives in the default
        # `~/.mfa_servicenow_mcp/` directory when the user has since set
        # SERVICENOW_BROWSER_USER_DATA_DIR (active cache moved to
        # `dirname(user_data_dir)`). The legacy file would otherwise hang
        # around forever and confuse the user ("why are there two of these?").
        self._cleanup_legacy_session_cache()
        # Sweep stale lock/session files (real fix for infinite-login incident).
        # See _cleanup_stale_sibling_files docstring for the two failure modes.
        self._cleanup_stale_sibling_files()
        self._cached_basic_auth_header: Optional[str] = None
        self._session_disk_hash: Optional[int] = None  # Track disk content to skip redundant writes
        # Track last-observed mtime of the session JSON. Lets get_headers()
        # cheaply detect when a sibling process has rewritten the file
        # (rotated g_ck, fresh re-auth) so we can adopt the update before
        # firing a request with our now-stale in-memory token.
        self._session_disk_mtime: float = 0.0

        # Lazy browser auth: only load disk cache on startup (no browser).
        # The actual browser login is deferred to the first tool call
        # via get_headers(), avoiding an unwanted login window on MCP start.
        # Remediation message when Playwright/Chromium isn't ready. Stored (not
        # raised) so the server still boots and the "install needed" notice can
        # reach the user through MCP `instructions`, sn_health, and the first
        # browser tool call — instead of a silent "MCP failed to load".
        self._browser_setup_error: Optional[str] = None
        if self.config.type == AuthType.BROWSER:
            # Log the resolved session path so users can confirm all MCP hosts
            # (Claude Desktop / Cursor / terminal / uvx) point at the same dir.
            # Sandboxed launchers occasionally remap $HOME — visible logging is
            # the simplest way to spot a path mismatch.
            logger.info("Session cache: %s", self._session_cache_path)
            # Probe readiness but do NOT crash the server when Chromium is
            # missing: a valid cached session still serves Table API requests
            # with no browser at all — only a re-login needs Chromium. Remember
            # the remediation so we can surface it where the user actually sees
            # it, rather than killing server startup.
            try:
                self._ensure_playwright_ready()
            except RuntimeError as exc:
                self._browser_setup_error = str(exc)
                logger.warning(
                    "Browser auth setup incomplete — server will start, but "
                    "browser login is unavailable until this is fixed:\n%s",
                    exc,
                )
                # Try to self-heal by downloading the Chromium build that the
                # *currently resolved* Playwright expects (e.g. the one uvx just
                # pulled). Runs in the background so the MCP handshake never
                # blocks — that blocking download is exactly what caused the
                # historical Codex "connection closed: initialize response"
                # timeout, which is why we DON'T auto-install inline.
                self._start_background_chromium_install()
            self._load_session_from_disk()
            if self._browser_cookie_header and not self._is_browser_session_expired():
                logger.info("Startup: session restored from disk cache — ready.")
            else:
                if self._browser_cookie_header:
                    self._browser_cookie_header = None
                    self._browser_cookie_expires_at = None
                logger.info(
                    "Startup: no cached session. "
                    "Browser login will be triggered on the first tool call."
                )

    # ------------------------------------------------------------------
    # v1.12.14: single structured channel for auth lifecycle events.
    # Every state transition + every failure should call _auth_event so
    # LOG_FILE has a complete trace of "what the auth state machine knew
    # and did" without grepping through scattered logger.info lines.
    # ------------------------------------------------------------------

    def _auth_event(self, event: str, **context: Any) -> None:
        """Emit one structured auth-state log line.

        Captures the full 16-field auth snapshot at the call site, then
        appends any caller-supplied context. Always goes to ``logger.info``
        with the prefix ``auth_event=<name>`` so a single
        ``grep 'auth_event='`` filters the entire session lifecycle out of
        a noisy LOG_FILE.

        Why this exists: today the auth manager carries ~16 mutually
        interacting state fields. When a sn_health call ends up refused,
        it can be because of any of those — and pre-v1.12.14 logs only
        recorded the human-readable narrative ("Browser session
        invalidated", "Browser re-auth failed"), leaving every post-mortem
        as guesswork. With this event channel the answer to "what did the
        state machine think at the moment of the refusal?" is one line.
        """
        now = time.time()
        last_login_at = self._browser_last_login_at
        last_attempt = self._browser_last_reauth_attempt_at
        last_started = self._last_login_started_at

        def _ago(ts: Optional[float]) -> str:
            if not ts:
                return "never"
            return f"{now - ts:.1f}s"

        flags = []
        if self._last_login_was_born_dead:
            flags.append("born_dead_armed")
        if self._needs_full_profile_purge:
            flags.append("needs_full_purge")
        if self._needs_profile_cookie_purge:
            flags.append("needs_cookie_purge")
        if self._browser_login_in_progress:
            flags.append("login_in_progress")

        snapshot: Dict[str, Any] = {
            "cookies": "set" if self._browser_cookie_header else "none",
            "token": "set" if self._browser_session_token else "none",
            # v1.12.16: redacted prefixes so two events can be compared for
            # cookie/token rotation. Same NAMES but different prefixes between
            # capture and probe == server-side rotation == captured session
            # is stale by the time we use it.
            "cookies_redacted": _format_cookie_values_for_log(self._browser_cookie_header),
            "token_prefix": _redact_value(self._browser_session_token, _LOG_TOKEN_VALUE_PREFIX_LEN),
            "user_agent_prefix": _redact_value(self._browser_user_agent, 32),
            # v1.12.21: surface the active HTTP client so each event shows
            # whether the call went out under TLS impersonation. Two events
            # with identical cookies but different http_client values
            # immediately localizes a regression to the wire layer.
            "http_client": _describe_http_session(self._http_session),
            "last_login_ago": _ago(last_login_at),
            "last_attempt_ago": _ago(last_attempt),
            "last_started_ago": _ago(last_started),
            "cooldown_s": self._browser_reauth_cooldown_seconds,
            "failure_count": self._browser_reauth_failure_count,
            "selfheal_consec": self._consecutive_self_heal_count,
            "circuit": (
                "open"
                if self._consecutive_self_heal_count >= _SELF_HEAL_CIRCUIT_THRESHOLD
                else "closed"
            ),
            "flags": ",".join(flags) if flags else "-",
        }
        # Caller context overrides snapshot keys on collision (rare; lets
        # call sites pass e.g. a freshly-computed cookie_count without
        # waiting for the snapshot to see it).
        snapshot.update(context)
        parts = [f"auth_event={event}"]
        for key, value in snapshot.items():
            # Repr non-strings cheaply so log line stays single-line and
            # grep-friendly. None becomes "None", booleans stay bare.
            parts.append(f"{key}={value}")
        logger.info(" ".join(parts))

    # ------------------------------------------------------------------
    # Playwright pre-flight check
    # ------------------------------------------------------------------

    # Wait-budget bounds for the login polling loop.
    # Pulled out so tests can monkeypatch them directly without having to
    # patch the budget computation itself, and so the rationale is in one
    # place instead of repeated in test comments.
    DEBUG_LOGIN_WAIT_BUDGET_MS: int = 1_800_000  # 30 min — DevTools inspection
    MIN_VISIBLE_LOGIN_WAIT_BUDGET_MS: int = 60_000  # human MFA/SSO entry floor
    MAX_HEADLESS_LOGIN_WAIT_BUDGET_MS: int = 30_000  # snappy fallback to visible

    @classmethod
    def _compute_login_wait_budget_ms(
        cls, timeout_ms: int, *, use_headless: bool, debug_mode: bool
    ) -> int:
        """Pick the wait_budget_ms used by the polling loop in login.

        - Debug mode: ``DEBUG_LOGIN_WAIT_BUDGET_MS``. Lets the user inspect
          requests in DevTools.
        - Visible-window (use_headless=False): at least
          ``MIN_VISIBLE_LOGIN_WAIT_BUDGET_MS``, raised to ``timeout_ms`` if
          larger. MFA/SSO entry needs human time; do not fail fast on a
          window the user is actively working in. This covers BOTH
          ``force_interactive=True`` AND ``browser_config.headless=False``.
        - Headless (use_headless=True): at most
          ``MAX_HEADLESS_LOGIN_WAIT_BUDGET_MS``. The cookie gate covers
          "MFA required" in <1 s, and the cap keeps the wrapper's fallback
          to interactive snappy when SSO never lands a probe-200 in the
          invisible window.
        """
        if debug_mode:
            return cls.DEBUG_LOGIN_WAIT_BUDGET_MS
        if not use_headless:
            return max(timeout_ms, cls.MIN_VISIBLE_LOGIN_WAIT_BUDGET_MS)
        return min(timeout_ms, cls.MAX_HEADLESS_LOGIN_WAIT_BUDGET_MS)

    def _apply_browser_session_headers(self, headers: dict) -> dict:
        """Mutate `headers` in place to include the captured browser session
        — Cookie + optional User-Agent + optional X-UserToken — and return
        the same dict for chaining.

        v1.12.0 reverts the v1.11.45 Referer addition. Field report from
        a user whose test instance worked pre-patches and broke after:
        adding Referer changed the request signature enough that the
        server started 302'ing every call to /logout_success.do. The
        probe path still sends Referer (it has to look UI-driven for the
        validation hit), but the actual API call path is back to the
        pre-v1.11.45 header set users had been relying on for months.
        """
        headers["Cookie"] = self._browser_cookie_header or ""
        if self._browser_user_agent:
            headers["User-Agent"] = self._browser_user_agent
        if self._browser_session_token:
            headers["X-UserToken"] = self._browser_session_token
        return headers

    @staticmethod
    def _has_valid_mfa_remembered_cookie(
        profile_cookies: list[dict], now: Optional[float] = None
    ) -> bool:
        """Return True if the persistent profile contains a non-expired
        `glide_mfa_remembered_browser` cookie.

        ServiceNow sets this cookie after a user completes MFA on a device
        and elects to "remember this browser". Subsequent logins from the
        same persistent Playwright profile skip the MFA prompt while the
        cookie is valid. The headless login gate uses this signal to decide
        whether a non-interactive attempt is worth trying.

        A cookie without an `expires` value (session cookie) or with a
        non-positive value is treated as expired/absent — `glide_mfa_
        remembered_browser` is always persistent in normal flows.
        """
        if now is None:
            now = time.time()
        for cookie in profile_cookies:
            if cookie.get("name") != "glide_mfa_remembered_browser":
                continue
            raw_expires = cookie.get("expires")
            # Coerce defensively. Playwright Python normally returns a
            # numeric expires, but tests / external session imports may
            # round-trip a string. Anything we cannot read as a float
            # is treated as "no valid expiry" — fail closed.
            try:
                expires = float(raw_expires) if raw_expires is not None else 0.0
            except (TypeError, ValueError):
                expires = 0.0
            if expires > now:
                return True
        return False

    @staticmethod
    def _ensure_playwright_ready() -> None:
        """Verify Playwright is importable and has a working Chromium binary.

        Called once during ``__init__`` when auth type is ``browser``.

        In a ``uvx`` environment the playwright *package* is expected to be
        provided via ``uvx --with playwright …``.  If it is missing we
        surface a clear error telling the user to add ``--with playwright``.

        The Chromium *browser binary* is a separate download. We do NOT
        auto-install it — a ~150 MB blocking subprocess inside the first
        browser tool call has caused MCP host timeouts (e.g. Codex
        "connection closed: initialize response"). Instead we raise a
        precise error with the one-liner the user should run.
        """
        # 1. Ensure the Python package is importable.
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "Playwright package is required for browser authentication but is not installed.\n"
                "• uvx:  uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp …\n"
                "• pip:  pip install playwright && playwright install chromium\n"
                "• dev:  uv pip install -e '.[browser]'"
            ) from None

        # 2. Ensure the Chromium browser binary is present.
        # Probe by launching headless Chromium briefly; raises if the binary
        # is missing or its version doesn't match the installed Playwright.
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                browser.close()
        except Exception as exc:
            exc_msg = str(exc).lower()
            if "executable doesn't exist" in exc_msg or "browser" in exc_msg:
                raise RuntimeError(
                    "Playwright Chromium binary missing or version-mismatched.\n"
                    "Install it once (this is fast on a good link, slow on a bad one,\n"
                    "which is why we don't auto-install inside the MCP handshake):\n"
                    "  uvx --with playwright playwright install chromium\n"
                    "\n"
                    "Then retry the tool call. To avoid surprise upgrades when a new\n"
                    "Playwright release ships a different Chromium build, pin the\n"
                    "Playwright version in your MCP client config:\n"
                    '  args = ["--with", "playwright==<version>", "--from", "mfa-servicenow-mcp==<version>", "servicenow-mcp"]'
                ) from None
            # Some other Playwright error — re-raise so callers see the real cause.
            raise

    def _start_background_chromium_install(self) -> None:
        """Download the Chromium build the resolved Playwright expects, async.

        When uvx pulls a newer Playwright than the cached browser, the binary
        is "missing or version-mismatched". ``python -m playwright install
        chromium`` (run with *this* interpreter's Playwright) fetches the exact
        matching revision into the shared cache — so the next login just works.

        Runs in a daemon thread: the ~150 MB download must never block the MCP
        handshake. On success the setup-error flag clears; on failure the manual
        remediation message stays. Opt out via
        ``SERVICENOW_AUTO_INSTALL_CHROMIUM=off``.
        """
        import subprocess
        import sys

        opt_out = os.getenv(_AUTO_INSTALL_CHROMIUM_ENV_VAR, "").strip().lower()
        if opt_out in _AUTO_INSTALL_CHROMIUM_OFF_VALUES:
            logger.info(
                "Chromium auto-install disabled via %s=%s — manual install required.",
                _AUTO_INSTALL_CHROMIUM_ENV_VAR,
                opt_out,
            )
            return

        # In a PyInstaller single-file build sys.executable is the app exe, not
        # a Python — `<exe> -m playwright install` would re-launch the app, not
        # install anything. The frozen build bundles Chromium anyway; if it's
        # somehow missing, keep the manual remediation rather than misfire.
        if getattr(sys, "frozen", False):
            logger.info(
                "Frozen build detected — skipping Chromium auto-install; "
                "manual install required if the bundled browser is missing."
            )
            return

        # Reflect the in-progress download in the user-facing notice so the
        # initialize-response instructions say "installing" rather than handing
        # the user a command they don't need to run.
        self._browser_setup_error = (
            "Playwright Chromium is missing; downloading the matching build "
            "automatically in the background. Retry your browser action in a "
            "moment. If it does not resolve, run: playwright install chromium"
        )

        def _run() -> None:
            logger.info("Auto-installing Playwright Chromium in background…")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True,
                    text=True,
                    timeout=_AUTO_INSTALL_CHROMIUM_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 — network/timeout/spawn failures
                logger.warning(
                    "Chromium auto-install failed (%s); manual install still required: "
                    "playwright install chromium",
                    exc,
                )
                return

            if result.returncode != 0:
                logger.warning(
                    "Chromium auto-install exited %s; manual install still required: "
                    "playwright install chromium\n%s",
                    result.returncode,
                    (result.stderr or "").strip()[:500],
                )
                return

            # Confirm the binary actually launches now before clearing the flag.
            try:
                self._ensure_playwright_ready()
            except RuntimeError as exc:
                logger.warning("Chromium auto-install did not resolve readiness:\n%s", exc)
                return
            self._browser_setup_error = None
            logger.info("Playwright Chromium installed — browser login enabled.")

        threading.Thread(target=_run, daemon=True, name="chromium-auto-install").start()

    def _get_cache_dir(self) -> str:
        """Resolve the root cache directory for session JSON and Playwright profile.

        Default: ``<user home>/.mfa_servicenow_mcp`` resolved via ``Path.home()``
        so Windows (``%USERPROFILE%``), macOS, and Linux all land in the per-user
        home directory regardless of how the MCP host launches the process
        (uvx, Claude Desktop, terminal). All MCP clients on the same machine
        share this path, so a single login is reused across hosts.

        Override via ``SERVICENOW_BROWSER_USER_DATA_DIR`` for non-standard
        layouts. The configured value is treated as a BASE directory that holds
        BOTH ``session_<host>_<user>.json`` and ``profile_<host>_<user>/`` — same
        structure as the default home dir. So a shared/global user_data_dir can
        no longer collapse multiple instances (or users) onto one Chromium cookie
        store: each instance+user still lands in its own profile subdir.

        Performs a one-time migration from the v1.12.4-1.12.6 location
        (``~/.servicenow_mcp/``) so users keep their existing sessions.
        """
        if self.config.browser and self.config.browser.user_data_dir:
            # User-chosen base: create it private if missing, but NEVER chmod a
            # pre-existing directory the user may deliberately share (imagine
            # user_data_dir pointed at $HOME). The secrets inside are protected
            # regardless: session JSON is 0600 and the profile subdir is forced
            # 0700 in _resolve_user_data_dir.
            cache_dir = os.path.abspath(self.config.browser.user_data_dir)
            _ensure_private_dir(cache_dir, chmod_existing=False)
            return cache_dir
        cache_dir = str(Path.home() / ".mfa_servicenow_mcp")
        legacy_dir = str(Path.home() / ".servicenow_mcp")
        if os.path.isdir(legacy_dir) and not os.path.exists(cache_dir):
            try:
                os.rename(legacy_dir, cache_dir)
                logger.info("Migrated cache directory: %s → %s", legacy_dir, cache_dir)
            except OSError as exc:
                logger.warning(
                    "Failed to migrate %s → %s: %s. Starting fresh in new location.",
                    legacy_dir,
                    cache_dir,
                    exc,
                )
        # Default dir is OURS — force private even if an older version created
        # it 0755. It holds the Chromium profile whose cookie DB is a live
        # replayable SSO session; the session JSON alone being 0600 is not
        # enough on a shared host.
        _ensure_private_dir(cache_dir, chmod_existing=True)
        return cache_dir

    def _get_instance_user_suffix(self) -> str:
        """Return the ``{instance}{_user}`` suffix used in cache filenames.

        Replace ``@`` with ``_at_`` before ``.`` so usernames like
        ``alice@corp.com`` and ``alice.corp.com`` produce distinct suffixes
        (previously both collapsed to ``alice_corp_com``).
        """
        instance_id = "default"
        if self.instance_url:
            instance_id = (urlparse(self.instance_url).hostname or "default").replace(".", "_")
        username = ""
        raw_user: Optional[str] = None
        if self.config.browser and self.config.browser.username:
            raw_user = self.config.browser.username
        elif self.config.basic and self.config.basic.username:
            raw_user = self.config.basic.username
        if raw_user:
            username = f"_{raw_user.replace('@', '_at_').replace('.', '_')}"
        return f"{instance_id}{username}"

    def _get_session_cache_path(self) -> str:
        """Get the path to the session cache file, scoped by instance + user."""
        return os.path.join(
            self._get_cache_dir(), f"session_{self._get_instance_user_suffix()}.json"
        )

    def _get_default_user_data_dir(self) -> str:
        """Per-instance default Playwright profile directory.

        Scoped by instance host (and username) so repeated MCP starts for the
        same instance share the same profile — preserving SSO/IDP cookies so
        re-login is silent when the ServiceNow session expires. Different
        instances/users get isolated profiles.
        """
        return os.path.join(self._get_cache_dir(), f"profile_{self._get_instance_user_suffix()}")

    def _resolve_user_data_dir(self, browser_config: BrowserAuthConfig) -> str:
        """Per-instance Playwright profile dir, ALWAYS scoped by host+user.

        A configured ``user_data_dir`` is a BASE, not the literal profile — it is
        folded into the cache dir by ``_get_cache_dir``, so the profile is
        ``<base>/profile_<host>_<user>``. This keeps the profile keyed the same
        way as the session JSON, so two instances (dev/test) or two users never
        share one cookie store even under a shared/global user_data_dir.

        The profile dir is forced 0700: its Chromium cookie DB is a replayable
        SSO session, and Playwright would otherwise create it with umask perms
        (0755) — exposed whenever the base dir is user-chosen and shared.
        """
        profile_dir = self._get_default_user_data_dir()
        try:
            _ensure_private_dir(profile_dir, chmod_existing=True)
        except OSError:  # pragma: no cover — never block login on perms
            pass
        return profile_dir

    def _instance_profile_label(self) -> str:
        """Short ``instance=<host> profile=<suffix>`` tag for auth messages.

        Login state is per-instance AND per-profile; with multiple instances
        configured (e.g. dev + test) an error that omits which one it refers to
        is easy to misread as "the other instance is fine". Naming both in every
        auth message removes that ambiguity. Read-only — derives from config,
        mutates no state, changes no control flow.
        """
        host = "default"
        if self.instance_url:
            host = urlparse(self.instance_url).hostname or "default"
        return f"instance={host} profile={self._get_instance_user_suffix()}"

    # ------------------------------------------------------------------
    # Cross-process login lock (disk-based)
    # ------------------------------------------------------------------

    def _acquire_login_lock(self) -> bool:
        """Try to acquire a cross-process login lock.

        Returns True if we got the lock (no other process is logging in).
        Returns False if another process already holds the lock.
        Stale locks (PID dead or older than 5 minutes) are automatically cleaned up.
        """
        if os.path.exists(self._login_lock_path):
            try:
                with open(self._login_lock_path, "r") as f:
                    lock_data = json.load(f)
                lock_pid = lock_data.get("pid")
                lock_time = lock_data.get("timestamp", 0)
                # Stale lock: process dead or lock older than 5 minutes
                stale = (time.time() - lock_time) > 300
                if not stale and lock_pid:
                    try:
                        os.kill(lock_pid, 0)  # Check if PID is alive
                    except OSError:
                        stale = True  # Process is dead
                if not stale:
                    logger.info(
                        "Login lock held by PID %s (age %.0fs) — "
                        "another terminal is already logging in.",
                        lock_pid,
                        time.time() - lock_time,
                    )
                    return False
                logger.info("Removing stale login lock (PID %s).", lock_pid)
            except Exception:
                pass  # Corrupt lock file — safe to overwrite
        try:
            with open(self._login_lock_path, "w") as f:
                json.dump({"pid": os.getpid(), "timestamp": time.time()}, f)
            return True
        except Exception as exc:
            logger.warning("Failed to acquire login lock: %s", exc)
            return True  # Fail open — better to double-login than deadlock

    def _release_login_lock(self) -> None:
        """Release the cross-process login lock (only if we own it)."""
        try:
            if os.path.exists(self._login_lock_path):
                with open(self._login_lock_path, "r") as f:
                    lock_data = json.load(f)
                if lock_data.get("pid") == os.getpid():
                    os.remove(self._login_lock_path)
        except Exception:
            pass

    def _wait_for_other_login(self, timeout: int = 180) -> bool:
        """Wait for another process to finish logging in, then reload session.

        Returns True if a fresh session was loaded from disk.
        Returns False if timeout elapsed or no session appeared.
        """
        logger.info("Waiting up to %ds for another terminal to complete login...", timeout)
        deadline = time.time() + timeout
        saw_lock = os.path.exists(self._login_lock_path)
        while time.time() < deadline:
            time.sleep(3)
            lock_exists = os.path.exists(self._login_lock_path)
            if lock_exists:
                saw_lock = True
            # Only treat a missing lock as "released" if one was observed first.
            if saw_lock and not lock_exists:
                if self._reload_session_from_disk():
                    logger.info("Other terminal completed login — session reloaded.")
                    return True
                # Lock released but no session yet — try disk load once more
                self._load_session_from_disk()
                if self._browser_cookie_header and not self._is_browser_session_expired():
                    logger.info("Other terminal completed login — session loaded from disk.")
                    return True
            # Lock still held — check if disk was updated (login succeeded while lock still exists)
            if self._reload_session_from_disk():
                logger.info("Fresh session appeared on disk while waiting — using it.")
                return True
        logger.warning("Timed out waiting for other terminal to complete login.")
        return False

    def _save_session_to_disk(self) -> None:
        """Save the current browser session to disk.

        Skips the write if the serialized content matches the last saved hash.
        """
        if self.config.type != AuthType.BROWSER or not self._browser_cookie_header:
            return

        data = {
            "cookie_header": self._browser_cookie_header,
            "user_agent": self._browser_user_agent,
            "session_token": self._browser_session_token,
            "expires_at": self._browser_cookie_expires_at,
            "instance_url": self.instance_url,
            # Persist last_validated_at so a sibling process that adopts this
            # session can decide whether to trust it or re-probe before use.
            "last_validated_at": self._browser_last_validated_at,
            # Persist last_login_at so the post-login grace period (90 s) keeps
            # working after disk-restore. Without this, a sibling/restarted
            # process adopts the session with last_login_at=None and the very
            # next 401 skips the grace branch → opens a redundant browser.
            "last_login_at": self._browser_last_login_at,
        }
        # Quick content-hash check to skip redundant writes
        content_hash = hash((data["cookie_header"], data["user_agent"], data["session_token"]))
        if content_hash == self._session_disk_hash:
            return
        try:
            # Cookies + X-UserToken are credentials: create the file owner-only
            # (0600) via os.open so umask can't widen it to a world-readable
            # 0644 that a co-tenant on a shared host could copy and replay.
            fd = os.open(
                self._session_cache_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            # Re-assert mode on an already-existing file (os.open honors the
            # mode only on creation, so a pre-existing 0644 would survive).
            try:
                os.chmod(self._session_cache_path, 0o600)
            except OSError:
                pass
            self._session_disk_hash = content_hash
            # Record our own mtime so _maybe_adopt_sibling_session_update()
            # doesn't treat this write as a sibling update on the next call.
            try:
                self._session_disk_mtime = os.path.getmtime(self._session_cache_path)
            except OSError:
                pass
            logger.info("Browser session saved to disk: %s", self._session_cache_path)
        except Exception as exc:
            logger.warning("Failed to save browser session to disk: %s", exc)

    def _cleanup_legacy_session_cache(self) -> None:
        """When the user has set SERVICENOW_BROWSER_USER_DATA_DIR, the active
        cache lives in `dirname(user_data_dir)`. Pre-existing copies in the
        default ``~/.mfa_servicenow_mcp/`` directory (or the older
        ``~/.servicenow_mcp/`` from v1.12.4-1.12.6) are unreachable from the
        active path resolver but stay on disk forever, confusing the user.
        Remove them.
        """
        if not (self.config.browser and self.config.browser.user_data_dir):
            return  # No USER_DATA_DIR set → default IS the active path
        suffix = self._get_instance_user_suffix()
        for legacy_dir in (
            str(Path.home() / ".mfa_servicenow_mcp"),
            str(Path.home() / ".servicenow_mcp"),
        ):
            if not os.path.isdir(legacy_dir):
                continue
            legacy_session = os.path.join(legacy_dir, f"session_{suffix}.json")
            legacy_lock = legacy_session.replace(".json", ".lock")
            for path in (legacy_session, legacy_lock):
                try:
                    if os.path.exists(path) and os.path.abspath(path) != os.path.abspath(
                        self._session_cache_path
                    ):
                        os.remove(path)
                        logger.info("Removed legacy session cache: %s", path)
                except Exception as exc:
                    logger.debug("Failed to remove legacy cache %s: %s", path, exc)

    def _cleanup_stale_sibling_files(self) -> None:
        """Remove stale lock/session files at startup (real bug fix, not cosmetic).

        Two failure modes observed in the field cause infinite-login state:

        1. **Cross-instance residue.** When the user switches instances
           (e.g. a dev → test instance), the previous instance's `.lock` and
           `session_*.json` files persist forever because each manager only
           owns its own paths. A `.lock` whose holding process is long dead
           or a session whose TTL expired weeks ago accumulates indefinitely.

        2. **Own-instance crashed lock.** If a previous run of THIS instance
           crashed mid-login (kill -9, OOM, panic), our own `.lock` file
           lingers with a dead PID. `_acquire_login_lock` would normally
           clean it up at the next login, but corrupt timestamps or PID
           collisions can defeat that check, producing the observed
           "Browser login is in progress in another terminal" loop.

        Sweep at startup so neither case can poison subsequent behavior.
        Active sessions (this instance's session_*.json) are left alone —
        `_load_session_from_disk` is responsible for probing/discarding them.
        """
        cache_dir = self._get_cache_dir()
        try:
            entries = os.listdir(cache_dir)
        except OSError:
            return
        active_session = os.path.abspath(self._session_cache_path)
        now = time.time()
        for name in entries:
            path = os.path.join(cache_dir, name)
            abs_path = os.path.abspath(path)
            try:
                if name.endswith(".lock"):
                    # Sweep ALL lock files (own + sibling). Live login will
                    # re-acquire its own lock; stale ones must not block.
                    if self._is_lock_file_stale(path, now):
                        os.remove(path)
                        logger.info("Removed stale lock file at startup: %s", path)
                elif name.startswith("session_") and name.endswith(".json"):
                    # Don't touch the active session — disk-load probe owns it.
                    if abs_path == active_session:
                        continue
                    if self._is_session_file_expired(path, now):
                        os.remove(path)
                        logger.info("Removed expired sibling session cache: %s", path)
            except Exception as exc:
                logger.debug("Failed to inspect/remove file %s: %s", path, exc)

    @staticmethod
    def _is_lock_file_stale(path: str, now: float) -> bool:
        """Return True only if a lock's holding process is verifiably dead.

        Deliberately conservative: timestamp age alone is NOT used here.
        A peer terminal can legitimately hold a login lock for a long time
        (slow MFA entry, debug mode with DevTools open up to 30 min, SSO
        round-trip). Killing such a lock at our startup would let us open
        a second browser window for the same login, producing the exact
        chaos the lock exists to prevent.

        The acceptable case is the one observed in the field: a previous
        process crashed mid-login and its PID is now reused by something
        unrelated or simply gone. Only that case is removed here.

        ``now`` is unused but kept for signature symmetry with
        ``_is_session_file_expired``.
        """
        del now  # intentional: see docstring
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception:
            return True  # Corrupt → safe to drop
        lock_pid = data.get("pid")
        if not isinstance(lock_pid, int) or lock_pid <= 0:
            return True
        try:
            os.kill(lock_pid, 0)
        except OSError:
            return True
        return False

    @staticmethod
    def _is_session_file_expired(path: str, now: float) -> bool:
        """Return True if a session file's expires_at has passed."""
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception:
            return False  # Don't delete unreadable files we can't classify
        expires_at = data.get("expires_at")
        if not isinstance(expires_at, (int, float)):
            return False
        return now > expires_at

    def _delete_session_cache_file(self, reason: str) -> None:
        """Remove the on-disk session cache file. Used to garbage-collect cache
        files whose TTL has expired AND whose server session has been confirmed
        invalid — leaving them around just causes the same stale-session probe
        + re-auth dance on every spawn."""
        try:
            if os.path.exists(self._session_cache_path):
                os.remove(self._session_cache_path)
                logger.info(
                    "Removed expired session cache (%s): %s",
                    reason,
                    self._session_cache_path,
                )
        except Exception as exc:
            logger.debug("Failed to remove expired session cache: %s", exc)

    def _load_session_from_disk(self) -> None:
        """Load the browser session from disk.

        If the disk TTL has expired, the session is still loaded and verified
        with a live API probe — the ServiceNow server session may outlive the
        conservative disk TTL, so we should not discard a potentially valid session.
        Confirmed-dead caches are removed so they don't keep getting re-probed.
        """
        if not os.path.exists(self._session_cache_path):
            return

        try:
            with open(self._session_cache_path, "r") as f:
                data = json.load(f)

            # Basic validation
            if data.get("instance_url") != self.instance_url:
                # Wrong instance — file is stale for this manager. Remove so we
                # don't keep reading it on every spawn.
                self._delete_session_cache_file("instance mismatch")
                return

            cookie_header = data.get("cookie_header")
            if not cookie_header:
                self._delete_session_cache_file("empty cookie")
                return

            expires_at = data.get("expires_at")
            disk_expired = expires_at and time.time() > expires_at

            if disk_expired:
                # TTL expired, but the real session might still be alive.
                # Verify with a live probe before discarding.
                logger.info(
                    "Disk session TTL expired. Probing server to check if session is still valid..."
                )
                self._browser_user_agent = data.get("user_agent")
                try:
                    if self.config.browser:
                        probe = self._probe_browser_api_with_cookie(
                            cookie_header,
                            timeout_seconds=10,
                            browser_config=self.config.browser,
                        )
                        if _response_confirms_browser_probe_session(probe):
                            new_ttl = (self.config.browser.session_ttl_minutes or 30) * 60
                            self._browser_cookie_header = cookie_header
                            self._browser_cookie_expires_at = time.time() + new_ttl
                            self._browser_session_token = data.get("session_token")
                            self._browser_last_validated_at = time.time()
                            self._save_session_to_disk()
                            logger.info(
                                "Disk session TTL expired but server session is still valid — "
                                "extended TTL by %d minutes.",
                                self.config.browser.session_ttl_minutes or 30,
                            )
                            return
                        logger.info(
                            "Disk session expired probe returned login redirect (status=%s) — "
                            "discarding cached session and requiring fresh login.",
                            probe.status_code,
                        )
                except Exception as exc:
                    logger.debug("Disk session probe failed: %s", exc)
                logger.info("Disk session expired and server confirmed invalid.")
                # Remove the dead cache so we don't probe-and-discard on every
                # spawn. A fresh login will write a new file.
                self._delete_session_cache_file("expired + server-invalid")
                return

            self._browser_cookie_header = cookie_header
            self._browser_user_agent = data.get("user_agent")
            self._browser_session_token = data.get("session_token")
            self._browser_cookie_expires_at = expires_at
            # Force a live probe before the first reuse of a disk-restored session.
            # A non-expired local TTL only means our cache is fresh enough to try;
            # it does not prove the remote ServiceNow auth state is still valid.
            self._browser_last_validated_at = None
            disk_login_at = data.get("last_login_at")
            self._browser_last_login_at = min(disk_login_at, time.time()) if disk_login_at else None
            # Anchor mtime so subsequent _maybe_adopt_sibling_session_update()
            # only fires when a sibling rewrites the file after this load.
            try:
                self._session_disk_mtime = os.path.getmtime(self._session_cache_path)
            except OSError:
                pass
            logger.info("Loaded browser session from disk: %s", self._session_cache_path)
        except Exception as exc:
            logger.warning("Failed to load browser session from disk: %s", exc)

    def _reload_session_from_disk(self) -> bool:
        """Reload session from disk if a fresher session exists.

        Used by request retry paths to pick up sessions written by another
        terminal/process sharing the same cache file.
        Returns True if a different (fresher) session was loaded.
        """
        if not os.path.exists(self._session_cache_path):
            return False
        try:
            with open(self._session_cache_path, "r") as f:
                data = json.load(f)
        except Exception:
            return False

        if data.get("instance_url") != self.instance_url:
            return False

        disk_cookie = data.get("cookie_header")
        if not disk_cookie:
            return False

        disk_expires = data.get("expires_at")
        disk_token = data.get("session_token")
        # Cookies match — but session_token (X-UserToken / g_ck) may have been
        # rotated by a sibling process via _absorb_response_token_rotation().
        # If so, adopt the rotated token so our next request doesn't send the
        # stale value the server now rejects with 302→/logout_success.do.
        if disk_cookie == self._browser_cookie_header:
            token_rotated = bool(disk_token) and disk_token != self._browser_session_token
            if token_rotated:
                self._browser_session_token = disk_token
                # Force a probe before trusting — the rotation may be paired
                # with server-side ACL change we haven't seen yet.
                self._browser_last_validated_at = None
                logger.info(
                    "Cross-process X-UserToken rotation adopted from disk "
                    "(session_token differs, cookies unchanged)."
                )
            # Refresh TTL if disk has a later expiry (another process extended it)
            if disk_expires and (
                not self._browser_cookie_expires_at
                or disk_expires > self._browser_cookie_expires_at
            ):
                self._browser_cookie_expires_at = disk_expires
                # Another process recently wrote/validated the session — adopt their
                # validated_at if present (capped to now) so we don't claim a fresher
                # validation than actually happened.
                disk_validated_at = data.get("last_validated_at")
                if disk_validated_at and not token_rotated:
                    self._browser_last_validated_at = min(disk_validated_at, time.time())
                logger.debug("Reload: same cookies but extended TTL from disk.")
            return token_rotated

        # Disk has different cookies — likely written by another terminal after re-auth
        if disk_expires and time.time() > disk_expires:
            # Remove the expired file so we don't keep re-reading it on every
            # 401 retry cycle. A fresh login will write a new one.
            self._delete_session_cache_file("expired on reload")
            return False

        self._browser_cookie_header = disk_cookie
        self._browser_user_agent = data.get("user_agent")
        self._browser_session_token = disk_token
        self._browser_cookie_expires_at = disk_expires
        # Pair with v1.10.21 probe-before-trust in get_headers(): inherit the disk
        # validation timestamp if present (capped to now); otherwise leave None so
        # the next caller probes before trusting cookies that may have been written
        # by a sibling process that has since idle-timed-out on the server.
        disk_validated_at = data.get("last_validated_at")
        self._browser_last_validated_at = (
            min(disk_validated_at, time.time()) if disk_validated_at else None
        )
        # Inherit last_login_at so the post-login grace period (90 s) survives
        # disk handoff between processes. Without this the adopting process
        # treats every 401 as "out of grace" and opens a redundant browser.
        disk_login_at = data.get("last_login_at")
        self._browser_last_login_at = min(disk_login_at, time.time()) if disk_login_at else None
        try:
            self._session_disk_mtime = os.path.getmtime(self._session_cache_path)
        except OSError:
            pass
        logger.info(
            "Reloaded fresher session from disk (written by another process): %s",
            self._session_cache_path,
        )
        return True

    def _maybe_adopt_sibling_session_update(self) -> bool:
        """Adopt session updates written by a sibling MCP process.

        Single os.stat() fast path: only opens/parses the session JSON when
        its mtime is newer than what we last loaded. Cheap enough to call on
        every get_headers(); ~sub-millisecond when no sibling write has
        occurred.

        Why this exists: ServiceNow rotates the X-UserToken (g_ck) on response
        headers periodically. _absorb_response_token_rotation() persists the
        rotated token to disk so other processes can pick it up — but without
        an active reload trigger, sibling processes keep using their stale
        in-memory token and the server 302s them to /logout_success.do on the
        next protected call, kicking off an invalidate→re-auth loop. mtime
        polling closes that loop: when one process rotates, every sibling's
        next get_headers() adopts the new token.

        Returns True when an update was adopted.
        """
        if self.config.type != AuthType.BROWSER:
            return False
        try:
            mtime = os.path.getmtime(self._session_cache_path)
        except OSError:
            return False
        # Tolerance for filesystem mtime granularity (HFS+ is 1 s) and minor
        # clock skew between writes within the same process.
        if mtime <= self._session_disk_mtime + 0.5:
            return False
        adopted = self._reload_session_from_disk()
        # Even when reload returned False (disk content unchanged or expired
        # and deleted), bump our mtime watermark so we don't re-stat-and-parse
        # the same unchanged file on every subsequent call.
        try:
            self._session_disk_mtime = os.path.getmtime(self._session_cache_path)
        except OSError:
            # File may have been deleted by reload (expired branch). Use the
            # mtime we already saw to suppress repeated re-checks until a new
            # file appears.
            self._session_disk_mtime = mtime
        return adopted

    def _start_keepalive(self) -> None:
        """No-op stub retained for backward-compat with tests that mock this
        method. v1.12.4 removed the keep-alive thread entirely: REST API pings
        don't reset the server-side idle timer on most ServiceNow instances,
        so the thread burned resources without keeping sessions alive. Session
        expiry now recovers via 401 detection in make_request → re-login.
        """
        return

    def stop_keepalive(self) -> None:
        """No-op stub. See `_start_keepalive` for rationale."""
        return

    def get_headers(self) -> Dict[str, str]:
        """
        Get the authentication headers for API requests.

        Returns:
            Dict[str, str]: Headers to include in API requests.
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self.config.type == AuthType.BASIC:
            if not self.config.basic:
                raise ValueError("Basic auth configuration is required")

            if self._cached_basic_auth_header is None:
                auth_str = f"{self.config.basic.username}:{self.config.basic.password}"
                encoded = base64.b64encode(auth_str.encode()).decode()
                self._cached_basic_auth_header = f"Basic {encoded}"
            headers["Authorization"] = self._cached_basic_auth_header

        elif self.config.type == AuthType.OAUTH:
            if not self.token or self._is_token_expired():
                self._get_oauth_token()

            headers["Authorization"] = f"{self.token_type} {self.token}"

        elif self.config.type == AuthType.API_KEY:
            if not self.config.api_key:
                raise ValueError("API key configuration is required")

            headers[self.config.api_key.header_name] = self.config.api_key.api_key

        elif self.config.type == AuthType.BROWSER:
            if not self.config.browser:
                raise ValueError("Browser auth configuration is required")
            # Cross-process sync: pick up any session update (rotated g_ck,
            # fresh re-auth) that a sibling MCP process wrote since we last
            # touched disk. Without this, sibling rotations stay invisible to
            # us and the next request goes out with a stale X-UserToken → the
            # server 302s to /logout_success.do → we invalidate and re-login
            # for no real reason. See _maybe_adopt_sibling_session_update().
            self._maybe_adopt_sibling_session_update()
            if not self._browser_cookie_header or self._is_browser_session_expired():
                # In-process lock: prevent concurrent tool calls from opening
                # multiple browser windows (both restore AND login are serialized).
                acquired = self._browser_login_lock.acquire(timeout=0)
                if not acquired:
                    # Another thread in this process is already logging in — wait for it.
                    logger.info("Browser login/restore in progress in another thread — waiting...")
                    self._browser_login_lock.acquire()  # Block until login finishes
                    self._browser_login_lock.release()
                    # Login should be done now — return headers if session is valid
                    if self._browser_cookie_header and not self._is_browser_session_expired():
                        self._apply_browser_session_headers(headers)
                        return headers
                    raise ValueError(
                        "Browser login completed in another thread but session is not available. "
                        "Please retry this request."
                    )
                # We hold the in-process lock from here.
                try:
                    # Double-check: another thread may have completed login while we waited.
                    if self._browser_cookie_header and not self._is_browser_session_expired():
                        self._apply_browser_session_headers(headers)
                        return headers

                    # Fast path: try disk reload before opening Playwright.
                    # Another process may have already written a fresh session to disk.
                    # Probe (single HTTP health check) before trusting it — without the
                    # probe, every spawn pays an observable 401 round-trip on the first
                    # real call when the disk session is server-stale.
                    if self._reload_session_from_disk():
                        if self._browser_cookie_header and not self._is_browser_session_expired():
                            if self._is_browser_session_valid(self.config.browser):
                                logger.info("Session restored from disk (fast path) — probe ok.")
                                self._browser_reauth_failure_count = 0
                                self._browser_reauth_cooldown_seconds = (
                                    self._browser_reauth_cooldown_base
                                )
                                self._apply_browser_session_headers(headers)
                                return headers
                            logger.info(
                                "Disk-restored session failed live probe — discarding "
                                "and continuing to interactive re-auth."
                            )
                            self.invalidate_browser_session()

                    # Try browser profile restore (opens Playwright) — now under lock.
                    if self._try_restore_browser_session(self.config.browser):
                        self._browser_reauth_failure_count = 0
                        self._browser_reauth_cooldown_seconds = self._browser_reauth_cooldown_base
                        self._apply_browser_session_headers(headers)
                        return headers

                    # Post-restore disk check: another process may have completed
                    # login while our _try_restore_browser_session was running.
                    # Same probe-before-trust policy as the earlier fast path.
                    if self._reload_session_from_disk():
                        if self._browser_cookie_header and not self._is_browser_session_expired():
                            if self._is_browser_session_valid(self.config.browser):
                                logger.info(
                                    "Session appeared on disk after restore attempt — "
                                    "another process completed login (probe ok)."
                                )
                                self._browser_reauth_failure_count = 0
                                self._browser_reauth_cooldown_seconds = (
                                    self._browser_reauth_cooldown_base
                                )
                                self._apply_browser_session_headers(headers)
                                return headers
                            logger.info(
                                "Disk session from sibling process failed probe — "
                                "discarding and continuing."
                            )
                            self.invalidate_browser_session()

                    # Browser auth is user-driven (MFA/SSO). Always keep interactive mode.
                    if self._browser_login_in_progress:
                        self._browser_login_lock.release()
                        raise ValueError(
                            f"Browser login is currently in progress for "
                            f"{self._instance_profile_label()} — the user is completing MFA/SSO "
                            "authentication. Please wait for the user to finish and then retry "
                            "this request. Do NOT start a new login attempt."
                        )
                    # Cross-process lock: another terminal may already be logging in.
                    if not self._acquire_login_lock():
                        # Another process is logging in — wait for it instead of opening a second browser.
                        if self._wait_for_other_login(
                            timeout=self.config.browser.timeout_seconds + 60
                        ):
                            if self._has_reusable_browser_session(self.config.browser):
                                self._browser_reauth_failure_count = 0
                                self._browser_reauth_cooldown_seconds = (
                                    self._browser_reauth_cooldown_base
                                )
                                self._apply_browser_session_headers(headers)
                                return headers
                            logger.info(
                                "Waited-for cross-process session failed validation. "
                                "Falling back to a local interactive login."
                            )
                            self.invalidate_browser_session()
                        # Timed out waiting — fall through to try login ourselves
                        if not self._acquire_login_lock():
                            raise ValueError(
                                "Browser login is in progress in another terminal for "
                                f"{self._instance_profile_label()}. "
                                "Please complete MFA/SSO there, or close that browser window first."
                            )
                    if not self._can_attempt_browser_reauth():
                        self._release_login_lock()
                        cooldown_remaining = self._get_reauth_cooldown_remaining()
                        self._auth_event(
                            "login.cooldown.refused",
                            cooldown_remaining_s=cooldown_remaining,
                        )
                        raise ValueError(
                            f"Browser session expired — NOT authenticated for "
                            f"{self._instance_profile_label()}. Re-login is on cooldown, so no "
                            f"login window will open yet. Retry this tool call in "
                            f"{cooldown_remaining}s to open a new login window. "
                            f"(Attempt {self._browser_reauth_failure_count} failed — "
                            f"cooldown {self._browser_reauth_cooldown_seconds}s) "
                            "If a browser login window already appeared, complete MFA/SSO there. "
                            "Treat this profile as unauthenticated — do not assume its session is valid."
                        )
                    logger.info(
                        "Triggering browser auth flow (headless-first; falls "
                        "back to a visible window if MFA is required). "
                        "(attempt #%d, cooldown=%ds)",
                        self._browser_reauth_failure_count + 1,
                        self._browser_reauth_cooldown_seconds,
                    )
                    self._mark_browser_reauth_attempt()
                    self._browser_login_in_progress = True
                    try:
                        # force_interactive=False — try headless first (cookie-gated).
                        # _login_with_browser auto-falls back to interactive on
                        # MFA_REQUIRED or timeout markers.
                        self._login_with_browser(self.config.browser, force_interactive=False)
                        # Login succeeded — reset failure state
                        self._browser_reauth_failure_count = 0
                        self._browser_reauth_cooldown_seconds = self._browser_reauth_cooldown_base
                        self._browser_login_in_progress = False
                        self._release_login_lock()
                    except Exception as exc:
                        error_text = str(exc).lower()
                        if "still in progress" in error_text or "still be completing" in error_text:
                            # Thread join timed out but browser is still open for user MFA.
                            # Keep _browser_login_in_progress=True so concurrent calls
                            # see "login in progress" and don't open duplicate windows.
                            # Keep lock held — browser is still open.
                            logger.info(
                                "Browser login thread still running — keeping login_in_progress=True"
                            )
                        else:
                            self._browser_login_in_progress = False
                            self._release_login_lock()
                        user_closed = _looks_like_user_close(error_text)
                        if user_closed:
                            # If session was already captured (cookies + key set
                            # by the success path before this exception), the
                            # close is benign — user just dismissed an already-
                            # successful window. Treat as success, no cooldown.
                            if self._browser_cookie_header and self._browser_session_key:
                                logger.info(
                                    "Browser closed after session was captured — "
                                    "ignoring (treating as successful login)."
                                )
                                self._browser_reauth_failure_count = 0
                                self._browser_reauth_cooldown_seconds = (
                                    self._browser_reauth_cooldown_base
                                )
                                self._apply_browser_session_headers(headers)
                                return headers
                            # Genuine user cancellation before auth completed.
                            user_close_cooldown = (
                                15  # 15s — break instant LLM auto-retry on user-cancelled login
                            )
                            self._browser_reauth_failure_count = max(
                                self._browser_reauth_failure_count, 1
                            )
                            self._browser_reauth_cooldown_seconds = user_close_cooldown
                            self._browser_last_reauth_attempt_at = time.time()
                            logger.info(
                                "Browser was closed by user — applying %ds cooldown to "
                                "prevent immediate reopen.",
                                user_close_cooldown,
                            )
                            # Replace the raw Playwright "target closed" exception with a
                            # clear cancellation signal so the LLM stops retrying.
                            raise ValueError(
                                f"LOGIN_CANCELLED_BY_USER ({self._instance_profile_label()}): "
                                "the browser login window was closed before authentication "
                                "completed — this profile is NOT authenticated. Wait "
                                f"{user_close_cooldown}s then explicitly retry to open a "
                                "new login window. Do NOT auto-retry — the user closed "
                                "the previous window on purpose."
                            ) from exc
                        else:
                            self._browser_reauth_failure_count += 1
                            self._browser_reauth_cooldown_seconds = min(
                                self._browser_reauth_cooldown_base
                                * (2**self._browser_reauth_failure_count),
                                self._browser_reauth_cooldown_max,
                            )
                            logger.warning(
                                "Browser re-auth failed (attempt #%d). Next retry cooldown: %ds",
                                self._browser_reauth_failure_count,
                                self._browser_reauth_cooldown_seconds,
                            )
                        raise
                finally:
                    try:
                        self._browser_login_lock.release()
                    except RuntimeError:
                        pass  # Already released
            elif self._should_validate_browser_session():
                # Disk-first: if another process already refreshed the session,
                # pick it up and skip the server probe entirely.
                if self._reload_session_from_disk():
                    logger.info("Validation skipped — picked up fresher session from disk.")
                elif not self._is_browser_session_valid(self.config.browser):
                    logger.info(
                        "Browser session is no longer valid on ServiceNow. "
                        "Triggering re-auth flow (headless-first; visible window "
                        "only if MFA is required)..."
                    )
                    self.invalidate_browser_session()
                    if not self._acquire_login_lock():
                        if self._wait_for_other_login(
                            timeout=self.config.browser.timeout_seconds + 60
                        ):
                            self._apply_browser_session_headers(headers)
                            return headers
                        # Wait timed out — peer process is still logging in.
                        # Retry the lock once: if the peer has since released
                        # we can take over; otherwise refuse rather than
                        # opening a duplicate browser window.
                        if not self._acquire_login_lock():
                            raise ValueError(
                                "Browser login is in progress in another terminal. "
                                "Please complete MFA/SSO there, or close that browser "
                                "window first, then retry this tool call."
                            )
                    self._mark_browser_reauth_attempt()
                    self._browser_login_in_progress = True
                    try:
                        # force_interactive=False — try headless first (cookie-gated).
                        # _login_with_browser auto-falls back to interactive on
                        # MFA_REQUIRED or timeout markers.
                        self._login_with_browser(self.config.browser, force_interactive=False)
                        self._browser_reauth_failure_count = 0
                        self._browser_reauth_cooldown_seconds = self._browser_reauth_cooldown_base
                        self._browser_login_in_progress = False
                        self._release_login_lock()
                    except Exception as exc:
                        error_text = str(exc).lower()
                        if "still in progress" in error_text or "still be completing" in error_text:
                            logger.info(
                                "Browser login thread still running — keeping login_in_progress=True"
                            )
                            raise
                        self._browser_login_in_progress = False
                        self._release_login_lock()
                        user_closed = _looks_like_user_close(error_text)
                        if user_closed:
                            # Benign post-success close: session already captured,
                            # treat as success and skip cooldown.
                            if self._browser_cookie_header and self._browser_session_key:
                                logger.info(
                                    "Browser closed after session was captured — "
                                    "ignoring (treating as successful login)."
                                )
                                self._browser_reauth_failure_count = 0
                                self._browser_reauth_cooldown_seconds = (
                                    self._browser_reauth_cooldown_base
                                )
                                self._apply_browser_session_headers(headers)
                                return headers
                            user_close_cooldown = (
                                15  # 15s — break instant LLM auto-retry on user-cancelled login
                            )
                            self._browser_reauth_failure_count = max(
                                self._browser_reauth_failure_count, 1
                            )
                            self._browser_reauth_cooldown_seconds = user_close_cooldown
                            self._browser_last_reauth_attempt_at = time.time()
                            logger.info(
                                "Browser was closed by user — applying %ds cooldown to "
                                "prevent immediate reopen.",
                                user_close_cooldown,
                            )
                            raise ValueError(
                                f"LOGIN_CANCELLED_BY_USER ({self._instance_profile_label()}): "
                                "the browser login window was closed before authentication "
                                "completed — this profile is NOT authenticated. Wait "
                                f"{user_close_cooldown}s then explicitly retry to open a "
                                "new login window. Do NOT auto-retry — the user closed "
                                "the previous window on purpose."
                            ) from exc
                        self._browser_reauth_failure_count += 1
                        self._browser_reauth_cooldown_seconds = min(
                            self._browser_reauth_cooldown_base
                            * (2**self._browser_reauth_failure_count),
                            self._browser_reauth_cooldown_max,
                        )
                        raise
            self._apply_browser_session_headers(headers)

        return headers

    def _is_token_expired(self) -> bool:
        if self.token_expires_at is None:
            return False
        return time.time() >= self.token_expires_at

    def _is_browser_session_expired(self) -> bool:
        if self._browser_cookie_expires_at is None:
            return False
        return time.time() >= self._browser_cookie_expires_at

    def session_status(self) -> str:
        """Last-known auth state for this instance — NO network call.

        Explicit, deterministic state for multi-instance visibility (e.g.
        list_instances). NOTE: `session_cached` means we hold local cookies, not
        that the server still honours them — true liveness is verified on each
        real request (the server can invalidate a session at any time).

        Returns one of:
          - `credentials`     : non-browser auth (basic/oauth/api_key) — header-based.
          - `session_cached`  : browser cookies held locally and not TTL-expired.
          - `no_session`      : no usable browser session — interactive login required.
        """
        if self.config.type != AuthType.BROWSER:
            return "credentials"
        if self._browser_cookie_header and not self._is_browser_session_expired():
            return "session_cached"
        return "no_session"

    def _should_validate_browser_session(self) -> bool:
        if not self._browser_cookie_header:
            return False
        if self._browser_last_login_at is not None:
            if (time.time() - self._browser_last_login_at) < self._browser_post_login_grace_seconds:
                return False
        if self._browser_last_validated_at is None:
            return True
        return (
            time.time() - self._browser_last_validated_at
        ) >= self._browser_validation_interval_seconds

    def _can_attempt_browser_reauth(self) -> bool:
        if self._browser_last_reauth_attempt_at is None:
            return True
        return (
            time.time() - self._browser_last_reauth_attempt_at
        ) >= self._browser_reauth_cooldown_seconds

    def _mark_browser_reauth_attempt(self) -> None:
        self._browser_last_reauth_attempt_at = time.time()

    def _clear_browser_reauth_attempt(self) -> None:
        self._browser_last_reauth_attempt_at = None

    def _get_reauth_cooldown_remaining(self) -> int:
        """Return remaining cooldown seconds before next re-auth attempt."""
        if self._browser_last_reauth_attempt_at is None:
            return 0
        return max(
            0,
            int(
                self._browser_reauth_cooldown_seconds
                - (time.time() - self._browser_last_reauth_attempt_at)
            ),
        )

    def _is_browser_session_valid(self, browser_config: BrowserAuthConfig) -> bool:
        if not self.instance_url or not self._browser_cookie_header:
            return False

        # Within post-login grace period: trust the session, skip probe.
        # Avoids re-opening browser due to transient probe failures right after login.
        if self._browser_last_login_at is not None:
            if (time.time() - self._browser_last_login_at) < self._browser_post_login_grace_seconds:
                logger.debug(
                    "Skipping session probe — within post-login grace period (%ds)",
                    self._browser_post_login_grace_seconds,
                )
                self._browser_last_validated_at = time.time()
                return True

        try:
            response = self._probe_browser_api_with_cookie(
                self._browser_cookie_header,
                timeout_seconds=min(int(browser_config.timeout_seconds), 30),
                browser_config=browser_config,
            )
        except Exception as exc:
            logger.warning(
                "Browser session validation probe failed: %s. "
                "Marking session as invalid to be safe.",
                exc,
            )
            return False

        self._browser_last_validated_at = time.time()
        # v1.12.21: compute is_redirect inline. ``requests.Response.is_redirect``
        # is requests-specific; curl_cffi's Response object exposes
        # status_code/headers/url but not that property, so the previous
        # ``response.is_redirect`` reference crashed under default-ON
        # impersonation. The semantics it tested for were "3xx with a
        # Location header" — recompute that directly.
        is_redirect = 300 <= response.status_code < 400 and bool(response.headers.get("Location"))
        logger.debug(
            "Browser session probe result: status=%s redirect=%s url_host=%s",
            response.status_code,
            is_redirect,
            (urlparse(str(response.url)).hostname or "").lower(),
        )

        if not _response_confirms_browser_probe_session(response):
            return False

        if response.status_code == 403:
            logger.info(
                "Browser session probe is authenticated but unauthorized for probe path: "
                "status=%s probe_path=%s",
                response.status_code,
                browser_config.probe_path,
            )
            return True

        return True

    def _has_reusable_browser_session(self, browser_config: BrowserAuthConfig) -> bool:
        """Return True only when the current browser session is safe to reuse."""
        if not self._browser_cookie_header or self._is_browser_session_expired():
            return False
        if not self._should_validate_browser_session():
            return True
        # Coalesce concurrent probes: only one thread issues the round-trip;
        # waiters re-check the validation timestamp after the lock and skip if
        # the leader already updated it.
        with self._browser_probe_lock:
            if not self._should_validate_browser_session():
                return True
            if not self._is_browser_session_valid(browser_config):
                return False
        return True

    def _mark_browser_session_recently_valid(self) -> None:
        """Treat a successful authenticated API response as proof that the
        browser-backed session is still alive.

        This avoids paying an additional validation probe on the next request
        when the server already accepted the current cookie + user token pair.

        v1.11.47: also resets the consecutive-self-heal counter — a successful
        response means the server is happy with our session, so the next time
        a logout-302 fires we should start the escalation ladder from zero
        again (don't force MFA based on stale counter state).

        v1.15.x: SLIDE the session TTL on proven activity. ServiceNow's
        session inactivity timeout is sliding — each authenticated request
        resets it server-side. Previously our ``_browser_cookie_expires_at``
        was a FIXED window from login time, so an actively-used session was
        torn down and re-logged-in every ~TTL minutes even under continuous
        use (the "login window every 30 min" complaint). Pushing the expiry
        forward on each confirmed-alive response mirrors the server. If the
        server has actually ended the session (real idle gap or a hard cap),
        the next request 401s and the normal self-heal re-login runs — so this
        never keeps a genuinely-dead session alive, it only stops us giving up
        on a live one early.
        """
        now = time.time()
        self._browser_last_validated_at = now
        self._consecutive_self_heal_count = 0
        if self._browser_cookie_expires_at is not None and self.config.browser:
            ttl_seconds = (self.config.browser.session_ttl_minutes or 30) * 60
            self._browser_cookie_expires_at = now + ttl_seconds

    def _absorb_response_bigip_rotation(self, response: requests.Response) -> Optional[str]:
        """v1.12.18: when a logout-redirect response carries a new
        ``BIGipServerpool_<host>`` value, overwrite the captured cookie
        with the F5-indicated backend so the *next* request lands on
        the server that actually hosts the session.

        Returns the new BIG-IP value (first 8 chars) if updated, else None.
        Caller is expected to retry the failed request once with the
        updated cookies; the retry path is bounded inside ``make_request``
        so this cannot loop.
        """
        if self.config.type != AuthType.BROWSER:
            return None
        if not self._browser_cookie_header:
            return None
        hint = _extract_bigip_routing_hint(response)
        if not hint:
            return None
        name, new_value = hint
        current = _cookie_header_to_dict(self._browser_cookie_header).get(name)
        if current == new_value:
            return None  # same backend — not a redirection hint
        self._browser_cookie_header = _replace_cookie_value_in_header(
            self._browser_cookie_header, name, new_value
        )
        # Persist so a sibling MCP for the same user picks up the corrected
        # routing on its next disk reload instead of repeating the dance.
        try:
            self._save_session_to_disk()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to persist BIG-IP-rotated cookie: %s", exc)
        return new_value[:8]

    def _absorb_response_token_rotation(self, response: requests.Response) -> None:
        """Pick up rotated X-UserToken / X-CSRF-Token from a server response.

        ServiceNow rotates the g_ck (X-UserToken) value periodically and may push
        the new value via the response headers. If we keep using the original
        token captured at login time we eventually hit 401 on mutating calls. By
        absorbing the rotated token immediately, subsequent requests stay valid
        without paying for a re-auth.

        Only updates when the server returned a non-empty token that differs from
        the one currently held in memory, and only for browser-auth managers.
        """
        if self.config.type != AuthType.BROWSER:
            return
        rotated = response.headers.get("X-UserToken") or response.headers.get("X-CSRF-Token")
        if not rotated:
            return
        rotated = rotated.strip()
        if not rotated or rotated == self._browser_session_token:
            return
        self._browser_session_token = rotated
        # Persist the rotated token so other processes pick it up via disk reload
        # on their next request.
        try:
            self._save_session_to_disk()
        except Exception as exc:
            logger.debug("Failed to persist rotated X-UserToken: %s", exc)

    def _probe_browser_api_with_cookie(
        self,
        cookie_header: str,
        timeout_seconds: int,
        browser_config: BrowserAuthConfig,
        *,
        include_user_token: bool = True,
    ) -> requests.Response:
        if not self.instance_url:
            raise ValueError("Instance URL is required for browser authentication")

        probe_target = (
            browser_config.probe_path
            or "/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id"
        )
        parsed_probe = urlparse(probe_target)
        probe_url = (
            probe_target
            if parsed_probe.scheme and parsed_probe.netloc
            else urljoin(f"{self.instance_url.rstrip('/')}/", probe_target.lstrip("/"))
        )
        parsed_url = urlparse(probe_url)
        probe_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        if parsed_url.query:
            probe_url = parsed_url._replace(query="").geturl()
        probe_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._browser_user_agent:
            probe_headers["User-Agent"] = self._browser_user_agent
        # Send X-UserToken (g_ck) when available. ServiceNow's CSRF check
        # rejects API requests without this header on some instances —
        # without it, plain cookie auth gets a 302 to login even when the
        # browser session is fully valid. The token is captured from the
        # live page via `window.g_ck` during the wait loop.
        if include_user_token and self._browser_session_token:
            probe_headers["X-UserToken"] = self._browser_session_token
        # Referer matching the instance keeps strict same-origin checks
        # happy on instances that gate API endpoints behind referer
        # validation.
        if self.instance_url:
            probe_headers["Referer"] = self.instance_url.rstrip("/") + "/"
        probe_cookies = _cookie_header_to_dict(cookie_header)
        # Diagnostic log — without this, post-login 302 loops are nearly
        # impossible to debug from logs alone (we can't tell whether cookie
        # capture lost a required cookie like `factor`, whether g_ck was
        # captured, or whether the server redirected us somewhere unexpected).
        logger.debug(
            "Browser probe outgoing: url=%s cookies=%s x_usertoken=%s referer=%s",
            probe_url,
            ",".join(sorted(probe_cookies.keys())),
            "set" if probe_headers.get("X-UserToken") else "MISSING",
            probe_headers.get("Referer", ""),
        )
        response = self._http_session.get(
            probe_url,
            params=probe_params,
            headers=probe_headers,
            cookies=probe_cookies,
            timeout=timeout_seconds,
            allow_redirects=False,
        )
        # Capture redirect Location on non-success — the exact destination
        # tells us why ServiceNow refused the cookies (login.do vs
        # logout_success.do vs anywhere else).
        try:
            status = int(response.status_code)
        except (TypeError, ValueError):
            status = 0
        if 300 <= status < 400:
            logger.debug(
                "Browser probe redirected: status=%s location=%s",
                response.status_code,
                response.headers.get("Location", ""),
            )
        return response

    def _try_restore_browser_session(self, browser_config: BrowserAuthConfig) -> bool:
        if not self.instance_url:
            return False
        instance_url = self.instance_url
        instance_host = (urlparse(instance_url).hostname or "").lower()
        timeout_ms = min(int(browser_config.timeout_seconds), 30) * 1000
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except Exception:
            return False

        effective_user_data_dir = self._resolve_user_data_dir(browser_config)
        logger.info(
            "Attempting browser session restore from persistent profile: host=%s user_data_dir=%s",
            instance_host,
            effective_user_data_dir,
        )

        # Playwright Sync API cannot run inside an active asyncio loop. MCP
        # tool dispatch runs us under asyncio, so naive sync_playwright() use
        # raised "It looks like you are using Playwright Sync API inside the
        # asyncio loop" → restore failed → every spawn fell through to a fresh
        # interactive login. Detect the active loop and offload to a thread,
        # mirroring _login_with_browser's pattern.
        try:
            import asyncio as _asyncio

            _loop = _asyncio.get_running_loop()
            if _loop and _loop.is_running():
                import threading as _threading

                holder: dict = {"ok": False, "exc": None}

                def _run_in_thread() -> None:
                    try:
                        holder["ok"] = self._try_restore_browser_session_sync(
                            browser_config, instance_url, instance_host, timeout_ms
                        )
                    except BaseException as _exc:  # noqa: BLE001
                        holder["exc"] = _exc

                _t = _threading.Thread(target=_run_in_thread, daemon=True)
                _t.start()
                _t.join(timeout=max(int(browser_config.timeout_seconds), 30) + 30)
                if _t.is_alive():
                    logger.info("Browser session restore thread timed out — skipping.")
                    return False
                if holder["exc"] is not None:
                    logger.info("Browser session restore thread raised: %s", holder["exc"])
                    return False
                return bool(holder["ok"])
        except RuntimeError:
            # No running event loop — fall through to direct sync execution.
            pass

        return self._try_restore_browser_session_sync(
            browser_config, instance_url, instance_host, timeout_ms
        )

    def _try_restore_browser_session_sync(
        self,
        browser_config: BrowserAuthConfig,
        instance_url: str,
        instance_host: str,
        timeout_ms: int,
    ) -> bool:
        from playwright.sync_api import sync_playwright

        effective_user_data_dir = self._resolve_user_data_dir(browser_config)
        cookie_header: Optional[str] = None
        try:
            with sync_playwright() as playwright:
                # Always headless for restore — this only checks cookies,
                # no user interaction needed.  Avoids a visible browser flash
                # that looks like a second login prompt.
                context = _launch_persistent_with_retry(
                    playwright.chromium,
                    effective_user_data_dir,
                    headless=True,
                )
                # Always close the persistent context, even if any page op below raises —
                # otherwise the Chromium window leaks and the user sees a stuck browser.
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    try:
                        page.goto(instance_url, timeout=timeout_ms, wait_until="domcontentloaded")
                    except Exception:
                        # Navigation can fail transiently; cookie probe below is authoritative.
                        pass
                    # Capture User-Agent and Session Token (g_ck) for session consistency
                    self._browser_user_agent = page.evaluate("navigator.userAgent")
                    try:
                        self._browser_session_token = page.evaluate("window.g_ck")
                    except Exception:
                        self._browser_session_token = None
                    cookies = context.cookies()
                    cookie_header = self._build_instance_cookie_header(
                        cookies,  # type: ignore[arg-type]
                        instance_url,
                        instance_host,
                    )
                finally:
                    try:
                        context.close()
                    except Exception as close_exc:
                        logger.debug("Restore context.close() raised: %s (ignored)", close_exc)
        except Exception as exc:
            logger.info("Browser session restore failed while opening profile: %s", exc)
            return False

        if not cookie_header:
            logger.info("Browser session restore skipped: no instance cookies found")
            return False

        try:
            probe = self._probe_browser_api_with_cookie(
                cookie_header,
                timeout_seconds=10,
                browser_config=browser_config,
            )
        except requests.RequestException as exc:
            logger.info("Browser session restore probe failed: %s", exc)
            self._auth_event(
                "profile.restore.network_error",
                error=str(exc)[:120],
            )
            return False

        if not _response_confirms_browser_probe_session(probe):
            probe_location = (probe.headers.get("Location") or "").lower()
            went_to_logout = (
                "logout_success" in probe_location
                or "/logout.do" in probe_location
                or _response_redirected_through_logout(probe)
            )
            if went_to_logout:
                self._consecutive_self_heal_count += 1
                # v1.12.0: do NOT auto-trigger full profile purge. Repeated
                # logout-302s do not necessarily mean mfa_remembered is
                # poisoned, and forcing MFA on every recovery proved more
                # painful than helpful in production. Counter increments
                # feed the circuit breaker, which stops re-auth after
                # _SELF_HEAL_CIRCUIT_THRESHOLD failures.
                logger.info(
                    "Browser session restore probe redirected to logout "
                    "(consecutive=%d) — mfa_remembered preserved.",
                    self._consecutive_self_heal_count,
                )
            logger.info(
                "Browser session restore probe rejected cached cookies: status=%s",
                probe.status_code,
            )
            self._auth_event(
                "profile.restore.rejected",
                logout_redirect=went_to_logout,
                attempted_cookies=_format_cookie_values_for_log(cookie_header),
                **{f"resp_{k}": v for k, v in _format_response_diagnostic(probe).items()},
            )
            return False

        if probe.status_code == 403:
            logger.info(
                "Browser session restore probe returned %s — authenticated but unauthorized "
                "for probe path (probe_path=%s). Accepting session.",
                probe.status_code,
                browser_config.probe_path,
            )

        self._browser_cookie_header = cookie_header
        self._browser_cookie_expires_at = time.time() + (browser_config.session_ttl_minutes * 60)
        self._browser_session_key = instance_host
        self._browser_last_validated_at = time.time()
        self._browser_last_login_at = time.time()
        self._clear_browser_reauth_attempt()
        self._save_session_to_disk()
        logger.info(
            "Browser session restored: session_key=%s cookie_count=%s cookie_names=%s ttl_minutes=%s",
            self._browser_session_key,
            len(_extract_cookie_names(self._browser_cookie_header)),
            ",".join(_extract_cookie_names(self._browser_cookie_header)),
            browser_config.session_ttl_minutes,
        )
        return True

    def _build_instance_cookie_header(
        self, cookies: list[dict], instance_url: str, instance_host: str
    ) -> Optional[str]:
        candidates: list[dict] = []
        for cookie in cookies:
            domain = str(cookie.get("domain", "")).lstrip(".").lower()
            # Accept both instance-scoped cookies (foo.instance.service-now.com)
            # and parent-domain cookies (.service-now.com) that apply to the instance.
            if not (domain.endswith(instance_host) or instance_host.endswith(domain)):
                continue
            # Some enterprise SSO chains issue required instance cookies without
            # the secure flag in browser context metadata. Keep domain-scoped
            # cookies and let server-side probe decide session validity.
            candidates.append(cookie)

        if not candidates:
            return None

        # Deduplicate by cookie name to avoid sending conflicting values from
        # parent + child domains. Prefer instance-specific domain cookies.
        def _priority(c: dict) -> tuple[int, int]:
            domain = str(c.get("domain", "")).lstrip(".").lower()
            is_instance_specific = 1 if domain.endswith(instance_host) else 0
            return (is_instance_specific, len(domain))

        deduped: dict[str, dict] = {}
        for cookie in sorted(candidates, key=_priority, reverse=True):
            name = str(cookie.get("name", "")).strip()
            if not name or name in deduped:
                continue
            deduped[name] = cookie

        return "; ".join([f"{c['name']}={c['value']}" for c in deduped.values()])

    def _is_instance_cookie(self, cookie: dict, instance_host: str) -> bool:
        domain = str(cookie.get("domain", "")).lstrip(".").lower()
        return bool(domain and domain.endswith(instance_host))

    def _get_oauth_token(self):
        """
        Get an OAuth token from ServiceNow.

        Raises:
            ValueError: If OAuth configuration is missing or token request fails.
        """
        if not self.config.oauth:
            raise ValueError("OAuth configuration is required")
        oauth_config = self.config.oauth

        # Determine token URL
        token_url = oauth_config.token_url
        if not token_url:
            if not self.instance_url:
                raise ValueError("Instance URL is required for OAuth authentication")
            instance_parts = self.instance_url.split(".")
            if len(instance_parts) < 2:
                raise ValueError(f"Invalid instance URL: {self.instance_url}")
            instance_name = instance_parts[0].split("//")[-1]
            token_url = f"https://{instance_name}.service-now.com/oauth_token.do"

        # Prepare Authorization header
        auth_str = f"{oauth_config.client_id}:{oauth_config.client_secret}"
        auth_header = base64.b64encode(auth_str.encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Try client_credentials grant first
        data_client_credentials = {"grant_type": "client_credentials"}

        logger.info("Attempting client_credentials grant...")
        response = self._http_session.post(token_url, headers=headers, data=data_client_credentials)

        logger.info(f"client_credentials response status: {response.status_code}")

        if response.status_code == 200:
            token_data = response.json()
            self.token = token_data.get("access_token")
            self.token_type = token_data.get("token_type", "Bearer")
            expires_in = token_data.get("expires_in")
            if isinstance(expires_in, (int, float)):
                self.token_expires_at = time.time() + float(expires_in)
            return

        # Try password grant if client_credentials failed
        if oauth_config.username and oauth_config.password:
            data_password = {
                "grant_type": "password",
                "username": oauth_config.username,
                "password": oauth_config.password,
            }

            logger.info("Attempting password grant...")
            response = self._http_session.post(token_url, headers=headers, data=data_password)

            logger.info(f"password grant response status: {response.status_code}")

            if response.status_code == 200:
                token_data = response.json()
                self.token = token_data.get("access_token")
                self.token_type = token_data.get("token_type", "Bearer")
                expires_in = token_data.get("expires_in")
                if isinstance(expires_in, (int, float)):
                    self.token_expires_at = time.time() + float(expires_in)
                return

        raise ValueError(
            "Failed to get OAuth token using both client_credentials and password grants."
        )

    def refresh_token(self):
        """Refresh the OAuth token if using OAuth authentication."""
        if self.config.type == AuthType.OAUTH:
            self._get_oauth_token()

    def _login_with_browser(
        self, browser_config: BrowserAuthConfig, force_interactive: bool = False
    ) -> None:
        """
        Run browser login safely when called from either sync or async contexts.

        Playwright Sync API cannot run inside an active asyncio event loop.
        MCP tool execution may happen while an event loop is active, so we
        offload Sync API usage to a separate thread in that case.
        """
        # The actual login is the first point that genuinely needs Chromium.
        # If startup flagged Playwright/Chromium as not ready, re-probe now
        # (the user may have installed it since) so a still-missing binary
        # surfaces the precise "playwright install chromium" remediation as the
        # tool-call error — instead of a raw Playwright stack or silent timeout.
        # On success, clear the flag so instructions/sn_health stop nagging.
        # Skip the re-probe when startup was already clean: it launches a real
        # browser, so doing it every login would be wasteful.
        if self._browser_setup_error is not None:
            self._ensure_playwright_ready()
            self._browser_setup_error = None

        # Hard ceiling for thread join — in interactive mode give generous time
        # for MFA/SSO (user must open authenticator app, read code, type it in).
        # Do NOT close the browser or raise an error while the user is still working.
        if force_interactive:
            join_timeout = max(int(browser_config.timeout_seconds) + 120, 600)
        else:
            join_timeout = max(int(browser_config.timeout_seconds) + 60, 360)

        def _run_sync_login(interactive: bool) -> None:
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                if loop.is_running():
                    error_holder: list[BaseException] = []

                    def _runner() -> None:
                        try:
                            self._login_with_browser_sync(browser_config, interactive)
                            # Login succeeded — if thread was still running after join timeout,
                            # clear the in-progress flag so next tool call can proceed.
                            self._browser_login_in_progress = False
                        except BaseException as exc:  # noqa: BLE001
                            self._browser_login_in_progress = False
                            error_holder.append(exc)

                    thread = threading.Thread(target=_runner, daemon=True)
                    thread.start()
                    thread.join(timeout=join_timeout)

                    if thread.is_alive():
                        # The browser is still open — user may still be completing MFA.
                        # Do NOT close or kill it. Keep login_in_progress=True so that
                        # concurrent tool calls see "login in progress" instead of
                        # triggering a duplicate browser window.
                        logger.warning(
                            "Browser login thread still running after %ss. "
                            "The user may still be completing MFA — keeping browser open.",
                            join_timeout,
                        )
                        raise ValueError(
                            f"Browser login is still in progress after {join_timeout}s. "
                            "The user may still be completing MFA/SSO authentication. "
                            "The browser window remains open — please wait for the user to finish "
                            "and then retry. Do NOT close the browser or start a new login."
                        )

                    if error_holder:
                        raise error_holder[0]
                    return
            except RuntimeError:
                # No running event loop in this thread; safe to execute sync API directly.
                pass

            self._login_with_browser_sync(browser_config, interactive)

        try:
            _run_sync_login(force_interactive)
        except Exception as exc:  # noqa: BLE001 — fallback decision uses marker text
            error_text = str(exc).lower()
            mfa_required = "mfa_required" in error_text
            headless_timeout = "timed out waiting for browser login/mfa" in error_text
            should_fallback_to_interactive = not force_interactive and (
                headless_timeout or mfa_required
            )
            if should_fallback_to_interactive:
                if mfa_required:
                    logger.info(
                        "Headless login attempt detected MFA requirement "
                        "(no remembered cookie or MFA prompt) — opening visible "
                        "browser for interactive MFA/SSO."
                    )
                else:
                    logger.info(
                        "Headless login attempt timed out — falling back to "
                        "interactive re-auth with prefilled credentials."
                    )
                _run_sync_login(True)
                return
            raise

    def _purge_stale_profile_cookies(self, context, instance_host: str) -> int:
        """Drop session-bound cookies from the persistent Chromium profile.

        Called when ``self._needs_profile_cookie_purge`` is set (after an
        invalidate, or when a probe redirected to ``logout_success.do``).

        Default behavior preserves ``glide_mfa_remembered_browser`` (v1.11.20).
        The v1.11.18 ``/logout.do`` flush is what actually unblocks the
        phantom-session loop, so the MFA-remembered cookie can stay and
        let the user skip the MFA prompt on the next login.

        v1.11.46: when ``self._needs_full_profile_purge`` is also set, drop
        ``glide_mfa_remembered_browser`` too. Required for self-heal
        recovery: the previous session was torn down server-side, and
        reusing mfa_remembered skips MFA on the next login → no ``factor``
        cookie minted → server keeps rejecting the cookie-jar → infinite
        login loop. Forcing full MFA on self-heal re-mints ``factor`` and
        the loop breaks.

        ``instance_host`` is informational — Playwright's
        ``clear_cookies(name=...)`` matches by name and we let it remove the
        cookie wherever it lives in the jar (covers the ``.service-now.com``
        and bare-host duplicates ServiceNow sometimes ships).

        Returns the number of cookie names successfully cleared.
        """
        full_purge = self._needs_full_profile_purge
        cookie_names: tuple[str, ...] = _STALE_PROFILE_COOKIE_NAMES
        if full_purge:
            cookie_names = cookie_names + ("glide_mfa_remembered_browser",)
        cleared = 0
        for cookie_name in cookie_names:
            try:
                context.clear_cookies(name=cookie_name)
                cleared += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "clear_cookies(name=%s) raised: %s (ignored)",
                    cookie_name,
                    exc,
                )
        # Consume the full-purge flag so it doesn't carry over to the next
        # routine invalidation. v1.11.46.
        self._needs_full_profile_purge = False
        logger.info(
            "Purged stale session cookies from persistent profile: " "host=%s cleared=%s (%s).",
            instance_host,
            cleared,
            (
                "full purge — mfa_remembered dropped, next login will force MFA"
                if full_purge
                else "mfa-remembered preserved — MFA prompt skipped if cookie still valid server-side"
            ),
        )
        return cleared

    def _try_profile_cookies_directly(self, browser_config: BrowserAuthConfig) -> bool:
        """v1.11.49: try the persistent profile's live cookies as a session,
        without touching login.do or logout.do.

        Mirrors `_try_restore_browser_session_sync` but reads cookies from a
        Playwright persistent context directly (instead of from the disk
        session JSON), so it catches the case where the profile has fresh
        cookies the disk cache hasn't seen yet — e.g. when the user has been
        interacting with ServiceNow in the same browser profile out-of-band.

        Returns True iff the probe with profile cookies confirmed an
        authenticated session; in that case, session state is populated and
        the caller should NOT proceed with the login flow.
        """
        if not self.instance_url:
            return False
        try:
            from playwright.sync_api import sync_playwright
        except Exception:  # noqa: BLE001
            return False

        instance_host = (urlparse(self.instance_url).hostname or "").lower()
        effective_user_data_dir = self._resolve_user_data_dir(browser_config)
        try:
            with sync_playwright() as playwright:
                context = _launch_persistent_with_retry(
                    playwright.chromium,
                    effective_user_data_dir,
                    headless=True,  # invisible — we are just inspecting cookies
                )
                try:
                    profile_cookies = context.cookies()
                    cookie_header = self._build_instance_cookie_header(
                        profile_cookies, self.instance_url, instance_host
                    )
                    if not cookie_header:
                        return False
                    probe = self._probe_browser_api_with_cookie(
                        cookie_header,
                        timeout_seconds=10,
                        browser_config=browser_config,
                    )
                    if not _response_confirms_browser_probe_session(probe):
                        return False
                    # Profile already has a valid session. Capture g_ck
                    # + User-Agent from a lightweight navigation so the
                    # captured headers match what make_request will send.
                    page = context.pages[0] if context.pages else context.new_page()
                    try:
                        ua = page.evaluate("navigator.userAgent")
                        if isinstance(ua, str) and ua.strip():
                            self._browser_user_agent = ua.strip()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        page.goto(
                            self.instance_url.rstrip("/")
                            + "/now/nav/ui/classic/params/target/home_splash.do",
                            timeout=10_000,
                            wait_until="domcontentloaded",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug(
                            "Profile-cookie home navigation failed: %s (ignored, "
                            "session still considered valid based on probe).",
                            exc,
                        )
                    try:
                        gck = page.evaluate("window.g_ck")
                        if isinstance(gck, str) and gck.strip():
                            self._browser_session_token = gck.strip()
                    except Exception:  # noqa: BLE001
                        pass
                    self._browser_cookie_header = cookie_header
                    self._browser_cookie_expires_at = time.time() + (
                        browser_config.session_ttl_minutes * 60
                    )
                    self._browser_session_key = instance_host
                    self._browser_last_validated_at = time.time()
                    self._browser_last_login_at = time.time()
                    self._clear_browser_reauth_attempt()
                    self._consecutive_self_heal_count = 0
                    self._save_session_to_disk()
                    logger.info(
                        "Browser session adopted from live profile cookies — "
                        "no logout/login dance, no MFA. cookie_count=%d "
                        "g_ck_present=%s",
                        len(profile_cookies),
                        bool(self._browser_session_token),
                    )
                    return True
                finally:
                    try:
                        context.close()
                    except Exception:  # noqa: BLE001
                        pass
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Profile-cookie direct probe failed: %s — falling through to login.",
                exc,
            )
            return False
        return False

    def _enforce_login_circuit(self) -> None:
        """Circuit-breaker guard at browser-login entry (extracted).

        Cohesive prologue — returns to allow the login, or raises
        SELF_HEAL_CIRCUIT_OPEN. Runs BEFORE any window opens, so no
        window-close path is involved. Mirror of _enforce_self_heal_circuit
        on the request side. Pinned by test_browser_grace_period.py."""
        # v1.11.48: circuit breaker enforcement at login entry.
        # Once the breaker is open (≥ threshold consecutive 302→logouts),
        # opening another browser window just produces another rejected
        # session and another MFA prompt. Bail out immediately. The user
        # restarting MCP or hitting a successful response resets the
        # counter and re-enables login.
        if self._consecutive_self_heal_count >= _SELF_HEAL_CIRCUIT_THRESHOLD:
            logger.error(
                "Browser login blocked: SELF_HEAL_CIRCUIT_OPEN "
                "(consecutive_self_heal=%d ≥ %d). The previous %d sessions "
                "were rejected by the server. Refusing to open another "
                "browser window — another MFA round would not help.",
                self._consecutive_self_heal_count,
                _SELF_HEAL_CIRCUIT_THRESHOLD,
                self._consecutive_self_heal_count,
            )
            self._auth_event(
                "login.circuit.refused",
                threshold=_SELF_HEAL_CIRCUIT_THRESHOLD,
            )
            raise ValueError(
                "SELF_HEAL_CIRCUIT_OPEN: %d consecutive sessions rejected "
                "server-side, including fresh full-MFA logins. Refusing to "
                "trigger yet another browser login. Investigate ACL/account "
                "status on the ServiceNow instance, or restart MCP to reset."
                % self._consecutive_self_heal_count
            )

    def _login_with_browser_sync(
        self, browser_config: BrowserAuthConfig, force_interactive: bool = False
    ) -> None:
        instance_url = self.instance_url
        if not instance_url:
            raise ValueError("Instance URL is required for browser authentication")

        # v1.12.0: the v1.11.49 profile-cookie pre-probe was REMOVED.
        # Field report: it sometimes adopted an incomplete cookie set
        # (missing JSESSIONID and BIGipServer*) that passed the
        # sys_user_preference probe but caused parallel API calls to be
        # routed to random load-balancer backends where the session did
        # not exist, producing a wave of 401s. Pre-v1.11.49 callers had
        # been depending on a clean login.do flow that yields a full
        # cookie jar, and the field user confirmed that earlier
        # behaviour was working fine. Helper retained in the file in
        # case a future caller wants to opt back in deliberately.

        self._enforce_login_circuit()

        # v1.12.0: minimum interval between login attempts (safe zone).
        # Server-side abuse detection flags accounts that submit login.do
        # rapidly. Even when the circuit breaker is still closed, two
        # logins within seconds is suspicious. Enforce a hard floor.
        #
        # v1.12.17: removed the v1.12.12 born-dead bypass. That bypass was
        # the load-bearing piece of an auto-recovery cascade that, when the
        # server kept producing born-dead sessions (multi-MCP single-session
        # contention, BIG-IP backend mismatch, abuse detection), looped the
        # user through MFA prompts every retry. With the bypass gone the
        # min-login-interval applies uniformly: born-dead is just another
        # failure that has to wait its turn, surfacing a clear LOGIN_COOLDOWN
        # error instead of silently re-firing login.do.
        now = time.time()
        # Snapshot the cooldown clock BEFORE we overwrite it below. A
        # headless pre-attempt that bails without firing a real login.do
        # (no remembered cookie, or the server bounced us to an MFA page)
        # restores this value before raising, so the immediate visible
        # fallback in _login_with_browser is NOT blocked by LOGIN_COOLDOWN.
        prev_last_login_started_at = self._last_login_started_at
        since_last = now - self._last_login_started_at if self._last_login_started_at else None
        if since_last is not None and since_last < _MIN_LOGIN_INTERVAL_SECONDS:
            remaining = _MIN_LOGIN_INTERVAL_SECONDS - since_last
            logger.warning(
                "Browser login blocked: last attempt was %.1fs ago, "
                "minimum interval is %.1fs. Refusing to fire another login.do "
                "submission. %.1fs until allowed.",
                since_last,
                _MIN_LOGIN_INTERVAL_SECONDS,
                remaining,
            )
            self._auth_event(
                "login.rate_limited",
                since_last_s=f"{since_last:.1f}",
                remaining_s=f"{remaining:.1f}",
                min_interval_s=_MIN_LOGIN_INTERVAL_SECONDS,
            )
            raise ValueError(
                f"LOGIN_COOLDOWN: previous browser login attempted {since_last:.1f}s "
                f"ago. Wait {remaining:.1f}s before retrying — back-to-back login "
                f"submissions risk getting the account flagged."
            )
        self._last_login_started_at = now
        self._auth_event(
            "login.start",
            interactive=not (browser_config.headless and not force_interactive),
            force_interactive=force_interactive,
            needs_full_purge=self._needs_full_profile_purge,
        )

        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise ValueError(
                "Playwright is required for browser authentication. "
                "Install with: pip install playwright && playwright install chromium"
            ) from exc

        login_url = browser_config.login_url or f"{instance_url}/login.do"
        timeout_ms = int(browser_config.timeout_seconds) * 1000
        # The actual visibility decision: a window is hidden only when the
        # config asks for headless AND no caller forced interactive. Both
        # the wait-budget rule and the startup log key off this, NOT off
        # `force_interactive` alone — otherwise a user with
        # `SERVICENOW_BROWSER_HEADLESS=false` would get a visible window
        # but only the 30 s headless budget, which is what the v1.11.6
        # field bug exposed.
        #
        # Headless-first with a SAFE fallback (v1.15.x). The first attempt
        # (force_interactive=False) runs headless so a valid remembered-browser
        # cookie produces a silent refresh — no visible window stealing the
        # user's cursor/focus mid-work. This is the common case under the 16h
        # MFA "remember this browser" window.
        #
        # The "headless-first" experiment (v1.15.8-1.15.9) was reverted in
        # v1.15.14 because it REGRESSED on real MFA instances: when the server
        # still demands a TOTP despite the cookie, the headless attempt reached
        # validate_multifactor_auth_code.do, timed out at 30s AND burned the
        # 60s min-login-interval, so the visible fallback was blocked by
        # LOGIN_COOLDOWN → re-auth FAILED. We now reintroduce it WITH the three
        # fixes that close exactly that hole:
        #   1. Cookie gate below: no valid remembered cookie → bail immediately
        #      (before any login.do) → fast visible fallback.
        #   2. MFA-page fast-detect in the wait loop: the instant the server
        #      lands us on an MFA challenge, abort (~1s) instead of waiting 30s.
        #   3. Both bail paths restore _last_login_started_at (the cooldown
        #      clock) before raising, so the visible fallback opens NOW.
        # force_interactive=True ALWAYS means visible — it is the "a human must
        # complete MFA/SSO right now" path, so the fallback window must be shown.
        # The first attempt (force_interactive=False) is headless regardless of
        # the SERVICENOW_BROWSER_HEADLESS flag: a valid remembered cookie then
        # refreshes silently, and the gate/fast-detect above route to a visible
        # fallback the moment MFA is actually required.
        use_headless = not force_interactive
        wait_budget_ms = self._compute_login_wait_budget_ms(
            timeout_ms,
            use_headless=use_headless,
            debug_mode=_is_debug_mode(),
        )
        instance_host = (urlparse(instance_url).hostname or "").lower()
        logger.info(
            "Starting browser auth flow: instance_host=%s login_host=%s "
            "timeout_seconds=%s wait_budget_ms=%s mode=%s",
            instance_host,
            (urlparse(login_url).hostname or "").lower(),
            int(browser_config.timeout_seconds),
            wait_budget_ms,
            "headless" if use_headless else "visible",
        )

        effective_user_data_dir = self._resolve_user_data_dir(browser_config)
        with sync_playwright() as playwright:
            context = _launch_persistent_with_retry(
                playwright.chromium,
                effective_user_data_dir,
                headless=use_headless,
            )

            def _safe_close_context() -> None:
                """Close the persistent Chromium context. Idempotent.

                Debug mode (SERVICENOW_BROWSER_DEBUG=true) skips the close so
                the user can inspect the failing request in DevTools.
                """
                if _is_debug_mode():
                    logger.info(
                        "[DEBUG MODE] Keeping browser window open for inspection. "
                        "Close it manually when done."
                    )
                    return
                try:
                    context.close()
                except Exception as _close_exc:  # noqa: BLE001
                    logger.debug("Login context.close() raised: %s (ignored)", _close_exc)

            # Always purge stale session cookies before login.do. The
            # persistent Chromium profile may carry cookies from a prior MCP
            # process whose server-side session has since been killed; if we
            # let those reach the new login.do submission, ServiceNow treats
            # it as a logout flow and 302s every probe to /logout_success.do.
            #
            # By the time we reach _login_with_browser_sync we have already
            # decided we don't have a usable in-memory session — the profile
            # cookies are never trusted directly for API auth, only used to
            # skip MFA via glide_mfa_remembered_browser. Since v1.11.14 also
            # purges that cookie (it was the carry-over tying us to the dead
            # server session), there is nothing left worth preserving.
            #
            # Pre-v1.11.15 this was gated on _needs_profile_cookie_purge,
            # which only fired AFTER an explicit invalidate_browser_session.
            # Field testing showed the very first re-auth after MCP restart
            # skipped the purge and hit the logout_success loop on attempt
            # #1 — the user typed credentials, MFA, watched it fail, and
            # only attempt #2 (which the abort path armed) recovered.
            self._purge_stale_profile_cookies(context, instance_host)
            self._needs_profile_cookie_purge = False

            # Headless gate: bail immediately if the persistent profile has no
            # valid `glide_mfa_remembered_browser` cookie. Without it, login
            # will hit an MFA prompt and stall — no point typing creds into a
            # window the user cannot see. Gated on use_headless, not on
            # force_interactive: when the browser is going to be visible
            # (non-headless), skip the gate and let the user enter MFA.
            # The outer wrapper catches the MFA_REQUIRED marker and falls
            # back to interactive mode.
            if use_headless and not _is_debug_mode():
                if not self._has_valid_mfa_remembered_cookie(context.cookies()):
                    # No usable cookie → MFA is certain and headless can't do
                    # it. We have NOT fired login.do, so restore the cooldown
                    # clock; otherwise the visible fallback would be refused by
                    # LOGIN_COOLDOWN (the v1.15.10 failure mode).
                    self._last_login_started_at = prev_last_login_started_at
                    _safe_close_context()
                    raise ValueError(
                        "MFA_REQUIRED: persistent profile has no valid "
                        "glide_mfa_remembered_browser cookie — falling back to "
                        "interactive login."
                    )

            page = context.pages[0] if context.pages else context.new_page()

            # Store the User-Agent from the browser to match in subsequent requests
            self._browser_user_agent = page.evaluate("navigator.userAgent")

            # Best-effort logout.do flush so a stale server-side session
            # does not redirect the upcoming login.do submission through
            # /logout_success.do. ``sysparm_url=login.do`` asks ServiceNow
            # to land on the login form after logout completes, saving a
            # round-trip on instances that respect the param.
            try:
                page.goto(
                    f"{instance_url.rstrip('/')}/logout.do?sysparm_url=login.do",
                    timeout=10_000,
                    wait_until="domcontentloaded",
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Pre-login logout.do flush raised: %s (ignored)", exc)

            page.goto(login_url, timeout=timeout_ms, wait_until="load")

            username = browser_config.username
            password = browser_config.password

            if username and password:
                # Wait for any username selector to become visible before filling.
                # Some login pages (SSO, custom portals) render the form via JS after
                # the load event — without this wait, fill() silently finds nothing.
                _wait_ms = min(timeout_ms, 10_000)
                for _sel in USERNAME_SELECTORS:
                    try:
                        page.wait_for_selector(_sel, timeout=_wait_ms, state="visible")
                        break
                    except Exception:
                        continue

                targets = [page]
                for frame in page.frames:
                    if frame is page.main_frame:
                        continue
                    targets.append(frame)  # type: ignore[arg-type]

                matched_any_selector = False
                submitted_login = False
                matched_locations: list[str] = []

                for index, target in enumerate(targets):
                    label = _target_label(target, index)
                    matched_user_selector = _fill_first_matching(
                        target, USERNAME_SELECTORS, username
                    )
                    matched_pass_selector = _fill_first_matching(
                        target, PASSWORD_SELECTORS, password
                    )

                    if matched_user_selector or matched_pass_selector:
                        matched_any_selector = True
                        matched_locations.append(label)
                        logger.info(
                            "Browser auth matched login fields on %s (user=%s pass=%s)",
                            label,
                            matched_user_selector,
                            matched_pass_selector,
                        )

                    matched_submit_selector = _click_first_matching(target, SUBMIT_SELECTORS)
                    if matched_submit_selector:
                        submitted_login = True
                        logger.info(
                            "Browser auth submitted login via click on %s selector=%s",
                            label,
                            matched_submit_selector,
                        )
                        break

                    if matched_pass_selector:
                        try:
                            target.locator(matched_pass_selector).press("Enter")
                            submitted_login = True
                            logger.info(
                                "Browser auth submitted login via Enter on %s selector=%s",
                                label,
                                matched_pass_selector,
                            )
                            break
                        except Exception:
                            pass

                if force_interactive and submitted_login:
                    logger.info(
                        "Interactive mode: credentials prefilled and login submitted. "
                        "Waiting for manual MFA completion."
                    )

                if not matched_any_selector:
                    logger.warning(
                        "Browser auth did not find matching username/password selectors on current page/frames. "
                        "current_url=%s frame_count=%s",
                        page.url,
                        len(targets),
                    )
                elif not submitted_login:
                    logger.warning(
                        "Browser auth filled credentials but could not submit login form. "
                        "matched_locations=%s current_url=%s",
                        ",".join(matched_locations),
                        page.url,
                    )

            logger.info(
                "Browser login waiting for manual completion (MFA/SSO). "
                "Please complete the login in the opened browser window."
            )

            # Simple wait loop: trust the browser page state.
            #
            # Login is considered complete when the page is on the instance
            # host on a non-login URL for ``STABLE_TICKS_REQUIRED``
            # consecutive 1-second polls. ``window.g_ck`` is captured if
            # available (used for X-UserToken on writes) but its absence
            # does NOT block confirmation — some ServiceNow pages populate
            # g_ck asynchronously or only inside iframes, and gating on it
            # caused the wait loop to time out at the dashboard.
            #
            # No HTTP probes, no logout-redirect counters, no limbo guards.
            # If captured cookies turn out to be UI-only (rare), the single
            # ``final_probe`` below catches it. If we miss that too, the
            # first real API call returns 401 and triggers a clean re-login.
            start = time.time()
            login_confirmed = False
            stable_instance_ticks = 0
            STABLE_TICKS_REQUIRED = 5
            current_url = ""  # v1.12.14: pre-init so the timeout-log code path
            # can read the last observed URL even if the loop never assigned
            # Cookies ServiceNow only sets AFTER a successful login.
            # ``_purge_stale_profile_cookies`` cleared everything just before
            # login.do submission, so any of these names in the persistent
            # profile during the wait loop must come from this attempt's
            # authentication. Their presence is a stronger signal than
            # page.url stability — page.url can stick on an SSO bounce or
            # SPA fragment for longer than the user takes to MFA.
            #
            # v1.12.12 tried dropping ``glide_session_store`` here on the
            # theory that it represents a half-session set during the MFA
            # challenge. v1.12.13 reverted that change: on instances that
            # never mint ``glide_user_session``, the tighter list forced
            # the slower ``stable_ticks=5`` fallback path, which captures
            # cookies a full 5 s after the post-login URL stabilizes — by
            # which point the SPA has issued enough background XHRs that
            # the server has rotated session state and our captured jar
            # no longer matches what the server now expects. Result:
            # ``final_probe`` rejects the just-captured session and the
            # user lands in a "login confirmed → immediate 401" loop.
            #
            # The born-dead pattern that motivated v1.12.12 #1 is already
            # handled by the in-grace logout path (which auto-purges
            # ``mfa_remembered`` and re-runs full MFA) combined with the
            # v1.12.12 #2 min-login-interval bypass — capturing cookies
            # earlier is fine because the recovery path catches anything
            # the server actually rejects on the first real call.
            POST_AUTH_COOKIE_MARKERS = ("glide_user_session", "glide_session_store")
            while (time.time() - start) * 1000 < wait_budget_ms:
                try:
                    if page.is_closed():
                        _safe_close_context()
                        raise ValueError(
                            "Browser was closed before login completed. "
                            "The next tool call will re-open the login window."
                        )
                    current_url = page.url
                except Exception as poll_exc:
                    error_text = str(poll_exc).lower()
                    if any(m in error_text for m in ["closed", "target", "disposed", "connection"]):
                        _safe_close_context()
                        raise ValueError(
                            "Target page, context or browser has been closed. "
                            "The next tool call will re-open the login window."
                        ) from poll_exc
                    _safe_close_context()
                    raise

                current_host = (urlparse(current_url).hostname or "").lower()

                # Headless can't satisfy an MFA/TOTP challenge — no human to
                # type the code into an invisible window. The instant the
                # server lands us on a multi-factor page, abort fast (~1s) and
                # let the wrapper open a visible window, instead of burning the
                # full 30s headless budget. Restore the cooldown clock so that
                # fallback opens immediately. Narrow MFA-only match so the
                # success path's transient login.do is never mis-detected.
                if use_headless and not _is_debug_mode() and _is_mfa_challenge_url(current_url):
                    self._last_login_started_at = prev_last_login_started_at
                    self._auth_event("login.headless.mfa_detected", url=current_url)
                    _safe_close_context()
                    raise ValueError(
                        "MFA_REQUIRED: server presented an MFA/TOTP challenge "
                        "in headless mode — falling back to interactive login."
                    )

                on_instance_non_login = current_host == instance_host and not _is_login_page_url(
                    current_url
                )
                if on_instance_non_login:
                    stable_instance_ticks += 1
                else:
                    stable_instance_ticks = 0

                # Cookie-marker signal — strong, but ONLY trustworthy after
                # the page has navigated off the MFA/login family.
                # ServiceNow sets ``glide_session_store`` /
                # ``glide_user_session`` as soon as the user reaches the MFA
                # challenge (a half-finished session). Confirming on the
                # cookie alone causes ``final_probe`` to briefly pass while
                # MFA is mid-entry; the next real request then 302s to
                # ``/logout_success.do`` once the server tears down the
                # partial session. Gate on ``on_instance_non_login``.
                try:
                    all_cookie_names = {c.get("name", "") for c in context.cookies()}
                except Exception:  # noqa: BLE001
                    all_cookie_names = set()
                has_post_auth_cookie = any(m in all_cookie_names for m in POST_AUTH_COOKIE_MARKERS)

                logger.debug(
                    "Login wait poll: url=%s on_instance_non_login=%s "
                    "stable_ticks=%s post_auth_cookie=%s cookies=%s",
                    current_url,
                    on_instance_non_login,
                    stable_instance_ticks,
                    has_post_auth_cookie,
                    ",".join(sorted(all_cookie_names))[:240] or "<none>",
                )

                confirmed_reason: Optional[str] = None
                if on_instance_non_login and has_post_auth_cookie:
                    confirmed_reason = "non_login_url+post_auth_cookie"
                elif on_instance_non_login and stable_instance_ticks >= STABLE_TICKS_REQUIRED:
                    confirmed_reason = "non_login_url_stable"

                if confirmed_reason is not None:
                    # Bounded g_ck capture retries. Without X-UserToken (g_ck),
                    # the first call against a protected-field path (e.g.
                    # sp_widget.client_script) 302s to /logout_success.do and
                    # the just-saved session becomes a permanent 401 loop —
                    # the v1.11.43 outage. v1.11.44 polls window.g_ck (and
                    # iframes) for several attempts because the token is
                    # often set by an inline script that runs a beat after
                    # the post-login navigation settles, and on some SSO
                    # bounces only inside an iframe.
                    captured_gck = ""
                    for _gck_attempt in range(GCK_CAPTURE_MAX_ATTEMPTS):
                        try:
                            evald = page.evaluate("window.g_ck")
                            if evald and isinstance(evald, str) and evald.strip():
                                captured_gck = evald.strip()
                        except Exception:  # noqa: BLE001
                            captured_gck = ""
                        if not captured_gck:
                            try:
                                frames_iter = page.frames
                            except Exception:  # noqa: BLE001
                                frames_iter = []
                            try:
                                for fr in frames_iter or []:
                                    try:
                                        fr_gck = fr.evaluate("window.g_ck")
                                    except Exception:  # noqa: BLE001
                                        continue
                                    if fr_gck and isinstance(fr_gck, str) and fr_gck.strip():
                                        captured_gck = fr_gck.strip()
                                        break
                            except TypeError:
                                pass
                        if captured_gck:
                            break
                        time.sleep(GCK_CAPTURE_INTERVAL_SECONDS)
                    if captured_gck:
                        self._browser_session_token = captured_gck
                    logger.info(
                        "Browser auth confirmed: reason=%s url=%s stable_ticks=%s "
                        "g_ck_present=%s",
                        confirmed_reason,
                        current_url,
                        stable_instance_ticks,
                        bool(self._browser_session_token),
                    )
                    self._auth_event(
                        "login.poll.confirmed",
                        reason=confirmed_reason,
                        url=current_url,
                        stable_ticks=stable_instance_ticks,
                    )
                    if not self._browser_session_token:
                        logger.warning(
                            "Browser auth confirmed without X-UserToken (g_ck) after "
                            "%d attempts. Protected-field reads (e.g. sp_widget.client_script) "
                            "may trigger 302→/logout_success.do and a permanent 401 loop. "
                            "If the very first real call 401s, delete the persistent "
                            "Chromium profile and retry login.",
                            GCK_CAPTURE_MAX_ATTEMPTS,
                        )
                        self._auth_event(
                            "login.poll.token_missing",
                            gck_attempts=GCK_CAPTURE_MAX_ATTEMPTS,
                            url=current_url,
                        )
                    login_confirmed = True
                    break

                time.sleep(1)

            if not login_confirmed:
                # v1.12.14: snapshot last polling state so the timeout log
                # carries WHY we never confirmed — last URL we saw, how many
                # stable ticks we accumulated, whether post-auth cookie was
                # ever observed. Without this the timeout was undebuggable.
                try:
                    last_cookie_names = ",".join(
                        sorted({c.get("name", "") for c in context.cookies()})
                    )[:240]
                except Exception:  # noqa: BLE001
                    last_cookie_names = "<cookies_unavailable>"
                self._auth_event(
                    "login.poll.timeout",
                    mode="headless" if use_headless else "interactive",
                    wait_budget_ms=wait_budget_ms,
                    last_url=current_url or "<never_polled>",
                    last_stable_ticks=stable_instance_ticks,
                    last_cookies=last_cookie_names or "<none>",
                )
                _safe_close_context()
                if use_headless:
                    # Restore the cooldown clock so the wrapper's visible
                    # fallback opens immediately rather than tripping
                    # LOGIN_COOLDOWN after a fruitless headless attempt.
                    self._last_login_started_at = prev_last_login_started_at
                    raise ValueError(
                        "Timed out waiting for browser login/MFA in headless mode. "
                        "If MFA prompt is required, run once with SERVICENOW_BROWSER_HEADLESS=false "
                        "to refresh session, then retry headless."
                    )
                raise ValueError(
                    "Timed out waiting for manual browser login/MFA completion. "
                    "Increase SERVICENOW_BROWSER_TIMEOUT and try again."
                )

            # Capture from full context for the same reason as in the polling loop.
            # If the polling loop already captured a token (possibly from an
            # iframe), keep it — re-running page.evaluate here can return
            # None on a transient page state and would clobber the value.
            if not (self._browser_session_token or "").strip():
                try:
                    fallback_gck = page.evaluate("window.g_ck")
                except Exception:  # noqa: BLE001
                    fallback_gck = None
                if fallback_gck and isinstance(fallback_gck, str) and fallback_gck.strip():
                    self._browser_session_token = fallback_gck.strip()
            cookies = context.cookies()
            if not cookies:
                _safe_close_context()
                raise ValueError("Browser login succeeded but no cookies were captured")

            cookie_header = self._build_instance_cookie_header(cookies, instance_url, instance_host)  # type: ignore[arg-type]
            if not cookie_header:
                _safe_close_context()
                raise ValueError("No instance-scoped secure cookies captured after login")
            self._browser_cookie_header = cookie_header
            self._browser_cookie_expires_at = time.time() + (
                browser_config.session_ttl_minutes * 60
            )
            self._browser_session_key = instance_host
            self._browser_last_validated_at = None
            self._browser_last_login_at = time.time()
            self._last_login_was_born_dead = False
            self._clear_browser_reauth_attempt()
            # Drop heavy in-flight work (Polaris Service Worker, AMB
            # WebSocket, dashboard XHRs) by navigating each open page to
            # about:blank before closing. Without this, on Polaris the
            # Service Worker and WebSocket subscription keep the OS
            # Chromium window alive long after `context.close()` returns,
            # so the user sees a stuck visible browser even though our
            # session capture is complete. about:blank has no SW, no
            # network, no JS — close becomes immediate. Cookies are not
            # affected (they live in the BrowserContext, not the page).
            if not _is_debug_mode():
                for _open_page in list(context.pages):
                    try:
                        if not _open_page.is_closed():
                            _open_page.goto(
                                "about:blank",
                                timeout=2000,
                                wait_until="commit",
                            )
                    except Exception:  # noqa: BLE001
                        pass
            # Close the persistent context BEFORE final_probe runs so the browser
            # window goes away whether the probe passes or fails. The probe is a
            # plain HTTP call against self._browser_cookie_header, so it does not
            # depend on the live Chromium context.
            _safe_close_context()

            # Final validation: avoid storing UI-only cookies that still fail API
            # auth and cause immediate 401/reopen loops.
            #
            # Light retry absorbs the server-side session-establishment race:
            # ServiceNow occasionally needs 1-3 s after login.do redirect before
            # the new session passes API auth. Without the retry, the first
            # final_probe 401 invalidates the just-captured session, the LLM
            # auto-retries the tool call, and a second browser window opens —
            # the "auto-close × 2" symptom users hit on a slower instance.
            final_probe = None
            probe_exc: Optional[Exception] = None
            for attempt in range(3):
                try:
                    final_probe = self._probe_browser_api_with_cookie(
                        self._browser_cookie_header,
                        timeout_seconds=10,
                        browser_config=browser_config,
                    )
                    probe_exc = None
                    if _response_confirms_browser_probe_session(final_probe):
                        break
                except requests.RequestException as exc:
                    probe_exc = exc
                    final_probe = None
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))  # 1.5 s, 3 s
            if probe_exc is not None and final_probe is None:
                # v1.12.13: emit the failure detail to the log too. The
                # raised ValueError reaches get_headers' except block but is
                # only re-raised, not unpacked, so LOG_FILE consumers see
                # "Browser session invalidated" with no probe diagnostic.
                logger.error(
                    "final_probe network failure: %s (no response). "
                    "Invalidating just-captured session.",
                    probe_exc,
                )
                self.invalidate_browser_session()
                raise ValueError(
                    "Browser login appeared to complete, but final API validation failed. "
                    "Not reusing this session; please retry login. "
                    f"Probe error: {probe_exc}"
                ) from probe_exc
            assert final_probe is not None  # narrow type after the loop
            if not _response_confirms_browser_probe_session(final_probe):
                # Include more detail for debugging auth failures.
                # `Location` is the decisive clue when status is 302/3xx —
                # it tells us exactly where the server thinks the session
                # belongs (e.g. /login.do means cookies aren't trusted;
                # /logout_success.do means the server already terminated us).
                # `_browser_session_token` (g_ck/X-UserToken) presence is
                # logged separately so we can tell cookie loss apart from
                # token loss when the redirect points at login.
                probe_url = final_probe.url
                probe_text = final_probe.text[:200]
                probe_location = final_probe.headers.get("Location", "")
                cookie_names = ",".join(_extract_cookie_names(self._browser_cookie_header))
                # v1.12.15: detect the "born-dead via mfa_remembered" pattern
                # right here in the login flow, not just in make_request. The
                # in-grace logout handler in make_request only fires for real
                # API calls AFTER the session is saved. final_probe runs DURING
                # the login flow, so when IT redirects through /logout_success
                # we already know the captured session is dead — and the only
                # plausible cause that doesn't depend on server state is the
                # mfa_remembered_browser cookie auto-skipping MFA. Arming
                # _needs_full_profile_purge here means the NEXT login automatically
                # drops mfa_remembered and forces a full MFA round, which mints
                # a session the server actually accepts. Without this, the user
                # is stuck in an infinite loop: login → probe rejects → invalidate
                # (but mfa_remembered preserved on disk) → next login uses the
                # same mfa_remembered → same dead session, ad infinitum. The
                # documented workaround was "delete the persistent Chromium
                # profile and retry login" — v1.12.15 makes that automatic.
                location_lower = probe_location.lower()
                looks_like_logout = (
                    "logout_success" in location_lower
                    or "/logout.do" in location_lower
                    or _response_redirected_through_logout(final_probe)
                )
                logger.error(
                    "final_probe rejected just-captured session — status=%s url=%s "
                    "location=%s x_usertoken=%s cookies=%s body[:200]=%r",
                    final_probe.status_code,
                    probe_url,
                    probe_location,
                    "set" if self._browser_session_token else "MISSING",
                    cookie_names,
                    probe_text,
                )
                self._auth_event(
                    "login.probe.failed",
                    captured_cookies=cookie_names or "<none>",
                    looks_like_logout=looks_like_logout,
                    **{f"resp_{k}": v for k, v in _format_response_diagnostic(final_probe).items()},
                )
                # v1.12.17: removed the auto-arm-full-purge introduced in
                # v1.12.15. Field logs proved the assumption wrong — even
                # after dropping mfa_remembered and forcing full MFA, the
                # next session was equally born-dead. The auto-arm just
                # produced an extra MFA prompt per retry for no benefit.
                # See request.born_dead handler above for the v1.12.17
                # recovery model: invalidate, surface the failure, let the
                # user manually retry under the normal rate-limit.
                self.invalidate_browser_session()
                raise ValueError(
                    f"Browser login completed, but API auth is still unauthorized. "
                    f"Status: {final_probe.status_code}, URL: {probe_url}, "
                    f"Location: {probe_location}, "
                    f"X-UserToken: {'set' if self._browser_session_token else 'MISSING'}, "
                    f"cookies={cookie_names}, Response: {probe_text}"
                )
            self._browser_last_validated_at = time.time()
            self._save_session_to_disk()
            if final_probe.status_code == 403:
                logger.info(
                    "Browser login completed and session is authenticated, but probe path is unauthorized: "
                    "status=%s probe_path=%s",
                    final_probe.status_code,
                    browser_config.probe_path,
                )
            # Idempotent second close — the earlier call (before final_probe)
            # already handles the failure paths; this one is a no-op safety
            # net for the success path.
            _safe_close_context()
            cookie_names_str = ",".join(_extract_cookie_names(self._browser_cookie_header))
            logger.info(
                "Browser session stored: mode=%s session_key=%s cookie_count=%s "
                "cookie_names=%s ttl_minutes=%s",
                "headless" if use_headless else "interactive",
                self._browser_session_key,
                len(_extract_cookie_names(self._browser_cookie_header)),
                cookie_names_str,
                browser_config.session_ttl_minutes,
            )
            self._auth_event(
                "login.stored",
                mode="headless" if use_headless else "interactive",
                cookie_names=cookie_names_str,
                ttl_minutes=browser_config.session_ttl_minutes,
            )

    def invalidate_browser_session(self, *, full_purge: bool = False):
        """Invalidate the current browser session, forcing re-authentication on next request.

        Only removes the disk cache file if it still contains OUR cookies.
        Another terminal may have already written a fresher session to disk,
        and we must not delete that.

        ``full_purge=True`` (v1.11.46) signals the next profile purge to
        also drop ``glide_mfa_remembered_browser``. Use it from self-heal
        paths (server-issued 302→logout_success.do, repeated probe 302s)
        where preserving the MFA-remembered cookie would skip MFA on the
        next login and end up minting a session without the ``factor``
        cookie, which strict instances reject again — the infinite-login
        loop the user kept hitting on the test instance.
        """
        my_cookie = self._browser_cookie_header
        had_cookies = bool(my_cookie)
        logger.info(
            "Browser session invalidated (in-memory)%s",
            " [full_purge: mfa_remembered will also be dropped]" if full_purge else "",
        )
        self._auth_event(
            "session.invalidated",
            full_purge=full_purge,
            had_cookies=had_cookies,
        )
        self._browser_cookie_header = None
        self._browser_cookie_expires_at = None
        self._browser_last_validated_at = None
        self._browser_session_token = None
        # The next browser login must start from a clean cookie jar. The
        # persistent Chromium profile still holds session cookies bound to
        # the now-invalidated server session; without purging, ServiceNow
        # treats the next ``login.do`` submission as a logout flow and 302s
        # every probe to ``/logout_success.do``. v1.11.14 added
        # ``glide_mfa_remembered_browser`` to the purge list — keeping it
        # was the root cause of the persistent logout-redirect loop. See
        # _purge_stale_profile_cookies for full rationale.
        self._needs_profile_cookie_purge = True
        if full_purge:
            self._needs_full_profile_purge = True
        if os.path.exists(self._session_cache_path):
            try:
                with open(self._session_cache_path, "r") as f:
                    disk_data = json.load(f)
                disk_cookie = disk_data.get("cookie_header")
                if disk_cookie and disk_cookie != my_cookie:
                    logger.info(
                        "Disk cache has a different session (likely from another terminal) — "
                        "keeping disk cache intact."
                    )
                    return
            except Exception:
                pass  # If we can't read, safe to remove
            try:
                os.remove(self._session_cache_path)
                logger.info("Session cache file removed: %s", self._session_cache_path)
            except Exception as exc:
                logger.warning("Failed to remove session cache file: %s", exc)

    def _enforce_self_heal_circuit(self, method: str, url: str) -> None:
        """Self-heal circuit breaker guard (extracted from make_request).

        A cohesive prologue: either returns (let the request proceed) or
        raises SELF_HEAL_CIRCUIT_OPEN. Single entry / single exit-or-raise —
        no state is threaded back to the caller, so lifting it out is
        behavior-preserving. Pinned by test_browser_grace_period.py."""
        # v1.12.0: fail fast when the self-heal circuit is open. Without
        # this guard, every retry from source_tools / sn_api parallel page
        # fetch / etc. would still try to send (and fail), pumping
        # ServiceNow with 100+ 401 calls in a few seconds and risking the
        # user being flagged or banned. The guard makes all calls return
        # instantly until a successful response resets the counter or the
        # user restarts MCP.
        #
        # v1.12.1: BEFORE refusing, throttled escape probe to
        # sys_user_preference. If the session has actually recovered
        # (transient instance policy hiccup cleared, idle timer reset by
        # another path, etc.), reset the counter and let the call through.
        # Throttled by _CIRCUIT_ESCAPE_PROBE_INTERVAL_SECONDS — when the
        # server genuinely is dead the throttle still leaves long stretches
        # of cheap refusals between probes, so we don't hammer.
        if (
            self.config.type == AuthType.BROWSER
            and self._consecutive_self_heal_count >= _SELF_HEAL_CIRCUIT_THRESHOLD
        ):
            now = time.time()
            probed_just_now = False
            if (
                self._browser_cookie_header
                and self.config.browser is not None
                and (now - self._browser_circuit_last_escape_at)
                >= _CIRCUIT_ESCAPE_PROBE_INTERVAL_SECONDS
            ):
                self._browser_circuit_last_escape_at = now
                probed_just_now = True
                try:
                    escape_probe = self._probe_browser_api_with_cookie(
                        self._browser_cookie_header,
                        timeout_seconds=10,
                        browser_config=self.config.browser,
                    )
                    if _response_confirms_browser_probe_session(escape_probe):
                        logger.info(
                            "Self-heal circuit AUTO-RESET: escape probe to "
                            "sys_user_preference returned 200 (was "
                            "consecutive=%d). Letting %s %s proceed.",
                            self._consecutive_self_heal_count,
                            method.upper(),
                            (urlparse(url).hostname or "").lower(),
                        )
                        self._auth_event(
                            "request.circuit.escaped",
                            method=method.upper(),
                            target_host=(urlparse(url).hostname or "").lower(),
                        )
                        self._mark_browser_session_recently_valid()
                        # Fall through to the normal request path.
                    else:
                        logger.warning(
                            "Self-heal circuit escape probe rejected by server "
                            "(status=%s). Continuing to refuse calls; next "
                            "probe in %.0fs.",
                            escape_probe.status_code,
                            _CIRCUIT_ESCAPE_PROBE_INTERVAL_SECONDS,
                        )
                        self._auth_event(
                            "request.circuit.escape_rejected",
                            next_probe_in_s=_CIRCUIT_ESCAPE_PROBE_INTERVAL_SECONDS,
                            **{
                                f"resp_{k}": v
                                for k, v in _format_response_diagnostic(escape_probe).items()
                            },
                        )
                except requests.RequestException as exc:
                    logger.warning(
                        "Self-heal circuit escape probe failed: %s. " "Continuing to refuse calls.",
                        exc,
                    )
                    self._auth_event(
                        "request.circuit.escape_network_error",
                        error=str(exc)[:120],
                    )

            # If we did not escape, refuse.
            if self._consecutive_self_heal_count >= _SELF_HEAL_CIRCUIT_THRESHOLD:
                self._auth_event(
                    "request.circuit.refused",
                    method=method.upper(),
                    target_host=(urlparse(url).hostname or "").lower(),
                    probed_just_now=probed_just_now,
                    has_cookies=bool(self._browser_cookie_header),
                )
                raise requests.HTTPError(
                    "SELF_HEAL_CIRCUIT_OPEN: %d consecutive auth failures. Refusing "
                    "to send this request. The server is rejecting every session — "
                    "restart MCP or wait for the instance policy to clear. "
                    "(Counter resets on the first successful response or escape "
                    "probe; %s)"
                    % (
                        self._consecutive_self_heal_count,
                        (
                            "escape probe ran this call"
                            if probed_just_now
                            else "next probe throttled"
                        ),
                    )
                )

    def make_request(
        self,
        method: str,
        url: str,
        max_retries: int = 1,
        **kwargs,
    ) -> requests.Response:
        """
        Make an authenticated HTTP request with automatic retry on 401
        and transient network errors (ConnectionError, Timeout).

        For Browser Auth, 401 responses trigger session invalidation and
        re-authentication before retry.

        Args:
            method: HTTP method (GET, POST, PATCH, PUT, DELETE).
            url: Request URL.
            max_retries: Maximum number of retries on 401 (default: 1).
            **kwargs: Additional arguments passed to requests.request().

        Returns:
            requests.Response: The HTTP response.

        Raises:
            requests.RequestException: If the request fails after all retries.
        """
        # v1.12.0/v1.12.1: self-heal circuit breaker — fail fast (with a
        # throttled escape probe) when the server rejects every session.
        # Raises SELF_HEAL_CIRCUIT_OPEN if the circuit is open and the
        # escape probe does not recover the session.
        self._enforce_self_heal_circuit(method, url)

        # Get auth headers
        headers = kwargs.pop("headers", {})
        headers.update(self.get_headers())
        # Snapshot the Cookie names BEFORE moving cookies to kwargs, so the
        # request-start log reflects what is actually sent. Pre-fix, we
        # logged after popping the Cookie header, which always read 0.
        cookie_names = _extract_cookie_names(headers.get("Cookie"))
        if self.config.type == AuthType.BROWSER:
            cookie_map = _cookie_header_to_dict(headers.get("Cookie"))
            if cookie_map:
                kwargs["cookies"] = cookie_map
                headers.pop("Cookie", None)
            elif "cookies" in kwargs:
                kwargs.pop("cookies", None)
        kwargs["headers"] = headers
        request_timeout = kwargs.get("timeout")
        request_host = (urlparse(url).hostname or "").lower()
        method_upper = method.upper()
        start = time.monotonic()
        # v1.11.45: include X-UserToken + Referer status so the request
        # start log can be diffed against the probe log when chasing
        # 302→/logout_success.do failures. Pre-v1.11.45 only the probe
        # logged these, leaving real-call header state unverifiable.
        outgoing_user_token = (
            "set"
            if headers.get("X-UserToken")
            else "MISSING" if self.config.type == AuthType.BROWSER else "n/a"
        )
        outgoing_referer = (
            "set"
            if headers.get("Referer")
            else "MISSING" if self.config.type == AuthType.BROWSER else "n/a"
        )
        logger.info(
            "ServiceNow request start: method=%s host=%s timeout=%s auth_type=%s "
            "cookie_count=%s x_usertoken=%s referer=%s",
            method_upper,
            request_host,
            request_timeout,
            self.config.type.value,
            len(cookie_names),
            outgoing_user_token,
            outgoing_referer,
        )
        if cookie_names and logger.isEnabledFor(logging.DEBUG):
            logger.debug("ServiceNow request cookies: %s", ",".join(cookie_names))
        # v1.12.16: emit a single auth_event=request.sent line that fully
        # describes the request shape — cookie name=valuePrefix pairs, token
        # prefix, UA prefix, the URL. Crucial for diagnosing "captured one
        # session, sent another" failures where the symptom is logout-302 on
        # a request that looks superficially correct.
        if self.config.type == AuthType.BROWSER:
            request_cookies_dict = kwargs.get("cookies") if "cookies" in kwargs else None
            if request_cookies_dict:
                cookies_sent_log = _format_request_cookies_dict_for_log(request_cookies_dict)
            else:
                cookies_sent_log = _format_cookie_values_for_log(headers.get("Cookie"))
            self._auth_event(
                "request.sent",
                method=method_upper,
                target_host=request_host,
                url=url,
                cookies_sent=cookies_sent_log,
                x_usertoken_sent=_redact_value(
                    headers.get("X-UserToken"), _LOG_TOKEN_VALUE_PREFIX_LEN
                ),
                user_agent_sent=_redact_value(headers.get("User-Agent"), 32),
            )

        # Retry on transient network errors (ConnectionError, Timeout) and
        # transient upstream gateway errors (502/503/504) before giving up.
        # This prevents brief network blips and ServiceNow load-balancer hiccups
        # from being surfaced as "MCP disconnected" to the caller.
        max_transient_retries = 2
        # Status codes that are almost always upstream-infrastructure transient.
        # 500 is excluded because it more often indicates a real server bug
        # whose body should be returned to the caller for diagnosis.
        transient_status_codes = {502, 503, 504}
        last_exc: Optional[Exception] = None
        response: Optional[requests.Response] = None

        for attempt in range(1 + max_transient_retries):
            try:
                response = self._http_session.request(method, url, **kwargs)
                last_exc = None
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                response = None
                elapsed_ms = int((time.monotonic() - start) * 1000)
                if attempt < max_transient_retries:
                    wait = 1.0 * (attempt + 1)  # 1s, 2s backoff
                    logger.warning(
                        "Transient network error (attempt %s/%s): %s. "
                        "Retrying in %.1fs... method=%s host=%s elapsed_ms=%s",
                        attempt + 1,
                        1 + max_transient_retries,
                        exc,
                        wait,
                        method_upper,
                        request_host,
                        elapsed_ms,
                    )
                    time.sleep(wait)
                    continue
                logger.error(
                    "Network error persisted after %s attempts: %s method=%s host=%s elapsed_ms=%s",
                    1 + max_transient_retries,
                    exc,
                    method_upper,
                    request_host,
                    elapsed_ms,
                )
                break

            if response.status_code in transient_status_codes and attempt < max_transient_retries:
                wait = 1.0 * (attempt + 1)  # 1s, 2s backoff (matches network-error path)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.warning(
                    "Transient upstream %s (attempt %s/%s). Retrying in %.1fs... "
                    "method=%s host=%s elapsed_ms=%s",
                    response.status_code,
                    attempt + 1,
                    1 + max_transient_retries,
                    wait,
                    method_upper,
                    request_host,
                    elapsed_ms,
                )
                time.sleep(wait)
                continue
            break

        if response is None:
            # All attempts failed with transient errors — raise the last one.
            raise last_exc  # type: ignore[misc]

        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "ServiceNow request end: method=%s host=%s status=%s elapsed_ms=%s",
            method_upper,
            request_host,
            response.status_code,
            elapsed_ms,
        )

        # v1.12.18: F5 BIG-IP backend re-routing absorption.
        #
        # When a logout-redirect response carries a Set-Cookie with a
        # BIGipServerpool_<host>=<value> that differs from the one we just
        # sent, F5 is telling us "you reached the wrong backend; switch
        # to this one". The captured session lives on backend B but our
        # cookie stuck us to backend A — fixable client-side by swapping
        # the cookie value and re-sending the same request to F5, which
        # will then route to backend B.
        #
        # Bounded to ONE retry per make_request call via the local flag,
        # so a misbehaving server that keeps shifting the hint can't loop
        # us. If the retry still produces a logout-redirect the original
        # born-dead handling below runs against the updated response.
        if (
            self.config.type == AuthType.BROWSER
            and self._browser_cookie_header
            and _response_redirected_through_logout(response)
        ):
            new_bigip_prefix = self._absorb_response_bigip_rotation(response)
            if new_bigip_prefix:
                logger.warning(
                    "BIG-IP backend redirect detected: server hinted "
                    "BIGipServerpool=%s..., overriding our cookie and "
                    "retrying %s %s once before treating as session death.",
                    new_bigip_prefix,
                    method_upper,
                    request_host,
                )
                self._auth_event(
                    "request.bigip_absorbed",
                    method=method_upper,
                    target_host=request_host,
                    new_bigip_prefix=new_bigip_prefix,
                )
                # Re-prime kwargs with the updated cookie set. Browser auth
                # uses kwargs["cookies"] (dict form); other auth types fall
                # back to the Cookie header on the headers dict.
                if "cookies" in kwargs:
                    kwargs["cookies"] = _cookie_header_to_dict(self._browser_cookie_header)
                else:
                    kwargs.setdefault("headers", {})["Cookie"] = self._browser_cookie_header
                try:
                    response = self._http_session.request(method, url, **kwargs)
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "ServiceNow request end (bigip-retry): method=%s host=%s "
                        "status=%s elapsed_ms=%s",
                        method_upper,
                        request_host,
                        response.status_code,
                        elapsed_ms,
                    )
                    self._auth_event(
                        "request.bigip_retry",
                        method=method_upper,
                        target_host=request_host,
                        **{
                            f"resp_{k}": v for k, v in _format_response_diagnostic(response).items()
                        },
                    )
                except (requests.ConnectionError, requests.Timeout) as exc:
                    logger.error(
                        "BIG-IP retry network error — falling through to "
                        "born-dead handling with original response: %s",
                        exc,
                    )

        # Self-heal: detect 302→/logout_success.do that requests followed
        # silently. The v1.11.43 outage signature was a doomed call
        # (protected-field read without a valid X-UserToken) reaching the
        # logout page — request returns 200 + logout HTML, which would
        # otherwise be misclassified as success here OR trapped in the
        # grace-period 401 retry loop on the very next call. Convert it
        # into the 401 recovery path so re-auth runs immediately.
        if (
            self.config.type == AuthType.BROWSER
            and self._browser_cookie_header
            and _response_redirected_through_logout(response)
        ):
            # v1.12.1: BEFORE touching the self-heal counter, distinguish
            # the two failure modes that both surface as 302→logout_success:
            #
            #   (a) Session is alive, target table denies access (ACL or
            #       scope policy on a custom app). The session is fine;
            #       only THIS call is doomed. Incrementing the counter or
            #       invalidating the session here was the v1.11.x bug
            #       that produced "every tool call fails after MFA" reports.
            #
            #   (b) Session truly died server-side (idle timeout, instance
            #       policy revoked, MFA-cookie mismatch). Every call dies
            #       the same way; we want self-heal + circuit breaker.
            #
            # A single same-session probe to /sys_user_preference cleanly
            # separates the two: probe returns 200 → (a), counter stays
            # at 0 and we raise TABLE_BLOCKED; probe also redirects/fails
            # → (b), fall through to the existing grace + circuit logic.
            session_alive_after_failure = False
            if self.config.browser is not None:
                try:
                    diag_probe = self._probe_browser_api_with_cookie(
                        self._browser_cookie_header,
                        timeout_seconds=10,
                        browser_config=self.config.browser,
                    )
                    session_alive_after_failure = _response_confirms_browser_probe_session(
                        diag_probe
                    )
                except requests.RequestException as exc:
                    logger.warning(
                        "Self-heal diagnostic probe failed: %s. " "Treating as session death.",
                        exc,
                    )

            if session_alive_after_failure:
                logger.warning(
                    "Self-heal diagnostic: %s %s redirected through "
                    "/logout_success.do, but a same-session probe to "
                    "sys_user_preference returned 200. Classifying as a "
                    "TABLE-LEVEL block (ACL/scope policy on the target), "
                    "not session death. Self-heal counter NOT incremented; "
                    "other tools remain callable.",
                    method_upper,
                    url,
                )
                # Refresh the validity timestamp so the next call doesn't
                # pay another validation probe.
                self._mark_browser_session_recently_valid()
                raise requests.HTTPError(
                    "TABLE_BLOCKED: ServiceNow redirected this call to "
                    "/logout_success.do, but a same-session probe to "
                    "sys_user_preference returned 200. The session is "
                    "alive — this is a table-level ACL or scope-policy "
                    f"block on the target ({url}). Check read ACLs / "
                    "scope rules for that table; other tools remain "
                    "callable on the current session.",
                    response=response,
                )

            # v1.11.47: respect the post-login grace period.
            #
            # If the 302→/logout_success.do happens within seconds of a
            # successful login (probe was 200, session saved), this is the
            # "fresh session born dead" pattern. Re-authenticating produces
            # another fresh session that hits the same server-side policy
            # and dies the same way — but every re-auth means another MFA
            # prompt. The user ends up MFAing on every tool call. Raise a
            # clear error WITHOUT invalidating: caller sees the failure,
            # session stays in memory for the user to retry/investigate,
            # no MFA loop. Outside grace (server's idle timeout fired), do
            # the standard self-heal: invalidate + re-auth on next call.
            self._consecutive_self_heal_count += 1
            self._auth_event(
                "request.logout_detected",
                method=method_upper,
                url=url,
                consecutive=self._consecutive_self_heal_count,
                threshold=_SELF_HEAL_CIRCUIT_THRESHOLD,
                **{f"resp_{k}": v for k, v in _format_response_diagnostic(response).items()},
            )
            if self._consecutive_self_heal_count >= _SELF_HEAL_CIRCUIT_THRESHOLD:
                logger.error(
                    "Self-heal CIRCUIT OPEN: %s %s — consecutive=%d ≥ threshold(%d). "
                    "Refusing further calls.",
                    method_upper,
                    url,
                    self._consecutive_self_heal_count,
                    _SELF_HEAL_CIRCUIT_THRESHOLD,
                )
                self._auth_event(
                    "request.circuit.tripped",
                    method=method_upper,
                    url=url,
                )
                raise requests.HTTPError(
                    "SELF_HEAL_CIRCUIT_OPEN: %d consecutive auth failures. "
                    "Server rejects every session. Restart MCP or wait for the "
                    "instance policy to clear." % self._consecutive_self_heal_count,
                    response=response,
                )
            in_grace = (
                self._browser_last_login_at is not None
                and (time.time() - self._browser_last_login_at)
                < self._browser_post_login_grace_seconds
            )
            if in_grace:
                # v1.12.2: reaching this branch means the auto-relogin just
                # finished, the actual call still got 302→logout, AND the
                # v1.12.1 diagnostic probe to sys_user_preference also
                # failed (otherwise we'd have raised TABLE_BLOCKED above).
                #
                # In other words: the brand-new session is "born dead" —
                # the server accepts our login but kills every subsequent
                # API call. The single most common cause is the
                # ``glide_mfa_remembered_browser`` cookie producing an
                # MFA-skipped session whose factor-cookie shape is
                # rejected by the server's session policy. The session is
                # "logged in" but lacks the post-MFA marker the server
                # expects, so every real API call is routed to
                # /logout_success.do.
                #
                # Old behaviour (v1.11.47–v1.12.1): raise a generic
                # SESSION_TORN_DOWN_FRESH error and tell the user to
                # restart MCP. Painful — user has to manually intervene
                # for what we can already diagnose precisely.
                #
                # New behaviour: trip the full-purge flag so the next
                # _login_with_browser drops mfa_remembered too, then
                # convert this response to a 401 so the existing 401
                # retry path below re-auths with full MFA. End result:
                # user gets ONE visible MFA prompt and the call succeeds.
                # No counter increment (this isn't repeated session
                # rejection — it's a single mfa_remembered glitch).
                # v1.12.17: removed the auto-recovery cascade that v1.12.2 +
                # v1.12.12 + v1.12.15 had built up:
                #   - _needs_full_profile_purge=True (would force MFA next time)
                #   - _last_login_was_born_dead=True (would bypass 60s rate-limit)
                #   - _consecutive_self_heal_count-=1 (would un-punish, keeping
                #     circuit closed indefinitely)
                # Combined, those auto-armed an immediate full-MFA retry. When
                # the server keeps rejecting (e.g. ServiceNow single-session
                # policy and a sibling Claude/MCP for the same user kills this
                # session, or an F5 BIG-IP backend-affinity mismatch), the
                # retry produced ANOTHER born-dead and re-armed itself — the
                # MFA-fatigue loop users hit on 2026-05-13 where every retry
                # demanded another MFA challenge.
                #
                # New behaviour: just invalidate and let the normal 401-retry
                # path run. The retry will hit the 60s min-login-interval
                # gate (un-bypassed) and refuse with a clear cooldown error,
                # so the user manually retries 1 min later. Meanwhile the
                # disk session cache is left intact if a sibling MCP wrote
                # a fresher session (invalidate_browser_session already
                # respects that), so the next manual retry's _reload_session_
                # from_disk picks up the sibling's working session.
                #
                # Keep the counter decrement so isolated born-deads don't
                # trip the circuit and trap the user; the rate-limit alone
                # is enough back-pressure.
                logger.warning(
                    "Session torn down by server within %.0fs of login "
                    "(%s %s) → session born dead. Invalidating. Likely "
                    "causes: (a) another Claude/MCP terminal for the same "
                    "user logged in and killed this session under "
                    "ServiceNow's single-session policy, (b) F5 BIG-IP "
                    "routed this client to a backend that does not host "
                    "the freshly-minted session, (c) instance abuse "
                    "detection. Retry after the rate-limit cooldown; if "
                    "repeated, close other MCP/login sessions on this "
                    "instance.",
                    self._browser_post_login_grace_seconds,
                    method_upper,
                    url,
                )
                self._auth_event(
                    "request.born_dead",
                    method=method_upper,
                    url=url,
                    **{f"resp_{k}": v for k, v in _format_response_diagnostic(response).items()},
                )
                self._consecutive_self_heal_count -= 1  # isolated born-dead — don't trip circuit
                self._browser_last_login_at = None
                self.invalidate_browser_session(full_purge=False)
                response.status_code = 401
                # Fall through to the 401 retry block below. Without the
                # bypass flags, get_headers() → _login_with_browser_sync's
                # min-login-interval gate fires after the first attempt
                # and raises LOGIN_COOLDOWN, surfacing the wait to the
                # user instead of triggering another silent MFA round.
            logger.warning(
                "Self-heal: response %s %s passed through /logout_success.do — "
                "session torn down server-side (outside grace). consecutive=%d. "
                "mfa_remembered preserved (v1.12.0 — no auto full_purge).",
                method_upper,
                url,
                self._consecutive_self_heal_count,
            )
            self._browser_last_login_at = None
            self.invalidate_browser_session(full_purge=False)
            response.status_code = 401

        if (
            self.config.type == AuthType.BROWSER
            and self._browser_cookie_header
            and _response_indicates_authenticated_session(response)
        ):
            self._mark_browser_session_recently_valid()
            self._absorb_response_token_rotation(response)

        # Handle 401 Unauthorized - retry with fresh session for Browser Auth
        if response.status_code == 401 and max_retries > 0:
            # Diagnostic: dump the response body + auth-relevant response headers
            # so the user can see WHY the server rejected the request without
            # reproducing the issue. Truncated to keep logs readable.
            try:
                _diag_body = (response.text or "")[:300].replace("\n", " ")
            except Exception:
                _diag_body = "<body unreadable>"
            _diag_token_rotated = response.headers.get("X-UserToken")
            logger.info(
                "401 diagnostic: method=%s host=%s url=%s ct=%s body=%s rotated_token_present=%s",
                method_upper,
                request_host,
                url,
                response.headers.get("Content-Type", ""),
                _diag_body,
                bool(_diag_token_rotated),
            )
            if self.config.type == AuthType.BROWSER:
                # Server-rotated token recovery — try this BEFORE the more expensive
                # paths below. If the server rejected our X-UserToken but pushed a
                # fresh value via the 401 response headers, swap it in and retry once.
                # This is the cheapest fix for the "logged in but immediately 401"
                # symptom caused by g_ck rotation between capture and first call.
                if _diag_token_rotated and _diag_token_rotated != self._browser_session_token:
                    logger.info("401 carried a rotated X-UserToken — swapping it in and retrying.")
                    self._browser_session_token = _diag_token_rotated.strip()
                    try:
                        self._save_session_to_disk()
                    except Exception:
                        pass
                    headers = kwargs.get("headers", {})
                    headers["X-UserToken"] = self._browser_session_token
                    kwargs["headers"] = headers
                    rotated_retry = self._http_session.request(method, url, **kwargs)
                    if rotated_retry.status_code != 401:
                        self._mark_browser_session_recently_valid()
                        self._absorb_response_token_rotation(rotated_retry)
                        return rotated_retry
                    # Fall through to the standard 401 handling below.

                # Within post-login grace period: the session was JUST created.
                # A 401 right after login is likely a transient timing issue (cookie propagation).
                # Retry once with existing cookies instead of invalidating and re-opening browser.
                if (
                    self._browser_last_login_at is not None
                    and (time.time() - self._browser_last_login_at)
                    < self._browser_post_login_grace_seconds
                ):
                    logger.info(
                        "Received 401 within post-login grace period — retrying with existing session "
                        "instead of re-authenticating."
                    )
                    time.sleep(2)  # brief wait for cookie propagation
                    retry_response = self._http_session.request(method, url, **kwargs)
                    if retry_response.status_code != 401:
                        return retry_response
                    # Second 401 inside grace period — distinguish ACL vs stale token by body.
                    # Previously this was unconditionally treated as ACL, which caused infinite
                    # 401 loops when the cause was actually a stale X-UserToken / cookie.
                    if _response_indicates_acl_block(retry_response):
                        raise requests.HTTPError(
                            "ACL_BLOCKED: 401 with explicit ACL/permission body markers "
                            "(not a session expiry). Re-authentication will not help — "
                            "verify the user's role/ACL on the target table or record.",
                            response=retry_response,
                        )
                    # Try a one-shot disk reload — another process may have refreshed the session.
                    if self._reload_session_from_disk():
                        logger.info(
                            "Grace-period 401 recovered via disk-reloaded session "
                            "(another process refreshed it)."
                        )
                        fresh_headers = self.get_headers()
                        headers = kwargs.get("headers", {})
                        headers.update(fresh_headers)
                        cookie_map = _cookie_header_to_dict(headers.get("Cookie"))
                        if cookie_map:
                            kwargs["cookies"] = cookie_map
                            headers.pop("Cookie", None)
                        kwargs["headers"] = headers
                        reloaded_response = self._http_session.request(method, url, **kwargs)
                        if reloaded_response.status_code != 401:
                            self._mark_browser_session_recently_valid()
                            self._absorb_response_token_rotation(reloaded_response)
                            return reloaded_response
                        if _response_indicates_acl_block(reloaded_response):
                            raise requests.HTTPError(
                                "ACL_BLOCKED: disk-reloaded session still got 401 with ACL "
                                "markers. Verify user permissions on the target.",
                                response=reloaded_response,
                            )
                    # The session was JUST created and final_probe passed, yet the
                    # very next real call still 401s. v1.12.0: increment the
                    # circuit breaker counter on plain 401s that we could not
                    # recover from in-grace. test-environment hardening was
                    # firing only 401s (not 302→logout), so the previous
                    # counter never reached the threshold and source_tools
                    # kept hammering the server with retries — exactly the
                    # "왜 비인증 호출이 이렇게 많아" symptom. Now any 401 that
                    # makes it to this raise contributes to the breaker.
                    self._consecutive_self_heal_count += 1
                    consecutive = self._consecutive_self_heal_count
                    # State-based guidance instead of an unconditional speculative
                    # cause (the old "Likely instance-policy/ACL/X-UserToken
                    # rotation" string led the LLM to confidently report a cause
                    # that was usually just "session not authenticated yet").
                    if consecutive <= 1:
                        guidance = (
                            "The browser session is not accepted by ServiceNow's REST API. "
                            "Complete an interactive login (MFA) for this instance, then retry."
                        )
                    else:
                        guidance = (
                            f"Still rejected after {consecutive} re-auth attempts — a fresh "
                            "login alone will not fix it. Likely the account's REST access or "
                            "an instance policy on this instance (e.g. post-clone hardening / "
                            "X-UserToken handling). Verify by calling the REST API directly in a "
                            "logged-in browser."
                        )
                    raise requests.HTTPError(
                        "FRESH_SESSION_REJECTED: a freshly established browser session "
                        f"(<{self._browser_post_login_grace_seconds}s old) was rejected by "
                        f"ServiceNow with 401 (consecutive={consecutive}). " + guidance,
                        response=retry_response,
                    )

                # If the 401 came back with a JSON body and clear ACL markers, it is an ACL
                # restriction — re-auth won't help. Raise so callers stop retrying instead of
                # silently returning 401 (which the LLM would interpret as session expiry).
                if _response_indicates_acl_block(response):
                    raise requests.HTTPError(
                        "ACL_BLOCKED: 401 with ACL/permission body markers (not session "
                        "expiry). Re-authentication will not help — verify the user's role/ACL "
                        "on the target table or record.",
                        response=response,
                    )

                # In browser mode, 401 almost always means the session/X-UserToken is dead.
                # First try reloading from disk — another terminal may have refreshed the session.
                if self._reload_session_from_disk():
                    logger.info(
                        "Received 401 but reloaded fresher session from disk (another terminal). "
                        "Retrying with reloaded session..."
                    )
                    fresh_headers = self.get_headers()
                    headers = kwargs.get("headers", {})
                    headers.update(fresh_headers)
                    cookie_map = _cookie_header_to_dict(headers.get("Cookie"))
                    if cookie_map:
                        kwargs["cookies"] = cookie_map
                        headers.pop("Cookie", None)
                    kwargs["headers"] = headers
                    retry_response = self._http_session.request(method, url, **kwargs)
                    if retry_response.status_code != 401:
                        self._mark_browser_session_recently_valid()
                        self._absorb_response_token_rotation(retry_response)
                        return retry_response
                    logger.info("Disk-reloaded session also got 401. Proceeding to full re-auth.")

                # Before re-auth: check if another process is already logging in.
                # If so, wait for it and reload from disk instead of opening a second browser.
                if not self._acquire_login_lock():
                    logger.info(
                        "Another process is already re-authenticating. "
                        "Waiting for it to finish..."
                    )
                    waited = self._wait_for_other_login(timeout=120)
                    if (
                        waited
                        and self._browser_cookie_header
                        and not self._is_browser_session_expired()
                    ):
                        logger.info("Picked up session from other process after wait.")
                        fresh_headers = self.get_headers()
                        headers = kwargs.get("headers", {})
                        headers.update(fresh_headers)
                        cookie_map = _cookie_header_to_dict(headers.get("Cookie"))
                        if cookie_map:
                            kwargs["cookies"] = cookie_map
                            headers.pop("Cookie", None)
                        kwargs["headers"] = headers
                        retry_response = self._http_session.request(method, url, **kwargs)
                        if retry_response.status_code != 401:
                            self._mark_browser_session_recently_valid()
                            return retry_response
                    # Fall through to own re-auth if other process didn't save a valid session
                else:
                    self._release_login_lock()

                logger.warning(
                    "Received 401 Unauthorized in browser mode. "
                    "Attempting session restore before full re-auth..."
                )
                # Invalidate current in-memory session (disk cache only deleted if it's our cookies)
                self.invalidate_browser_session()

                # Get fresh headers — get_headers() will try restore first, then interactive
                try:
                    fresh_headers = self.get_headers()
                except Exception as exc:
                    logger.error("Browser re-authentication failed: %s", exc)
                    # Raise so callers get a clear "login failed" error instead of a
                    # silent 401 that would make the LLM think "session still expired".
                    raise requests.HTTPError(
                        f"Browser re-authentication failed — {exc}. "
                        "Complete login in the browser window then retry.",
                        response=response,
                    ) from exc

                # Update headers and cookies for the retry
                headers = kwargs.get("headers", {})
                headers.update(fresh_headers)
                cookie_map = _cookie_header_to_dict(headers.get("Cookie"))
                if cookie_map:
                    kwargs["cookies"] = cookie_map
                    headers.pop("Cookie", None)
                kwargs["headers"] = headers

                # Retry request with decremented retries
                retry_start = time.monotonic()
                response = self._http_session.request(method, url, **kwargs)
                retry_elapsed_ms = int((time.monotonic() - retry_start) * 1000)
                logger.info(
                    "ServiceNow request retry end: method=%s host=%s status=%s elapsed_ms=%s",
                    method_upper,
                    request_host,
                    response.status_code,
                    retry_elapsed_ms,
                )
                if self._browser_cookie_header and _response_indicates_authenticated_session(
                    response
                ):
                    self._mark_browser_session_recently_valid()
                elif response.status_code == 401:
                    # Re-auth completed (browser opened, new cookies captured) but the very
                    # next call still returns 401. Raise so the caller stops retrying — looping
                    # would just open another browser window for the same broken state.
                    if _response_indicates_acl_block(response):
                        raise requests.HTTPError(
                            "ACL_BLOCKED: 401 persists after fresh login with ACL markers. "
                            "Verify the user's role/ACL on the target.",
                            response=response,
                        )
                    raise requests.HTTPError(
                        "SESSION_REAUTH_FAILED: 401 persists immediately after a fresh "
                        "browser login. The captured session is rejected by the server. "
                        "Stop retrying — verify the account, MFA flow, and instance URL.",
                        response=response,
                    )
            else:
                logger.warning(
                    f"Received 401 Unauthorized with {self.config.type.value} auth. "
                    "Check your credentials."
                )

        # Clear session cookie jar to prevent stale cookies leaking across
        # requests.  Browser auth manages cookies explicitly via headers.
        self._http_session.cookies.clear()
        return response
