"""
Red-green tests for Batch API, parallel portal_tools, lazy loading, and dynamic paging.
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


# ============================================================================
# 1. Batch API
# ============================================================================


class TestBatchAPI:
    """Tests for ServiceNow Batch API helper."""

    def test_sn_batch_combines_multiple_queries_into_one_http_call(self, mock_config, mock_auth):
        """Batch helper must send a single POST to /api/now/batch with multiple
        serviced_requests, and return parsed results per sub-request."""
        from servicenow_mcp.tools.core_plus import sn_batch

        # Mock response: batch endpoint returns an array of sub-responses
        batch_response = MagicMock()
        batch_response.status_code = 200
        batch_response.content = json.dumps(
            {
                "serviced_requests": [
                    {
                        "id": "req1",
                        "status_code": 200,
                        "body": {"result": [{"sys_id": "w1", "name": "Widget A"}]},
                    },
                    {
                        "id": "req2",
                        "status_code": 200,
                        "body": {"result": [{"sp_angular_provider": {"value": "p1"}}]},
                    },
                ]
            }
        ).encode()
        batch_response.headers = {}
        mock_auth.make_request.return_value = batch_response

        requests = [
            {
                "id": "req1",
                "method": "GET",
                "url": "/api/now/table/sp_widget?sysparm_limit=10&sysparm_fields=sys_id,name",
            },
            {
                "id": "req2",
                "method": "GET",
                "url": "/api/now/table/m2m_sp_widget_angular_provider?sysparm_query=sp_widgetINw1",
            },
        ]

        results = sn_batch(mock_config, mock_auth, requests=requests)

        # Must be a single HTTP call
        assert mock_auth.make_request.call_count == 1
        call_args = mock_auth.make_request.call_args
        assert call_args[0][0] == "POST"
        assert "/api/now/batch" in call_args[0][1]

        # Results keyed by request id
        assert "req1" in results
        assert "req2" in results
        assert results["req1"]["result"][0]["name"] == "Widget A"
        assert results["req2"]["result"][0]["sp_angular_provider"]["value"] == "p1"

    def test_sn_batch_handles_partial_failure(self, mock_config, mock_auth):
        """If one sub-request fails, batch must still return successes and mark failures."""
        from servicenow_mcp.tools.core_plus import sn_batch

        batch_response = MagicMock()
        batch_response.status_code = 200
        batch_response.content = json.dumps(
            {
                "serviced_requests": [
                    {
                        "id": "ok",
                        "status_code": 200,
                        "body": {"result": [{"sys_id": "1"}]},
                    },
                    {
                        "id": "fail",
                        "status_code": 404,
                        "body": {"error": {"message": "not found"}},
                    },
                ]
            }
        ).encode()
        batch_response.headers = {}
        mock_auth.make_request.return_value = batch_response

        results = sn_batch(
            mock_config,
            mock_auth,
            requests=[
                {"id": "ok", "method": "GET", "url": "/api/now/table/sp_widget"},
                {"id": "fail", "method": "GET", "url": "/api/now/table/nonexistent"},
            ],
        )

        assert results["ok"]["result"][0]["sys_id"] == "1"
        assert results["fail"].get("error") is not None

    def test_sn_batch_empty_requests_returns_empty(self, mock_config, mock_auth):
        """Empty request list should return empty dict without making API call."""
        from servicenow_mcp.tools.core_plus import sn_batch

        results = sn_batch(mock_config, mock_auth, requests=[])
        assert results == {}
        assert mock_auth.make_request.call_count == 0

    def test_sn_batch_chunks_large_request_lists(self, mock_config, mock_auth):
        """Batch API has limits (~150 requests). Helper must chunk automatically."""
        from servicenow_mcp.tools.core_plus import SN_BATCH_MAX_REQUESTS, sn_batch

        # Create more requests than the limit
        many_requests = [
            {"id": f"r{i}", "method": "GET", "url": f"/api/now/table/sp_widget?i={i}"}
            for i in range(SN_BATCH_MAX_REQUESTS + 5)
        ]

        def _mock_batch_response(*args, **kwargs):
            body = kwargs.get("json") or (args[2] if len(args) > 2 else {})
            resp = MagicMock()
            resp.status_code = 200
            sub_responses = [
                {"id": r["id"], "status_code": 200, "body": {"result": []}}
                for r in body.get("rest_requests", [])
            ]
            resp.content = json.dumps({"serviced_requests": sub_responses}).encode()
            resp.headers = {}
            return resp

        mock_auth.make_request.side_effect = _mock_batch_response

        results = sn_batch(mock_config, mock_auth, requests=many_requests)

        # Should have made 2 HTTP calls (chunked)
        assert mock_auth.make_request.call_count == 2
        # All request IDs should be in results
        assert len(results) == SN_BATCH_MAX_REQUESTS + 5


# ============================================================================
# 2. Portal tools parallel migration
# ============================================================================


class TestPortalToolsParallel:
    """Tests verifying portal_tools uses parallel sn_query_all."""

    def test_search_portal_regex_matches_uses_parallel_fetch(self, mock_config, mock_auth):
        """search_portal_regex_matches must call sn_query_page (not sn_query)
        for widget fetching, proving it uses the parallel path."""
        from servicenow_mcp.tools.portal_tools import (
            SearchPortalRegexMatchesParams,
            search_portal_regex_matches,
        )

        widget_data = [
            {
                "sys_id": "w1",
                "name": "TestWidget",
                "id": "test_widget",
                "script": "var url = '/sp?id=test';",
                "template": "",
                "client_script": "",
            }
        ]

        with patch("servicenow_mcp.tools.portal_tools.sn_query_all") as mock_all:
            mock_all.return_value = widget_data
            result = search_portal_regex_matches(
                mock_config,
                mock_auth,
                SearchPortalRegexMatchesParams(
                    regex="/sp",
                    source_types=["widget"],
                    include_widget_fields=["script"],
                    max_widgets=10,
                    max_matches=10,
                ),
            )

        assert result["success"] is True
        assert result["scan_summary"]["widgets_scanned"] == 1
        mock_all.assert_called_once()

    def test_detect_angular_implicit_globals_uses_parallel_fetch(self, mock_config, mock_auth):
        """detect_angular_implicit_globals must use sn_query_all for provider fetching."""
        from servicenow_mcp.tools.portal_tools import (
            DetectAngularImplicitGlobalsParams,
            detect_angular_implicit_globals,
        )

        provider_data = [
            {
                "sys_id": "p1",
                "name": "TestProvider",
                "id": "test_prov",
                "script": "undeclaredVar = 42;",
            }
        ]

        with patch("servicenow_mcp.tools.portal_tools.sn_query_all") as mock_all:
            mock_all.return_value = provider_data
            result = detect_angular_implicit_globals(
                mock_config,
                mock_auth,
                DetectAngularImplicitGlobalsParams(max_providers=10, max_matches=10),
            )

        assert result["success"] is True
        mock_all.assert_called_once()


# ============================================================================
# 3. Lazy tool loading
# ============================================================================


class TestLazyToolLoading:
    """Tests verifying lazy tool module import."""

    def test_discover_tools_only_imports_requested_modules(self):
        """When tool package restricts to a few tools, only those modules load."""
        from servicenow_mcp.utils.registry import discover_tools_lazy

        # Request only core tools (should not import workflow_tools, etc.)
        registry = discover_tools_lazy(enabled_names={"sn_health", "sn_query", "sn_aggregate"})

        assert "sn_health" in registry
        assert "sn_query" in registry
        assert "sn_aggregate" in registry
        # Tools from other modules should NOT be loaded
        assert "create_workflow" not in registry
        assert "create_incident" not in registry

    def test_discover_tools_lazy_returns_same_format_as_discover_tools(self):
        """Lazy discovery must return the same registry format as eager discovery."""
        from servicenow_mcp.utils.registry import discover_tools, discover_tools_lazy

        eager = discover_tools()
        # Pick a subset
        subset = {"sn_health", "sn_query", "list_incidents"}
        lazy = discover_tools_lazy(enabled_names=subset)

        for name in subset:
            assert name in lazy, f"{name} missing from lazy registry"
            # Same tuple structure: (impl, params, ret_type, desc, serialization)
            assert len(lazy[name]) == len(eager[name])
            assert lazy[name][3] == eager[name][3]  # Same description


# ============================================================================
# 4. Dynamic page_size adjustment
# ============================================================================


class TestDynamicPaging:
    """Tests for dynamic page_size optimization in sn_query_all."""

    def test_small_dataset_fetched_in_single_page(self, mock_config, mock_auth):
        """When total_count <= page_size, no subsequent pages should be fetched."""
        from servicenow_mcp.tools.core_plus import sn_query_all

        # 3 records total, page_size=50 — should fetch once and done
        with patch("servicenow_mcp.tools.core_plus.sn_query_page") as mock_page:
            mock_page.return_value = (
                [{"sys_id": f"r{i}"} for i in range(3)],
                3,  # total_count = 3
            )
            rows = sn_query_all(
                mock_config,
                mock_auth,
                table="sp_widget",
                query="",
                fields="sys_id",
                page_size=50,
                max_records=100,
            )

        assert len(rows) == 3
        assert mock_page.call_count == 1  # Single page, no more

    def test_large_dataset_uses_enlarged_page_for_remaining(self, mock_config, mock_auth):
        """When remaining records fit in one enlarged page (<=100), fetch them
        in a single request instead of multiple small pages."""
        from servicenow_mcp.tools.core_plus import sn_query_all

        # total=80, first page fetches 20 (page_size=20), remaining=60
        # 60 fits in one page (<=100), so should enlarge to 60 instead of 3x20
        first_page = ([{"sys_id": f"r{i}"} for i in range(20)], 80)
        remaining_page = ([{"sys_id": f"r{i}"} for i in range(20, 80)], 80)

        call_count = 0

        def _mock_page(config, auth, *, table, query, fields, limit, offset, **kw):
            nonlocal call_count
            call_count += 1
            if offset == 0:
                return first_page
            else:
                # The remaining page should request limit=60 (all remaining)
                assert limit == 60, f"Expected dynamic limit=60, got {limit}"
                return remaining_page

        with patch("servicenow_mcp.tools.core_plus.sn_query_page", side_effect=_mock_page):
            rows = sn_query_all(
                mock_config,
                mock_auth,
                table="sp_widget",
                query="",
                fields="sys_id",
                page_size=20,
                max_records=100,
            )

        assert len(rows) == 80
        assert call_count == 2  # first page + one enlarged remaining page

    def test_page_size_never_exceeds_100(self, mock_config, mock_auth):
        """Dynamic page enlargement must never exceed ServiceNow's 100 limit."""
        from servicenow_mcp.tools.core_plus import sn_query_all

        # total=500, page_size=20 → remaining=480 → cannot enlarge beyond 100
        first_page = ([{"sys_id": f"r{i}"} for i in range(20)], 500)

        limits_seen = []

        def _mock_page(config, auth, *, table, query, fields, limit, offset, **kw):
            limits_seen.append(limit)
            if offset == 0:
                return first_page
            return ([{"sys_id": f"r{offset + i}"} for i in range(limit)], 500)

        with patch("servicenow_mcp.tools.core_plus.sn_query_page", side_effect=_mock_page):
            rows = sn_query_all(
                mock_config,
                mock_auth,
                table="sp_widget",
                query="",
                fields="sys_id",
                page_size=20,
                max_records=100,
            )

        assert len(rows) == 100
        # No limit should exceed 100
        assert all(lim <= 100 for lim in limits_seen), f"Limits exceeded 100: {limits_seen}"
