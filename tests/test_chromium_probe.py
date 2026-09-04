"""The startup Chromium probe must not fill the log with Playwright's shutdown.

Seven days of real session logs carried 248 ERROR lines — 124 pairs — of

    asyncio - ERROR - Task was destroyed but it is pending!
    asyncio - ERROR - Future exception was never retrieved

Reproduced in isolation: `check_chromium_install_hint()` on its own, with no
server and no browser, emits both every time. They come from inside
`sync_playwright().stop()`, which cancels its connection task and closes the loop
before the cancellation finishes. Nothing is broken and the probe returns the
right answer — the cost is that ERROR stops meaning anything in a log people read
to find out what went wrong. (That is not hypothetical here: a genuinely dead
progress channel sat undetected for two days behind a `logger.debug`.)

What is pinned below is the SHAPE of the fix, not the silence: the suppression is
scoped to the probe call, matches on the Playwright evidence rather than on the
asyncio wording, and leaves nothing behind on the asyncio logger.
"""

import logging

from servicenow_mcp.utils import chromium


def _noise_records(caplog):
    return [
        r
        for r in caplog.records
        if "Task was destroyed" in r.getMessage()
        or "Future exception was never retrieved" in r.getMessage()
    ]


def test_the_probe_leaves_no_playwright_teardown_errors(caplog):
    with caplog.at_level(logging.ERROR, logger="asyncio"):
        chromium.check_chromium_install_hint()

    assert _noise_records(caplog) == [], (
        "the probe emitted Playwright's own shutdown noise at ERROR; every session "
        "log then carries it, and ERROR stops being worth reading"
    )


def test_the_filter_does_not_outlive_the_probe():
    """A filter left on the asyncio logger would hide things it never saw."""
    before = list(logging.getLogger("asyncio").filters)

    chromium.check_chromium_install_hint()

    assert logging.getLogger("asyncio").filters == before


def test_a_real_asyncio_error_with_the_same_wording_survives():
    """Matched on the Playwright evidence, not on asyncio's phrasing.

    An unrelated destroyed task or unretrieved exception in the same instant is
    exactly what this must not eat — the noise is identified by WHOSE it is.
    """
    noise = chromium._PlaywrightTeardownNoise()

    def record(message):
        return logging.LogRecord("asyncio", logging.ERROR, __file__, 1, message, None, None)

    # Playwright's, by the connection module in the task repr.
    assert not noise.filter(
        record(
            "Task was destroyed but it is pending!\ntask: <Task cancelling "
            "coro=<Connection.run.<locals>.init() running at "
            "/x/site-packages/playwright/_impl/_connection.py:344>>"
        )
    )
    assert not noise.filter(
        record(
            "Future exception was never retrieved\nfuture: <Future finished "
            "exception=TargetClosedError('Target page, context or browser has been closed')>"
        )
    )
    # Somebody else's, same opening words. Must pass.
    assert noise.filter(record("Task was destroyed but it is pending!\ntask: <Task name='sync'>"))
    assert noise.filter(
        record("Future exception was never retrieved\nfuture: <Future exception=ValueError('x')>")
    )
    # Anything else at all.
    assert noise.filter(record("Executing <Handle ...> took 0.5 seconds"))


def test_the_probe_still_answers(monkeypatch):
    """Suppressing the noise must not suppress the finding.

    The probe exists to tell the user Chromium is missing before a tool call
    fails on it; a filter that swallowed that would be the trade this repo
    refuses to make.
    """

    class _Chromium:
        @property
        def executable_path(self):
            raise RuntimeError("Executable doesn't exist at /nope/chrome")

    class _PW:
        chromium = _Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    hint = chromium._probe_chromium_unfiltered(_PW)

    assert hint is not None and "playwright install chromium" in hint
