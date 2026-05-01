"""
Authentication manager for the ServiceNow MCP server.
"""

import base64
import json
import logging
import os
import threading
import time
from typing import Dict, Optional
from urllib.parse import parse_qsl, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils.config import AuthConfig, AuthType, BrowserAuthConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared HTTP Session Factory
# ---------------------------------------------------------------------------

_SESSION_POOL_SIZE = 20  # Max connections per host (default urllib3 is 10)
_SESSION_MAX_RETRIES_CONNECT = 0  # Connection-level retries handled by make_request


def _build_http_session() -> requests.Session:
    """Create a ``requests.Session`` with connection-pooling tuned for
    repeated calls to a single ServiceNow instance.

    Benefits over bare ``requests.request()``:
    - TCP keep-alive: avoids 3-way handshake on every call
    - TLS session resumption: saves ~100-300ms per request
    - urllib3 connection pool: reuses sockets across threads
    """
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
    return session


_PROFILE_LOCK_HINTS = (
    "singletonlock",
    "profile directory is already",
    "already in use",
    "failed to create /",
    "process already exists",
)


# Substrings (lowercase) that indicate the persistent Chromium context was
# closed before login completed. We treat any match as "user-cancelled the
# login window" — the LLM/auth state machine then applies a cooldown rather
# than re-opening another window immediately.
USER_CLOSE_ERROR_MARKERS = (
    "target closed",
    "browser closed",
    "browser was closed",
    "browser has been closed",
    "target page, context or browser has been closed",
    "connection closed",
    "login_cancelled_by_user",
)


def _looks_like_user_close(error_text: str) -> bool:
    """Return True if `error_text` (lowercased exception message) contains
    a marker indicating the browser/login window was closed before auth
    completed."""
    return any(marker in error_text for marker in USER_CLOSE_ERROR_MARKERS)


def _is_debug_mode() -> bool:
    """Debug mode: SERVICENOW_BROWSER_DEBUG=1/true keeps the Chromium window open
    even on errors and auto-opens DevTools, so the user can inspect the failing
    401 response, request headers, cookies, and X-UserToken without the auth
    manager auto-closing the window mid-investigation."""
    val = (os.environ.get("SERVICENOW_BROWSER_DEBUG") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _launch_persistent_with_retry(chromium, user_data_dir: str, *, headless: bool):
    """Launch a persistent Chromium context, retrying briefly if the profile
    directory is locked by a concurrent MCP process.

    With a per-instance shared profile path, two processes starting at the
    same time can briefly race on the Chromium profile lock (the losing side
    typically releases within 1-2s after a quick headless probe). Without a
    retry we would surface that transient lock as a login failure.

    Debug mode (SERVICENOW_BROWSER_DEBUG=true) forces headed + auto-opens
    DevTools so the user can inspect the failing requests directly.
    """
    debug = _is_debug_mode()
    if debug:
        headless = False
    launch_kwargs: dict = {"headless": headless}
    if debug:
        launch_kwargs["args"] = ["--auto-open-devtools-for-tabs"]

    attempts = 5
    backoff = 1.5
    for attempt in range(1, attempts + 1):
        try:
            return chromium.launch_persistent_context(user_data_dir, **launch_kwargs)
        except Exception as exc:
            msg = str(exc).lower()
            if attempt == attempts or not any(hint in msg for hint in _PROFILE_LOCK_HINTS):
                raise
            logger.info(
                "Chromium profile locked by another process "
                "(attempt %d/%d): %s — retrying in %.1fs",
                attempt,
                attempts,
                exc,
                backoff,
            )
            time.sleep(backoff)
            backoff *= 1.5


USERNAME_SELECTORS = (
    "input#user_name",
    "input[name='user_name']",
    "input#username",
    "input[name='username']",
    "input[type='email']",
    "input[name='identifier']",
    "input[name='loginfmt']",
)

PASSWORD_SELECTORS = (
    "input#user_password",
    "input[name='user_password']",
    "input#password",
    "input[name='password']",
    "input[name='passwd']",
    "input[type='password']",
)

SUBMIT_SELECTORS = (
    "button#sysverb_login",
    "input#sysverb_login",
    "button[type='submit']",
    "input[type='submit']",
    "button[name='login']",
    "input[name='login']",
    "input#idSIButton9",
    "button[data-type='save']",
)


def _is_login_page_url(url: str) -> bool:
    """Return True when the URL still indicates ServiceNow login flow."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    # Explicit login/logout page markers
    login_markers = [
        "/login.do",
        "/auth_redirect.do",
        "/external_logout_complete.do",
        "/multi_factor_auth_view.do",
        "/multi_factor_auth_setup.do",
        "/external_login_complete.do",
        "/sys_auth_info.do",
    ]
    return (
        any(marker in path for marker in login_markers)
        or "sysparm_type=login" in query
        or "sysparm_reauth=true" in query
        or "sysparm_mfa_needed=true" in query
        or "sysparm_direct=true" in query
        or path == "/login"
        or path == "/auth"
    )


def _extract_cookie_names(cookie_header: Optional[str]) -> list[str]:
    if not cookie_header:
        return []
    names: list[str] = []
    for part in cookie_header.split(";"):
        token = part.strip()
        if not token or "=" not in token:
            continue
        names.append(token.split("=", 1)[0].strip())
    return names


def _cookie_header_to_dict(cookie_header: Optional[str]) -> dict[str, str]:
    if not cookie_header:
        return {}
    cookie_map: dict[str, str] = {}
    for part in cookie_header.split(";"):
        token = part.strip()
        if not token or "=" not in token:
            continue
        name, value = token.split("=", 1)
        key = name.strip()
        if not key:
            continue
        cookie_map[key] = value.strip()
    return cookie_map


def _has_servicenow_session_cookie(cookie_names: list[str]) -> bool:
    session_cookie_names = {
        "jsessionid",
        "glide_user_session",
        "glide_session_store",
        "glide_session",
        "glide_user_route",
        "glide_ss",
    }
    return any(name.lower() in session_cookie_names for name in cookie_names)


def _looks_like_instance_main_ui(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    # Common post-login ServiceNow UI routes.
    return any(
        marker in path for marker in ["/now/", "/navpage.do", "/home.do", "/sp"]
    ) or path in ("", "/")


def _response_indicates_login_redirect(response: requests.Response) -> bool:
    location = (response.headers.get("Location") or "").lower()
    response_url = str(response.url or "").lower()
    return (
        "login.do" in location
        or "sysparm_type=login" in location
        or _is_login_page_url(response_url)
    )


def _response_indicates_authenticated_session(response: requests.Response) -> bool:
    if _response_indicates_login_redirect(response):
        return False

    try:
        body = (response.text or "")[:2000].lower()
    except Exception:
        body = ""

    unauthenticated_markers = [
        "user not authenticated",
        "login with sso",
        "forgot password ?",
        "forgot password?",
        "log in | servicenow",
        "<title>log in",
    ]
    return not any(marker in body for marker in unauthenticated_markers)


def _response_confirms_browser_probe_session(response: requests.Response) -> bool:
    """Return True only when the probe proves the session is reusable."""
    if not _response_indicates_authenticated_session(response):
        return False
    if response.status_code == 401:
        content_type = (response.headers.get("Content-Type") or "").lower()
        return "application/json" in content_type
    return response.status_code == 403 or 200 <= response.status_code < 300


def _response_indicates_acl_block(response: requests.Response) -> bool:
    """Return True only when a 401 JSON body clearly indicates an ACL/permission block
    (not a session/token expiry).

    ServiceNow returns 401 + JSON for both stale X-UserToken AND ACL denials, so we
    must inspect the body to tell them apart. When uncertain, return False so the
    caller treats it as a session issue and re-authenticates.
    """
    if response.status_code != 401:
        return False
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "application/json" not in content_type:
        return False
    if _response_indicates_login_redirect(response):
        return False
    try:
        body = (response.text or "")[:2000].lower()
    except Exception:
        return False
    # Strong session-expiry signals — definitively NOT ACL
    session_expiry_markers = (
        "user not authenticated",
        "session has expired",
        "session expired",
        "invalid session",
        "x-usertoken",
    )
    if any(marker in body for marker in session_expiry_markers):
        return False
    # Strong ACL signals
    acl_markers = (
        "insufficient rights",
        "access denied",
        "acl ",
        "operation against the requested object is not allowed",
        "no permission",
        "not authorized to",
    )
    return any(marker in body for marker in acl_markers)


def _selector_exists(target, selector: str) -> bool:
    try:
        return target.locator(selector).count() > 0
    except Exception:
        return False


def _fill_first_matching(target, selectors: tuple[str, ...], value: str) -> Optional[str]:
    for selector in selectors:
        if _selector_exists(target, selector):
            try:
                target.fill(selector, value)
                return selector
            except Exception:
                continue
    return None


def _click_first_matching(target, selectors: tuple[str, ...]) -> Optional[str]:
    for selector in selectors:
        if _selector_exists(target, selector):
            try:
                target.click(selector)
                return selector
            except Exception:
                continue
    return None


def _target_label(target, index: int) -> str:
    try:
        url = str(getattr(target, "url", "") or "")
    except Exception:
        url = ""
    prefix = "main" if index == 0 else f"frame[{index}]"
    return f"{prefix}:{url}" if url else prefix


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
        self._http_session: requests.Session = _build_http_session()
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
        self._browser_validation_interval_seconds = 120
        self._browser_last_login_at: Optional[float] = None
        self._browser_post_login_grace_seconds = 90
        self._browser_reauth_cooldown_seconds = 15  # Start short, back off on repeated failures
        self._browser_reauth_cooldown_base = 15
        self._browser_reauth_cooldown_max = 120
        self._browser_reauth_failure_count = 0
        self._browser_login_in_progress = False  # True while browser window is open for MFA
        self._browser_login_lock = threading.Lock()  # Prevent concurrent browser login attempts
        self._keepalive_thread: Optional[threading.Thread] = None
        self._keepalive_stop_event = threading.Event()
        self._session_cache_path = self._get_session_cache_path()
        self._login_lock_path = self._session_cache_path.replace(".json", ".lock")
        # Garbage-collect a stale legacy cache that lives in the default
        # `~/.servicenow_mcp/` directory when the user has since set
        # SERVICENOW_BROWSER_USER_DATA_DIR (active cache moved to
        # `dirname(user_data_dir)`). The legacy file would otherwise hang
        # around forever and confuse the user ("why are there two of these?").
        self._cleanup_legacy_session_cache()
        self._cached_basic_auth_header: Optional[str] = None
        self._session_disk_hash: Optional[int] = None  # Track disk content to skip redundant writes
        self._keepalive_consecutive_failures: int = 0  # Track consecutive keepalive failures

        # Lazy browser auth: only load disk cache on startup (no browser).
        # The actual browser login is deferred to the first tool call
        # via get_headers(), avoiding an unwanted login window on MCP start.
        if self.config.type == AuthType.BROWSER:
            self._ensure_playwright_ready()
            self._load_session_from_disk()
            if self._browser_cookie_header and not self._is_browser_session_expired():
                logger.info("Startup: session restored from disk cache — ready.")
                self._start_keepalive()
            else:
                if self._browser_cookie_header:
                    self._browser_cookie_header = None
                    self._browser_cookie_expires_at = None
                logger.info(
                    "Startup: no cached session. "
                    "Browser login will be triggered on the first tool call."
                )

    # ------------------------------------------------------------------
    # Playwright pre-flight check
    # ------------------------------------------------------------------

    @staticmethod
    def _should_skip_probe(
        *,
        state_changed: bool,
        in_confirmation: bool,
        iterations_since_probe: int,
        safety_net_iterations: int = 10,
    ) -> bool:
        """Return True if the polling loop should skip the HTTP probe this
        iteration.

        The probe is gated on observable state change (URL path or cookie
        set) so we do not spam ServiceNow with identical 401s while the
        user is typing an MFA code on a stationary page.

        Three rules:
        - In the consecutive-confirmation phase (`in_confirmation=True`,
          i.e. one successful probe already seen), never skip — we need
          the next probe immediately to confirm or invalidate.
        - If state changed (URL or cookie set differs from last probe),
          never skip — something material happened.
        - Otherwise, skip until `iterations_since_probe` reaches the
          safety net so a no-state-change completion is still detected.
        """
        if in_confirmation:
            return False
        if state_changed:
            return False
        return iterations_since_probe < safety_net_iterations

    @staticmethod
    def _compute_login_wait_budget_ms(
        timeout_ms: int, *, use_headless: bool, debug_mode: bool
    ) -> int:
        """Pick the wait_budget_ms used by the polling loop in login.

        - Debug mode: 30 minutes. Lets the user inspect requests in DevTools.
        - Visible-window (use_headless=False): at least 60s, raised to
          `timeout_ms` if larger. MFA/SSO entry needs human time; do not
          fail fast on a window the user is actively working in. This
          covers BOTH `force_interactive=True` AND
          `browser_config.headless=False` — both produce a visible window
          and both deserve the longer budget.
        - Headless (use_headless=True): at most 30s. The cookie gate
          covers the common "MFA required" case in <1s, and a 30s cap
          keeps the wrapper's fallback to interactive snappy when SSO
          never lands a probe-200 in the invisible window.
        """
        if debug_mode:
            return 1800000
        if not use_headless:
            return max(timeout_ms, 60000)
        return min(timeout_ms, 30000)

    def _apply_browser_session_headers(self, headers: dict) -> dict:
        """Mutate `headers` in place to include the captured browser session
        — Cookie + optional User-Agent + optional X-UserToken — and return
        the same dict for chaining. Centralises the 10-call pattern that
        previously copy-pasted the same three assignments around
        get_auth_headers."""
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

        The Chromium *browser binary* is a separate download.  If it is
        missing or version-mismatched we run ``playwright install chromium``
        automatically.
        """
        import shutil
        import subprocess
        import sys

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
        # Quick probe: try launching Chromium headless.  If the binary is
        # missing or version-mismatched Playwright raises a clear error.
        need_install = False
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                browser.close()
        except Exception as exc:
            exc_msg = str(exc).lower()
            if "executable doesn't exist" in exc_msg or "browser" in exc_msg:
                need_install = True
            else:
                logger.debug("Playwright probe raised non-binary error: %s", exc)

        if need_install:
            logger.info("Chromium browser binary missing — installing via playwright install …")
            # Prefer the playwright CLI on PATH (works inside uvx venvs),
            # fall back to ``python -m playwright``.
            pw_cli = shutil.which("playwright")
            if pw_cli:
                cmd = [pw_cli, "install", "chromium"]
            else:
                cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
            subprocess.check_call(cmd, timeout=300)
            logger.info("Chromium browser binary installed successfully.")

    def _get_cache_dir(self) -> str:
        """Resolve the root cache directory for session JSON and Playwright profile.

        If the user has set ``browser.user_data_dir`` (via
        ``SERVICENOW_BROWSER_USER_DATA_DIR``), the session JSON sits next to
        that profile directory so both files live in the same parent — letting
        multiple MCP hosts (Claude / Codex / etc.) share login state by
        pointing at the same path. Otherwise default to ``~/.servicenow_mcp``.
        """
        if self.config.browser and self.config.browser.user_data_dir:
            cache_dir = os.path.dirname(os.path.abspath(self.config.browser.user_data_dir))
        else:
            cache_dir = os.path.join(os.path.expanduser("~"), ".servicenow_mcp")
        os.makedirs(cache_dir, exist_ok=True)
        return cache_dir

    def _get_instance_user_suffix(self) -> str:
        """Return the ``{instance}{_user}`` suffix used in cache filenames."""
        instance_id = "default"
        if self.instance_url:
            instance_id = (urlparse(self.instance_url).hostname or "default").replace(".", "_")
        username = ""
        if self.config.browser and self.config.browser.username:
            username = f"_{self.config.browser.username.replace('.', '_').replace('@', '_')}"
        elif self.config.basic and self.config.basic.username:
            username = f"_{self.config.basic.username.replace('.', '_').replace('@', '_')}"
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
        """Return the configured Playwright profile dir, or the per-instance default."""
        return browser_config.user_data_dir or self._get_default_user_data_dir()

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

        Skips the write if the serialized content matches the last saved hash,
        which reduces I/O by ~70-80% during keepalive pings.
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
        }
        # Quick content-hash check to skip redundant writes
        content_hash = hash((data["cookie_header"], data["user_agent"], data["session_token"]))
        if content_hash == self._session_disk_hash:
            return
        try:
            with open(self._session_cache_path, "w") as f:
                json.dump(data, f)
            self._session_disk_hash = content_hash
            logger.info("Browser session saved to disk: %s", self._session_cache_path)
        except Exception as exc:
            logger.warning("Failed to save browser session to disk: %s", exc)

    def _cleanup_legacy_session_cache(self) -> None:
        """When the user has set SERVICENOW_BROWSER_USER_DATA_DIR, the active
        cache lives in `dirname(user_data_dir)`. A pre-existing copy in the
        default `~/.servicenow_mcp/` directory (left over from a run that did
        NOT set USER_DATA_DIR) is unreachable from the active path resolver
        but stays on disk forever, confusing the user. Remove it.
        """
        if not (self.config.browser and self.config.browser.user_data_dir):
            return  # No USER_DATA_DIR set → default IS the active path
        legacy_dir = os.path.join(os.path.expanduser("~"), ".servicenow_mcp")
        if not os.path.isdir(legacy_dir):
            return
        suffix = self._get_instance_user_suffix()
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
            logger.info("Loaded browser session from disk: %s", self._session_cache_path)
        except Exception as exc:
            logger.warning("Failed to load browser session from disk: %s", exc)

    def _reload_session_from_disk(self) -> bool:
        """Reload session from disk if a fresher session exists.

        Used by keepalive and request retry paths to pick up sessions
        written by another terminal/process sharing the same cache file.
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
        # Skip if disk session is the same as what we already have in memory
        if disk_cookie == self._browser_cookie_header:
            # But refresh TTL if disk has a later expiry (another process extended it)
            if disk_expires and (
                not self._browser_cookie_expires_at
                or disk_expires > self._browser_cookie_expires_at
            ):
                self._browser_cookie_expires_at = disk_expires
                # Another process recently wrote/validated the session — adopt their
                # validated_at if present (capped to now) so we don't claim a fresher
                # validation than actually happened.
                disk_validated_at = data.get("last_validated_at")
                if disk_validated_at:
                    self._browser_last_validated_at = min(disk_validated_at, time.time())
                logger.debug("Reload: same cookies but extended TTL from disk.")
            return False

        # Disk has different cookies — likely written by another terminal after re-auth
        if disk_expires and time.time() > disk_expires:
            # Remove the expired file so we don't keep re-reading it on every
            # 401 retry / keepalive cycle. A fresh login will write a new one.
            self._delete_session_cache_file("expired on reload")
            return False

        self._browser_cookie_header = disk_cookie
        self._browser_user_agent = data.get("user_agent")
        self._browser_session_token = data.get("session_token")
        self._browser_cookie_expires_at = disk_expires
        # Pair with v1.10.21 probe-before-trust in get_headers(): inherit the disk
        # validation timestamp if present (capped to now); otherwise leave None so
        # the next caller probes before trusting cookies that may have been written
        # by a sibling process that has since idle-timed-out on the server.
        disk_validated_at = data.get("last_validated_at")
        self._browser_last_validated_at = (
            min(disk_validated_at, time.time()) if disk_validated_at else None
        )
        logger.info(
            "Reloaded fresher session from disk (written by another process): %s",
            self._session_cache_path,
        )
        return True

    def _start_keepalive(self) -> None:
        """Start a background thread that periodically pings ServiceNow
        to keep the browser session alive (sliding window reset).

        The ping interval is half the session TTL (default 15 minutes).
        Only runs when a valid session exists; sleeps quietly otherwise.
        """
        if not self.config.browser:
            return

        import random

        ttl_minutes = self.config.browser.session_ttl_minutes or 30
        base_interval = max(ttl_minutes * 60 // 2, 60)  # half of TTL, minimum 60s
        # Add jitter so multiple MCP processes don't ping at the same time
        ping_interval = base_interval + random.randint(10, 60)

        def _keepalive_loop() -> None:
            while not self._keepalive_stop_event.is_set():
                self._keepalive_stop_event.wait(ping_interval)
                if self._keepalive_stop_event.is_set():
                    break
                # Only ping if we have a valid session outside grace period
                if not self._browser_cookie_header or self._is_browser_session_expired():
                    # No session in memory — try loading from disk
                    # (another terminal may have written a fresh session)
                    self._reload_session_from_disk()
                    if not self._browser_cookie_header or self._is_browser_session_expired():
                        continue
                if (
                    self._browser_last_login_at is not None
                    and (time.time() - self._browser_last_login_at)
                    < self._browser_post_login_grace_seconds
                ):
                    continue
                # Dedup: if another process recently extended TTL on disk,
                # skip our ping to avoid redundant requests from multiple terminals.
                if self._reload_session_from_disk():
                    # Disk had fresher cookies — adopted them, skip ping this cycle.
                    self._keepalive_consecutive_failures = 0
                    continue
                if self._browser_cookie_expires_at and (
                    self._browser_cookie_expires_at - time.time()
                ) > (ttl_minutes * 60 - ping_interval * 0.3):
                    # TTL was recently extended (by another process's ping) —
                    # remaining TTL is close to full, no need to ping again.
                    logger.debug(
                        "Keep-alive: TTL recently extended (remaining %.0fs), skipping ping.",
                        self._browser_cookie_expires_at - time.time(),
                    )
                    continue
                try:
                    probe = self._probe_browser_api_with_cookie(
                        self._browser_cookie_header,
                        timeout_seconds=10,
                        browser_config=self.config.browser,  # type: ignore[arg-type]
                    )
                    if _response_confirms_browser_probe_session(probe):
                        # Session is alive — extend TTL
                        self._browser_cookie_expires_at = time.time() + (ttl_minutes * 60)
                        self._browser_last_validated_at = time.time()
                        self._keepalive_consecutive_failures = 0
                        self._save_session_to_disk()
                        logger.debug(
                            "Keep-alive ping OK: session extended by %d minutes.",
                            ttl_minutes,
                        )
                    else:
                        self._keepalive_consecutive_failures += 1
                        logger.info(
                            "Keep-alive ping: session invalid (status=%s, failure %d/3). "
                            "Trying disk reload...",
                            probe.status_code,
                            self._keepalive_consecutive_failures,
                        )
                        # Another terminal may have re-authenticated — try disk reload
                        if self._reload_session_from_disk():
                            logger.info("Keep-alive: reloaded fresher session from disk.")
                            self._keepalive_consecutive_failures = 0
                        elif self._keepalive_consecutive_failures >= 3:
                            logger.info(
                                "Keep-alive: 3 consecutive failures — "
                                "invalidating session. Will re-authenticate on next tool call."
                            )
                            self.invalidate_browser_session()
                            self._keepalive_consecutive_failures = 0
                except Exception as exc:
                    self._keepalive_consecutive_failures += 1
                    logger.debug(
                        "Keep-alive ping failed (failure %d/3): %s",
                        self._keepalive_consecutive_failures,
                        exc,
                    )
                    if self._keepalive_consecutive_failures >= 3:
                        logger.info("Keep-alive: 3 consecutive failures — " "invalidating session.")
                        self.invalidate_browser_session()
                        self._keepalive_consecutive_failures = 0

        self._keepalive_thread = threading.Thread(
            target=_keepalive_loop, daemon=True, name="sn-session-keepalive"
        )
        self._keepalive_thread.start()
        logger.info(
            "Session keep-alive started: ping every %d minutes (TTL=%d minutes).",
            ping_interval // 60,
            ttl_minutes,
        )

    def stop_keepalive(self) -> None:
        """Stop the keep-alive background thread."""
        self._keepalive_stop_event.set()
        if self._keepalive_thread and self._keepalive_thread.is_alive():
            self._keepalive_thread.join(timeout=5)
            logger.info("Session keep-alive stopped.")

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
                                if not self._keepalive_thread:
                                    self._start_keepalive()
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
                        if not self._keepalive_thread:
                            self._start_keepalive()
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
                                if not self._keepalive_thread:
                                    self._start_keepalive()
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
                            "Browser login is currently in progress — the user is completing MFA/SSO authentication. "
                            "Please wait for the user to finish and then retry this request. "
                            "Do NOT start a new login attempt."
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
                                if not self._keepalive_thread:
                                    self._start_keepalive()
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
                                "Browser login is in progress in another terminal. "
                                "Please complete MFA/SSO there, or close that browser window first."
                            )
                    if not self._can_attempt_browser_reauth():
                        self._release_login_lock()
                        cooldown_remaining = self._get_reauth_cooldown_remaining()
                        raise ValueError(
                            f"Browser session expired. Re-login will be attempted automatically "
                            f"in {cooldown_remaining}s. "
                            f"(Attempt {self._browser_reauth_failure_count} failed — "
                            f"cooldown {self._browser_reauth_cooldown_seconds}s) "
                            "If the browser login window appeared, please complete MFA/SSO authentication. "
                            "You can also retry this tool call after the cooldown to trigger a new login."
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
                        if not self._keepalive_thread:
                            self._start_keepalive()
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
                                if not self._keepalive_thread:
                                    self._start_keepalive()
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
                                "LOGIN_CANCELLED_BY_USER: the browser login window was "
                                f"closed before authentication completed. Wait "
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
                            if not self._keepalive_thread:
                                self._start_keepalive()
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
                                if not self._keepalive_thread:
                                    self._start_keepalive()
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
                                "LOGIN_CANCELLED_BY_USER: the browser login window was "
                                f"closed before authentication completed. Wait "
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
        logger.debug(
            "Browser session probe result: status=%s redirect=%s url_host=%s",
            response.status_code,
            response.is_redirect,
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
        if self._should_validate_browser_session() and not self._is_browser_session_valid(
            browser_config
        ):
            return False
        return True

    def _mark_browser_session_recently_valid(self) -> None:
        """Treat a successful authenticated API response as proof that the
        browser-backed session is still alive.

        This avoids paying an additional validation probe on the next request
        when the server already accepted the current cookie + user token pair.
        """
        self._browser_last_validated_at = time.time()

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
        probe_cookies = _cookie_header_to_dict(cookie_header)
        return self._http_session.get(
            probe_url,
            params=probe_params,
            headers=probe_headers,
            cookies=probe_cookies,
            timeout=timeout_seconds,
            allow_redirects=False,
        )

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
            return False

        if not _response_confirms_browser_probe_session(probe):
            logger.info(
                "Browser session restore probe rejected cached cookies: status=%s",
                probe.status_code,
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

    def _login_with_browser_sync(
        self, browser_config: BrowserAuthConfig, force_interactive: bool = False
    ) -> None:
        instance_url = self.instance_url
        if not instance_url:
            raise ValueError("Instance URL is required for browser authentication")

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
        use_headless = browser_config.headless and not force_interactive
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
                    _safe_close_context()
                    raise ValueError(
                        "MFA_REQUIRED: persistent profile has no valid "
                        "glide_mfa_remembered_browser cookie — falling back to "
                        "interactive login."
                    )

            page = context.pages[0] if context.pages else context.new_page()

            # Store the User-Agent from the browser to match in subsequent requests
            self._browser_user_agent = page.evaluate("navigator.userAgent")

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

            # Keep browser open until cookie-based API probe confirms authenticated session.
            # Avoid closing too early on transient cookies while MFA/SSO is still in progress.
            start = time.time()
            login_confirmed = False
            successful_probes = 0
            stable_instance_ticks = 0
            # State gate: only run the HTTP probe when URL path or cookie set has
            # actually changed since the last probe. While the user is typing
            # an MFA code, the page state is stationary and there is nothing
            # new to verify — running 70 identical probes during a 90s wait
            # just spams 401s and noises up stderr. Safety net forces a probe
            # every ~10s so we never miss a no-state-change MFA completion.
            prev_url_path = ""
            prev_cookie_names: set[str] = set()
            iterations_since_probe = 0
            while (time.time() - start) * 1000 < wait_budget_ms:
                # Detect browser closed by user — break immediately instead of
                # looping for minutes until wait_budget_ms expires.
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
                # Use full-context cookies; some IdP/ServiceNow flows keep auth
                # cookies on parent domains that may not be returned for a single URL filter.
                current_cookies = context.cookies()
                cookie_header = self._build_instance_cookie_header(
                    current_cookies,  # type: ignore[arg-type]
                    instance_url,
                    instance_host,
                )
                if cookie_header:
                    cookie_names = _extract_cookie_names(cookie_header)
                    if current_host == instance_host and not _is_login_page_url(current_url):
                        stable_instance_ticks += 1
                    else:
                        stable_instance_ticks = 0
                    # Skip probe when neither URL path nor cookie set changed
                    # since last probe. Safety net: force a probe every ~10
                    # iterations even on stationary state, so we never get
                    # stuck waiting on a no-change completion. Once we've
                    # gotten a successful probe, we are in the consecutive-
                    # confirmation phase — bypass the gate so the second
                    # probe runs immediately.
                    current_path = urlparse(current_url).path
                    cookie_name_set = set(cookie_names)
                    state_changed = (
                        current_path != prev_url_path or cookie_name_set != prev_cookie_names
                    )
                    iterations_since_probe += 1
                    if self._should_skip_probe(
                        state_changed=state_changed,
                        in_confirmation=successful_probes > 0,
                        iterations_since_probe=iterations_since_probe,
                    ):
                        time.sleep(1)
                        continue
                    prev_url_path = current_path
                    prev_cookie_names = cookie_name_set
                    iterations_since_probe = 0
                    try:
                        probe = self._probe_browser_api_with_cookie(
                            cookie_header,
                            timeout_seconds=min(int(browser_config.timeout_seconds), 5),
                            browser_config=browser_config,
                        )
                        # Require consecutive successful probes so we do not treat
                        # intermediate redirect/cookie states as completed MFA login.
                        # Also ensure the probe returned a clear authenticated status (200 or 403).
                        # A 401 (Unauthorized) or 3xx (Redirect) indicates login is still in progress.
                        if _response_confirms_browser_probe_session(probe):
                            resolved_url = str(probe.url)
                            resolved_host = (urlparse(resolved_url).hostname or "").lower()
                            if (
                                resolved_host == instance_host
                                and current_host == instance_host
                                and not _is_login_page_url(resolved_url)
                                and not _is_login_page_url(current_url)
                            ):
                                successful_probes += 1
                                logger.debug(
                                    "Browser auth probe success candidate: status=%s current_host=%s "
                                    "resolved_host=%s stable_ticks=%s successful_probes=%s cookie_count=%s",
                                    probe.status_code,
                                    current_host,
                                    resolved_host,
                                    stable_instance_ticks,
                                    successful_probes,
                                    len(cookie_names),
                                )
                                if successful_probes >= 2:
                                    logger.info(
                                        "Browser auth confirmed by probe: status=%s current_host=%s "
                                        "resolved_host=%s cookie_names=%s",
                                        probe.status_code,
                                        current_host,
                                        resolved_host,
                                        ",".join(cookie_names),
                                    )
                                    login_confirmed = True
                                    break
                            else:
                                successful_probes = 0
                        else:
                            logger.warning(
                                "Browser auth probe unauthorized: status=%s current_host=%s "
                                "stable_ticks=%s cookie_names=%s",
                                probe.status_code,
                                current_host,
                                stable_instance_ticks,
                                ",".join(cookie_names),
                            )
                            successful_probes = 0
                    except requests.RequestException:
                        # During MFA transitions network hiccups are possible; keep polling until timeout.
                        successful_probes = 0
                time.sleep(1)

            if not login_confirmed:
                _safe_close_context()
                if use_headless:
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
            try:
                self._browser_session_token = page.evaluate("window.g_ck")
            except Exception:
                self._browser_session_token = None
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
            self._clear_browser_reauth_attempt()
            # Close the persistent context BEFORE final_probe runs so the browser
            # window goes away whether the probe passes or fails. The probe is a
            # plain HTTP call against self._browser_cookie_header, so it does not
            # depend on the live Chromium context.
            _safe_close_context()

            # Final validation: avoid storing UI-only cookies that still fail API
            # auth and cause immediate 401/reopen loops.
            try:
                final_probe = self._probe_browser_api_with_cookie(
                    self._browser_cookie_header,
                    timeout_seconds=10,
                    browser_config=browser_config,
                )
            except requests.RequestException as exc:
                self.invalidate_browser_session()
                raise ValueError(
                    "Browser login appeared to complete, but final API validation failed. "
                    "Not reusing this session; please retry login. "
                    f"Probe error: {exc}"
                ) from exc
            if not _response_confirms_browser_probe_session(final_probe):
                self.invalidate_browser_session()
                # Include more detail for debugging auth failures
                probe_url = final_probe.url
                probe_text = final_probe.text[:200]
                raise ValueError(
                    f"Browser login completed, but API auth is still unauthorized. "
                    f"Status: {final_probe.status_code}, URL: {probe_url}, Response: {probe_text}"
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
            logger.info(
                "Browser session stored: mode=%s session_key=%s cookie_count=%s "
                "cookie_names=%s ttl_minutes=%s",
                "headless" if use_headless else "interactive",
                self._browser_session_key,
                len(_extract_cookie_names(self._browser_cookie_header)),
                ",".join(_extract_cookie_names(self._browser_cookie_header)),
                browser_config.session_ttl_minutes,
            )

    def invalidate_browser_session(self):
        """Invalidate the current browser session, forcing re-authentication on next request.

        Only removes the disk cache file if it still contains OUR cookies.
        Another terminal may have already written a fresher session to disk,
        and we must not delete that.
        """
        my_cookie = self._browser_cookie_header
        logger.info("Browser session invalidated (in-memory)")
        self._browser_cookie_header = None
        self._browser_cookie_expires_at = None
        self._browser_last_validated_at = None
        self._browser_session_token = None
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
        # Get auth headers
        headers = kwargs.pop("headers", {})
        headers.update(self.get_headers())
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
        cookie_names = _extract_cookie_names(headers.get("Cookie"))
        start = time.monotonic()
        logger.info(
            "ServiceNow request start: method=%s host=%s timeout=%s auth_type=%s cookie_count=%s",
            method_upper,
            request_host,
            request_timeout,
            self.config.type.value,
            len(cookie_names),
        )
        if cookie_names and logger.isEnabledFor(logging.DEBUG):
            logger.debug("ServiceNow request cookies: %s", ",".join(cookie_names))

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
                    # very next real call still 401s. Re-authenticating would just
                    # produce another fresh-but-rejected session and the user would
                    # see another browser window. Raise a clear, non-retriable signal
                    # so the LLM stops retrying and the user can investigate the
                    # actual root cause (X-UserToken policy, ACL on this endpoint,
                    # cookie-domain mismatch, instance security policy).
                    raise requests.HTTPError(
                        "FRESH_SESSION_REJECTED: a brand-new browser session "
                        "(<{grace}s old) is being rejected by ServiceNow with 401 on "
                        "this endpoint, even though final_probe passed. "
                        "Re-authentication will not help — the session itself is fine. "
                        "Likely causes: X-UserToken (g_ck) policy/rotation on this "
                        "endpoint, ACL restriction with a non-standard error body, "
                        "cookie-domain mismatch (.service-now.com vs instance host), "
                        "or instance security policy blocking the call. "
                        "Inspect the 401 diagnostic log line above for body/headers.".format(
                            grace=self._browser_post_login_grace_seconds
                        ),
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
