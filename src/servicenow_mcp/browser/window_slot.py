"""Which debug window this MCP process drives: one window per terminal.

One account used to mean one window, shared by every MCP host on the machine.
That is the right unit for LOOKING at something together, and the wrong one for
testing several users at once: impersonation re-points the window's whole
session, so a requester in one terminal and an approver in another kept taking
the same window away from each other. Two identities at once need two cookie
jars, i.e. two Chromium profiles, i.e. two windows.

So a process leases a window NUMBER the first time it uses the debug window and
keeps it for its lifetime. Window 1 is the pre-existing window (same key, same
profile, so its remembered MFA device survives); window N>1 is ``<key>__wN``
with a profile of its own, signed in once and remembered from then on.

The lease is a file naming the holder's pid and start time. Held means that
process is still running; a dead holder, or a pid that now belongs to a
different process (start time moved), frees it. Claiming runs under the same
O_EXCL claim the launch uses, so two terminals starting together cannot both
take window 2.

Bounded at :data:`MAX_WINDOWS`. With every window held, the process shares
window 1 the way every process did before, and says so — fewer windows than
terminals is a degraded answer, never a refused one.

The window lives as long as its terminal: when the process exits, the window it
leased is closed and the lease released (window.close_windows_of_this_process).
The profile stays, so the next terminal on that number is still signed in.
"""

import json
import logging
import os
import re
import threading
from typing import Dict, List, Optional, Set, Tuple

from ..auth._process import _is_pid_alive
from ._launch_lock import LaunchBusy, launch_claim

logger = logging.getLogger(__name__)

MAX_WINDOWS = 4
_LEASE_PREFIX = "debug_slot_"
_SUFFIX = re.compile(r"__w(\d+)$")
# ps reports start time to the second; a lease written with the same reading
# may differ by rounding only.
_START_TOLERANCE_S = 2.0

_held: Dict[str, int] = {}
_owned: Dict[str, Tuple[str, str]] = {}  # base key -> (root, window key) leased here
_shared: Set[str] = set()
_leases: Set[str] = set()
_guard = threading.Lock()
_my_start: Optional[float] = None


def window_suffix(number: int) -> str:
    """Key suffix for window ``number``. Window 1 keeps the bare key."""
    return "" if number <= 1 else f"__w{number}"


def number_of(key_or_path: str) -> int:
    """The window number a window key (or a path ending in one) carries."""
    found = _SUFFIX.search(os.path.basename(str(key_or_path or "")))
    return int(found.group(1)) if found else 1


def held_number(base_key: str) -> int:
    """The window this process leased for ``base_key``; 1 if it never claimed."""
    return _held.get(base_key, 1)


def is_shared(base_key: str) -> bool:
    """True when every window was held and this process fell back to window 1."""
    return base_key in _shared


def lease_path(root: str, window_key: str) -> str:
    return os.path.join(root, f"{_LEASE_PREFIX}{window_key}.lease")


def _started_at(pid: int) -> Optional[float]:
    from .window import _process_started_at  # window imports this module

    return _process_started_at(pid)


def _own_start() -> Optional[float]:
    global _my_start
    if _my_start is None:
        _my_start = _started_at(os.getpid())
    return _my_start


def _read(path: str) -> Optional[Dict[str, object]]:
    """The lease's contents; {} when present but unreadable; None when absent."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable window lease %s: %s", path, exc)
        return {}


def _holder_is_live(holder: Dict[str, object]) -> bool:
    """Whether the process named in a lease is the one still running.

    Unreadable counts as live: a lease nobody can read is not evidence the
    window is free, and taking it could put two terminals on one window.
    """
    try:
        pid = int(holder.get("pid") or 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    if not _is_pid_alive(pid):
        return False
    recorded = holder.get("started_at")
    if recorded is None:
        return True
    now = _started_at(pid)
    if now is None:
        return True  # could not tell a reused pid from the holder
    try:
        return abs(float(recorded) - now) <= _START_TOLERANCE_S  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True


def _is_mine(holder: Optional[Dict[str, object]]) -> bool:
    return bool(holder) and holder.get("pid") == os.getpid()  # type: ignore[union-attr]


def lease_is_mine(root: str, window_key: str) -> bool:
    return _is_mine(_read(lease_path(root, window_key)))


def owned_windows() -> List[Tuple[str, str]]:
    """(root, window key) for every window this process leased and still holds.

    Read without the claim lock: this runs at exit, possibly from a signal
    handler that interrupted a claim on the same thread.
    """
    return list(_owned.values())


def release(root: str, window_key: str) -> None:
    """Drop this process's lease on a window, if it is still ours."""
    path = lease_path(root, window_key)
    if _is_mine(_read(path)):
        try:
            os.remove(path)
        except OSError as exc:
            logger.debug("Could not release window lease %s: %s", path, exc)
    _leases.discard(path)


def lease_held_elsewhere(root: str, window_key: str) -> bool:
    """True when another running process holds this window. For the reaper."""
    holder = _read(lease_path(root, window_key))
    if holder is None or _is_mine(holder):
        return False
    return _holder_is_live(holder)


def _take(path: str) -> bool:
    holder = _read(path)
    if _is_mine(holder):
        return True
    if holder is not None:
        if _holder_is_live(holder):
            return False
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.debug("Could not clear a stale window lease %s: %s", path, exc)
            return False
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    except OSError as exc:
        logger.debug("Could not write window lease %s: %s", path, exc)
        return False
    with os.fdopen(fd, "w") as handle:
        json.dump({"pid": os.getpid(), "started_at": _own_start()}, handle)
    _leases.add(path)
    return True


def _scan(root: str, base_key: str) -> int:
    for number in range(1, MAX_WINDOWS + 1):
        if _take(lease_path(root, base_key + window_suffix(number))):
            return number
    return 0


def claim(root: str, base_key: str) -> int:
    """Lease a window for this process and return its number. Never raises.

    Cheap after the first call: it only re-reads this process's own lease, and
    claims again if that lease is gone (deleted by hand, or reclaimed after this
    process was mistaken for dead).
    """
    if not os.path.isabs(str(root or "")):
        # No real cache dir to keep a lease in. Writing one relative to the cwd
        # would scatter lease files wherever the server happened to start.
        return held_number(base_key)
    with _guard:
        current = _held.get(base_key)
        if current and base_key not in _shared:
            if _is_mine(_read(lease_path(root, base_key + window_suffix(current)))):
                return current
        try:
            os.makedirs(root, exist_ok=True)
            number = 0
            for _attempt in range(3):
                with launch_claim(os.path.join(root, f"{_LEASE_PREFIX}{base_key}.claim")) as ok:
                    if ok:
                        number = _scan(root, base_key)
                        break
        except (LaunchBusy, OSError) as exc:
            logger.debug("Could not lease a debug window, sharing window 1: %s", exc)
            number = 0
        if number:
            _shared.discard(base_key)
            _owned[base_key] = (root, base_key + window_suffix(number))
        else:
            _shared.add(base_key)
            _owned.pop(base_key, None)
            number = 1
        _held[base_key] = number
        return number


def has_claimed(base_key: str) -> bool:
    """True once this process holds (or shares) a window for ``base_key``."""
    return base_key in _held


def free_numbers(root: str, base_key: str) -> List[int]:
    """Window numbers no running process holds — the ones this process may take."""
    out = []
    for number in range(1, MAX_WINDOWS + 1):
        holder = _read(lease_path(root, base_key + window_suffix(number)))
        if holder is None or _is_mine(holder) or not _holder_is_live(holder):
            out.append(number)
    return out


def claim_number(root: str, base_key: str, number: int) -> str:
    """Lease window ``number`` specifically. Never raises.

    ``"ok"`` — it is this process's window now (any other lease of ours on the
    same account is released, the window itself left open). ``"held"`` — another
    running process holds it. ``"invalid"`` — not a window number.
    ``"unavailable"`` — the lease could not be written.
    """
    if not 1 <= int(number) <= MAX_WINDOWS:
        return "invalid"
    if not os.path.isabs(str(root or "")):
        return "unavailable"
    with _guard:
        target = base_key + window_suffix(number)
        try:
            os.makedirs(root, exist_ok=True)
            with launch_claim(os.path.join(root, f"{_LEASE_PREFIX}{base_key}.claim")) as ok:
                if not ok:
                    return "unavailable"
                if not _take(lease_path(root, target)):
                    holder = _read(lease_path(root, target))
                    return (
                        "held" if holder is not None and _holder_is_live(holder) else "unavailable"
                    )
        except (LaunchBusy, OSError) as exc:
            logger.debug("Could not lease debug window %s: %s", number, exc)
            return "unavailable"
        previous = _owned.get(base_key)
        if previous and previous[1] != target:
            release(*previous)
        _shared.discard(base_key)
        _owned[base_key] = (root, target)
        _held[base_key] = number
        return "ok"


__all__ = [
    "MAX_WINDOWS",
    "claim",
    "claim_number",
    "free_numbers",
    "has_claimed",
    "held_number",
    "is_shared",
    "lease_held_elsewhere",
    "lease_is_mine",
    "lease_path",
    "number_of",
    "owned_windows",
    "release",
    "window_suffix",
]
