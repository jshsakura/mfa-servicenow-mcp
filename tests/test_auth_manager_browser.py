"""
Tests for browser-session behavior in AuthManager.
"""

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


def _make_browser_manager() -> AuthManager:
    cfg = AuthConfig(
        type=AuthType.BROWSER,
        browser=BrowserAuthConfig(
            headless=False,
            timeout_seconds=10,
            session_ttl_minutes=30,
        ),
    )
    with (
        patch.object(AuthManager, "_ensure_playwright_ready"),
        patch.object(AuthManager, "_load_session_from_disk"),
        patch.object(AuthManager, "_start_keepalive"),
    ):
        manager = AuthManager(cfg, "https://example.service-now.com")
    manager._browser_cookie_header = "OLD=COOKIE"
    manager._browser_cookie_expires_at = time.time() + 600
    manager._browser_last_validated_at = None
    return manager


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
