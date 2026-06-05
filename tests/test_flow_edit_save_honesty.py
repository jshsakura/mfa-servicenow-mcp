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
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value={"flow": "x"}),
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


def test_save_with_publish_reports_live():
    # PUT (save) then POST (publish) both succeed.
    result = _save(True, MagicMock(side_effect=[_ok_response(), _ok_response()]))
    assert result["success"] is True
    assert result["published"] is True
    assert "note" in result and "recompiled" in result["note"]


def test_publish_failure_is_not_reported_as_success():
    # save PUT ok, publish POST raises -> edit is staged but NOT live.
    def _mr(method, url, **kwargs):
        if method == "POST":
            raise RuntimeError("publish 500")
        return _ok_response()

    result = _save(True, MagicMock(side_effect=_mr))
    assert result["success"] is False
    assert result["published"] is False
    assert "publish_error" in result
