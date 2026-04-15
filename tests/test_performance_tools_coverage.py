"""
Additional tests for performance_tools to increase coverage to 80%+.

Covers: _extract_script_references, _detect_patterns edge cases,
_analyze_transaction_logs branches, _fetch_widget_bundle not found,
_fetch_angular_providers failure paths, deep analysis with script includes,
recommendation generation branches, and widget-not-found path.
"""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.performance_tools import (
    AnalyzeWidgetPerformanceParams,
    _analyze_transaction_logs,
    _detect_patterns,
    _extract_script_references,
    _fetch_angular_providers,
    _fetch_widget_bundle,
    analyze_widget_performance,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


@pytest.fixture
def config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture
def auth():
    return MagicMock()


# ---------------------------------------------------------------------------
# _extract_script_references
# ---------------------------------------------------------------------------


class TestExtractScriptReferences:
    def test_empty_script(self):
        """Cover line 174-175: empty string returns empty set."""
        assert _extract_script_references("") == set()
        assert _extract_script_references(None) == set()

    def test_extracts_custom_classes(self):
        """Cover lines 177-179: finds class references, ignores built-ins."""
        script = "var x = new MyHelper(); var gr = new GlideRecord('task');"
        refs = _extract_script_references(script)
        assert "MyHelper" in refs
        assert "GlideRecord" not in refs

    def test_ignores_global_prefix(self):
        script = "var x = new global.CustomUtil();"
        refs = _extract_script_references(script)
        assert "CustomUtil" in refs


# ---------------------------------------------------------------------------
# _detect_patterns
# ---------------------------------------------------------------------------


class TestDetectPatterns:
    def test_empty_script(self):
        """Cover line 185: empty script returns []."""
        assert _detect_patterns("", "test") == []
        assert _detect_patterns(None, "test") == []

    def test_detects_glide_record_loop(self):
        """Cover lines 194-213: pattern detection with line numbers and snippets."""
        script = """var gr = new GlideRecord('task');
gr.query();
while (gr.next()) {
    gs.log(gr.number);
}"""
        patterns = _detect_patterns(script, "widget/test/script")
        assert len(patterns) > 0
        found_types = [p.pattern_type for p in patterns]
        assert "glide_record_loop" in found_types

    def test_snippet_truncation(self):
        """Cover line 198-199: snippet > 200 chars gets truncated."""
        # Build a script with a very long line around a pattern match
        long_line = "x" * 250
        script = f"{long_line}\nwhile (gr.next()) {{\n{long_line}\n}}"
        patterns = _detect_patterns(script, "test_source")
        for p in patterns:
            if p.snippet and len(p.snippet) > 200:
                assert p.snippet.endswith("...")


# ---------------------------------------------------------------------------
# _analyze_transaction_logs
# ---------------------------------------------------------------------------


class TestAnalyzeTransactionLogs:
    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    def test_logs_not_successful(self, mock_get_logs, config, auth):
        """Cover line 250: log_result not successful."""
        mock_get_logs.return_value = {"success": False}
        result = _analyze_transaction_logs(config, auth, "wid1", None, 3000, "last_7d")
        assert result["count"] == 0

    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    def test_empty_transactions(self, mock_get_logs, config, auth):
        """Cover line 253-254: empty results."""
        mock_get_logs.return_value = {"success": True, "results": []}
        result = _analyze_transaction_logs(config, auth, "wid1", None, 3000, "last_7d")
        assert result["count"] == 0

    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    def test_with_page_id(self, mock_get_logs, config, auth):
        """Cover line 234: page_id present."""
        mock_get_logs.return_value = {
            "success": True,
            "results": [
                {
                    "response_time": "5000",
                    "url": "/sp",
                    "response_status": "200",
                    "sys_created_on": "2025-01-01",
                    "sys_created_by": "admin",
                },
            ],
        }
        result = _analyze_transaction_logs(config, auth, "wid1", "page1", 3000, "last_7d")
        assert result["count"] == 1
        assert result["avg_response_time"] == 5000.0

    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    def test_invalid_response_time_skipped(self, mock_get_logs, config, auth):
        """Cover lines 261-263: ValueError/TypeError on response_time."""
        mock_get_logs.return_value = {
            "success": True,
            "results": [
                {"response_time": "not_a_number", "url": "/sp"},
                {"response_time": None, "url": "/sp"},
                {
                    "response_time": "1000",
                    "url": "/sp",
                    "response_status": "200",
                    "sys_created_on": "2025-01-01",
                    "sys_created_by": "admin",
                },
            ],
        }
        result = _analyze_transaction_logs(config, auth, "wid1", None, 500, "last_7d")
        assert result["count"] == 1
        assert result["avg_response_time"] == 1000.0


# ---------------------------------------------------------------------------
# _fetch_widget_bundle
# ---------------------------------------------------------------------------


class TestFetchWidgetBundle:
    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_not_found(self, mock_sn_query, config, auth):
        """Cover line 304: widget not found returns {}."""
        mock_sn_query.return_value = {"success": True, "results": []}
        result = _fetch_widget_bundle(config, auth, "nonexistent")
        assert result == {}

    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_query_failure(self, mock_sn_query, config, auth):
        """Cover line 303: success=False."""
        mock_sn_query.return_value = {"success": False}
        result = _fetch_widget_bundle(config, auth, "wid1")
        assert result == {}


# ---------------------------------------------------------------------------
# _fetch_angular_providers
# ---------------------------------------------------------------------------


class TestFetchAngularProviders:
    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_m2m_query_failure(self, mock_sn_query, config, auth):
        """Cover line 328: m2m query not successful."""
        mock_sn_query.return_value = {"success": False}
        result = _fetch_angular_providers(config, auth, "wid1")
        assert result == []

    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_no_provider_refs(self, mock_sn_query, config, auth):
        """Cover line 341: empty provider refs."""
        mock_sn_query.return_value = {"success": True, "results": []}
        result = _fetch_angular_providers(config, auth, "wid1")
        assert result == []

    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_provider_query_failure(self, mock_sn_query, config, auth):
        """Cover line 355: provider query not successful."""
        mock_sn_query.side_effect = [
            {
                "success": True,
                "results": [{"sp_angular_provider": {"value": "prov1"}}],
            },
            {"success": False},
        ]
        result = _fetch_angular_providers(config, auth, "wid1")
        assert result == []


# ---------------------------------------------------------------------------
# analyze_widget_performance (integration-level)
# ---------------------------------------------------------------------------


class TestAnalyzeWidgetPerformance:
    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_widget_not_found(self, mock_sn_query, mock_get_logs, config, auth):
        """Cover lines 403-404: widget not found returns error report."""
        mock_get_logs.return_value = {"success": True, "results": []}
        mock_sn_query.return_value = {"success": True, "results": []}
        result = analyze_widget_performance(
            config,
            auth,
            AnalyzeWidgetPerformanceParams(widget_id="nonexistent"),
        )
        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("servicenow_mcp.tools.performance_tools.get_metadata_source")
    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_deep_analysis_with_script_includes(
        self, mock_sn_query, mock_get_logs, mock_get_metadata, config, auth
    ):
        """Cover lines 437-456: deep analysis fetches script includes."""
        mock_get_logs.return_value = {"success": True, "results": []}
        mock_sn_query.side_effect = [
            # widget bundle
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "wid1",
                        "name": "TestWidget",
                        "id": "test_widget",
                        "script": "var h = new MyHelper(); h.doStuff();",
                        "client_script": "",
                    }
                ],
            },
            # m2m angular providers (empty)
            {"success": True, "results": []},
        ]
        mock_get_metadata.return_value = {"script": "var gr = new GlideRecord('task'); gr.query();"}

        result = analyze_widget_performance(
            config,
            auth,
            AnalyzeWidgetPerformanceParams(
                widget_id="wid1",
                analysis_depth="deep",
                include_script_includes=True,
                include_angular_providers=True,
            ),
        )
        assert result["success"] is True
        assert any("sys_script_include" in s for s in result["report"]["sources_analyzed"])

    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_recommendations_with_slow_transactions_and_critical(
        self, mock_sn_query, mock_get_logs, config, auth
    ):
        """Cover lines 460, 469, 478-482, 485, 491-494: recommendation branches."""
        # Return many slow transactions
        mock_get_logs.return_value = {
            "success": True,
            "results": [
                {
                    "response_time": "5000",
                    "url": "/sp",
                    "response_status": "200",
                    "sys_created_on": "2025-01-01",
                    "sys_created_by": "admin",
                }
                for _ in range(10)
            ],
        }
        # Widget with AJAX-in-loop (critical) and nested GR (high)
        script = """
for (var i = 0; i < 10; i++) {
    var ajax = new GlideAjax('MyUtil');
}
var gr = new GlideRecord('task');
var gr = new GlideRecord('incident');
"""
        mock_sn_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "wid1",
                    "name": "SlowWidget",
                    "id": "slow_widget",
                    "script": script,
                    "client_script": "",
                }
            ],
        }

        result = analyze_widget_performance(
            config,
            auth,
            AnalyzeWidgetPerformanceParams(
                widget_id="wid1",
                analysis_depth="quick",
                include_angular_providers=False,
                include_script_includes=False,
            ),
        )
        assert result["success"] is True
        report = result["report"]
        assert report["slow_transactions_count"] == 10
        # Should have recommendations for slow txns
        recs = report["recommendations"]
        assert any("slow transactions" in r for r in recs)

    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_no_patterns_recommendation(self, mock_sn_query, mock_get_logs, config, auth):
        """Cover line 496-497: no patterns found yields 'no issues' recommendation."""
        mock_get_logs.return_value = {"success": True, "results": []}
        mock_sn_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "wid1",
                    "name": "CleanWidget",
                    "id": "clean_widget",
                    "script": "// clean script",
                    "client_script": "",
                }
            ],
        }
        result = analyze_widget_performance(
            config,
            auth,
            AnalyzeWidgetPerformanceParams(
                widget_id="wid1",
                analysis_depth="quick",
                include_angular_providers=False,
                include_script_includes=False,
            ),
        )
        assert result["success"] is True
        recs = result["report"]["recommendations"]
        assert any("No significant" in r for r in recs)

    @patch("servicenow_mcp.tools.performance_tools.get_metadata_source")
    @patch("servicenow_mcp.tools.performance_tools.get_logs")
    @patch("servicenow_mcp.tools.performance_tools.sn_query")
    def test_script_include_returns_none(
        self, mock_sn_query, mock_get_logs, mock_get_metadata, config, auth
    ):
        """Cover line 452: si_result has no script key."""
        mock_get_logs.return_value = {"success": True, "results": []}
        mock_sn_query.side_effect = [
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "wid1",
                        "name": "TestWidget",
                        "script": "var h = new CustomUtil();",
                        "client_script": "",
                    }
                ],
            },
            {"success": True, "results": []},  # angular providers
        ]
        mock_get_metadata.return_value = {"name": "CustomUtil"}  # no "script" key

        result = analyze_widget_performance(
            config,
            auth,
            AnalyzeWidgetPerformanceParams(
                widget_id="wid1",
                analysis_depth="deep",
                include_script_includes=True,
                include_angular_providers=True,
            ),
        )
        assert result["success"] is True
        # Should NOT have sys_script_include in sources since script was missing
        assert not any("sys_script_include" in s for s in result["report"]["sources_analyzed"])
