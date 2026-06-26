"""serialize_tool_output must route dict results through the response-size guard
end-to-end: small results untouched, oversized record-backed results abridged
under budget, and oversized-but-unabridgeable results passed through whole."""

import json

from servicenow_mcp.server import serialize_tool_output


def _utf8(s: str) -> int:
    return len(s.encode("utf-8"))


def test_small_dict_not_abridged(monkeypatch):
    monkeypatch.setenv("SERVICENOW_RESPONSE_BUDGET_CHARS", "10000")
    result = {"success": True, "rows": [{"a": 1}, {"b": "short"}]}
    out = serialize_tool_output(result, "x")
    assert "_abridged" not in out
    assert json.loads(out) == result


def test_oversized_record_backed_abridged_under_budget(monkeypatch):
    monkeypatch.setenv("SERVICENOW_RESPONSE_BUDGET_CHARS", "3000")
    result = {"sys_id": "W", "table": "sp_widget", "script": "x" * 50_000}
    out = serialize_tool_output(result, "get_widget_bundle")
    assert "_abridged" in out
    assert _utf8(out) <= 3000
    parsed = json.loads(out)
    assert parsed["script"]["_abridged"] is True
    assert "get_portal_component_code" in parsed["script"]["_fetch"]


def test_oversized_unabridgeable_passed_through(monkeypatch):
    # A single huge PROTECTED field cannot be safely abridged; emit it whole
    # (the client's scratchpad copy is recoverable) rather than corrupt it.
    monkeypatch.setenv("SERVICENOW_RESPONSE_BUDGET_CHARS", "5000")
    result = {"success": False, "error": "boom", "message": "z" * 50_000}
    out = serialize_tool_output(result, "x")
    assert "_abridged" not in out
    assert json.loads(out) == result
