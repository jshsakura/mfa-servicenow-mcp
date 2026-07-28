"""Cross-process claim so N MCP hosts open ONE shared window, not N.

Claude Desktop, a terminal, and an IDE extension can all run this server at
once against the same instance. Without a claim they race: each reads "no
window", each launches, and the user gets a pile of Chromium windows. The auth
layer hit exactly this with its login lock (issue #30) and the fix there — the
create IS the claim, via ``O_CREAT|O_EXCL`` — is the fix here. Checking
``os.path.exists()`` and then writing is a TOCTOU race that both hosts win.

Two properties keep this simple compared to the login lock:

- Losing the race is harmless. A host that cannot claim waits for the winner
  and then reuses the window the winner created — the correct outcome anyway,
  so there is no need to steal a live claim.
- A double launch cannot produce a double window. Both would target the same
  ``--user-data-dir``, and Chromium hands a second launch off to the process
  already holding that profile and exits. The claim makes the race graceful;
  the shared profile is what makes it safe.
"""

import errno
import json
import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator

from ..auth._process import _is_pid_alive

logger = logging.getLogger(__name__)

# Launching is spawn + readiness poll; window.py caps that poll at 30s.
# A claim older than this outlived any legitimate launch and is collectable.
CLAIM_STALE_AFTER_S = 60.0

# How long a losing host waits for the winner before giving up and looking
# again. Slightly longer than the readiness cap so the winner's window is
# visible in the state file by the time we re-read it.
CLAIM_WAIT_S = 40.0
_CLAIM_POLL_S = 0.25


class LaunchBusy(RuntimeError):
    """Another host is opening the shared window and did not finish in time."""


def _claim_is_stale(path: str) -> bool:
    """True when the claim's holder is gone or the claim simply aged out.

    Age is checked FIRST and on its own is sufficient. Liveness alone is not:
    an unrelated process can inherit a dead holder's pid, report "alive"
    forever, and make the claim permanently uncollectable.
    """
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False

    if time.time() - stat.st_mtime > CLAIM_STALE_AFTER_S:
        return True

    try:
        with open(path, "r", encoding="utf-8") as handle:
            holder = int(json.load(handle).get("pid", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False  # unreadable but recent — assume a live peer is writing it

    return holder > 0 and not _is_pid_alive(holder)


def _try_claim(path: str) -> bool:
    """Atomically create the claim file. True if we now hold it."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            return _try_claim(path)
        # Fail open: a broken claim path must not make the window unopenable.
        logger.warning("Could not create debug-window launch claim: %s", exc)
        return True
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump({"pid": os.getpid(), "timestamp": time.time()}, handle)
    except OSError as exc:  # pragma: no cover - claim existence is what matters
        logger.debug("Claim file written partially: %s", exc)
    return True


def _release(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:  # pragma: no cover - best effort
        logger.debug("Could not release debug-window launch claim: %s", exc)


@contextmanager
def launch_claim(path: str, *, wait_s: float = CLAIM_WAIT_S) -> Iterator[bool]:
    """Hold the launch claim for the duration of the block.

    Yields True when we own the claim and should launch. Yields False when a
    peer finished launching while we waited — the caller should re-read the
    window state and reuse whatever the peer opened rather than launching.

    Raises :class:`LaunchBusy` if a peer holds the claim past ``wait_s``
    without releasing it, so a wedged host surfaces instead of piling on.
    """
    deadline = time.time() + wait_s
    claimed = _try_claim(path)

    while not claimed and time.time() < deadline:
        if _claim_is_stale(path):
            _release(path)
            claimed = _try_claim(path)
            continue
        time.sleep(_CLAIM_POLL_S)
        if not os.path.exists(path):
            # The winner released — it has a window now. Tell the caller to
            # look for it instead of racing to open a second one.
            yield False
            return

    if not claimed:
        raise LaunchBusy(
            "Another process has been opening the shared debug window for over "
            f"{wait_s:.0f}s. If no window appeared, close any stray Chromium "
            "window for this instance and try again."
        )

    try:
        yield True
    finally:
        _release(path)


__all__ = ["CLAIM_STALE_AFTER_S", "CLAIM_WAIT_S", "LaunchBusy", "launch_claim"]
