"""Direct tests for servicenow_mcp.services.changeset get/list path.

Targeted lines (as of v1.9.41 baseline): 73, 77 (update field branches for
description/developer), 223-296 (entire get function).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import changeset as cs_service


@pytest.fixture
def auth(mock_auth):
    mock_auth.make_request = MagicMock()
    mock_auth.get_headers = MagicMock(return_value={})
    return mock_auth


# ---------------------------------------------------------------------------
# update — description/developer branches (lines 73, 77)
# ---------------------------------------------------------------------------


def test_update_sends_only_columns_that_exist(mock_config, auth):
    """Cover the if-description and if-developer branches."""

    captured: dict = {}

    def _capture(method, url, **kwargs):
        captured["json"] = kwargs.get("json")
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"result": {"sys_id": "us_001"}}
        r.raise_for_status = MagicMock()
        return r

    auth.make_request.side_effect = _capture
    with patch("servicenow_mcp.services.changeset.invalidate_query_cache"):
        result = cs_service.update(
            mock_config,
            auth,
            changeset_id="us_001",
            description="updated desc",
            developer="user.dev",
        )
    assert result["success"] is True
    # `developer` is not a column on sys_update_set and is no longer sent.
    assert captured["json"] == {"description": "updated desc"}


# ---------------------------------------------------------------------------
# get — single detail
# ---------------------------------------------------------------------------


def test_get_single_returns_changeset_and_changes(mock_config, auth):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.side_effect = [
            ([{"sys_id": "us_001", "name": "App release"}], 1),  # the changeset
            ([{"sys_id": "x1"}, {"sys_id": "x2"}], 2),  # sys_update_xml rows
        ]
        result = cs_service.get(mock_config, auth, changeset_id="us_001")
    assert result["success"] is True
    assert result["changeset"]["sys_id"] == "us_001"
    assert result["change_count"] == 2


def test_entries_are_listed_without_their_payload(mock_config, auth):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.side_effect = [([{"sys_id": "us_001"}], 1), ([{"sys_id": "x1"}], 1)]
        result = cs_service.get(mock_config, auth, changeset_id="us_001")
    entries_call = mock_qp.call_args_list[1].kwargs
    assert entries_call["fields"] == cs_service.ENTRY_LISTING_FIELDS
    assert "payload" not in entries_call["fields"].split(",")
    assert "target_name" in entries_call["fields"].split(",")
    # A silenced read would come back as "0 entries"; this one must raise instead.
    assert entries_call["fail_silently"] is False
    assert "include_payload=true" in result["payload"]
    assert "complete" not in result


def test_include_payload_reads_every_column(mock_config, auth):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.side_effect = [([{"sys_id": "us_001"}], 1), ([{"sys_id": "x1"}], 1)]
        result = cs_service.get(mock_config, auth, changeset_id="us_001", include_payload=True)
    assert mock_qp.call_args_list[1].kwargs["fields"] == ""
    assert "payload" not in result


@pytest.mark.parametrize("total", [250, None])
def test_a_capped_listing_says_so_and_names_the_next_read(mock_config, auth, total):
    rows = [{"sys_id": f"x{i}"} for i in range(cs_service.ENTRY_LISTING_LIMIT)]
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.side_effect = [([{"sys_id": "us_001"}], 1), (rows, total)]
        result = cs_service.get(mock_config, auth, changeset_id="us_001")
    assert result["complete"] is False
    assert result["change_total"] == total
    assert f"offset={cs_service.ENTRY_LISTING_LIMIT}" in result["more"]


def test_an_unreadable_entry_list_is_an_error_not_zero(mock_config, auth):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.side_effect = [([{"sys_id": "us_001"}], 1), RuntimeError("HTTP 500")]
        result = cs_service.get(mock_config, auth, changeset_id="us_001")
    assert result["success"] is False and "HTTP 500" in result["message"]
    assert "change_count" not in result


def test_get_single_not_found(mock_config, auth):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.return_value = ([], 0)
        result = cs_service.get(mock_config, auth, changeset_id="missing")
    assert result["success"] is False
    assert "not found" in result["message"].lower()


def test_get_single_error_path(mock_config, auth):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.side_effect = RuntimeError("detail err")
        result = cs_service.get(mock_config, auth, changeset_id="us_001")
    assert result["success"] is False
    assert "detail err" in result["message"]


# ---------------------------------------------------------------------------
# get — list path including filters and timeframe branches
# ---------------------------------------------------------------------------


def test_get_list_count_only(mock_config, auth):
    with patch("servicenow_mcp.tools.sn_api.sn_count") as mock_count:
        mock_count.return_value = 5
        result = cs_service.get(mock_config, auth, state="in_progress", count_only=True)
    assert result == {"success": True, "count": 5}
    assert "state=in_progress" in mock_count.call_args[0][3]


def test_get_list_with_all_filters(mock_config, auth):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.return_value = ([{"sys_id": "us_a"}], 1)
        result = cs_service.get(
            mock_config,
            auth,
            state="complete",
            application="x_app",
            developer="user.dev",
            query="active=true",
        )
    assert result["success"] is True
    q = mock_qp.call_args.kwargs["query"]
    assert "state=complete" in q
    assert "application=x_app" in q
    # Not a sys_update_set column: the server would drop the condition, so it
    # is never sent (and it used to be sent as developer=None).
    assert "developer" not in q
    assert "active=true" in q


@pytest.mark.parametrize(
    "timeframe,fragment",
    [
        ("recent", "Last 7 days"),
        ("last_week", "Last week"),
        ("last_month", "Last month"),
    ],
)
def test_get_list_timeframe_branches(mock_config, auth, timeframe, fragment):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.return_value = ([], 0)
        cs_service.get(mock_config, auth, timeframe=timeframe)
    q = mock_qp.call_args.kwargs["query"]
    assert fragment in q


def test_get_list_error_path(mock_config, auth):
    with patch("servicenow_mcp.services.changeset.sn_query_page") as mock_qp:
        mock_qp.side_effect = RuntimeError("list err")
        result = cs_service.get(mock_config, auth)
    assert result["success"] is False
    assert "list err" in result["message"]
