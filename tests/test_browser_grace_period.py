"""
Tests for browser post-login grace period protection.

Verifies that within the 90-second grace window after a successful login,
no code path can trigger a duplicate browser window:

1. _should_validate_browser_session → returns False during grace
2. _is_browser_session_valid → skips probe during grace, returns True
3. keepalive thread → skips probe during grace
4. make_request 401 handler → retries with existing cookies during grace
"""

import time
from unittest.mock import MagicMock, patch

import requests

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig


def _make_manager(
    *,
    login_at: float | None = None,
    grace_seconds: int = 90,
    cookie: str = "JSESSIONID=abc123",
    ttl_minutes: int = 30,
    validated_at: float | None = None,
    validation_interval: int = 120,
) -> AuthManager:
    """Create a browser-auth manager with controllable grace period state."""
    cfg = AuthConfig(
        type=AuthType.BROWSER,
        browser=BrowserAuthConfig(
            headless=False,
            timeout_seconds=10,
            session_ttl_minutes=ttl_minutes,
        ),
    )
    with (
        patch.object(AuthManager, "_ensure_playwright_ready"),
        patch.object(AuthManager, "_load_session_from_disk"),
        patch.object(AuthManager, "_start_keepalive"),
    ):
        mgr = AuthManager(cfg, "https://test.service-now.com")

    mgr._browser_cookie_header = cookie
    mgr._browser_cookie_expires_at = time.time() + (ttl_minutes * 60)
    mgr._browser_last_login_at = login_at
    mgr._browser_last_validated_at = validated_at
    mgr._browser_post_login_grace_seconds = grace_seconds
    mgr._browser_validation_interval_seconds = validation_interval
    return mgr


# ================================================================
# 1. _should_validate_browser_session — grace period blocks validation
# ================================================================


class TestShouldValidateGracePeriod:
    def test_within_grace_returns_false(self):
        mgr = _make_manager(login_at=time.time())
        assert mgr._should_validate_browser_session() is False

    def test_just_inside_grace_boundary_returns_false(self):
        mgr = _make_manager(login_at=time.time() - 89)
        assert mgr._should_validate_browser_session() is False

    def test_just_outside_grace_boundary_returns_true(self):
        """After grace expires, validation should be allowed."""
        mgr = _make_manager(
            login_at=time.time() - 91,
            validated_at=None,  # never validated → should trigger
        )
        assert mgr._should_validate_browser_session() is True

    def test_no_login_at_and_no_validated_at_returns_true(self):
        """No grace data at all — first-time session, should validate."""
        mgr = _make_manager(login_at=None, validated_at=None)
        assert mgr._should_validate_browser_session() is True

    def test_recently_validated_returns_false(self):
        """Validated 10 seconds ago, interval is 120s → no re-validation."""
        mgr = _make_manager(
            login_at=time.time() - 200,  # grace expired
            validated_at=time.time() - 10,  # but recently validated
        )
        assert mgr._should_validate_browser_session() is False

    def test_validation_interval_expired_returns_true(self):
        mgr = _make_manager(
            login_at=time.time() - 200,
            validated_at=time.time() - 130,  # 130s > 120s interval
        )
        assert mgr._should_validate_browser_session() is True

    def test_no_cookie_returns_false(self):
        mgr = _make_manager(login_at=time.time(), cookie="")
        assert mgr._should_validate_browser_session() is False


# ================================================================
# 2. _is_browser_session_valid — skips probe during grace
# ================================================================


class TestIsValidGracePeriod:
    def test_within_grace_skips_probe_returns_true(self):
        mgr = _make_manager(login_at=time.time())
        # Should NOT call the HTTP probe at all
        with patch.object(mgr, "_probe_browser_api_with_cookie") as mock_probe:
            result = mgr._is_browser_session_valid(mgr.config.browser)

        assert result is True
        mock_probe.assert_not_called()
        # Should update validated_at
        assert mgr._browser_last_validated_at is not None

    def test_outside_grace_does_probe(self):
        mgr = _make_manager(login_at=time.time() - 200)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {}
        mock_response.url = "https://test.service-now.com/api/now/table/sys_user"

        with patch.object(
            mgr, "_probe_browser_api_with_cookie", return_value=mock_response
        ) as mock_probe:
            result = mgr._is_browser_session_valid(mgr.config.browser)

        assert result is True
        mock_probe.assert_called_once()

    def test_outside_grace_probe_failure_returns_false(self):
        mgr = _make_manager(login_at=time.time() - 200)

        with patch.object(
            mgr,
            "_probe_browser_api_with_cookie",
            side_effect=requests.RequestException("timeout"),
        ):
            result = mgr._is_browser_session_valid(mgr.config.browser)

        assert result is False

    def test_no_login_at_does_probe(self):
        """First-ever session (no login_at) — must probe."""
        mgr = _make_manager(login_at=None)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {}
        mock_response.url = "https://test.service-now.com/api/now/table/sys_user"

        with patch.object(
            mgr, "_probe_browser_api_with_cookie", return_value=mock_response
        ) as mock_probe:
            mgr._is_browser_session_valid(mgr.config.browser)

        mock_probe.assert_called_once()


# ================================================================
# 3. get_headers validation path — no re-login during grace
# ================================================================


class TestGetHeadersGracePeriod:
    def test_get_headers_within_grace_no_relogin(self):
        """Even if _browser_last_validated_at is None, grace period prevents validation."""
        mgr = _make_manager(login_at=time.time(), validated_at=None)

        with patch.object(mgr, "_login_with_browser") as mock_login:
            headers = mgr.get_headers()

        mock_login.assert_not_called()
        assert "Cookie" in headers

    def test_get_headers_outside_grace_probe_ok_no_relogin(self):
        """After grace, probe succeeds → no re-login."""
        mgr = _make_manager(
            login_at=time.time() - 200,
            validated_at=time.time() - 130,  # expired interval
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.headers = {}
        mock_response.url = "https://test.service-now.com/api/now/table/sys_user"

        with patch.object(mgr, "_probe_browser_api_with_cookie", return_value=mock_response):
            with patch.object(mgr, "_login_with_browser") as mock_login:
                headers = mgr.get_headers()

        mock_login.assert_not_called()
        assert headers["Cookie"] == "JSESSIONID=abc123"

    def test_get_headers_outside_grace_probe_fail_triggers_relogin(self):
        """After grace, probe fails → re-login is triggered."""
        mgr = _make_manager(
            login_at=time.time() - 200,
            validated_at=time.time() - 130,
        )

        # Probe returns 401 with redirect to login page
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.is_redirect = True
        mock_response.headers = {"Location": "/login.do"}
        mock_response.url = "https://test.service-now.com/login.do"

        def _fake_login(_cfg, force_interactive=False):
            mgr._browser_cookie_header = "NEW=session"
            mgr._browser_cookie_expires_at = time.time() + 1800
            mgr._browser_last_validated_at = time.time()
            mgr._browser_last_login_at = time.time()

        with patch.object(mgr._http_session, "get", return_value=mock_response):
            with patch.object(mgr, "_login_with_browser", side_effect=_fake_login) as mock_login:
                headers = mgr.get_headers()

        mock_login.assert_called_once()
        assert headers["Cookie"] == "NEW=session"


# ================================================================
# 4. make_request 401 handler — retry before re-login during grace
# ================================================================


class TestMakeRequest401GracePeriod:
    def _setup_manager_for_request(self):
        mgr = _make_manager(login_at=time.time())
        mgr._browser_last_reauth_attempt_at = None
        return mgr

    def test_401_within_grace_retries_first(self):
        """401 during grace → retry with existing cookies, not re-login."""
        mgr = self._setup_manager_for_request()

        first_response = MagicMock()
        first_response.status_code = 401
        first_response.headers = {}
        first_response.url = "https://test.service-now.com/api/now/table/sys_user"

        retry_response = MagicMock()
        retry_response.status_code = 200

        with patch.object(
            mgr,
            "get_headers",
            return_value={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "JSESSIONID=abc123",
            },
        ):
            with patch.object(
                mgr._http_session, "request", side_effect=[first_response, retry_response]
            ):
                with patch.object(mgr, "invalidate_browser_session") as mock_invalidate:
                    response = mgr.make_request(
                        "GET",
                        "https://test.service-now.com/api/now/table/sys_user",
                        timeout=10,
                        max_retries=1,
                    )

        assert response.status_code == 200
        mock_invalidate.assert_not_called()

    def test_401_within_grace_retry_also_401_then_reauth(self):
        """401 during grace → retry also 401 → proceed to full re-auth."""
        mgr = self._setup_manager_for_request()

        response_401 = MagicMock()
        response_401.status_code = 401
        response_401.headers = {}
        response_401.url = "https://test.service-now.com/api/now/table/sys_user"

        response_200 = MagicMock()
        response_200.status_code = 200

        call_count = [0]

        def _fake_get_headers():
            call_count[0] += 1
            if call_count[0] <= 1:
                return {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Cookie": "JSESSIONID=abc123",
                }
            # After re-auth
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "NEW=session",
            }

        with patch.object(mgr, "get_headers", side_effect=_fake_get_headers):
            with patch.object(
                mgr._http_session,
                "request",
                side_effect=[response_401, response_401, response_200],
            ):
                with patch.object(mgr, "invalidate_browser_session"):
                    response = mgr.make_request(
                        "GET",
                        "https://test.service-now.com/api/now/table/sys_user",
                        timeout=10,
                        max_retries=1,
                    )

        assert response.status_code == 200

    def test_401_outside_grace_no_retry_direct_reauth(self):
        """401 after grace expired → skip retry, go straight to re-auth."""
        mgr = _make_manager(login_at=time.time() - 200)
        mgr._browser_last_reauth_attempt_at = None

        response_401 = MagicMock()
        response_401.status_code = 401
        response_401.headers = {"Location": "/login.do"}
        response_401.url = "https://test.service-now.com/login.do"

        response_200 = MagicMock()
        response_200.status_code = 200

        call_count = [0]

        def _fake_get_headers():
            call_count[0] += 1
            if call_count[0] <= 1:
                return {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Cookie": "OLD=session",
                }
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "NEW=session",
            }

        with patch.object(mgr, "get_headers", side_effect=_fake_get_headers):
            with patch.object(
                mgr._http_session, "request", side_effect=[response_401, response_200]
            ):
                with patch.object(mgr, "invalidate_browser_session") as mock_invalidate:
                    result = mgr.make_request(
                        "GET",
                        "https://test.service-now.com/api/now/table/sys_user",
                        timeout=10,
                        max_retries=1,
                    )

        assert result.status_code == 200
        mock_invalidate.assert_called_once()

    def test_401_no_login_at_no_retry_direct_reauth(self):
        """No login_at (restored session) → no grace, direct re-auth on 401."""
        mgr = _make_manager(login_at=None)
        mgr._browser_last_reauth_attempt_at = None

        response_401 = MagicMock()
        response_401.status_code = 401
        response_401.headers = {}
        response_401.url = "https://test.service-now.com/api/now/table/sys_user"

        response_200 = MagicMock()
        response_200.status_code = 200

        call_count = [0]

        def _fake_get_headers():
            call_count[0] += 1
            if call_count[0] <= 1:
                return {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Cookie": "OLD=session",
                }
            return {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Cookie": "NEW=session",
            }

        with patch.object(mgr, "get_headers", side_effect=_fake_get_headers):
            with patch.object(
                mgr._http_session, "request", side_effect=[response_401, response_200]
            ):
                with patch.object(mgr, "invalidate_browser_session") as mock_invalidate:
                    mgr.make_request(
                        "GET",
                        "https://test.service-now.com/api/now/table/sys_user",
                        timeout=10,
                        max_retries=1,
                    )

        mock_invalidate.assert_called_once()


# ================================================================
# 5. Edge cases — boundary conditions
# ================================================================


class TestGracePeriodEdgeCases:
    def test_grace_period_exactly_at_boundary(self):
        """At exactly grace_seconds, should be outside grace."""
        mgr = _make_manager(login_at=time.time() - 90, grace_seconds=90)
        # time.time() - login_at >= grace_seconds → outside
        assert mgr._should_validate_browser_session() is True

    def test_multiple_get_headers_calls_within_grace(self):
        """Multiple rapid calls — none should trigger validation."""
        mgr = _make_manager(login_at=time.time(), validated_at=None)

        with patch.object(mgr, "_login_with_browser") as mock_login:
            for _ in range(10):
                mgr.get_headers()

        mock_login.assert_not_called()

    def test_session_expired_during_grace_triggers_login(self):
        """If TTL expired but still in grace, the expired check takes priority."""
        mgr = _make_manager(
            login_at=time.time(),
            ttl_minutes=0,  # already expired
        )
        mgr._browser_cookie_expires_at = time.time() - 1  # expired

        # Restore should fail, then login path
        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_login_with_browser") as mock_login:

                def _fake_login(_cfg, force_interactive=False):
                    mgr._browser_cookie_header = "NEW=cookie"
                    mgr._browser_cookie_expires_at = time.time() + 1800
                    mgr._browser_last_login_at = time.time()

                mock_login.side_effect = _fake_login
                mgr.get_headers()

        mock_login.assert_called_once()

    def test_login_in_progress_blocks_concurrent_call(self):
        """If login is in progress, second call should raise, not open another browser."""
        mgr = _make_manager(cookie="")
        mgr._browser_cookie_header = None
        mgr._browser_login_in_progress = True

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            try:
                mgr.get_headers()
                raise AssertionError("Should have raised ValueError")
            except ValueError as exc:
                assert "currently in progress" in str(exc)

    def test_browser_closed_by_user_resets_cooldown(self):
        """When user closes browser manually, cooldown resets for immediate retry."""
        mgr = _make_manager(cookie="")
        mgr._browser_cookie_header = None
        mgr._browser_reauth_failure_count = 0

        def _raise_closed(_cfg, force_interactive=False):
            raise ValueError("Target page, context or browser has been closed")

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_login_with_browser", side_effect=_raise_closed):
                try:
                    mgr.get_headers()
                except ValueError:
                    pass

        # Should NOT increment failure count
        assert mgr._browser_reauth_failure_count == 0
        # Should allow immediate retry
        assert mgr._browser_last_reauth_attempt_at is None
        assert mgr._browser_login_in_progress is False

    def test_real_failure_increments_cooldown(self):
        """Actual login failure (not user-closed) should increase cooldown."""
        mgr = _make_manager(cookie="")
        mgr._browser_cookie_header = None
        mgr._browser_reauth_failure_count = 0

        def _raise_error(_cfg, force_interactive=False):
            raise ValueError("Timed out waiting for browser login/MFA in headless mode.")

        with patch.object(mgr, "_try_restore_browser_session", return_value=False):
            with patch.object(mgr, "_login_with_browser", side_effect=_raise_error):
                try:
                    mgr.get_headers()
                except ValueError:
                    pass

        assert mgr._browser_reauth_failure_count == 1
        assert mgr._browser_reauth_cooldown_seconds > mgr._browser_reauth_cooldown_base
