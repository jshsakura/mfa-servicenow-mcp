"""Run a Playwright Sync API call where it is legal.

Playwright's Sync API refuses to start on a thread that has a running asyncio
loop, and MCP tool dispatch IS such a thread. A probe called there raises "It
looks like you are using Playwright Sync API inside the asyncio loop" — a
message about the caller, which hid the real answer ("Chromium is missing /
still installing") from the user.
"""

import asyncio
import threading
from typing import Callable, Dict, TypeVar

T = TypeVar("T")


def run_off_event_loop(fn: Callable[[], T], timeout: float = 120.0) -> T:
    """Call ``fn`` directly when no loop runs here, else on a worker thread; re-raise its error."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn()
    box: Dict[str, object] = {}

    def _run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised on the caller's thread
            box["error"] = exc

    worker = threading.Thread(target=_run, daemon=True, name="playwright-off-loop")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise RuntimeError(f"Playwright call did not finish within {timeout:.0f}s")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]
