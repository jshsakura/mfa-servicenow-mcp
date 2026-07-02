"""Batch-3 flow-edit hardening: dirty-checkout protection (un-saved staged
edits are never silently wiped by a re-checkout), clone leftover-uid detection,
no ghost version row on a failed save, and success=False on manage_workflow
error returns.
"""

import json
from unittest.mock import MagicMock, patch

import servicenow_mcp.tools.flow_edit_tools as fet
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    _CHECKOUT_META_KEY,
    ManageFlowEditParams,
    manage_flow_edit,
)
from servicenow_mcp.tools.workflow_tools import update_workflow
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig

FLOW_ID = "b" * 32


def _cfg():
    return ServerConfig(
        instance_url="https://dev.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def _flow_read_auth(flow_payload):
    def _mr(method, url, **kwargs):
        if method == "GET" and "/api/now/table/" in url:
            return _response({"result": [{"sys_id": FLOW_ID}]})
        if method == "GET":
            return _response({"result": flow_payload})
        return _response({"result": {}})

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    return auth


def _writable_flow():
    return {
        "id": FLOW_ID,
        "scope": "sc",
        "security": {"can_write": True},
        "actionInstances": [{"id": "act1", "inputs": [{"name": "table", "value": "incident"}]}],
        "triggerInstances": [{"id": "trg1", "inputs": [{"name": "condition", "value": "a=1"}]}],
    }


# ---------------------------------------------------------------------------
# Dirty-checkout protection
# ---------------------------------------------------------------------------


def test_leaf_edit_marks_checkout_dirty(tmp_path, monkeypatch):
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    cfg = _cfg()
    fet._save_checkout(cfg, FLOW_ID, _writable_flow())
    result = manage_flow_edit(
        cfg,
        MagicMock(spec=AuthManager),
        ManageFlowEditParams(
            action="set_action_input",
            flow_id=FLOW_ID,
            node_id="act1",
            input_name="table",
            value="problem",
        ),
    )
    assert result["success"] is True
    on_disk = fet._load_checkout(cfg, FLOW_ID)
    assert on_disk[_CHECKOUT_META_KEY]["dirty"] is True


def test_checkout_refuses_to_wipe_dirty_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    cfg = _cfg()
    dirty = _writable_flow()
    dirty[_CHECKOUT_META_KEY] = {"dirty": True}
    fet._save_checkout(cfg, FLOW_ID, dirty)
    auth = MagicMock(spec=AuthManager)
    result = manage_flow_edit(cfg, auth, ManageFlowEditParams(action="checkout", flow_id=FLOW_ID))
    assert result["success"] is False
    assert "un-saved staged edits" in result["error"]
    assert "force=true" in result["hint"]
    auth.make_request.assert_not_called()  # blocked before any network call


def test_checkout_force_overwrites_dirty_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    cfg = _cfg()
    dirty = _writable_flow()
    dirty[_CHECKOUT_META_KEY] = {"dirty": True}
    fet._save_checkout(cfg, FLOW_ID, dirty)
    auth = _flow_read_auth(_writable_flow())
    result = manage_flow_edit(
        cfg, auth, ManageFlowEditParams(action="checkout", flow_id=FLOW_ID, force=True)
    )
    assert result["success"] is True
    assert fet._load_checkout(cfg, FLOW_ID)[_CHECKOUT_META_KEY].get("dirty") is not True


def test_checkout_overwrites_clean_checkout_without_force(tmp_path, monkeypatch):
    # A clean checkout (no staged edits) carries nothing to lose — re-checkout
    # must stay friction-free.
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    cfg = _cfg()
    fet._save_checkout(cfg, FLOW_ID, _writable_flow())  # no dirty flag
    auth = _flow_read_auth(_writable_flow())
    result = manage_flow_edit(cfg, auth, ManageFlowEditParams(action="checkout", flow_id=FLOW_ID))
    assert result["success"] is True


# ---------------------------------------------------------------------------
# Clone leftover-uid detection
# ---------------------------------------------------------------------------


def test_add_branch_warns_when_template_uid_survives_outside_remap():
    checkout = {
        "id": FLOW_ID,
        "scope": "sc",
        "flowLogicInstances": [
            {
                "id": "if1",
                "uiUniqueIdentifier": "uid-template",
                "parent": "root",
                "order": 1,
                # A field the remap does NOT cover, embedding the node's own uid.
                "customRef": "points-at-uid-template",
                "inputs": [{"name": "condition", "value": "a=1"}],
            }
        ],
    }
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch("servicenow_mcp.tools.flow_edit_tools._save_checkout"),
    ):
        result = manage_flow_edit(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowEditParams(
                action="add_branch", flow_id=FLOW_ID, node_id="uid-template", value="b=2"
            ),
        )
    assert result["success"] is True
    assert any("uid-template" in w for w in result["warnings"])


def test_add_branch_clean_clone_has_no_warnings():
    checkout = {
        "id": FLOW_ID,
        "scope": "sc",
        "flowLogicInstances": [
            {
                "id": "if1",
                "uiUniqueIdentifier": "uid-template",
                "parent": "root",
                "order": 1,
                "inputs": [{"name": "condition", "value": "a=1"}],
            }
        ],
    }
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch("servicenow_mcp.tools.flow_edit_tools._save_checkout"),
    ):
        result = manage_flow_edit(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowEditParams(
                action="add_branch", flow_id=FLOW_ID, node_id="uid-template", value="b=2"
            ),
        )
    assert result["success"] is True
    assert "warnings" not in result


# ---------------------------------------------------------------------------
# No ghost version row on failed save
# ---------------------------------------------------------------------------


def test_failed_save_creates_no_version_row():
    def _mr(method, url, **kwargs):
        if method == "PUT":
            raise RuntimeError("save rejected")
        return _response({"result": {}})

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    checkout = {"id": FLOW_ID, "scope": "sc"}
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _cfg(),
            auth,
            ManageFlowEditParams(action="save", flow_id=FLOW_ID, verify=False),
        )
    assert result["success"] is False
    assert not any(
        "/versioning/" in c.args[1] for c in auth.make_request.call_args_list
    ), "version row must not be created when the PUT failed"


def test_successful_save_still_creates_version_row():
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=_response({"result": {}}))
    checkout = {"id": FLOW_ID, "scope": "sc"}
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _cfg(),
            auth,
            ManageFlowEditParams(action="save", flow_id=FLOW_ID, verify=False),
        )
    assert result["success"] is True
    assert any("/versioning/" in c.args[1] for c in auth.make_request.call_args_list)


# ---------------------------------------------------------------------------
# manage_workflow error returns carry success=False
# ---------------------------------------------------------------------------


def test_workflow_error_returns_are_machine_detectable():
    result = update_workflow(
        ServerConfig(
            instance_url="https://dev.service-now.com",
            auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
        ),
        MagicMock(spec=AuthManager),
        {"workflow_id": "", "name": "x"},
    )
    assert result["success"] is False
    assert "error" in result


def test_checkout_meta_round_trip_with_dirty_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    cfg = _cfg()
    data = {"id": FLOW_ID, _CHECKOUT_META_KEY: {"dirty": True, "sys_mod_count": "3"}}
    fet._save_checkout(cfg, FLOW_ID, data)
    assert json.loads(fet._checkout_path(cfg, FLOW_ID).read_text()) == data
    assert fet._existing_dirty_checkout(cfg, FLOW_ID) is not None
