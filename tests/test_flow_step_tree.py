"""The flow reader (render_flow_compact) presents the canvas as ONE context-safe
indented text tree (actions/logic/subflows merged by order, children nested
under their If parent) with conditions decoded and data pills resolved to step
labels — so a human can point at "that step under the If" even when editing is
blocked. It reuses the canonical flow_designer detail→summary→text pipeline.
"""

from servicenow_mcp.tools.flow_designer_tools import _readable_pill, render_flow_compact
from servicenow_mcp.tools.flow_edit_tools import _render_inputs

# Two top-level steps; an If (uid=if1) at order 2 nests an action at order 3 and
# a nested If (uid=if2) at order 4, which itself nests End at order 5. The nested
# If's condition references the Ask-For-Approval step by uiUniqueIdentifier.
_FLOW = {
    "id": "f1",
    "name": "F",
    "type": "flow",
    "actionInstances": [
        {
            "id": "a1",
            "uiUniqueIdentifier": "uidA1",
            "name": "Look Up Record",
            "internalName": "look_up_record",
            "order": "1",
            "parent": "",
            "inputs": [{"name": "table", "value": "incident", "displayValue": "Incident"}],
        },
        {
            "id": "a2",
            "uiUniqueIdentifier": "uidA2",
            "name": "Ask For Approval",
            "internalName": "ask_for_approval",
            "order": "3",
            "parent": "if1",
            "inputs": [],
        },
    ],
    "flowLogicInstances": [
        {
            "id": "l1",
            "uiUniqueIdentifier": "if1",
            "name": "If: check",
            "order": "2",
            "parent": "",
            "inputs": [
                {"name": "condition_name", "value": "check"},
                {"name": "condition", "value": "active=true"},
            ],
        },
        {
            "id": "l2",
            "uiUniqueIdentifier": "if2",
            "name": "If: reject",
            "order": "4",
            "parent": "if1",
            "inputs": [{"name": "condition", "value": "{{uidA2.approval_state}}=rejected"}],
        },
        {
            "id": "l3",
            "uiUniqueIdentifier": "end1",
            "name": "End",
            "order": "5",
            "parent": "if2",
            "inputs": [],
        },
    ],
    "subFlowInstances": [],
}


def test_compact_meta_and_counts():
    r = render_flow_compact(_FLOW)
    assert r["flow_id"] == "f1" and r["type"] == "flow"
    assert r["counts"] == {"actions": 2, "logic": 3, "subflows": 0}
    assert isinstance(r["tree"], str)


def test_compact_order_and_nesting():
    tree = render_flow_compact(_FLOW)["tree"]
    # ordered, with deeper steps indented (depth → leading spaces after the [n])
    assert "[1] ACTION" in tree
    assert "[2] LOGIC" in tree
    assert "[3]   ACTION" in tree  # nested one level under the If
    assert "[4]   LOGIC" in tree
    assert "[5]     LOGIC" in tree  # nested two levels


def test_compact_resolves_uid_pill_and_decodes_condition():
    tree = render_flow_compact(_FLOW)["tree"]
    # {{uidA2.approval_state}}=rejected → pill resolved + operator humanized
    assert "Ask For Approval ▸ approval_state is rejected" in tree
    # the plain encoded query is gone
    assert "{{uidA2.approval_state}}" not in tree


def test_compact_no_crash_on_missing_uid():
    flow = {
        "id": "f",
        "actionInstances": [{"id": "a", "name": "A", "order": "1", "parent": ""}],  # no ui_id
        "flowLogicInstances": [],
        "subFlowInstances": [],
    }
    r = render_flow_compact(flow)
    assert isinstance(r["tree"], str)  # dropped-no-ui-id is handled, no exception


def test_compact_no_crash_on_duplicate_uid():
    # Duplicate uiUniqueIdentifier makes _build_flow_summary raise
    # FlowSummaryIntegrityError; render_flow_compact must catch and degrade.
    flow = {
        "id": "f",
        "actionInstances": [],
        "flowLogicInstances": [
            {"id": "R", "uiUniqueIdentifier": "ur", "name": "R", "order": "1", "parent": ""},
            {"id": "X", "uiUniqueIdentifier": "ur", "name": "X", "order": "2", "parent": "ur"},
        ],
        "subFlowInstances": [],
    }
    r = render_flow_compact(flow)
    assert isinstance(r["tree"], str)
    assert "unavailable" in r["tree"]


def test_field_pill_resolution_via_label_map():
    assert _readable_pill("{{uidX.foo.bar}}", {"uidX": "My Step"}) == "My Step ▸ foo ▸ bar"


def test_script_input_flagged_and_kept_whole():
    body = "\n".join(f"line{i}" for i in range(40))
    rendered = _render_inputs([{"name": "script", "value": body}])
    assert rendered[0]["is_script"] is True
    assert rendered[0]["line_count"] == 40
    assert rendered[0]["value"] == body  # never truncated
