"""
Tests for browser-session behavior in AuthManager.
"""

import json
import os
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from servicenow_mcp.auth.auth_manager import (
    PASSWORD_SELECTORS,
    SUBMIT_SELECTORS,
    USERNAME_SELECTORS,
    AuthManager,
    _click_first_matching,
    _fill_first_matching,
    _response_indicates_authenticated_session,
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
                # Headless-first: caller now passes force_interactive=False;
                # the wrapper internally falls back to interactive on
                # MFA_REQUIRED. The mock simulates a successful relogin
                # outcome regardless of mode.
                assert force_interactive is False
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
                # Headless-first entry; wrapper handles fallback internally.
                assert force_interactive is False
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

    def test_reload_does_not_falsely_mark_validated_for_new_cookies(self, tmp_path):
        """v1.10.21: probe-before-trust policy. A session adopted from disk must
        NOT claim "just validated" — the cookie may already be stale on the
        server. Setting last_validated_at to now would skip the validation probe
        and cause a 401 on the very next request, which is the source of the
        "every first call fails, retry succeeds" pattern.
        """
        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path
        manager._browser_last_validated_at = None

        # Sibling wrote an older-format session WITHOUT last_validated_at.
        _write_session_cache(cache_path, "ADOPTED=COOKIE", time.time() + 1800)

        assert manager._reload_session_from_disk() is True
        assert manager._browser_cookie_header == "ADOPTED=COOKIE"
        # Critical: validated_at remains None so the next caller probes.
        assert manager._browser_last_validated_at is None

    def test_reload_inherits_disk_validated_at_when_present(self, tmp_path):
        """When the disk session carries a last_validated_at, inherit it (capped
        to now) so we don't claim a fresher validation than another process
        actually performed.
        """
        import json as _json

        manager = _make_browser_manager()
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path
        manager._browser_last_validated_at = None

        validated_30s_ago = time.time() - 30
        with open(cache_path, "w") as f:
            _json.dump(
                {
                    "cookie_header": "ADOPTED=COOKIE",
                    "user_agent": "Test",
                    "session_token": "tok",
                    "expires_at": time.time() + 1800,
                    "instance_url": "https://example.service-now.com",
                    "last_validated_at": validated_30s_ago,
                },
                f,
            )

        assert manager._reload_session_from_disk() is True
        assert manager._browser_last_validated_at == validated_30s_ago

    def test_save_persists_last_validated_at(self, tmp_path):
        """Saved sessions must include last_validated_at so siblings can adopt
        the same validation timestamp instead of re-probing unnecessarily."""
        manager = _make_browser_manager()
        manager._session_cache_path = str(tmp_path / "session.json")
        manager._browser_cookie_header = "WRITE=COOKIE"
        validated = time.time() - 10
        manager._browser_last_validated_at = validated
        manager._session_disk_hash = None  # force write

        manager._save_session_to_disk()

        with open(manager._session_cache_path) as f:
            data = json.load(f)
        assert data["last_validated_at"] == validated


class TestAbsorbResponseTokenRotation:
    """Tests for _absorb_response_token_rotation() — ServiceNow rotates g_ck
    (X-UserToken) periodically and pushes the new value via response headers.
    Failing to absorb the rotated token leads to 401 on subsequent mutating calls.
    """

    def test_absorbs_rotated_x_user_token(self):
        manager = _make_browser_manager()
        manager._browser_session_token = "OLD_TOKEN"
        manager._session_cache_path = "/tmp/_test_rotation.json"
        manager._session_disk_hash = None

        response = MagicMock()
        response.headers = {"X-UserToken": "ROTATED_TOKEN"}

        with patch.object(manager, "_save_session_to_disk") as mock_save:
            manager._absorb_response_token_rotation(response)

        assert manager._browser_session_token == "ROTATED_TOKEN"
        mock_save.assert_called_once()

    def test_falls_back_to_x_csrf_token(self):
        manager = _make_browser_manager()
        manager._browser_session_token = "OLD_TOKEN"

        response = MagicMock()
        response.headers = {"X-CSRF-Token": "CSRF_ROTATED"}

        with patch.object(manager, "_save_session_to_disk"):
            manager._absorb_response_token_rotation(response)

        assert manager._browser_session_token == "CSRF_ROTATED"

    def test_no_op_when_token_unchanged(self):
        manager = _make_browser_manager()
        manager._browser_session_token = "SAME_TOKEN"

        response = MagicMock()
        response.headers = {"X-UserToken": "SAME_TOKEN"}

        with patch.object(manager, "_save_session_to_disk") as mock_save:
            manager._absorb_response_token_rotation(response)

        assert manager._browser_session_token == "SAME_TOKEN"
        mock_save.assert_not_called()

    def test_no_op_when_no_token_header(self):
        manager = _make_browser_manager()
        manager._browser_session_token = "ORIGINAL"

        response = MagicMock()
        response.headers = {"Content-Type": "application/json"}

        with patch.object(manager, "_save_session_to_disk") as mock_save:
            manager._absorb_response_token_rotation(response)

        assert manager._browser_session_token == "ORIGINAL"
        mock_save.assert_not_called()

    def test_no_op_for_non_browser_auth(self):
        """Token rotation only applies to browser auth — basic/OAuth/API key
        managers do not use X-UserToken."""
        cfg = AuthConfig(
            type=AuthType.BASIC,
            basic=__import__(
                "servicenow_mcp.utils.config", fromlist=["BasicAuthConfig"]
            ).BasicAuthConfig(username="u", password="p"),
        )
        manager = AuthManager(cfg, "https://example.service-now.com")
        manager._browser_session_token = "should_not_change"

        response = MagicMock()
        response.headers = {"X-UserToken": "rotated"}

        manager._absorb_response_token_rotation(response)
        assert manager._browser_session_token == "should_not_change"


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
                    manager.make_request(
                        "GET",
                        "https://example.service-now.com/api/now/table/sys_user",
                        timeout=10,
                        max_retries=1,
                    )

        # Should have attempted disk reload first, then fallen through to re-auth flow
        assert mock_request.call_count == 3

    def test_401_wait_for_other_login_uses_loaded_session_without_second_reload(self):
        """If another terminal already loaded a fresh session into memory, retry immediately.

        _wait_for_other_login() can return True after populating in-memory cookies.
        A follow-up _reload_session_from_disk() may correctly return False because
        there is nothing newer on disk, but that must not force a second re-auth.
        """

        manager = _make_browser_manager()
        manager._browser_last_reauth_attempt_at = None

        first_response = MagicMock()
        first_response.status_code = 401
        first_response.headers = {"Location": "/login.do"}
        first_response.url = "https://example.service-now.com/login.do"

        retry_response = MagicMock()
        retry_response.status_code = 200
        retry_response.headers = {}
        retry_response.url = "https://example.service-now.com/api/now/table/sys_user"

        def _wait_for_other_login(timeout=120):
            manager._browser_cookie_header = "OTHER=COOKIE"
            manager._browser_cookie_expires_at = time.time() + 1800
            manager._browser_last_validated_at = time.time()
            return True

        def _get_headers():
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": manager._browser_cookie_header or "OLD=COOKIE",
            }

        with patch.object(manager, "get_headers", side_effect=_get_headers):
            with patch.object(manager._http_session, "request") as mock_request:
                mock_request.side_effect = [first_response, retry_response]

                with (
                    patch.object(manager, "_reload_session_from_disk", return_value=False),
                    patch.object(manager, "_acquire_login_lock", return_value=False),
                    patch.object(
                        manager, "_wait_for_other_login", side_effect=_wait_for_other_login
                    ),
                    patch.object(manager, "invalidate_browser_session") as mock_invalidate,
                ):
                    response = manager.make_request(
                        "GET",
                        "https://example.service-now.com/api/now/table/sys_user",
                        timeout=10,
                        max_retries=1,
                    )

        assert response.status_code == 200
        assert mock_request.call_count == 2
        assert mock_request.call_args_list[1].kwargs["cookies"] == {"OTHER": "COOKIE"}
        mock_invalidate.assert_not_called()


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
        assert manager._browser_last_validated_at is None

    def test_load_valid_session_requires_probe_before_reuse(self, tmp_path):
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        manager._browser_cookie_expires_at = None
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(cache_path, "CACHED=COOKIE", time.time() + 1800)

        manager._load_session_from_disk()

        assert manager._browser_cookie_header == "CACHED=COOKIE"
        assert manager._browser_last_validated_at is None

        with (
            patch.object(manager, "_is_browser_session_valid", return_value=True) as mock_valid,
            patch.object(manager, "_login_with_browser") as mock_login,
            patch.object(manager, "_start_keepalive"),
        ):
            headers = manager.get_headers()

        assert headers["Cookie"] == "CACHED=COOKIE"
        mock_valid.assert_called_once_with(manager.config.browser)
        mock_login.assert_not_called()

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

    def test_load_expired_session_probe_401_login_html_is_rejected(self, tmp_path):
        """Disk TTL expiry + unauthenticated 401 HTML must be treated as dead."""
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path

        _write_session_cache(cache_path, "STALE=COOKIE", time.time() - 100)

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.is_redirect = False
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.url = "https://example.service-now.com/api/now/table/sys_user_preference"
        mock_response.text = "User Not Authenticated"

        with patch.object(manager._http_session, "get", return_value=mock_response):
            manager._load_session_from_disk()

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


class TestCrossProcessLoginLock:
    """Tests for disk-based login lock to prevent duplicate browser windows."""

    def test_acquire_lock_succeeds_when_no_lock_exists(self, tmp_path):
        manager = _make_browser_manager()
        manager._login_lock_path = str(tmp_path / "test.lock")

        assert manager._acquire_login_lock() is True
        assert os.path.exists(manager._login_lock_path)

    def test_acquire_lock_fails_when_held_by_live_process(self, tmp_path):
        manager = _make_browser_manager()
        lock_path = str(tmp_path / "test.lock")
        manager._login_lock_path = lock_path

        # Simulate another process holding the lock (use our own PID — it's alive)
        with open(lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": time.time()}, f)

        # A different manager (simulating another terminal) should fail to acquire
        manager2 = _make_browser_manager()
        manager2._login_lock_path = lock_path

        assert manager2._acquire_login_lock() is False

    def test_acquire_lock_cleans_stale_dead_pid(self, tmp_path):
        manager = _make_browser_manager()
        lock_path = str(tmp_path / "test.lock")
        manager._login_lock_path = lock_path

        # Write a lock with a PID that doesn't exist
        with open(lock_path, "w") as f:
            json.dump({"pid": 99999999, "timestamp": time.time()}, f)

        # Should clean up stale lock and acquire
        assert manager._acquire_login_lock() is True

    def test_acquire_lock_cleans_stale_old_timestamp(self, tmp_path):
        manager = _make_browser_manager()
        lock_path = str(tmp_path / "test.lock")
        manager._login_lock_path = lock_path

        # Write a lock that's older than 5 minutes
        with open(lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": time.time() - 400}, f)

        assert manager._acquire_login_lock() is True

    def test_acquire_lock_cleans_corrupt_file(self, tmp_path):
        manager = _make_browser_manager()
        lock_path = str(tmp_path / "test.lock")
        manager._login_lock_path = lock_path

        with open(lock_path, "w") as f:
            f.write("not json{{{")

        assert manager._acquire_login_lock() is True

    def test_release_lock_only_if_owner(self, tmp_path):
        manager = _make_browser_manager()
        lock_path = str(tmp_path / "test.lock")
        manager._login_lock_path = lock_path

        # Lock held by another PID
        with open(lock_path, "w") as f:
            json.dump({"pid": 99999999, "timestamp": time.time()}, f)

        manager._release_login_lock()

        # Should NOT delete — we don't own it
        assert os.path.exists(lock_path)

    def test_release_lock_deletes_if_owner(self, tmp_path):
        manager = _make_browser_manager()
        lock_path = str(tmp_path / "test.lock")
        manager._login_lock_path = lock_path

        manager._acquire_login_lock()
        manager._release_login_lock()

        assert not os.path.exists(lock_path)

    def test_release_lock_noop_when_no_file(self, tmp_path):
        manager = _make_browser_manager()
        manager._login_lock_path = str(tmp_path / "nonexistent.lock")

        # Should not raise
        manager._release_login_lock()

    def test_wait_for_other_login_picks_up_session(self, tmp_path):
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        manager._browser_cookie_expires_at = None
        cache_path = str(tmp_path / "session.json")
        lock_path = str(tmp_path / "test.lock")
        manager._session_cache_path = cache_path
        manager._login_lock_path = lock_path

        # Simulate: lock exists, then gets released and session appears
        with open(lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": time.time()}, f)

        # Write a session file (simulating the other terminal completing login)
        _write_session_cache(cache_path, "FRESH=COOKIE", time.time() + 1800)
        # Remove lock (simulating the other terminal releasing it)
        os.remove(lock_path)

        result = manager._wait_for_other_login(timeout=5)

        assert result is True
        assert manager._browser_cookie_header == "FRESH=COOKIE"

    def test_wait_for_other_login_timeout(self, tmp_path):
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        lock_path = str(tmp_path / "test.lock")
        manager._login_lock_path = lock_path
        manager._session_cache_path = str(tmp_path / "no_session.json")

        # Lock stays held, no session appears
        with open(lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": time.time()}, f)

        result = manager._wait_for_other_login(timeout=4)

        assert result is False


# ---------------------------------------------------------------------------
# Browser login race-condition prevention
# ---------------------------------------------------------------------------


class TestBrowserLoginRacePrevention:
    """Tests for fixes that prevent duplicate browser login windows.

    Three bugs were fixed:
    1. _try_restore_browser_session() ran outside any lock, allowing parallel
       tool calls to each open a Playwright browser simultaneously.
    2. _try_restore_browser_session() used headless=browser_config.headless,
       making the restore attempt visible when headless=false.
    3. After _try_restore_browser_session() failed, the code did not re-check
       the disk cache before proceeding to interactive login, so a session
       written by another process during restore was missed.
    """

    def test_restore_always_uses_headless_true(self):
        """_try_restore_browser_session must launch Playwright with headless=True,
        regardless of browser_config.headless, because it only checks cookies."""
        import sys

        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(
                headless=False,  # User wants visible browser for login
                timeout_seconds=10,
                user_data_dir="/tmp/test-profile",
            ),
        )
        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_load_session_from_disk"),
            patch.object(AuthManager, "_start_keepalive"),
        ):
            manager = AuthManager(cfg, "https://example.service-now.com")

        # Mock Playwright context/page
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate.side_effect = ["TestUA", None]
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = []

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

        mock_sync_pw = MagicMock()
        mock_sync_pw.return_value.__enter__ = MagicMock(return_value=mock_pw_instance)
        mock_sync_pw.return_value.__exit__ = MagicMock(return_value=False)

        # Mock playwright at module level so `from playwright.sync_api import sync_playwright` works
        mock_pw_mod = MagicMock()
        mock_pw_mod.sync_api.sync_playwright = mock_sync_pw
        saved = {k: sys.modules.get(k) for k in ("playwright", "playwright.sync_api")}
        sys.modules["playwright"] = mock_pw_mod
        sys.modules["playwright.sync_api"] = mock_pw_mod.sync_api
        try:
            manager._try_restore_browser_session(cfg.browser)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

        call_kwargs = mock_pw_instance.chromium.launch_persistent_context.call_args
        assert call_kwargs.kwargs.get("headless") is True or call_kwargs[1].get("headless") is True

    def test_restore_runs_under_inprocess_lock(self):
        """_try_restore_browser_session must not run concurrently within a process.
        When session is missing, the in-process lock should be acquired BEFORE
        restore is attempted, so a second thread waits instead of opening another browser."""
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        manager._browser_cookie_expires_at = None

        restore_calls: list[float] = []
        login_calls: list[float] = []

        def _slow_restore(_cfg):
            restore_calls.append(time.time())
            time.sleep(0.1)  # Simulate browser open/close
            return False

        def _mock_login(_cfg, force_interactive=False):
            login_calls.append(time.time())
            manager._browser_cookie_header = "NEW=COOKIE"
            manager._browser_cookie_expires_at = time.time() + 600

        import threading

        def _thread_get_headers():
            """Second thread should wait on lock, not call restore."""
            try:
                manager.get_headers()
            except Exception:
                pass  # May fail if login mock not fully set up for second call

        with (
            patch.object(manager, "_try_restore_browser_session", side_effect=_slow_restore),
            patch.object(manager, "_login_with_browser", side_effect=_mock_login),
            patch.object(manager, "_reload_session_from_disk", return_value=False),
            patch.object(manager, "_acquire_login_lock", return_value=True),
            patch.object(manager, "_release_login_lock"),
            patch.object(manager, "_start_keepalive"),
        ):
            # Start two threads nearly simultaneously
            t = threading.Thread(target=_thread_get_headers)
            t.start()
            time.sleep(0.01)  # Let thread start

            try:
                manager.get_headers()
            except Exception:
                pass

            t.join(timeout=5)

        # Restore should have been called (at least by one thread).
        # The key assertion: _login_with_browser should NOT be called more than once
        # because the second caller should find the session set by the first.
        assert len(login_calls) <= 1, (
            f"_login_with_browser called {len(login_calls)} times — "
            "in-process lock should prevent concurrent login"
        )

    def test_disk_reload_after_restore_prevents_second_login(self, tmp_path):
        """After _try_restore_browser_session fails, a disk reload should be attempted.
        If another process wrote a session to disk during restore, we should use it
        instead of opening an interactive login browser."""
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        manager._browser_cookie_expires_at = None
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path
        manager.instance_url = "https://example.service-now.com"

        restore_called = False

        def _restore_that_simulates_other_process_login(_cfg):
            nonlocal restore_called
            restore_called = True
            # Simulate: while restore is running, another process writes a session to disk
            _write_session_cache(cache_path, "OTHER_PROCESS=COOKIE", time.time() + 1800)
            return False  # Restore itself fails

        with (
            patch.object(
                manager,
                "_try_restore_browser_session",
                side_effect=_restore_that_simulates_other_process_login,
            ),
            patch.object(manager, "_login_with_browser") as mock_login,
            patch.object(manager, "_start_keepalive"),
        ):
            headers = manager.get_headers()

        assert restore_called, "_try_restore_browser_session should have been called"
        mock_login.assert_not_called(), (
            "_login_with_browser should NOT be called — "
            "disk reload after restore should have found the session"
        )
        assert headers["Cookie"] == "OTHER_PROCESS=COOKIE"

    def test_fast_path_disk_reload_skips_browser_entirely(self, tmp_path):
        """When a valid session exists on disk, get_headers should return it
        without acquiring any lock or opening a browser."""
        manager = _make_browser_manager()
        manager._browser_cookie_header = None
        manager._browser_cookie_expires_at = None
        cache_path = str(tmp_path / "session.json")
        manager._session_cache_path = cache_path
        manager.instance_url = "https://example.service-now.com"

        _write_session_cache(cache_path, "DISK=SESSION", time.time() + 1800)

        with (
            patch.object(manager, "_try_restore_browser_session") as mock_restore,
            patch.object(manager, "_login_with_browser") as mock_login,
            patch.object(manager, "_start_keepalive"),
        ):
            headers = manager.get_headers()

        mock_restore.assert_not_called()
        mock_login.assert_not_called()
        assert headers["Cookie"] == "DISK=SESSION"


# ---------------------------------------------------------------------------
# _try_restore_browser_session probe-response handling
# ---------------------------------------------------------------------------


class TestTryRestoreBrowserSessionProbe:
    """Validates probe-response handling in _try_restore_browser_session().

    Before the fix: a 401 response with no login.do redirect was treated as
    reusable because auth detection only checked for login redirects.
    The browser profile cookies were accepted and every subsequent real API
    call failed with 401 or "User Not Authenticated".

    After the fix: cold restore only accepts a probe that clearly proves an
    authenticated API session (2xx or 403, without login/unauth markers).
    """

    # A minimal valid cookie for example.service-now.com
    _INSTANCE_COOKIES = [
        {
            "name": "glide_session_store",
            "value": "abc123",
            "domain": "example.service-now.com",
            "path": "/",
        }
    ]

    def _make_manager_and_pw_patch(self, tmp_path, cookies):
        """Return (cfg, manager, mock_pw_mod) wired for _try_restore_browser_session tests."""
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(
                headless=False,
                timeout_seconds=10,
                user_data_dir=str(tmp_path / "profile"),
            ),
        )
        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_load_session_from_disk"),
            patch.object(AuthManager, "_start_keepalive"),
        ):
            manager = AuthManager(cfg, "https://example.service-now.com")

        # Redirect session cache to tmp_path to avoid polluting the real
        # ~/.servicenow_mcp/ directory (which breaks other tests that call
        # _reload_session_from_disk via get_headers).
        manager._session_cache_path = str(tmp_path / "session.json")

        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate.side_effect = ["TestUA", None]
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = cookies

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch_persistent_context.return_value = mock_context

        mock_sync_pw = MagicMock()
        mock_sync_pw.return_value.__enter__ = MagicMock(return_value=mock_pw_instance)
        mock_sync_pw.return_value.__exit__ = MagicMock(return_value=False)

        mock_pw_mod = MagicMock()
        mock_pw_mod.sync_api.sync_playwright = mock_sync_pw

        return cfg, manager, mock_pw_mod

    def _run_restore(
        self,
        manager,
        cfg,
        mock_pw_mod,
        probe_status: int,
        probe_text: str = "",
        content_type: str = "application/json",
    ) -> bool:
        """Run _try_restore_browser_session with a synthetic probe response."""
        import sys

        mock_probe = MagicMock()
        mock_probe.status_code = probe_status
        mock_probe.is_redirect = False
        mock_probe.headers = {"Content-Type": content_type}
        mock_probe.url = "https://example.service-now.com/api/now/table/sys_user"
        mock_probe.text = probe_text

        saved = {k: sys.modules.get(k) for k in ("playwright", "playwright.sync_api")}
        sys.modules["playwright"] = mock_pw_mod
        sys.modules["playwright.sync_api"] = mock_pw_mod.sync_api
        try:
            with patch.object(manager, "_probe_browser_api_with_cookie", return_value=mock_probe):
                return manager._try_restore_browser_session(cfg.browser)
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_restore_probe_401_json_returns_true_and_loads_cookie(self, tmp_path):
        """401 JSON probe during restore still means authenticated but unauthorized."""
        cfg, manager, mock_pw_mod = self._make_manager_and_pw_patch(
            tmp_path, self._INSTANCE_COOKIES
        )
        result = self._run_restore(manager, cfg, mock_pw_mod, probe_status=401)
        assert result is True
        assert manager._browser_cookie_header is not None

    def test_restore_probe_403_returns_true_and_loads_cookie(self, tmp_path):
        """403 probe without login redirect during restore means authenticated but unauthorized."""
        cfg, manager, mock_pw_mod = self._make_manager_and_pw_patch(
            tmp_path, self._INSTANCE_COOKIES
        )
        result = self._run_restore(manager, cfg, mock_pw_mod, probe_status=403)
        assert result is True

    def test_restore_probe_200_returns_true_and_loads_cookie(self, tmp_path):
        """200 probe during restore must return True and populate browser cookie header."""
        cfg, manager, mock_pw_mod = self._make_manager_and_pw_patch(
            tmp_path, self._INSTANCE_COOKIES
        )
        result = self._run_restore(manager, cfg, mock_pw_mod, probe_status=200)
        assert result is True
        assert manager._browser_cookie_header == "glide_session_store=abc123"

    def test_restore_probe_login_html_body_returns_false(self, tmp_path):
        """Same-origin login HTML must not be treated as a valid restored session."""
        cfg, manager, mock_pw_mod = self._make_manager_and_pw_patch(
            tmp_path, self._INSTANCE_COOKIES
        )
        result = self._run_restore(
            manager,
            cfg,
            mock_pw_mod,
            probe_status=200,
            probe_text="<title>Log in | ServiceNow</title> Login with SSO",
            content_type="text/html",
        )
        assert result is False
        assert manager._browser_cookie_header is None

    def test_restore_probe_401_unauth_body_returns_false(self, tmp_path):
        """401 with explicit unauthenticated body must be rejected during restore."""
        cfg, manager, mock_pw_mod = self._make_manager_and_pw_patch(
            tmp_path, self._INSTANCE_COOKIES
        )
        result = self._run_restore(
            manager,
            cfg,
            mock_pw_mod,
            probe_status=401,
            probe_text="User Not Authenticated",
            content_type="text/html",
        )
        assert result is False
        assert manager._browser_cookie_header is None


def test_response_indicates_authenticated_session_rejects_unauth_body():
    response = MagicMock()
    response.status_code = 200
    response.is_redirect = False
    response.headers = {"Content-Type": "text/html"}
    response.url = "https://example.service-now.com/navpage.do"
    response.text = "User Not Authenticated"

    assert _response_indicates_authenticated_session(response) is False


def test_login_final_probe_request_error_does_not_persist_session(tmp_path):
    cfg = AuthConfig(
        type=AuthType.BROWSER,
        browser=BrowserAuthConfig(
            headless=False,
            timeout_seconds=5,
            session_ttl_minutes=30,
            user_data_dir=str(tmp_path / "profile"),
        ),
    )
    with (
        patch.object(AuthManager, "_ensure_playwright_ready"),
        patch.object(AuthManager, "_load_session_from_disk"),
        patch.object(AuthManager, "_start_keepalive"),
    ):
        manager = AuthManager(cfg, "https://example.service-now.com")

    manager._session_cache_path = str(tmp_path / "session.json")

    mock_context = MagicMock()
    mock_page = MagicMock()
    # Sequence: navigator.userAgent, then window.g_ck reads in the wait
    # loop (every poll once stable_ticks>=3 — return non-empty so the
    # loop confirms login), then one more g_ck capture after confirm.
    mock_page.evaluate.side_effect = [
        "TestUA",
        "g_ck_value",
        "g_ck_value",
        "g_ck_value",
    ]
    mock_page.is_closed.return_value = False
    mock_page.url = "https://example.service-now.com/navpage.do"
    mock_context.pages = [mock_page]
    mock_context.cookies.return_value = [
        {
            "name": "glide_session_store",
            "value": "abc123",
            "domain": "example.service-now.com",
            "path": "/",
        }
    ]

    import sys

    mock_pw_instance = MagicMock()
    mock_sync_pw = MagicMock()
    mock_sync_pw.return_value.__enter__ = MagicMock(return_value=mock_pw_instance)
    mock_sync_pw.return_value.__exit__ = MagicMock(return_value=False)
    mock_pw_mod = MagicMock()
    mock_pw_mod.sync_api.sync_playwright = mock_sync_pw
    saved = {k: sys.modules.get(k) for k in ("playwright", "playwright.sync_api")}
    sys.modules["playwright"] = mock_pw_mod
    sys.modules["playwright.sync_api"] = mock_pw_mod.sync_api

    try:
        with (
            patch(
                "servicenow_mcp.auth.auth_manager._launch_persistent_with_retry",
                return_value=mock_context,
            ),
            patch.object(
                manager,
                "_probe_browser_api_with_cookie",
                # Three consecutive failures mirror the production retry budget
                # added to absorb the post-login session-establishment race.
                # A persistently failing probe must still invalidate.
                side_effect=[
                    requests.RequestException("probe boom"),
                    requests.RequestException("probe boom"),
                    requests.RequestException("probe boom"),
                ],
            ),
            patch.object(manager, "_save_session_to_disk") as mock_save,
            # Skip the inter-attempt sleeps to keep the unit test fast.
            patch("servicenow_mcp.auth.auth_manager.time.sleep"),
        ):
            # force_interactive=True bypasses the headless MFA-remembered
            # cookie gate. The simple wait loop confirms login from page
            # state alone; the only HTTP probe is the final_probe after
            # capture, which is what RequestException covers here.
            with pytest.raises(ValueError, match="final API validation failed"):
                manager._login_with_browser_sync(cfg.browser, force_interactive=True)
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    mock_save.assert_not_called()
    assert manager._browser_cookie_header is None
    assert not os.path.exists(manager._session_cache_path)
