"""Invariant tests for the background server-session keep-alive
(src/servicenow_mcp/auth/_keepalive.py, v1.18.45).

Pinned guarantees:
- Keepalive NEVER opens a browser or triggers a login — a rejected ping only
  logs and leaves recovery to the next real tool call.
- Idle horizon: no pings once real tool activity is older than the max-idle
  window, and keepalive's own pings do not refresh that horizon.
- Opt-out via SERVICENOW_SESSION_KEEPALIVE=off (default is ON).
- Foreground-recently-validated sessions are not re-pinged.
"""

import time
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth._keepalive import (
    _keepalive_enabled,
    _keepalive_interval_s,
    _keepalive_max_idle_s,
)
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig


def _make_manager() -> AuthManager:
    cfg = AuthConfig(
        type=AuthType.BROWSER,
        browser=BrowserAuthConfig(headless=True, timeout_seconds=10, session_ttl_minutes=30),
    )
    with (
        patch.object(AuthManager, "_ensure_playwright_ready"),
        patch.object(AuthManager, "_load_session_from_disk"),
    ):
        return AuthManager(cfg, "https://example.service-now.com")


def _probe_response(status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.url = "https://example.service-now.com/api/now/table/sys_user_preference"
    response.text = '{"result": []}'
    return response


class TestEnvGates:
    def test_default_enabled(self, monkeypatch):
        monkeypatch.delenv("SERVICENOW_SESSION_KEEPALIVE", raising=False)
        assert _keepalive_enabled() is True

    def test_off_values_disable(self, monkeypatch):
        for value in ("off", "false", "0", "no", "OFF"):
            monkeypatch.setenv("SERVICENOW_SESSION_KEEPALIVE", value)
            assert _keepalive_enabled() is False

    def test_interval_floor_and_default(self, monkeypatch):
        monkeypatch.delenv("SERVICENOW_SESSION_KEEPALIVE_INTERVAL_S", raising=False)
        assert _keepalive_interval_s() == 300.0
        monkeypatch.setenv("SERVICENOW_SESSION_KEEPALIVE_INTERVAL_S", "5")
        assert _keepalive_interval_s() == 60.0  # min floor
        monkeypatch.setenv("SERVICENOW_SESSION_KEEPALIVE_INTERVAL_S", "not-a-number")
        assert _keepalive_interval_s() == 300.0

    def test_max_idle_default(self, monkeypatch):
        monkeypatch.delenv("SERVICENOW_SESSION_KEEPALIVE_MAX_IDLE_S", raising=False)
        assert _keepalive_max_idle_s() == 6 * 3600.0

    def test_disabled_never_starts_thread(self, monkeypatch):
        monkeypatch.setenv("SERVICENOW_SESSION_KEEPALIVE", "off")
        mgr = _make_manager()
        mgr._session_keepalive.ensure_started()
        assert mgr._session_keepalive._thread is None


class TestTick:
    def test_ping_marks_valid_without_feeding_activity(self):
        """A 200 ping slides the TTL (from_keepalive=True) but must NOT
        refresh the activity horizon — else keepalive feeds itself forever."""
        mgr = _make_manager()
        mgr._browser_cookie_header = "JSESSIONID=abc"
        mgr._browser_cookie_expires_at = time.time() + 60
        mgr._browser_last_validated_at = time.time() - 3600  # stale → ping due
        keepalive = mgr._session_keepalive
        activity_before = time.time() - 100
        keepalive._last_activity_at = activity_before

        with patch.object(
            mgr, "_probe_browser_api_with_cookie", return_value=_probe_response(200)
        ) as probe:
            assert keepalive._tick() is True

        probe.assert_called_once()
        # TTL slid forward, validation stamped ...
        assert mgr._browser_last_validated_at > time.time() - 5
        assert mgr._browser_cookie_expires_at > time.time() + 60 * 25
        # ... but the activity horizon did not move.
        assert keepalive._last_activity_at == activity_before

    def test_real_request_success_feeds_activity_and_starts_thread(self):
        """The foreground path (default from_keepalive=False) refreshes the
        horizon and lazily starts the thread."""
        mgr = _make_manager()
        keepalive = mgr._session_keepalive
        assert keepalive._last_activity_at == 0.0
        with patch.object(keepalive, "ensure_started") as ensure:
            mgr._mark_browser_session_recently_valid()
        assert keepalive._last_activity_at > 0.0
        ensure.assert_called_once()

    def test_idle_horizon_stops_pings(self):
        """No real activity within max-idle → no probe (abandoned session
        must lapse server-side)."""
        mgr = _make_manager()
        mgr._browser_cookie_header = "JSESSIONID=abc"
        keepalive = mgr._session_keepalive
        keepalive._last_activity_at = time.time() - (7 * 3600)  # > 6 h default

        with patch.object(mgr, "_probe_browser_api_with_cookie") as probe:
            assert keepalive._tick() is True
        probe.assert_not_called()

    def test_recent_foreground_validation_skips_ping(self):
        mgr = _make_manager()
        mgr._browser_cookie_header = "JSESSIONID=abc"
        mgr._browser_last_validated_at = time.time() - 10  # just validated
        keepalive = mgr._session_keepalive
        keepalive._last_activity_at = time.time()

        with patch.object(mgr, "_probe_browser_api_with_cookie") as probe:
            assert keepalive._tick() is True
        probe.assert_not_called()

    def test_no_session_no_ping(self):
        mgr = _make_manager()
        assert mgr._browser_cookie_header is None
        keepalive = mgr._session_keepalive
        keepalive._last_activity_at = time.time()
        with patch.object(mgr, "_probe_browser_api_with_cookie") as probe:
            assert keepalive._tick() is True
        probe.assert_not_called()

    def test_rejected_ping_never_opens_browser(self):
        """THE invariant: a dead server session must not pop a browser/MFA
        window from a background thread. Rejection only logs; login,
        invalidation, and purge machinery stay untouched."""
        mgr = _make_manager()
        mgr._browser_cookie_header = "JSESSIONID=abc"
        mgr._browser_last_validated_at = time.time() - 3600
        keepalive = mgr._session_keepalive
        keepalive._last_activity_at = time.time()
        validated_before = mgr._browser_last_validated_at

        with (
            patch.object(mgr, "_probe_browser_api_with_cookie", return_value=_probe_response(401)),
            patch.object(mgr, "_login_with_browser") as login,
            patch.object(mgr, "invalidate_browser_session") as invalidate,
        ):
            assert keepalive._tick() is True

        login.assert_not_called()
        invalidate.assert_not_called()
        # Rejection must not stamp the session as freshly valid either.
        assert mgr._browser_last_validated_at == validated_before

    def test_probe_exception_is_swallowed(self):
        mgr = _make_manager()
        mgr._browser_cookie_header = "JSESSIONID=abc"
        mgr._browser_last_validated_at = None
        keepalive = mgr._session_keepalive
        keepalive._last_activity_at = time.time()
        with patch.object(mgr, "_probe_browser_api_with_cookie", side_effect=RuntimeError("boom")):
            assert keepalive._tick() is True

    def test_dead_manager_ends_thread(self):
        mgr = _make_manager()
        keepalive = mgr._session_keepalive
        keepalive._manager_ref = lambda: None  # simulate GC'd manager
        assert keepalive._tick() is False


class TestMfaDetectedDiagnostics:
    def test_mfa_detected_event_reports_remembered_cookie_state(self):
        """v1.18.45: the mfa_detected auth event carries whether a live
        mfa-remembered cookie existed at challenge time — distinguishes
        'cookie expired' from 'instance policy ignores remembered browsers'."""
        import pytest

        mgr = _make_manager()
        browser_cfg = BrowserAuthConfig(timeout_seconds=10, headless=False, session_ttl_minutes=30)
        cookies = [
            {"name": "JSESSIONID", "value": "abc", "domain": "example.service-now.com"},
            {
                "name": "glide_mfa_remembered_browser",
                "value": "remembered",
                "domain": "example.service-now.com",
                "expires": time.time() + 86400,
            },
        ]
        mock_page = MagicMock()
        mock_page.url = "https://example.service-now.com/validate_multifactor_auth_code.do"
        mock_page.is_closed.return_value = False
        mock_page.evaluate.return_value = None
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = cookies
        mock_pw = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_context
        mock_sync = MagicMock()
        mock_sync.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync.__exit__ = MagicMock(return_value=False)

        events = []
        original_auth_event = mgr._auth_event

        def _capture(event, **context):
            events.append((event, context))
            return original_auth_event(event, **context)

        with patch.dict(
            "sys.modules",
            {"playwright.sync_api": MagicMock(sync_playwright=MagicMock(return_value=mock_sync))},
        ):
            with patch("servicenow_mcp.auth.auth_manager.time.sleep"):
                with patch.object(mgr, "_auth_event", side_effect=_capture):
                    with pytest.raises(ValueError, match="MFA_REQUIRED"):
                        mgr._login_with_browser_sync(browser_cfg)

        mfa_events = [ctx for name, ctx in events if name == "login.headless.mfa_detected"]
        assert mfa_events, f"no mfa_detected event captured: {[n for n, _ in events]}"
        assert mfa_events[0]["mfa_remembered_cookie_valid"] is True
