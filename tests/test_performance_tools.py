from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.performance_tools import (
    AnalyzeWidgetPerformanceParams,
    _fetch_angular_providers,
    analyze_widget_performance,
)
from servicenow_mcp.utils.config import ServerConfig


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth_manager():
    return MagicMock()


@patch("servicenow_mcp.tools.performance_tools.get_logs")
@patch("servicenow_mcp.tools.performance_tools.sn_query")
def test_analyze_widget_performance_handles_raw_provider_refs(
    mock_sn_query, mock_get_logs, mock_config, mock_auth_manager
):
    mock_get_logs.return_value = {"success": True, "results": []}
    mock_sn_query.side_effect = [
        {
            "success": True,
            "results": [
                {
                    "sys_id": "wid-1",
                    "name": "Budget Widget",
                    "id": "budget_widget",
                    "script": "var gr = new GlideRecord('task');",
                    "client_script": "function onLoad() { return true; }",
                }
            ],
        },
        {
            "success": True,
            "results": [{"sp_angular_provider": "prov-1"}],
        },
        {
            "success": True,
            "results": [
                {
                    "sys_id": "prov-1",
                    "name": "budgetProvider",
                    "script": "function resolveBudgetRoute(){ return '/sp?id=budget'; }",
                }
            ],
        },
    ]

    result = analyze_widget_performance(
        mock_config,
        mock_auth_manager,
        AnalyzeWidgetPerformanceParams(
            widget_id="budget_widget",
            analysis_depth="standard",
            include_angular_providers=True,
            include_script_includes=False,
        ),
    )

    assert result["success"] is True
    assert result["summary"]["sources_analyzed"] == 3
    assert "sp_angular_provider/budgetProvider" in result["report"]["sources_analyzed"]


class TestUnreadProvidersAreNotReportedAsNone:
    """ "No providers" and "could not look" are different answers.

    This fetched the junction table by a hardcoded name. m2m table names are not
    uniform across releases, so on instances using the other spelling the read
    400s — and the failure collapsed into `[]`, which the report presented as a
    result. Measured live on a widget with eight provider links: zero found, no
    warning, "No significant performance issues detected", and the provider
    scripts never read. One of them was 9,690 bytes.

    So the junction table is discovered rather than assumed, and the fetch says
    why a list is short instead of leaving the caller to assume it is complete.
    """

    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    @patch("servicenow_mcp.tools.portal_dev_tools.resolve_angular_provider_m2m")
    def test_an_unreadable_junction_table_is_a_reason_not_an_empty_list(
        self, mock_resolve, mock_query
    ):
        mock_resolve.return_value = "m2m_whatever"
        mock_query.return_value = {"success": False, "message": "Invalid table"}

        providers, reason = _fetch_angular_providers(MagicMock(), MagicMock(), "w1")

        assert providers == []
        assert reason and "m2m_whatever" in reason and "Invalid table" in reason

    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    @patch("servicenow_mcp.tools.portal_dev_tools.resolve_angular_provider_m2m")
    def test_a_widget_with_no_providers_reports_no_reason(self, mock_resolve, mock_query):
        """Genuinely none must stay distinguishable from not-checked."""
        mock_resolve.return_value = "m2m_whatever"
        mock_query.return_value = {"success": True, "results": []}

        providers, reason = _fetch_angular_providers(MagicMock(), MagicMock(), "w1")

        assert providers == []
        assert reason is None

    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    @patch("servicenow_mcp.tools.portal_dev_tools.resolve_angular_provider_m2m")
    def test_the_discovered_table_is_used_not_a_hardcoded_name(self, mock_resolve, mock_query):
        mock_resolve.return_value = "m2m_sp_ng_pro_sp_widget"
        mock_query.return_value = {"success": True, "results": []}

        _fetch_angular_providers(MagicMock(), MagicMock(), "w1")

        assert mock_query.call_args.args[2].table == "m2m_sp_ng_pro_sp_widget"

    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    @patch("servicenow_mcp.tools.portal_dev_tools.resolve_angular_provider_m2m")
    def test_columnar_rows_are_decoded(self, mock_resolve, mock_query):
        """The junction read is limit=50; three rows already switch the shape."""
        from servicenow_mcp.tools.sn_api import to_columnar

        mock_resolve.return_value = "m2m"
        rows = [{"sp_angular_provider": f"p{i}"} for i in range(3)]
        mock_query.side_effect = [
            {"success": True, "format": "columnar", "results": to_columnar(rows)},
            {"success": True, "results": [{"sys_id": "p0", "name": "prov", "script": "x"}]},
        ]

        providers, reason = _fetch_angular_providers(MagicMock(), MagicMock(), "w1")

        assert reason is None
        assert [p["name"] for p in providers] == ["prov"]
