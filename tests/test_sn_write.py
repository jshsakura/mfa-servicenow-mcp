"""Tests for sn_write — generic Table API CRUD with hard-coded denylist."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.sn_api import SN_WRITE_DENY_TABLES, SnWriteParams, sn_write
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _mock_response(json_body, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.content = b'{"x":1}'
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Denylist enforcement (hard-coded — no env override possible)
# ---------------------------------------------------------------------------


class TestDenylist:
    @pytest.mark.parametrize("table", sorted(SN_WRITE_DENY_TABLES))
    def test_blocked_tables_reject_create(self, table):
        cfg = _config()
        auth = MagicMock()
        out = sn_write(
            cfg,
            auth,
            SnWriteParams(table=table, action="create", fields={"name": "x"}),
        )
        assert out["success"] is False
        assert "blocked" in out["error"].lower()
        # No HTTP call should have been made
        assert auth.make_request.call_count == 0

    @pytest.mark.parametrize("table", sorted(SN_WRITE_DENY_TABLES))
    def test_blocked_tables_reject_update(self, table):
        cfg = _config()
        auth = MagicMock()
        out = sn_write(
            cfg,
            auth,
            SnWriteParams(table=table, action="update", sys_id="abc", fields={"name": "x"}),
        )
        assert out["success"] is False
        assert auth.make_request.call_count == 0

    def test_delete_blocked_on_arbitrary_sys_table(self):
        """Even tables NOT in the explicit denylist are blocked from delete if sys_*."""
        cfg = _config()
        auth = MagicMock()
        out = sn_write(cfg, auth, SnWriteParams(table="sys_choice", action="delete", sys_id="abc"))
        assert out["success"] is False
        assert "sys_*" in out["error"]
        assert auth.make_request.call_count == 0

    def test_denylist_is_frozen_set(self):
        """Defensive: denylist must be immutable to prevent runtime tampering."""
        assert isinstance(SN_WRITE_DENY_TABLES, frozenset)


# ---------------------------------------------------------------------------
# Required-field validation
# ---------------------------------------------------------------------------


class TestRequiredFields:
    def test_update_without_sys_id_fails(self):
        cfg = _config()
        out = sn_write(
            cfg,
            MagicMock(),
            SnWriteParams(table="incident", action="update", fields={"state": 2}),
        )
        assert out["success"] is False
        assert "sys_id" in out["error"]

    def test_delete_without_sys_id_fails(self):
        cfg = _config()
        out = sn_write(cfg, MagicMock(), SnWriteParams(table="incident", action="delete"))
        assert out["success"] is False
        assert "sys_id" in out["error"]

    def test_create_without_fields_fails(self):
        cfg = _config()
        out = sn_write(cfg, MagicMock(), SnWriteParams(table="incident", action="create"))
        assert out["success"] is False
        assert "fields" in out["error"]

    def test_update_without_fields_fails(self):
        cfg = _config()
        out = sn_write(
            cfg,
            MagicMock(),
            SnWriteParams(table="incident", action="update", sys_id="abc"),
        )
        assert out["success"] is False
        assert "fields" in out["error"]


# ---------------------------------------------------------------------------
# dry_run path — no network call
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_returns_preview(self):
        auth = MagicMock()
        out = sn_write(
            _config(),
            auth,
            SnWriteParams(
                table="incident",
                action="create",
                fields={"short_description": "test"},
                dry_run=True,
            ),
        )
        assert out["success"] is True
        assert out["dry_run"] is True
        assert out["fields"] == {"short_description": "test"}
        assert auth.make_request.call_count == 0


# ---------------------------------------------------------------------------
# HTTP execution paths
# ---------------------------------------------------------------------------


class TestExecution:
    def test_create_calls_post(self):
        auth = MagicMock()
        auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "new123", "state": "1"}}
        )
        cfg = _config()
        with patch(
            "servicenow_mcp.tools.sn_api._safe_json",
            return_value={"result": {"sys_id": "new123", "state": "1"}},
        ):
            out = sn_write(
                cfg,
                auth,
                SnWriteParams(table="incident", action="create", fields={"short_description": "x"}),
            )
        assert out["success"] is True
        assert out["sys_id"] == "new123"
        method, url = auth.make_request.call_args[0][:2]
        assert method == "POST"
        assert "/api/now/table/incident" in url

    def test_update_calls_patch(self):
        auth = MagicMock()
        auth.make_request.return_value = _mock_response({"result": {"sys_id": "abc", "state": "2"}})
        with patch(
            "servicenow_mcp.tools.sn_api._safe_json",
            return_value={"result": {"sys_id": "abc"}},
        ):
            out = sn_write(
                _config(),
                auth,
                SnWriteParams(table="incident", action="update", sys_id="abc", fields={"state": 2}),
            )
        assert out["success"] is True
        method, url = auth.make_request.call_args[0][:2]
        assert method == "PATCH"
        assert url.endswith("/incident/abc")

    def test_delete_calls_delete(self):
        auth = MagicMock()
        auth.make_request.return_value = _mock_response({}, status=204)
        out = sn_write(
            _config(),
            auth,
            SnWriteParams(table="incident", action="delete", sys_id="abc"),
        )
        assert out["success"] is True
        method, url = auth.make_request.call_args[0][:2]
        assert method == "DELETE"
        assert url.endswith("/incident/abc")

    def test_http_error_returns_failure(self):
        auth = MagicMock()
        auth.make_request.side_effect = RuntimeError("network down")
        out = sn_write(
            _config(),
            auth,
            SnWriteParams(table="incident", action="create", fields={"x": "y"}),
        )
        assert out["success"] is False
        assert "network down" in out["error"]
