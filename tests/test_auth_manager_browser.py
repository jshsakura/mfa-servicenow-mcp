"""
Tests for browser-session behavior in AuthManager.
"""

import time
from unittest.mock import MagicMock, patch

import requests

from servicenow_mcp.auth.auth_manager import AuthManager
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

    with patch("servicenow_mcp.auth.auth_manager.requests.get", return_value=mock_response):
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


def test_browser_session_probe_request_error_keeps_existing_session():
    manager = _make_browser_manager()

    with patch(
        "servicenow_mcp.auth.auth_manager.requests.get",
        side_effect=requests.RequestException("network issue"),
    ):
        with patch.object(manager, "_login_with_browser") as relogin:
            headers = manager.get_headers()

    assert headers["Cookie"] == "OLD=COOKIE"
    relogin.assert_not_called()


def test_browser_session_probe_403_without_login_redirect_keeps_session():
    manager = _make_browser_manager()

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.is_redirect = False
    mock_response.headers = {}
    mock_response.url = "https://example.service-now.com/api/now/table/sys_user"

    with patch("servicenow_mcp.auth.auth_manager.requests.get", return_value=mock_response):
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
    manager = AuthManager(cfg, "https://example.service-now.com")

    with patch("servicenow_mcp.auth.auth_manager.requests.get") as mock_get:
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
        with patch("servicenow_mcp.auth.auth_manager.requests.request") as mock_request:
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
