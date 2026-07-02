"""Batch-2 flow-edit hardening: instance-scoped checkout files (dev/test clones
share sys_ids), staged-property verification on save_properties, structural
verify, Else-branch clone rejection, helper-level browser-auth defense, and
happy-path coverage for the previously untested leaf-edit actions.
"""

import json
from unittest.mock import MagicMock, patch

import servicenow_mcp.tools.flow_edit_tools as fet
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    _CHECKOUT_META_KEY,
    ManageFlowEditParams,
    _checkout_path,
    _copy_flow,
    _toggle_active,
    _verify_persisted,
    manage_flow_edit,
)
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    ServerConfig,
)

FLOW_ID = "a" * 32


def _cfg(url="https://dev.service-now.com"):
    return ServerConfig(
        instance_url=url,
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _basic_cfg():
    return ServerConfig(
        instance_url="https://dev.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def _response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Instance-scoped checkout files
# ---------------------------------------------------------------------------


def test_checkout_path_is_scoped_per_instance():
    dev = _checkout_path(_cfg("https://dev.service-now.com"), FLOW_ID)
    test = _checkout_path(_cfg("https://test.service-now.com"), FLOW_ID)
    assert dev != test
    assert "dev.service-now.com" in dev.name


def test_save_on_other_instance_does_not_see_foreign_checkout(tmp_path, monkeypatch):
    # A checkout taken on dev must be invisible to a test-instance session even
    # for the SAME sys_id (dev/test clones share sys_ids).
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    fet._save_checkout(_cfg("https://dev.service-now.com"), FLOW_ID, {"scope": "sc"})
    auth = MagicMock(spec=AuthManager)
    result = manage_flow_edit(
        _cfg("https://test.service-now.com"),
        auth,
        ManageFlowEditParams(action="save", flow_id=FLOW_ID),
    )
    assert result["success"] is False
    assert "No checkout" in result["error"]
    auth.make_request.assert_not_called()


def test_discard_removes_only_this_instance_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    dev_cfg = _cfg("https://dev.service-now.com")
    test_cfg = _cfg("https://test.service-now.com")
    fet._save_checkout(dev_cfg, FLOW_ID, {"scope": "sc"})
    fet._save_checkout(test_cfg, FLOW_ID, {"scope": "sc"})
    result = manage_flow_edit(
        dev_cfg,
        MagicMock(spec=AuthManager),
        ManageFlowEditParams(action="discard", flow_id=FLOW_ID),
    )
    assert result["success"] is True
    assert not _checkout_path(dev_cfg, FLOW_ID).exists()
    assert _checkout_path(test_cfg, FLOW_ID).exists()


# ---------------------------------------------------------------------------
# save_properties: staged-property verification
# ---------------------------------------------------------------------------

_BASELINE = {"sys_updated_on": "2026-07-01 00:00:00", "sys_mod_count": "5"}


def _props_auth(fresh_flow):
    def _mr(method, url, **kwargs):
        if method == "GET" and "/api/now/table/" in url:
            return _response({"result": [{"sys_id": FLOW_ID, **_BASELINE, "sys_updated_by": "me"}]})
        if method == "GET":
            return _response({"result": fresh_flow})
        return _response({"result": {}})

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    return auth


def _run_save_properties(fresh_flow, staged):
    checkout = {
        "id": FLOW_ID,
        "scope": "sc",
        "runAs": staged.get("runAs", "user"),
        _CHECKOUT_META_KEY: {**_BASELINE, "staged_properties": staged},
    }
    auth = _props_auth(fresh_flow)
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path") as mock_path,
    ):
        mock_path.return_value.unlink = MagicMock()
        result = manage_flow_edit(
            _cfg(), auth, ManageFlowEditParams(action="save_properties", flow_id=FLOW_ID)
        )
    return result, mock_path.return_value.unlink


def test_save_properties_verify_failure_preserves_checkout():
    result, unlink = _run_save_properties(
        fresh_flow={"id": FLOW_ID, "runAs": "system"}, staged={"runAs": "user"}
    )
    assert result["success"] is False
    assert result["verified"] is False
    assert result["mismatches"][0] == {
        "property": "runAs",
        "expected": "user",
        "actual": "system",
    }
    unlink.assert_not_called()


def test_save_properties_verify_pass():
    result, _ = _run_save_properties(
        fresh_flow={"id": FLOW_ID, "runAs": "user"}, staged={"runAs": "user"}
    )
    assert result["success"] is True
    assert result["verified"] is True


def test_set_property_records_staged_property_in_meta():
    checkout = {"id": FLOW_ID, "scope": "sc", _CHECKOUT_META_KEY: dict(_BASELINE)}
    saved = {}
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch(
            "servicenow_mcp.tools.flow_edit_tools._save_checkout",
            side_effect=lambda cfg, fid, data: saved.update(data),
        ),
    ):
        result = manage_flow_edit(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowEditParams(
                action="set_property", flow_id=FLOW_ID, input_name="runAs", value="user"
            ),
        )
    assert result["success"] is True
    assert saved[_CHECKOUT_META_KEY]["staged_properties"] == {"runAs": "user"}


# ---------------------------------------------------------------------------
# Structural verify + Else-branch clone rejection
# ---------------------------------------------------------------------------


def test_verify_persisted_detects_dropped_structural_node():
    intended = {
        "flowLogicInstances": [
            {"id": "l1", "inputs": []},
            {"id": "l2-new", "inputs": []},
        ]
    }
    fresh = {"flowLogicInstances": [{"id": "l1", "inputs": []}]}
    result = _verify_persisted(intended, fresh)
    assert result["verified"] is False
    assert any("structural edit reverted" in str(m.get("actual")) for m in result["mismatches"])


def test_add_branch_rejects_template_without_condition_input():
    checkout = {
        "id": FLOW_ID,
        "scope": "sc",
        "flowLogicInstances": [
            {
                "id": "else1",
                "uiUniqueIdentifier": "u-else",
                "parent": "root",
                "order": 1,
                "inputs": [{"name": "other", "value": "x"}],  # no 'condition'
            }
        ],
    }
    with patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout):
        result = manage_flow_edit(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowEditParams(
                action="add_branch", flow_id=FLOW_ID, node_id="u-else", value="a=1"
            ),
        )
    assert result["success"] is False
    assert "condition" in result["error"]


# ---------------------------------------------------------------------------
# Helper-level browser-auth defense (session-only processflow API)
# ---------------------------------------------------------------------------


def test_copy_flow_rejects_basic_auth_directly():
    auth = MagicMock(spec=AuthManager)
    result = _copy_flow(_basic_cfg(), auth, FLOW_ID, "Copy of flow")
    assert result["success"] is False
    assert "browser auth" in result["error"]
    auth.make_request.assert_not_called()


def test_toggle_active_rejects_basic_auth_directly():
    auth = MagicMock(spec=AuthManager)
    result = _toggle_active(_basic_cfg(), auth, FLOW_ID, "sc", activate=True)
    assert result["success"] is False
    assert "browser auth" in result["error"]
    auth.make_request.assert_not_called()


# ---------------------------------------------------------------------------
# Previously untested leaf-edit actions (happy paths)
# ---------------------------------------------------------------------------


def _leaf_checkout():
    return {
        "id": FLOW_ID,
        "scope": "sc",
        "actionInstances": [{"id": "act1", "inputs": [{"name": "table", "value": "incident"}]}],
        "triggerInstances": [{"id": "trg1", "inputs": [{"name": "condition", "value": "state=1"}]}],
    }


def test_set_action_input_updates_checkout():
    saved = {}
    with (
        patch(
            "servicenow_mcp.tools.flow_edit_tools._load_checkout",
            return_value=_leaf_checkout(),
        ),
        patch(
            "servicenow_mcp.tools.flow_edit_tools._save_checkout",
            side_effect=lambda cfg, fid, data: saved.update(data),
        ),
    ):
        result = manage_flow_edit(
            _cfg(),
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
    assert saved["actionInstances"][0]["inputs"][0]["value"] == "problem"


def test_set_trigger_condition_updates_checkout():
    saved = {}
    with (
        patch(
            "servicenow_mcp.tools.flow_edit_tools._load_checkout",
            return_value=_leaf_checkout(),
        ),
        patch(
            "servicenow_mcp.tools.flow_edit_tools._save_checkout",
            side_effect=lambda cfg, fid, data: saved.update(data),
        ),
    ):
        result = manage_flow_edit(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowEditParams(action="set_trigger_condition", flow_id=FLOW_ID, value="state=6"),
        )
    assert result["success"] is True
    assert saved["triggerInstances"][0]["inputs"][0]["value"] == "state=6"


def test_status_reads_local_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    cfg = _cfg()
    fet._save_checkout(cfg, FLOW_ID, _leaf_checkout())
    result = manage_flow_edit(
        cfg, MagicMock(spec=AuthManager), ManageFlowEditParams(action="status", flow_id=FLOW_ID)
    )
    assert result["success"] is True
    assert "summary" in result


def test_read_action_is_classified_read_only():
    # read_action never mutates; forcing it through the confirm gate was an
    # inconsistency (all other manage_flow_designer reads are exempt).
    from servicenow_mcp.policies.write_guards import _is_read_only

    assert _is_read_only("manage_flow_designer", {"action": "read_action"}) is True
    assert _is_read_only("manage_flow_designer", {"action": "save"}) is False


def test_checkout_meta_survives_file_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    cfg = _cfg()
    data = {"id": FLOW_ID, _CHECKOUT_META_KEY: {"sys_mod_count": "5"}}
    fet._save_checkout(cfg, FLOW_ID, data)
    loaded = fet._load_checkout(cfg, FLOW_ID)
    assert loaded[_CHECKOUT_META_KEY]["sys_mod_count"] == "5"
    assert json.loads(_checkout_path(cfg, FLOW_ID).read_text()) == data
