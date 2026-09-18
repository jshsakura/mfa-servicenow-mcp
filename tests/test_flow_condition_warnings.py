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

from servicenow_mcp.tools.flow_designer_tools import _build_flow_summary

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
