"""manage_flow_edit save must be honest about the design-time vs published gap.

save(publish=False) writes only the design-time model; get_detail and the
runtime read the compiled snapshot. Reporting a bare success there is the #1
"my edit vanished" trap. The save response must warn when not published, and
must NOT report success when the publish (recompile) step fails.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import ManageFlowEditParams, manage_flow_edit
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _cfg():
    # Flow editing is gated behind browser auth.
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _ok_response():
    resp = MagicMock()
    resp.json.return_value = {"result": {}}
    resp.raise_for_status = MagicMock()
    return resp


def _save(publish: bool, make_request):
    auth = MagicMock(spec=AuthManager)
    auth.make_request = make_request
    # Checkout payload carries the flow's app scope (sysparm_transaction_scope);
    # save/publish require it, mirroring the real processflow write contract.
    with (
        patch(
            "servicenow_mcp.tools.flow_edit_tools._load_checkout",
            return_value={"flow": "x", "scope": "scope_sys_id"},
        ),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path") as mock_path,
    ):
        mock_path.return_value.unlink = MagicMock()
        return manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="save", flow_id="f1", publish=publish)
        )


def test_save_without_publish_warns_design_time_only():
    result = _save(False, MagicMock(return_value=_ok_response()))
    assert result["success"] is True
    assert result["published"] is False
    assert "warning" in result
    assert "DESIGN-TIME ONLY" in result["warning"]
    assert "publish=true" in result["warning"]


def test_save_with_publish_saves_then_requires_confirmation():
    # save(publish=true) persists design-time, but the recompile is gated on
    # explicit user approval: without confirm=true it returns the publish plan
    # (confirmation_required) instead of silently recompiling the runtime.
    result = _save(True, MagicMock(return_value=_ok_response()))
    assert result["saved"] is True
    assert result["published"] is False
    assert result["confirmation_required"] is True
    assert "warning" in result and "user approval" in result["warning"]


def test_save_put_uses_scope_param_no_snapshot():
    # save PUT must use the scope param (not the old param_only_properties), and
    # NO curl /snapshot or legacy /publish is attempted.
    calls = []

    def _mr(method, url, **kwargs):
        calls.append((method, url, kwargs.get("params")))
        return _ok_response()

    result = _save(True, MagicMock(side_effect=_mr))
    assert result["saved"] is True
    put = [c for c in calls if c[0] == "PUT"]
    assert put and put[0][2] == {"sysparm_transaction_scope": "scope_sys_id"}
    assert not any("/snapshot" in c[1] or "/publish" in c[1] for c in calls)


def test_save_requires_scope():
    # A checkout payload missing 'scope' cannot be safely written.
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=_ok_response())
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value={"flow": "x"}),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="save", flow_id="f1", publish=True)
        )
    assert result["success"] is False
    assert "scope" in result["error"].lower()
