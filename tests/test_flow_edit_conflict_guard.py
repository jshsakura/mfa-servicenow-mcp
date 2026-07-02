"""Lost-update guard on the checkout -> save window, and the retry-material
invariants around it: a stale checkout must never silently overwrite a newer
remote flow, a failed verify must keep the checkout on disk, and the checkout
bookkeeping key must never be PUT back to the server.
"""

import json
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    _CHECKOUT_META_KEY,
    ManageFlowEditParams,
    manage_flow_edit,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig

FLOW_ID = "f" * 32


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _baseline_row(updated_on="2026-07-01 00:00:00", mod_count="5", updated_by="alice"):
    return {
        "sys_id": FLOW_ID,
        "sys_updated_on": updated_on,
        "sys_mod_count": mod_count,
        "sys_updated_by": updated_by,
    }


def _checkout_data(baseline=None):
    data = {
        "id": FLOW_ID,
        "scope": "scope_sys_id",
        "actionInstances": [{"id": "a1", "inputs": [{"name": "table", "value": "incident"}]}],
    }
    if baseline is not None:
        data[_CHECKOUT_META_KEY] = baseline
    return data


def _auth(table_row, flow_read=None):
    """make_request router: Table API GET -> [table_row]; processflow GET ->
    flow_read; writes -> generic ok."""

    def _mr(method, url, **kwargs):
        if method == "GET" and "/api/now/table/" in url:
            return _response({"result": [table_row] if table_row else []})
        if method == "GET":
            return _response({"result": flow_read or {}})
        return _response({"result": {}})

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    return auth


def _save(auth, checkout, **param_overrides):
    kwargs = {"action": "save", "flow_id": FLOW_ID, "verify": False}
    kwargs.update(param_overrides)
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path") as mock_path,
    ):
        mock_path.return_value.unlink = MagicMock()
        result = manage_flow_edit(_cfg(), auth, ManageFlowEditParams(**kwargs))
    return result, mock_path.return_value.unlink


def test_save_blocked_when_remote_changed_after_checkout():
    baseline = {"sys_updated_on": "2026-07-01 00:00:00", "sys_mod_count": "5"}
    auth = _auth(_baseline_row(updated_on="2026-07-02 09:00:00", mod_count="7"))
    result, unlink = _save(auth, _checkout_data(baseline))
    assert result["success"] is False
    assert "nothing was overwritten" in result["error"]
    assert result["checkout_preserved"] is True
    assert result["remote_change"]["remote_now"]["sys_updated_by"] == "alice"
    unlink.assert_not_called()
    assert not any(c.args[0] == "PUT" for c in auth.make_request.call_args_list)


def test_save_proceeds_when_remote_unchanged():
    baseline = {"sys_updated_on": "2026-07-01 00:00:00", "sys_mod_count": "5"}
    auth = _auth(_baseline_row())
    result, _ = _save(auth, _checkout_data(baseline))
    assert result["success"] is True
    assert any(c.args[0] == "PUT" for c in auth.make_request.call_args_list)


def test_save_force_overrides_conflict():
    baseline = {"sys_updated_on": "2026-07-01 00:00:00", "sys_mod_count": "5"}
    auth = _auth(_baseline_row(updated_on="2026-07-02 09:00:00", mod_count="7"))
    result, _ = _save(auth, _checkout_data(baseline), force=True)
    assert result["success"] is True
    assert any(c.args[0] == "PUT" for c in auth.make_request.call_args_list)


def test_save_fails_open_without_baseline():
    # Checkouts taken before this guard existed have no baseline — they must
    # still save (fail-open), not get stuck.
    auth = _auth(_baseline_row(updated_on="2026-07-02 09:00:00"))
    result, _ = _save(auth, _checkout_data(baseline=None))
    assert result["success"] is True


def test_save_strips_checkout_meta_from_put_payload():
    baseline = {"sys_updated_on": "2026-07-01 00:00:00", "sys_mod_count": "5"}
    auth = _auth(_baseline_row())
    _save(auth, _checkout_data(baseline))
    puts = [c for c in auth.make_request.call_args_list if c.args[0] == "PUT"]
    assert puts and _CHECKOUT_META_KEY not in puts[0].kwargs["json"]


def test_dry_run_reports_conflict_without_writing():
    baseline = {"sys_updated_on": "2026-07-01 00:00:00", "sys_mod_count": "5"}
    auth = _auth(_baseline_row(updated_on="2026-07-02 09:00:00", mod_count="7"))
    result, _ = _save(auth, _checkout_data(baseline), dry_run=True)
    assert result["dry_run"] is True
    assert result["plan"]["remote_changed_since_checkout"] is True
    assert not any(c.args[0] in ("PUT", "POST") for c in auth.make_request.call_args_list)


def test_verify_failure_preserves_checkout():
    # The verify re-read shows the server reverted our value: the checkout must
    # stay on disk as retry material.
    baseline = {"sys_updated_on": "2026-07-01 00:00:00", "sys_mod_count": "5"}
    reverted = {"actionInstances": [{"id": "a1", "inputs": [{"name": "table", "value": "WRONG"}]}]}
    auth = _auth(_baseline_row(), flow_read=reverted)
    result, unlink = _save(auth, _checkout_data(baseline), verify=True)
    assert result["success"] is False
    assert result["verified"] is False
    assert result["checkout_preserved"] is True
    unlink.assert_not_called()


def test_save_properties_blocked_on_conflict():
    baseline = {"sys_updated_on": "2026-07-01 00:00:00", "sys_mod_count": "5"}
    auth = _auth(_baseline_row(updated_on="2026-07-02 09:00:00", mod_count="7"))
    with (
        patch(
            "servicenow_mcp.tools.flow_edit_tools._load_checkout",
            return_value=_checkout_data(baseline),
        ),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _cfg(),
            auth,
            ManageFlowEditParams(action="save_properties", flow_id=FLOW_ID),
        )
    assert result["success"] is False
    assert result["checkout_preserved"] is True
    assert not any(c.args[0] == "PUT" for c in auth.make_request.call_args_list)


def test_checkout_captures_baseline_in_checkout_file():
    flow_read = {
        "id": FLOW_ID,
        "scope": "scope_sys_id",
        "security": {"can_write": True},
        "actionInstances": [],
    }
    auth = _auth(_baseline_row(), flow_read=flow_read)
    saved = {}
    with patch(
        "servicenow_mcp.tools.flow_edit_tools._save_checkout",
        side_effect=lambda cfg, fid, data: saved.update(data),
    ):
        result = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="checkout", flow_id=FLOW_ID)
        )
    assert result["success"] is True
    assert saved[_CHECKOUT_META_KEY]["sys_updated_on"] == "2026-07-01 00:00:00"
    assert saved[_CHECKOUT_META_KEY]["sys_mod_count"] == "5"
    # The meta must survive a JSON round-trip (it is stored in the file).
    assert json.loads(json.dumps(saved))[_CHECKOUT_META_KEY]["sys_updated_by"] == "alice"


def test_checkout_locked_flow_returns_diagnostics():
    flow_read = {"id": FLOW_ID, "security": {"can_write": False}}
    auth = _auth(_baseline_row(updated_by="bob"), flow_read=flow_read)
    result = manage_flow_edit(
        _cfg(), auth, ManageFlowEditParams(action="checkout", flow_id=FLOW_ID)
    )
    assert result["success"] is False
    assert "can_write=false" in result["error"]
    assert "Workflow Studio" in result["hint"]
    assert result["last_remote_update"]["sys_updated_by"] == "bob"


def test_unsafe_flow_id_rejected_before_any_call():
    auth = MagicMock(spec=AuthManager)
    result = manage_flow_edit(
        _cfg(), auth, ManageFlowEditParams(action="discard", flow_id="../../etc/passwd")
    )
    assert result["success"] is False
    assert "plain sys_id" in result["error"]
    auth.make_request.assert_not_called()


def test_set_branch_condition_errors_when_condition_input_missing():
    # An Else branch has no 'condition' input — this must be an error, not a
    # silently-ignored success.
    checkout = {
        "id": FLOW_ID,
        "scope": "scope_sys_id",
        "flowLogicInstances": [{"id": "logic1", "inputs": [{"name": "other", "value": "x"}]}],
    }
    auth = MagicMock(spec=AuthManager)
    with patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout):
        result = manage_flow_edit(
            _cfg(),
            auth,
            ManageFlowEditParams(
                action="set_branch_condition", flow_id=FLOW_ID, node_id="logic1", value="a=1"
            ),
        )
    assert result["success"] is False
    assert "condition input not found" in result["error"]
