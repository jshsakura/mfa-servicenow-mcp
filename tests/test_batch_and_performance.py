"""
Red-green tests for Batch API, parallel portal_tools, lazy loading, and dynamic paging.
"""

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
        subset = {"sn_health", "sn_query", "manage_incident"}
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
        from servicenow_mcp.tools.sn_api import sn_query_all

        # 3 records total, page_size=50 — should fetch once and done
        with patch("servicenow_mcp.tools.sn_api.sn_query_page") as mock_page:
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
        from servicenow_mcp.tools.sn_api import sn_query_all

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

        with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=_mock_page):
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
        from servicenow_mcp.tools.sn_api import sn_query_all

        # total=500, page_size=20 → remaining=480 → cannot enlarge beyond 100
        first_page = ([{"sys_id": f"r{i}"} for i in range(20)], 500)

        limits_seen = []

        def _mock_page(config, auth, *, table, query, fields, limit, offset, **kw):
            limits_seen.append(limit)
            if offset == 0:
                return first_page
            return ([{"sys_id": f"r{offset + i}"} for i in range(limit)], 500)

        with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=_mock_page):
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


# ============================================================================
# 5. Parallel pagination failure handling
# ============================================================================


class TestParallelPageFailureHandling:
    """sn_query_all's parallel path must not silently truncate results when a
    middle page is dropped, and must surface errors when fail_silently=False.

    Setup note: page_size=50 + max_records=300 forces server_remaining=250
    (>100), so dynamic_size stays at the page size and the fetch fans out to
    parallel offsets [50, 100, 150, 200, 250] — the regime where a mid-range
    page failure can strand the pages that follow it.
    """

    TOTAL = 300
    PAGE = 50
    FAIL_OFFSET = 150  # a true middle page (not first, not last)

    def _first_page(self):
        return ([{"sys_id": f"r{i}"} for i in range(self.PAGE)], self.TOTAL)

    def test_transient_mid_page_failure_recovered_by_retry(self, mock_config, mock_auth):
        """A page that comes back empty in the parallel fan-out is retried once
        sequentially; if the retry succeeds, no rows are lost."""
        from servicenow_mcp.tools.sn_api import sn_query_all

        calls = {}

        def _mock_page(
            config, auth, *, table, query, fields, limit, offset, fail_silently=True, **kw
        ):
            calls[offset] = calls.get(offset, 0) + 1
            if offset == 0:
                return self._first_page()
            # First (parallel) hit on the failing offset drops the page; the
            # sequential retry on the same offset then succeeds.
            if offset == self.FAIL_OFFSET and calls[offset] == 1:
                return ([], None)
            return ([{"sys_id": f"r{offset + i}"} for i in range(limit)], None)

        with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=_mock_page):
            rows = sn_query_all(
                mock_config,
                mock_auth,
                table="sp_widget",
                query="",
                fields="sys_id",
                page_size=self.PAGE,
                max_records=self.TOTAL,
            )

        assert len(rows) == self.TOTAL  # nothing truncated by the transient miss
        assert calls[self.FAIL_OFFSET] == 2  # one parallel attempt + one retry

    def test_page_error_propagates_when_not_fail_silently(self, mock_config, mock_auth):
        """With fail_silently=False, an error on any parallel page must reach the
        caller instead of being swallowed into an empty (end-of-data) page."""
        from servicenow_mcp.tools.sn_api import sn_query_all

        def _mock_page(
            config, auth, *, table, query, fields, limit, offset, fail_silently=True, **kw
        ):
            if offset == 0:
                return self._first_page()
            if offset == self.FAIL_OFFSET:
                # Mirror real sn_query_page: raise when the caller wants errors.
                if not fail_silently:
                    raise RuntimeError("boom at 150")
                return ([], None)
            return ([{"sys_id": f"r{offset + i}"} for i in range(limit)], None)

        with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=_mock_page):
            with pytest.raises(RuntimeError, match="boom at 150"):
                sn_query_all(
                    mock_config,
                    mock_auth,
                    table="sp_widget",
                    query="",
                    fields="sys_id",
                    page_size=self.PAGE,
                    max_records=self.TOTAL,
                    fail_silently=False,
                )

    def test_permanent_mid_page_failure_truncates_at_gap_and_warns(
        self, mock_config, mock_auth, caplog
    ):
        """If a middle page is still empty after retry (fail_silently=True), the
        merge stops at the gap — it must never splice in the later pages as if
        the data were contiguous — and it logs a truncation warning."""
        from servicenow_mcp.tools.sn_api import sn_query_all

        def _mock_page(
            config, auth, *, table, query, fields, limit, offset, fail_silently=True, **kw
        ):
            if offset == 0:
                return self._first_page()
            if offset == self.FAIL_OFFSET:
                return ([], None)  # empty on both the parallel hit and the retry
            return ([{"sys_id": f"r{offset + i}"} for i in range(limit)], None)

        with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=_mock_page):
            with caplog.at_level("WARNING"):
                rows = sn_query_all(
                    mock_config,
                    mock_auth,
                    table="sp_widget",
                    query="",
                    fields="sys_id",
                    page_size=self.PAGE,
                    max_records=self.TOTAL,
                )

        # Contiguous prefix only: offsets 0, 50, 100 = 150 rows. The 200/250
        # pages must NOT be appended over the gap at 150.
        assert len(rows) == 150
        assert any("truncated" in r.getMessage() for r in caplog.records)

    def test_clean_parallel_fetch_does_no_extra_retry(self, mock_config, mock_auth):
        """Regression: when every page succeeds, the retry path is never taken —
        each offset is fetched exactly once."""
        from servicenow_mcp.tools.sn_api import sn_query_all

        calls = {}

        def _mock_page(
            config, auth, *, table, query, fields, limit, offset, fail_silently=True, **kw
        ):
            calls[offset] = calls.get(offset, 0) + 1
            if offset == 0:
                return self._first_page()
            return ([{"sys_id": f"r{offset + i}"} for i in range(limit)], None)

        with patch("servicenow_mcp.tools.sn_api.sn_query_page", side_effect=_mock_page):
            rows = sn_query_all(
                mock_config,
                mock_auth,
                table="sp_widget",
                query="",
                fields="sys_id",
                page_size=self.PAGE,
                max_records=self.TOTAL,
            )

        assert len(rows) == self.TOTAL
        assert all(count == 1 for count in calls.values()), f"unexpected retries: {calls}"
