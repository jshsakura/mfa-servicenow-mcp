"""_flow_runtime_status: the direct, unambiguous publish answer so a caller never
has to read the sys_hub_flow snapshot columns to tell "draft status" from "live"."""

from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.flow_designer_tools import _flow_runtime_status


def _rows(active, master, latest):
    return ([{"active": active, "master_snapshot": master, "latest_snapshot": latest}], None)


@patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
def test_live_and_current(mock_q):
    # active + master == latest -> the published version IS the latest.
    mock_q.return_value = _rows("true", "snap-1", "snap-1")
    out = _flow_runtime_status(MagicMock(), MagicMock(), "flow-1")
    assert out["live"] is True
    assert out["published_is_current"] is True
    assert out["has_unpublished_edits"] is False
    assert "LIVE" in out["note"]


@patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
def test_live_but_unpublished_edits_ahead(mock_q):
    # active but latest != master -> a draft sits ahead of what actually runs.
    mock_q.return_value = _rows("true", "snap-1", "snap-2")
    out = _flow_runtime_status(MagicMock(), MagicMock(), "flow-1")
    assert out["live"] is True
    assert out["published_is_current"] is False
    assert out["has_unpublished_edits"] is True
    assert "UNPUBLISHED" in out["note"]


@patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
def test_not_live_when_inactive(mock_q):
    mock_q.return_value = _rows("false", "snap-1", "snap-1")
    out = _flow_runtime_status(MagicMock(), MagicMock(), "flow-1")
    assert out["live"] is False
    assert out["published_is_current"] is False
    assert "NOT LIVE" in out["note"]


@patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
def test_missing_flow_returns_empty(mock_q):
    mock_q.return_value = ([], None)
    assert _flow_runtime_status(MagicMock(), MagicMock(), "nope") == {}


@patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page", side_effect=RuntimeError("boom"))
def test_lookup_failure_is_advisory(mock_q):
    # Never break get_detail on a runtime-status lookup error.
    assert _flow_runtime_status(MagicMock(), MagicMock(), "flow-1") == {}
