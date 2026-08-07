"""Keep the debug window's scratch directory from growing without end.

Every ``inspect`` and every ``act`` that takes a screenshot writes two files: an
image and an event dump. Nothing ever removed them. The reaper retires idle
WINDOWS after half an hour and has never looked at what they left behind, so a
day of ordinary use measured 25 files and 2.5MB, and nothing about that number
was ever going to stop rising.

Why this is not simply "delete the old ones"
--------------------------------------------
The paths are RETURNED TO THE CALLER. A response says
``screenshot: /…/shot-1786064130354.webp``, and the model may still be holding
that path several turns later — reading it back to look at the picture again, or
handing it to the user. A prune that is merely "old enough" would delete files
whose paths are live in someone's context, and the failure would look like the
tool lying about where it put something.

So the floor is a COUNT, not an age: the most recent ``KEEP_RECENT`` artifacts
are never touched, however small the byte budget gets. Age only decides the
order of what is removed beyond that floor. A session does not usually hold more
than a handful of paths at once, and the floor is set well above that.

Everything else follows the same rule the rest of this package uses: it is
best-effort, it never raises into the operation it is housekeeping for, and it
reports what it removed rather than being silently helpful.
"""

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# What this directory is allowed to hold. Generous — the point is a ceiling, not
# a tight budget: a WebP screenshot is ~40KB and an event dump up to ~100KB, so
# this is several hundred captures.
MAX_BYTES = 64 * 1024 * 1024

# Never removed, no matter what the byte budget says. See the module docstring:
# these paths are live in the caller's context.
KEEP_RECENT = 40

# Beyond the count floor, nothing younger than this is a candidate either. A
# capture taken a minute ago belongs to the conversation that is happening now.
MIN_AGE_S = 30 * 60.0

# Only what this package writes. A directory is not a licence to delete
# whatever is in it — someone may have put something here.
_OURS = (".webp", ".png", ".jpg", ".jpeg", ".json")
_PREFIXES = ("shot-", "events-")


def _candidates(directory: str) -> List[Tuple[float, int, str]]:
    """(mtime, size, path) for the files this package wrote. Newest first."""
    found: List[Tuple[float, int, str]] = []
    try:
        entries = os.listdir(directory)
    except OSError as exc:
        logger.debug("Cannot list the debug artifacts dir %s: %s", directory, exc)
        return []
    for name in entries:
        if not name.startswith(_PREFIXES) or not name.endswith(_OURS):
            continue
        path = os.path.join(directory, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue  # vanished under us; nothing to do about it
        if not os.path.isfile(path):
            continue
        found.append((stat.st_mtime, stat.st_size, path))
    found.sort(reverse=True)
    return found


def prune(
    directory: str,
    *,
    max_bytes: int = MAX_BYTES,
    keep_recent: int = KEEP_RECENT,
    min_age_s: float = MIN_AGE_S,
    now: Optional[float] = None,
) -> Dict[str, object]:
    """Trim the directory to the byte budget, oldest first. Never raises.

    Returns what it actually did. An empty dict means nothing needed doing,
    which is the normal case and deliberately says nothing to the caller.
    """
    moment = time.time() if now is None else now
    files = _candidates(directory)
    if not files:
        return {}

    total = sum(size for _mtime, size, _path in files)
    if total <= max_bytes:
        return {}

    removed = 0
    freed = 0
    # Oldest first, and only past the floor. `files` is newest-first, so the
    # tail is what may go.
    for mtime, size, path in reversed(files[keep_recent:]):
        if total - freed <= max_bytes:
            break
        if moment - mtime < min_age_s:
            continue
        try:
            os.remove(path)
        except OSError as exc:  # noqa: PERF203 - one bad file must not stop the sweep
            logger.debug("Could not remove a debug artifact %s: %s", path, exc)
            continue
        removed += 1
        freed += size

    if not removed:
        # Over budget and nothing eligible: everything is recent or protected.
        # Said rather than swallowed — a cap that silently gave up looks exactly
        # like one that worked.
        return {
            "artifacts_note": (
                f"The debug artifacts directory holds {total // (1024 * 1024)}MB, over the "
                f"{max_bytes // (1024 * 1024)}MB it trims at, and nothing was old enough to "
                f"remove (the {keep_recent} most recent are always kept). It is at "
                f"{directory}."
            )
        }
    return {
        "artifacts_pruned": removed,
        "artifacts_freed_mb": round(freed / (1024 * 1024), 1),
    }


__all__ = ["KEEP_RECENT", "MAX_BYTES", "MIN_AGE_S", "prune"]
