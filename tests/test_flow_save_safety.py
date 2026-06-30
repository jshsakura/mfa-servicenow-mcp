"""Safety nets on save: dry_run plans without writing; verify re-reads after the
write and fails loudly if the server silently reverted our values.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    ManageFlowEditParams,
    _verify_persisted,
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
    r.json.return_value = {"result": {}}
    r.raise_for_status = MagicMock()
    return r


_CHECKOUT = {
    "id": "f1",
    "scope": "sc",
    "actionInstances": [
        {"id": "a1", "inputs": [{"name": "table", "value": "incident"}]},
    ],
}


def test_verify_persisted_detects_revert():
    intended = {"actionInstances": [{"id": "a1", "inputs": [{"name": "x", "value": "new"}]}]}
    fresh_ok = {"actionInstances": [{"id": "a1", "inputs": [{"name": "x", "value": "new"}]}]}
    fresh_bad = {"actionInstances": [{"id": "a1", "inputs": [{"name": "x", "value": "OLD"}]}]}
    assert _verify_persisted(intended, fresh_ok)["verified"] is True
    bad = _verify_persisted(intended, fresh_bad)
    assert bad["verified"] is False
    assert bad["mismatches"][0] == {
        "node_id": "a1",
        "input": "x",
        "expected": "new",
        "actual": "OLD",
    }


def test_dry_run_does_not_write():
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=_ok())
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=_CHECKOUT),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _cfg(),
            auth,
            ManageFlowEditParams(action="save", flow_id="f1", publish=True, dry_run=True),
        )
    assert result["dry_run"] is True
    assert result["plan"]["then_publish"] is True
    auth.make_request.assert_not_called()  # nothing written


def test_save_verify_fail_marks_unsuccessful():
    # PUT/create_version succeed, but the verify re-read shows our value missing.
    def _mr(method, url, **kwargs):
        if method == "GET":  # the verify re-read
            r = MagicMock()
            r.json.return_value = {
                "result": {
                    "actionInstances": [
                        {"id": "a1", "inputs": [{"name": "table", "value": "WRONG"}]}
                    ]
                }
            }
            r.raise_for_status = MagicMock()
            return r
        return _ok()

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=_CHECKOUT),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="save", flow_id="f1", verify=True)
        )
    assert result["success"] is False
    assert result["verified"] is False
    assert result["mismatches"][0]["input"] == "table"


def test_save_verify_pass():
    def _mr(method, url, **kwargs):
        if method == "GET":
            r = MagicMock()
            r.json.return_value = {
                "result": {
                    "actionInstances": [
                        {"id": "a1", "inputs": [{"name": "table", "value": "incident"}]}
                    ]
                }
            }
            r.raise_for_status = MagicMock()
            return r
        return _ok()

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=_CHECKOUT),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="save", flow_id="f1", verify=True)
        )
    assert result["success"] is True
    assert result["verified"] is True
