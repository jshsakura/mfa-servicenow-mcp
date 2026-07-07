"""Playwright DOM helpers, login-form selectors, persistent-context launch,
debug-mode detection, and private-directory creation.

Extracted verbatim from auth_manager.py (v1.18.25). auth_manager re-imports
every symbol so its namespace stays byte-identical for callers and tests.
"""

import logging
import os
import time
from typing import Optional

logger = logging.getLogger("servicenow_mcp.auth.auth_manager")


def _is_debug_mode() -> bool:
    """Debug mode: SERVICENOW_BROWSER_DEBUG=1/true keeps the Chromium window open
    even on errors and auto-opens DevTools, so the user can inspect the failing
    401 response, request headers, cookies, and X-UserToken without the auth
    manager auto-closing the window mid-investigation."""
    val = (os.environ.get("SERVICENOW_BROWSER_DEBUG") or "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _ensure_private_dir(path: str, *, chmod_existing: bool) -> None:
    """Create *path* as a private (0700) directory.

    chmod_existing=True is for dirs WE own (default cache dir, profile_* dirs):
    also tighten a pre-existing dir, fixing 0755 modes left by older versions
    or by Playwright's umask. chmod_existing=False is for user-chosen base
    dirs: create private if missing, but never rewrite the mode of an existing
    directory the user may deliberately share.
    """
    os.makedirs(path, mode=0o700, exist_ok=True)
    if not chmod_existing:
        return
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover — e.g. exotic filesystems; not fatal
        pass


_PROFILE_LOCK_HINTS = (
    "singletonlock",
    "profile directory is already",
    "already in use",
    "failed to create /",
    "process already exists",
)

# How long to wait for a sibling process to release the Chromium profile
# before launching on it. Headless cookie probes hold the profile for 2-5s;
# 8s covers a slow probe without stalling a real login noticeably.
_SINGLETON_WAIT_S = 8.0
_SINGLETON_POLL_S = 0.25


def _singleton_holder_pid(user_data_dir: str) -> Optional[int]:
    """PID currently holding the profile's Chromium SingletonLock, else None.

    Chromium writes SingletonLock as a symlink to ``<hostname>-<pid>``. A live
    pid means a sibling MCP process (another tab's probe or login window) has
    the profile open — launching now would make one of the two die within ~2s.
    A dead pid is a stale lock from a crash; Chromium recovers from that on
    its own, so it counts as free.
    """
    lock_path = os.path.join(user_data_dir, "SingletonLock")
    try:
        target = os.readlink(lock_path)
    except OSError:
        return None  # no lock — profile free
    try:
        pid = int(target.rsplit("-", 1)[-1])
    except ValueError:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None  # dead holder — stale lock
    except OSError:
        pass  # e.g. PermissionError: pid exists but isn't ours — still busy
    return pid


def _wait_for_profile_singleton(user_data_dir: str) -> None:
    """Poll until the profile's SingletonLock clears or the wait budget ends."""
    holder = _singleton_holder_pid(user_data_dir)
    if holder is None:
        return
    logger.info(
        "Chromium profile is held by PID %s (a sibling MCP process is probing "
        "or logging in) — waiting up to %.0fs for it to release before launching.",
        holder,
        _SINGLETON_WAIT_S,
    )
    deadline = time.time() + _SINGLETON_WAIT_S
    while time.time() < deadline:
        time.sleep(_SINGLETON_POLL_S)
        if _singleton_holder_pid(user_data_dir) is None:
            return
    logger.info(
        "Profile still held after %.0fs — launching anyway (retry logic below "
        "handles a residual lock).",
        _SINGLETON_WAIT_S,
    )


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

    # A sibling tab (possibly an older-version server without the probe lock)
    # may hold the profile right now — wait briefly instead of racing it.
    _wait_for_profile_singleton(user_data_dir)

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
