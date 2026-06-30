"""Writing a condition must be as easy as reading one: callers describe rows
({field, operator, value}) and the tool encodes them into a ServiceNow encoded
query — the inverse of the decoder — so nobody hand-writes 'a=1^ORb=2'.
"""

from servicenow_mcp.tools.flow_designer_tools import _condition_to_text, _encode_condition
from servicenow_mcp.tools.flow_edit_tools import _resolve_condition_value


def test_encode_basic_and():
    rows = [
        {"field": "state", "operator": "is", "value": "6"},
        {"field": "priority", "operator": "is", "value": "1"},
    ]
    assert _encode_condition(rows) == "state=6^priority=1"


def test_encode_accepts_human_labels_and_tokens():
    rows = [
        {"field": "short_description", "operator": "contains", "value": "vpn"},
        {"field": "priority", "operator": "CHANGESTO", "value": "1"},
        {"field": "state", "operator": "is not", "value": "7"},
    ]
    assert _encode_condition(rows) == "short_descriptionLIKEvpn^priorityCHANGESTO1^state!=7"


def test_encode_or_and_new_group():
    rows = [
        {"field": "a", "operator": "is", "value": "1"},
        {"field": "b", "operator": "is", "value": "2", "conjunction": "OR"},
        {"field": "c", "operator": "is", "value": "3", "conjunction": "NEW_GROUP"},
    ]
    assert _encode_condition(rows) == "a=1^ORb=2^NQc=3"


def test_encode_omits_value_for_empty_operators():
    rows = [{"field": "sys_id", "operator": "is not empty"}]
    assert _encode_condition(rows) == "sys_idISNOTEMPTY"


def test_encode_decode_roundtrip_readable():
    rows = [
        {"field": "state", "operator": "is", "value": "6"},
        {"field": "active", "operator": "is", "value": "true", "conjunction": "OR"},
    ]
    enc = _encode_condition(rows)
    assert _condition_to_text(enc) == "state is 6 OR active is true"


def test_resolve_accepts_raw_string_unchanged():
    raw = "state=6^priority=1"
    assert _resolve_condition_value(raw) == raw


def test_resolve_accepts_json_list_string():
    js = '[{"field":"state","operator":"is","value":"6"}]'
    assert _resolve_condition_value(js) == "state=6"


def test_resolve_accepts_python_list():
    rows = [{"field": "state", "operator": "is", "value": "6"}]
    assert _resolve_condition_value(rows) == "state=6"
