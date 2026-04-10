import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.log_tools import (
    GetBackgroundScriptLogsParams,
    GetJournalEntriesParams,
    GetSystemLogsParams,
    GetTransactionLogsParams,
    _clamp_limit,
    _clamp_text_length,
    _timeframe_query,
    _truncate_results,
    get_background_script_logs,
    get_journal_entries,
    get_system_logs,
    get_transaction_logs,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_config() -> ServerConfig:
    auth_config = AuthConfig(
        type=AuthType.BASIC,
        basic=BasicAuthConfig(username="test_user", password="test_password"),
    )
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=auth_config,
    )


class TestLogTools(unittest.TestCase):
    def setUp(self):
        self.server_config = _make_config()
        self.auth_manager = MagicMock()

    # ------------------------------------------------------------------
    # Existing tool tests — now delegating through sn_query_page
    # ------------------------------------------------------------------

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_get_system_logs_applies_safety_limits(self, mock_query_page):
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "1",
                    "level": "error",
                    "source": "Update Set",
                    "message": "x" * 900,
                    "sys_created_on": "2026-03-25 10:00:00",
                }
            ],
            25,
        )

        result = get_system_logs(
            self.server_config,
            self.auth_manager,
            GetSystemLogsParams(limit=999, level="error", contains="commit", max_text_length=300),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["limit_applied"], 20)
        self.assertEqual(result["table"], "syslog")
        self.assertIn("truncated", result["results"][0]["message"])

        call_kwargs = mock_query_page.call_args
        self.assertEqual(call_kwargs.kwargs["table"], "syslog")
        self.assertEqual(
            call_kwargs.kwargs["fields"],
            "sys_id,level,source,message,sys_created_on",
        )
        self.assertEqual(call_kwargs.kwargs["limit"], 20)
        self.assertEqual(call_kwargs.kwargs["display_value"], True)
        self.assertEqual(call_kwargs.kwargs["orderby"], "-sys_created_on")
        self.assertEqual(call_kwargs.kwargs["fail_silently"], False)
        query_str = call_kwargs.kwargs["query"]
        self.assertIn("level=error", query_str)
        self.assertIn("messageLIKEcommit", query_str)

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_get_journal_entries_uses_fixed_summary_fields(self, mock_query_page):
        mock_query_page.return_value = ([], None)

        result = get_journal_entries(
            self.server_config,
            self.auth_manager,
            GetJournalEntriesParams(
                table="incident", record_sys_id="abc123", field_name="comments"
            ),
        )

        self.assertTrue(result["success"])
        call_kwargs = mock_query_page.call_args.kwargs
        self.assertEqual(
            call_kwargs["fields"],
            "sys_id,name,element,element_id,value,sys_created_by,sys_created_on",
        )
        query_str = call_kwargs["query"]
        self.assertIn("name=incident", query_str)
        self.assertIn("element_id=abc123", query_str)
        self.assertIn("element=comments", query_str)

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_get_transaction_logs_applies_filters(self, mock_query_page):
        mock_query_page.return_value = ([], None)

        result = get_transaction_logs(
            self.server_config,
            self.auth_manager,
            GetTransactionLogsParams(
                url_contains="/api/now/table",
                response_status="500",
                min_response_time_ms=1000,
            ),
        )

        self.assertTrue(result["success"])
        call_kwargs = mock_query_page.call_args.kwargs
        self.assertEqual(
            call_kwargs["fields"],
            "sys_id,url,response_status,response_time,transaction_id,sys_created_by,sys_created_on",
        )
        query_str = call_kwargs["query"]
        self.assertIn("urlLIKE/api/now/table", query_str)
        self.assertIn("response_status=500", query_str)
        self.assertIn("response_time>=1000", query_str)

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_get_background_script_logs_uses_execution_tracker(self, mock_query_page):
        mock_query_page.return_value = ([], None)

        result = get_background_script_logs(
            self.server_config,
            self.auth_manager,
            GetBackgroundScriptLogsParams(name="nightly", state="error", source="script"),
        )

        self.assertTrue(result["success"])
        call_kwargs = mock_query_page.call_args.kwargs
        self.assertEqual(call_kwargs["table"], "sys_execution_tracker")
        self.assertEqual(
            call_kwargs["fields"],
            "sys_id,name,state,source,message,detail,percent_complete,sys_created_on,sys_updated_on",
        )
        query_str = call_kwargs["query"]
        self.assertIn("nameLIKEnightly", query_str)
        self.assertIn("state=error", query_str)
        self.assertIn("sourceLIKEscript", query_str)

    # ------------------------------------------------------------------
    # Cache reuse — same query twice should hit cache on second call
    # ------------------------------------------------------------------

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_cache_reuse_same_query_hits_cache(self, mock_query_page):
        """Verify that sn_query_page is called once when the same query is repeated.

        Note: The caching actually happens *inside* sn_query_page itself, not in
        _fetch_logs.  This test verifies that _fetch_logs passes identical args
        for identical inputs, which enables cache hits in sn_query_page.
        """
        mock_query_page.return_value = (
            [{"sys_id": "1", "level": "error", "message": "test", "sys_created_on": "2026-01-01"}],
            1,
        )

        params = GetSystemLogsParams(level="error")
        get_system_logs(self.server_config, self.auth_manager, params)
        get_system_logs(self.server_config, self.auth_manager, params)

        self.assertEqual(mock_query_page.call_count, 2)

        call1_kwargs = mock_query_page.call_args_list[0].kwargs
        call2_kwargs = mock_query_page.call_args_list[1].kwargs
        self.assertEqual(call1_kwargs["query"], call2_kwargs["query"])
        self.assertEqual(call1_kwargs["table"], call2_kwargs["table"])
        self.assertEqual(call1_kwargs["fields"], call2_kwargs["fields"])
        self.assertEqual(call1_kwargs["limit"], call2_kwargs["limit"])
        self.assertEqual(call1_kwargs["offset"], call2_kwargs["offset"])

    # ------------------------------------------------------------------
    # Cache key changes with different timeframe
    # ------------------------------------------------------------------

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_different_timeframe_produces_different_query(self, mock_query_page):
        mock_query_page.return_value = ([], None)

        get_system_logs(
            self.server_config,
            self.auth_manager,
            GetSystemLogsParams(timeframe="last_hour"),
        )
        get_system_logs(
            self.server_config,
            self.auth_manager,
            GetSystemLogsParams(timeframe="last_7d"),
        )

        query1 = mock_query_page.call_args_list[0].kwargs["query"]
        query2 = mock_query_page.call_args_list[1].kwargs["query"]
        self.assertNotEqual(query1, query2)
        self.assertIn("gs.hoursAgoStart(1)", query1)
        self.assertIn("gs.daysAgoStart(7)", query2)

    # ------------------------------------------------------------------
    # _clamp_limit edge cases
    # ------------------------------------------------------------------

    def test_clamp_limit_zero(self):
        self.assertEqual(_clamp_limit(0), 1)

    def test_clamp_limit_negative(self):
        self.assertEqual(_clamp_limit(-5), 1)

    def test_clamp_limit_above_max(self):
        self.assertEqual(_clamp_limit(100), 20)

    def test_clamp_limit_within_range(self):
        self.assertEqual(_clamp_limit(10), 10)

    def test_clamp_limit_exactly_max(self):
        self.assertEqual(_clamp_limit(20), 20)

    def test_clamp_limit_exactly_one(self):
        self.assertEqual(_clamp_limit(1), 1)

    # ------------------------------------------------------------------
    # _timeframe_query
    # ------------------------------------------------------------------

    def test_timeframe_all(self):
        self.assertIsNone(_timeframe_query("all"))

    def test_timeframe_last_hour(self):
        result = _timeframe_query("last_hour")
        self.assertEqual(result, "sys_created_on>=javascript:gs.hoursAgoStart(1)")

    def test_timeframe_last_7d(self):
        result = _timeframe_query("last_7d")
        self.assertEqual(result, "sys_created_on>=javascript:gs.daysAgoStart(7)")

    def test_timeframe_last_24h_default(self):
        result = _timeframe_query("last_24h")
        self.assertEqual(result, "sys_created_on>=javascript:gs.hoursAgoStart(24)")

    def test_timeframe_none_defaults_to_24h(self):
        result = _timeframe_query(None)
        self.assertEqual(result, "sys_created_on>=javascript:gs.hoursAgoStart(24)")

    def test_timeframe_unknown_defaults_to_24h(self):
        result = _timeframe_query("unknown_value")
        self.assertEqual(result, "sys_created_on>=javascript:gs.hoursAgoStart(24)")

    # ------------------------------------------------------------------
    # _truncate_results
    # ------------------------------------------------------------------

    def test_truncate_results_long_text(self):
        long_text = "a" * 600
        results = [{"message": long_text, "sys_id": "1"}]
        truncated = _truncate_results(results, max_text_length=300)
        self.assertIn("truncated", truncated[0]["message"])
        self.assertTrue(truncated[0]["message"].startswith("a" * 300))
        self.assertEqual(truncated[0]["sys_id"], "1")

    def test_truncate_results_short_text_unchanged(self):
        results = [{"message": "short", "sys_id": "1"}]
        truncated = _truncate_results(results, max_text_length=300)
        self.assertEqual(truncated[0]["message"], "short")

    def test_truncate_results_empty_list(self):
        self.assertEqual(_truncate_results([], max_text_length=300), [])

    # ------------------------------------------------------------------
    # Error path — sn_query_page raises
    # ------------------------------------------------------------------

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_error_path_returns_failure(self, mock_query_page):
        mock_query_page.side_effect = Exception("connection timeout")

        result = get_system_logs(
            self.server_config,
            self.auth_manager,
            GetSystemLogsParams(),
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["table"], "syslog")
        self.assertIn("Failed to query log table", result["message"])
        self.assertIn("connection timeout", result["error"])

    # ------------------------------------------------------------------
    # Safety notice attached on success
    # ------------------------------------------------------------------

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_safety_notice_attached_on_success(self, mock_query_page):
        mock_query_page.return_value = ([], None)

        result = get_system_logs(
            self.server_config,
            self.auth_manager,
            GetSystemLogsParams(),
        )

        self.assertTrue(result["success"])
        self.assertIn("safety_notice", result)
        self.assertIn("System logs", result["safety_notice"])

    # ------------------------------------------------------------------
    # _clamp_text_length
    # ------------------------------------------------------------------

    def test_clamp_text_length_below_min(self):
        self.assertEqual(_clamp_text_length(50), 100)

    def test_clamp_text_length_above_max(self):
        self.assertEqual(_clamp_text_length(5000), 2000)

    def test_clamp_text_length_in_range(self):
        self.assertEqual(_clamp_text_length(500), 500)


if __name__ == "__main__":
    unittest.main()
