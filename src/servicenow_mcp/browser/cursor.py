"""High-water mark of what has already been reported, PER TAB.

``since_last`` is what makes the repeat-inspect loop cheap: after fixing some
CSS you want "what changed", not the same forty errors again. That only works
if the mark survives between tool calls, and it has to survive without the
model being asked to carry it. The repo already learned that lesson — a
mechanism the LLM must remember to pass along is not a mechanism.

So the cursor lives on disk next to the window state, defaults to on, and the
caller can still ask for everything with ``since_last=False``.

**One mark per tab, not one per window.** It used to be a single integer for the
whole window, and the probe's ``seq`` counts from 1 in EVERY tab (it is a
closure variable mirrored into that tab's sessionStorage). So a mark of 120
taken while inspecting one tab, applied to a second tab sitting at 40, filtered
away every event that tab had — and ``dropped`` computed to
``max(0, 40 - 40 - 120) == 0``, so nothing said a word. The result was a
``"No errors, no failed requests"`` verdict over a tab nobody had ever read:
the exact shape CLAUDE.md enumerates, an absence scored as evidence of safety.

The map is bounded and forgets the least recently WRITTEN tab, because tabs are
opened and closed all day. Forgetting one costs a single re-read of its buffer,
which over-fetches — the direction this is allowed to fail in. Recency is the
map's insertion order, never the mark's value: a mark counts events, so ranking
by it evicts the quietest tab, which is the one you just opened.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Plenty for a debugging session's worth of tabs. Beyond this the oldest entry
# is dropped and that tab simply re-reports its buffer once.
MAX_TRACKED_TABS = 16

# The mark for a window whose probe predates tab ids (v1.24.5). Kept under a
# reserved key rather than guessed at: an old probe's drain() reads a number,
# and there is exactly one number it can be given.
LEGACY_KEY = "_legacy"


def _read(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable inspect cursor at %s: %s", path, exc)
        return {}
    return raw if isinstance(raw, dict) else {}


def read_marks(path: str) -> Dict[str, int]:
    """Every tab's high-water mark, ``{tabId: seq}``.

    A file written before v1.24.5 holds ``{"seq": N}`` and no tab id. That N
    belongs to whichever tab was inspected last and there is no way to say
    which, so it is carried under LEGACY_KEY: an upgraded probe reports a real
    tab id, matches nothing, and starts from 0 — one re-read rather than a
    number quietly applied to the wrong tab.
    """
    raw = _read(path)
    tabs = raw.get("tabs")
    marks: Dict[str, int] = {}
    if isinstance(tabs, dict):
        for key, value in tabs.items():
            try:
                marks[str(key)] = max(0, int(value))
            except (TypeError, ValueError):
                continue
    elif raw.get("seq") is not None:
        try:
            marks[LEGACY_KEY] = max(0, int(raw["seq"]))
        except (TypeError, ValueError):
            pass
    return marks


def read_cursor(path: str) -> int:
    """The largest mark on record. Only for callers that cannot name a tab."""
    marks = read_marks(path)
    return max(marks.values()) if marks else 0


def write_mark(path: str, tab_id: str, seq: int) -> None:
    """Record ``seq`` as read for ``tab_id``, keeping the map bounded."""
    if seq <= 0:
        return
    if not tab_id:
        # No tab id means an old probe answered. Recording it under a real key
        # would let it be applied to a tab it did not come from.
        tab_id = LEGACY_KEY
    marks = read_marks(path)
    # Move-to-end, then evict from the front: insertion order IS the recency
    # order, and it survives the JSON round-trip.
    #
    # Eviction used to drop the LOWEST seq, described as "the tab nobody has
    # read from in a while". seq counts a tab's EVENTS, not when it was read, so
    # the quietest tab was evicted no matter how recently it was used — and the
    # tab you are actively inspecting is the quietest one there is while it is
    # still fresh. It was therefore evicted by the very write that recorded it,
    # every time, once 16 tabs were on file. The mark never persisted, every
    # inspect re-read the whole buffer, and `new_events` came back equal to
    # `next_seq` looking like a genuine count rather than a cursor that was
    # never applied. Failing toward the expensive read is the allowed direction;
    # doing it silently and permanently is not.
    marks.pop(str(tab_id), None)
    marks[str(tab_id)] = int(seq)
    while len(marks) > MAX_TRACKED_TABS:
        marks.pop(next(iter(marks)))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"tabs": marks}, handle)
        os.replace(tmp_path, path)
    except OSError as exc:  # pragma: no cover - cursor is an optimization
        logger.debug("Could not persist inspect cursor: %s", exc)


def reset_cursor(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover
        logger.debug("Could not reset inspect cursor: %s", exc)


def resolve_marks(
    path: str, *, since_last: bool, explicit: Optional[int] = None
) -> Dict[str, int] | int:
    """What to hand the page's ``drain``.

    An explicit value always wins and stays an int — it is the escape hatch for
    re-reading a span the cursor has moved past, and it is aimed at whatever tab
    the call lands on by definition.
    """
    if explicit is not None:
        return max(0, int(explicit))
    return read_marks(path) if since_last else {}


__all__ = [
    "LEGACY_KEY",
    "MAX_TRACKED_TABS",
    "read_cursor",
    "read_marks",
    "reset_cursor",
    "resolve_marks",
    "write_mark",
]
