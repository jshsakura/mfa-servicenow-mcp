"""Background server-session keep-alive for browser auth.

ServiceNow's session inactivity timeout is sliding — only authenticated
requests reset it. 2026-07-05 field logs: with work spread across several
Claude sessions and three instances, every idle gap longer than the server
timeout killed the session server-side, and each comeback paid a full
browser login — 53 login starts / 25 manual MFA entries in one day. While an
MCP process is alive it can keep the session warm with a cheap authenticated
GET (the same probe the restore path uses), so the next tool call — in ANY
process sharing the session cache — reuses the live session instead of
re-opening a browser window.

Policy guarantees (pinned by tests/test_session_keepalive.py):

- NEVER opens a browser window or triggers a login. On a rejected ping it
  logs and truly pauses — no further pings until the next real tool call
  (which owns recovery via the normal self-heal path) or a sibling-session
  adoption from disk; a dead session is never re-probed on the interval.
- Before each ping it adopts a sibling process's rotated/re-authed session
  from disk, so a shared session cache stays warm from whichever process is
  live — never pings a stale in-memory cookie.
- Only pings while there was real tool activity within the idle horizon
  (default 6 h) — an abandoned workstation must not hold a server session
  open indefinitely.
- Opt-out with SERVICENOW_SESSION_KEEPALIVE=off; cadence tunable via
  SERVICENOW_SESSION_KEEPALIVE_INTERVAL_S (default 300 s, min 60 s).
- Skips the ping entirely when foreground traffic validated the session
  recently — no redundant round-trips during active use.
"""

import logging
import os
import threading
import time
import weakref
from typing import Optional

from ._response_predicates import _response_confirms_browser_probe_session

logger = logging.getLogger(__name__)

_ENV_TOGGLE = "SERVICENOW_SESSION_KEEPALIVE"
_ENV_INTERVAL = "SERVICENOW_SESSION_KEEPALIVE_INTERVAL_S"
_ENV_MAX_IDLE = "SERVICENOW_SESSION_KEEPALIVE_MAX_IDLE_S"

_DEFAULT_INTERVAL_S = 300.0  # 5 min — well under any sane server idle timeout
_MIN_INTERVAL_S = 60.0
_DEFAULT_MAX_IDLE_S = 6 * 3600.0  # stop extending after 6 h without real work


def _keepalive_enabled() -> bool:
    """Default ON. Only an explicit off-ish value disables."""
    return os.getenv(_ENV_TOGGLE, "").strip().lower() not in ("off", "false", "0", "no")


def _keepalive_interval_s() -> float:
    try:
        value = float(os.getenv(_ENV_INTERVAL, "") or _DEFAULT_INTERVAL_S)
    except ValueError:
        value = _DEFAULT_INTERVAL_S
    return max(value, _MIN_INTERVAL_S)


def _keepalive_max_idle_s() -> float:
    try:
        return float(os.getenv(_ENV_MAX_IDLE, "") or _DEFAULT_MAX_IDLE_S)
    except ValueError:
        return _DEFAULT_MAX_IDLE_S


class SessionKeepalive:
    """One background daemon thread per AuthManager, started lazily on the
    first proven-valid response and idle-gated by real tool activity."""

    def __init__(self, manager) -> None:
        # Weakref so the thread never pins a discarded AuthManager alive.
        self._manager_ref = weakref.ref(manager)
        self._thread: Optional[threading.Thread] = None
        self._thread_lock = threading.Lock()
        self._stop = threading.Event()
        self._last_activity_at: float = 0.0
        # Set to the activity watermark at which a probe was REJECTED. While it
        # equals _last_activity_at (no new real tool call since), the session is
        # known dead and we stop re-probing it — a dead session only recovers on
        # a real call's self-heal, so spaced 401s would be pure waste (and a
        # 401-storm risk on lockout-monitoring instances). None = not suppressed.
        self._dead_since_activity: Optional[float] = None

    def record_activity(self) -> None:
        """Called (indirectly) from the request path on every authenticated
        200. Keepalive pings deliberately do NOT route here — they must not
        refresh their own idle horizon."""
        self._last_activity_at = time.time()

    def ensure_started(self) -> None:
        if not _keepalive_enabled():
            return
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            # Clear a prior stop() so a restarted thread doesn't exit on its
            # first wait() — otherwise stop() would permanently kill keepalive.
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="sn-session-keepalive",
                daemon=True,
            )
            self._thread.start()
            logger.debug(
                "Session keepalive started: interval=%.0fs max_idle=%.0fs",
                _keepalive_interval_s(),
                _keepalive_max_idle_s(),
            )

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(_keepalive_interval_s()):
            try:
                if not self._tick():
                    return
            except Exception as exc:  # noqa: BLE001 — background thread must never raise
                logger.debug("Session keepalive tick failed: %s", exc)

    def _tick(self) -> bool:
        """One keep-alive evaluation. Returns False to end the thread."""
        manager = self._manager_ref()
        if manager is None:
            return False
        if not _keepalive_enabled():
            return True
        browser_config = getattr(manager.config, "browser", None)
        if browser_config is None:
            return True
        # Adopt a sibling process's rotated/re-authed session from disk BEFORE
        # probing — otherwise, in the multi-process setup this feature targets,
        # we'd ping a stale in-memory cookie and 401 forever while a live
        # session sits on disk (the normal request path adopts in get_headers).
        # A fresh adoption also clears a prior dead-session suppression: the new
        # session deserves a probe.
        try:
            if manager._maybe_adopt_sibling_session_update():
                self._dead_since_activity = None
        except Exception as exc:  # noqa: BLE001
            logger.debug("Session keepalive sibling-adoption check failed (ignored): %s", exc)
        if not manager._browser_cookie_header:
            return True
        now = time.time()
        if (now - self._last_activity_at) > _keepalive_max_idle_s():
            return True  # user walked away — let the server session lapse
        # Known dead since the last real activity, and no new tool call has run
        # (which would have self-healed) — don't re-probe a corpse.
        if self._dead_since_activity is not None and self._dead_since_activity == (
            self._last_activity_at
        ):
            return True
        last_validated = manager._browser_last_validated_at
        if last_validated and (now - last_validated) < _keepalive_interval_s() * 0.5:
            return True  # foreground traffic is already keeping it alive
        try:
            response = manager._probe_browser_api_with_cookie(
                manager._browser_cookie_header,
                timeout_seconds=min(int(browser_config.timeout_seconds), 15),
                browser_config=browser_config,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Session keepalive probe errored (ignored): %s", exc)
            return True
        if _response_confirms_browser_probe_session(response):
            # from_keepalive=True: slide the TTL but do NOT touch the
            # activity clock — otherwise keepalive feeds itself forever.
            manager._mark_browser_session_recently_valid(from_keepalive=True)
            self._dead_since_activity = None
            logger.debug("Session keepalive ping OK (status=%s)", response.status_code)
        else:
            # Session died server-side. Suppress further pings until the next
            # real tool call (which owns self-heal / re-login) or a sibling
            # session adoption — re-probing a dead session every interval is
            # pure waste and risks a 401-storm on lockout-monitoring instances.
            # NEVER open a browser here: that would pop MFA windows unprompted.
            self._dead_since_activity = self._last_activity_at
            logger.info(
                "Session keepalive rejected (status=%s) — pausing pings until the "
                "next tool call re-authenticates via the normal flow.",
                getattr(response, "status_code", "?"),
            )
        return True
