"""Chromium presence probe for browser auth.

Centralizes the "is Playwright Chromium installed?" check so the MCP server,
the auth manager, and the sn_health tool all answer the same question without
duplicating logic. Returns user-facing instructions (with the exact install
command) — the caller decides where to surface them.
"""

from __future__ import annotations

import gc
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def check_chromium_install_hint() -> Optional[str]:
    """Return an LLM-facing instructions string if Chromium needs installing.

    Browser auth requires a Playwright Chromium binary. When it's missing or
    version-mismatched we surface the exact install command through every
    user-visible channel (MCP `instructions` + sn_health) so the LLM can guide
    the user immediately instead of letting them discover it via a cryptic
    handshake timeout on the first tool call.

    Returns:
        Multi-line instructions string when remediation is needed, else None.
    """
    try:
        import playwright.sync_api  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return (
            "Playwright Python package is missing. Run the server with "
            "`uvx --with playwright --from mfa-servicenow-mcp servicenow-mcp …` "
            "or install it manually (`pip install playwright`)."
        )

    # The Sync API cannot run on a thread that already has a RUNNING asyncio
    # loop — MCP dispatches tools on the event-loop thread (see server.py), so a
    # naive sync_playwright() here always raised "using Playwright Sync API
    # inside the asyncio loop" → the probe silently no-op'd and never caught a
    # missing/mismatched Chromium. Offload to a worker thread when a loop is
    # live (mirrors auth_manager._try_restore_browser_session).
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        import threading

        holder: dict = {}

        def _run() -> None:
            try:
                holder["result"] = _probe_chromium()
            except BaseException as exc:  # noqa: BLE001
                holder["exc"] = exc

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=30)
        if t.is_alive() or "exc" in holder:
            logger.debug("Chromium probe thread failed/timed out: %s", holder.get("exc"))
            return None
        return holder.get("result")

    return _probe_chromium()


class _PlaywrightTeardownNoise(logging.Filter):
    """Drop the two ERROR lines Playwright's own shutdown emits, and nothing else.

    Reproduced in isolation: ``check_chromium_install_hint()`` on its own, with
    no server and no browser, prints

        asyncio - ERROR - Task was destroyed but it is pending!
        task: <Task cancelling ... coro=<Connection.run.<locals>.init() ...>>
        asyncio - ERROR - Future exception was never retrieved
        future: <Future finished exception=TargetClosedError(...)>

    every time. It comes from inside ``sync_playwright().stop()``: the driver
    cancels its connection task and closes the loop before the cancellation
    finishes. The probe still returns the right answer — nothing is broken, and
    nothing is being hidden from the person running this.

    Measured over seven days of real sessions: 248 of these, at ERROR, in logs
    that are read to find what went wrong. That is the actual cost — a log where
    ERROR is usually noise is a log where a real ERROR gets skipped, which is how
    the dead progress channel survived two days.

    Two things keep this from being a signal killer. It is installed ONLY around
    the probe call (see :func:`_probe_chromium`), so asyncio is unfiltered for
    the entire life of the server. And it matches on the Playwright evidence in
    the record, not just the asyncio wording — an unrelated destroyed task or
    unretrieved exception in the same instant still gets through. If Playwright
    changes the wording, the noise comes back and is visible again; nothing is
    lost either way.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            text = record.getMessage()
        except Exception:  # noqa: BLE001 - a record we cannot read is not ours to drop
            return True
        if "Task was destroyed but it is pending" in text:
            return "playwright" not in text.lower()
        if "Future exception was never retrieved" in text:
            return "TargetClosedError" not in text
        return True


def _probe_chromium() -> Optional[str]:
    """Actually open Playwright and check the Chromium binary. MUST run on a
    thread with NO running asyncio loop (the Sync API requirement)."""
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    # Scoped to this call and removed in `finally`, including on the error
    # paths below — a filter left behind on the asyncio logger would outlive its
    # justification and start hiding things it was never meant to see.
    asyncio_logger = logging.getLogger("asyncio")
    noise_filter = _PlaywrightTeardownNoise()
    asyncio_logger.addFilter(noise_filter)
    try:
        return _probe_chromium_unfiltered(sync_playwright)
    finally:
        # `Task was destroyed` is emitted from `Task.__del__`, so it fires when
        # the driver's objects are COLLECTED — which is after `stop()` returns
        # and, without this, after the filter has already been taken down. The
        # first attempt removed the filter in `finally` and the noise still came
        # out, in exactly the same place. Collecting here brings the __del__s
        # forward into the window the filter covers, which is the only way to
        # scope this narrowly rather than leaving a filter on asyncio for the
        # life of the process.
        gc.collect()
        asyncio_logger.removeFilter(noise_filter)


def _probe_chromium_unfiltered(sync_playwright) -> Optional[str]:  # type: ignore[no-untyped-def]
    try:
        with sync_playwright() as pw:
            _ = pw.chromium.executable_path
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "executable" in msg or "browser" in msg or "doesn't exist" in msg:
            return (
                "Playwright Chromium browser is not installed (browser auth will fail "
                "on the next tool call). Run this once:\n"
                "  uvx --with playwright playwright install chromium\n"
                "Then retry. To prevent this from recurring after a Playwright release, "
                "pin both packages in your MCP client config:\n"
                '  args = ["--with", "playwright==<version>", '
                '"--from", "mfa-servicenow-mcp==<version>", "servicenow-mcp"]'
            )
        # Non-binary error — let it surface elsewhere; don't pollute instructions.
        logger.debug("Chromium probe raised non-binary error: %s", exc)
    return None
