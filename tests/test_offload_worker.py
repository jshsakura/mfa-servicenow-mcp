"""The persistent CDP worker: one thread, warm connections, honest failure.

The per-call model spawned a Playwright driver subprocess and a fresh CDP
websocket for every debug tool call. These tests pin the replacement:
- with a running loop, jobs share ONE worker thread and ONE connection
- a hung job poisons the worker; the next call gets a fresh one
- a connection that failed or died is never handed out again
- with no loop (CLI/tests) the old transient connect/close behavior remains
"""

import asyncio
import sys
import threading
import types

import pytest

from servicenow_mcp.browser import _offload


class FakeBrowser:
    def __init__(self):
        self.closed = 0
        self.connected = True

    def is_connected(self):
        return self.connected

    def close(self):
        self.closed += 1
        self.connected = False


class FakePlaywright:
    """Stands in for the object sync_playwright().start() returns."""

    def __init__(self):
        self.connects = []
        self.browsers = []
        self.stopped = 0
        outer = self

        class _Chromium:
            def connect_over_cdp(self, endpoint):
                outer.connects.append(endpoint)
                browser = FakeBrowser()
                outer.browsers.append(browser)
                return browser

        self.chromium = _Chromium()

    def stop(self):
        self.stopped += 1


class FakeSyncPlaywrightCM:
    """Stands in for sync_playwright(): usable as CM (inline) or .start() (worker)."""

    instances: list["FakeSyncPlaywrightCM"] = []

    def __init__(self):
        self.pw = FakePlaywright()
        FakeSyncPlaywrightCM.instances.append(self)

    def start(self):
        return self.pw

    def __enter__(self):
        return self.pw

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_playwright(monkeypatch):
    FakeSyncPlaywrightCM.instances = []
    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = FakeSyncPlaywrightCM
    package = types.ModuleType("playwright")
    package.sync_api = fake
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    yield fake
    _offload._reset_worker_for_tests()


def _in_loop(fn):
    """Run fn() on a thread that HAS a running asyncio loop (the MCP shape)."""

    async def _main():
        return fn()

    return asyncio.run(_main())


class TestWorkerReuse:
    def test_jobs_share_one_thread_and_one_connection(self, fake_playwright):
        seen = []

        def job():
            with _offload.cdp_browser("http://127.0.0.1:9001") as browser:
                seen.append((threading.current_thread().name, id(browser)))
                return True

        assert _in_loop(lambda: _offload.run_off_loop(job)) is True
        assert _in_loop(lambda: _offload.run_off_loop(job)) is True

        threads = {name for name, _ in seen}
        browsers = {bid for _, bid in seen}
        assert threads == {"sn-debug-browser"}
        assert len(browsers) == 1, "the second call must reuse the warm connection"
        pw = FakeSyncPlaywrightCM.instances[0].pw
        assert pw.connects == ["http://127.0.0.1:9001"], "exactly one connect"
        assert pw.browsers[0].closed == 0, "a healthy cached connection is never closed"

    def test_endpoints_get_separate_connections(self, fake_playwright):
        def job(endpoint):
            with _offload.cdp_browser(endpoint) as browser:
                return id(browser)

        first = _in_loop(lambda: _offload.run_off_loop(lambda: job("http://127.0.0.1:9001")))
        second = _in_loop(lambda: _offload.run_off_loop(lambda: job("http://127.0.0.1:9002")))
        assert first != second
        pw = FakeSyncPlaywrightCM.instances[0].pw
        assert len(pw.connects) == 2


class TestFailureIsNeverReused:
    def test_body_exception_invalidates_the_cached_connection(self, fake_playwright):
        def failing():
            with _offload.cdp_browser("http://127.0.0.1:9001"):
                raise RuntimeError("page went away")

        def ok():
            with _offload.cdp_browser("http://127.0.0.1:9001") as browser:
                return id(browser)

        with pytest.raises(RuntimeError):
            _in_loop(lambda: _offload.run_off_loop(failing))
        _in_loop(lambda: _offload.run_off_loop(ok))

        pw = FakeSyncPlaywrightCM.instances[0].pw
        assert len(pw.connects) == 2, "the failed connection must not be handed out again"
        assert pw.browsers[0].closed == 1

    def test_dead_connection_is_replaced_not_returned(self, fake_playwright):
        def job():
            with _offload.cdp_browser("http://127.0.0.1:9001") as browser:
                return id(browser)

        first = _in_loop(lambda: _offload.run_off_loop(job))
        pw = FakeSyncPlaywrightCM.instances[0].pw
        pw.browsers[0].connected = False  # window died / was relaunched
        second = _in_loop(lambda: _offload.run_off_loop(job))
        assert first != second
        assert len(pw.connects) == 2


class TestTimeoutPoisonsTheWorker:
    def test_hung_job_times_out_and_next_call_gets_a_fresh_worker(self, fake_playwright):
        release = threading.Event()
        idents = []

        def hung():
            idents.append(threading.get_ident())
            release.wait(5.0)

        def quick():
            idents.append(threading.get_ident())
            return "ok"

        with pytest.raises(TimeoutError):
            _in_loop(lambda: _offload.run_off_loop(hung, timeout_s=0.05))
        try:
            assert _in_loop(lambda: _offload.run_off_loop(quick, timeout_s=5.0)) == "ok"
            assert len(idents) == 2
            assert idents[0] != idents[1], "the poisoned worker must not run new jobs"
        finally:
            release.set()

    def test_poisoned_worker_tears_down_its_playwright_state(self, fake_playwright):
        def connect():
            with _offload.cdp_browser("http://127.0.0.1:9001"):
                return True

        _in_loop(lambda: _offload.run_off_loop(connect))
        worker = _offload._worker
        pw = FakeSyncPlaywrightCM.instances[0].pw
        worker.poison()
        worker._thread.join(timeout=5.0)
        assert not worker._thread.is_alive()
        assert pw.browsers[0].closed == 1
        assert pw.stopped == 1


class TestInlinePathStaysTransient:
    def test_no_loop_means_connect_use_close_every_time(self, fake_playwright):
        def job():
            with _offload.cdp_browser("http://127.0.0.1:9001") as browser:
                return browser

        first = _offload.run_off_loop(job)
        second = _offload.run_off_loop(job)
        assert first is not second
        assert first.closed == 1 and second.closed == 1
        # Each inline call opened its own transient sync_playwright.
        assert len(FakeSyncPlaywrightCM.instances) == 2
