"""Custom Action types (Action Designer) use a different model than flows —
input/output variables + ordered steps (Script step etc.) from a separate
step_instances payload. The reader must render them at screen fidelity,
including the full Script body.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    ManageFlowEditParams,
    _compact_action_summary,
    manage_flow_edit,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig

_ACTION = {
    "id": "act1",
    "name": "My Resolve Action",
    "internal_name": "my_resolve",
    "state": "published",
    "active": True,
    "scope": "scope1",
    "scopename": "x_myapp",
    "inputs": [{"name": "service_close", "label": "service_close", "type": "reference"}],
    "outputs": [
        {"name": "success", "label": "success", "type": "string"},
        {"name": "first_approver", "label": "first_approver", "type": "reference"},
    ],
}
_STEPS = {
    "steps": [
        {
            "step_id": "s1",
            "label": "Script step",
            "step_type_name": "Script",
            "step_type_category": "utilities",
            "order": 1,
            "error_handling_type": "EVAL_ERRORS",
            "inputs": [{"name": "script", "value": "var x = 1;\nreturn x;"}],
            "outputs": [{"name": "__step_status__", "type": "object"}],
        }
    ]
}


def test_action_summary_variables_and_script():
    a = _compact_action_summary(_ACTION, _STEPS)
    assert a["kind"] == "action"
    assert a["name"] == "My Resolve Action"
    assert a["scope_name"] == "x_myapp"
    assert [v["name"] for v in a["input_variables"]] == ["service_close"]
    assert {v["name"] for v in a["output_variables"]} == {"success", "first_approver"}
    step = a["steps"][0]
    assert step["label"] == "Script step"
    assert step["step_type"] == "Script"
    assert step["error_handling"] == "EVAL_ERRORS"
    script_in = [i for i in step["inputs"] if i["name"] == "script"][0]
    assert script_in["is_script"] is True
    assert script_in["line_count"] == 2
    assert script_in["value"] == "var x = 1;\nreturn x;"  # full body kept


def test_action_summary_handles_missing_steps():
    a = _compact_action_summary(_ACTION, None)
    assert a["steps"] == []


def test_read_action_dispatch():
    cfg = ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )
    auth = MagicMock(spec=AuthManager)
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._try_processflow_action",
        return_value={"action": _ACTION, "steps": _STEPS},
    ):
        result = manage_flow_edit(
            cfg, auth, ManageFlowEditParams(action="read_action", flow_id="act1")
        )
    assert result["success"] is True
    assert result["summary"]["name"] == "My Resolve Action"
    assert result["summary"]["steps"][0]["step_type"] == "Script"


def test_read_action_surfaces_fetch_error():
    cfg = ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )
    auth = MagicMock(spec=AuthManager)
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._try_processflow_action",
        return_value={"_error": "not found"},
    ):
        result = manage_flow_edit(
            cfg, auth, ManageFlowEditParams(action="read_action", flow_id="bad")
        )
    assert result["success"] is False
    assert "not found" in result["error"]
