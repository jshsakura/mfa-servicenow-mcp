"""Flow properties (Run As / Protection / Priority / active) are edited via the
"Flow properties" dialog and saved with PUT /flow?...&param_only_properties=true
— a different write than a structure save. set_property stages the change in the
checkout; save_properties persists it.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import ManageFlowEditParams, manage_flow_edit
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _ok():
    r = MagicMock()
    r.json.return_value = {"result": {}}
    r.raise_for_status = MagicMock()
    return r


def _run(params, checkout):
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=_ok())
    saved = {}
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch(
            "servicenow_mcp.tools.flow_edit_tools._save_checkout",
            side_effect=lambda fid, data: saved.update(data),
        ),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(_cfg(), auth, params)
    return result, saved, auth


def test_set_property_runas_staged():
    result, saved, _ = _run(
        ManageFlowEditParams(action="set_property", flow_id="f1", input_name="runAs", value="user"),
        {"id": "f1", "runAs": "system", "scope": "sc"},
    )
    assert result["success"] is True
    assert result["property"] == "runAs" and result["value"] == "user"
    assert saved["runAs"] == "user"


def test_set_property_active_coerces_bool():
    result, saved, _ = _run(
        ManageFlowEditParams(
            action="set_property", flow_id="f1", input_name="active", value="false"
        ),
        {"id": "f1", "active": True, "scope": "sc"},
    )
    assert saved["active"] is False


def test_set_property_rejects_unknown():
    result, _, _ = _run(
        ManageFlowEditParams(action="set_property", flow_id="f1", input_name="evil", value="x"),
        {"id": "f1", "scope": "sc"},
    )
    assert result["success"] is False
    assert "Unknown" in result["error"] or "unsupported" in result["error"]


def test_save_properties_uses_param_only_properties_and_scope():
    result, _, auth = _run(
        ManageFlowEditParams(action="save_properties", flow_id="f1"),
        {"id": "f1", "runAs": "user", "scope": "scope_sys_id"},
    )
    assert result["success"] is True
    # find the PUT call
    put = [c for c in auth.make_request.call_args_list if c.args[0] == "PUT"]
    assert put, "no PUT issued"
    params = put[0].kwargs["params"]
    assert params == {"sysparm_transaction_scope": "scope_sys_id", "param_only_properties": "true"}
    assert result["saved_properties"]["runAs"] == "user"


def test_save_properties_requires_scope():
    result, _, _ = _run(
        ManageFlowEditParams(action="save_properties", flow_id="f1"),
        {"id": "f1", "runAs": "user"},  # no scope
    )
    assert result["success"] is False
    assert "scope" in result["error"].lower()
