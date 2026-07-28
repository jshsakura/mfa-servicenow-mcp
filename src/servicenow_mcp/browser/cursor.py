"""High-water mark of what has already been reported for a window.

``since_last`` is what makes the repeat-inspect loop cheap: after fixing some
CSS you want "what changed", not the same forty errors again. That only works
if the mark survives between tool calls, and it has to survive without the
model being asked to carry it. The repo already learned that lesson — a
mechanism the LLM must remember to pass along is not a mechanism.

So the cursor lives on disk next to the window state, defaults to on, and the
caller can still ask for everything with ``since_last=False``.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def read_cursor(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return max(0, int(json.load(handle).get("seq", 0)))
    except FileNotFoundError:
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.debug("Unreadable inspect cursor at %s: %s", path, exc)
        return 0


def write_cursor(path: str, seq: int) -> None:
    if seq <= 0:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump({"seq": int(seq)}, handle)
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


def resolve_after_seq(path: str, *, since_last: bool, explicit: Optional[int] = None) -> int:
    """Where to start reading from.

    An explicit value always wins — it is the escape hatch for re-reading a
    span the cursor has already moved past.
    """
    if explicit is not None:
        return max(0, int(explicit))
    return read_cursor(path) if since_last else 0


__all__ = ["read_cursor", "reset_cursor", "resolve_after_seq", "write_cursor"]
