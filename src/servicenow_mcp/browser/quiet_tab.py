"""Open a tab without taking the person's keyboard and mouse.

Measured on macOS (Chrome for Testing over CDP, 2026-11): with another app in
front, ``context.new_page()`` and ``page.bring_to_front()`` each made the debug
window the active app, so whatever the person was typing went into the browser.
Clicks, typing and ``goto`` through Playwright did NOT, and neither did
``Target.createTarget`` with ``background: true`` — that tab still loads, runs
the context's init scripts, screenshots and takes input.

So a new tab opens behind the current one, and is brought forward only when the
debug window is already the app in front (the person is looking at it, so there
is nothing to take). Where that cannot be told, it stays behind: a tab one click
away costs less than keystrokes landing in the wrong window.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PID = re.compile(r'"?pid"?\s*=\s*(\d+)')


def window_is_front(pid: int) -> Optional[bool]:
    """Whether the debug window's process is the app in front. None: cannot tell."""
    if sys.platform != "darwin" or not pid:
        return None
    try:
        asn = subprocess.run(
            ["lsappinfo", "front"], capture_output=True, text=True, timeout=1
        ).stdout.strip()
        if not asn:
            return None
        out = subprocess.run(
            ["lsappinfo", "info", "-only", "pid", asn], capture_output=True, text=True, timeout=1
        ).stdout
    except Exception as exc:  # noqa: BLE001 - unknown, not "not in front"
        logger.debug("Could not read the front app: %s", exc)
        return None
    found = _PID.search(out)
    return int(found.group(1)) == int(pid) if found else None


def open_tab(browser: Any, context: Any) -> Any:
    """A new blank tab opened behind the current one; falls back to ``new_page``."""
    session = None
    try:
        session = browser.new_browser_cdp_session()
        with context.expect_page(timeout=10_000) as info:
            session.send("Target.createTarget", {"url": "about:blank", "background": True})
        return info.value
    except Exception as exc:  # noqa: BLE001 - a working tab beats a quiet failure
        logger.debug("Background tab unavailable, opening a normal one: %s", exc)
        return context.new_page()
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:  # noqa: BLE001 - nothing to clean up
                pass


def show_if_watched(page: Any, pid: int) -> bool:
    """Bring ``page`` forward only when the debug window is already in front."""
    if window_is_front(pid) is not True:
        return False
    try:
        page.bring_to_front()
    except Exception as exc:  # noqa: BLE001 - cosmetic
        logger.debug("Could not bring the tab forward: %s", exc)
        return False
    return True


__all__ = ["open_tab", "show_if_watched", "window_is_front"]
