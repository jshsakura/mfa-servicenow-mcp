"""Direct tests for servicenow_mcp.services.change covering branches that the
existing snapshot tests in test_change_snapshots.py do not exercise.

Targeted lines (as of v1.9.41 baseline): 120 (update dry_run), 146-148
(update error path), 198-200 (add_task error path), 222-295 (entire get/list
function including timeframe filters).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import change as change_service


def _resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


@pytest.fixture
def auth(mock_auth):
    mock_auth.make_request = MagicMock()
    return mock_auth


# ---------------------------------------------------------------------------
# update — dry_run branch + error path (lines 120, 146-148)
# ---------------------------------------------------------------------------


def test_update_dry_run_returns_preview_without_writing(mock_config, auth):
    with patch("servicenow_mcp.services.change.build_update_preview") as mock_preview:
        mock_preview.return_value = {"success": True, "dry_run": True, "preview": "..."}
        result = change_service.update(
            mock_config,
            auth,
            change_id="ch_001",
            short_description="Bumped",
            dry_run=True,
        )
    # build_update_preview is called and its return is forwarded as-is
    assert result == {"success": True, "dry_run": True, "preview": "..."}
    mock_preview.assert_called_once()
    # No write attempted
    auth.make_request.assert_not_called()


def test_update_error_path_wraps_exception(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("network down")
    with patch("servicenow_mcp.services.change.invalidate_query_cache"):
        result = change_service.update(mock_config, auth, change_id="ch_001", short_description="x")
    assert result["success"] is False
    assert "network down" in result["message"]


# ---------------------------------------------------------------------------
# add_task error path (lines 198-200)
# ---------------------------------------------------------------------------


def test_add_task_error_path_wraps_exception(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("server 500")
    with patch("servicenow_mcp.services.change.invalidate_query_cache"):
        result = change_service.add_task(
            mock_config, auth, change_id="ch_001", short_description="step"
        )
    assert result["success"] is False
    assert "server 500" in result["message"]


# ---------------------------------------------------------------------------
# get — single-detail path (lines 222-249)
# ---------------------------------------------------------------------------


def test_get_single_returns_change_and_tasks(mock_config, auth):
    with patch("servicenow_mcp.services.change.sn_query_page") as mock_qp:
        mock_qp.side_effect = [
            ([{"sys_id": "ch_001", "number": "CHG0001"}], 1),  # change_request row
            ([{"sys_id": "tsk_1"}, {"sys_id": "tsk_2"}], 2),  # change_task rows
        ]
        result = change_service.get(mock_config, auth, change_id="ch_001")
    assert result["success"] is True
    assert result["change_request"]["sys_id"] == "ch_001"
    assert len(result["tasks"]) == 2


def test_get_single_not_found(mock_config, auth):
    with patch("servicenow_mcp.services.change.sn_query_page") as mock_qp:
        mock_qp.return_value = ([], 0)
        result = change_service.get(mock_config, auth, change_id="ch_missing")
    assert result["success"] is False
    assert "not found" in result["message"]


def test_get_single_error_path(mock_config, auth):
    with patch("servicenow_mcp.services.change.sn_query_page") as mock_qp:
        mock_qp.side_effect = RuntimeError("oops")
        result = change_service.get(mock_config, auth, change_id="ch_001")
    assert result["success"] is False
    assert "oops" in result["message"]


# ---------------------------------------------------------------------------
# get — list path including filter combinations and timeframe branches
# (lines 251-295)
# ---------------------------------------------------------------------------


def test_get_list_count_only(mock_config, auth):
    with patch("servicenow_mcp.services.change.sn_count") as mock_count:
        mock_count.return_value = 42
        result = change_service.get(mock_config, auth, state="2", count_only=True)
    assert result == {"success": True, "count": 42}
    # Query passed contains the state filter
    assert "state=2" in mock_count.call_args[0][3]


def test_get_list_with_filters_and_query(mock_config, auth):
    with patch("servicenow_mcp.services.change.sn_query_page") as mock_qp:
        mock_qp.return_value = ([{"sys_id": "a"}, {"sys_id": "b"}], 2)
        result = change_service.get(
            mock_config,
            auth,
            state="3",
            type="normal",
            category="hardware",
            assignment_group="grp_1",
            query="active=true",
            limit=50,
        )
    assert result["success"] is True
    assert result["count"] == 2
    q = mock_qp.call_args.kwargs["query"]
    assert "state=3" in q
    assert "type=normal" in q
    assert "category=hardware" in q
    assert "assignment_group=grp_1" in q
    assert "active=true" in q


@pytest.mark.parametrize(
    "timeframe,fragment",
    [
        ("upcoming", "start_date>"),
        ("in-progress", "start_date<"),
        ("completed", "end_date<"),
    ],
)
def test_get_list_timeframe_branches(mock_config, auth, timeframe, fragment):
    with patch("servicenow_mcp.services.change.sn_query_page") as mock_qp:
        mock_qp.return_value = ([], 0)
        change_service.get(mock_config, auth, timeframe=timeframe)
    q = mock_qp.call_args.kwargs["query"]
    assert fragment in q


def test_get_list_total_falls_back_to_len_when_unknown(mock_config, auth):
    with patch("servicenow_mcp.services.change.sn_query_page") as mock_qp:
        mock_qp.return_value = ([{"sys_id": "a"}], None)
        result = change_service.get(mock_config, auth)
    assert result["total"] == 1  # falls back to len(rows)


def test_get_list_error_path(mock_config, auth):
    with patch("servicenow_mcp.services.change.sn_query_page") as mock_qp:
        mock_qp.side_effect = RuntimeError("list failed")
        result = change_service.get(mock_config, auth)
    assert result["success"] is False
    assert "list failed" in result["message"]
