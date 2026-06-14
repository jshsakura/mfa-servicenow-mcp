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

from servicenow_mcp.tools.source_tools import (
    DownloadAppSourcesParams,
    DownloadSourcesParams,
    download_app_sources,
    download_server_sources,
)
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

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_server_sources_emits_per_type_progress(self, mock_query_all, config, auth, tmp_path):
        # download_server_sources streams a tick per finished source type, and the
        # per-type counter is monotonic within its single _download_source_types call.
        mock_query_all.return_value = []

        calls = []
        with use_progress_emitter(lambda p, t, m: calls.append((p, m))):
            result = download_server_sources(
                config,
                auth,
                DownloadSourcesParams(
                    scope="x_app",
                    families=["ui"],  # multiple source types -> multiple ticks
                    output_dir=str(tmp_path),
                ),
            )

        assert result["success"] is True
        assert calls, "expected per-type progress to be emitted"
        progresses = [p for p, _ in calls]
        assert progresses == sorted(progresses)
        assert any("downloaded:" in m for _, m in calls)

    @patch("servicenow_mcp.tools.portal_tools._sn_query_all")
    @patch("servicenow_mcp.tools.portal_tools.apply_scope_namespace")
    def test_portal_phase_emits_gated_when_nested(
        self, mock_scope, mock_qall, config, auth, tmp_path
    ):
        # Standalone download_portal_sources streams phase ticks; the emit_phases=False
        # path (how download_app_sources invokes it) stays silent so the app's
        # per-stage counter remains monotonic. Guards the v1.16.14 progress invariant.
        from servicenow_mcp.tools.portal_tools import (
            DownloadPortalSourcesParams,
            download_portal_sources,
        )

        mock_scope.side_effect = lambda c, a, p: (p, None)
        mock_qall.return_value = []
        # Nest output_dir one level: download_portal_sources writes _settings.json
        # to the scope root's PARENT, so a bare tmp_path would leak settings into
        # the shared pytest tmp base and pollute sibling tests' _find_settings_json.
        out = tmp_path / "portal_out"
        base = dict(
            scope="x_app",
            output_dir=str(out),
            include_linked_angular_providers=False,
            include_linked_script_includes=False,
        )

        on: list = []
        with use_progress_emitter(lambda p, t, m: on.append(m)):
            download_portal_sources(config, auth, DownloadPortalSourcesParams(**base))
        assert any("portal:" in m for m in on), "standalone should emit phase progress"

        off: list = []
        with use_progress_emitter(lambda p, t, m: off.append(m)):
            download_portal_sources(
                config, auth, DownloadPortalSourcesParams(**base), emit_phases=False
            )
        assert not any("portal:" in m for m in off), "nested call must not emit phases"

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


# ---------------------------------------------------------------------------
# audit_local_sources also streams progress (Phase C expansion)
# ---------------------------------------------------------------------------


class TestAuditEmitsProgress:
    def test_audit_local_sources_streams_phase_progress(self, config, auth, tmp_path):
        import json as _json

        from servicenow_mcp.tools.source_audit_tools import (
            AuditAppSourcesParams,
            audit_local_sources,
        )

        (tmp_path / "_manifest.json").write_text(
            _json.dumps({"scope": "x_app", "instance": "test"}), encoding="utf-8"
        )
        rec = tmp_path / "sys_script_include" / "UtilSI"
        rec.mkdir(parents=True)
        (rec / "_metadata.json").write_text(
            _json.dumps(
                {
                    "source_type": "script_include",
                    "table": "sys_script_include",
                    "sys_id": "s1",
                    "name": "UtilSI",
                }
            ),
            encoding="utf-8",
        )
        (rec / "script.js").write_text("var x = 1;", encoding="utf-8")

        calls = []
        with use_progress_emitter(lambda p, t, m: calls.append((p, m))):
            result = audit_local_sources(
                config, auth, AuditAppSourcesParams(source_root=str(tmp_path))
            )

        assert result.get("success") is not False
        assert len(calls) >= 3
        assert any("cross-reference" in m for _, m in calls)
