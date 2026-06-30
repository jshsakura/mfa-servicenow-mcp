"""The flow reader must decode encoded-query condition strings into the
human-readable builder rows the Flow Designer canvas shows — an opaque
'a=1^ORb=2' blob causes confusion on follow-up edits.
"""

from servicenow_mcp.tools.flow_designer_tools import _decode_condition, _readable_pill
from servicenow_mcp.tools.flow_edit_tools import _render_inputs


def test_single_is_condition_with_pill():
    rows = _decode_condition("u_ref_company={{Updated_1.current.company}}")
    assert len(rows) == 1
    r = rows[0]
    assert r["conjunction"] == "WHERE"
    assert r["field"] == "u_ref_company"
    assert r["op_label"] == "is"
    assert r["value"] == "{{Updated_1.current.company}}"
    assert r["value_pill"] == "Updated_1 ▸ current ▸ company"


def test_three_way_or_group():
    q = "a.name={{p.x}}^ORb.name={{p.x}}^ORc.name={{p.x}}"
    rows = _decode_condition(q)
    assert [r["conjunction"] for r in rows] == ["WHERE", "OR", "OR"]
    assert [r["field"] for r in rows] == ["a.name", "b.name", "c.name"]
    assert all(r["op_label"] == "is" for r in rows)


def test_and_and_operator_variants():
    rows = _decode_condition("active=true^priority!=1^short_descriptionLIKEvpn^stateISEMPTY")
    assert [r["conjunction"] for r in rows] == ["WHERE", "AND", "AND", "AND"]
    assert [(r["field"], r["op_label"]) for r in rows] == [
        ("active", "is"),
        ("priority", "is not"),
        ("short_description", "contains"),
        ("state", "is empty"),
    ]
    # ISEMPTY carries no value
    assert "value" not in rows[3] or rows[3]["value"] == ""


def test_greater_equal_matched_before_greater():
    rows = _decode_condition("amount>=100")
    assert rows[0]["operator"] == ">="
    assert rows[0]["op_label"] == "is at or after"
    assert rows[0]["value"] == "100"


def test_changes_family_operators():
    # record-update trigger: state changes from 1 to 6, new group from 9 to -11
    rows = _decode_condition(
        "stateCHANGESFROM1^stateCHANGESTO6^NQstateCHANGESFROM9^stateCHANGESTO-11"
    )
    assert [(r["field"], r["op_label"], r.get("value")) for r in rows] == [
        ("state", "changes from", "1"),
        ("state", "changes to", "6"),
        ("state", "changes from", "9"),
        ("state", "changes to", "-11"),
    ]
    assert rows[2]["conjunction"] == "NEW_GROUP"


def test_new_query_group_marker():
    rows = _decode_condition("a=1^NQb=2")
    assert rows[1]["conjunction"] == "NEW_GROUP"
    assert rows[1]["field"] == "b"


def test_readable_pill_non_pill_returns_none():
    assert _readable_pill("plain value") is None
    assert _readable_pill("{{a.b}}") == "a ▸ b"


def test_render_inputs_attaches_decoded_conditions():
    inputs = [
        {"name": "conditions", "value": "x=1^ORy=2"},
        {"name": "table", "value": "incident", "displayValue": "Incident"},
    ]
    rendered = {i["name"]: i for i in _render_inputs(inputs)}
    assert "conditions" in rendered["conditions"]
    assert len(rendered["conditions"]["conditions"]) == 2
    # non-condition inputs keep display, no decoded rows
    assert rendered["table"]["display"] == "Incident"
    assert "conditions" not in rendered["table"]
