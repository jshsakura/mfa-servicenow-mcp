"""Native flow clone: POST /processflow/flow/{id}/copy?sysparm_transaction_scope=
with {name, scope} — the server remaps all instance sys_ids and returns the new
flow sys_id in result.data. We just mirror that one call.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import ManageFlowEditParams, _copy_flow, manage_flow_edit
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _copy_resp(new_id="newid", err=""):
    r = MagicMock()
    r.json.return_value = {"result": {"data": new_id, "errorMessage": err, "errorCode": 0}}
    r.raise_for_status = MagicMock()
    return r


def test_copy_flow_posts_to_copy_endpoint_with_scope():
    calls = []

    def _mr(method, url, **kwargs):
        calls.append((method, url, kwargs.get("params"), kwargs.get("json")))
        return _copy_resp("newflow1")

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    result = _copy_flow(_cfg(), auth, "src123", "My Copy", scope="sc1")
    assert result["success"] is True
    assert result["new_flow_id"] == "newflow1"
    post = [c for c in calls if c[0] == "POST"][0]
    assert post[1].endswith("/flow/src123/copy")
    assert post[2] == {"sysparm_transaction_scope": "sc1"}
    assert post[3] == {"name": "My Copy", "scope": "sc1"}


def test_copy_flow_resolves_scope_when_omitted():
    auth = MagicMock(spec=AuthManager)
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._table_lookup",
        return_value=[{"sys_id": "src123", "sys_scope": "resolved_scope"}],
    ):
        auth.make_request = MagicMock(return_value=_copy_resp("nid"))
        result = _copy_flow(_cfg(), auth, "src123", "C")
    assert result["success"] is True
    body = auth.make_request.call_args.kwargs["json"]
    assert body["scope"] == "resolved_scope"


def test_copy_flow_surfaces_error_message():
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=_copy_resp(new_id="", err="duplicate name"))
    result = _copy_flow(_cfg(), auth, "src", "C", scope="s")
    assert result["success"] is False
    assert "duplicate name" in result["error"]


def test_copy_action_dispatch_uses_value_as_name():
    auth = MagicMock(spec=AuthManager)
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._copy_flow",
        return_value={"success": True, "new_flow_id": "x"},
    ) as mock_copy:
        manage_flow_edit(
            _cfg(),
            auth,
            ManageFlowEditParams(action="copy", flow_id="src", value="Brand New Name"),
        )
    assert mock_copy.call_args.args[2] == "src"
    assert mock_copy.call_args.args[3] == "Brand New Name"
