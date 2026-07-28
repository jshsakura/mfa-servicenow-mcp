"""A hard cap on how often a debug window may be launched.

The window is the one part of this server with a physical side effect: it puts
something on the user's screen. The realistic failure is not a single wrong
call, it is a loop — an LLM that misreads a result and retries, or a Chromium
that dies on startup and gets relaunched every time. Either turns into windows
appearing over and over while the user is trying to work.

Both are stopped here, in deterministic code, rather than by asking the model to
be careful. The same reasoning the repo applies to its write guards: a rule the
LLM has to remember is not a guard.

Two limits, aimed at the two different failures:

``MIN_RELAUNCH_INTERVAL_S``
    A window that vanished seconds after it launched did not get closed by a
    user, it crashed. Relaunching immediately just repeats the crash, so a
    too-soon relaunch is refused and the caller is told to look at the cause.

``MAX_LAUNCHES_PER_WINDOW`` within ``LAUNCH_WINDOW_S``
    A blunt ceiling for everything else. Normal use — open in the morning,
    reopen after closing it a couple of times — stays far below it.
"""

import json
import logging
import os
import time
from typing import List, Tuple

logger = logging.getLogger(__name__)

# A user closing a window and asking for it again takes at least a few seconds;
# anything faster is a crash loop, not a person.
MIN_RELAUNCH_INTERVAL_S = 15.0

MAX_LAUNCHES_PER_WINDOW = 6
LAUNCH_WINDOW_S = 600.0

# Keeps the history file bounded regardless of how long the server runs.
_MAX_RECORDED = 32


class LaunchBudgetExceeded(RuntimeError):
    """Refusing to open another window; something is looping."""


def _read_history(path: str) -> List[float]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable launch history at %s: %s", path, exc)
        return []
    if not isinstance(raw, list):
        return []
    return [float(item) for item in raw if isinstance(item, (int, float))]


def _write_history(path: str, stamps: List[float]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(stamps[-_MAX_RECORDED:], handle)
        os.replace(tmp_path, path)
    except OSError as exc:  # pragma: no cover - history is advisory
        logger.debug("Could not persist launch history: %s", exc)


def recent_launches(path: str, *, now: float, window_s: float = LAUNCH_WINDOW_S) -> List[float]:
    return [stamp for stamp in _read_history(path) if now - stamp <= window_s]


def check_launch_allowed(path: str, *, now: float | None = None) -> None:
    """Raise :class:`LaunchBudgetExceeded` when another launch would be a loop.

    Read-only: callers record the launch separately, so a launch that fails for
    an unrelated reason (Chromium missing) does not consume budget it never used.
    """
    moment = time.time() if now is None else now
    stamps = recent_launches(path, now=moment)
    if not stamps:
        return

    since_last = moment - max(stamps)
    if since_last < MIN_RELAUNCH_INTERVAL_S:
        raise LaunchBudgetExceeded(
            f"A debug window was launched {since_last:.0f}s ago and is already gone. "
            "That is a browser failing at startup, not a window that was closed — "
            f"relaunching is refused for {MIN_RELAUNCH_INTERVAL_S:.0f}s. Check the "
            "Chromium install and the profile directory."
        )

    if len(stamps) >= MAX_LAUNCHES_PER_WINDOW:
        raise LaunchBudgetExceeded(
            f"{len(stamps)} debug windows have been opened in the last "
            f"{LAUNCH_WINDOW_S / 60:.0f} minutes. Refusing another one — something is "
            "reopening in a loop. Use the window that is already open, or wait."
        )


def record_launch(path: str, *, now: float | None = None) -> None:
    moment = time.time() if now is None else now
    _write_history(path, [*_read_history(path), moment])


def budget_status(path: str, *, now: float | None = None) -> Tuple[int, int]:
    """(launches in the current window, allowance) — for reporting, not gating."""
    moment = time.time() if now is None else now
    return len(recent_launches(path, now=moment)), MAX_LAUNCHES_PER_WINDOW


__all__ = [
    "LAUNCH_WINDOW_S",
    "LaunchBudgetExceeded",
    "MAX_LAUNCHES_PER_WINDOW",
    "MIN_RELAUNCH_INTERVAL_S",
    "budget_status",
    "check_launch_allowed",
    "record_launch",
    "recent_launches",
]
