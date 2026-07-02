"""add_branch stages a NEW sibling branch by cloning an existing branch subtree.

The clone mints fresh ids/uiUniqueIdentifiers, re-parents descendants, remaps
data pills that point into the subtree, inherits flowBlockId/definitionId from
the template (so the compiled flow stays valid), and swaps only the condition.
It is staged into the checkout — save (then UI publish) is what persists it.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import (
    ManageFlowEditParams,
    _clone_branch,
    manage_flow_edit,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _flow():
    """IF branch (uid=IF1) with a child Update action (uid=ACT1) whose input
    references both a node in the subtree (ACT1) and one outside it (trigger)."""
    return {
        "id": "f1",
        "scope": "sc",
        "flowLogicInstances": [
            {
                "id": "id_if1",
                "uiUniqueIdentifier": "IF1",
                "parent": "",
                "order": 5,
                "flowBlockId": "blk1",
                "definitionId": "def_if",
                "connectedTo": "",
                "inputs": [
                    {"name": "condition", "value": "mp_gap_lc<0"},
                    {"name": "condition_name", "value": "MP less than 0"},
                ],
            }
        ],
        "actionInstances": [
            {
                "id": "id_act1",
                "uiUniqueIdentifier": "ACT1",
                "parent": "IF1",
                "order": 6,
                "inputs": [
                    {"name": "state", "value": "10"},
                    {"name": "record", "value": "{{trigger.current}} {{ACT1.self}}"},
                ],
            }
        ],
        "subFlowInstances": [],
    }


def test_clone_branch_creates_sibling_with_new_condition():
    flow = _flow()
    res, err = _clone_branch(flow, "IF1", "mp_gap_lc=0", "MP equals 0")
    assert err is None
    assert res["cloned_node_count"] == 2

    new_uid = res["new_branch_uid"]
    logic = next(n for n in flow["flowLogicInstances"] if n["uiUniqueIdentifier"] == new_uid)
    # Sibling of the template (same parent), fresh ids, block/def inherited.
    assert logic["parent"] == ""
    assert logic["id"] != "id_if1"
    assert logic["flowBlockId"] == "blk1"
    assert logic["definitionId"] == "def_if"
    cond = {i["name"]: i["value"] for i in logic["inputs"]}
    assert cond["condition"] == "mp_gap_lc=0"
    assert cond["condition_name"] == "MP equals 0"
    assert logic["name"] == "If: MP equals 0"
    assert logic["order"] > 6  # placed after the template subtree


def test_clone_branch_reparents_child_and_remaps_only_internal_pills():
    flow = _flow()
    res, _ = _clone_branch(flow, "IF1", "x=0", "L")
    new_uid, child_uid = res["new_branch_uid"], res["child_uids"][0]

    act = next(n for n in flow["actionInstances"] if n["uiUniqueIdentifier"] == child_uid)
    assert act["parent"] == new_uid  # re-parented to the clone
    assert act["id"] != "id_act1"
    rec = {i["name"]: i["value"] for i in act["inputs"]}["record"]
    # In-subtree pill (ACT1) remapped; out-of-subtree pill (trigger) untouched.
    assert child_uid in rec
    assert "{{trigger.current}}" in rec
    assert "ACT1" not in rec

    # Original template + child are left intact.
    assert flow["flowLogicInstances"][0]["uiUniqueIdentifier"] == "IF1"
    assert flow["actionInstances"][0]["uiUniqueIdentifier"] == "ACT1"


def test_clone_branch_rejects_non_logic_template():
    _, err = _clone_branch(_flow(), "ACT1", "x=1", "L")
    assert err and "LOGIC" in err


def test_clone_branch_rejects_unknown_template():
    _, err = _clone_branch(_flow(), "NOPE", "x=1", "L")
    assert err and "not found" in err


def test_add_branch_stages_into_checkout_and_encodes_condition():
    """Structured condition rows are encoded, and the new branch is written back
    to the checkout file (staged, not pushed)."""
    saved = {}

    def _fake_save(config, flow_id, data):
        saved["flow_id"] = flow_id
        saved["data"] = data

    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=_flow()),
        patch("servicenow_mcp.tools.flow_edit_tools._save_checkout", side_effect=_fake_save),
    ):
        result = manage_flow_edit(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowEditParams(
                action="add_branch",
                flow_id="f1",
                node_id="IF1",
                value='[{"field": "mp_gap_lc", "operator": "is", "value": "0"}]',
                condition_label="MP equals 0",
            ),
        )

    assert result["success"] is True
    assert result["cloned_node_count"] == 2
    assert "mp_gap_lc" in result["condition"]
    # New branch persisted to the checkout for a later save.
    assert len(saved["data"]["flowLogicInstances"]) == 2


def test_add_branch_requires_node_id_and_value():
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=_flow()),
        patch("servicenow_mcp.tools.flow_edit_tools._save_checkout"),
    ):
        missing_value = manage_flow_edit(
            _cfg(),
            MagicMock(spec=AuthManager),
            ManageFlowEditParams(action="add_branch", flow_id="f1", node_id="IF1"),
        )
    assert missing_value["success"] is False
    assert "condition" in missing_value["error"]
