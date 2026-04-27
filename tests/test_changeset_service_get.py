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


def test_update_description_and_developer_branches(mock_config, auth):
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
    assert captured["json"] == {"description": "updated desc", "developer": "user.dev"}


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
    with patch("servicenow_mcp.services.changeset.sn_count") as mock_count:
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
    assert "developer=user.dev" in q
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
