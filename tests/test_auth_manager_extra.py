"""Extra tests for auth_manager.py — targeting uncovered browser auth and lock paths."""

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.auth.auth_manager import (
    AuthManager,
    _click_first_matching,
    _fill_first_matching,
    _launch_persistent_with_retry,
    _target_label,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, BrowserAuthConfig


def _make_browser_manager(
    instance_url: str = "https://example.service-now.com",
    session_ttl_minutes: int = 30,
) -> AuthManager:
    cfg = AuthConfig(
        type=AuthType.BROWSER,
        browser=BrowserAuthConfig(
            headless=False,
            timeout_seconds=10,
            session_ttl_minutes=session_ttl_minutes,
        ),
    )
    with (
        patch.object(AuthManager, "_ensure_playwright_ready"),
        patch.object(AuthManager, "_load_session_from_disk"),
    ):
        manager = AuthManager(cfg, instance_url)
    return manager


class TestLaunchPersistentWithRetry:
    @patch("servicenow_mcp.auth.auth_manager.time.sleep")
    def test_retries_on_profile_lock(self, mock_sleep):
        mock_chromium = MagicMock()

        exc = Exception("Chromium profile is already in use")
        mock_chromium.launch_persistent_context.side_effect = [
            exc,
            MagicMock(),
        ]

        result = _launch_persistent_with_retry(mock_chromium, "/tmp/test_profile", headless=True)
        assert result is not None
        assert mock_sleep.called

    @patch("servicenow_mcp.auth.auth_manager.time.sleep")
    def test_raises_after_max_attempts(self, mock_sleep):
        mock_chromium = MagicMock()
        exc = Exception("Chromium profile is already in use")
        mock_chromium.launch_persistent_context.side_effect = exc

        with pytest.raises(Exception, match="profile"):
            _launch_persistent_with_retry(mock_chromium, "/tmp/test_profile", headless=True)

    def test_raises_non_lock_error_immediately(self):
        mock_chromium = MagicMock()
        exc = Exception("Some other error")
        mock_chromium.launch_persistent_context.side_effect = exc

        with pytest.raises(Exception, match="Some other error"):
            _launch_persistent_with_retry(mock_chromium, "/tmp/test_profile", headless=True)


class TestFillFirstMatching:
    def test_fills_first_selector(self):
        target = MagicMock()
        target.locator.return_value.count.return_value = 1
        result = _fill_first_matching(target, ("input#a", "input#b"), "value")
        assert result == "input#a"
        target.fill.assert_called_once_with("input#a", "value")

    def test_skips_failed_fill(self):
        target = MagicMock()
        locator_mock = MagicMock()
        locator_mock.count.return_value = 1
        target.locator.return_value = locator_mock
        target.fill.side_effect = [Exception("fill failed"), None]
        result = _fill_first_matching(target, ("input#a", "input#b"), "value")
        assert result == "input#b"

    def test_returns_none_if_nothing_found(self):
        target = MagicMock()
        target.locator.return_value.count.return_value = 0
        result = _fill_first_matching(target, ("input#a",), "value")
        assert result is None


class TestClickFirstMatching:
    def test_clicks_first_selector(self):
        target = MagicMock()
        target.locator.return_value.count.return_value = 1
        result = _click_first_matching(target, ("button#a", "button#b"))
        assert result == "button#a"
        target.click.assert_called_once_with("button#a")

    def test_skips_failed_click(self):
        target = MagicMock()
        target.locator.return_value.count.return_value = 1
        target.click.side_effect = [Exception("click failed"), None]
        result = _click_first_matching(target, ("button#a", "button#b"))
        assert result == "button#b"

    def test_returns_none_if_nothing_found(self):
        target = MagicMock()
        target.locator.return_value.count.return_value = 0
        result = _click_first_matching(target, ("button#a",))
        assert result is None


class TestTargetLabel:
    def test_main_frame(self):
        target = MagicMock()
        target.url = "https://example.service-now.com/page"
        assert "main" in _target_label(target, 0)

    def test_child_frame(self):
        target = MagicMock()
        target.url = "https://example.service-now.com/iframe"
        assert "frame[1]" in _target_label(target, 1)

    def test_no_url(self):
        target = MagicMock(spec=[])
        assert "main" in _target_label(target, 0)


class TestLoginLock:
    def test_acquire_and_release(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        assert mgr._acquire_login_lock() is True
        assert os.path.exists(mgr._login_lock_path)

        mgr._release_login_lock()
        assert not os.path.exists(mgr._login_lock_path)

    def test_acquire_fails_on_active_lock(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        with open(mgr._login_lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": time.time()}, f)

        assert mgr._acquire_login_lock() is False

    def test_acquire_removes_stale_lock(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        stale_time = time.time() - 600
        with open(mgr._login_lock_path, "w") as f:
            json.dump({"pid": 99999999, "timestamp": stale_time}, f)

        assert mgr._acquire_login_lock() is True

    def test_release_skips_other_pid(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        with open(mgr._login_lock_path, "w") as f:
            json.dump({"pid": 12345, "timestamp": time.time()}, f)

        mgr._release_login_lock()
        assert os.path.exists(mgr._login_lock_path)

    def test_acquire_corrupt_lock_overwrites(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        with open(mgr._login_lock_path, "w") as f:
            f.write("not json")

        assert mgr._acquire_login_lock() is True


class TestSessionCachePath:
    def test_basic_auth_username_included(self):
        cfg = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="john.doe@test.com", password="secret"),
        )
        mgr = AuthManager(cfg, "https://myinstance.service-now.com")
        assert "john_doe_at_test_com" in mgr._session_cache_path

    def test_browser_username_included(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(username="admin@test.com"),
        )
        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_load_session_from_disk"),
        ):
            mgr = AuthManager(cfg, "https://myinstance.service-now.com")
        assert "admin_at_test_com" in mgr._session_cache_path

    def test_instance_host_in_path(self):
        mgr = _make_browser_manager()
        assert "example" in mgr._session_cache_path and "service-now" in mgr._session_cache_path


class TestDefaultUserDataDir:
    def test_returns_dir(self):
        mgr = _make_browser_manager()
        result = mgr._get_default_user_data_dir()
        assert "profile_" in result

    def test_custom_dir(self, tmp_path):
        custom = tmp_path / "custom" / "path"
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(user_data_dir=str(custom)),
        )
        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_load_session_from_disk"),
        ):
            mgr = AuthManager(cfg, "https://test.service-now.com")
        # A configured dir is a BASE: profile is host+user scoped beneath it, and
        # the session JSON sits in the same base — same structure as the default.
        resolved = mgr._resolve_user_data_dir(cfg.browser)
        assert resolved == str(custom / "profile_test_service-now_com")
        assert mgr._session_cache_path == str(custom / "session_test_service-now_com.json")

    def test_shared_base_dir_isolates_by_host_and_user(self, tmp_path):
        # The footgun killer: even with ONE shared user_data_dir, two instances
        # (different hosts) and two users never share a Chromium profile.
        shared = str(tmp_path / "shared")

        def _mgr(url, user):
            cfg = AuthConfig(
                type=AuthType.BROWSER,
                browser=BrowserAuthConfig(user_data_dir=shared, username=user),
            )
            with (
                patch.object(AuthManager, "_ensure_playwright_ready"),
                patch.object(AuthManager, "_load_session_from_disk"),
            ):
                return AuthManager(cfg, url)

        dev = _mgr("https://dev.service-now.com", None)
        test = _mgr("https://test.service-now.com", None)
        same_host_other_user = _mgr("https://dev.service-now.com", "alice")

        dev_profile = dev._resolve_user_data_dir(dev.config.browser)
        test_profile = test._resolve_user_data_dir(test.config.browser)
        alice_profile = same_host_other_user._resolve_user_data_dir(
            same_host_other_user.config.browser
        )
        # All three distinct, all under the shared base.
        assert dev_profile != test_profile != alice_profile
        assert dev_profile != alice_profile
        for p in (dev_profile, test_profile, alice_profile):
            assert p.startswith(shared + os.sep)
        # Sessions isolated too.
        assert dev._session_cache_path != test._session_cache_path
        assert dev._session_cache_path != same_host_other_user._session_cache_path


class TestSaveSessionToDisk:
    def test_skips_non_browser(self, tmp_path):
        cfg = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="secret"),
        )
        mgr = AuthManager(cfg, "https://test.service-now.com")
        mgr._session_cache_path = str(tmp_path / "session.json")
        mgr._browser_cookie_header = "cookie"
        mgr._save_session_to_disk()
        assert not os.path.exists(mgr._session_cache_path)

    def test_saves_browser_session(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")
        mgr._browser_cookie_header = "test=cookie"
        mgr._browser_user_agent = "TestAgent"
        mgr._browser_session_token = "tok123"
        mgr._browser_cookie_expires_at = time.time() + 3600
        mgr._session_disk_hash = None

        mgr._save_session_to_disk()
        assert os.path.exists(mgr._session_cache_path)
        data = json.loads(open(mgr._session_cache_path).read())
        assert data["cookie_header"] == "test=cookie"

    def test_skips_identical_content(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")
        mgr._browser_cookie_header = "test=cookie"
        mgr._browser_user_agent = "TestAgent"
        mgr._browser_session_token = "tok123"
        mgr._browser_cookie_expires_at = time.time() + 3600

        mgr._save_session_to_disk()
        first_mtime = os.path.getmtime(mgr._session_cache_path)
        time.sleep(0.05)
        mgr._save_session_to_disk()
        assert os.path.getmtime(mgr._session_cache_path) == first_mtime


class TestLoadSessionFromDisk:
    def test_no_cache_file(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "nonexistent.json")
        mgr._load_session_from_disk()
        assert mgr._browser_cookie_header is None

    def test_loads_valid_session(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")

        data = {
            "cookie_header": "test=cookie",
            "user_agent": "TestAgent",
            "session_token": "tok123",
            "expires_at": time.time() + 3600,
            "instance_url": "https://example.service-now.com",
        }
        with open(mgr._session_cache_path, "w") as f:
            json.dump(data, f)

        mgr._load_session_from_disk()
        assert mgr._browser_cookie_header == "test=cookie"
        assert mgr._browser_user_agent == "TestAgent"

    def test_rejects_wrong_instance(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")

        data = {
            "cookie_header": "test=cookie",
            "instance_url": "https://other-instance.service-now.com",
            "expires_at": time.time() + 3600,
        }
        with open(mgr._session_cache_path, "w") as f:
            json.dump(data, f)

        mgr._load_session_from_disk()
        assert mgr._browser_cookie_header is None

    def test_rejects_empty_cookie(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")

        data = {
            "cookie_header": "",
            "instance_url": "https://example.service-now.com",
            "expires_at": time.time() + 3600,
        }
        with open(mgr._session_cache_path, "w") as f:
            json.dump(data, f)

        mgr._load_session_from_disk()
        assert mgr._browser_cookie_header is None

    def test_expired_session_probes_server(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")

        data = {
            "cookie_header": "test=expired",
            "user_agent": "TestAgent",
            "session_token": None,
            "expires_at": time.time() - 100,
            "instance_url": "https://example.service-now.com",
        }
        with open(mgr._session_cache_path, "w") as f:
            json.dump(data, f)

        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "https://example.service-now.com/login.do"}
        mock_response.text = "<html>login</html>"
        mock_response.url = "https://example.service-now.com/login.do"

        with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_response):
            mgr._load_session_from_disk()

        assert mgr._browser_cookie_header is None

    def test_expired_but_valid_session(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")

        data = {
            "cookie_header": "test=valid",
            "user_agent": "TestAgent",
            "session_token": "tok",
            "expires_at": time.time() - 100,
            "instance_url": "https://example.service-now.com",
        }
        with open(mgr._session_cache_path, "w") as f:
            json.dump(data, f)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"result": []}'
        mock_response.headers = {}

        with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_response):
            mgr._load_session_from_disk()

        assert mgr._browser_cookie_header == "test=valid"

    def test_expired_probe_exception(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")

        data = {
            "cookie_header": "test=probe_fail",
            "user_agent": "TestAgent",
            "session_token": None,
            "expires_at": time.time() - 100,
            "instance_url": "https://example.service-now.com",
        }
        with open(mgr._session_cache_path, "w") as f:
            json.dump(data, f)

        with patch.object(
            mgr, "_probe_browser_api_with_cookie", side_effect=Exception("probe error")
        ):
            mgr._load_session_from_disk()

        assert mgr._browser_cookie_header is None


class TestWaitForOtherLogin:
    def test_timeout(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        with open(mgr._login_lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": time.time()}, f)

        with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
            result = mgr._wait_for_other_login(timeout=0)
        assert result is False

    def test_lock_released_no_session(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        with patch.object(mgr, "_reload_session_from_disk", return_value=False):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                result = mgr._wait_for_other_login(timeout=1)
        assert result is False

    def test_session_appears_while_waiting(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._login_lock_path = str(tmp_path / "test.lock")

        with patch.object(mgr, "_reload_session_from_disk", return_value=True):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                result = mgr._wait_for_other_login(timeout=1)
        assert result is True


class TestReloadSessionFromDisk:
    def test_no_cache_file(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "nonexistent.json")
        assert mgr._reload_session_from_disk() is False

    def test_reloads_valid_session(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session.json")

        data = {
            "cookie_header": "reloaded=cookie",
            "user_agent": "TestAgent",
            "session_token": "tok",
            "expires_at": time.time() + 3600,
            "instance_url": "https://example.service-now.com",
        }
        with open(mgr._session_cache_path, "w") as f:
            json.dump(data, f)

        assert mgr._reload_session_from_disk() is True
        assert mgr._browser_cookie_header == "reloaded=cookie"


class TestCleanupStaleSiblingFiles:
    """Cross-instance startup sweep — defends against the infinite-login state
    caused by stale lock/session files from prior crashed runs."""

    def test_removes_lock_with_dead_pid(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        sibling_lock = tmp_path / "session_other.lock"
        with open(sibling_lock, "w") as f:
            json.dump({"pid": 999_999, "timestamp": time.time()}, f)

        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path)):
            mgr._cleanup_stale_sibling_files()
        assert not sibling_lock.exists()

    def test_keeps_lock_with_alive_pid(self, tmp_path):
        """Critical: a peer terminal mid-MFA must not have its lock killed."""
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        peer_lock = tmp_path / "session_peer.lock"
        with open(peer_lock, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": time.time()}, f)

        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path)):
            mgr._cleanup_stale_sibling_files()
        assert peer_lock.exists()

    def test_keeps_old_lock_with_alive_pid(self, tmp_path):
        """Long-running login (slow MFA, debug mode) must survive sweep."""
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        peer_lock = tmp_path / "session_peer.lock"
        with open(peer_lock, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": time.time() - 3600}, f)

        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path)):
            mgr._cleanup_stale_sibling_files()
        assert peer_lock.exists(), "old-but-alive lock must NOT be swept"

    def test_removes_corrupt_lock(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        bad = tmp_path / "session_bad.lock"
        bad.write_text("not json {")
        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path)):
            mgr._cleanup_stale_sibling_files()
        assert not bad.exists()

    def test_removes_expired_sibling_session(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        old = tmp_path / "session_old.json"
        with open(old, "w") as f:
            json.dump({"expires_at": time.time() - 1000}, f)

        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path)):
            mgr._cleanup_stale_sibling_files()
        assert not old.exists()

    def test_keeps_active_session_even_if_expired(self, tmp_path):
        """The active instance's session file is owned by _load_session_from_disk."""
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        with open(mgr._session_cache_path, "w") as f:
            json.dump({"expires_at": time.time() - 1000}, f)

        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path)):
            mgr._cleanup_stale_sibling_files()
        assert os.path.exists(mgr._session_cache_path)

    def test_keeps_unexpired_sibling_session(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        good = tmp_path / "session_other.json"
        with open(good, "w") as f:
            json.dump({"expires_at": time.time() + 1000}, f)

        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path)):
            mgr._cleanup_stale_sibling_files()
        assert good.exists()

    def test_ignores_unrelated_files(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        unrelated = tmp_path / "profile_dir"
        unrelated.mkdir()
        readme = tmp_path / "README.txt"
        readme.write_text("hi")

        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path)):
            mgr._cleanup_stale_sibling_files()
        assert unrelated.exists()
        assert readme.exists()

    def test_handles_missing_cache_dir(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._session_cache_path = str(tmp_path / "session_active.json")
        mgr._login_lock_path = str(tmp_path / "session_active.lock")

        with patch.object(mgr, "_get_cache_dir", return_value=str(tmp_path / "does_not_exist")):
            mgr._cleanup_stale_sibling_files()  # Must not raise.


class TestProbeCoalescing:
    """Concurrent _has_reusable_browser_session calls must coalesce probes."""

    def _prime_session(self, mgr: AuthManager) -> None:
        mgr._browser_cookie_header = "JSESSIONID=abc"
        mgr._browser_cookie_expires_at = time.time() + 3600
        mgr._browser_last_validated_at = None
        mgr._browser_last_login_at = None

    def test_parallel_callers_run_probe_only_once(self):
        import threading

        mgr = _make_browser_manager()
        self._prime_session(mgr)
        cfg = mgr.config.browser
        probe_calls = []
        gate = threading.Event()

        def fake_probe(_cfg):
            probe_calls.append(time.time())
            gate.wait(timeout=2)
            mgr._browser_last_validated_at = time.time()
            return True

        results: list[bool] = []
        threads: list[threading.Thread] = []

        def worker():
            results.append(mgr._has_reusable_browser_session(cfg))

        with patch.object(mgr, "_is_browser_session_valid", side_effect=fake_probe):
            for _ in range(5):
                t = threading.Thread(target=worker)
                threads.append(t)
                t.start()
            time.sleep(0.05)  # let all 5 reach the probe lock
            gate.set()
            for t in threads:
                t.join(timeout=3)

        assert all(results)
        assert len(probe_calls) == 1, f"expected 1 probe, got {len(probe_calls)}"

    def test_skips_lock_when_recently_validated(self):
        mgr = _make_browser_manager()
        self._prime_session(mgr)
        mgr._browser_last_validated_at = time.time()  # fresh
        cfg = mgr.config.browser

        with patch.object(mgr, "_is_browser_session_valid") as probe:
            assert mgr._has_reusable_browser_session(cfg) is True
            probe.assert_not_called()

    def test_failed_probe_returns_false(self):
        mgr = _make_browser_manager()
        self._prime_session(mgr)
        cfg = mgr.config.browser

        with patch.object(mgr, "_is_browser_session_valid", return_value=False):
            assert mgr._has_reusable_browser_session(cfg) is False
