"""
Red-green tests for LLM token optimization:
1. count_only support in list tools
2. Compact JSON serialization (no indent)
3. Conditional metadata inclusion
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


def _mock_count_response(count: int):
    """Helper: mock response for Aggregate API (count endpoint)."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"result": {"stats": {"count": str(count)}}}
    return resp


# ============================================================================
# 1. count_only on list tools
# ============================================================================


class TestCountOnly:
    """Every list tool must support count_only=True to avoid fetching records."""

    def test_list_incidents_count_only(self, mock_config, mock_auth):
        from servicenow_mcp.tools.incident_tools import (
            GetIncidentByNumberParams,
            get_incident_by_number,
        )

        mock_auth.make_request.return_value = _mock_count_response(42)
        result = get_incident_by_number(
            mock_config, mock_auth, GetIncidentByNumberParams(count_only=True)
        )
        assert result["count"] == 42
        assert "incidents" not in result  # No records fetched

    def test_list_catalog_items_count_only(self, mock_config, mock_auth):
        from servicenow_mcp.tools.catalog_tools import ListCatalogItemsParams, list_catalog_items

        mock_auth.make_request.return_value = _mock_count_response(15)
        result = list_catalog_items(mock_config, mock_auth, ListCatalogItemsParams(count_only=True))
        assert result["count"] == 15
        assert "items" not in result and "results" not in result

    def test_list_users_count_only(self, mock_config, mock_auth):
        from servicenow_mcp.tools.user_tools import ListUsersParams, list_users

        mock_auth.make_request.return_value = _mock_count_response(200)
        result = list_users(mock_config, mock_auth, ListUsersParams(count_only=True))
        assert result["count"] == 200
        assert "users" not in result

    def test_list_workflows_count_only(self, mock_config, mock_auth):
        from servicenow_mcp.tools.workflow_tools import ListWorkflowsParams, list_workflows

        mock_auth.make_request.return_value = _mock_count_response(8)
        result = list_workflows(mock_config, mock_auth, ListWorkflowsParams(count_only=True))
        assert result["count"] == 8

    def test_list_script_includes_count_only(self, mock_config, mock_auth):
        from servicenow_mcp.tools.script_include_tools import (
            ListScriptIncludesParams,
            list_script_includes,
        )

        mock_auth.make_request.return_value = _mock_count_response(55)
        result = list_script_includes(
            mock_config, mock_auth, ListScriptIncludesParams(count_only=True)
        )
        assert result["count"] == 55

    def test_list_change_requests_count_only(self, mock_config, mock_auth):
        from servicenow_mcp.tools.change_tools import (
            GetChangeRequestDetailsParams,
            get_change_request_details,
        )

        mock_auth.make_request.return_value = _mock_count_response(3)
        result = get_change_request_details(
            mock_config, mock_auth, GetChangeRequestDetailsParams(count_only=True)
        )
        assert result["count"] == 3

    def test_list_portals_count_only(self, mock_config, mock_auth):
        from servicenow_mcp.tools.portal_management_tools import GetPortalParams, get_portal

        mock_auth.make_request.return_value = _mock_count_response(2)
        result = get_portal(mock_config, mock_auth, GetPortalParams(count_only=True))
        assert result["count"] == 2

    def test_list_changesets_count_only(self, mock_config, mock_auth):
        from servicenow_mcp.tools.changeset_tools import (
            GetChangesetDetailsParams,
            get_changeset_details,
        )

        mock_auth.make_request.return_value = _mock_count_response(7)
        result = get_changeset_details(
            mock_config, mock_auth, GetChangesetDetailsParams(count_only=True)
        )
        assert result["count"] == 7

    def test_count_only_makes_single_aggregate_api_call(self, mock_config, mock_auth):
        """count_only must use Aggregate API (stats), not Table API."""
        from servicenow_mcp.tools.incident_tools import (
            GetIncidentByNumberParams,
            get_incident_by_number,
        )

        mock_auth.make_request.return_value = _mock_count_response(10)
        get_incident_by_number(mock_config, mock_auth, GetIncidentByNumberParams(count_only=True))

        assert mock_auth.make_request.call_count == 1
        url = mock_auth.make_request.call_args[0][1]
        assert "/api/now/stats/" in url  # Aggregate API, not table API


# ============================================================================
# 2. Compact JSON serialization
# ============================================================================


class TestCompactSerialization:
    """Tool output must use compact JSON (no indent) to save tokens."""

    def test_serialize_tool_output_no_indent(self):
        from servicenow_mcp.server import serialize_tool_output

        data = {"success": True, "results": [{"sys_id": "abc", "name": "test"}]}
        output = serialize_tool_output(data, "test_tool")

        # Must not have indentation whitespace
        assert "\n" not in output
        assert "  " not in output  # No indent spaces

    def test_serialize_tool_output_preserves_data(self):
        from servicenow_mcp.server import serialize_tool_output

        data = {"success": True, "count": 5, "items": [1, 2, 3]}
        output = serialize_tool_output(data, "test_tool")
        parsed = json.loads(output)
        assert parsed == data


# ============================================================================
# 3. Conditional metadata
# ============================================================================


class TestConditionalMetadata:
    """Empty warnings, safety_notice, and scan_summary should be omitted."""

    def test_detection_tool_omits_empty_warnings(self, mock_config, mock_auth):
        from servicenow_mcp.tools.detection_tools import (
            DetectMissingCodesParams,
            detect_missing_profit_company_codes,
        )

        mock_auth.make_request.return_value = _mock_count_response(0)
        result = detect_missing_profit_company_codes(
            mock_config,
            mock_auth,
            DetectMissingCodesParams(
                required_codes=["2400", "5K00", "2J00"],
                widget_prefix="hopes",
            ),
        )
        # When no warnings, key should be absent
        assert result.get("warnings") is None or result.get("warnings") == []

    def test_search_regex_omits_empty_warnings_when_targeted(self, mock_config, mock_auth):
        """When widget_ids are targeted (no broad scan), warnings should be empty/absent."""
        from servicenow_mcp.tools.portal_tools import (
            SearchPortalRegexMatchesParams,
            search_portal_regex_matches,
        )

        with patch("servicenow_mcp.tools.portal_tools.sn_query_all") as mock_all:
            mock_all.return_value = []
            result = search_portal_regex_matches(
                mock_config,
                mock_auth,
                SearchPortalRegexMatchesParams(
                    regex="test",
                    widget_ids=["w1"],
                    source_types=["widget"],
                    max_widgets=10,
                    max_matches=10,
                ),
            )

        # With targeted widget_ids, no broad-scan warnings needed
        warnings = result.get("warnings", [])
        assert len(warnings) == 0 or "warnings" not in result
