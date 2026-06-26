"""Tests for the response-size guard (utils/response_budget).

Invariants under test:
- A result that would overflow the client's byte ceiling is abridged so the
  client never silently truncates it to a scratchpad file.
- ONLY record-backed values (container has sys_id) are stubbed, so every stub
  carries a correct re-fetch hint; computed/non-recoverable values are left whole.
- Identity/safety/computed keys are never abridged at any depth.
- The budget is measured in UTF-8 bytes (CJK-safe).
- Input is never mutated; the result fits the budget (or honestly reports it can't).
"""

import copy

from servicenow_mcp.utils.response_budget import (
    DEFAULT_BUDGET_BYTES,
    ENV_BUDGET,
    MIN_STUB_FIELD_BYTES,
    PREVIEW_CHARS,
    PROTECTED_KEYS,
    _sha256,
    byte_len,
    enforce_response_budget,
    get_response_budget,
)


def _big(n: int) -> str:
    return "x" * n


# --------------------------------------------------------------------------- #
# Budget resolution
# --------------------------------------------------------------------------- #


def test_default_budget_when_env_unset(monkeypatch):
    monkeypatch.delenv(ENV_BUDGET, raising=False)
    assert get_response_budget() == DEFAULT_BUDGET_BYTES


def test_env_override(monkeypatch):
    monkeypatch.setenv(ENV_BUDGET, "1234")
    assert get_response_budget() == 1234


def test_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv(ENV_BUDGET, "not-a-number")
    assert get_response_budget() == DEFAULT_BUDGET_BYTES
    monkeypatch.setenv(ENV_BUDGET, "-5")
    assert get_response_budget() == DEFAULT_BUDGET_BYTES


def test_env_integration_drives_abridging(monkeypatch):
    monkeypatch.setenv(ENV_BUDGET, "1000")
    result = {"sys_id": "W", "table": "sp_widget", "script": _big(9_000)}
    bounded, abridged = enforce_response_budget(result, tool_name="x")  # budget=None -> env
    assert abridged is True
    assert byte_len(bounded) <= 1000


# --------------------------------------------------------------------------- #
# Pass-through (common, small case)
# --------------------------------------------------------------------------- #


def test_small_result_unchanged():
    result = {"success": True, "rows": [{"a": 1}, {"b": "short"}]}
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=10_000)
    assert abridged is False
    assert bounded is result


def test_non_container_unchanged():
    bounded, abridged = enforce_response_budget("a string", tool_name="x", budget=10)
    assert abridged is False
    assert bounded == "a string"


# --------------------------------------------------------------------------- #
# Record-backed stubbing
# --------------------------------------------------------------------------- #


def test_largest_field_stubbed_small_kept_and_fits():
    result = {
        "sys_id": "abc123",
        "table": "sp_widget",
        "script": _big(40_000),
        "css": _big(3_000),
    }
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=10_000)
    assert abridged is True
    assert isinstance(bounded["script"], dict) and bounded["script"]["_abridged"] is True
    assert bounded["css"] == _big(3_000)  # smaller field kept whole
    assert byte_len(bounded) <= 10_000


def test_only_largest_stubbed_when_sufficient():
    # Stubbing the single biggest field alone fits — smaller eligible fields stay.
    result = {
        "sys_id": "s",
        "table": "sp_widget",
        "script": _big(80_000),
        "template": _big(3_000),
    }
    bounded, _ = enforce_response_budget(result, tool_name="x", budget=20_000)
    assert isinstance(bounded["script"], dict)
    assert bounded["template"] == _big(3_000)
    assert bounded["_abridged_fields"] == ["script"]


def test_stub_shape_and_integrity():
    body = _big(40_000)
    result = {"sys_id": "s1", "table": "sp_widget", "script": body}
    bounded, _ = enforce_response_budget(result, tool_name="x", budget=5_000)
    stub = bounded["script"]
    assert stub["_full_length"] == 40_000
    assert stub["_sha256"] == _sha256(body)
    assert stub["_preview"] == body[:PREVIEW_CHARS]
    assert len(stub["_preview"]) == PREVIEW_CHARS


def test_marker_overhead_kept_under_budget():
    # Many small metadata fields + one big code field at a tight budget: the
    # appended _abridged_fields/_note marker must not push it back over budget.
    result = {"sys_id": "S", "table": "sp_widget", "script": _big(20_000)}
    for i in range(15):
        result[f"meta{i}"] = "v" * 100
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=4_000)
    assert abridged is True
    assert byte_len(bounded) <= 4_000


# --------------------------------------------------------------------------- #
# Only RECORD-BACKED values are stubbed
# --------------------------------------------------------------------------- #


def test_non_record_backed_field_left_whole():
    # No sys_id in the container -> not stubbed (its scratchpad copy is recoverable).
    result = {"blob": _big(90_000)}
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=1_000)
    assert abridged is False
    assert bounded is result


def test_computed_diff_not_destroyed():
    # diff_local_component returns a computed diff with no sys_id/table; stubbing
    # it would be irrecoverable, so it must be left whole.
    result = {
        "mode": "diff",
        "component": {"table": "sp_widget", "name": "w"},
        "diffs": [{"field": "script", "status": "modified", "diff": _big(90_000)}],
    }
    bounded, abridged = enforce_response_budget(
        result, tool_name="diff_local_component", budget=1_000
    )
    assert abridged is False
    assert bounded["diffs"][0]["diff"] == _big(90_000)


# --------------------------------------------------------------------------- #
# Protected keys — never abridged at any depth
# --------------------------------------------------------------------------- #


def test_protected_direct_string_kept():
    long_msg = _big(90_000)
    result = {"sys_id": "s", "table": "sp_widget", "message": long_msg, "script": _big(90_000)}
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=5_000)
    assert abridged is True
    assert bounded["message"] == long_msg  # protected, kept whole
    assert isinstance(bounded["script"], dict)  # unprotected record-backed, stubbed


def test_protected_nested_subtree_kept():
    # Safety reasoning nested in list/dict under protected keys must survive.
    result = {
        "sys_id": "s",
        "table": "sp_widget",
        "factors": [_big(9_000)],
        "warnings": {"detail": _big(9_000)},
        "script": _big(90_000),
    }
    bounded, _ = enforce_response_budget(result, tool_name="x", budget=5_000)
    assert bounded["factors"] == [_big(9_000)]
    assert bounded["warnings"] == {"detail": _big(9_000)}
    assert isinstance(bounded["script"], dict)


def test_safety_notice_protected():
    assert "safety_notice" in PROTECTED_KEYS
    assert "note" in PROTECTED_KEYS
    assert "diff" in PROTECTED_KEYS and "diffs" in PROTECTED_KEYS


def test_single_huge_protected_field_left_whole():
    # Nothing safely abridgeable -> leave whole; the client scratchpad copy is recoverable.
    result = {"success": False, "error": "boom", "message": _big(200_000)}
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=75_000)
    assert abridged is False
    assert bounded is result


# --------------------------------------------------------------------------- #
# Recursion: nested record-backed dict
# --------------------------------------------------------------------------- #


def test_nested_record_backed_dict_abridged():
    result = {
        "flow": "MyFlow",
        "widget": {"sys_id": "a1", "table": "sp_widget", "script": _big(90_000)},
    }
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=5_000)
    assert abridged is True
    assert isinstance(bounded["widget"]["script"], dict)
    assert bounded["widget"]["sys_id"] == "a1"
    assert "widget.script" in bounded["_abridged_fields"]


# --------------------------------------------------------------------------- #
# Row truncation (lists overflowing by element count)
# --------------------------------------------------------------------------- #


def test_row_count_overflow_truncated_and_fits():
    result = {
        "success": True,
        "table": "incident",
        "results": [{"sys_id": f"r{i}", "desc": "y" * 500} for i in range(300)],
    }
    assert byte_len(result) > 20_000
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=20_000)
    assert abridged is True
    assert byte_len(bounded) <= 20_000
    # A navigable marker row is appended and the top level flags the drop.
    assert bounded["results"][-1]["_truncated_items"] > 0
    assert bounded["_truncated_items"] > 0
    # Kept rows are intact.
    assert bounded["results"][0] == {"sys_id": "r0", "desc": "y" * 500}


# --------------------------------------------------------------------------- #
# Byte budget (CJK)
# --------------------------------------------------------------------------- #


def test_budget_measured_in_utf8_bytes():
    # 5000 Korean chars = 15000 UTF-8 bytes: must be treated as over a 9000 budget
    # even though len(str) == 5000 < 9000.
    body = "가" * 5_000
    result = {"sys_id": "s", "table": "sp_widget", "script": body}
    assert len(body) < 9_000 < len(body.encode("utf-8"))
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=9_000)
    assert abridged is True
    assert byte_len(bounded) <= 9_000


# --------------------------------------------------------------------------- #
# Fetch hints
# --------------------------------------------------------------------------- #


def test_precise_hint_for_portal_table():
    result = {"sys_id": "WID1", "table": "sp_widget", "script": _big(90_000)}
    bounded, _ = enforce_response_budget(result, tool_name="get_widget_bundle", budget=5_000)
    hint = bounded["script"]["_fetch"]
    assert "get_portal_component_code" in hint
    assert "WID1" in hint and "sp_widget" in hint and "script" in hint


def test_non_portal_table_uses_sn_query_hint():
    # A business-rule script (sys_script) must NOT be told to call a portal tool.
    result = {"sys_id": "BR1", "table": "sys_script", "script": _big(90_000)}
    bounded, _ = enforce_response_budget(result, tool_name="x", budget=5_000)
    hint = bounded["script"]["_fetch"]
    assert "get_portal_component_code" not in hint
    assert "sn_query" in hint and "sys_script" in hint and "BR1" in hint


def test_widget_table_inferred_from_tool_name():
    result = {"widget": {"sys_id": "WID2", "script": _big(90_000)}}
    bounded, _ = enforce_response_budget(result, tool_name="get_widget_bundle", budget=5_000)
    assert "sp_widget" in bounded["widget"]["script"]["_fetch"]
    assert "WID2" in bounded["widget"]["script"]["_fetch"]


# --------------------------------------------------------------------------- #
# Immutability and markers
# --------------------------------------------------------------------------- #


def test_input_not_mutated():
    result = {"sys_id": "s", "table": "sp_widget", "script": _big(90_000)}
    snapshot = copy.deepcopy(result)
    enforce_response_budget(result, tool_name="x", budget=5_000)
    assert result == snapshot
    assert isinstance(result["script"], str)


def test_top_level_marker_added():
    result = {"sys_id": "s", "table": "sp_widget", "script": _big(90_000)}
    bounded, _ = enforce_response_budget(result, tool_name="x", budget=5_000)
    assert bounded["_abridged_fields"] == ["script"]
    assert "NOT the complete content" in bounded["_abridged_note"]


def test_realistic_widget_bundle_fits_budget():
    result = {
        "widget": {
            "sys_id": "W",
            "table": "sp_widget",
            "name": "big_widget",
            "template": _big(30_000),
            "script": _big(40_000),
            "client_script": _big(20_000),
            "css": _big(15_000),
        },
        "providers": [{"name": "p1"}],
    }
    assert byte_len(result) > 75_000
    bounded, abridged = enforce_response_budget(
        result, tool_name="get_widget_bundle", budget=75_000
    )
    assert abridged is True
    assert byte_len(bounded) <= 75_000
    assert bounded["widget"]["sys_id"] == "W"
    assert bounded["widget"]["name"] == "big_widget"


def test_stubbing_and_row_truncation_together_fit_budget():
    # Both mechanisms fire: a big record-backed field (stubbed) AND a long row
    # list (truncated). The variable-size marker reserve must keep it under budget.
    result = {
        "sys_id": "W",
        "table": "sp_widget",
        "script": _big(40_000),
        "results": [{"sys_id": f"r{i}", "desc": "y" * 500} for i in range(300)],
    }
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=20_000)
    assert abridged is True
    assert isinstance(bounded["script"], dict)
    assert bounded["results"][-1]["_truncated_items"] > 0
    assert byte_len(bounded) <= 20_000


def test_table_less_hint_references_producing_tool():
    # A flow step has a sys_id but no table -> the hint must point back at the
    # producing tool, not an unactionable sys_id read.
    result = {"steps": [{"sys_id": "STEP1", "script": _big(40_000)}]}
    bounded, _ = enforce_response_budget(result, tool_name="manage_flow_designer", budget=3_000)
    hint = bounded["steps"][0]["script"]["_fetch"]
    assert "manage_flow_designer" in hint and "STEP1" in hint


def test_portal_hint_uses_chunked_recovery():
    result = {"sys_id": "W", "table": "sp_widget", "script": _big(40_000)}
    bounded, _ = enforce_response_budget(result, tool_name="x", budget=3_000)
    hint = bounded["script"]["_fetch"]
    assert "fetch_complete=false" in hint and "next_offset" in hint
    assert "in full" not in hint  # honest: chunked, not one-shot


def test_row_marker_has_no_false_paging_promise():
    result = {"items": [{"sys_id": f"r{i}", "v": "y" * 600} for i in range(200)]}
    bounded, _ = enforce_response_budget(result, tool_name="x", budget=15_000)
    marker = bounded["items"][-1]
    assert marker["_truncated_items"] > 0
    assert "offset/limit" not in marker["_fetch"]


def test_list_nested_in_list_truncated():
    result = {"data": [[{"sys_id": f"r{i}", "v": "y" * 500} for i in range(300)]]}
    assert byte_len(result) > 15_000
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=15_000)
    assert abridged is True
    assert byte_len(bounded) <= 15_000
    assert bounded["data"][0][-1]["_truncated_items"] > 0


def test_min_stub_field_floor_respected():
    # A record-backed field under the floor is never stubbed.
    result = {"sys_id": "s", "table": "sp_widget", "small": _big(MIN_STUB_FIELD_BYTES - 1)}
    bounded, abridged = enforce_response_budget(result, tool_name="x", budget=500)
    assert abridged is False  # under floor, nothing eligible, left whole
    assert bounded is result
