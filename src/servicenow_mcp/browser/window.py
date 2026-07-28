"""Lifecycle of the shared debug window (a detached Chromium + CDP port).

The window is launched as a plain OS process rather than a Playwright-managed
browser so it outlives the tool call that opened it. State (pid + port +
profile) lives in a small JSON file keyed by instance and user, mirroring how
the auth layer keys its session files — so a dev window and a test window never
collide with each other, nor with the login profile.

The window signs in on its own (see session.py); nothing about the API's
session is copied into it.
"""

import json
import logging
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from ..auth._browser_dom import _singleton_holder_pid
from ..auth._process import _is_pid_alive
from ._launch_lock import launch_claim
from ._offload import require_playwright, run_off_loop
from .launch_budget import check_launch_allowed, record_launch

logger = logging.getLogger(__name__)

# The debug window is ALWAYS visible, whatever SERVICENOW_BROWSER_HEADLESS says.
# That setting governs the *login* browser — a background mechanism nobody needs
# to watch. This window exists for the opposite reason: "let's look at it
# together". A headless shared screen is a contradiction, so the setting is
# deliberately not consulted here. Pinned by tests/test_debug_window.py.
DEBUG_WINDOW_ALWAYS_HEADED = True

# Chromium needs a moment to bind the debugging port. Polling beats a fixed
# sleep: a warm profile answers in ~300ms, a cold one can take several seconds.
_PORT_READY_TIMEOUT_S = 30.0
_PORT_POLL_INTERVAL_S = 0.25
_PORT_PROBE_TIMEOUT_S = 1.0

# Graceful shutdown before escalating to a forced kill.
_STOP_GRACE_S = 5.0
_STOP_POLL_INTERVAL_S = 0.2

DEFAULT_VIEWPORT = (1440, 900)


@dataclass(frozen=True)
class WindowState:
    """Where the shared window is and how to reach it. Immutable by contract."""

    pid: int
    port: int
    profile_dir: str
    instance_url: str
    started_at: float
    executable_path: str = ""

    @property
    def cdp_endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def instance_host(self) -> str:
        return (urlparse(self.instance_url).hostname or "").lower()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pid": self.pid,
            "port": self.port,
            "profile_dir": self.profile_dir,
            "instance_url": self.instance_url,
            "started_at": self.started_at,
            "executable_path": self.executable_path,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> Optional["WindowState"]:
        try:
            return cls(
                pid=int(raw["pid"]),
                port=int(raw["port"]),
                profile_dir=str(raw["profile_dir"]),
                instance_url=str(raw.get("instance_url", "")),
                started_at=float(raw.get("started_at", 0.0)),
                executable_path=str(raw.get("executable_path", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("Ignoring malformed debug-window state: %s", exc)
            return None


def replace_state(state: WindowState, **changes: Any) -> WindowState:
    """Immutable update helper — never mutate a WindowState in place."""
    return replace(state, **changes)


# ---------------------------------------------------------------------------
# Paths — mirror the auth layer's instance+user scoping, plus session mode
# ---------------------------------------------------------------------------


def _cache_root(auth_manager: Any) -> str:
    """Reuse the auth layer's cache root so debug state sits beside session state.

    Read-only use of a frozen class's helper: we call it, we never change it.
    Falls back to the documented default if the helper ever moves.
    """
    getter = getattr(auth_manager, "_get_cache_dir", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception as exc:  # noqa: BLE001 - never fail on a path lookup
            logger.debug("Falling back to default cache dir: %s", exc)
    return str(Path.home() / ".mfa_servicenow_mcp")


def _instance_suffix(auth_manager: Any) -> str:
    """Instance+user key. The same helper the session/profile files use."""
    getter = getattr(auth_manager, "_get_instance_user_suffix", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception as exc:  # noqa: BLE001
            logger.debug("Falling back to host-only debug-window key: %s", exc)
    host = urlparse(getattr(auth_manager, "instance_url", "") or "").hostname or "default"
    return host.replace(".", "_")


def _window_key(auth_manager: Any) -> str:
    """Identity of one window: which configured instance+user opened it.

    Note this keys the *config*, not the person signed into the window — the
    window has its own session and may well be impersonating someone else.
    """
    return _instance_suffix(auth_manager)


def window_state_path(auth_manager: Any) -> str:
    return os.path.join(_cache_root(auth_manager), f"debug_window_{_window_key(auth_manager)}.json")


def window_claim_path(auth_manager: Any) -> str:
    return os.path.join(
        _cache_root(auth_manager), f"debug_window_{_window_key(auth_manager)}.claim"
    )


def window_history_path(auth_manager: Any) -> str:
    """Launch timestamps, for the rate cap in launch_budget.py."""
    return os.path.join(
        _cache_root(auth_manager), f"debug_window_{_window_key(auth_manager)}.launches.json"
    )


def window_cursor_path(auth_manager: Any) -> str:
    """High-water mark of already-reported events (see cursor.py)."""
    return os.path.join(
        _cache_root(auth_manager), f"debug_window_{_window_key(auth_manager)}.cursor.json"
    )


def window_login_path(auth_manager: Any) -> str:
    """Records that this window already spent its one auto-login attempt.

    Keyed by window, not by instance — see login.py for why a second attempt is
    a lockout risk rather than a second chance.
    """
    return os.path.join(
        _cache_root(auth_manager), f"debug_window_{_window_key(auth_manager)}.login.json"
    )


def window_impersonation_path(auth_manager: Any) -> str:
    """Who this window is impersonating, and who it was before.

    On disk rather than in memory because one window is shared by every MCP
    session pointed at this instance: the session that ends an impersonation is
    routinely not the one that started it. Keyed to the window's ``started_at``
    inside the file (see impersonate.py), so a closed window leaves nothing that
    could describe the next one.
    """
    return os.path.join(
        _cache_root(auth_manager),
        f"debug_window_{_window_key(auth_manager)}.impersonation.json",
    )


def window_artifacts_dir(auth_manager: Any) -> str:
    """Where full event dumps and screenshots land — on disk, never in context."""
    return os.path.join(_cache_root(auth_manager), f"debug_artifacts_{_window_key(auth_manager)}")


def window_profile_dir(auth_manager: Any) -> str:
    """Profile dir for the debug window — deliberately NOT the login profile.

    Chromium allows one process per profile directory (SingletonLock). If the
    shared window used the login profile it would hold that lock for as long as
    it stayed open, and every later login or probe would wait 8s and then fail.
    See auth/_browser_dom.py::_wait_for_profile_singleton.
    """
    return os.path.join(_cache_root(auth_manager), f"debug_profile_{_window_key(auth_manager)}")


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


def read_window_state(auth_manager: Any) -> Optional[WindowState]:
    path = window_state_path(auth_manager)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return WindowState.from_dict(json.load(handle))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable debug-window state at %s: %s", path, exc)
        return None


def write_window_state(auth_manager: Any, state: WindowState) -> None:
    path = window_state_path(auth_manager)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(state.to_dict(), handle)
    os.replace(tmp_path, path)


def clear_window_state(auth_manager: Any) -> None:
    try:
        os.remove(window_state_path(auth_manager))
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not clear debug-window state: %s", exc)


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


def _cdp_responds(port: int, timeout_s: float = _PORT_PROBE_TIMEOUT_S) -> bool:
    """True when the CDP HTTP endpoint answers — the real readiness signal.

    A live pid is not enough: Chromium runs for a while before it binds the
    debugging port, and attaching too early fails with a bare connection error.
    Requiring both also defends against pid reuse — an unrelated process that
    inherits the recorded pid will not be serving DevTools on that exact port.
    """
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback URL
            f"http://127.0.0.1:{port}/json/version", timeout=timeout_s
        ) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def is_window_alive(state: Optional[WindowState]) -> bool:
    if state is None:
        return False
    return _is_pid_alive(state.pid) and _cdp_responds(state.port)


# ---------------------------------------------------------------------------
# Launch / stop
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Ask the OS for an unused loopback port.

    There is a small window between closing this socket and Chromium binding
    it. Losing that race surfaces as a failed readiness poll with a clear
    message rather than a silent half-start, which is good enough here.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _chromium_executable() -> str:
    """Path to the Chromium binary Playwright manages, without launching it."""
    require_playwright()

    def _resolve() -> str:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            return str(pw.chromium.executable_path)

    return run_off_loop(_resolve, timeout_s=60.0)


def _launch_args(*, port: int, profile_dir: str, viewport: Tuple[int, int], url: str) -> list[str]:
    width, height = viewport
    args = [
        # Chromium binds this to loopback only. Still: anything running as this
        # user on this machine can drive the window while it is open, so it is
        # closed as soon as the user closes the window.
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
        # Chromium 111+ rejects CDP websockets carrying a non-null Origin.
        # Playwright sends none, but hosts that proxy through a local page do.
        "--remote-allow-origins=http://127.0.0.1",
    ]
    if url:
        args.append(url)
    return args


def _orphan_window_pid(profile_dir: str) -> Optional[int]:
    """A live Chromium holding our profile that we have no port for.

    Happens when the state file is lost (cache cleared, upgrade) while the
    window is still open. Relaunching into that profile would not create a
    second window — Chromium hands off to the running process and exits — so
    the readiness poll would fail with a confusing timeout. Detecting it lets
    us say what actually happened.
    """
    return _singleton_holder_pid(profile_dir)


def launch_window(
    auth_manager: Any,
    *,
    url: str = "",
    viewport: Tuple[int, int] = DEFAULT_VIEWPORT,
) -> WindowState:
    """Start a visible Chromium with a CDP port and return its state.

    Always headed — see DEBUG_WINDOW_ALWAYS_HEADED.
    """
    executable = _chromium_executable()
    profile_dir = window_profile_dir(auth_manager)
    os.makedirs(profile_dir, mode=0o700, exist_ok=True)

    orphan = _orphan_window_pid(profile_dir)
    if orphan is not None:
        raise RuntimeError(
            f"A debug window for this instance is already open (pid {orphan}) but this "
            "server lost track of its debugging port. Close that window and try again."
        )

    port = _free_port()
    args = _launch_args(port=port, profile_dir=profile_dir, viewport=viewport, url=url)

    logger.info("Launching shared debug window on CDP port %s (profile=%s)", port, profile_dir)
    process = subprocess.Popen(  # noqa: S603 - executable path comes from Playwright
        [executable, *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(sys.platform != "win32"),
    )

    deadline = time.time() + _PORT_READY_TIMEOUT_S
    while time.time() < deadline:
        if _cdp_responds(port):
            state = WindowState(
                pid=process.pid,
                port=port,
                profile_dir=profile_dir,
                instance_url=str(getattr(auth_manager, "instance_url", "") or ""),
                started_at=time.time(),
                executable_path=executable,
            )
            write_window_state(auth_manager, state)
            return state
        if process.poll() is not None:
            raise RuntimeError(
                f"The debug browser exited immediately (code {process.returncode}). "
                f"Check that the profile directory is writable: {profile_dir}"
            )
        time.sleep(_PORT_POLL_INTERVAL_S)

    _terminate(process.pid)
    raise TimeoutError(
        f"The debug browser did not open its debugging port within "
        f"{_PORT_READY_TIMEOUT_S:.0f}s (port {port})."
    )


def _terminate(pid: int) -> None:
    """Ask a pid to exit. Never uses os.kill on Windows.

    On Windows os.kill maps every signal other than CTRL_C/CTRL_BREAK to an
    unconditional TerminateProcess — the same trap auth/_process.py documents
    for liveness checks. taskkill without /F asks politely first.
    """
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603,S607 - fixed argv, no shell
            ["taskkill", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    import signal

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        logger.debug("Could not signal debug window pid %s: %s", pid, exc)


def _force_terminate(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603,S607
            ["taskkill", "/PID", str(pid), "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    import signal

    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        logger.debug("Could not force-kill debug window pid %s: %s", pid, exc)


def stop_window(auth_manager: Any, *, state: Optional[WindowState] = None) -> bool:
    """Close the shared window. Returns True if a live window was stopped."""
    target = state or read_window_state(auth_manager)
    if target is None:
        return False
    if not _is_pid_alive(target.pid):
        clear_window_state(auth_manager)
        return False

    _terminate(target.pid)
    deadline = time.time() + _STOP_GRACE_S
    while time.time() < deadline:
        if not _is_pid_alive(target.pid):
            clear_window_state(auth_manager)
            return True
        time.sleep(_STOP_POLL_INTERVAL_S)

    _force_terminate(target.pid)
    clear_window_state(auth_manager)
    return True


def find_window(auth_manager: Any) -> Optional[WindowState]:
    """The live window, or None. NEVER launches.

    This is what read-only callers use. Inspecting must not be able to put a
    window on the user's screen: a read tool that opens windows means one
    appears every time the model wants to check something. Only the tool whose
    stated purpose is opening a window may call :func:`ensure_window`.
    """
    state = read_window_state(auth_manager)
    return state if is_window_alive(state) else None


def ensure_window(
    auth_manager: Any,
    *,
    url: str = "",
    viewport: Tuple[int, int] = DEFAULT_VIEWPORT,
) -> Tuple[WindowState, bool]:
    """Return a live window, reusing the existing one when possible.

    The second element is True when a new window was opened, so callers can
    tell the user whether a window just appeared on their screen. Reuse is the
    common path — calling this repeatedly is idempotent and does not multiply
    windows.

    The launch runs under a cross-process claim (several MCP hosts commonly run
    against one instance) and against a launch-rate cap (see launch_budget.py).
    """
    existing = read_window_state(auth_manager)
    if is_window_alive(existing):
        return existing, False  # type: ignore[return-value]

    with launch_claim(window_claim_path(auth_manager)) as claimed:
        # Re-read inside the claim: a peer may have opened one while we waited,
        # and reusing theirs is the whole point of the claim.
        current = read_window_state(auth_manager)
        if is_window_alive(current):
            return current, False  # type: ignore[return-value]
        if not claimed:
            raise RuntimeError(
                "Another process finished opening the shared debug window but no live "
                "window was found. Try again."
            )
        if current is not None:
            # Stale state from a window the user closed (or a crash). Drop it so
            # a dead pid is never reported as a live session.
            clear_window_state(auth_manager)

        history_path = window_history_path(auth_manager)
        check_launch_allowed(history_path)
        state = launch_window(auth_manager, url=url, viewport=viewport)
        # Recorded only after a launch actually succeeded, so a failure for an
        # unrelated reason (missing Chromium) does not burn the budget.
        record_launch(history_path)
        return state, True


__all__ = [
    "DEBUG_WINDOW_ALWAYS_HEADED",
    "DEFAULT_VIEWPORT",
    "WindowState",
    "clear_window_state",
    "ensure_window",
    "find_window",
    "is_window_alive",
    "launch_window",
    "read_window_state",
    "replace_state",
    "stop_window",
    "window_artifacts_dir",
    "window_claim_path",
    "window_cursor_path",
    "window_history_path",
    "window_impersonation_path",
    "window_login_path",
    "window_profile_dir",
    "window_state_path",
    "write_window_state",
]
