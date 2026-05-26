"""Tests for manage_widget_dependency — unified CRUD + link/unlink for
Service Portal widget Angular providers and CSS/JS dependencies.

Live write tool: every path must return a meaningful dict (success message or
error+hint) so the LLM never flails.
"""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.widget_dependency_tools import (
    ManageWidgetDependencyParams,
    manage_widget_dependency,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

DEV = "portal_dev_tools"
PORTAL = "portal_tools"


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def _resp(json_body, status=200):
    r = MagicMock()
    r.status_code = status
    r.content = b"{}"
    r.json.return_value = json_body
    r.raise_for_status.return_value = None
    return r


def _p(**kw):
    return ManageWidgetDependencyParams(**kw)


# ---------------------------------------------------------------------------
# Validation — required fields per action; page is read-only
# ---------------------------------------------------------------------------


class TestValidation:
    @pytest.mark.parametrize(
        "kw",
        [
            dict(action="list", target="provider"),  # no filter
            dict(action="get", target="provider"),  # no record_id/widget_id
            dict(action="create", target="provider"),  # no name
            dict(action="update", target="provider", record_id="x"),  # no fields
            dict(action="delete", target="provider"),  # no record_id
            dict(action="link", target="provider", widget_id="w"),  # no record_id
            dict(action="unlink", target="provider", record_id="r"),  # no widget_id
            dict(action="link", target="page", widget_id="w", record_id="r"),  # page write
            dict(action="bogus", target="provider"),  # unknown action
            dict(action="list", target="bogus", widget_ids=["w"]),  # unknown target
        ],
    )
    def test_invalid_params_rejected(self, kw):
        with pytest.raises(ValueError):
            _p(**kw)

    @pytest.mark.parametrize(
        "kw",
        [
            dict(action="list", target="provider", widget_ids=["w"]),
            dict(action="list", target="page", page_id="index"),
            dict(action="get", target="provider", record_id="p1"),
            dict(action="create", target="dependency", name="d", module="m"),
            dict(action="update", target="provider", record_id="p1", name="n"),
            dict(action="delete", target="dependency", record_id="d1"),
            dict(action="link", target="provider", widget_id="w", record_id="p1"),
            dict(action="unlink", target="dependency", widget_id="w", record_id="d1"),
        ],
    )
    def test_valid_params_accepted(self, kw):
        assert _p(**kw).action == kw["action"]


# ---------------------------------------------------------------------------
# Read delegation — list/get route to the internal resolvers
# ---------------------------------------------------------------------------


class TestReadDelegation:
    def test_list_provider_delegates_to_provider_map(self):
        sentinel = {"success": True, "dependency_map": [], "_via": "provider_map"}
        with patch(
            f"servicenow_mcp.tools.{DEV}.get_provider_dependency_map", return_value=sentinel
        ) as m:
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="list", target="provider", widget_ids=["w1"])
            )
        assert out is sentinel
        assert m.call_args.args[2].widget_ids == ["w1"]

    def test_list_page_delegates_to_page_resolver(self):
        sentinel = {"success": True, "_via": "page"}
        with patch(
            f"servicenow_mcp.tools.{PORTAL}.resolve_page_dependencies", return_value=sentinel
        ) as m:
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="list", target="page", page_id="index")
            )
        assert out is sentinel
        assert m.call_args.args[2].page_id == "index"

    def test_include_source_delegates_to_widget_chain(self):
        sentinel = {"success": True, "_via": "chain"}
        with patch(
            f"servicenow_mcp.tools.{PORTAL}.resolve_widget_chain", return_value=sentinel
        ) as m:
            out = manage_widget_dependency(
                _config(),
                MagicMock(),
                _p(action="get", target="provider", widget_id="w1", include_source=True),
            )
        assert out is sentinel
        assert m.call_args.args[2].widget_id == "w1"

    def test_list_dependency_builds_css_js_map(self):
        # widgets, then m2m, then sp_dependency details
        side = [
            ([{"sys_id": "W1", "name": "Widget A"}], None),
            ([{"sys_id": "M1", "sp_widget": "W1", "sp_dependency": "D1"}], None),
            ([{"sys_id": "D1", "name": "Common CSS", "module": "modA"}], None),
        ]
        with patch(f"servicenow_mcp.tools.{DEV}._sn_get", side_effect=side):
            out = manage_widget_dependency(
                _config(), MagicMock(), _p(action="list", target="dependency", widget_ids=["W1"])
            )
        assert out["success"] is True
        assert out["dependency_map"][0]["dependencies"][0]["name"] == "Common CSS"


# ---------------------------------------------------------------------------
# Write: create / update / delete records
# ---------------------------------------------------------------------------


class TestRecordWrites:
    def test_create_provider_posts_and_hints_link(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({"result": {"sys_id": "P1"}})
        with patch(
            "servicenow_mcp.tools.sn_api._safe_json", return_value={"result": {"sys_id": "P1"}}
        ):
            out = manage_widget_dependency(
                _config(), auth, _p(action="create", target="provider", name="MyProvider")
            )
        assert out["success"] is True
        assert out["sys_id"] == "P1"
        assert "action=link" in out["next"]  # meaningful next-step guidance
        method, url = auth.make_request.call_args.args[:2]
        assert method == "POST" and url.endswith("/api/now/table/sp_angular_provider")

    def test_create_dependency_includes_module(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({"result": {"sys_id": "D1"}})
        with patch(
            "servicenow_mcp.tools.sn_api._safe_json", return_value={"result": {"sys_id": "D1"}}
        ):
            manage_widget_dependency(
                _config(), auth, _p(action="create", target="dependency", name="d", module="modX")
            )
        body = auth.make_request.call_args.kwargs["json"]
        assert body == {"name": "d", "module": "modX"}

    def test_create_dry_run_no_http(self):
        auth = MagicMock()
        out = manage_widget_dependency(
            _config(), auth, _p(action="create", target="provider", name="x", dry_run=True)
        )
        assert out["dry_run"] is True
        assert auth.make_request.call_count == 0

    def test_delete_calls_delete(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({}, status=204)
        out = manage_widget_dependency(
            _config(), auth, _p(action="delete", target="dependency", record_id="D1")
        )
        assert out["success"] is True
        method, url = auth.make_request.call_args.args[:2]
        assert method == "DELETE" and url.endswith("/sp_dependency/D1")

    def test_write_failure_returns_hint(self):
        auth = MagicMock()
        auth.make_request.side_effect = RuntimeError("boom")
        out = manage_widget_dependency(
            _config(), auth, _p(action="update", target="provider", record_id="P1", name="n")
        )
        assert out["success"] is False
        assert "boom" in out["error"]
        assert "hint" in out  # never a bare failure


# ---------------------------------------------------------------------------
# Link / unlink — m2m junction, idempotent
# ---------------------------------------------------------------------------


class TestLink:
    def test_link_creates_m2m_when_absent(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({"result": {"sys_id": "M1"}})
        # _resolve_widget_sys_id -> widget found; idempotency check -> none
        with (
            patch(
                f"servicenow_mcp.tools.{DEV}._sn_get",
                side_effect=[([{"sys_id": "W1"}], None), ([], None)],
            ),
            patch(
                "servicenow_mcp.tools.sn_api._safe_json", return_value={"result": {"sys_id": "M1"}}
            ),
        ):
            out = manage_widget_dependency(
                _config(), auth, _p(action="link", target="provider", widget_id="w", record_id="P1")
            )
        assert out["success"] is True
        body = auth.make_request.call_args.kwargs["json"]
        assert body == {"sp_widget": "W1", "sp_angular_provider": "P1"}

    def test_link_idempotent_noop(self):
        auth = MagicMock()
        with patch(
            f"servicenow_mcp.tools.{DEV}._sn_get",
            side_effect=[([{"sys_id": "W1"}], None), ([{"sys_id": "EXISTING"}], None)],
        ):
            out = manage_widget_dependency(
                _config(), auth, _p(action="link", target="provider", widget_id="w", record_id="P1")
            )
        assert out["success"] is True
        assert out["noop"] is True
        assert auth.make_request.call_count == 0  # no duplicate row created

    def test_link_widget_not_found_has_hint(self):
        auth = MagicMock()
        with patch(f"servicenow_mcp.tools.{DEV}._sn_get", side_effect=[([], None)]):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="link", target="dependency", widget_id="nope", record_id="D1"),
            )
        assert out["success"] is False
        assert "hint" in out
        assert auth.make_request.call_count == 0

    def test_unlink_deletes_matching_rows(self):
        auth = MagicMock()
        auth.make_request.return_value = _resp({}, status=204)
        with patch(
            f"servicenow_mcp.tools.{DEV}._sn_get",
            side_effect=[([{"sys_id": "W1"}], None), ([{"sys_id": "M1"}, {"sys_id": "M2"}], None)],
        ):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="unlink", target="provider", widget_id="w", record_id="P1"),
            )
        assert out["success"] is True
        assert out["deleted"] == ["M1", "M2"]
        assert auth.make_request.call_count == 2

    def test_unlink_noop_when_no_link(self):
        auth = MagicMock()
        with patch(
            f"servicenow_mcp.tools.{DEV}._sn_get",
            side_effect=[([{"sys_id": "W1"}], None), ([], None)],
        ):
            out = manage_widget_dependency(
                _config(),
                auth,
                _p(action="unlink", target="provider", widget_id="w", record_id="P1"),
            )
        assert out["success"] is True
        assert out["noop"] is True
        assert auth.make_request.call_count == 0
