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
    mock_response.is_redirect = False
    mock_response.headers = {}

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
