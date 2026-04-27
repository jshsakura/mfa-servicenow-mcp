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


def _launch_persistent_with_retry(chromium, user_data_dir: str, *, headless: bool):
    """Launch a persistent Chromium context, retrying briefly if the profile
    directory is locked by a concurrent MCP process.

    With a per-instance shared profile path, two processes starting at the
    same time can briefly race on the Chromium profile lock (the losing side
    typically releases within 1-2s after a quick headless probe). Without a
    retry we would surface that transient lock as a login failure.
    """
    attempts = 5
    backoff = 1.5
    for attempt in range(1, attempts + 1):
        try:
            return chromium.launch_persistent_context(user_data_dir, headless=headless)
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
    return not _response_indicates_login_redirect(response)


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
        self._browser_user_agent = None
        self._browser_session_token = None
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

    def _get_session_cache_path(self) -> str:
        """Get the path to the session cache file, scoped by instance + user."""
        home = os.path.expanduser("~")
        cache_dir = os.path.join(home, ".servicenow_mcp")
        os.makedirs(cache_dir, exist_ok=True)
        instance_id = "default"
        if self.instance_url:
            instance_id = (urlparse(self.instance_url).hostname or "default").replace(".", "_")
        # Include username in cache key to prevent session cross-contamination
        # when multiple users share the same machine/instance.
        username = ""
        if self.config.browser and self.config.browser.username:
            username = f"_{self.config.browser.username.replace('.', '_').replace('@', '_')}"
        elif self.config.basic and self.config.basic.username:
            username = f"_{self.config.basic.username.replace('.', '_').replace('@', '_')}"
        return os.path.join(cache_dir, f"session_{instance_id}{username}.json")

    def _get_default_user_data_dir(self) -> str:
        """Per-instance default Playwright profile directory.

        Scoped by instance host (and username) so repeated MCP starts for the
        same instance share the same profile — preserving SSO/IDP cookies so
        re-login is silent when the ServiceNow session expires. Different
        instances/users get isolated profiles.
        """
        home = os.path.expanduser("~")
        cache_dir = os.path.join(home, ".servicenow_mcp")
        os.makedirs(cache_dir, exist_ok=True)
        instance_id = "default"
        if self.instance_url:
            instance_id = (urlparse(self.instance_url).hostname or "default").replace(".", "_")
        username = ""
        if self.config.browser and self.config.browser.username:
            username = f"_{self.config.browser.username.replace('.', '_').replace('@', '_')}"
        return os.path.join(cache_dir, f"profile_{instance_id}{username}")

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

    def _load_session_from_disk(self) -> None:
        """Load the browser session from disk.

        If the disk TTL has expired, the session is still loaded and verified
        with a live API probe — the ServiceNow server session may outlive the
        conservative disk TTL, so we should not discard a potentially valid session.
        """
        if not os.path.exists(self._session_cache_path):
            return

        try:
            with open(self._session_cache_path, "r") as f:
                data = json.load(f)

            # Basic validation
            if data.get("instance_url") != self.instance_url:
                return

            cookie_header = data.get("cookie_header")
            if not cookie_header:
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
                        if _response_indicates_authenticated_session(probe):
                            # Non-redirect = authenticated (matches runtime validation).
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
                return

            self._browser_cookie_header = cookie_header
            self._browser_user_agent = data.get("user_agent")
            self._browser_session_token = data.get("session_token")
            self._browser_cookie_expires_at = expires_at
            # Set validation interval so we don't immediately probe
            self._browser_last_validated_at = time.time()
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
                self._browser_last_validated_at = time.time()
                logger.debug("Reload: same cookies but extended TTL from disk.")
            return False

        # Disk has different cookies — likely written by another terminal after re-auth
        if disk_expires and time.time() > disk_expires:
            return False  # disk session already expired

        self._browser_cookie_header = disk_cookie
        self._browser_user_agent = data.get("user_agent")
        self._browser_session_token = data.get("session_token")
        self._browser_cookie_expires_at = disk_expires
        self._browser_last_validated_at = time.time()
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
                    if _response_indicates_authenticated_session(probe):
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
                        headers["Cookie"] = self._browser_cookie_header or ""
                        if self._browser_user_agent:
                            headers["User-Agent"] = self._browser_user_agent
                        if self._browser_session_token:
                            headers["X-UserToken"] = self._browser_session_token
                        return headers
                    raise ValueError(
                        "Browser login completed in another thread but session is not available. "
                        "Please retry this request."
                    )
                # We hold the in-process lock from here.
                try:
                    # Double-check: another thread may have completed login while we waited.
                    if self._browser_cookie_header and not self._is_browser_session_expired():
                        headers["Cookie"] = self._browser_cookie_header or ""
                        if self._browser_user_agent:
                            headers["User-Agent"] = self._browser_user_agent
                        if self._browser_session_token:
                            headers["X-UserToken"] = self._browser_session_token
                        return headers

                    # Fast path: try disk reload before opening Playwright.
                    # Another process may have already written a fresh session to disk.
                    if self._reload_session_from_disk():
                        if self._browser_cookie_header and not self._is_browser_session_expired():
                            logger.info(
                                "Session restored from disk (fast path) — skipping browser."
                            )
                            self._browser_reauth_failure_count = 0
                            self._browser_reauth_cooldown_seconds = (
                                self._browser_reauth_cooldown_base
                            )
                            if not self._keepalive_thread:
                                self._start_keepalive()
                            headers["Cookie"] = self._browser_cookie_header or ""
                            if self._browser_user_agent:
                                headers["User-Agent"] = self._browser_user_agent
                            if self._browser_session_token:
                                headers["X-UserToken"] = self._browser_session_token
                            return headers

                    # Try browser profile restore (opens Playwright) — now under lock.
                    if self._try_restore_browser_session(self.config.browser):
                        self._browser_reauth_failure_count = 0
                        self._browser_reauth_cooldown_seconds = self._browser_reauth_cooldown_base
                        if not self._keepalive_thread:
                            self._start_keepalive()
                        headers["Cookie"] = self._browser_cookie_header or ""
                        if self._browser_user_agent:
                            headers["User-Agent"] = self._browser_user_agent
                        if self._browser_session_token:
                            headers["X-UserToken"] = self._browser_session_token
                        return headers

                    # Post-restore disk check: another process may have completed
                    # login while our _try_restore_browser_session was running.
                    if self._reload_session_from_disk():
                        if self._browser_cookie_header and not self._is_browser_session_expired():
                            logger.info(
                                "Session appeared on disk after restore attempt — "
                                "another process completed login."
                            )
                            self._browser_reauth_failure_count = 0
                            self._browser_reauth_cooldown_seconds = (
                                self._browser_reauth_cooldown_base
                            )
                            if not self._keepalive_thread:
                                self._start_keepalive()
                            headers["Cookie"] = self._browser_cookie_header or ""
                            if self._browser_user_agent:
                                headers["User-Agent"] = self._browser_user_agent
                            if self._browser_session_token:
                                headers["X-UserToken"] = self._browser_session_token
                            return headers

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
                            if not self._keepalive_thread:
                                self._start_keepalive()
                            headers["Cookie"] = self._browser_cookie_header or ""
                            if self._browser_user_agent:
                                headers["User-Agent"] = self._browser_user_agent
                            if self._browser_session_token:
                                headers["X-UserToken"] = self._browser_session_token
                            return headers
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
                        "Opening browser in interactive mode for login/MFA. "
                        "(attempt #%d, cooldown=%ds)",
                        self._browser_reauth_failure_count + 1,
                        self._browser_reauth_cooldown_seconds,
                    )
                    self._mark_browser_reauth_attempt()
                    self._browser_login_in_progress = True
                    try:
                        self._login_with_browser(self.config.browser, force_interactive=True)
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
                            # User closed the browser manually — not a real failure.
                            # Reset cooldown so next tool call can retry immediately.
                        user_closed = any(
                            marker in error_text
                            for marker in [
                                "target closed",
                                "browser closed",
                                "browser has been closed",
                                "target page, context or browser has been closed",
                                "connection closed",
                            ]
                        )
                        if user_closed:
                            logger.info(
                                "Browser was closed by user — resetting cooldown for immediate retry."
                            )
                            self._browser_reauth_failure_count = 0
                            self._browser_reauth_cooldown_seconds = (
                                self._browser_reauth_cooldown_base
                            )
                            self._browser_last_reauth_attempt_at = None
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
                if not self._is_browser_session_valid(self.config.browser):
                    logger.info(
                        "Browser session is no longer valid on ServiceNow. "
                        "Opening browser for interactive re-authentication..."
                    )
                    self.invalidate_browser_session()
                    if not self._acquire_login_lock():
                        if self._wait_for_other_login(
                            timeout=self.config.browser.timeout_seconds + 60
                        ):
                            if not self._keepalive_thread:
                                self._start_keepalive()
                            headers["Cookie"] = self._browser_cookie_header or ""
                            if self._browser_user_agent:
                                headers["User-Agent"] = self._browser_user_agent
                            if self._browser_session_token:
                                headers["X-UserToken"] = self._browser_session_token
                            return headers
                    self._mark_browser_reauth_attempt()
                    self._browser_login_in_progress = True
                    try:
                        self._login_with_browser(self.config.browser, force_interactive=True)
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
                        else:
                            self._browser_login_in_progress = False
                            self._release_login_lock()
                            self._browser_reauth_failure_count += 1
                            self._browser_reauth_cooldown_seconds = min(
                                self._browser_reauth_cooldown_base
                                * (2**self._browser_reauth_failure_count),
                                self._browser_reauth_cooldown_max,
                            )
                        raise
            headers["Cookie"] = self._browser_cookie_header or ""
            if self._browser_user_agent:
                headers["User-Agent"] = self._browser_user_agent
            if self._browser_session_token:
                headers["X-UserToken"] = self._browser_session_token

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

        if not _response_indicates_authenticated_session(response):
            return False

        if response.status_code in (401, 403):
            logger.info(
                "Browser session probe is authenticated but unauthorized for probe path: "
                "status=%s probe_path=%s",
                response.status_code,
                browser_config.probe_path,
            )
            return True

        return True

    def _mark_browser_session_recently_valid(self) -> None:
        """Treat a successful authenticated API response as proof that the
        browser-backed session is still alive.

        This avoids paying an additional validation probe on the next request
        when the server already accepted the current cookie + user token pair.
        """
        self._browser_last_validated_at = time.time()

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
            from playwright.sync_api import sync_playwright
        except Exception:
            return False

        effective_user_data_dir = self._resolve_user_data_dir(browser_config)
        logger.info(
            "Attempting browser session restore from persistent profile: host=%s user_data_dir=%s",
            instance_host,
            effective_user_data_dir,
        )
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
                context.close()
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

        if not _response_indicates_authenticated_session(probe):
            logger.info(
                "Browser session restore probe indicated login redirect: status=%s",
                probe.status_code,
            )
            return False

        if probe.status_code in (401, 403):
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
        except ValueError as exc:
            error_text = str(exc).lower()
            should_fallback_to_interactive = (
                not force_interactive and "timed out waiting for browser login/mfa" in error_text
            )
            if should_fallback_to_interactive:
                logger.info(
                    "Automatic browser re-auth timed out. "
                    "Falling back to interactive re-auth with prefilled credentials."
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
        # In interactive MFA mode, allow enough time for user input/device approval.
        # Do not force a short cap that closes the browser mid-authentication.
        wait_budget_ms = max(timeout_ms, 300000) if force_interactive else timeout_ms
        instance_host = (urlparse(instance_url).hostname or "").lower()
        logger.info(
            "Starting browser auth flow: instance_host=%s login_host=%s timeout_seconds=%s mode=%s",
            instance_host,
            (urlparse(login_url).hostname or "").lower(),
            int(browser_config.timeout_seconds),
            "interactive" if force_interactive else "auto",
        )

        # 세션 만료 시 강제로 브라우저 표시 (headless 설정 무시)
        use_headless = browser_config.headless and not force_interactive

        effective_user_data_dir = self._resolve_user_data_dir(browser_config)
        with sync_playwright() as playwright:
            context = _launch_persistent_with_retry(
                playwright.chromium,
                effective_user_data_dir,
                headless=use_headless,
            )
            page = context.pages[0] if context.pages else context.new_page()

            # Store the User-Agent from the browser to match in subsequent requests
            self._browser_user_agent = page.evaluate("navigator.userAgent")

            page.goto(login_url, timeout=timeout_ms, wait_until="load")

            username = browser_config.username
            password = browser_config.password

            if username and password:
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
            saw_unauthorized_probe = False
            while (time.time() - start) * 1000 < wait_budget_ms:
                # Detect browser closed by user — break immediately instead of
                # looping for minutes until wait_budget_ms expires.
                try:
                    if page.is_closed():
                        raise ValueError(
                            "Browser was closed before login completed. "
                            "The next tool call will re-open the login window."
                        )
                    current_url = page.url
                except Exception as poll_exc:
                    error_text = str(poll_exc).lower()
                    if any(m in error_text for m in ["closed", "target", "disposed", "connection"]):
                        raise ValueError(
                            "Target page, context or browser has been closed. "
                            "The next tool call will re-open the login window."
                        ) from poll_exc
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
                        if _response_indicates_authenticated_session(
                            probe
                        ) and probe.status_code in (200, 403):
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
                            saw_unauthorized_probe = True
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
                    # Fallback for environments where API probe is flaky/blocked after MFA.
                    # In interactive mode, trust stable main-UI state to avoid hanging forever.
                    if (
                        force_interactive
                        and stable_instance_ticks >= 8
                        and _looks_like_instance_main_ui(current_url)
                        and _has_servicenow_session_cookie(cookie_names)
                    ):
                        logger.info(
                            "Interactive browser auth confirmed by stable main UI: "
                            "current_url=%s stable_ticks=%s cookie_names=%s",
                            current_url,
                            stable_instance_ticks,
                            ",".join(cookie_names),
                        )
                        login_confirmed = True
                        break
                    if (
                        not force_interactive
                        and stable_instance_ticks >= 5
                        and _has_servicenow_session_cookie(cookie_names)
                    ):
                        logger.info(
                            "Browser auth confirmed by stable instance URL and session cookie: "
                            "current_host=%s stable_ticks=%s cookie_names=%s had_unauthorized_probe=%s",
                            current_host,
                            stable_instance_ticks,
                            ",".join(cookie_names),
                            saw_unauthorized_probe,
                        )
                        login_confirmed = True
                        break
                time.sleep(1)

            if not login_confirmed:
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
                raise ValueError("Browser login succeeded but no cookies were captured")

            cookie_header = self._build_instance_cookie_header(cookies, instance_url, instance_host)  # type: ignore[arg-type]
            if not cookie_header:
                raise ValueError("No instance-scoped secure cookies captured after login")
            self._browser_cookie_header = cookie_header
            self._browser_cookie_expires_at = time.time() + (
                browser_config.session_ttl_minutes * 60
            )
            self._browser_session_key = instance_host
            self._browser_last_validated_at = time.time()
            self._browser_last_login_at = time.time()
            self._clear_browser_reauth_attempt()
            self._save_session_to_disk()
            # Final validation before closing browser: avoid storing UI-only cookies that
            # still fail API auth and cause immediate 401/reopen loops.
            try:
                final_probe = self._probe_browser_api_with_cookie(
                    self._browser_cookie_header,
                    timeout_seconds=10,
                    browser_config=browser_config,
                )
            except requests.RequestException as exc:
                logger.warning(
                    "Final browser API probe failed after login confirmation; "
                    "keeping session based on browser state: %s",
                    exc,
                )
                final_probe = None
            if final_probe and not _response_indicates_authenticated_session(final_probe):
                self.invalidate_browser_session()
                # Include more detail for debugging auth failures
                probe_url = final_probe.url
                probe_text = final_probe.text[:200]
                raise ValueError(
                    f"Browser login completed, but API auth is still unauthorized. "
                    f"Status: {final_probe.status_code}, URL: {probe_url}, Response: {probe_text}"
                )
            if final_probe and final_probe.status_code in (401, 403):
                logger.info(
                    "Browser login completed and session is authenticated, but probe path is unauthorized: "
                    "status=%s probe_path=%s",
                    final_probe.status_code,
                    browser_config.probe_path,
                )
            logger.info(
                "Browser session stored: session_key=%s cookie_count=%s cookie_names=%s ttl_minutes=%s",
                self._browser_session_key,
                len(_extract_cookie_names(self._browser_cookie_header)),
                ",".join(_extract_cookie_names(self._browser_cookie_header)),
                browser_config.session_ttl_minutes,
            )

            context.close()

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

        # Handle 401 Unauthorized - retry with fresh session for Browser Auth
        if response.status_code == 401 and max_retries > 0:
            if self.config.type == AuthType.BROWSER:
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
                    logger.warning(
                        "Retry within grace period still returned 401. Proceeding to re-auth."
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
                    if waited and self._reload_session_from_disk():
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
                    logger.error(
                        "Failed to re-authenticate after 401: %s. "
                        "The request will be returned as-is with the 401 status.",
                        exc,
                    )
                    return response

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
            else:
                logger.warning(
                    f"Received 401 Unauthorized with {self.config.type.value} auth. "
                    "Check your credentials."
                )

        # Clear session cookie jar to prevent stale cookies leaking across
        # requests.  Browser auth manages cookies explicitly via headers.
        self._http_session.cookies.clear()
        return response
