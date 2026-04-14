"""
Tests for browser-session behavior in AuthManager.
"""

import json
import os
import tempfile
import time
from typing import Any
from unittest.mock import MagicMock, patch

import requests

from servicenow_mcp.auth.auth_manager import (
    PASSWORD_SELECTORS,
    SUBMIT_SELECTORS,
    USERNAME_SELECTORS,
    AuthManager,
    _click_first_matching,
    _fill_first_matching,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig


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
        patch.object(AuthManager, "_start_keepalive"),
    ):
        manager = AuthManager(cfg, instance_url)
    manager._browser_cookie_header = "OLD=COOKIE"
    manager._browser_cookie_expires_at = time.time() + 600
    manager._browser_last_validated_at = None
    return manager


def _write_session_cache(
    path: str,
    cookie: str,
    expires_at: float,
    instance_url: str = "https://example.service-now.com",
    session_token: str = "g_ck_tok",
    user_agent: str = "TestAgent",
) -> None:
    """Helper to write a session cache file for testing."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {
                "cookie_header": cookie,
                "user_agent": user_agent,
                "session_token": session_token,
                "expires_at": expires_at,
                "instance_url": instance_url,
            },
            f,
        )


def test_browser_session_probe_401_triggers_interactive_relogin():
    manager = _make_browser_manager()

    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.is_redirect = True
    mock_response.headers = {"Location": "/login.do"}
    mock_response.url = "https://example.service-now.com/login.do"

    with patch.object(manager._http_session, "get", return_value=mock_response):
        with patch.object(manager, "_login_with_browser") as relogin:

            def _set_new_cookie(_cfg, force_interactive=False):
                assert force_interactive is True
                manager._browser_cookie_header = "NEW=COOKIE"
                manager._browser_cookie_expires_at = time.time() + 600
                manager._browser_last_validated_at = time.time()

            relogin.side_effect = _set_new_cookie

            headers = manager.get_headers()

    assert headers["Cookie"] == "NEW=COOKIE"
    assert relogin.call_count == 1


def test_browser_session_probe_request_error_triggers_interactive_relogin():
    manager = _make_browser_manager()

    with patch.object(
        manager._http_session,
        "get",
        side_effect=requests.RequestException("network issue"),
    ):
        with patch.object(manager, "_login_with_browser") as relogin:

            def _set_new_cookie(_cfg, force_interactive=False):
                assert force_interactive is True
                manager._browser_cookie_header = "NEW=COOKIE"
                manager._browser_cookie_expires_at = time.time() + 600
                manager._browser_last_validated_at = time.time()

            relogin.side_effect = _set_new_cookie
            headers = manager.get_headers()

    assert headers["Cookie"] == "NEW=COOKIE"
    assert relogin.call_count == 1


def test_browser_session_probe_403_without_login_redirect_keeps_session():
    manager = _make_browser_manager()

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.is_redirect = False
    mock_response.headers = {}
    mock_response.url = "https://example.service-now.com/api/now/table/sys_user"

    with patch.object(manager._http_session, "get", return_value=mock_response):
        with patch.object(manager, "_login_with_browser") as relogin:
            headers = manager.get_headers()

    assert headers["Cookie"] == "OLD=COOKIE"
    relogin.assert_not_called()


def test_browser_probe_path_query_string_is_split_into_url_and_params():
    cfg = AuthConfig(
        type=AuthType.BROWSER,
        browser=BrowserAuthConfig(
            probe_path="/api/now/table/incident?sysparm_limit=1&sysparm_fields=sys_id",
            timeout_seconds=10,
        ),
    )
    with (
        patch.object(AuthManager, "_ensure_playwright_ready"),
        patch.object(AuthManager, "_load_session_from_disk"),
        patch.object(AuthManager, "_start_keepalive"),
    ):
        manager = AuthManager(cfg, "https://example.service-now.com")

    with patch.object(manager._http_session, "get") as mock_get:
        manager._probe_browser_api_with_cookie(
            "a=b",
            timeout_seconds=5,
            browser_config=cfg.browser,
        )

    assert mock_get.call_args.args[0] == "https://example.service-now.com/api/now/table/incident"
    assert mock_get.call_args.kwargs["params"] == {
        "sysparm_limit": "1",
        "sysparm_fields": "sys_id",
    }


def test_reauth_cooldown_uses_attempt_time_not_last_login_time():
    manager = _make_browser_manager()

    # Recent successful login should not block re-auth attempt.
    manager._browser_last_login_at = time.time()
    manager._browser_last_reauth_attempt_at = None

    assert manager._can_attempt_browser_reauth() is True

    manager._mark_browser_reauth_attempt()
    assert manager._can_attempt_browser_reauth() is False


def test_make_request_replaces_cookies_on_retry_after_401():
    manager = _make_browser_manager()
    manager._browser_last_reauth_attempt_at = None

    first_response = MagicMock()
    first_response.status_code = 401
    first_response.headers = {"Location": "/login.do"}
    first_response.url = "https://example.service-now.com/login.do"
    second_response = MagicMock()
    second_response.status_code = 200

    with patch.object(
        manager,
        "get_headers",
        side_effect=[
            {"Accept": "application/json", "Content-Type": "application/json", "Cookie": "OLD=1"},
            {"Accept": "application/json", "Content-Type": "application/json", "Cookie": "NEW=1"},
        ],
    ):
        with patch.object(manager._http_session, "request") as mock_request:
            mock_request.side_effect = [first_response, second_response]

            response = manager.make_request(
                "GET",
                "https://example.service-now.com/api/now/table/sys_user",
                timeout=10,
                max_retries=1,
            )

    assert response.status_code == 200
    assert mock_request.call_count == 2
    assert mock_request.call_args_list[0].kwargs["cookies"] == {"OLD": "1"}
    assert mock_request.call_args_list[1].kwargs["cookies"] == {"NEW": "1"}


def test_make_request_success_marks_browser_session_recently_valid():
    manager = _make_browser_manager()
    manager._browser_last_validated_at = None

    success_response = MagicMock()
    success_response.status_code = 200
    success_response.headers = {}
    success_response.url = "https://example.service-now.com/api/now/table/sys_user"

    with patch.object(
        manager,
        "get_headers",
        return_value={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": "OLD=1",
        },
    ):
        with patch.object(manager._http_session, "request", return_value=success_response):
            before = time.time()
            manager.make_request(
                "GET",
                "https://example.service-now.com/api/now/table/sys_user",
                timeout=10,
                max_retries=1,
            )

    assert manager._browser_last_validated_at is not None
    assert manager._browser_last_validated_at >= before


class _FakeLocator:
    def __init__(self, exists: bool, target: Any, selector: str):
        self._exists = exists
        self._target = target
        self._selector = selector

    def count(self):
        return 1 if self._exists else 0

    def press(self, key: str):
        self._target.pressed.append((self._selector, key))


class _FakeTarget:
    def __init__(self, existing_selectors: set[str]):
        self._existing_selectors = existing_selectors
        self.filled: list[tuple[str, str]] = []
        self.clicked: list[str] = []
        self.pressed: list[tuple[str, str]] = []

    def locator(self, selector: str):
        return _FakeLocator(selector in self._existing_selectors, self, selector)

    def fill(self, selector: str, value: str):
        self.filled.append((selector, value))

    def click(self, selector: str):
        self.clicked.append(selector)


def test_fill_first_matching_uses_first_available_selector():
    target = _FakeTarget({USERNAME_SELECTORS[2], USERNAME_SELECTORS[4]})

    matched = _fill_first_matching(target, USERNAME_SELECTORS, "alice")

    assert matched == USERNAME_SELECTORS[2]
    assert target.filled == [(USERNAME_SELECTORS[2], "alice")]


def test_click_first_matching_uses_first_available_selector():
    target = _FakeTarget({SUBMIT_SELECTORS[3], SUBMIT_SELECTORS[4]})

    matched = _click_first_matching(target, SUBMIT_SELECTORS)

    assert matched == SUBMIT_SELECTORS[3]
    assert target.clicked == [SUBMIT_SELECTORS[3]]


def test_fill_first_matching_returns_none_when_password_selector_missing():
    target = _FakeTarget(set())

    matched = _fill_first_matching(target, PASSWORD_SELECTORS, "secret")

    assert matched is None
    assert target.filled == []


# ---------------------------------------------------------------------------
# Session sharing & keepalive resilience tests
# ---------------------------------------------------------------------------


class TestReloadSessionFromDisk:
    """Tests for _reload_session_from_disk() — cross-terminal session sync."""

    def test_reload_picks_up_fresher_cookies_from_disk(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        # Another terminal wrote a fresher session
        _write_session_cache(cache_path, "FRESH=COOKIE", time.time() + 1800)

        result = manager._reload_session_from_disk()

        assert result is True
        assert manager._browser_cookie_header == "FRESH=COOKIE"

    def test_reload_skips_when_same_cookies(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        # Disk has same cookies as in-memory
        _write_session_cache(cache_path, "OLD=COOKIE", time.time() + 1800)

        result = manager._reload_session_from_disk()

        assert result is False
        assert manager._browser_cookie_header == "OLD=COOKIE"

    def test_reload_extends_ttl_when_same_cookies_but_later_expiry(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path
        original_expires = manager._browser_cookie_expires_at

        # Another process extended TTL for same cookies
        new_expires = time.time() + 3600
        _write_session_cache(cache_path, "OLD=COOKIE", new_expires)

        result = manager._reload_session_from_disk()

        assert result is False  # Not "new" cookies
        assert manager._browser_cookie_expires_at == new_expires
        assert manager._browser_cookie_expires_at > original_expires

    def test_reload_skips_expired_disk_session(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        # Disk has different but expired cookies
        _write_session_cache(cache_path, "EXPIRED=COOKIE", time.time() - 100)

        result = manager._reload_session_from_disk()

        assert result is False
        assert manager._browser_cookie_header == "OLD=COOKIE"  # unchanged

    def test_reload_skips_wrong_instance(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(
            cache_path,
            "OTHER=COOKIE",
            time.time() + 1800,
            instance_url="https://other.service-now.com",
        )

        result = manager._reload_session_from_disk()

        assert result is False
        assert manager._browser_cookie_header == "OLD=COOKIE"

    def test_reload_skips_when_no_file(self, tmp_path):
        manager = _make_browser_manager()
        manager._session_cache_path = str(tmp_path / "nonexistent.json")

        result = manager._reload_session_from_disk()

        assert result is False

    def test_reload_handles_corrupt_file(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        with open(cache_path, "w") as f:
            f.write("not json{{{")

        result = manager._reload_session_from_disk()

        assert result is False
        assert manager._browser_cookie_header == "OLD=COOKIE"

    def test_reload_skips_empty_cookie_header(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(cache_path, "", time.time() + 1800)

        result = manager._reload_session_from_disk()

        assert result is False

    def test_reload_updates_user_agent_and_token(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(
            cache_path,
            "NEW=COOKIE",
            time.time() + 1800,
            user_agent="NewBrowser/1.0",
            session_token="new_g_ck",
        )

        manager._reload_session_from_disk()

        assert manager._browser_user_agent == "NewBrowser/1.0"
        assert manager._browser_session_token == "new_g_ck"


class TestInvalidateSessionDiskSafety:
    """Tests for invalidate_browser_session() — must not delete other terminal's session."""

    def test_invalidate_deletes_disk_when_cookies_match(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        # Disk has same cookies as in-memory
        _write_session_cache(cache_path, "OLD=COOKIE", time.time() + 1800)

        manager.invalidate_browser_session()

        assert not os.path.exists(cache_path)
        assert manager._browser_cookie_header is None

    def test_invalidate_preserves_disk_when_cookies_differ(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        # Another terminal wrote fresher cookies to disk
        _write_session_cache(cache_path, "FRESH=FROM_OTHER_TERMINAL", time.time() + 1800)

        manager.invalidate_browser_session()

        # Disk file must survive — it belongs to another terminal
        assert os.path.exists(cache_path)
        with open(cache_path) as f:
            data = json.load(f)
        assert data["cookie_header"] == "FRESH=FROM_OTHER_TERMINAL"
        # In-memory state is cleared regardless
        assert manager._browser_cookie_header is None

    def test_invalidate_deletes_disk_when_file_unreadable(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        with open(cache_path, "w") as f:
            f.write("corrupt{{{")

        manager.invalidate_browser_session()

        # Can't read → safe to delete
        assert not os.path.exists(cache_path)

    def test_invalidate_clears_all_memory_state(self, tmp_path):
        manager = _make_browser_manager()
        manager._session_cache_path = str(tmp_path / "no_file.json")
        manager._browser_session_token = "tok123"

        manager.invalidate_browser_session()

        assert manager._browser_cookie_header is None
        assert manager._browser_cookie_expires_at is None
        assert manager._browser_last_validated_at is None
        assert manager._browser_session_token is None


class TestKeepaliveConsecutiveFailures:
    """Tests for keepalive retry logic — 3 consecutive failures before invalidation."""

    def test_single_keepalive_failure_does_not_invalidate(self):
        manager = _make_browser_manager()
        manager._keepalive_consecutive_failures = 0

        # Simulate one failure in keepalive: counter should increment, session stays
        manager._keepalive_consecutive_failures += 1

        assert manager._keepalive_consecutive_failures == 1
        assert manager._browser_cookie_header == "OLD=COOKIE"  # Not invalidated

    def test_three_failures_threshold(self):
        manager = _make_browser_manager()

        # After 3 failures, keepalive should invalidate
        manager._keepalive_consecutive_failures = 3
        should_invalidate = manager._keepalive_consecutive_failures >= 3

        assert should_invalidate is True

    def test_success_resets_failure_counter(self):
        manager = _make_browser_manager()
        manager._keepalive_consecutive_failures = 2

        # Simulate successful ping
        manager._keepalive_consecutive_failures = 0

        assert manager._keepalive_consecutive_failures == 0


class TestKeepalivePingDedup:
    """Tests for keepalive ping deduplication across terminals."""

    def test_skip_ping_when_ttl_recently_extended(self):
        manager = _make_browser_manager(session_ttl_minutes=30)
        ttl_seconds = 30 * 60  # 1800s
        ping_interval = ttl_seconds // 2  # 900s

        # TTL was just extended (remaining ≈ full TTL)
        manager._browser_cookie_expires_at = time.time() + ttl_seconds

        remaining = manager._browser_cookie_expires_at - time.time()
        threshold = ttl_seconds - ping_interval * 0.3  # 1800 - 270 = 1530

        # remaining (~1800) > threshold (1530) → should skip
        assert remaining > threshold

    def test_do_ping_when_ttl_getting_low(self):
        manager = _make_browser_manager(session_ttl_minutes=30)
        ttl_seconds = 30 * 60
        ping_interval = ttl_seconds // 2

        # Half the TTL has elapsed
        manager._browser_cookie_expires_at = time.time() + (ttl_seconds // 2)

        remaining = manager._browser_cookie_expires_at - time.time()
        threshold = ttl_seconds - ping_interval * 0.3

        # remaining (~900) < threshold (1530) → should ping
        assert remaining < threshold


class TestMakeRequest401DiskReload:
    """Tests for 401 handling — try disk reload before full re-auth."""

    def test_401_reloads_from_disk_and_retries(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path
        manager._browser_last_reauth_attempt_at = None

        # Another terminal wrote a fresh session
        _write_session_cache(cache_path, "FRESH=COOKIE", time.time() + 1800)

        first_response = MagicMock()
        first_response.status_code = 401
        first_response.headers = {"Location": "/login.do"}
        first_response.url = "https://example.service-now.com/login.do"

        second_response = MagicMock()
        second_response.status_code = 200
        second_response.headers = {}
        second_response.url = "https://example.service-now.com/api/now/table/sys_user"

        with patch.object(
            manager,
            "get_headers",
            return_value={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "FRESH=COOKIE",
            },
        ):
            with patch.object(manager._http_session, "request") as mock_request:
                mock_request.side_effect = [first_response, second_response]

                response = manager.make_request(
                    "GET",
                    "https://example.service-now.com/api/now/table/sys_user",
                    timeout=10,
                    max_retries=1,
                )

        assert response.status_code == 200
        # The disk-reloaded cookies should have been used
        assert manager._browser_cookie_header == "FRESH=COOKIE"

    def test_401_disk_reload_also_fails_falls_through_to_reauth(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path
        manager._browser_last_reauth_attempt_at = None

        # Disk has different cookies but they're also stale
        _write_session_cache(cache_path, "STALE=DISK", time.time() + 1800)

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.headers = {"Location": "/login.do"}
        resp_401.url = "https://example.service-now.com/login.do"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.url = "https://example.service-now.com/api/now/table/sys_user"

        call_count = 0

        def _mock_get_headers():
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": manager._browser_cookie_header or "REAUTH=COOKIE",
            }

        with patch.object(manager, "get_headers", side_effect=_mock_get_headers):
            with patch.object(manager._http_session, "request") as mock_request:
                # First call: 401 with OLD=COOKIE
                # Second call (disk reload retry): 401 again with STALE=DISK
                # Third call (after full re-auth): 200
                mock_request.side_effect = [resp_401, resp_401, resp_200]

                with patch.object(manager, "invalidate_browser_session"):
                    response = manager.make_request(
                        "GET",
                        "https://example.service-now.com/api/now/table/sys_user",
                        timeout=10,
                        max_retries=1,
                    )

        # Should have attempted disk reload first, then fallen through to re-auth flow
        assert mock_request.call_count == 3


class TestSaveSessionDiskHash:
    """Tests for _save_session_to_disk idempotency."""

    def test_save_skips_redundant_write(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        manager._save_session_to_disk()
        mtime1 = os.path.getmtime(cache_path)

        # Second save with identical data should be skipped (hash match)
        manager._save_session_to_disk()
        mtime2 = os.path.getmtime(cache_path)

        assert mtime1 == mtime2

    def test_save_writes_when_data_changes(self, tmp_path):
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        manager._save_session_to_disk()
        with open(cache_path) as f:
            data1 = json.load(f)

        manager._browser_cookie_header = "CHANGED=COOKIE"
        manager._session_disk_hash = None  # Force re-hash
        manager._save_session_to_disk()
        with open(cache_path) as f:
            data2 = json.load(f)

        assert data1["cookie_header"] != data2["cookie_header"]
        assert data2["cookie_header"] == "CHANGED=COOKIE"


class TestLoadSessionFromDisk:
    """Tests for _load_session_from_disk() startup behavior."""

    def test_load_valid_session(self, tmp_path):
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(cache_path, "CACHED=COOKIE", time.time() + 1800)

        manager._load_session_from_disk()

        assert manager._browser_cookie_header == "CACHED=COOKIE"
        assert manager._browser_last_validated_at is not None

    def test_load_expired_session_probes_server(self, tmp_path):
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(cache_path, "EXPIRED=COOKIE", time.time() - 100)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.url = "https://example.service-now.com/api/now/table/sys_user"

        with patch.object(manager._http_session, "get", return_value=mock_response):
            manager._load_session_from_disk()

        # Server said session still valid → should be loaded with extended TTL
        assert manager._browser_cookie_header == "EXPIRED=COOKIE"
        assert manager._browser_cookie_expires_at > time.time()

    def test_load_expired_session_server_rejects(self, tmp_path):
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(cache_path, "DEAD=COOKIE", time.time() - 100)

        mock_response = MagicMock()
        mock_response.status_code = 302
        mock_response.headers = {"Location": "/login.do"}
        mock_response.url = "https://example.service-now.com/login.do"

        with patch.object(manager._http_session, "get", return_value=mock_response):
            manager._load_session_from_disk()

        # Server rejected → not loaded
        assert manager._browser_cookie_header is None

    def test_load_wrong_instance_ignored(self, tmp_path):
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(
            cache_path,
            "OTHER=COOKIE",
            time.time() + 1800,
            instance_url="https://other.service-now.com",
        )

        manager._load_session_from_disk()

        assert manager._browser_cookie_header is None

    def test_load_missing_file_is_noop(self, tmp_path):
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        manager._session_cache_path = str(tmp_path / "nonexistent.json")

        manager._load_session_from_disk()

        assert manager._browser_cookie_header is None
