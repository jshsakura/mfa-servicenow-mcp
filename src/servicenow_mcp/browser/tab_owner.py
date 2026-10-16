"""Which tab in the shared window belongs to THIS MCP session.

The problem
-----------
One window is shared on purpose ("let's look at this together"), and every
instance in it is a tab. What was never shared on purpose is a single tab
between several MCP hosts. All four entry points — inspect, act, navigate, arm —
choose a page with ``capture._active_instance_page``, whose rule is "the tab on
this instance with the newest ``lastHuman`` stamp". That function's own
docstring records why the rule cannot separate callers:

    Playwright drives the page through the CDP Input domain and those events
    are trusted too, so the model's own clicking lands in the same field.

So terminal A's clicks make A's tab the newest-touched tab, and terminal B —
asking the same question of the same window with no way to name itself — is
handed A's page. There was no lock and nothing was ever "held": B read and drove
A's tab silently, and when A had typed into a form, B's navigate came back
``blocked_by_unsaved_input`` and looked like a window it was locked out of.

The pin
-------
A tab already has a durable identity: the probe mints ``tabId`` into that tab's
sessionStorage (probe.py), and cursor.py already keys its per-tab marks by it.
The one thing missing was an identity for the CALLER, and this supplies it.

Identity is the PROCESS, not anything the model passes in. Each terminal runs
its own MCP server process, so ``OWNER_ID`` separates them for free, and the
repo's standing rule applies — a mechanism the LLM has to remember to pass along
is not a mechanism. It is deliberately not the pid alone: pids are recycled, and
an inherited pid would let a fresh process adopt a stranger's tab. The pid is
recorded ALONGSIDE the identity, and used for one thing only — collecting
entries whose process is gone. Collecting is allowed to be wrong in the safe
direction (a kept entry costs one map slot); adopting would not be.

A pin is a PREFERENCE, never a claim on the tab. Nothing here stops the person
at the keyboard, or another session, from using that tab — the window is shared
and that is the point. All a pin says is "when several tabs would do, this is
the one I was working in".

Scoped per instance host, because one window holds several instances and a
session that works in dev and test wants a tab in each.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from ..auth._process import _is_pid_alive

logger = logging.getLogger(__name__)

# This process, for as long as it runs. A restart deliberately starts over: the
# terminal that owned the tab is gone, and inheriting its tab would be guessing.
OWNER_ID = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"

# Bounded like cursor.py's map, and for the same reason: this is an optimization
# whose worst failure is one re-pick. Entries are dropped oldest-written first.
MAX_TRACKED_PINS = 32

# Another session counts as BUSY on an instance only if it called within this
# long. A live process used to be enough, and a terminal idle for twenty hours
# then held the window: every identity switch stopped to ask the user about a
# session nobody was in, and its pinned tab stayed off limits. Every tool call
# refreshes `used_at` (touch). Measured on real logs: between consecutive
# debug-window calls p95 is 32s and only 1% of gaps exceed 3 min, so a session
# that is working almost never reads as idle. An entry with no readable time
# stays busy: an unknown last call is not proof that nobody is there.
BUSY_WITHIN_S = 3 * 60.0


def _read(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable debug-window tab pins at %s: %s", path, exc)
        return {}
    pins = raw.get("pins") if isinstance(raw, dict) else None
    return pins if isinstance(pins, dict) else {}


def _key(instance_host: str) -> str:
    return f"{OWNER_ID}|{instance_host}"


def read_pin(path: str, instance_host: str) -> str:
    """The tab id this session was last working in on ``instance_host``, or "".

    "" covers every way the question can go unanswered — no file, no entry,
    unreadable JSON. They mean the same thing to the caller (pick a tab the
    normal way) and none of them is a statement about which tab is right.
    """
    entry = _read(path).get(_key(instance_host))
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("tab_id") or "")


def write_pin(path: str, instance_host: str, tab_id: str) -> None:
    """Record ``tab_id`` as this session's tab on ``instance_host``.

    Best effort throughout: a pin that fails to persist costs one re-pick on the
    next call, so it must never be able to fail the operation it accompanies.
    """
    if not tab_id:
        return
    pins = _read(path)

    # Collect entries whose process is gone before adding one. A recycled pid
    # can keep a dead session's entry alive here, which is harmless — the entry
    # is only ever read back under its own OWNER_ID, and that is not recycled.
    for key in [k for k, v in pins.items() if not _owner_alive(v)]:
        pins.pop(key, None)

    # Move-to-end so insertion order is recency order, then evict from the
    # front — the same shape (and the same past bug) as cursor.py: ranking by
    # anything other than write order evicts the entry that was just made.
    pins.pop(_key(instance_host), None)
    now = time.time()
    pins[_key(instance_host)] = {"tab_id": tab_id, "pid": os.getpid(), "at": now, "used_at": now}
    while len(pins) > MAX_TRACKED_PINS:
        pins.pop(next(iter(pins)))
    _write(path, pins)


def _write(path: str, pins: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"pins": pins}, handle)
        os.replace(tmp_path, path)
    except OSError as exc:  # pragma: no cover - a pin is an optimization
        logger.debug("Could not persist a debug-window tab pin: %s", exc)


# ---------------------------------------------------------------------------
# Presence — who else is using this instance in the window, and how recently
# ---------------------------------------------------------------------------


def touch(path: str, instance_host: str) -> None:
    """Record that this session just used ``instance_host`` in the window.

    Written on every tool call, pinned or not: a session that only ever read
    the one tab someone else opened has no pin, and without this it would be
    invisible to the check below — the one session a switch would surprise.
    Presence names no tab, so it never claims one (``claimed_by_others``
    skips entries without a ``tab_id``).
    """
    if not path or not instance_host:
        return
    pins = _read(path)
    entry = pins.get(_key(instance_host))
    entry = dict(entry) if isinstance(entry, dict) else {"tab_id": ""}
    entry.update({"pid": os.getpid(), "used_at": time.time()})
    pins[_key(instance_host)] = entry
    while len(pins) > MAX_TRACKED_PINS:
        pins.pop(next(iter(pins)))
    _write(path, pins)


def _last_used_s(entry: Dict[str, Any], now: float) -> Optional[int]:
    last: Any = entry.get("used_at") or entry.get("at")
    if last is None:
        return None
    try:
        return max(0, int(now - float(last)))
    except (TypeError, ValueError):
        return None


def _busy(last_used_s: Optional[int]) -> bool:
    return last_used_s is None or last_used_s <= BUSY_WITHIN_S


def others_on(path: str, instance_host: str) -> List[Dict[str, Any]]:
    """Other MCP sessions whose process is still running and that have used
    ``instance_host`` in this window.

    A running process is not a busy one — an idle terminal keeps its entry — so
    each carries how long ago it last called and whether that is recent enough
    to count as busy (``BUSY_WITHIN_S``). An entry whose pid cannot be read
    counts as running, for the reason ``claimed_by_others`` gives.
    """
    now = time.time()
    found: List[Dict[str, Any]] = []
    for key, entry in _read(path).items():
        if key == _key(instance_host) or not isinstance(entry, dict):
            continue
        if not key.endswith(f"|{instance_host}") or not _owner_alive(entry):
            continue
        last_used_s = _last_used_s(entry, now)
        found.append(
            {"pid": entry.get("pid"), "last_used_s": last_used_s, "busy": _busy(last_used_s)}
        )
    return found


def idle_others(path: str, instance_host: str) -> List[Dict[str, Any]]:
    """Running sessions on ``instance_host`` that have not called in
    ``BUSY_WITHIN_S`` — the ones a session-wide change goes ahead over, and
    names in its result so the takeover is never silent."""
    if not path or not instance_host:
        return []
    return [other for other in others_on(path, instance_host) if not other["busy"]]


def shared_window_refusal(
    path: str, instance_host: str, what: str, *, acknowledged: bool
) -> Optional[Dict[str, Any]]:
    """Stop a session-wide change while another session is on the same instance.

    The limit, stated rather than engineered around: one window has ONE cookie
    jar per instance, so it holds one identity per instance at a time. Two
    sessions on the same instance share whoever the window is; different
    instances (dev and test) never touch each other. This does not pretend to
    isolate anything — it makes the collision a decision instead of a surprise,
    and hands the model what it needs to make it: who, and how recently.
    """
    if acknowledged or not path or not instance_host:
        return None
    # Only a session that is actually working stops the change. An idle one is
    # gone over without asking; the caller reports it (idle_others).
    others = [other for other in others_on(path, instance_host) if other["busy"]]
    if not others:
        return None
    seen = ", ".join(
        f"pid {o['pid']}, last call "
        + (f"{o['last_used_s']}s ago" if o["last_used_s"] is not None else "time unknown")
        for o in others
    )
    return {
        "success": False,
        "limit": "one_identity_per_instance",
        "other_sessions": others,
        "error": (
            f"LIMIT, not a fault: the debug window holds one identity per instance at a "
            f"time, and {len(others)} other running MCP session(s) have used {instance_host} "
            f"in it within the last {int(BUSY_WITHIN_S // 60)} minutes ({seen}). {what} "
            f"applies to every tab on {instance_host}, theirs included. Either wait for "
            "that session to finish, or ask the user whether disrupting it is fine and "
            "retry with shared_window_ack=true. Other instances in the window are not "
            "affected."
        ),
    }


def claimed_by_others(path: str, instance_host: str) -> set:
    """Tab ids on ``instance_host`` pinned by OTHER sessions that are still running.

    This is what keeps the fix from costing everyone else a tab. "I have no pin"
    is not on its own a reason to open a new tab — a single terminal, which is
    the ordinary case, would then open one on every navigate and the window
    would fill up with pages nobody asked for. The reason to step aside is
    narrower and provable: the tab in front of me is one ANOTHER live session
    said it is working in.

    Every part of that is required, so every part is checked. An entry from a
    process that has exited claims nothing (its terminal is closed); this
    session's own entry is not "another session"; an entry for a different host
    is about a different tab.

    An entry that names no tab identifies nothing and is skipped. An entry whose
    PID cannot be read is counted as a live claim, via ``_owner_alive`` — the two
    failures here are not symmetric. Over-counting opens one tab nobody asked
    for; under-counting navigates a page somebody is working in out from under
    them, which is the bug this whole file exists to fix.

    A session idle past ``BUSY_WITHIN_S`` claims nothing: nobody is working in
    its tab, so it is free to use. An entry with no readable time still claims.
    """
    now = time.time()
    claimed = set()
    for key, entry in _read(path).items():
        if key == _key(instance_host) or not isinstance(entry, dict):
            continue
        if not key.endswith(f"|{instance_host}"):
            continue
        tab_id = str(entry.get("tab_id") or "")
        if tab_id and _owner_alive(entry) and _busy(_last_used_s(entry, now)):
            claimed.add(tab_id)
    return claimed


def drop_pin(path: str, instance_host: str) -> None:
    """Forget this session's tab on ``instance_host`` (its tab is gone)."""
    pins = _read(path)
    if pins.pop(_key(instance_host), None) is None:
        return
    _write(path, pins)


def _owner_alive(entry: Any) -> bool:
    """Is the process that wrote this entry still running?

    Unreadable entries are kept, not collected: "I could not tell" is not
    "nobody is there", and the cost of keeping one is a single map slot.
    """
    if not isinstance(entry, dict):
        return True
    try:
        pid = int(entry.get("pid", 0))
    except (TypeError, ValueError):
        return True
    return pid <= 0 or _is_pid_alive(pid)


__all__ = [
    "BUSY_WITHIN_S",
    "MAX_TRACKED_PINS",
    "OWNER_ID",
    "claimed_by_others",
    "drop_pin",
    "idle_others",
    "others_on",
    "read_pin",
    "shared_window_refusal",
    "touch",
    "write_pin",
]
