"""One read entry point for the whole Workflow Studio set: a NAME or sys_id
resolves to its surface (flow/subflow/action/decision) and renders at screen
fidelity, so callers don't juggle three tools or guess the type.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    ManageFlowEditParams,
    _resolve_target,
    manage_flow_edit,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _lookup_stub(mapping):
    """mapping: table -> rows; query ignored (tests pass exact matches)."""

    def _fn(config, auth, table, query, fields="sys_id,name,type", limit=5):
        return mapping.get(table, [])

    return _fn


HEX = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"


def test_resolve_by_sysid_flow_vs_subflow():
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._table_lookup",
        side_effect=_lookup_stub({"sys_hub_flow": [{"sys_id": HEX, "name": "F", "type": "flow"}]}),
    ):
        assert _resolve_target(_cfg(), MagicMock(), HEX) == {
            "kind": "flow",
            "sys_id": HEX,
            "name": "F",
        }
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._table_lookup",
        side_effect=_lookup_stub(
            {"sys_hub_flow": [{"sys_id": HEX, "name": "S", "type": "subflow"}]}
        ),
    ):
        assert _resolve_target(_cfg(), MagicMock(), HEX)["kind"] == "subflow"


def test_resolve_by_sysid_action_then_decision():
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._table_lookup",
        side_effect=_lookup_stub(
            {"sys_hub_action_type_definition": [{"sys_id": HEX, "name": "A"}]}
        ),
    ):
        assert _resolve_target(_cfg(), MagicMock(), HEX)["kind"] == "action"
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._table_lookup",
        side_effect=_lookup_stub({"sys_decision": [{"sys_id": HEX, "name": "D"}]}),
    ):
        assert _resolve_target(_cfg(), MagicMock(), HEX)["kind"] == "decision"


def test_resolve_by_name_unique_and_ambiguous():
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._table_lookup",
        side_effect=_lookup_stub({"sys_hub_flow": [{"sys_id": "i1", "name": "X", "type": "flow"}]}),
    ):
        assert _resolve_target(_cfg(), MagicMock(), "X")["kind"] == "flow"
    # same name in two surfaces -> candidates
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._table_lookup",
        side_effect=_lookup_stub(
            {
                "sys_hub_flow": [{"sys_id": "i1", "name": "Dup", "type": "flow"}],
                "sys_hub_action_type_definition": [{"sys_id": "i2", "name": "Dup"}],
            }
        ),
    ):
        res = _resolve_target(_cfg(), MagicMock(), "Dup")
        assert len(res["candidates"]) == 2


def test_resolve_unknown_name():
    with patch("servicenow_mcp.tools.flow_edit_tools._table_lookup", side_effect=_lookup_stub({})):
        assert _resolve_target(_cfg(), MagicMock(), "nope")["kind"] == "unknown"


def test_read_routes_to_action_renderer():
    target = {"kind": "action", "sys_id": "a1", "name": "A"}
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._resolve_target", return_value=target),
        patch(
            "servicenow_mcp.tools.flow_edit_tools._try_processflow_action",
            return_value={"action": {"id": "a1", "name": "A"}, "steps": {"steps": []}},
        ),
    ):
        result = manage_flow_edit(
            _cfg(), MagicMock(spec=AuthManager), ManageFlowEditParams(action="read", flow_id="A")
        )
    assert result["success"] is True
    assert result["kind"] == "action"
    assert result["summary"]["name"] == "A"


def test_read_routes_to_flow_renderer():
    target = {"kind": "flow", "sys_id": "f1", "name": "F"}
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._resolve_target", return_value=target),
        patch(
            "servicenow_mcp.tools.flow_edit_tools._try_processflow_api",
            return_value={"result": {"id": "f1", "name": "F", "actionInstances": []}},
        ),
    ):
        result = manage_flow_edit(
            _cfg(), MagicMock(spec=AuthManager), ManageFlowEditParams(action="read", flow_id="F")
        )
    assert result["success"] is True and result["kind"] == "flow"
    assert "tree" in result["summary"]


def test_read_ambiguous_returns_candidates():
    target = {"candidates": [{"kind": "flow", "sys_id": "1"}, {"kind": "action", "sys_id": "2"}]}
    with patch("servicenow_mcp.tools.flow_edit_tools._resolve_target", return_value=target):
        result = manage_flow_edit(
            _cfg(), MagicMock(spec=AuthManager), ManageFlowEditParams(action="read", flow_id="Dup")
        )
    assert result["success"] is False
    assert len(result["candidates"]) == 2


def test_read_decision_is_detected_not_silently_failed():
    target = {"kind": "decision", "sys_id": "d1", "name": "Allow Access Policy"}
    with patch("servicenow_mcp.tools.flow_edit_tools._resolve_target", return_value=target):
        result = manage_flow_edit(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowEditParams(action="read", flow_id="Allow Access Policy"),
        )
    assert result["success"] is False
    assert result["kind"] == "decision"
    assert result["sys_id"] == "d1"
