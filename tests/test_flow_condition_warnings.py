"""Two ways a branch condition reads correctly over the API and is broken on screen.

Flow Designer draws a condition row through the flow's label cache, which only
the field picker writes. So a pill that is not in that cache leaves the row EMPTY
on screen while the encoded query still decodes fine here — and a field picked
without its value gives a term that can never match. Both are mechanical and both
are pure reads, so the structure summary reports them.

`integrity.pill_registration_checked` exists because the label cache is not always
at hand: without it the pill check cannot run, and a missing warning must not read
as "the pills are fine".
"""

from servicenow_mcp.tools.flow_designer_tools import _annotate_condition_inputs, _build_flow_summary

STEP_UID = "aaaa1111-bbbb-2222-cccc-333344445555"
REGISTERED = f"{STEP_UID}.result_flag"
UNREGISTERED = "subflow.my_input.parent_ref.flag_field"


def _structure(condition):
    """One action and one IF branch carrying `condition`."""
    return {
        "actions": [{"order": 1, "ui_id": STEP_UID, "parent_ui_id": "", "action_type": "Do Thing"}],
        "logic": [
            {
                "order": 2,
                "ui_id": "bbbb2222-cccc-3333-dddd-444455556666",
                "parent_ui_id": "",
                "logic_type": "IF",
                "condition_label": "check",
                "condition": condition,
            }
        ],
        "subflows": [],
    }


def _warnings(condition, known_pills):
    out = _build_flow_summary(_structure(condition), known_pills=known_pills)
    return out, {w["code"] for w in out["warnings"]}


def test_unregistered_pill_is_reported_and_named():
    out, codes = _warnings(f"{{{{{UNREGISTERED}}}}}=true", {REGISTERED})
    assert "UNREGISTERED_CONDITION_PILL" in codes
    hit = next(w for w in out["warnings"] if w["code"] == "UNREGISTERED_CONDITION_PILL")
    assert UNREGISTERED in hit["message"]
    assert hit["severity"] == "high"


def test_registered_pill_is_not_reported():
    _, codes = _warnings(f"{{{{{REGISTERED}}}}}=true", {REGISTERED})
    assert "UNREGISTERED_CONDITION_PILL" not in codes


def test_empty_value_is_reported():
    """A field picked without its value — the term cannot match anything."""
    out, codes = _warnings(f"{{{{{REGISTERED}}}}}=", {REGISTERED})
    assert "EMPTY_CONDITION_VALUE" in codes
    hit = next(w for w in out["warnings"] if w["code"] == "EMPTY_CONDITION_VALUE")
    assert "EMPTY value" in hit["message"]


def test_value_less_operator_is_not_an_empty_value():
    """ISNOTEMPTY legitimately carries no value; flagging it would be noise."""
    _, codes = _warnings(f"{{{{{REGISTERED}}}}}ISNOTEMPTY", {REGISTERED})
    assert "EMPTY_CONDITION_VALUE" not in codes


def test_both_faults_are_reported_together():
    condition = f"{{{{{REGISTERED}}}}}=true^NQ{{{{{UNREGISTERED}}}}}="
    _, codes = _warnings(condition, {REGISTERED})
    assert {"UNREGISTERED_CONDITION_PILL", "EMPTY_CONDITION_VALUE"} <= codes


def test_without_the_label_cache_the_check_is_declared_unrun():
    """No cache → no pill check. The flag says so, so an empty warning list is
    not mistaken for a clean bill of health."""
    out, codes = _warnings(f"{{{{{UNREGISTERED}}}}}=true", None)
    assert out["integrity"]["pill_registration_checked"] is False
    assert "UNREGISTERED_CONDITION_PILL" not in codes


def test_with_the_label_cache_the_check_is_declared_run():
    out, _ = _warnings(f"{{{{{REGISTERED}}}}}=true", {REGISTERED})
    assert out["integrity"]["pill_registration_checked"] is True


# --- the single-node drill-down ------------------------------------------------
# The tree truncates a long condition and points at node_id for the full one. That
# read is the precise one, so its `value` stays the exact encoded query — but a
# raw uuid pill names nothing, so the readable form rides beside it.


def test_drilldown_keeps_the_exact_value_and_adds_the_readable_one():
    inputs = [{"name": "condition", "value": f"{{{{{REGISTERED}}}}}=true"}]
    _annotate_condition_inputs(inputs, {STEP_UID: "Do Thing"})
    assert inputs[0]["value"] == f"{{{{{REGISTERED}}}}}=true"
    assert inputs[0]["value_readable"] == "Do Thing ▸ result_flag is true"


def test_drilldown_without_a_label_map_still_decodes_the_operator():
    """No map means the step uuid cannot be named. The operator still decodes,
    and nothing is invented to fill the gap."""
    inputs = [{"name": "condition", "value": f"{{{{{REGISTERED}}}}}ISNOTEMPTY"}]
    _annotate_condition_inputs(inputs, None)
    assert "is not empty" in inputs[0]["value_readable"]
    assert STEP_UID in inputs[0]["value_readable"]


def test_drilldown_leaves_non_condition_inputs_alone():
    inputs = [{"name": "record", "value": "{{trigger.current}}"}]
    _annotate_condition_inputs(inputs, None)
    assert "value_readable" not in inputs[0]
