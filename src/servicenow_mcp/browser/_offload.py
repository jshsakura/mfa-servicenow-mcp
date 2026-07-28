"""Run sync-Playwright work off the MCP event-loop thread.

The Playwright Sync API refuses to start on a thread that already has a
RUNNING asyncio loop, and MCP dispatches tool calls on exactly that thread.
``utils/chromium.py`` documents the same trap: a naive ``sync_playwright()``
raised "using Playwright Sync API inside the asyncio loop" and the caller
silently no-op'd. Every Playwright entry point in this package funnels
through :func:`run_off_loop` so no caller has to remember the rule.
"""

import asyncio
import logging
import threading
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# A CDP attach + read should take well under a second on localhost. The cap
# exists so a hung browser surfaces as a clear error instead of wedging the
# MCP request forever.
DEFAULT_OFFLOAD_TIMEOUT_S = 120.0


class PlaywrightUnavailable(RuntimeError):
    """Playwright is not importable in this interpreter."""


def require_playwright() -> None:
    """Raise :class:`PlaywrightUnavailable` with an actionable message."""
    try:
        import playwright.sync_api  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise PlaywrightUnavailable(
            "Playwright is not installed in this interpreter. Run the server with "
            "`uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp ...` "
            "or install it manually (`pip install playwright`)."
        ) from exc


def run_off_loop(fn: Callable[[], T], *, timeout_s: float = DEFAULT_OFFLOAD_TIMEOUT_S) -> T:
    """Call ``fn`` on a thread with no running asyncio loop and return its result.

    When the caller's thread has no live loop (CLI, tests) ``fn`` runs inline —
    spawning a thread there would only add latency. Exceptions propagate to the
    caller either way, so error handling is identical on both paths.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None or not loop.is_running():
        return fn()

    holder: dict[str, Any] = {}

    def _run() -> None:
        try:
            holder["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            holder["error"] = exc

    thread = threading.Thread(target=_run, name="sn-debug-browser", daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        raise TimeoutError(
            f"Debug browser operation did not finish within {timeout_s:.0f}s. "
            "The window may be blocked on a dialog or an unresponsive page."
        )
    if "error" in holder:
        raise holder["error"]
    return holder["result"]  # type: ignore[no-any-return]
