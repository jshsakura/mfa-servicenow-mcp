from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.performance_tools import (
    AnalyzeWidgetPerformanceParams,
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


@patch("servicenow_mcp.tools.performance_tools.get_transaction_logs")
@patch("servicenow_mcp.tools.performance_tools.sn_query")
def test_analyze_widget_performance_handles_raw_provider_refs(
    mock_sn_query, mock_get_transaction_logs, mock_config, mock_auth_manager
):
    mock_get_transaction_logs.return_value = {"success": True, "results": []}
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
