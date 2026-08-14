"""Run sync-Playwright work off the MCP event-loop thread.

The Playwright Sync API refuses to start on a thread that already has a
RUNNING asyncio loop, and MCP dispatches tool calls on exactly that thread.
``utils/chromium.py`` documents the same trap: a naive ``sync_playwright()``
raised "using Playwright Sync API inside the asyncio loop" and the caller
silently no-op'd. Every Playwright entry point in this package funnels
through :func:`run_off_loop` so no caller has to remember the rule.

The off-loop side is ONE long-lived worker thread, not a thread per call.
Sync-Playwright objects are bound to the thread that created them, so a
persistent CDP connection is only possible if every job runs on the same
thread — and that persistence is the point: the per-call model spawned a
Playwright driver subprocess and a fresh CDP websocket for every single
tool call (up to five in one ``open_debug_window``). The worker owns the
driver and a per-endpoint browser cache (:func:`cdp_browser`); a job that
overruns its budget poisons the worker, which tears its state down and is
replaced on the next call — a hung page can slow one call, never wedge the
connection cache into a lying state.

When the caller's thread has no running loop (CLI, tests) jobs run inline
and :func:`cdp_browser` is transient (connect, yield, close) — caching
would pin thread-affine objects to whichever thread happened to call first.
"""

import asyncio
import logging
import queue
import threading
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar

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


class _BrowserWorker:
    """One thread that owns the Playwright driver and every CDP connection.

    Jobs are executed strictly in submission order. ``poison()`` marks the
    worker unusable: the loop tears down its Playwright state after the
    current job (if that job ever returns) and exits; the module spawns a
    fresh worker for the next call. A worker abandoned mid-hang leaks its
    thread exactly as the old per-call model leaked an abandoned thread —
    but never leaks a half-dead connection into a future call.
    """

    def __init__(self) -> None:
        self._jobs: "queue.Queue[Any]" = queue.Queue()
        self._poisoned = threading.Event()
        self._pw: Any = None
        self._browsers: Dict[str, Any] = {}
        self._thread = threading.Thread(target=self._loop, name="sn-debug-browser", daemon=True)
        self._thread.start()

    # -- caller side ---------------------------------------------------------

    def submit(self, fn: Callable[[], T], timeout_s: float) -> T:
        holder: dict[str, Any] = {}
        done = threading.Event()
        self._jobs.put((fn, holder, done))
        if not done.wait(timeout=timeout_s):
            self.poison()
            raise TimeoutError(
                f"Debug browser operation did not finish within {timeout_s:.0f}s. "
                "The window may be blocked on a dialog or an unresponsive page."
            )
        if "error" in holder:
            raise holder["error"]
        return holder["result"]  # type: ignore[no-any-return]

    def poison(self) -> None:
        self._poisoned.set()
        # Wake the loop if it is idle so teardown does not wait for a next job.
        self._jobs.put(None)

    @property
    def usable(self) -> bool:
        return self._thread.is_alive() and not self._poisoned.is_set()

    # -- worker side ---------------------------------------------------------

    def _loop(self) -> None:
        _WORKER_LOCAL.worker = self
        try:
            while True:
                job = self._jobs.get()
                if job is None or self._poisoned.is_set():
                    break
                fn, holder, done = job
                try:
                    holder["result"] = fn()
                except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
                    holder["error"] = exc
                finally:
                    done.set()
                if self._poisoned.is_set():
                    break
        finally:
            self._teardown()

    def get_browser(self, endpoint: str) -> Any:
        """Return a live cached connection to ``endpoint``, or connect fresh.

        A cached entry is revalidated with ``is_connected()`` on every use —
        a window that died or was relaunched (new port ⇒ new endpoint) never
        answers through a stale handle. Dead entries for OTHER endpoints are
        swept opportunistically so relaunch cycles cannot accumulate handles.
        """
        for key in [k for k, b in self._browsers.items() if not _is_connected(b)]:
            self._invalidate(key)
        cached = self._browsers.get(endpoint)
        if cached is not None:
            return cached
        if self._pw is None:
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

            self._pw = sync_playwright().start()
        browser = self._pw.chromium.connect_over_cdp(endpoint)
        self._browsers[endpoint] = browser
        return browser

    def _invalidate(self, endpoint: str) -> None:
        browser = self._browsers.pop(endpoint, None)
        if browser is not None:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 - already dead is fine
                pass

    def _teardown(self) -> None:
        for endpoint in list(self._browsers):
            self._invalidate(endpoint)
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001 - best-effort shutdown
                pass
            self._pw = None


def _is_connected(browser: Any) -> bool:
    try:
        return bool(browser.is_connected())
    except Exception:  # noqa: BLE001 - a handle that cannot answer is dead
        return False


_WORKER_LOCAL = threading.local()
_worker: Optional[_BrowserWorker] = None
_worker_lock = threading.Lock()


def _get_worker() -> _BrowserWorker:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker.usable:
            _worker = _BrowserWorker()
        return _worker


def _reset_worker_for_tests() -> None:
    """Discard the shared worker (tests only)."""
    global _worker
    with _worker_lock:
        if _worker is not None:
            _worker.poison()
            _worker = None


def run_off_loop(fn: Callable[[], T], *, timeout_s: float = DEFAULT_OFFLOAD_TIMEOUT_S) -> T:
    """Call ``fn`` on the persistent worker thread and return its result.

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

    return _get_worker().submit(fn, timeout_s)


@contextmanager
def cdp_browser(endpoint: str) -> Iterator[Any]:
    """Yield a CDP-connected browser for ``endpoint``.

    On the worker thread this is the warm cached connection — NOT closed on
    exit, so the next call skips driver spawn and websocket setup entirely.
    Any exception from the body invalidates the cache entry: one reconnect is
    cheaper than ever answering through a connection that just failed.

    Off the worker (inline path) it is transient: connect, yield, close —
    byte-for-byte the old per-call behavior.
    """
    worker = getattr(_WORKER_LOCAL, "worker", None)
    if worker is not None:
        browser = worker.get_browser(endpoint)
        try:
            yield browser
        except BaseException:
            worker._invalidate(endpoint)
            raise
        return

    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(endpoint)
        try:
            yield browser
        finally:
            # Disconnects from the window; does not close it (Playwright: a
            # connected browser is disconnected, a launched one is closed).
            browser.close()
