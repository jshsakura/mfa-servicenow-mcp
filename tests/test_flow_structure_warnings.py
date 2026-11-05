"""Structural flow warnings, built through the real tree builder."""

from servicenow_mcp.tools.flow_designer_tools import _build_flow_summary

APPROVAL = "aaaa1111-bbbb-2222-cccc-333344445555"
IF_ID = "bbbb2222-cccc-3333-dddd-444455556666"
CLOSE_ID = "cccc3333-dddd-4444-eeee-555566667777"
ELSE_ID = "dddd4444-eeee-5555-ffff-666677778888"


def _inp(**kw):
    return [{"name": k, "value": v} for k, v in kw.items()]


def _approval():
    return {
        "order": 1,
        "ui_id": APPROVAL,
        "parent_ui_id": "",
        "action_type_name": "Ask For Approval",
        "inputs": _inp(approval_conditions="x"),
    }


def _if(order=2, ui=IF_ID, condition="{{%s.approval_state}}=approved" % APPROVAL, kind="IF"):
    return {
        "order": order,
        "ui_id": ui,
        "parent_ui_id": "",
        "logic_type": kind,
        "condition": condition,
    }


def _close(order=3, ui=CLOSE_ID, values="state=closed_complete"):
    return {
        "order": order,
        "ui_id": ui,
        "parent_ui_id": "",
        "action_type_name": "Update Record",
        "inputs": _inp(record="r", table_name="t", values=values),
    }


def _codes(structure):
    return [w["code"] for w in _build_flow_summary(structure)["warnings"]]


def test_fall_through_autocomplete_fires():
    s = {"actions": [_approval(), _close()], "logic": [_if()], "subflows": []}
    assert "FALL_THROUGH_AUTOCOMPLETE" in _codes(s)


def test_fall_through_not_fired_with_else():
    s = {
        "actions": [_approval(), _close(order=4)],
        "logic": [_if(), _if(order=3, ui=ELSE_ID, condition="", kind="ELSE")],
        "subflows": [],
    }
    assert "FALL_THROUGH_AUTOCOMPLETE" not in _codes(s)


def test_fall_through_not_fired_for_non_closing_or_no_if():
    s = {"actions": [_approval(), _close(values="comments=hi")], "logic": [_if()], "subflows": []}
    assert "FALL_THROUGH_AUTOCOMPLETE" not in _codes(s)
    s = {"actions": [_approval(), _close()], "logic": [], "subflows": []}
    assert "FALL_THROUGH_AUTOCOMPLETE" not in _codes(s)


def test_reject_on_requested_fires():
    cond = "{{%s.approval_state}}=requested" % APPROVAL
    s = {"actions": [_approval()], "logic": [_if(condition=cond)], "subflows": []}
    assert "REJECT_ON_REQUESTED" in _codes(s)


def test_reject_on_requested_ignores_other_values_and_unknown_pills():
    s = {"actions": [_approval()], "logic": [_if()], "subflows": []}
    assert "REJECT_ON_REQUESTED" not in _codes(s)
    other = "{{eeee5555-ffff-6666-aaaa-777788889999.approval_state}}=requested"
    s = {"actions": [_approval()], "logic": [_if(condition=other)], "subflows": []}
    assert "REJECT_ON_REQUESTED" not in _codes(s)


def _sub(order, ui, **inputs):
    return {
        "order": order,
        "ui_id": ui,
        "parent_ui_id": "",
        "subflow_name": "Sample Subflow",
        "subflow_sys_id": "aaaa1111bbbb2222cccc3333dddd4444",
        "inputs": _inp(**inputs),
    }


def test_subflow_input_name_mismatch_fires():
    s = {
        "actions": [],
        "logic": [],
        "subflows": [
            _sub(1, "u1", reject="a", record="b"),
            _sub(2, "u2", rejected="a", record="b"),
        ],
    }
    hits = [
        w for w in _build_flow_summary(s)["warnings"] if w["code"] == "SUBFLOW_INPUT_NAME_MISMATCH"
    ]
    assert len(hits) == 1
    assert "reject" in hits[0]["message"] and "rejected" in hits[0]["message"]


def test_subflow_input_mismatch_ignores_same_and_unrelated_names():
    same = [_sub(1, "u1", reject="a"), _sub(2, "u2", reject="b")]
    assert "SUBFLOW_INPUT_NAME_MISMATCH" not in _codes(
        {"actions": [], "logic": [], "subflows": same}
    )
    diff = [_sub(1, "u1", reject="a"), _sub(2, "u2", approver="b")]
    assert "SUBFLOW_INPUT_NAME_MISMATCH" not in _codes(
        {"actions": [], "logic": [], "subflows": diff}
    )
