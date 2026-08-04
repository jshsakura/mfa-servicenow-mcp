"""Close debug windows nobody is using, so having several stays cheap.

Why reaping rather than fewer windows
-------------------------------------
One window per host+account is not waste, it is the unit a ServiceNow session
comes in — a cookie jar. Impersonating two people at once genuinely needs two
of them, and dev/test/prod genuinely need three. So the answer to "four windows
piled up" is not to merge them; merging would take away something real. The
answer is that nothing ever closed them.

That is what this does, and it is deliberately the only automatic closing in
the server. It runs when a window is about to be opened — the moment the
population is about to grow is exactly the moment there is a reason to look at
it — so there is no daemon and no background timer, the same stance
``_launch_lock`` takes toward stale claims.

The one thing it must never do
------------------------------
Close a window somebody is looking at. That is worse than any number of stray
Chromiums: the entire premise of the feature is "let's look at this together",
and a window that vanishes mid-sentence is indistinguishable from the crash
this repo has already chased once. The lock collector shipped a bug of exactly
this shape (v1.21.17, deleting a live claim) and it was cheap by comparison.

So every condition below is a veto, all of them must agree, and anything that
cannot be established counts as a veto too — an unreadable state file, a probe
too old to answer, a CDP attach that fails. "No evidence" means keep it. The
cost of being wrong in that direction is a browser that stays open one more
launch; the cost in the other direction is somebody's work.

Why last-attach and last-touch have to be read together
-------------------------------------------------------
Neither alone separates a person from the model. The probe's ``lastHuman`` is
stamped from trusted input events, but Playwright drives the page through the
CDP Input domain and those events are trusted too, so the model's own clicking
lands in the same field. And ``last_used_at`` only says when a tool attached,
which says nothing about the human.

Together they are unambiguous. The reaper only considers windows no tool has
attached to for ``IDLE_AFTER_S``; across that span the model generated no input
at all, so any ``lastHuman`` inside it must be a person. The overlap where the
two are confusable is, by construction, entirely in the past.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from ._offload import PlaywrightUnavailable, require_playwright, run_off_loop
from .probe import presence_script
from .window import (
    WindowState,
    read_window_state,
    terminate_pid,
    window_liveness,
    window_state_path,
)

logger = logging.getLogger(__name__)

# How long a window must go untouched before it is even a candidate. Generous
# on purpose: the failure this prevents (a pile of browsers) is an annoyance,
# and the failure it could cause (closing a window in use) is not. Half an hour
# is longer than any pause inside one debugging session.
IDLE_AFTER_S = 30 * 60.0

# Attaching to decide is worth a moment, but this runs in front of a window the
# user is waiting for, so it is kept short and a slow window simply survives.
PRESENCE_TIMEOUT_S = 8.0

# ``debug_window_{key}.json`` is the state file; the rest are sidecars that
# happen to match the same glob. Listed rather than pattern-matched so adding a
# sidecar without updating this list fails loudly in tests, not silently in a
# reaper that mistakes it for a window.
_STATE_PREFIX = "debug_window_"
_SIDECAR_SUFFIXES = (".cursor", ".login", ".launches", ".impersonation")


def _cache_root(auth_manager: Any) -> str:
    """The directory the state files live in, derived from a known-good path."""
    return os.path.dirname(window_state_path(auth_manager))


def _key_from_state_path(path: str) -> Optional[str]:
    """The window key a state file belongs to, or None if it is a sidecar."""
    name = os.path.basename(path)
    if not name.startswith(_STATE_PREFIX) or not name.endswith(".json"):
        return None
    key = name[len(_STATE_PREFIX) : -len(".json")]
    if not key or any(key.endswith(suffix) for suffix in _SIDECAR_SUFFIXES):
        return None
    return key


def list_window_keys(auth_manager: Any) -> List[str]:
    """Every window this machine has state for, live or not."""
    root = _cache_root(auth_manager)
    try:
        entries = sorted(os.listdir(root))
    except OSError as exc:
        logger.debug("Cannot list debug-window state in %s: %s", root, exc)
        return []
    return [key for key in (_key_from_state_path(name) for name in entries) if key]


class _StateFile:
    """A window addressed by its files rather than by an auth manager.

    The reaper looks at OTHER configurations' windows, which no auth manager in
    this process can name. It only needs the two paths, so it stands in for one
    where ``window.py`` asks for a manager.
    """

    def __init__(self, root: str, key: str):
        self._root = root
        self.key = key

    def _get_cache_dir(self) -> str:
        return self._root

    def _get_instance_user_suffix(self) -> str:
        return self.key


def _impersonation_is_live(root: str, key: str, state: WindowState) -> bool:
    """True when this exact window is currently pretending to be someone.

    Keyed on ``started_at`` like impersonate.py writes it, so a marker left by a
    window that has since closed never speaks for the one running now. Closing
    such a window would be technically harmless — the session dies with it — but
    a window deliberately parked as another user is the clearest possible signal
    that somebody set it up on purpose.
    """
    path = os.path.join(root, f"{_STATE_PREFIX}{key}.impersonation.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            marker = json.load(handle)
    except FileNotFoundError:
        return False
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable impersonation marker at %s: %s", path, exc)
        return True  # unreadable is not evidence of absence
    if not marker.get("as"):
        return False
    try:
        return abs(float(marker.get("started_at", -1.0)) - float(state.started_at)) < 0.001
    except (TypeError, ValueError):
        return True


def read_presence(state: WindowState) -> Optional[Dict[str, Any]]:
    """Ask the window itself whether anyone is at it. None means no evidence.

    Every tab is polled, not just the instance one: a person reading release
    notes in the second tab of this window is using it, and the reaper has no
    business deciding which tab counts. The newest stamp and any unsaved input
    anywhere in the window both veto.
    """

    def _work() -> Optional[Dict[str, Any]]:
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(state.cdp_endpoint)
            try:
                pages = [page for context in browser.contexts for page in context.pages]
                pages = [p for p in pages if not str(p.url).startswith("devtools://")]
                if not pages:
                    # An open window with no page is nothing to protect, but it
                    # is also nothing to read — report it as answered-and-empty
                    # rather than as no-evidence.
                    return {"idle_ms": None, "dirty": 0, "answered": True}

                # The SMALLEST elapsed time wins: the most recent touch anywhere
                # in the window is what protects it.
                idle_ms: Optional[float] = None
                dirty = 0
                answered = False
                for page in pages:
                    try:
                        reading = page.evaluate(presence_script())
                    except Exception as exc:  # noqa: BLE001 - a page can be mid-navigation
                        logger.debug("Presence read failed on %s: %s", page.url, exc)
                        return None
                    if not reading:
                        continue  # no probe on THIS tab, or one too old to answer
                    answered = True
                    dirty += int(reading.get("dirty") or 0)
                    page_now = float(reading.get("now") or 0.0)
                    last_human = float(reading.get("lastHuman") or 0.0)
                    if last_human <= 0 or page_now <= 0:
                        continue  # nobody has ever touched this tab
                    elapsed = max(0.0, page_now - last_human)
                    idle_ms = elapsed if idle_ms is None else min(idle_ms, elapsed)
                if not answered:
                    return None
                return {"idle_ms": idle_ms, "dirty": dirty, "answered": True}
            finally:
                browser.close()

    try:
        require_playwright()
        return run_off_loop(_work, timeout_s=PRESENCE_TIMEOUT_S)
    except (PlaywrightUnavailable, RuntimeError, TimeoutError, OSError) as exc:
        logger.debug("Could not read presence from %s: %s", state.cdp_endpoint, exc)
        return None


def _should_close(
    root: str,
    key: str,
    state: WindowState,
    *,
    now: float,
    idle_after_s: float,
) -> Tuple[bool, str]:
    """All vetoes, in cheapest-first order. Returns (close?, why)."""
    liveness = window_liveness(state)
    if not liveness.process:
        return False, "not running"
    if now - state.last_used_at < idle_after_s:
        return False, "in use"
    if _impersonation_is_live(root, key, state):
        return False, "impersonating"
    if liveness.pages == 0:
        # The veto above is `reusable`-shaped elsewhere, but here it must not be:
        # a window whose last tab was closed is exactly what should be reaped,
        # and treating it as "not running" would leave it resident forever. There
        # is no unsaved input to protect and no presence to ask — nobody can see
        # it. `pages is None` is not this case and falls through to the read
        # below, which will decline rather than guess.
        return True, "no tabs left"

    presence = read_presence(state)
    if presence is None:
        return False, "could not ask"
    if presence.get("dirty"):
        return False, "unsaved input"
    idle_ms = presence.get("idle_ms")
    if idle_ms is not None and idle_ms < idle_after_s * 1000.0:
        return False, "someone is at it"
    return True, "idle"


def reap_idle_windows(
    auth_manager: Any,
    *,
    idle_after_s: float = IDLE_AFTER_S,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Close every window that is provably unused. Returns what was closed.

    The window belonging to ``auth_manager`` is never a candidate — it is the
    one being asked for. Returning the closures rather than logging them is the
    point: a window that disappears without the answer saying so reads as the
    failure this whole change is about.
    """
    moment = time.time() if now is None else now
    root = _cache_root(auth_manager)
    mine = _key_from_state_path(window_state_path(auth_manager))
    closed: List[Dict[str, Any]] = []

    for key in list_window_keys(auth_manager):
        if key == mine:
            continue
        handle = _StateFile(root, key)
        state = read_window_state(handle)
        if state is None:
            continue
        try:
            close, why = _should_close(root, key, state, now=moment, idle_after_s=idle_after_s)
        except Exception as exc:  # noqa: BLE001 - a decision must never break a launch
            logger.debug("Skipping %s while reaping: %s", key, exc)
            continue
        if not close:
            logger.debug("Keeping debug window %s: %s", key, why)
            continue
        if terminate_pid(state.pid):
            closed.append(
                {
                    "instance": state.instance_host or key,
                    "idle_minutes": int((moment - state.last_used_at) / 60),
                }
            )
        # The state file goes either way: the pid is gone by now, and leaving it
        # would advertise a window that is not there.
        try:
            os.remove(os.path.join(root, f"{_STATE_PREFIX}{key}.json"))
        except OSError as exc:  # pragma: no cover - best effort
            logger.debug("Could not clear state for %s: %s", key, exc)

    return closed


__all__ = [
    "IDLE_AFTER_S",
    "list_window_keys",
    "read_presence",
    "reap_idle_windows",
]
