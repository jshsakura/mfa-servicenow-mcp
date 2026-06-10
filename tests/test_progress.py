"""Tests for the progress-streaming layer (perceived-speed, v1.16).

Covers:
- emit_progress / use_progress_emitter contextvar plumbing (utils.progress)
- server-side whitelist gate (_should_stream_progress)
- download_app_sources emitting stage progress through the single _run_stage choke point

The point of this layer is PERCEIVED speed: long data tools must report progress
mid-call instead of going silent then dumping at the end. It must never change
behaviour when no client subscribed (no progress token) and must never let a
notification failure break the actual tool.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.source_tools import DownloadAppSourcesParams, download_app_sources
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig
from servicenow_mcp.utils.progress import emit_progress, use_progress_emitter


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def auth() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# emit_progress / use_progress_emitter
# ---------------------------------------------------------------------------


class TestEmitProgress:
    def test_noop_without_emitter(self):
        # No emitter installed for this call → silent no-op, never raises.
        assert emit_progress(1, 5, "hello") is None

    def test_invokes_installed_emitter(self):
        calls = []
        with use_progress_emitter(lambda p, t, m: calls.append((p, t, m))):
            emit_progress(2, 5, "stage")
        assert calls == [(2.0, 5.0, "stage")]

    def test_total_none_passthrough(self):
        # Indeterminate totals must stay None, not coerce to 0.0.
        calls = []
        with use_progress_emitter(lambda p, t, m: calls.append((p, t, m))):
            emit_progress(3, None, "indeterminate")
        assert calls == [(3.0, None, "indeterminate")]

    def test_swallows_emitter_error(self):
        def boom(p, t, m):
            raise RuntimeError("notification socket dead")

        # An emitter blowing up must never propagate into the tool body.
        with use_progress_emitter(boom):
            assert emit_progress(1, None, "x") is None

    def test_restores_previous_emitter(self):
        outer = []
        with use_progress_emitter(lambda p, t, m: outer.append(m)):
            inner = []
            with use_progress_emitter(lambda p, t, m: inner.append(m)):
                emit_progress(1, None, "inner")
            emit_progress(2, None, "outer")
        assert inner == ["inner"]
        assert outer == ["outer"]
        # After every context exits, back to a global no-op.
        assert emit_progress(9, None, "gone") is None


# ---------------------------------------------------------------------------
# Server whitelist gate
# ---------------------------------------------------------------------------


class TestShouldStreamProgress:
    def test_whitelisted_with_token(self):
        from servicenow_mcp.server import PROGRESS_STREAMING_TOOLS, _should_stream_progress

        assert "download_app_sources" in PROGRESS_STREAMING_TOOLS
        assert _should_stream_progress("download_app_sources", "tok-1") is True

    def test_whitelisted_without_token(self):
        # No progress token = client did not subscribe → keep the legacy on-loop path.
        from servicenow_mcp.server import _should_stream_progress

        assert _should_stream_progress("download_app_sources", None) is False

    def test_non_whitelisted_with_token(self):
        # Browser/auth and light tools stay on-loop even when a token is present.
        from servicenow_mcp.server import _should_stream_progress

        assert _should_stream_progress("sn_query", "tok-1") is False


# ---------------------------------------------------------------------------
# download_app_sources actually emits stage progress
# ---------------------------------------------------------------------------


class TestDownloadEmitsProgress:
    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_emits_stage_progress(
        self, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        mock_query_all.return_value = []
        mock_scan.return_value = {"x_app_request"}
        mock_schema.return_value = ({"x_app_request": 3}, [])

        calls = []
        with use_progress_emitter(lambda p, t, m: calls.append((p, m))):
            result = download_app_sources(
                config,
                auth,
                DownloadAppSourcesParams(
                    scope="x_app",
                    include_widget_sources=False,
                    include_schema=True,
                    output_dir=str(tmp_path),
                ),
            )

        assert result["success"] is True
        # Multiple stages (groups + global + schema) each report progress.
        assert calls, "expected stage progress to be emitted"
        assert len(calls) >= 2
        # Progress value is monotonically non-decreasing.
        progresses = [p for p, _ in calls]
        assert progresses == sorted(progresses)
        # The schema stage is identifiable in the stream.
        assert any("schema" in m for _, m in calls)

    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_no_emitter_does_not_break_download(
        self, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        mock_query_all.return_value = []
        mock_scan.return_value = set()
        mock_schema.return_value = ({}, [])

        # No emitter installed: download must behave exactly as before.
        result = download_app_sources(
            config,
            auth,
            DownloadAppSourcesParams(
                scope="x_app",
                include_widget_sources=False,
                include_schema=False,
                output_dir=str(tmp_path),
            ),
        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Server dispatch: the worker-thread → loop notification bridge
# ---------------------------------------------------------------------------


class _FakeSession:
    """Records progress notifications instead of writing them to a transport."""

    def __init__(self):
        self.notifications = []

    async def send_progress_notification(
        self, progress_token, progress, total=None, message=None, related_request_id=None
    ):
        self.notifications.append((progress_token, progress, total, message))


def _stub_with_channel(token, session):
    from servicenow_mcp.server import ServiceNowMCP

    class _Stub:
        def _progress_channel(self):
            return token, session

    _Stub._invoke_impl = ServiceNowMCP._invoke_impl
    return _Stub()


class TestInvokeImplBridge:
    def test_streams_notifications_for_whitelisted_tool(self):
        # A whitelisted DATA tool with a subscribed client runs in a worker
        # thread; emit_progress() from THAT thread must reach the session on the
        # event loop as real progress notifications.
        session = _FakeSession()
        stub = _stub_with_channel("tok-9", session)

        def impl(cfg, am, params):
            emit_progress(1, None, "downloading: portal")
            emit_progress(2, None, "downloading: schema")
            return {"success": True}

        result = asyncio.run(stub._invoke_impl("download_app_sources", impl, None, None, None))
        assert result == {"success": True}
        assert [n[3] for n in session.notifications] == [
            "downloading: portal",
            "downloading: schema",
        ]
        assert all(n[0] == "tok-9" for n in session.notifications)

    def test_non_whitelisted_runs_inline_without_notifications(self):
        # Non-whitelisted tools bypass the worker thread entirely (browser-auth
        # invariant) and never emit, even with a token + session present.
        session = _FakeSession()
        stub = _stub_with_channel("tok-9", session)

        def impl(cfg, am, params):
            emit_progress(1, None, "should be a no-op here")
            return {"ok": 1}

        result = asyncio.run(stub._invoke_impl("sn_query", impl, None, None, None))
        assert result == {"ok": 1}
        assert session.notifications == []

    def test_notification_failure_never_breaks_the_tool(self):
        # If the session blows up sending a notification, the tool still returns.
        class _BoomSession:
            async def send_progress_notification(self, *a, **k):
                raise RuntimeError("transport closed")

        stub = _stub_with_channel("tok-9", _BoomSession())

        def impl(cfg, am, params):
            emit_progress(1, None, "x")
            return {"survived": True}

        result = asyncio.run(stub._invoke_impl("download_app_sources", impl, None, None, None))
        assert result == {"survived": True}
