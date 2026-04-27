"""Direct tests for servicenow_mcp.services.incident covering uncovered branches.

Targeted lines (as of v1.9.41 baseline): error paths in update/add_comment/
resolve, dry_run for resolve, and the entire get/list function (sys_id vs
number routing, filter combinations, count_only, error paths).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import incident as incident_service
from servicenow_mcp.services.incident import IncidentResponse


def _resp(payload: dict, status: int = 200) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


@pytest.fixture
def auth(mock_auth):
    mock_auth.make_request = MagicMock()
    mock_auth.get_headers = MagicMock(return_value={})
    return mock_auth


# ---------------------------------------------------------------------------
# update / add_comment / resolve — error paths
# ---------------------------------------------------------------------------


def test_update_error_path(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("PUT failed")
    with patch("servicenow_mcp.services.incident.resolve_incident_sys_id") as mock_r:
        mock_r.return_value = ("sys_001", None)
        with patch("servicenow_mcp.services.incident.invalidate_query_cache"):
            result = incident_service.update(
                mock_config, auth, incident_id="INC0001", short_description="x"
            )
    assert isinstance(result, IncidentResponse)
    assert result.success is False
    assert "PUT failed" in result.message


def test_add_comment_error_path(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("comment failed")
    with patch("servicenow_mcp.services.incident.resolve_incident_sys_id") as mock_r:
        mock_r.return_value = ("sys_001", None)
        with patch("servicenow_mcp.services.incident.invalidate_query_cache"):
            result = incident_service.add_comment(
                mock_config, auth, incident_id="INC0001", comment="hi"
            )
    assert result.success is False
    assert "comment failed" in result.message


def test_resolve_error_path(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("resolve failed")
    with patch("servicenow_mcp.services.incident.resolve_incident_sys_id") as mock_r:
        mock_r.return_value = ("sys_001", None)
        with patch("servicenow_mcp.services.incident.invalidate_query_cache"):
            result = incident_service.resolve(
                mock_config,
                auth,
                incident_id="INC0001",
                resolution_code="solved",
                resolution_notes="fixed",
            )
    assert result.success is False
    assert "resolve failed" in result.message


def test_resolve_dry_run(mock_config, auth):
    with patch("servicenow_mcp.services.incident.resolve_incident_sys_id") as mock_r:
        mock_r.return_value = ("sys_001", None)
        with patch("servicenow_mcp.services.incident.build_update_preview") as mock_prev:
            mock_prev.return_value = {"success": True, "dry_run": True, "preview": "..."}
            result = incident_service.resolve(
                mock_config,
                auth,
                incident_id="INC0001",
                resolution_code="solved",
                resolution_notes="fixed",
                dry_run=True,
            )
    assert result == {"success": True, "dry_run": True, "preview": "..."}
    auth.make_request.assert_not_called()


# ---------------------------------------------------------------------------
# get — single detail (sys_id vs number routing)
# ---------------------------------------------------------------------------


def test_get_single_by_number_uses_number_filter(mock_config, auth):
    """A non-32-char incident_id is treated as INC number."""
    with patch("servicenow_mcp.services.incident.sn_query_page") as mock_qp:
        mock_qp.return_value = ([{"sys_id": "s1", "number": "INC0001"}], 1)
        result = incident_service.get(mock_config, auth, incident_id="INC0001")
    assert result["success"] is True
    assert "number=INC0001" in mock_qp.call_args.kwargs["query"]


def test_get_single_by_sys_id_uses_sys_id_filter(mock_config, auth):
    """A 32-char hex incident_id is treated as a sys_id."""
    sys_id = "a" * 32
    with patch("servicenow_mcp.services.incident.sn_query_page") as mock_qp:
        mock_qp.return_value = ([{"sys_id": sys_id, "number": "INC0009"}], 1)
        result = incident_service.get(mock_config, auth, incident_id=sys_id)
    assert result["success"] is True
    assert f"sys_id={sys_id}" in mock_qp.call_args.kwargs["query"]


def test_get_single_unwraps_assigned_to_display_value(mock_config, auth):
    with patch("servicenow_mcp.services.incident.sn_query_page") as mock_qp:
        mock_qp.return_value = (
            [{"sys_id": "s1", "number": "INC0001", "assigned_to": {"display_value": "Alice"}}],
            1,
        )
        result = incident_service.get(mock_config, auth, incident_id="INC0001")
    assert result["incident"]["assigned_to"] == "Alice"


def test_get_single_not_found(mock_config, auth):
    with patch("servicenow_mcp.services.incident.sn_query_page") as mock_qp:
        mock_qp.return_value = ([], 0)
        result = incident_service.get(mock_config, auth, incident_id="INC9999")
    assert result["success"] is False
    assert "not found" in result["message"].lower()


def test_get_single_error_path(mock_config, auth):
    with patch("servicenow_mcp.services.incident.sn_query_page") as mock_qp:
        mock_qp.side_effect = RuntimeError("boom")
        result = incident_service.get(mock_config, auth, incident_id="INC0001")
    assert result["success"] is False
    assert "boom" in result["message"]


# ---------------------------------------------------------------------------
# get — list path
# ---------------------------------------------------------------------------


def test_get_list_count_only(mock_config, auth):
    with patch("servicenow_mcp.services.incident.sn_count") as mock_count:
        mock_count.return_value = 7
        result = incident_service.get(mock_config, auth, state="2", count_only=True)
    assert result == {"success": True, "count": 7}
    assert "state=2" in mock_count.call_args[0][3]


def test_get_list_with_all_filters_and_search(mock_config, auth):
    with patch("servicenow_mcp.services.incident.sn_query_page") as mock_qp:
        mock_qp.return_value = (
            [{"sys_id": "s1", "number": "INC0001", "assigned_to": "Bob"}],
            1,
        )
        result = incident_service.get(
            mock_config,
            auth,
            state="1",
            assigned_to="user_bob",
            category="network",
            query="firewall",
        )
    assert result["success"] is True
    assert len(result["incidents"]) == 1
    q = mock_qp.call_args.kwargs["query"]
    assert "state=1" in q
    assert "assigned_to=user_bob" in q
    assert "category=network" in q
    assert "short_descriptionLIKEfirewall" in q


def test_get_list_unwraps_assigned_to_in_each_row(mock_config, auth):
    with patch("servicenow_mcp.services.incident.sn_query_page") as mock_qp:
        mock_qp.return_value = (
            [
                {"sys_id": "s1", "assigned_to": {"display_value": "Alice"}},
                {"sys_id": "s2", "assigned_to": "raw_string_user"},
            ],
            2,
        )
        result = incident_service.get(mock_config, auth)
    assigned = [i["assigned_to"] for i in result["incidents"]]
    assert assigned == ["Alice", "raw_string_user"]


def test_get_list_error_path(mock_config, auth):
    with patch("servicenow_mcp.services.incident.sn_query_page") as mock_qp:
        mock_qp.side_effect = RuntimeError("list err")
        result = incident_service.get(mock_config, auth)
    assert result["success"] is False
    assert "list err" in result["message"]
    assert result["incidents"] == []
