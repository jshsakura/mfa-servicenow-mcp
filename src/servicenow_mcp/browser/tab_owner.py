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
from typing import Any, Dict

from ..auth._process import _is_pid_alive

logger = logging.getLogger(__name__)

# This process, for as long as it runs. A restart deliberately starts over: the
# terminal that owned the tab is gone, and inheriting its tab would be guessing.
OWNER_ID = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"

# Bounded like cursor.py's map, and for the same reason: this is an optimization
# whose worst failure is one re-pick. Entries are dropped oldest-written first.
MAX_TRACKED_PINS = 32


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
    pins[_key(instance_host)] = {"tab_id": tab_id, "pid": os.getpid(), "at": time.time()}
    while len(pins) > MAX_TRACKED_PINS:
        pins.pop(next(iter(pins)))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"pins": pins}, handle)
        os.replace(tmp_path, path)
    except OSError as exc:  # pragma: no cover - a pin is an optimization
        logger.debug("Could not persist a debug-window tab pin: %s", exc)


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
    """
    claimed = set()
    for key, entry in _read(path).items():
        if key == _key(instance_host) or not isinstance(entry, dict):
            continue
        if not key.endswith(f"|{instance_host}"):
            continue
        tab_id = str(entry.get("tab_id") or "")
        if tab_id and _owner_alive(entry):
            claimed.add(tab_id)
    return claimed


def drop_pin(path: str, instance_host: str) -> None:
    """Forget this session's tab on ``instance_host`` (its tab is gone)."""
    pins = _read(path)
    if pins.pop(_key(instance_host), None) is None:
        return
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"pins": pins}, handle)
        os.replace(tmp_path, path)
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not drop a debug-window tab pin: %s", exc)


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
    "MAX_TRACKED_PINS",
    "OWNER_ID",
    "claimed_by_others",
    "drop_pin",
    "read_pin",
    "write_pin",
]
