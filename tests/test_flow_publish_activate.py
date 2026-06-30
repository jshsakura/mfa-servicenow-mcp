"""Publish vs activate, captured 1:1 from the UI:
- publish (snapshot recompile) is editor-gated and NOT API-reachable → the tool
  returns UI guidance (manual_publish_required) instead of a broken call.
- activate/deactivate of an ALREADY-published flow = GET /flow/{id}/activate|
  deactivate (a plain toggle, no recompile) — these DO work via API.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    ManageFlowEditParams,
    _toggle_active,
    manage_flow_edit,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _ok():
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json.return_value = {"result": {}}
    return r


def test_publish_returns_ui_guidance():
    # Recompile is editor-gated — publish must not pretend to work; it returns
    # manual_publish_required + the Workflow Studio URL, with NO snapshot call.
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=_ok())
    r = manage_flow_edit(_cfg(), auth, ManageFlowEditParams(action="publish", flow_id="f1"))
    assert r["success"] is False
    assert r["manual_publish_required"] is True
    assert r["ui_url"].endswith("/now/wsd/flow-designer/f1")
    # no snapshot/publish HTTP call attempted
    assert not any("/snapshot" in str(c) for c in auth.make_request.call_args_list)


def test_toggle_active_uses_get_activate():
    calls = []

    def _mr(method, url, **kwargs):
        calls.append((method, url))
        return _ok()

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    r = _toggle_active(_cfg(), auth, "f1", "sc", activate=True)
    assert r == {"success": True, "action": "activate", "active": True}
    assert any(m == "GET" and u.endswith("/f1/activate") for m, u in calls)


def test_toggle_deactivate_uses_get_deactivate():
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=_ok())
    r = _toggle_active(_cfg(), auth, "f1", "sc", activate=False)
    assert r["action"] == "deactivate" and r["active"] is False
    assert auth.make_request.call_args_list[0].args == (
        "GET",
        "https://test.service-now.com/api/now/processflow/flow/f1/deactivate",
    )


def test_activate_action_resolves_scope_and_toggles():
    auth = MagicMock(spec=AuthManager)
    with (
        patch(
            "servicenow_mcp.tools.flow_edit_tools._table_lookup",
            return_value=[{"sys_id": "f1", "sys_scope": "scope1"}],
        ),
        patch(
            "servicenow_mcp.tools.flow_edit_tools._toggle_active",
            return_value={"success": True, "action": "activate", "active": True},
        ) as mock_toggle,
    ):
        r = manage_flow_edit(_cfg(), auth, ManageFlowEditParams(action="activate", flow_id="f1"))
    assert r["action"] == "activate"
    assert mock_toggle.call_args.kwargs["activate"] is True
