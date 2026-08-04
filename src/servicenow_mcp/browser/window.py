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
    # When a tool last attached. Defaults to ``started_at`` on read, so a state
    # file written before this field existed reads as "untouched since launch"
    # rather than as "idle since 1970" — the difference decides whether the
    # reaper may close it.
    last_used_at: float = 0.0

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
            "last_used_at": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> Optional["WindowState"]:
        try:
            started_at = float(raw.get("started_at", 0.0))
            # Absent, not falsy: a state file written before this field existed
            # falls back to the launch time, while one that genuinely recorded
            # 0.0 round-trips unchanged.
            raw_last = raw.get("last_used_at")
            return cls(
                pid=int(raw["pid"]),
                port=int(raw["port"]),
                profile_dir=str(raw["profile_dir"]),
                instance_url=str(raw.get("instance_url", "")),
                started_at=started_at,
                executable_path=str(raw.get("executable_path", "")),
                last_used_at=(float(raw_last) if raw_last is not None else started_at),
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


def _window_account(auth_manager: Any) -> str:
    """The account this window will sign itself in as, or "".

    Same source and same order as ``login.saved_credentials`` — the window's
    identity is whoever it logs in as, so the key must be read from where the
    login reads it. Two config shapes are accepted because the auth layer holds
    an ``AuthConfig`` while the tool layer holds a ``ServerConfig`` wrapping one.
    """
    config = getattr(auth_manager, "config", None)
    if config is None:
        return ""
    root = getattr(config, "auth", None) or config
    for holder in ("browser", "basic"):
        section = getattr(root, holder, None)
        username = getattr(section, "username", None)
        if username:
            return str(username)
    return ""


def _window_key(auth_manager: Any) -> str:
    """Identity of one window: the instance host plus the account it signs in as.

    Deliberately NOT ``_get_instance_user_suffix``. That helper keys SESSION and
    PROFILE files, and for those the profile label is rightly the identity unit
    (issue #64) — but it also means the key format flips shape depending on
    whether a label is declared: ``{profile}_{host}`` with one, ``{host}_{user}``
    without. Two configs pointed at the same instance as the same person then
    produce two different keys, so neither finds the other's window and a second
    one opens. That is a duplicate, not a second session.

    What actually has to stay separate is a SESSION, and a ServiceNow session is
    a cookie jar: one per host per account. So that is what is keyed here, and a
    profile label — a naming convenience in someone's config — cannot split it.
    Impersonation is unaffected: it re-points a session at another user, so two
    people at once still needs two windows, which host+account still gives.

    Falls back to the suffix helper only when there is no host to key on, which
    in practice means an unconfigured instance URL.
    """
    try:
        raw_url = str(getattr(auth_manager, "instance_url", "") or "")
        host = (urlparse(raw_url).hostname or "").lower()
    except (TypeError, ValueError) as exc:
        logger.debug("Falling back to the suffix helper for the window key: %s", exc)
        host = ""
    if not host:
        return _instance_suffix(auth_manager)
    key = host.replace(".", "_")
    account = _window_account(auth_manager)
    if account:
        # `@` before `.` so alice@corp.com and alice.corp.com stay distinct —
        # the same ordering the auth layer's suffix uses, for the same reason.
        key += f"_{account.replace('@', '_at_').replace('.', '_')}"
    return key


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


def touch_window(auth_manager: Any, state: WindowState) -> WindowState:
    """Record that a tool just attached, and return the updated state.

    This is the model's half of "is anyone using this window?" — the human's
    half is recorded in the page by the probe. Best-effort: failing to write a
    timestamp must never fail the operation that was being performed. The cost
    of a lost stamp is bounded and one-directional — the window looks idler than
    it is, and the reaper's other conditions still have to agree before anything
    closes.
    """
    stamped = replace_state(state, last_used_at=time.time())
    try:
        write_window_state(auth_manager, stamped)
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not stamp the debug-window last-used time: %s", exc)
        return state
    return stamped


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


def _cdp_page_count(port: int, timeout_s: float = _PORT_PROBE_TIMEOUT_S) -> Optional[int]:
    """How many real tabs the window has, or None when it could not be asked.

    ``None`` and ``0`` are deliberately different answers. An unreadable target
    list means the question did not get through; an empty one means the browser
    answered and has nothing open. Collapsing them would put "we could not find
    out" and "there is nothing" in the same bucket, which is the mistake this
    whole check exists to correct.

    ``devtools://`` targets are not tabs, matching ``capture._instance_page`` —
    the inspector counting as a page is how a window with only its own DevTools
    open would look occupied.
    """
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed loopback URL
            f"http://127.0.0.1:{port}/json/list", timeout=timeout_s
        ) as response:
            if not 200 <= response.status < 300:
                return None
            targets = json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(targets, list):
        return None
    return sum(
        1
        for target in targets
        if isinstance(target, dict)
        and target.get("type") == "page"
        and not str(target.get("url") or "").startswith("devtools://")
    )


@dataclass(frozen=True)
class Liveness:
    """What was actually checked about a window, rather than a verdict alone.

    ``pid alive AND port answers`` used to be reported as "this window can be
    reused". It cannot: on macOS, closing the last browser window does not quit
    Chromium. The process stays up, the CDP port keeps answering, and the caller
    is handed a window with nowhere to look — so *closing* the window is what
    creates the broken state, which is why "close it and reopen" does not
    recover. Two signals were read and a third thing was claimed.

    Each field is one signal, and ``pages`` distinguishes "no tabs" from "could
    not ask". A window that cannot answer is not reusable: launching a spare
    window is recoverable, attaching to a dead one is not.
    """

    process: bool  # the recorded pid is alive
    port: bool  # CDP /json/version answered
    pages: Optional[int]  # real tabs; None when the list could not be read

    @property
    def reusable(self) -> bool:
        """True only when every signal came back and covered the question."""
        return self.process and self.port and bool(self.pages)

    @property
    def reason(self) -> str:
        """Why the window is not reusable, in the caller's words."""
        if not self.process:
            return "the recorded process is gone"
        if not self.port:
            return "the debugging port does not answer"
        if self.pages is None:
            return "the window did not report its tabs"
        if self.pages == 0:
            return "the window has no tabs left (it was closed)"
        return f"reusable ({self.pages} tab(s))"


def window_liveness(state: Optional[WindowState]) -> Liveness:
    """Read each liveness signal in cheapest-first order, stopping at the first no."""
    if state is None:
        return Liveness(process=False, port=False, pages=None)
    if not _is_pid_alive(state.pid):
        return Liveness(process=False, port=False, pages=None)
    if not _cdp_responds(state.port):
        return Liveness(process=True, port=False, pages=None)
    return Liveness(process=True, port=True, pages=_cdp_page_count(state.port))


def is_window_alive(state: Optional[WindowState]) -> bool:
    """Can this window be attached to and used? See :class:`Liveness`."""
    return window_liveness(state).reusable


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
        # Belt to mark_profile_clean's braces: even if a crash mark survives,
        # the "restore pages?" bubble must not sit on top of the page the user
        # and the model are looking at together.
        "--hide-crash-restore-bubble",
    ]
    if url:
        args.append(url)
    return args


# What Chromium restores FROM. Modern builds keep numbered files under
# Sessions/; older ones keep these four in Default/. Both are cleared, because a
# profile can carry either after an upgrade.
_LEGACY_SESSION_FILES = ("Current Session", "Current Tabs", "Last Session", "Last Tabs")


def clear_restore_state(profile_dir: str) -> bool:
    """Leave Chromium nothing to restore, so the window opens with ONE tab.

    Measured, twice, on the real profile: close the window with a signal and the
    next launch comes back with the previous tab restored AND the url we passed
    on the command line — two tabs on the same page, then three, growing by one
    per cycle as each restored session is itself saved.

    Marking the previous exit clean is not enough and the reason is visible in
    the profile: ``exit_type`` reads "Crashed" for as long as the browser is
    RUNNING (Chromium writes "Normal" only on a clean exit), so a pre-launch fix
    of that flag is undone a second later. What actually drives the restore is
    ``Default/Sessions/Session_*`` and ``Tabs_*``, so those are what goes.

    This is safe precisely because of what it does NOT touch: cookies live in
    ``Default/Cookies``, so the signed-in session — the thing that makes the
    second open silent — survives untouched. A tool surface should open on the
    page it was asked for and nothing else; a browsing session it is not.

    Returns True when something was actually cleared, for the tests.
    """
    cleared = False
    sessions_dir = os.path.join(profile_dir, "Default", "Sessions")
    try:
        for name in os.listdir(sessions_dir):
            if name.startswith(("Session_", "Tabs_")):
                try:
                    os.remove(os.path.join(sessions_dir, name))
                    cleared = True
                except OSError as exc:  # pragma: no cover - best effort
                    logger.debug("Could not remove session file %s: %s", name, exc)
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not list %s: %s", sessions_dir, exc)

    for name in _LEGACY_SESSION_FILES:
        try:
            os.remove(os.path.join(profile_dir, "Default", name))
            cleared = True
        except FileNotFoundError:
            pass
        except OSError as exc:  # pragma: no cover - best effort
            logger.debug("Could not remove %s: %s", name, exc)

    if _mark_profile_clean(profile_dir):
        cleared = True
    if cleared:
        logger.info("Cleared the debug profile's restore state; the window opens with one tab.")
    return cleared


def _mark_profile_clean(profile_dir: str) -> bool:
    """Clear a stale crash mark, so no "restore pages?" bubble greets the user.

    Secondary to :func:`clear_restore_state` — with no session files left there
    is nothing to restore either way, but a profile that still reads as crashed
    can show the bubble over the page being debugged.
    """
    prefs_path = os.path.join(profile_dir, "Default", "Preferences")
    try:
        with open(prefs_path, "r", encoding="utf-8") as handle:
            prefs = json.load(handle)
    except FileNotFoundError:
        return False  # A profile that has never run has nothing to restore.
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("Could not read Chromium preferences at %s: %s", prefs_path, exc)
        return False

    profile_prefs = prefs.get("profile")
    if not isinstance(profile_prefs, dict):
        return False
    if profile_prefs.get("exit_type") == "Normal" and profile_prefs.get("exited_cleanly", True):
        return False

    profile_prefs["exit_type"] = "Normal"
    profile_prefs["exited_cleanly"] = True
    tmp_path = f"{prefs_path}.{os.getpid()}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(prefs, handle)
        os.replace(tmp_path, prefs_path)
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not clear the Chromium crash mark: %s", exc)
        return False
    return True


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
    # Before the launch, not after: a restored tab exists the moment the window
    # opens, and then something has to guess which of two identical tabs is the
    # one that was asked for.
    clear_restore_state(profile_dir)

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
            now = time.time()
            state = WindowState(
                pid=process.pid,
                port=port,
                profile_dir=profile_dir,
                instance_url=str(getattr(auth_manager, "instance_url", "") or ""),
                started_at=now,
                executable_path=executable,
                last_used_at=now,
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


def terminate_pid(pid: int) -> bool:
    """Ask a window to exit, then insist. False when it was already gone.

    Split out so the reaper closes windows exactly the way stop_window does —
    graceful first, forced only after the grace period. A second closer with
    its own kill policy is how one of them ends up SIGKILLing a browser that
    was still flushing its profile to disk.
    """
    if not _is_pid_alive(pid):
        return False

    _terminate(pid)
    deadline = time.time() + _STOP_GRACE_S
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            return True
        time.sleep(_STOP_POLL_INTERVAL_S)

    _force_terminate(pid)
    return True


def stop_window(auth_manager: Any, *, state: Optional[WindowState] = None) -> bool:
    """Close the shared window. Returns True if a live window was stopped."""
    target = state or read_window_state(auth_manager)
    if target is None:
        return False
    stopped = terminate_pid(target.pid)
    clear_window_state(auth_manager)
    return stopped


def find_window(auth_manager: Any) -> Optional[WindowState]:
    """The live window, or None. NEVER launches.

    This is what read-only callers use. Inspecting must not be able to put a
    window on the user's screen: a read tool that opens windows means one
    appears every time the model wants to check something. Only the tool whose
    stated purpose is opening a window may call :func:`ensure_window`.
    """
    state = read_window_state(auth_manager)
    if not is_window_alive(state):
        return None
    assert state is not None  # is_window_alive rejects None
    # Reading IS using: an inspect every few minutes is a window in active use,
    # and the reaper must see that as clearly as it sees an action.
    return touch_window(auth_manager, state)


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
    if window_liveness(existing).reusable:
        return touch_window(auth_manager, existing), False  # type: ignore[arg-type]

    with launch_claim(window_claim_path(auth_manager)) as claimed:
        # Re-read inside the claim: a peer may have opened one while we waited,
        # and reusing theirs is the whole point of the claim.
        current = read_window_state(auth_manager)
        liveness = window_liveness(current)
        if liveness.reusable:
            return touch_window(auth_manager, current), False  # type: ignore[arg-type]
        if not claimed:
            raise RuntimeError(
                "Another process finished opening the shared debug window but no live "
                "window was found. Try again."
            )
        if current is not None:
            # Stale state from a window the user closed (or a crash). Drop it so
            # a dead pid is never reported as a live session.
            if liveness.process and liveness.pages == 0:
                # A window whose last tab was closed keeps its process and its
                # port alive, so dropping the state file alone would strand it:
                # unreachable, un-reapable, and resident until reboot. Retire it
                # here — but only on a CONFIRMED empty tab list. `pages is None`
                # means the question never got through, and an unread signal is
                # not permission to kill somebody's browser.
                logger.info("Retiring a debug window with no tabs left (pid %s)", current.pid)
                terminate_pid(current.pid)
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
    "Liveness",
    "WindowState",
    "clear_window_state",
    "ensure_window",
    "find_window",
    "is_window_alive",
    "launch_window",
    "clear_restore_state",
    "read_window_state",
    "replace_state",
    "stop_window",
    "terminate_pid",
    "touch_window",
    "window_artifacts_dir",
    "window_claim_path",
    "window_cursor_path",
    "window_history_path",
    "window_impersonation_path",
    "window_login_path",
    "window_liveness",
    "window_profile_dir",
    "window_state_path",
    "write_window_state",
]
