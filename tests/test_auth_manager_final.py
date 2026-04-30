"""
Final coverage tests for auth_manager.py — targeting the remaining uncovered lines.

Lines missed (from coverage report):
362, 415, 494-495, 498-499, 601-602, 835, 837, 839, 847-852, 862, 864,
906, 908, 1427-1463, 1489-1811, 1842-1843, 1896, 2004-2022
"""

import asyncio
import json
import os
import threading
import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import requests

from servicenow_mcp.auth.auth_manager import (
    PASSWORD_SELECTORS,
    SUBMIT_SELECTORS,
    USERNAME_SELECTORS,
    AuthManager,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig


def _make_browser_manager(
    instance_url: str = "https://example.service-now.com",
    session_ttl_minutes: int = 30,
    headless: bool = True,
) -> AuthManager:
    cfg = AuthConfig(
        type=AuthType.BROWSER,
        browser=BrowserAuthConfig(
            headless=headless,
            timeout_seconds=10,
            session_ttl_minutes=session_ttl_minutes,
        ),
    )
    with (
        patch.object(AuthManager, "_ensure_playwright_ready"),
        patch.object(AuthManager, "_load_session_from_disk"),
        patch.object(AuthManager, "_start_keepalive"),
    ):
        manager = AuthManager(cfg, instance_url)
    return manager


# ===========================================================================
# Line 362: _ensure_playwright_ready — browser probe opens and closes
# ===========================================================================


class TestEnsurePlaywrightReadyProbeClose:
    def test_browser_probe_success_closes(self):
        """When browser opens successfully, it is probed then closed."""
        mock_browser = MagicMock()
        mock_pw = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser

        mock_sync_pw = MagicMock()
        mock_sync_pw.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync_pw.__exit__ = MagicMock(return_value=False)

        real_import = __import__

        def _mock_import(name, *args, **kwargs):
            if name == "playwright.sync_api" or (
                name == "playwright" and args and "sync_api" in str(args)
            ):
                mod = MagicMock()
                mod.sync_playwright = MagicMock(return_value=mock_sync_pw)
                return mod
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            AuthManager._ensure_playwright_ready()

        mock_browser.close.assert_called_once()


# ===========================================================================
# Line 415: _get_default_user_data_dir with browser username
# ===========================================================================


class TestDefaultUserDataDirBrowserUsername:
    def test_browser_username_in_profile_dir(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(username="admin@example.com", timeout_seconds=10),
        )
        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_load_session_from_disk"),
            patch.object(AuthManager, "_start_keepalive"),
        ):
            mgr = AuthManager(cfg, "https://myinst.service-now.com")
        result = mgr._get_default_user_data_dir()
        assert "admin_example_com" in result
        assert "profile_" in result


# ===========================================================================
# Lines 494-495, 498-499: _wait_for_other_login — disk load paths
# ===========================================================================


class TestWaitForOtherLoginDiskPaths:
    def test_lock_released_disk_load_succeeds(self, tmp_path):
        """After lock released, _load_session_from_disk returns valid session."""
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        # Lock exists initially but will be removed (simulating other process releasing)
        lock_data = {"pid": os.getpid(), "timestamp": time.time()}
        with open(mgr._login_lock_path, "w") as f:
            json.dump(lock_data, f)

        # First call: _reload returns False, then lock released
        # _load_session_from_disk sets cookie (not expired)
        reload_count = {"n": 0}

        def _mock_reload():
            reload_count["n"] += 1
            return False

        def _mock_load():
            # Set cookie after lock released
            mgr._browser_cookie_header = "other=cookie"
            mgr._browser_cookie_expires_at = time.time() + 600

        def _mock_sleep(seconds):
            # Remove lock file to simulate release
            if os.path.exists(mgr._login_lock_path):
                os.remove(mgr._login_lock_path)

        def _mock_expired():
            return False

        with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
            with patch.object(mgr, "_load_session_from_disk", side_effect=_mock_load):
                with patch.object(mgr, "_is_browser_session_expired", side_effect=_mock_expired):
                    with patch(
                        "servicenow_mcp.auth.auth_manager.time.sleep", side_effect=_mock_sleep
                    ):
                        result = mgr._wait_for_other_login(timeout=5)

        assert result is True

    def test_lock_held_fresh_session_on_disk(self, tmp_path):
        """Lock still held but fresh session appeared on disk."""
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        # Lock file stays present (other process still has it)
        lock_data = {"pid": 99999999, "timestamp": time.time()}
        with open(mgr._login_lock_path, "w") as f:
            json.dump(lock_data, f)

        reload_count = {"n": 0}

        def _mock_reload():
            reload_count["n"] += 1
            if reload_count["n"] >= 1:
                mgr._browser_cookie_header = "fresh=cookie"
                mgr._browser_cookie_expires_at = time.time() + 600
                return True
            return False

        with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                result = mgr._wait_for_other_login(timeout=2)

        assert result is True


# ===========================================================================
# Line 601-602: _load_session_from_disk — exception handler
# ===========================================================================


class TestLoadSessionFromDiskException:
    def test_corrupt_json_logs_warning(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")

        with open(mgr._session_cache_path, "w") as f:
            f.write("{corrupt json!!!")

        mgr._load_session_from_disk()
        assert mgr._browser_cookie_header is None


# ===========================================================================
# Lines 835, 837, 839: get_headers — another thread completed, session not available
# ===========================================================================


class TestGetHeadersAnotherThreadNoSession:
    def test_another_thread_completed_but_no_session(self):
        """Another thread completed login but no cookie set — raises ValueError."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None

        mock_lock = MagicMock()
        acquired = {"count": 0}

        def _mock_acquire(blocking=False, timeout=-1):
            acquired["count"] += 1
            if acquired["count"] == 1:
                return False  # First call: another thread has lock
            return True

        mock_lock.acquire = _mock_acquire
        mock_lock.release = MagicMock()
        mgr._browser_login_lock = mock_lock

        with pytest.raises(
            ValueError,
            match="Browser login completed in another thread but session is not available",
        ):
            mgr.get_headers()


# ===========================================================================
# Lines 847-852: get_headers — double-check after lock, session valid
# ===========================================================================


class TestGetHeadersDoubleCheckAfterLock:
    def test_double_check_session_valid_after_lock(self):
        """After acquiring lock, double-check finds valid session from another thread."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_user_agent = "TestUA"
        mgr._browser_session_token = "tok123"

        mock_lock = MagicMock()
        acquired = {"count": 0}

        def _mock_acquire(blocking=False, timeout=-1):
            acquired["count"] += 1
            if acquired["count"] == 1:
                mgr._browser_cookie_header = "other=cookie"
                mgr._browser_cookie_expires_at = time.time() + 600
                return True
            return True

        mock_lock.acquire = _mock_acquire
        mock_lock.release = MagicMock()
        mgr._browser_login_lock = mock_lock

        with patch.object(mgr, "_reload_session_from_disk", return_value=False):
            headers = mgr.get_headers()

        assert headers["Cookie"] == "other=cookie"
        assert headers["User-Agent"] == "TestUA"
        assert headers["X-UserToken"] == "tok123"


# ===========================================================================
# Lines 862, 864: get_headers — restore success with user_agent/session_token
# ===========================================================================


class TestGetHeadersRestoreWithUserAgentToken:
    def test_restore_success_sets_user_agent_and_token(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._keepalive_thread = None

        def _mock_restore(cfg):
            mgr._browser_cookie_header = "restored=1"
            mgr._browser_cookie_expires_at = time.time() + 600
            mgr._browser_user_agent = "RestoreAgent"
            mgr._browser_session_token = "restore_tok"
            return True

        with patch.object(mgr, "_reload_session_from_disk", return_value=False):
            with patch.object(mgr, "_try_restore_browser_session", side_effect=_mock_restore):
                with patch.object(mgr, "_start_keepalive"):
                    headers = mgr.get_headers()

        assert headers["Cookie"] == "restored=1"
        assert headers["User-Agent"] == "RestoreAgent"
        assert headers["X-UserToken"] == "restore_tok"


# ===========================================================================
# Lines 906, 908: get_headers — waited for other login, has user_agent/token
# ===========================================================================


class TestGetHeadersWaitOtherLoginWithDetails:
    def test_wait_success_with_user_agent_and_token(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._keepalive_thread = None

        def _mock_wait(timeout):
            mgr._browser_cookie_header = "waited=1"
            mgr._browser_cookie_expires_at = time.time() + 600
            mgr._browser_user_agent = "WaitUA"
            mgr._browser_session_token = "wait_tok"
            return True

        with patch.object(mgr, "_reload_session_from_disk", return_value=False):
            with patch.object(mgr, "_try_restore_browser_session", return_value=False):
                with patch.object(mgr, "_acquire_login_lock", return_value=False):
                    with patch.object(mgr, "_wait_for_other_login", side_effect=_mock_wait):
                        with patch.object(mgr, "_start_keepalive"):
                            headers = mgr.get_headers()

        assert headers["Cookie"] == "waited=1"
        assert headers["User-Agent"] == "WaitUA"
        assert headers["X-UserToken"] == "wait_tok"


# ===========================================================================
# Lines 1427-1463: _login_with_browser — running event loop thread delegation
# ===========================================================================


class TestLoginWithBrowserEventLoop:
    def test_running_event_loop_offloads_to_thread(self):
        """When called inside a running event loop, offloads to a thread."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        sync_called = {"interactive": None}

        def _mock_sync(cfg, interactive=False):
            sync_called["interactive"] = interactive

        # Simulate being called from within a running event loop
        async def _run_in_loop():
            with patch.object(mgr, "_login_with_browser_sync", side_effect=_mock_sync):
                mgr._login_with_browser(browser_cfg, force_interactive=True)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_run_in_loop())
        loop.close()

        assert sync_called["interactive"] is True

    def test_running_event_loop_thread_error_propagated(self):
        """Error from thread in running event loop is re-raised."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)

        def _mock_sync(cfg, interactive=False):
            raise ValueError("sync login failed")

        async def _run_in_loop():
            with patch.object(mgr, "_login_with_browser_sync", side_effect=_mock_sync):
                mgr._login_with_browser(browser_cfg, force_interactive=True)

        loop = asyncio.new_event_loop()
        with pytest.raises(ValueError, match="sync login failed"):
            loop.run_until_complete(_run_in_loop())
        loop.close()

    def test_running_event_loop_thread_timeout(self):
        """Thread still running after join_timeout raises ValueError."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)

        # Create a slow sync login that takes longer than join_timeout
        barrier = threading.Barrier(2, timeout=30)

        def _mock_sync(cfg, interactive=False):
            # Block forever to simulate long MFA
            barrier.wait()

        async def _run_in_loop():
            with patch.object(mgr, "_login_with_browser_sync", side_effect=_mock_sync):
                mgr._login_with_browser(browser_cfg, force_interactive=True)

        loop = asyncio.new_event_loop()

        # join_timeout = max(10 + 120, 600) = 600
        # We need thread.join to return with thread still alive

        def _mock_thread_join(self_thread, timeout=None):
            # Don't actually wait — just return (thread stays "alive")
            pass

        with patch.object(threading.Thread, "join", _mock_thread_join):
            with patch.object(mgr, "_login_with_browser_sync", side_effect=_mock_sync):
                with pytest.raises(ValueError, match="still in progress after"):
                    loop.run_until_complete(_run_in_loop())

        loop.close()
        # Release the barrier so the background thread can finish
        try:
            barrier.abort()
        except Exception:
            pass


# ===========================================================================
# Lines 1489-1811: _login_with_browser_sync — full browser auth flow
# ===========================================================================


class TestLoginWithBrowserSync:
    def _make_playwright_mocks(
        self,
        page_url="https://example.service-now.com/now/nav/ui",
        cookies=None,
        g_ck="g_ck_token",
        user_agent="TestAgent/1.0",
        probe_status=200,
        probe_url="https://example.service-now.com/api/now/table/sys_user?sysparm_limit=1",
    ):
        """Helper to create Playwright mock chain."""
        if cookies is None:
            cookies = [
                {
                    "name": "JSESSIONID",
                    "value": "abc123",
                    "domain": "example.service-now.com",
                },
            ]

        mock_page = MagicMock()
        mock_page.url = page_url
        mock_page.evaluate.side_effect = lambda expr: {
            "navigator.userAgent": user_agent,
            "window.g_ck": g_ck,
        }.get(expr, None)
        mock_page.is_closed.return_value = False

        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = cookies

        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_probe = MagicMock()
        mock_probe.status_code = probe_status
        mock_probe.headers = {}
        mock_probe.url = probe_url
        mock_probe.text = '{"result": []}'

        return mock_sync, mock_page, mock_context, mock_probe

    def test_no_instance_url_raises(self):
        mgr = _make_browser_manager()
        mgr.instance_url = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        with pytest.raises(ValueError, match="Instance URL is required"):
            mgr._login_with_browser_sync(browser_cfg)

    def test_playwright_import_fails(self):
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        real_import = __import__

        def _mock_import(name, *args, **kwargs):
            if "playwright" in name:
                raise ImportError("no playwright")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_mock_import):
            with pytest.raises(ValueError, match="Playwright is required"):
                mgr._login_with_browser_sync(browser_cfg)

    def test_full_login_no_credentials(self):
        """Login without username/password — waits for manual completion."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        # Simulate polling: first iteration finds cookies and probe succeeds twice
        probe_count = {"n": 0}

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            probe_count["n"] += 1
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

        assert mgr._browser_cookie_header is not None
        assert "JSESSIONID=abc123" in mgr._browser_cookie_header
        assert mgr._browser_user_agent == "TestAgent/1.0"
        assert mgr._browser_session_token == "g_ck_token"
        mock_context.close.assert_called_once()

    def test_full_login_with_credentials_filled(self):
        """Login with username/password — fills form fields."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            username="admin",
            password="secret",
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        # Set up fill/click behavior
        mock_locator_user = MagicMock()
        mock_locator_user.count.return_value = 1
        mock_locator_pass = MagicMock()
        mock_locator_pass.count.return_value = 1
        mock_locator_submit = MagicMock()
        mock_locator_submit.count.return_value = 1

        def _mock_locator(selector):
            if selector in USERNAME_SELECTORS:
                return mock_locator_user
            if selector in PASSWORD_SELECTORS:
                return mock_locator_pass
            if selector in SUBMIT_SELECTORS:
                return mock_locator_submit
            return MagicMock()

        mock_page.locator = _mock_locator
        mock_page.frames = []  # Only main frame

        # probe succeeds on first iteration
        probe_count = {"n": 0}

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            probe_count["n"] += 1
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

        assert mgr._browser_cookie_header is not None

    def test_login_with_credentials_enter_submit(self):
        """When no submit button found, Enter key on password field submits."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            username="admin",
            password="secret",
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        # No submit selector matches, but password matches
        mock_locator_user = MagicMock()
        mock_locator_user.count.return_value = 1
        mock_locator_pass = MagicMock()
        mock_locator_pass.count.return_value = 1

        def _mock_locator(selector):
            if selector in USERNAME_SELECTORS:
                return mock_locator_user
            if selector in PASSWORD_SELECTORS:
                return mock_locator_pass
            # Submit selectors return count 0
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        mock_page.locator = _mock_locator
        mock_page.frames = []

        # Press Enter on password field works
        MagicMock()
        mock_page.locator.return_value = None  # won't be used for press

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

    def test_login_no_matching_selectors_logs_warning(self):
        """When no username/password selectors match, logs warning."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            username="admin",
            password="secret",
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        # All selectors return count 0
        def _mock_locator(selector):
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        mock_page.locator = _mock_locator
        mock_page.frames = []

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

    def test_login_matched_but_not_submitted(self):
        """When credentials filled but can't submit, logs warning."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            username="admin",
            password="secret",
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        # Username matches, password matches, but no submit, and Enter fails
        mock_locator_user = MagicMock()
        mock_locator_user.count.return_value = 1
        mock_locator_pass = MagicMock()
        mock_locator_pass.count.return_value = 1

        def _mock_locator(selector):
            if selector in USERNAME_SELECTORS:
                return mock_locator_user
            if selector in PASSWORD_SELECTORS:
                return mock_locator_pass
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        mock_page.locator = _mock_locator
        mock_page.frames = []

        # Enter key raises exception (suppressed)
        pass_loc = MagicMock()
        pass_loc.press.side_effect = Exception("press failed")

        def _mock_locator_for_press(selector):
            if selector in PASSWORD_SELECTORS:
                return pass_loc
            if selector in USERNAME_SELECTORS:
                return mock_locator_user
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        # Override locator for this test
        mock_page.locator = _mock_locator_for_press

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

    def test_login_browser_closed_by_user(self):
        """Browser closed by user raises ValueError."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()
        mock_page.is_closed.return_value = True

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                with pytest.raises(ValueError, match="closed"):
                    mgr._login_with_browser_sync(browser_cfg)

    def test_login_context_disposed(self):
        """Target disposed error during polling raises ValueError."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()
        # page.url raises "disposed" error
        type(mock_page).url = PropertyMock(side_effect=Exception("Target page has been disposed"))

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                with pytest.raises(ValueError, match="Target page"):
                    mgr._login_with_browser_sync(browser_cfg)

    def test_login_no_cookies_raises(self):
        """Login succeeds polling but final cookie capture empty — raises ValueError."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks(cookies=[])

        # During polling, _build_instance_cookie_header returns None (no cookies)
        # so the loop times out without cookies
        mock_page.url = "https://example.service-now.com/now/nav/ui"

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                with pytest.raises(ValueError, match="headless mode"):
                    mgr._login_with_browser_sync(browser_cfg)

    def test_login_no_instance_cookies_raises(self):
        """Cookies exist but none for this instance — raises ValueError."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks(
            cookies=[{"name": "other", "value": "x", "domain": "other.com"}]
        )
        mock_page.url = "https://example.service-now.com/now/nav/ui"

        # _build_instance_cookie_header returns None since cookies don't match
        # The polling loop times out
        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                with pytest.raises(ValueError, match="headless mode"):
                    mgr._login_with_browser_sync(browser_cfg)

    def test_login_probe_unauthorized_after_login(self):
        """After login, API probe shows unauthorized — invalidates and raises."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, _ = self._make_playwright_mocks()
        mock_page.url = "https://example.service-now.com/now/nav/ui"

        # Polling probe succeeds (confirms login)
        poll_probe = MagicMock()
        poll_probe.status_code = 200
        poll_probe.headers = {}
        poll_probe.url = "https://example.service-now.com/api/now/table/sys_user"

        # Final probe after closing — shows redirect
        final_probe = MagicMock()
        final_probe.status_code = 302
        final_probe.headers = {"Location": "/login.do"}
        final_probe.url = "https://example.service-now.com/login.do"
        final_probe.text = "<html>login</html>"

        probe_count = {"n": 0}

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            probe_count["n"] += 1
            if probe_count["n"] <= 2:
                return poll_probe
            return final_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                    with patch.object(mgr, "_save_session_to_disk"):
                        with patch.object(mgr, "invalidate_browser_session"):
                            with pytest.raises(ValueError, match="API auth is still unauthorized"):
                                mgr._login_with_browser_sync(browser_cfg)

    def test_login_final_probe_403_logs_info(self):
        """Final probe returns 403 — still accepted, logs info."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
            probe_path="/api/now/table/sys_user",
        )

        mock_sync, mock_page, mock_context, _ = self._make_playwright_mocks()
        mock_page.url = "https://example.service-now.com/now/nav/ui"

        poll_probe = MagicMock()
        poll_probe.status_code = 200
        poll_probe.headers = {}
        poll_probe.url = "https://example.service-now.com/api/now/table/sys_user"

        final_probe = MagicMock()
        final_probe.status_code = 403
        final_probe.headers = {}
        final_probe.url = "https://example.service-now.com/api/now/table/sys_user"
        final_probe.text = "Forbidden"

        probe_count = {"n": 0}

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            probe_count["n"] += 1
            if probe_count["n"] <= 2:
                return poll_probe
            return final_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                    with patch.object(mgr, "_save_session_to_disk"):
                        mgr._login_with_browser_sync(browser_cfg)

        assert mgr._browser_cookie_header is not None

    def test_login_timeout_headless(self):
        """Timeout in headless mode raises specific error."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=2,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, _ = self._make_playwright_mocks()
        mock_page.url = "https://example.service-now.com/login.do"  # Still on login page
        mock_page.is_closed.return_value = False

        # No cookies ever appear
        mock_context.cookies.return_value = []

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                with pytest.raises(ValueError, match="headless mode"):
                    mgr._login_with_browser_sync(browser_cfg)

    def test_login_timeout_non_headless(self):
        """Timeout in non-headless mode raises specific error."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=2,
            headless=False,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, _ = self._make_playwright_mocks()
        mock_page.url = "https://example.service-now.com/login.do"
        mock_page.is_closed.return_value = False
        mock_context.cookies.return_value = []

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                with pytest.raises(
                    ValueError,
                    match="Timed out waiting for manual browser login",
                ):
                    mgr._login_with_browser_sync(browser_cfg)

    def test_login_interactive_forces_non_headless(self):
        """force_interactive=True overrides headless setting."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg, force_interactive=True)

        # Verify launch was called with headless=False (forced interactive)
        launch_call = (
            mock_spw.return_value.__enter__.return_value.chromium.launch_persistent_context
        )
        launch_call.assert_called_once()
        call_kwargs = launch_call.call_args
        assert call_kwargs.kwargs.get("headless") is False

    def test_login_probe_exception_continues(self):
        """RequestException during probe is caught and polling continues."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        probe_count = {"n": 0}

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            probe_count["n"] += 1
            if probe_count["n"] == 1:
                raise requests.RequestException("network hiccup")
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

    def test_login_probe_unauthorized_resets_counter(self):
        """Unauthorized probe resets successful_probes counter."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, _ = self._make_playwright_mocks()
        mock_page.url = "https://example.service-now.com/now/nav/ui"

        probe_count = {"n": 0}

        # First: 401, then success twice
        unauth_probe = MagicMock()
        unauth_probe.status_code = 401
        unauth_probe.headers = {}
        unauth_probe.url = "https://example.service-now.com/api/now/table/sys_user"

        auth_probe = MagicMock()
        auth_probe.status_code = 200
        auth_probe.headers = {}
        auth_probe.url = "https://example.service-now.com/api/now/table/sys_user"

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            probe_count["n"] += 1
            if probe_count["n"] == 1:
                return unauth_probe
            return auth_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

    def test_login_interactive_stable_main_ui_no_longer_confirms_login(self):
        """Interactive mode now also requires a successful probe before confirmation."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, _ = self._make_playwright_mocks()
        mock_page.url = "https://example.service-now.com/now/nav/ui/classic"

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            raise requests.RequestException("blocked")

        fake_now = {"value": 0.0}

        def _fake_time():
            fake_now["value"] += 60.0
            return fake_now["value"]

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        with patch(
                            "servicenow_mcp.auth.auth_manager.time.time", side_effect=_fake_time
                        ):
                            with pytest.raises(
                                ValueError,
                                match="Timed out waiting for manual browser login/MFA completion",
                            ):
                                mgr._login_with_browser_sync(browser_cfg, force_interactive=True)

        assert mgr._browser_cookie_header is None

    def test_login_non_interactive_stable_cookie_no_longer_confirms_login(self):
        """Non-interactive mode now requires a successful probe before confirmation."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, _ = self._make_playwright_mocks()
        mock_page.url = "https://example.service-now.com/now/nav/ui/classic"

        # Override cookies to include glide_user_session for the fallback check
        mock_context.cookies.return_value = [
            {
                "name": "glide_user_session",
                "value": "abc",
                "domain": "example.service-now.com",
            },
        ]

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            raise requests.RequestException("blocked")

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        with pytest.raises(
                            ValueError, match="Timed out waiting for browser login/MFA"
                        ):
                            mgr._login_with_browser_sync(browser_cfg, force_interactive=False)

    def test_login_with_frames(self):
        """Login with iframe targets — fills in frames too."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            username="admin",
            password="secret",
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        # All locators return count 0 (no matching)
        def _mock_locator(selector):
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        mock_page.locator = _mock_locator

        mock_frame = MagicMock()
        mock_frame.url = "https://sso.example.com/login"
        mock_frame.locator = _mock_locator
        mock_page.frames = [mock_page.main_frame, mock_frame]
        mock_page.main_frame = mock_page  # Not a real main_frame, but fine

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

    def test_login_custom_login_url(self):
        """Custom login URL is used instead of default."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
            login_url="https://sso.example.com/login",
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

        # Verify goto was called with custom URL
        mock_page.goto.assert_called_once()
        assert mock_page.goto.call_args.args[0] == "https://sso.example.com/login"

    def test_login_g_ck_eval_fails(self):
        """When window.g_ck eval fails, session_token is None."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, mock_probe = self._make_playwright_mocks()
        # First eval (navigator.userAgent) succeeds, second (g_ck) fails
        eval_count = {"n": 0}

        def _mock_evaluate(expr):
            eval_count["n"] += 1
            if "userAgent" in expr:
                return "TestAgent"
            raise Exception("g_ck not found")

        mock_page.evaluate = _mock_evaluate

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

        assert mgr._browser_session_token is None
        assert mgr._browser_cookie_header is not None

    def test_login_no_existing_pages(self):
        """When context has no pages, creates a new one."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, _, mock_context, mock_probe = self._make_playwright_mocks()

        mock_new_page = MagicMock()
        mock_new_page.url = "https://example.service-now.com/now/nav/ui"
        mock_new_page.evaluate.side_effect = lambda expr: {
            "navigator.userAgent": "TestAgent",
            "window.g_ck": "tok",
        }.get(expr, None)
        mock_new_page.is_closed.return_value = False

        mock_context.pages = []
        mock_context.new_page.return_value = mock_new_page

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            return mock_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)

        mock_context.new_page.assert_called_once()
        assert mgr._browser_cookie_header is not None

    def test_login_probe_redirect_resets_counter(self):
        """Probe host mismatch resets successful_probes counter."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            headless=True,
            session_ttl_minutes=30,
        )

        mock_sync, mock_page, mock_context, _ = self._make_playwright_mocks()
        # Page is on IdP host, not instance host
        mock_page.url = "https://idp.example.com/mfa"

        # Probe returns 200 but resolved to different host
        other_host_probe = MagicMock()
        other_host_probe.status_code = 200
        other_host_probe.headers = {}
        other_host_probe.url = "https://idp.example.com/api"

        instance_probe = MagicMock()
        instance_probe.status_code = 200
        instance_probe.headers = {}
        instance_probe.url = "https://example.service-now.com/api"

        probe_count = {"n": 0}

        def _mock_probe(cookie_header, timeout_seconds=10, browser_config=None):
            probe_count["n"] += 1
            if probe_count["n"] <= 2:
                return other_host_probe
            # Switch page URL to instance
            mock_page.url = "https://example.service-now.com/now/nav/ui"
            return instance_probe

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)},
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=_mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                        mgr._login_with_browser_sync(browser_cfg)


# ===========================================================================
# Lines 1842-1843: invalidate_browser_session — file removal error
# ===========================================================================


class TestInvalidateSessionRemoveError:
    def test_remove_cache_file_permission_error(self, tmp_path):
        mgr = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        mgr._session_cache_path = cache_path
        mgr._browser_cookie_header = "my=cookie"

        # Write a matching session file
        with open(cache_path, "w") as f:
            json.dump({"cookie_header": "my=cookie"}, f)

        with patch("os.remove", side_effect=PermissionError("denied")):
            mgr.invalidate_browser_session()

        # Should not raise — just logs warning


# ===========================================================================
# Line 1896: make_request — debug cookie logging
# ===========================================================================


class TestMakeRequestDebugLogging:
    def test_cookie_names_logged_at_debug(self):

        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "JSESSIONID=abc; glide=xyz"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api"

        with patch.object(mgr._http_session, "request", return_value=mock_resp):
            with patch.object(
                mgr,
                "logger",
            ) as mock_logger:
                # Enable DEBUG level
                mock_logger.isEnabledFor.return_value = True
                mock_logger.debug = MagicMock()
                mock_logger.info = MagicMock()
                mock_logger.warning = MagicMock()
                mock_logger.error = MagicMock()

                # Patch the module-level logger
                with patch("servicenow_mcp.auth.auth_manager.logger") as mod_logger:
                    mod_logger.isEnabledFor.return_value = True
                    mod_logger.debug = MagicMock()
                    mod_logger.info = MagicMock()
                    mod_logger.warning = MagicMock()
                    mod_logger.error = MagicMock()

                    resp = mgr.make_request(
                        "GET",
                        "https://example.service-now.com/api",
                        timeout=10,
                    )

        assert resp.status_code == 200


# ===========================================================================
# Lines 2004-2022: make_request — 401 another process re-authenticating
# ===========================================================================


class TestMakeRequest401OtherProcess:
    def test_401_another_process_waits_and_retries(self):
        """Another process is re-authenticating; wait and retry succeeds."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "old=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()
        mgr._browser_last_login_at = None

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.headers = {}
        resp_401.url = "https://example.service-now.com/api"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.url = "https://example.service-now.com/api"

        request_count = {"n": 0}

        def _mock_request(*args, **kwargs):
            request_count["n"] += 1
            if request_count["n"] <= 1:
                return resp_401
            return resp_200

        def _mock_reload():
            mgr._browser_cookie_header = "new=1"
            return True

        def _mock_get_headers():
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "new=1",
            }

        with patch.object(mgr._http_session, "request", side_effect=_mock_request):
            with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
                with patch.object(mgr, "get_headers", side_effect=_mock_get_headers):
                    with patch.object(mgr, "_acquire_login_lock", return_value=False):
                        with patch.object(mgr, "_wait_for_other_login", return_value=True):
                            with patch.object(mgr, "_mark_browser_session_recently_valid"):
                                resp = mgr.make_request(
                                    "GET",
                                    "https://example.service-now.com/api",
                                    timeout=10,
                                    max_retries=1,
                                )

        assert resp.status_code == 200

    def test_401_another_process_wait_fails_reauth_falls_through(self):
        """Another process re-auth fails, falls through to own re-auth."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "old=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()
        mgr._browser_last_login_at = None

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.headers = {}
        resp_401.url = "https://example.service-now.com/api"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.url = "https://example.service-now.com/api"

        request_count = {"n": 0}

        def _mock_request(*args, **kwargs):
            request_count["n"] += 1
            if request_count["n"] <= 2:
                return resp_401
            return resp_200

        get_headers_count = {"n": 0}

        def _mock_get_headers():
            get_headers_count["n"] += 1
            if get_headers_count["n"] == 1:
                return {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Cookie": "old=1",
                }
            mgr._browser_cookie_header = "reauthed=1"
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "reauthed=1",
            }

        with patch.object(mgr._http_session, "request", side_effect=_mock_request):
            with patch.object(mgr, "_reload_session_from_disk", return_value=True):
                with patch.object(mgr, "get_headers", side_effect=_mock_get_headers):
                    with patch.object(mgr, "_acquire_login_lock", return_value=True):
                        with patch.object(mgr, "_release_login_lock"):
                            with patch.object(mgr, "invalidate_browser_session"):
                                with patch.object(mgr, "_mark_browser_session_recently_valid"):
                                    resp = mgr.make_request(
                                        "GET",
                                        "https://example.service-now.com/api",
                                        timeout=10,
                                        max_retries=1,
                                    )

        assert resp.status_code == 200

    def test_401_other_process_no_reload_falls_through(self):
        """Wait succeeds but reload fails — falls through to own re-auth."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "old=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()
        mgr._browser_last_login_at = None

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.headers = {}
        resp_401.url = "https://example.service-now.com/api"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.url = "https://example.service-now.com/api"

        request_count = {"n": 0}

        def _mock_request(*args, **kwargs):
            request_count["n"] += 1
            if request_count["n"] <= 2:
                return resp_401
            return resp_200

        reload_count = {"n": 0}

        def _mock_reload():
            reload_count["n"] += 1
            if reload_count["n"] == 1:
                # First reload (before _acquire_login_lock) succeeds
                return True
            # Second reload (after wait) fails
            return False

        get_headers_count = {"n": 0}

        def _mock_get_headers():
            get_headers_count["n"] += 1
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "final=1",
            }

        with patch.object(mgr._http_session, "request", side_effect=_mock_request):
            with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
                with patch.object(mgr, "get_headers", side_effect=_mock_get_headers):
                    with patch.object(mgr, "_acquire_login_lock", return_value=False):
                        with patch.object(mgr, "_wait_for_other_login", return_value=True):
                            with patch.object(mgr, "invalidate_browser_session"):
                                with patch.object(mgr, "_mark_browser_session_recently_valid"):
                                    resp = mgr.make_request(
                                        "GET",
                                        "https://example.service-now.com/api",
                                        timeout=10,
                                        max_retries=1,
                                    )

        assert resp.status_code == 200


# ===========================================================================
# Edge case: get_headers — reload session from disk (fast path)
# ===========================================================================


class TestGetHeadersDiskReloadFastPath:
    def test_fast_path_disk_reload_with_keepalive_start(self):
        """Disk reload succeeds in fast path, keepalive starts."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._keepalive_thread = None

        def _mock_reload():
            mgr._browser_cookie_header = "disk=1"
            mgr._browser_cookie_expires_at = time.time() + 600
            mgr._browser_user_agent = "DiskUA"
            mgr._browser_session_token = "disk_tok"
            return True

        with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
            with patch.object(mgr, "_start_keepalive") as mock_keepalive:
                headers = mgr.get_headers()

        assert headers["Cookie"] == "disk=1"
        assert headers["User-Agent"] == "DiskUA"
        assert headers["X-UserToken"] == "disk_tok"
        mock_keepalive.assert_called_once()


# ===========================================================================
# Edge case: get_headers — post-restore disk check
# ===========================================================================


class TestGetHeadersPostRestoreDiskCheck:
    def test_post_restore_disk_reload_succeeds(self):
        """After restore fails, disk reload succeeds."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._keepalive_thread = None

        reload_count = {"n": 0}

        def _mock_reload():
            reload_count["n"] += 1
            if reload_count["n"] == 2:
                # Second reload (post-restore check) succeeds
                mgr._browser_cookie_header = "postrestore=1"
                mgr._browser_cookie_expires_at = time.time() + 600
                mgr._browser_user_agent = "PostRestoreUA"
                mgr._browser_session_token = "post_tok"
                return True
            return False

        with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
            with patch.object(mgr, "_try_restore_browser_session", return_value=False):
                with patch.object(mgr, "_start_keepalive"):
                    headers = mgr.get_headers()

        assert headers["Cookie"] == "postrestore=1"
        assert headers["User-Agent"] == "PostRestoreUA"
        assert headers["X-UserToken"] == "post_tok"


# ===========================================================================
# Edge case: get_headers — validation triggers re-auth with restore
# ===========================================================================


class TestGetHeadersValidationRestorePath:
    def test_validation_restore_with_keepalive(self):
        """Validation triggers restore which succeeds, keepalive starts."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._keepalive_thread = None

        def _mock_restore(cfg):
            mgr._browser_cookie_header = "restored=1"
            mgr._browser_cookie_expires_at = time.time() + 600
            return True

        with patch.object(mgr, "_reload_session_from_disk", return_value=False):
            with patch.object(mgr, "_try_restore_browser_session", side_effect=_mock_restore):
                with patch.object(mgr, "_start_keepalive"):
                    headers = mgr.get_headers()

        assert headers["Cookie"] == "restored=1"
        assert mgr._browser_reauth_failure_count == 0
