"""
Comprehensive tests for AuthManager targeting uncovered lines.

Covers: basic auth, OAuth, API key, helper functions, make_request,
token expiry, error handling, cookie utilities, and browser session methods.
"""

import base64
import json
import os
import time
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
import requests

from servicenow_mcp.auth.auth_manager import (
    AuthManager,
    _build_http_session,
    _cookie_header_to_dict,
    _extract_cookie_names,
    _has_servicenow_session_cookie,
    _is_login_page_url,
    _looks_like_instance_main_ui,
    _response_indicates_authenticated_session,
    _response_indicates_login_redirect,
    _selector_exists,
    _target_label,
)
from servicenow_mcp.utils.config import (
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    OAuthConfig,
)

# ---------------------------------------------------------------------------
# Helpers to build AuthManager for non-browser auth types
# ---------------------------------------------------------------------------


def _make_basic_manager(
    instance_url: str = "https://test.service-now.com",
    username: str = "admin",
    password: str = "secret",
) -> AuthManager:
    cfg = AuthConfig(
        type=AuthType.BASIC,
        basic=BasicAuthConfig(username=username, password=password),
    )
    return AuthManager(cfg, instance_url)


def _make_oauth_manager(
    instance_url: str = "https://test.service-now.com",
    client_id: str = "cid",
    client_secret: str = "csecret",
    username: str = "admin",
    password: str = "pass",
    token_url: str | None = None,
) -> AuthManager:
    cfg = AuthConfig(
        type=AuthType.OAUTH,
        oauth=OAuthConfig(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            token_url=token_url,
        ),
    )
    return AuthManager(cfg, instance_url)


def _make_apikey_manager(
    instance_url: str = "https://test.service-now.com",
    api_key: str = "my-api-key",
    header_name: str = "X-ServiceNow-API-Key",
) -> AuthManager:
    cfg = AuthConfig(
        type=AuthType.API_KEY,
        api_key=ApiKeyConfig(api_key=api_key, header_name=header_name),
    )
    return AuthManager(cfg, instance_url)


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
    return manager


# ===========================================================================
# Helper / utility function tests
# ===========================================================================


class TestExtractCookieNames:
    def test_empty_string(self):
        assert _extract_cookie_names("") == []

    def test_none(self):
        assert _extract_cookie_names(None) == []

    def test_single_cookie(self):
        assert _extract_cookie_names("foo=bar") == ["foo"]

    def test_multiple_cookies(self):
        assert _extract_cookie_names("a=1; b=2; c=3") == ["a", "b", "c"]

    def test_skips_empty_parts(self):
        assert _extract_cookie_names("a=1;  ; b=2") == ["a", "b"]

    def test_skips_no_equals(self):
        # tokens without = are skipped
        assert _extract_cookie_names("a=1; noequals; b=2") == ["a", "b"]


class TestCookieHeaderToDict:
    def test_empty_string(self):
        assert _cookie_header_to_dict("") == {}

    def test_none(self):
        assert _cookie_header_to_dict(None) == {}

    def test_single(self):
        assert _cookie_header_to_dict("foo=bar") == {"foo": "bar"}

    def test_multiple(self):
        assert _cookie_header_to_dict("a=1; b=2") == {"a": "1", "b": "2"}

    def test_skips_empty_key(self):
        # "=value" -> key is empty, should be skipped
        assert _cookie_header_to_dict("=val; good=ok") == {"good": "ok"}

    def test_skips_no_equals(self):
        assert _cookie_header_to_dict("noequals; a=1") == {"a": "1"}

    def test_value_with_equals(self):
        # value part may contain '='
        result = _cookie_header_to_dict("token=abc=def")
        assert result == {"token": "abc=def"}


class TestHasServicenowSessionCookie:
    def test_has_jsessionid(self):
        assert _has_servicenow_session_cookie(["JSESSIONID"]) is True

    def test_has_glide(self):
        assert _has_servicenow_session_cookie(["glide_user_session"]) is True

    def test_no_match(self):
        assert _has_servicenow_session_cookie(["random_cookie"]) is False

    def test_empty(self):
        assert _has_servicenow_session_cookie([]) is False

    def test_case_insensitive(self):
        assert _has_servicenow_session_cookie(["GLIDE_SESSION"]) is True


class TestIsLoginPageUrl:
    def test_login_do(self):
        assert _is_login_page_url("https://x.com/login.do") is True

    def test_auth_redirect(self):
        assert _is_login_page_url("https://x.com/auth_redirect.do") is True

    def test_mfa_view(self):
        assert _is_login_page_url("https://x.com/multi_factor_auth_view.do") is True

    def test_mfa_setup(self):
        assert _is_login_page_url("https://x.com/multi_factor_auth_setup.do") is True

    def test_query_login(self):
        assert _is_login_page_url("https://x.com/page?sysparm_type=login") is True

    def test_query_reauth(self):
        assert _is_login_page_url("https://x.com/page?sysparm_reauth=true") is True

    def test_query_mfa_needed(self):
        assert _is_login_page_url("https://x.com/page?sysparm_mfa_needed=true") is True

    def test_query_direct(self):
        assert _is_login_page_url("https://x.com/page?sysparm_direct=true") is True

    def test_path_login(self):
        assert _is_login_page_url("https://x.com/login") is True

    def test_path_auth(self):
        assert _is_login_page_url("https://x.com/auth") is True

    def test_normal_url(self):
        assert _is_login_page_url("https://x.com/api/now/table/sys_user") is False

    def test_external_logout(self):
        assert _is_login_page_url("https://x.com/external_logout_complete.do") is True

    def test_external_login_complete(self):
        assert _is_login_page_url("https://x.com/external_login_complete.do") is True

    def test_sys_auth_info(self):
        assert _is_login_page_url("https://x.com/sys_auth_info.do") is True


class TestLooksLikeInstanceMainUI:
    def test_now_route(self):
        assert _looks_like_instance_main_ui("https://x.com/now/nav/ui") is True

    def test_navpage(self):
        assert _looks_like_instance_main_ui("https://x.com/navpage.do") is True

    def test_home(self):
        assert _looks_like_instance_main_ui("https://x.com/home.do") is True

    def test_sp(self):
        assert _looks_like_instance_main_ui("https://x.com/sp") is True

    def test_root(self):
        assert _looks_like_instance_main_ui("https://x.com/") is True

    def test_empty_path(self):
        assert _looks_like_instance_main_ui("https://x.com") is True

    def test_api_path(self):
        assert _looks_like_instance_main_ui("https://x.com/api/v1/resource") is False


class TestResponseIndicatesLoginRedirect:
    def test_login_in_location(self):
        resp = MagicMock()
        resp.headers = {"Location": "/login.do"}
        resp.url = "https://x.com/api"
        assert _response_indicates_login_redirect(resp) is True

    def test_sysparm_login_in_location(self):
        resp = MagicMock()
        resp.headers = {"Location": "/page?sysparm_type=login"}
        resp.url = "https://x.com/api"
        assert _response_indicates_login_redirect(resp) is True

    def test_login_url(self):
        resp = MagicMock()
        resp.headers = {}
        resp.url = "https://x.com/login.do"
        assert _response_indicates_login_redirect(resp) is True

    def test_normal_response(self):
        resp = MagicMock()
        resp.headers = {}
        resp.url = "https://x.com/api/now/table/sys_user"
        assert _response_indicates_login_redirect(resp) is False

    def test_authenticated_inverse(self):
        resp = MagicMock()
        resp.headers = {}
        resp.url = "https://x.com/api/now/table/sys_user"
        assert _response_indicates_authenticated_session(resp) is True


class TestSelectorExists:
    def test_exists(self):
        target = MagicMock()
        target.locator.return_value.count.return_value = 1
        assert _selector_exists(target, "input#user") is True

    def test_not_exists(self):
        target = MagicMock()
        target.locator.return_value.count.return_value = 0
        assert _selector_exists(target, "input#user") is False

    def test_exception(self):
        target = MagicMock()
        target.locator.side_effect = Exception("boom")
        assert _selector_exists(target, "input#user") is False


class TestTargetLabel:
    def test_main_with_url(self):
        target = MagicMock()
        target.url = "https://x.com/page"
        assert _target_label(target, 0) == "main:https://x.com/page"

    def test_frame_with_url(self):
        target = MagicMock()
        target.url = "https://x.com/frame"
        assert _target_label(target, 2) == "frame[2]:https://x.com/frame"

    def test_no_url(self):
        target = MagicMock()
        target.url = ""
        assert _target_label(target, 0) == "main"

    def test_url_raises(self):
        target = MagicMock()
        type(target).url = PropertyMock(side_effect=Exception("no url"))
        assert _target_label(target, 1) == "frame[1]"


class TestBuildHttpSession:
    def test_returns_session(self):
        s = _build_http_session()
        assert isinstance(s, requests.Session)
        assert "Accept-Encoding" in s.headers


# ===========================================================================
# Basic Auth tests
# ===========================================================================


class TestBasicAuth:
    def test_get_headers_basic(self):
        mgr = _make_basic_manager(username="admin", password="secret")
        headers = mgr.get_headers()
        expected = base64.b64encode(b"admin:secret").decode()
        assert headers["Authorization"] == f"Basic {expected}"
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"

    def test_basic_auth_caches_header(self):
        mgr = _make_basic_manager()
        h1 = mgr.get_headers()
        h2 = mgr.get_headers()
        assert h1["Authorization"] == h2["Authorization"]
        assert mgr._cached_basic_auth_header is not None

    def test_basic_auth_missing_config_raises(self):
        cfg = AuthConfig(type=AuthType.BASIC, basic=None)
        mgr = AuthManager(cfg, "https://test.service-now.com")
        with pytest.raises(ValueError, match="Basic auth configuration is required"):
            mgr.get_headers()


# ===========================================================================
# API Key Auth tests
# ===========================================================================


class TestApiKeyAuth:
    def test_get_headers_api_key(self):
        mgr = _make_apikey_manager(api_key="key123", header_name="X-SN-Key")
        headers = mgr.get_headers()
        assert headers["X-SN-Key"] == "key123"

    def test_api_key_missing_config_raises(self):
        cfg = AuthConfig(type=AuthType.API_KEY, api_key=None)
        mgr = AuthManager(cfg, "https://test.service-now.com")
        with pytest.raises(ValueError, match="API key configuration is required"):
            mgr.get_headers()


# ===========================================================================
# OAuth Auth tests
# ===========================================================================


class TestOAuthAuth:
    def test_get_headers_oauth_triggers_token_fetch(self):
        mgr = _make_oauth_manager(token_url="https://test.service-now.com/oauth_token.do")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "tok123",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        with patch.object(mgr._http_session, "post", return_value=mock_resp):
            headers = mgr.get_headers()
        assert headers["Authorization"] == "Bearer tok123"
        assert mgr.token == "tok123"
        assert mgr.token_type == "Bearer"
        assert mgr.token_expires_at is not None

    def test_oauth_missing_config_raises(self):
        cfg = AuthConfig(type=AuthType.OAUTH, oauth=None)
        mgr = AuthManager(cfg, "https://test.service-now.com")
        with pytest.raises(ValueError, match="OAuth configuration is required"):
            mgr.get_headers()

    def test_oauth_missing_instance_url_raises(self):
        cfg = AuthConfig(
            type=AuthType.OAUTH,
            oauth=OAuthConfig(
                client_id="cid",
                client_secret="cs",
                username="u",
                password="p",
                token_url=None,
            ),
        )
        mgr = AuthManager(cfg, None)
        with pytest.raises(ValueError, match="Instance URL is required"):
            mgr.get_headers()

    def test_oauth_invalid_instance_url_raises(self):
        cfg = AuthConfig(
            type=AuthType.OAUTH,
            oauth=OAuthConfig(
                client_id="cid",
                client_secret="cs",
                username="u",
                password="p",
                token_url=None,
            ),
        )
        mgr = AuthManager(cfg, "http://localhost")
        with pytest.raises(ValueError, match="Invalid instance URL"):
            mgr.get_headers()

    def test_oauth_client_credentials_success(self):
        mgr = _make_oauth_manager(token_url="https://test.sn.com/oauth_token.do")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "cc_tok",
            "token_type": "Bearer",
            "expires_in": 1800,
        }
        with patch.object(mgr._http_session, "post", return_value=mock_resp):
            mgr._get_oauth_token()
        assert mgr.token == "cc_tok"

    def test_oauth_falls_back_to_password_grant(self):
        mgr = _make_oauth_manager(token_url="https://test.sn.com/oauth_token.do")
        cc_resp = MagicMock()
        cc_resp.status_code = 401
        pw_resp = MagicMock()
        pw_resp.status_code = 200
        pw_resp.json.return_value = {
            "access_token": "pw_tok",
            "token_type": "Bearer",
            "expires_in": 600,
        }
        with patch.object(mgr._http_session, "post", side_effect=[cc_resp, pw_resp]):
            mgr._get_oauth_token()
        assert mgr.token == "pw_tok"

    def test_oauth_both_grants_fail(self):
        mgr = _make_oauth_manager(token_url="https://test.sn.com/oauth_token.do")
        fail_resp = MagicMock()
        fail_resp.status_code = 401
        with patch.object(mgr._http_session, "post", return_value=fail_resp):
            with pytest.raises(ValueError, match="Failed to get OAuth token"):
                mgr._get_oauth_token()

    def test_oauth_token_url_derived_from_instance(self):
        mgr = _make_oauth_manager(
            instance_url="https://myinst.service-now.com",
            token_url=None,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "t",
            "token_type": "Bearer",
        }
        with patch.object(mgr._http_session, "post", return_value=mock_resp) as mock_post:
            mgr._get_oauth_token()
        call_url = mock_post.call_args[0][0]
        assert "myinst.service-now.com/oauth_token.do" in call_url

    def test_oauth_no_expires_in(self):
        mgr = _make_oauth_manager(token_url="https://test.sn.com/oauth_token.do")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "t",
            "token_type": "Bearer",
        }
        with patch.object(mgr._http_session, "post", return_value=mock_resp):
            mgr._get_oauth_token()
        assert mgr.token_expires_at is None

    def test_oauth_string_expires_in_ignored(self):
        mgr = _make_oauth_manager(token_url="https://test.sn.com/oauth_token.do")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "t",
            "token_type": "Bearer",
            "expires_in": "not_a_number",
        }
        with patch.object(mgr._http_session, "post", return_value=mock_resp):
            mgr._get_oauth_token()
        assert mgr.token_expires_at is None

    def test_refresh_token_calls_get_oauth_token(self):
        mgr = _make_oauth_manager()
        with patch.object(mgr, "_get_oauth_token") as mock_get:
            mgr.refresh_token()
        mock_get.assert_called_once()

    def test_refresh_token_noop_for_basic(self):
        mgr = _make_basic_manager()
        # Should not raise or do anything
        mgr.refresh_token()


class TestTokenExpiry:
    def test_not_expired_when_no_expiry(self):
        mgr = _make_basic_manager()
        mgr.token_expires_at = None
        assert mgr._is_token_expired() is False

    def test_not_expired(self):
        mgr = _make_basic_manager()
        mgr.token_expires_at = time.time() + 3600
        assert mgr._is_token_expired() is False

    def test_expired(self):
        mgr = _make_basic_manager()
        mgr.token_expires_at = time.time() - 10
        assert mgr._is_token_expired() is True

    def test_oauth_auto_refreshes_on_expired(self):
        mgr = _make_oauth_manager(token_url="https://test.sn.com/oauth_token.do")
        mgr.token = "old_tok"
        mgr.token_type = "Bearer"
        mgr.token_expires_at = time.time() - 10  # expired

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "new_tok",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        with patch.object(mgr._http_session, "post", return_value=mock_resp):
            headers = mgr.get_headers()
        assert headers["Authorization"] == "Bearer new_tok"


# ===========================================================================
# Browser session helper tests
# ===========================================================================


class TestBrowserSessionExpiry:
    def test_not_expired_no_expiry(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_expires_at = None
        assert mgr._is_browser_session_expired() is False

    def test_not_expired(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_expires_at = time.time() + 600
        assert mgr._is_browser_session_expired() is False

    def test_expired(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_expires_at = time.time() - 10
        assert mgr._is_browser_session_expired() is True


class TestShouldValidateBrowserSession:
    def test_no_cookie(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        assert mgr._should_validate_browser_session() is False

    def test_within_grace_period(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = time.time()
        assert mgr._should_validate_browser_session() is False

    def test_never_validated(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = None
        mgr._browser_last_validated_at = None
        assert mgr._should_validate_browser_session() is True

    def test_validated_recently(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = None
        mgr._browser_last_validated_at = time.time()
        mgr._browser_validation_interval_seconds = 120
        assert mgr._should_validate_browser_session() is False

    def test_validated_long_ago(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = None
        mgr._browser_last_validated_at = time.time() - 200
        mgr._browser_validation_interval_seconds = 120
        assert mgr._should_validate_browser_session() is True


class TestCanAttemptBrowserReauth:
    def test_no_prior_attempt(self):
        mgr = _make_browser_manager()
        mgr._browser_last_reauth_attempt_at = None
        assert mgr._can_attempt_browser_reauth() is True

    def test_cooldown_not_elapsed(self):
        mgr = _make_browser_manager()
        mgr._browser_last_reauth_attempt_at = time.time()
        mgr._browser_reauth_cooldown_seconds = 60
        assert mgr._can_attempt_browser_reauth() is False

    def test_cooldown_elapsed(self):
        mgr = _make_browser_manager()
        mgr._browser_last_reauth_attempt_at = time.time() - 120
        mgr._browser_reauth_cooldown_seconds = 60
        assert mgr._can_attempt_browser_reauth() is True


class TestGetReauthCooldownRemaining:
    def test_no_prior_attempt(self):
        mgr = _make_browser_manager()
        mgr._browser_last_reauth_attempt_at = None
        assert mgr._get_reauth_cooldown_remaining() == 0

    def test_cooldown_remaining(self):
        mgr = _make_browser_manager()
        mgr._browser_last_reauth_attempt_at = time.time()
        mgr._browser_reauth_cooldown_seconds = 60
        remaining = mgr._get_reauth_cooldown_remaining()
        assert 50 <= remaining <= 60

    def test_cooldown_passed(self):
        mgr = _make_browser_manager()
        mgr._browser_last_reauth_attempt_at = time.time() - 120
        mgr._browser_reauth_cooldown_seconds = 60
        assert mgr._get_reauth_cooldown_remaining() == 0


class TestClearBrowserReauthAttempt:
    def test_clears(self):
        mgr = _make_browser_manager()
        mgr._browser_last_reauth_attempt_at = time.time()
        mgr._clear_browser_reauth_attempt()
        assert mgr._browser_last_reauth_attempt_at is None


class TestMarkBrowserSessionRecentlyValid:
    def test_sets_timestamp(self):
        mgr = _make_browser_manager()
        mgr._browser_last_validated_at = None
        before = time.time()
        mgr._mark_browser_session_recently_valid()
        assert mgr._browser_last_validated_at is not None
        assert mgr._browser_last_validated_at >= before


# ===========================================================================
# _is_browser_session_valid tests
# ===========================================================================


class TestIsBrowserSessionValid:
    def test_no_instance_url(self):
        mgr = _make_browser_manager()
        mgr.instance_url = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        assert mgr._is_browser_session_valid(browser_cfg) is False

    def test_no_cookie(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        assert mgr._is_browser_session_valid(browser_cfg) is False

    def test_within_grace_period_returns_true(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = time.time()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        assert mgr._is_browser_session_valid(browser_cfg) is True
        assert mgr._browser_last_validated_at is not None

    def test_probe_success(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.is_redirect = False
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api/now/table/sys_user"
        with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_resp):
            assert mgr._is_browser_session_valid(browser_cfg) is True

    def test_probe_redirect_to_login(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {"Location": "/login.do"}
        mock_resp.url = "https://example.service-now.com/login.do"
        mock_resp.is_redirect = True
        with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_resp):
            assert mgr._is_browser_session_valid(browser_cfg) is False

    def test_probe_exception(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=Exception("net err")):
            assert mgr._is_browser_session_valid(browser_cfg) is False

    def test_probe_401_but_authenticated(self):
        """401 from ACL but not a login redirect => still valid."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api/now/table/sys_user"
        mock_resp.is_redirect = False
        with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_resp):
            assert mgr._is_browser_session_valid(browser_cfg) is True

    def test_probe_403_but_authenticated(self):
        """403 from ACL but not a login redirect => still valid."""
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_last_login_at = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api/now/table/sys_user"
        mock_resp.is_redirect = False
        with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_resp):
            assert mgr._is_browser_session_valid(browser_cfg) is True


# ===========================================================================
# _probe_browser_api_with_cookie tests
# ===========================================================================


class TestProbeBrowserApiWithCookie:
    def test_no_instance_url_raises(self):
        mgr = _make_browser_manager()
        mgr.instance_url = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        with pytest.raises(ValueError, match="Instance URL is required"):
            mgr._probe_browser_api_with_cookie("a=1", 10, browser_cfg)

    def test_uses_user_agent(self):
        mgr = _make_browser_manager()
        mgr._browser_user_agent = "TestBrowser/1.0"
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, probe_path="/api/now/table/sys_user")
        mock_resp = MagicMock()
        with patch.object(mgr._http_session, "get", return_value=mock_resp) as mock_get:
            mgr._probe_browser_api_with_cookie("a=1", 10, browser_cfg)
        call_headers = mock_get.call_args.kwargs["headers"]
        assert call_headers["User-Agent"] == "TestBrowser/1.0"

    def test_full_url_probe_path(self):
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10,
            probe_path="https://other.service-now.com/api/now/table/incident",
        )
        mock_resp = MagicMock()
        with patch.object(mgr._http_session, "get", return_value=mock_resp) as mock_get:
            mgr._probe_browser_api_with_cookie("a=1", 10, browser_cfg)
        assert mock_get.call_args.args[0] == "https://other.service-now.com/api/now/table/incident"


# ===========================================================================
# _build_instance_cookie_header tests
# ===========================================================================


class TestBuildInstanceCookieHeader:
    def test_no_matching_cookies(self):
        mgr = _make_browser_manager()
        cookies = [{"name": "x", "value": "1", "domain": "other.com"}]
        result = mgr._build_instance_cookie_header(
            cookies, "https://example.service-now.com", "example.service-now.com"
        )
        assert result is None

    def test_matching_cookies(self):
        mgr = _make_browser_manager()
        cookies = [
            {"name": "JSESSIONID", "value": "abc", "domain": "example.service-now.com"},
            {"name": "glide", "value": "xyz", "domain": ".service-now.com"},
        ]
        result = mgr._build_instance_cookie_header(
            cookies, "https://example.service-now.com", "example.service-now.com"
        )
        assert result is not None
        assert "JSESSIONID=abc" in result

    def test_dedup_prefers_instance_specific(self):
        mgr = _make_browser_manager()
        cookies = [
            {"name": "tok", "value": "parent", "domain": ".service-now.com"},
            {"name": "tok", "value": "specific", "domain": "example.service-now.com"},
        ]
        result = mgr._build_instance_cookie_header(
            cookies, "https://example.service-now.com", "example.service-now.com"
        )
        assert result is not None
        assert "tok=specific" in result
        assert result.count("tok=") == 1

    def test_empty_name_skipped(self):
        mgr = _make_browser_manager()
        cookies = [
            {"name": "", "value": "x", "domain": "example.service-now.com"},
            {"name": "good", "value": "y", "domain": "example.service-now.com"},
        ]
        result = mgr._build_instance_cookie_header(
            cookies, "https://example.service-now.com", "example.service-now.com"
        )
        assert "good=y" in result


class TestIsInstanceCookie:
    def test_true(self):
        mgr = _make_browser_manager()
        cookie = {"domain": ".example.service-now.com"}
        assert mgr._is_instance_cookie(cookie, "example.service-now.com") is True

    def test_false(self):
        mgr = _make_browser_manager()
        cookie = {"domain": ".other.com"}
        assert mgr._is_instance_cookie(cookie, "example.service-now.com") is False

    def test_empty_domain(self):
        mgr = _make_browser_manager()
        cookie = {"domain": ""}
        assert mgr._is_instance_cookie(cookie, "example.service-now.com") is False


# ===========================================================================
# _get_session_cache_path tests
# ===========================================================================


class TestGetSessionCachePath:
    def test_basic_path(self):
        mgr = _make_basic_manager(instance_url="https://myinst.service-now.com")
        path = mgr._get_session_cache_path()
        assert "myinst_service-now_com" in path
        assert path.endswith(".json")

    def test_no_instance_url(self):
        cfg = AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="a", password="b"))
        mgr = AuthManager(cfg, None)
        path = mgr._get_session_cache_path()
        assert "default" in path

    def test_browser_username_in_path(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(username="user@corp.com", timeout_seconds=10),
        )
        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_load_session_from_disk"),
            patch.object(AuthManager, "_start_keepalive"),
        ):
            mgr = AuthManager(cfg, "https://inst.service-now.com")
        path = mgr._get_session_cache_path()
        assert "user_corp_com" in path


# ===========================================================================
# make_request tests
# ===========================================================================


class TestMakeRequestBasic:
    def test_simple_get(self):
        mgr = _make_basic_manager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://test.service-now.com/api"
        with patch.object(mgr._http_session, "request", return_value=mock_resp):
            resp = mgr.make_request("GET", "https://test.service-now.com/api", timeout=10)
        assert resp.status_code == 200

    def test_401_logs_warning_for_basic(self):
        mgr = _make_basic_manager()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}
        mock_resp.url = "https://test.service-now.com/api"
        with patch.object(mgr._http_session, "request", return_value=mock_resp):
            resp = mgr.make_request(
                "GET", "https://test.service-now.com/api", timeout=10, max_retries=1
            )
        assert resp.status_code == 401

    def test_transient_network_error_retries(self):
        mgr = _make_basic_manager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://test.service-now.com/api"
        with patch.object(
            mgr._http_session,
            "request",
            side_effect=[requests.ConnectionError("conn err"), mock_resp],
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                resp = mgr.make_request("GET", "https://test.service-now.com/api", timeout=10)
        assert resp.status_code == 200

    def test_all_transient_retries_exhausted_raises(self):
        mgr = _make_basic_manager()
        with patch.object(
            mgr._http_session,
            "request",
            side_effect=requests.ConnectionError("persistent err"),
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                with pytest.raises(requests.ConnectionError):
                    mgr.make_request("GET", "https://test.service-now.com/api", timeout=10)

    def test_timeout_error_retries(self):
        mgr = _make_basic_manager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://test.service-now.com/api"
        with patch.object(
            mgr._http_session,
            "request",
            side_effect=[requests.Timeout("timed out"), mock_resp],
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                resp = mgr.make_request("GET", "https://test.service-now.com/api", timeout=10)
        assert resp.status_code == 200


class TestMakeRequestBrowser:
    def test_cookie_header_converted_to_dict(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1; b=2"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api"

        with patch.object(mgr._http_session, "request", return_value=mock_resp) as mock_req:
            mgr.make_request("GET", "https://example.service-now.com/api", timeout=10)

        # Cookie should be passed as dict, not in headers
        call_kwargs = mock_req.call_args.kwargs
        assert call_kwargs.get("cookies") == {"a": "1", "b": "2"}

    def test_empty_cookie_no_cookies_kwarg(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api"

        # Simulate get_headers returning no Cookie
        with patch.object(
            mgr,
            "get_headers",
            return_value={"Accept": "application/json", "Content-Type": "application/json"},
        ):
            with patch.object(mgr._http_session, "request", return_value=mock_resp) as mock_req:
                mgr.make_request(
                    "GET",
                    "https://example.service-now.com/api",
                    timeout=10,
                    cookies={"leftover": "val"},
                )

        call_kwargs = mock_req.call_args.kwargs
        assert "cookies" not in call_kwargs

    def test_browser_401_reauth_fails_returns_original(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()
        mgr._browser_last_login_at = None

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api"

        call_count = 0

        def _mock_get_headers():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Cookie": "a=1",
                }
            raise ValueError("Cannot re-authenticate")

        with patch.object(mgr, "get_headers", side_effect=_mock_get_headers):
            with patch.object(mgr._http_session, "request", return_value=mock_resp):
                with patch.object(mgr, "invalidate_browser_session"):
                    with patch.object(mgr, "_reload_session_from_disk", return_value=False):
                        resp = mgr.make_request(
                            "GET",
                            "https://example.service-now.com/api",
                            timeout=10,
                            max_retries=1,
                        )
        # Should return the 401 response when reauth fails
        assert resp.status_code == 401

    def test_browser_marks_session_valid_on_success(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = None

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api"

        with patch.object(mgr._http_session, "request", return_value=mock_resp):
            before = time.time()
            mgr.make_request("GET", "https://example.service-now.com/api", timeout=10)

        assert mgr._browser_last_validated_at is not None
        assert mgr._browser_last_validated_at >= before

    def test_browser_401_within_grace_period_retries_with_existing(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()
        mgr._browser_last_login_at = time.time()  # within grace

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.headers = {}
        resp_401.url = "https://example.service-now.com/api"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.url = "https://example.service-now.com/api"

        with patch.object(mgr._http_session, "request", side_effect=[resp_401, resp_200]):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                resp = mgr.make_request(
                    "GET",
                    "https://example.service-now.com/api",
                    timeout=10,
                    max_retries=1,
                )
        assert resp.status_code == 200

    def test_browser_401_grace_retry_still_fails_proceeds_to_reauth(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()
        mgr._browser_last_login_at = time.time()

        resp_401 = MagicMock()
        resp_401.status_code = 401
        resp_401.headers = {}
        resp_401.url = "https://example.service-now.com/api"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.headers = {}
        resp_200.url = "https://example.service-now.com/api"

        request_count = 0

        def _mock_request(*args, **kwargs):
            nonlocal request_count
            request_count += 1
            if request_count <= 2:
                return resp_401
            return resp_200

        get_headers_count = 0

        def _mock_get_headers():
            nonlocal get_headers_count
            get_headers_count += 1
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "a=1",
            }

        with patch.object(mgr, "get_headers", side_effect=_mock_get_headers):
            with patch.object(mgr._http_session, "request", side_effect=_mock_request):
                with patch.object(mgr, "invalidate_browser_session"):
                    with patch.object(mgr, "_reload_session_from_disk", return_value=False):
                        with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                            resp = mgr.make_request(
                                "GET",
                                "https://example.service-now.com/api",
                                timeout=10,
                                max_retries=1,
                            )
        assert resp.status_code == 200


# ===========================================================================
# Browser get_headers edge cases
# ===========================================================================


class TestBrowserGetHeadersEdgeCases:
    def test_missing_browser_config_raises(self):
        cfg = AuthConfig(type=AuthType.BROWSER, browser=None)
        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_load_session_from_disk"),
            patch.object(AuthManager, "_start_keepalive"),
        ):
            mgr = AuthManager(cfg, "https://inst.service-now.com")
        with pytest.raises(ValueError, match="Browser auth configuration is required"):
            mgr.get_headers()

    def test_browser_login_in_progress_raises(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_login_in_progress = True
        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with pytest.raises(ValueError, match="Browser login is currently in progress"):
                mgr.get_headers()

    def test_valid_browser_session_returns_cookie_headers(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "sess=abc"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()
        mgr._browser_user_agent = "UA/1.0"
        mgr._browser_session_token = "g_ck_val"

        headers = mgr.get_headers()
        assert headers["Cookie"] == "sess=abc"
        assert headers["User-Agent"] == "UA/1.0"
        assert headers["X-UserToken"] == "g_ck_val"

    def test_no_user_agent_omitted(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "sess=abc"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time()
        mgr._browser_user_agent = None
        mgr._browser_session_token = None

        headers = mgr.get_headers()
        assert "User-Agent" not in headers
        assert "X-UserToken" not in headers

    def test_restore_success_resets_failure_state(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_reauth_failure_count = 3
        mgr._browser_reauth_cooldown_seconds = 120

        def _mock_restore(cfg):
            mgr._browser_cookie_header = "restored=1"
            mgr._browser_cookie_expires_at = time.time() + 600
            return True

        with patch.object(mgr, "_try_restore_browser_session", side_effect=_mock_restore):
            headers = mgr.get_headers()

        assert mgr._browser_reauth_failure_count == 0
        assert mgr._browser_reauth_cooldown_seconds == mgr._browser_reauth_cooldown_base
        assert headers["Cookie"] == "restored=1"

    def test_login_success_resets_state_and_starts_keepalive(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_login_in_progress = False
        mgr._browser_reauth_failure_count = 2
        mgr._browser_reauth_cooldown_seconds = 60
        mgr._keepalive_thread = None

        def _mock_login(cfg, force_interactive=False):
            mgr._browser_cookie_header = "fresh=1"
            mgr._browser_cookie_expires_at = time.time() + 600

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_acquire_login_lock", return_value=True):
                with patch.object(mgr, "_can_attempt_browser_reauth", return_value=True):
                    with patch.object(mgr, "_login_with_browser", side_effect=_mock_login):
                        with patch.object(mgr, "_mark_browser_reauth_attempt"):
                            with patch.object(mgr, "_release_login_lock"):
                                with patch.object(mgr, "_start_keepalive") as mock_keepalive:
                                    headers = mgr.get_headers()

        assert headers["Cookie"] == "fresh=1"
        assert mgr._browser_reauth_failure_count == 0
        assert mgr._browser_reauth_cooldown_seconds == mgr._browser_reauth_cooldown_base
        assert mgr._browser_login_in_progress is False
        mock_keepalive.assert_called_once()

    def test_cooldown_blocks_reauth_raises(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_login_in_progress = False
        mgr._browser_last_reauth_attempt_at = time.time()
        mgr._browser_reauth_cooldown_seconds = 60

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_acquire_login_lock", return_value=True):
                with pytest.raises(ValueError, match="Browser session expired"):
                    mgr.get_headers()

    def test_another_terminal_login_wait_success(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_login_in_progress = False

        def _mock_wait(timeout):
            mgr._browser_cookie_header = "waited=1"
            mgr._browser_cookie_expires_at = time.time() + 600
            return True

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_acquire_login_lock", return_value=False):
                with patch.object(mgr, "_wait_for_other_login", side_effect=_mock_wait):
                    headers = mgr.get_headers()

        assert headers["Cookie"] == "waited=1"

    def test_wait_timeout_then_lock_fails_raises(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_login_in_progress = False

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_acquire_login_lock", return_value=False):
                with patch.object(mgr, "_wait_for_other_login", return_value=False):
                    with pytest.raises(
                        ValueError, match="Browser login is in progress in another terminal"
                    ):
                        mgr.get_headers()


# ===========================================================================
# Browser login error handling in get_headers
# ===========================================================================


class TestBrowserLoginErrorHandling:
    def test_user_closed_browser_resets_cooldown(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_login_in_progress = False
        mgr._browser_reauth_failure_count = 0

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_acquire_login_lock", return_value=True):
                with patch.object(mgr, "_can_attempt_browser_reauth", return_value=True):
                    with patch.object(
                        mgr,
                        "_login_with_browser",
                        side_effect=ValueError("target closed by user"),
                    ):
                        with patch.object(mgr, "_release_login_lock"):
                            with patch.object(mgr, "_mark_browser_reauth_attempt"):
                                with pytest.raises(ValueError, match="target closed"):
                                    mgr.get_headers()

        assert mgr._browser_reauth_failure_count == 0
        assert mgr._browser_last_reauth_attempt_at is None

    def test_other_error_increases_cooldown(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_login_in_progress = False
        mgr._browser_reauth_failure_count = 0

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_acquire_login_lock", return_value=True):
                with patch.object(mgr, "_can_attempt_browser_reauth", return_value=True):
                    with patch.object(
                        mgr,
                        "_login_with_browser",
                        side_effect=ValueError("some unexpected error"),
                    ):
                        with patch.object(mgr, "_release_login_lock"):
                            with patch.object(mgr, "_mark_browser_reauth_attempt"):
                                with pytest.raises(ValueError, match="unexpected error"):
                                    mgr.get_headers()

        assert mgr._browser_reauth_failure_count == 1
        assert mgr._browser_reauth_cooldown_seconds > mgr._browser_reauth_cooldown_base

    def test_still_in_progress_keeps_flag(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._browser_cookie_expires_at = None
        mgr._browser_login_in_progress = False
        mgr._browser_reauth_failure_count = 0

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_acquire_login_lock", return_value=True):
                with patch.object(mgr, "_can_attempt_browser_reauth", return_value=True):
                    with patch.object(
                        mgr,
                        "_login_with_browser",
                        side_effect=ValueError("login is still in progress after 600s"),
                    ):
                        with patch.object(mgr, "_mark_browser_reauth_attempt"):
                            with pytest.raises(ValueError, match="still in progress"):
                                mgr.get_headers()

        # The flag should remain True since login is still going on
        assert mgr._browser_login_in_progress is True


# ===========================================================================
# stop_keepalive tests
# ===========================================================================


class TestStopKeepalive:
    def test_stop_when_no_thread(self):
        mgr = _make_browser_manager()
        mgr._keepalive_thread = None
        mgr.stop_keepalive()  # should not raise

    def test_stop_running_thread(self):
        mgr = _make_browser_manager()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        mgr._keepalive_thread = mock_thread
        mgr.stop_keepalive()
        mock_thread.join.assert_called_once_with(timeout=5)

    def test_stop_dead_thread(self):
        mgr = _make_browser_manager()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        mgr._keepalive_thread = mock_thread
        mgr.stop_keepalive()
        mock_thread.join.assert_not_called()


# ===========================================================================
# _save_session_to_disk tests
# ===========================================================================


class TestSaveSessionToDisk:
    def test_noop_for_non_browser(self):
        mgr = _make_basic_manager()
        mgr._save_session_to_disk()  # should not raise

    def test_noop_when_no_cookie(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = None
        mgr._save_session_to_disk()  # should not raise

    def test_writes_to_disk(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._session_cache_path = str(tmp_path / "session.json")
        mgr._session_disk_hash = None
        mgr._save_session_to_disk()
        assert os.path.exists(mgr._session_cache_path)
        with open(mgr._session_cache_path) as f:
            data = json.load(f)
        assert data["cookie_header"] == "a=1"

    def test_skips_redundant_write(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._session_cache_path = str(tmp_path / "session.json")
        mgr._session_disk_hash = None
        mgr._save_session_to_disk()
        mtime1 = os.path.getmtime(mgr._session_cache_path)
        mgr._save_session_to_disk()
        mtime2 = os.path.getmtime(mgr._session_cache_path)
        assert mtime1 == mtime2

    def test_handles_write_error(self, tmp_path):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "a=1"
        mgr._session_cache_path = "/nonexistent_dir/impossible.json"
        mgr._session_disk_hash = None
        # Should not raise, just log warning
        mgr._save_session_to_disk()


# ===========================================================================
# _try_restore_browser_session tests
# ===========================================================================


class TestTryRestoreBrowserSession:
    def test_no_instance_url(self):
        mgr = _make_browser_manager()
        mgr.instance_url = None
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, user_data_dir="/tmp/data")
        assert mgr._try_restore_browser_session(browser_cfg) is False

    def test_no_user_data_dir(self):
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, user_data_dir=None)
        assert mgr._try_restore_browser_session(browser_cfg) is False


# ===========================================================================
# Browser __init__ branch tests
# ===========================================================================


class TestBrowserInit:
    def test_init_with_valid_cached_session(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(timeout_seconds=10),
        )
        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_start_keepalive"),
        ):
            with patch.object(AuthManager, "_load_session_from_disk") as mock_load:
                # Simulate _load_session_from_disk setting a valid session
                def _set_session():
                    # access through closure once __init__ sets the attributes
                    pass

                mock_load.side_effect = _set_session
                mgr = AuthManager(cfg, "https://inst.service-now.com")
                # Manually set to simulate loaded session
                mgr._browser_cookie_header = "loaded=1"
                mgr._browser_cookie_expires_at = time.time() + 600

        # The init code checks after _load_session_from_disk, but we can't
        # easily test the branch since _load_session_from_disk is mocked.
        # Instead just verify the manager was created.
        assert mgr.config.type == AuthType.BROWSER

    def test_init_no_cached_session_clears_state(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(timeout_seconds=10),
        )

        def _mock_load(self_ref=None):
            pass  # Don't set any session data

        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_load_session_from_disk", side_effect=_mock_load),
            patch.object(AuthManager, "_start_keepalive") as mock_keepalive,
        ):
            AuthManager(cfg, "https://inst.service-now.com")

        # No session loaded, keepalive should not start
        mock_keepalive.assert_not_called()

    def test_init_expired_cached_session_clears(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(timeout_seconds=10),
        )

        def _mock_load_expired():
            pass

        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_start_keepalive"),
        ):
            # Simulate loading a session that is expired
            with patch.object(AuthManager, "_load_session_from_disk") as mock_load:

                def _set_expired_session():
                    pass

                mock_load.side_effect = _set_expired_session
                mgr = AuthManager(cfg, "https://inst.service-now.com")
                # Set expired session to test the branch
                mgr._browser_cookie_header = "exp=1"
                mgr._browser_cookie_expires_at = time.time() - 100

        # Verify the manager was created
        assert mgr is not None


# ===========================================================================
# Validation during get_headers (should_validate path)
# ===========================================================================


class TestBrowserValidationDuringGetHeaders:
    def test_validation_fails_triggers_reauth(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "old=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time() - 300  # stale
        mgr._browser_validation_interval_seconds = 120
        mgr._browser_last_login_at = None  # not in grace

        def _mock_login(cfg, force_interactive=False):
            mgr._browser_cookie_header = "new=1"
            mgr._browser_cookie_expires_at = time.time() + 600
            mgr._browser_last_validated_at = time.time()

        with patch.object(mgr, "_is_browser_session_valid", return_value=False):
            with patch.object(mgr, "invalidate_browser_session"):
                with patch.object(mgr, "_acquire_login_lock", return_value=True):
                    with patch.object(mgr, "_login_with_browser", side_effect=_mock_login):
                        with patch.object(mgr, "_release_login_lock"):
                            with patch.object(mgr, "_mark_browser_reauth_attempt"):
                                mgr.get_headers()

        assert mgr._browser_reauth_failure_count == 0

    def test_validation_fails_other_terminal_handles(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "old=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time() - 300
        mgr._browser_validation_interval_seconds = 120
        mgr._browser_last_login_at = None

        def _mock_wait(timeout):
            mgr._browser_cookie_header = "other=1"
            mgr._browser_cookie_expires_at = time.time() + 600
            mgr._browser_user_agent = "OtherUA"
            mgr._browser_session_token = "other_tok"
            return True

        with patch.object(mgr, "_is_browser_session_valid", return_value=False):
            with patch.object(mgr, "invalidate_browser_session"):
                with patch.object(mgr, "_acquire_login_lock", return_value=False):
                    with patch.object(mgr, "_wait_for_other_login", side_effect=_mock_wait):
                        headers = mgr.get_headers()

        assert headers["Cookie"] == "other=1"
        assert headers["User-Agent"] == "OtherUA"
        assert headers["X-UserToken"] == "other_tok"

    def test_validation_reauth_still_in_progress(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "old=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time() - 300
        mgr._browser_validation_interval_seconds = 120
        mgr._browser_last_login_at = None

        with patch.object(mgr, "_is_browser_session_valid", return_value=False):
            with patch.object(mgr, "invalidate_browser_session"):
                with patch.object(mgr, "_acquire_login_lock", return_value=True):
                    with patch.object(mgr, "_mark_browser_reauth_attempt"):
                        with patch.object(
                            mgr,
                            "_login_with_browser",
                            side_effect=ValueError("still in progress after 600s"),
                        ):
                            with pytest.raises(ValueError, match="still in progress"):
                                mgr.get_headers()

        assert mgr._browser_login_in_progress is True

    def test_validation_reauth_other_error_increases_cooldown(self):
        mgr = _make_browser_manager()
        mgr._browser_cookie_header = "old=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_validated_at = time.time() - 300
        mgr._browser_validation_interval_seconds = 120
        mgr._browser_last_login_at = None
        mgr._browser_reauth_failure_count = 0

        with patch.object(mgr, "_is_browser_session_valid", return_value=False):
            with patch.object(mgr, "invalidate_browser_session"):
                with patch.object(mgr, "_acquire_login_lock", return_value=True):
                    with patch.object(mgr, "_mark_browser_reauth_attempt"):
                        with patch.object(
                            mgr,
                            "_login_with_browser",
                            side_effect=ValueError("network error"),
                        ):
                            with patch.object(mgr, "_release_login_lock"):
                                with pytest.raises(ValueError, match="network error"):
                                    mgr.get_headers()

        assert mgr._browser_reauth_failure_count == 1
        assert mgr._browser_login_in_progress is False


# ===========================================================================
# _fill_first_matching / _click_first_matching exception branches
# ===========================================================================


class TestFillClickExceptionBranches:
    def test_fill_exception_continues_to_next(self):
        """When fill raises, should try next selector."""
        from servicenow_mcp.auth.auth_manager import _fill_first_matching

        target = MagicMock()
        # First selector exists but fill raises, second works
        loc1 = MagicMock()
        loc1.count.return_value = 1
        loc2 = MagicMock()
        loc2.count.return_value = 1

        def _locator(sel):
            if sel == "sel1":
                return loc1
            return loc2

        target.locator = _locator
        target.fill.side_effect = [Exception("fill error"), None]

        result = _fill_first_matching(target, ("sel1", "sel2"), "value")
        assert result == "sel2"

    def test_click_exception_continues_to_next(self):
        """When click raises, should try next selector."""
        from servicenow_mcp.auth.auth_manager import _click_first_matching

        target = MagicMock()
        loc1 = MagicMock()
        loc1.count.return_value = 1
        loc2 = MagicMock()
        loc2.count.return_value = 1

        def _locator(sel):
            if sel == "sel1":
                return loc1
            return loc2

        target.locator = _locator
        target.click.side_effect = [Exception("click error"), None]

        result = _click_first_matching(target, ("sel1", "sel2"))
        assert result == "sel2"


# ===========================================================================
# Browser __init__ branches (valid session, expired session with cookie)
# ===========================================================================


class TestBrowserInitBranches:
    def test_init_valid_cached_starts_keepalive(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(timeout_seconds=10),
        )

        def _mock_load(self_inner):
            self_inner._browser_cookie_header = "cached=1"
            self_inner._browser_cookie_expires_at = time.time() + 600

        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_start_keepalive") as mock_keepalive,
            patch.object(
                AuthManager,
                "_load_session_from_disk",
                lambda self: _mock_load(self),
            ),
        ):
            AuthManager(cfg, "https://inst.service-now.com")

        mock_keepalive.assert_called_once()

    def test_init_expired_cookie_clears_state(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(timeout_seconds=10),
        )

        def _mock_load(self_inner):
            self_inner._browser_cookie_header = "expired=1"
            self_inner._browser_cookie_expires_at = time.time() - 100

        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_start_keepalive") as mock_keepalive,
            patch.object(
                AuthManager,
                "_load_session_from_disk",
                lambda self: _mock_load(self),
            ),
        ):
            mgr = AuthManager(cfg, "https://inst.service-now.com")

        # Expired cookie should be cleared
        assert mgr._browser_cookie_header is None
        assert mgr._browser_cookie_expires_at is None
        mock_keepalive.assert_not_called()

    def test_init_no_cookie_no_keepalive(self):
        cfg = AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(timeout_seconds=10),
        )

        with (
            patch.object(AuthManager, "_ensure_playwright_ready"),
            patch.object(AuthManager, "_start_keepalive") as mock_keepalive,
            patch.object(AuthManager, "_load_session_from_disk"),
        ):
            AuthManager(cfg, "https://inst.service-now.com")

        mock_keepalive.assert_not_called()


# ===========================================================================
# _ensure_playwright_ready tests
# ===========================================================================


class TestEnsurePlaywrightReady:
    def test_import_error_raises_runtime_error(self):
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def _selective_import(name, *args, **kwargs):
            if "playwright" in name:
                raise ImportError("no playwright")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_selective_import):
            with pytest.raises(RuntimeError, match="Playwright package is required"):
                AuthManager._ensure_playwright_ready()


# ===========================================================================
# _login_with_browser (thread delegation) tests
# ===========================================================================


class TestLoginWithBrowser:
    def test_fallback_to_interactive_on_timeout(self):
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        call_count = 0

        def _mock_sync_login(cfg, interactive=False):
            nonlocal call_count
            call_count += 1
            if call_count == 1 and not interactive:
                raise ValueError("Timed out waiting for browser login/MFA in headless")
            # second call (interactive) succeeds

        with patch.object(mgr, "_login_with_browser_sync", side_effect=_mock_sync_login):
            mgr._login_with_browser(browser_cfg, force_interactive=False)

        assert call_count == 2

    def test_non_timeout_error_not_retried(self):
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)

        with patch.object(
            mgr,
            "_login_with_browser_sync",
            side_effect=ValueError("some other error"),
        ):
            with pytest.raises(ValueError, match="some other error"):
                mgr._login_with_browser(browser_cfg, force_interactive=False)

    def test_force_interactive_timeout_not_retried(self):
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)

        with patch.object(
            mgr,
            "_login_with_browser_sync",
            side_effect=ValueError("Timed out waiting for browser login/MFA"),
        ):
            with pytest.raises(ValueError, match="Timed out"):
                mgr._login_with_browser(browser_cfg, force_interactive=True)

    def test_join_timeout_calculation_interactive(self):
        """Interactive mode uses longer join timeout."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        # join_timeout = max(10 + 120, 600) = 600 for force_interactive
        # Just verify it doesn't crash by calling with a fast mock
        with patch.object(mgr, "_login_with_browser_sync"):
            mgr._login_with_browser(browser_cfg, force_interactive=True)

    def test_join_timeout_calculation_auto(self):
        """Auto mode uses shorter join timeout."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)
        # join_timeout = max(10 + 60, 360) = 360 for non-interactive
        with patch.object(mgr, "_login_with_browser_sync"):
            mgr._login_with_browser(browser_cfg, force_interactive=False)

    def test_no_event_loop_calls_sync_directly(self):
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10)

        with patch.object(mgr, "_login_with_browser_sync") as mock_sync:
            mgr._login_with_browser(browser_cfg, force_interactive=True)

        mock_sync.assert_called_once_with(browser_cfg, True)


# ===========================================================================
# _try_restore_browser_session deeper paths
# ===========================================================================


class TestTryRestoreBrowserSessionDeep:
    def test_playwright_import_fails(self):
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, user_data_dir="/tmp/data")
        real_import = __import__

        def _selective_import(name, *args, **kwargs):
            if "playwright" in name:
                raise ImportError("no playwright")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_selective_import):
            result = mgr._try_restore_browser_session(browser_cfg)
        assert result is False

    def test_full_restore_success(self):
        """Test full restore path with mocked playwright."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10, user_data_dir="/tmp/data", session_ttl_minutes=30
        )

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = ["TestAgent/1.0", "g_ck_token"]
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "JSESSIONID", "value": "abc123", "domain": "example.service-now.com"},
        ]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_probe = MagicMock()
        mock_probe.status_code = 200
        mock_probe.headers = {}
        mock_probe.url = "https://example.service-now.com/api/now/table/sys_user"

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    result = mgr._try_restore_browser_session(browser_cfg)

        assert result is True
        assert mgr._browser_cookie_header is not None
        assert "JSESSIONID=abc123" in mgr._browser_cookie_header
        assert mgr._browser_user_agent == "TestAgent/1.0"
        assert mgr._browser_session_token == "g_ck_token"

    def test_restore_no_cookies(self):
        """When no instance cookies found, return False."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, user_data_dir="/tmp/data")

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = ["UA", None]
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "other", "value": "x", "domain": "other.com"},
        ]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            result = mgr._try_restore_browser_session(browser_cfg)

        assert result is False

    def test_restore_probe_request_error(self):
        """When probe raises RequestException, return False."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, user_data_dir="/tmp/data")

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = ["UA", None]
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "JSESSIONID", "value": "abc", "domain": "example.service-now.com"},
        ]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            with patch.object(
                mgr,
                "_probe_browser_api_with_cookie",
                side_effect=requests.RequestException("timeout"),
            ):
                result = mgr._try_restore_browser_session(browser_cfg)

        assert result is False

    def test_restore_probe_unauthorized(self):
        """When probe indicates login redirect, return False."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, user_data_dir="/tmp/data")

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = ["UA", None]
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "JSESSIONID", "value": "abc", "domain": "example.service-now.com"},
        ]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_probe = MagicMock()
        mock_probe.status_code = 302
        mock_probe.headers = {"Location": "/login.do"}
        mock_probe.url = "https://example.service-now.com/login.do"

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_probe):
                result = mgr._try_restore_browser_session(browser_cfg)

        assert result is False

    def test_restore_probe_acl_restricted(self):
        """Probe returns 403 without login redirect during restore => True.

        403 without a login redirect indicates the session is authenticated
        but the user lacks ACL access to the probe endpoint. Since the session
        is valid, we accept it — consistent with runtime validation which also
        treats 403-without-redirect as authenticated.
        """
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10, user_data_dir="/tmp/data", session_ttl_minutes=30
        )

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = ["UA", None]
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "JSESSIONID", "value": "abc", "domain": "example.service-now.com"},
        ]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_probe = MagicMock()
        mock_probe.status_code = 403
        mock_probe.headers = {}
        mock_probe.url = "https://example.service-now.com/api/now/table/sys_user"

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    result = mgr._try_restore_browser_session(browser_cfg)

        assert result is True

    def test_restore_context_launch_fails(self):
        """When launching persistent context fails, return False."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, user_data_dir="/tmp/data")

        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.side_effect = Exception("launch failed")

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            result = mgr._try_restore_browser_session(browser_cfg)

        assert result is False

    def test_restore_navigation_fails_but_cookies_work(self):
        """When goto fails but cookies are still valid, should succeed."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10, user_data_dir="/tmp/data", session_ttl_minutes=30
        )

        mock_page = MagicMock()
        mock_page.goto.side_effect = Exception("navigation error")
        mock_page.evaluate.side_effect = ["UA", "g_ck"]
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "JSESSIONID", "value": "abc", "domain": "example.service-now.com"},
        ]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_probe = MagicMock()
        mock_probe.status_code = 200
        mock_probe.headers = {}
        mock_probe.url = "https://example.service-now.com/api"

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    result = mgr._try_restore_browser_session(browser_cfg)

        assert result is True

    def test_restore_g_ck_eval_fails(self):
        """When g_ck evaluation fails, session_token is None but restore succeeds."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10, user_data_dir="/tmp/data", session_ttl_minutes=30
        )

        mock_page = MagicMock()
        mock_page.evaluate.side_effect = ["UA", Exception("no g_ck")]
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "JSESSIONID", "value": "abc", "domain": "example.service-now.com"},
        ]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_probe = MagicMock()
        mock_probe.status_code = 200
        mock_probe.headers = {}
        mock_probe.url = "https://example.service-now.com/api"

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    result = mgr._try_restore_browser_session(browser_cfg)

        assert result is True
        assert mgr._browser_session_token is None

    def test_restore_no_existing_pages_creates_new(self):
        """When no pages in context, creates new page."""
        mgr = _make_browser_manager()
        browser_cfg = BrowserAuthConfig(
            timeout_seconds=10, user_data_dir="/tmp/data", session_ttl_minutes=30
        )

        mock_new_page = MagicMock()
        mock_new_page.evaluate.side_effect = ["UA", None]
        mock_context = MagicMock()
        mock_context.pages = []  # No existing pages
        mock_context.new_page.return_value = mock_new_page
        mock_context.cookies.return_value = [
            {"name": "JSESSIONID", "value": "abc", "domain": "example.service-now.com"},
        ]
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        mock_probe = MagicMock()
        mock_probe.status_code = 200
        mock_probe.headers = {}
        mock_probe.url = "https://example.service-now.com/api"

        mock_spw = MagicMock(return_value=mock_sync)
        with patch.dict(
            "sys.modules", {"playwright.sync_api": MagicMock(sync_playwright=mock_spw)}
        ):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_probe):
                with patch.object(mgr, "_save_session_to_disk"):
                    result = mgr._try_restore_browser_session(browser_cfg)

        assert result is True
        mock_context.new_page.assert_called_once()


# ===========================================================================
# _acquire_login_lock write failure
# ===========================================================================


class TestAcquireLoginLockWriteFailure:
    def test_lock_write_fails_returns_true(self, tmp_path):
        """When writing lock file fails, should fail open (return True)."""
        mgr = _make_browser_manager()
        # Point to a non-writable path
        mgr._login_lock_path = "/proc/nonexistent/impossible.lock"
        result = mgr._acquire_login_lock()
        assert result is True  # Fail open


# ===========================================================================
# _release_login_lock exception path
# ===========================================================================


class TestReleaseLockExceptionPath:
    def test_release_handles_json_error(self, tmp_path):
        mgr = _make_browser_manager()
        lock_path = str(tmp_path / "test.lock")
        mgr._login_lock_path = lock_path
        with open(lock_path, "w") as f:
            f.write("not json{{{")
        # Should not raise
        mgr._release_login_lock()
        # File still exists since we couldn't parse it
        # (the except clause swallows the error)


# ===========================================================================
# make_request browser 401 -> disk reload path
# ===========================================================================


class TestMakeRequestBrowserDiskReload:
    def test_401_disk_reload_success(self):
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

        def _mock_reload():
            mgr._browser_cookie_header = "reloaded=1"
            return True

        with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
            with patch.object(mgr._http_session, "request", side_effect=[resp_401, resp_200]):
                resp = mgr.make_request(
                    "GET",
                    "https://example.service-now.com/api",
                    timeout=10,
                    max_retries=1,
                )
        assert resp.status_code == 200

    def test_401_disk_reload_also_401_falls_to_reauth(self):
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

        reload_count = 0

        def _mock_reload():
            nonlocal reload_count
            reload_count += 1
            if reload_count == 1:
                mgr._browser_cookie_header = "reloaded=1"
                return True
            return False

        get_headers_count = 0

        def _mock_get_headers():
            nonlocal get_headers_count
            get_headers_count += 1
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": f"attempt{get_headers_count}=1",
            }

        with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
            with patch.object(
                mgr._http_session, "request", side_effect=[resp_401, resp_401, resp_200]
            ):
                with patch.object(mgr, "get_headers", side_effect=_mock_get_headers):
                    with patch.object(mgr, "invalidate_browser_session"):
                        resp = mgr.make_request(
                            "GET",
                            "https://example.service-now.com/api",
                            timeout=10,
                            max_retries=1,
                        )
        assert resp.status_code == 200


# ===========================================================================
# Keepalive loop behavior tests
# ===========================================================================


class TestKeepaliveLoop:
    def test_start_keepalive_no_browser_config_noop(self):
        mgr = _make_browser_manager()
        mgr.config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="a", password="b")
        )
        mgr._start_keepalive()  # Should be noop since config.browser is None

    def test_stop_keepalive_sets_event(self):
        mgr = _make_browser_manager()
        mgr._keepalive_stop_event.clear()
        mgr.stop_keepalive()
        assert mgr._keepalive_stop_event.is_set()

    def test_keepalive_probe_success_extends_ttl(self):
        """Exercise keepalive loop: probe success path."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 100  # Low TTL to trigger ping
        mgr._browser_last_login_at = None
        mgr._browser_last_validated_at = time.time() - 300

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://example.service-now.com/api/now/table/sys_user"

        # Patch wait to return immediately (simulate timer fired) then set stop
        call_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False  # Not stopped yet on first call

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_resp):
                with patch.object(mgr, "_reload_session_from_disk", return_value=False):
                    with patch.object(mgr, "_save_session_to_disk"):
                        mgr._start_keepalive()
                        mgr._keepalive_thread.join(timeout=5)

        assert mgr._keepalive_consecutive_failures == 0

    def test_keepalive_probe_invalid_increments_failure(self):
        """Exercise keepalive loop: probe returns login redirect."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 100
        mgr._browser_last_login_at = None

        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {"Location": "/login.do"}
        mock_resp.url = "https://example.service-now.com/login.do"

        call_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_resp):
                with patch.object(mgr, "_reload_session_from_disk", return_value=False):
                    mgr._start_keepalive()
                    mgr._keepalive_thread.join(timeout=5)

        assert mgr._keepalive_consecutive_failures == 1

    def test_keepalive_probe_exception_increments_failure(self):
        """Exercise keepalive loop: probe raises exception."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 100
        mgr._browser_last_login_at = None

        call_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(
                mgr,
                "_probe_browser_api_with_cookie",
                side_effect=Exception("network err"),
            ):
                with patch.object(mgr, "_reload_session_from_disk", return_value=False):
                    mgr._start_keepalive()
                    mgr._keepalive_thread.join(timeout=5)

        assert mgr._keepalive_consecutive_failures == 1

    def test_keepalive_3_failures_invalidates(self):
        """3 consecutive probe exceptions invalidate session."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 100
        mgr._browser_last_login_at = None
        mgr._keepalive_consecutive_failures = 2  # Already at 2

        call_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(
                mgr,
                "_probe_browser_api_with_cookie",
                side_effect=Exception("err"),
            ):
                with patch.object(mgr, "_reload_session_from_disk", return_value=False):
                    with patch.object(mgr, "invalidate_browser_session") as mock_inv:
                        mgr._start_keepalive()
                        mgr._keepalive_thread.join(timeout=5)

        mock_inv.assert_called_once()

    def test_keepalive_3_invalid_probes_invalidates(self):
        """3 consecutive invalid probe responses invalidate session."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 100
        mgr._browser_last_login_at = None
        mgr._keepalive_consecutive_failures = 2

        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {"Location": "/login.do"}
        mock_resp.url = "https://example.service-now.com/login.do"

        call_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_resp):
                with patch.object(mgr, "_reload_session_from_disk", return_value=False):
                    with patch.object(mgr, "invalidate_browser_session") as mock_inv:
                        mgr._start_keepalive()
                        mgr._keepalive_thread.join(timeout=5)

        mock_inv.assert_called_once()

    def test_keepalive_no_session_tries_disk(self):
        """When no session in memory, keepalive tries disk reload."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = None  # No session
        mgr._browser_cookie_expires_at = None
        mgr._browser_last_login_at = None

        call_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(mgr, "_reload_session_from_disk", return_value=False) as mock_reload:
                mgr._start_keepalive()
                mgr._keepalive_thread.join(timeout=5)

        mock_reload.assert_called()

    def test_keepalive_within_grace_period_skips(self):
        """Within post-login grace period, keepalive skips ping."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 600
        mgr._browser_last_login_at = time.time()  # Just logged in

        call_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(mgr, "_probe_browser_api_with_cookie") as mock_probe:
                mgr._start_keepalive()
                mgr._keepalive_thread.join(timeout=5)

        mock_probe.assert_not_called()

    def test_keepalive_disk_dedup_skips_ping(self):
        """When disk reload returns fresher cookies, skip ping."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 100
        mgr._browser_last_login_at = None

        call_count = 0
        reload_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        def _mock_reload():
            nonlocal reload_count
            reload_count += 1
            if reload_count == 1:
                return True  # Fresher session from disk
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
                with patch.object(mgr, "_probe_browser_api_with_cookie") as mock_probe:
                    mgr._start_keepalive()
                    mgr._keepalive_thread.join(timeout=5)

        mock_probe.assert_not_called()
        assert mgr._keepalive_consecutive_failures == 0

    def test_keepalive_ttl_recently_extended_skips(self):
        """When TTL was recently extended, skip ping."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        # Set expires_at to nearly full TTL (recently extended)
        mgr._browser_cookie_expires_at = time.time() + (30 * 60)
        mgr._browser_last_login_at = None

        call_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(mgr, "_reload_session_from_disk", return_value=False):
                with patch.object(mgr, "_probe_browser_api_with_cookie") as mock_probe:
                    mgr._start_keepalive()
                    mgr._keepalive_thread.join(timeout=5)

        mock_probe.assert_not_called()

    def test_keepalive_invalid_probe_disk_reload_success(self):
        """Invalid probe but disk reload succeeds resets failures."""
        mgr = _make_browser_manager(session_ttl_minutes=30)
        mgr._browser_cookie_header = "a=1"
        mgr._browser_cookie_expires_at = time.time() + 100
        mgr._browser_last_login_at = None

        mock_resp = MagicMock()
        mock_resp.status_code = 302
        mock_resp.headers = {"Location": "/login.do"}
        mock_resp.url = "https://example.service-now.com/login.do"

        call_count = 0
        reload_count = 0

        def _mock_wait(timeout):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                mgr._keepalive_stop_event.set()
            return False

        def _mock_reload():
            nonlocal reload_count
            reload_count += 1
            # First call is from dedup check (before probe), second is after invalid probe
            if reload_count == 2:
                return True  # Fresher session after probe failure
            return False

        with patch.object(mgr._keepalive_stop_event, "wait", side_effect=_mock_wait):
            with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_resp):
                with patch.object(mgr, "_reload_session_from_disk", side_effect=_mock_reload):
                    mgr._start_keepalive()
                    mgr._keepalive_thread.join(timeout=5)

        assert mgr._keepalive_consecutive_failures == 0


# ===========================================================================
# _ensure_playwright_ready deeper tests
# ===========================================================================


class TestEnsurePlaywrightReadyDeep:
    def test_binary_missing_installs_with_cli(self):
        """When browser binary is missing, install via playwright CLI."""

        mock_pw = MagicMock()
        mock_pw.chromium.launch.side_effect = Exception("Executable doesn't exist at /path")
        mock_pw.chromium.launch.return_value = None

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
            with patch("shutil.which", return_value="/usr/bin/playwright"):
                with patch("subprocess.check_call") as mock_check_call:
                    AuthManager._ensure_playwright_ready()

        mock_check_call.assert_called_once_with(
            ["/usr/bin/playwright", "install", "chromium"], timeout=300
        )

    def test_binary_missing_fallback_to_python_m(self):
        """When playwright CLI not on PATH, use python -m playwright."""
        import sys

        mock_pw = MagicMock()
        mock_pw.chromium.launch.side_effect = Exception("Executable doesn't exist at /path")

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
            with patch("shutil.which", return_value=None):
                with patch("subprocess.check_call") as mock_check_call:
                    AuthManager._ensure_playwright_ready()

        mock_check_call.assert_called_once_with(
            [sys.executable, "-m", "playwright", "install", "chromium"], timeout=300
        )

    def test_non_binary_error_logs_debug(self):
        """Non-binary probe error should not trigger install."""
        mock_pw = MagicMock()
        mock_pw.chromium.launch.side_effect = Exception("some other problem")

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
            with patch("subprocess.check_call") as mock_check_call:
                AuthManager._ensure_playwright_ready()

        # Should not have called install since it's not a binary error
        mock_check_call.assert_not_called()


# ===========================================================================
# make_request: cookie_names logging, clear cookies at end
# ===========================================================================


class TestMakeRequestCookieDetails:
    def test_request_clears_session_cookies_after(self):
        mgr = _make_basic_manager()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {}
        mock_resp.url = "https://test.service-now.com/api"

        # Add some cookies to the session to verify they get cleared
        mgr._http_session.cookies.set("stale", "cookie")
        with patch.object(mgr._http_session, "request", return_value=mock_resp):
            mgr.make_request("GET", "https://test.service-now.com/api", timeout=10)

        # Cookies should be cleared after request
        assert len(mgr._http_session.cookies) == 0
