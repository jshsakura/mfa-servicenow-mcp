"""Tests for unified get_logs tool.

Covers all 4 log types (system, journal, transaction, background),
filter mapping, safety limits, error handling, and edge cases.
"""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.log_tools import (
    GetLogsParams,
    LOG_TYPES,
    _clamp_limit,
    _clamp_text_length,
    _timeframe_query,
    _truncate_results,
    get_logs,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        ),
    )


class TestInternals(unittest.TestCase):
    """Safety clamps and shared internals."""

    def test_clamp_limit_upper(self):
        self.assertEqual(_clamp_limit(999), 20)

    def test_clamp_limit_lower(self):
        self.assertEqual(_clamp_limit(0), 1)

    def test_clamp_limit_normal(self):
        self.assertEqual(_clamp_limit(10), 10)

    def test_clamp_text_upper(self):
        self.assertEqual(_clamp_text_length(99999), 2000)

    def test_clamp_text_lower(self):
        self.assertEqual(_clamp_text_length(10), 100)

    def test_timeframe_last_hour(self):
        q = _timeframe_query("last_hour")
        self.assertIn("hoursAgoStart(1)", q)

    def test_timeframe_last_24h(self):
        q = _timeframe_query("last_24h")
        self.assertIn("hoursAgoStart(24)", q)

    def test_timeframe_last_7d(self):
        q = _timeframe_query("last_7d")
        self.assertIn("daysAgoStart(7)", q)

    def test_timeframe_all(self):
        self.assertIsNone(_timeframe_query("all"))

    def test_timeframe_default(self):
        q = _timeframe_query("")
        self.assertIn("hoursAgoStart(24)", q)

    def test_truncate_results_long_text(self):
        rows = [{"message": "x" * 1000}]
        result = _truncate_results(rows, 500)
        self.assertTrue(result[0]["message"].endswith("(truncated, original length: 1000)"))
        self.assertLessEqual(len(result[0]["message"]), 600)

    def test_truncate_results_short_text(self):
        rows = [{"message": "short"}]
        result = _truncate_results(rows, 500)
        self.assertEqual(result[0]["message"], "short")

    def test_truncate_results_non_string(self):
        rows = [{"count": 42}]
        result = _truncate_results(rows, 500)
        self.assertEqual(result[0]["count"], 42)


class TestGetLogsSystemType(unittest.TestCase):
    """Tests for log_type=system (syslog)."""

    def setUp(self):
        self.config = _make_config()
        self.auth = MagicMock()

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_system_basic_query(self, mock_qp):
        mock_qp.return_value = (
            [{"sys_id": "1", "level": "error", "source": "Script", "message": "NullPointerException", "sys_created_on": "2026-04-15"}],
            1,
        )

        result = get_logs(self.config, self.auth, GetLogsParams(log_type="system"))

        self.assertTrue(result["success"])
        self.assertEqual(result["log_type"], "system")
        self.assertEqual(result["table"], "syslog")
        self.assertEqual(result["count"], 1)

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_system_level_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", level="error",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("level=error", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_system_source_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", source="BusinessRule",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("sourceLIKEBusinessRule", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_system_contains_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", contains="NullPointer",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("messageLIKENullPointer", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_system_combined_filters(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", level="error", source="BR", contains="fail",
            timeframe="last_hour",
        ))

        _, kwargs = mock_qp.call_args
        query = kwargs["query"]
        self.assertIn("level=error", query)
        self.assertIn("sourceLIKEBR", query)
        self.assertIn("messageLIKEfail", query)
        self.assertIn("hoursAgoStart(1)", query)

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_system_text_truncation(self, mock_qp):
        mock_qp.return_value = (
            [{"sys_id": "1", "level": "error", "source": "x", "message": "A" * 900, "sys_created_on": "2026-04-15"}],
            1,
        )

        result = get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", max_text_length=200,
        ))

        self.assertTrue(result["results"][0]["message"].endswith(")"))
        self.assertLessEqual(len(result["results"][0]["message"]), 300)


class TestGetLogsJournalType(unittest.TestCase):
    """Tests for log_type=journal (sys_journal_field)."""

    def setUp(self):
        self.config = _make_config()
        self.auth = MagicMock()

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_journal_table_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="journal", table="incident",
        ))

        _, kwargs = mock_qp.call_args
        self.assertEqual(kwargs["table"], "sys_journal_field")
        self.assertIn("name=incident", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_journal_record_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="journal", record_sys_id="abc123",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("element_id=abc123", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_journal_field_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="journal", field_name="work_notes",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("element=work_notes", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_journal_created_by_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="journal", created_by="admin",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("sys_created_by=admin", kwargs["query"])


class TestGetLogsTransactionType(unittest.TestCase):
    """Tests for log_type=transaction (syslog_transaction)."""

    def setUp(self):
        self.config = _make_config()
        self.auth = MagicMock()

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_transaction_url_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="transaction", url_contains="/api/now/table",
        ))

        _, kwargs = mock_qp.call_args
        self.assertEqual(kwargs["table"], "syslog_transaction")
        self.assertIn("urlLIKE/api/now/table", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_transaction_status_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="transaction", response_status="500",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("response_status=500", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_transaction_slow_request_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="transaction", min_response_time_ms=5000,
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("response_time>=5000", kwargs["query"])


class TestGetLogsBackgroundType(unittest.TestCase):
    """Tests for log_type=background (sys_execution_tracker)."""

    def setUp(self):
        self.config = _make_config()
        self.auth = MagicMock()

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_background_name_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="background", name="DataMigration",
        ))

        _, kwargs = mock_qp.call_args
        self.assertEqual(kwargs["table"], "sys_execution_tracker")
        self.assertIn("nameLIKEDataMigration", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_background_state_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="background", state="running",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("state=running", kwargs["query"])


class TestGetLogsSafetyAndEdgeCases(unittest.TestCase):
    """Safety limits, error handling, invalid input."""

    def setUp(self):
        self.config = _make_config()
        self.auth = MagicMock()

    def test_invalid_log_type(self):
        result = get_logs(self.config, self.auth, GetLogsParams(log_type="invalid"))
        self.assertFalse(result["success"])
        self.assertIn("Unknown log_type", result["message"])
        self.assertIn("available_types", result)

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_limit_clamped(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", limit=999,
        ))

        self.assertEqual(result["limit_applied"], 20)

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_offset_applied(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", offset=50,
        ))

        _, kwargs = mock_qp.call_args
        self.assertEqual(kwargs["offset"], 50)

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_timeframe_all(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", timeframe="all",
        ))

        _, kwargs = mock_qp.call_args
        # 'all' means no timeframe filter
        self.assertNotIn("hoursAgoStart", kwargs["query"])
        self.assertNotIn("daysAgoStart", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_api_error_handled(self, mock_qp):
        mock_qp.side_effect = Exception("Connection refused")

        result = get_logs(self.config, self.auth, GetLogsParams(log_type="system"))

        self.assertFalse(result["success"])
        self.assertIn("Connection refused", result["error"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_raw_query_appended(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="system", query="sys_scope=x_app",
        ))

        _, kwargs = mock_qp.call_args
        self.assertIn("sys_scope=x_app", kwargs["query"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_result_has_log_type_and_label(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "1"}], 1)

        result = get_logs(self.config, self.auth, GetLogsParams(log_type="system"))

        self.assertEqual(result["log_type"], "system")
        self.assertEqual(result["log_label"], "System Log")

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_ordered_by_created_desc(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(log_type="journal"))

        _, kwargs = mock_qp.call_args
        self.assertEqual(kwargs["orderby"], "-sys_created_on")

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_display_value_true(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(log_type="system"))

        _, kwargs = mock_qp.call_args
        self.assertTrue(kwargs["display_value"])

    @patch("servicenow_mcp.tools.log_tools.sn_query_page")
    def test_irrelevant_filters_ignored(self, mock_qp):
        """Filters for other log types should not appear in query."""
        mock_qp.return_value = ([], 0)

        get_logs(self.config, self.auth, GetLogsParams(
            log_type="system",
            url_contains="/api",  # transaction filter, should be ignored for system
            record_sys_id="abc",  # journal filter, should be ignored for system
        ))

        _, kwargs = mock_qp.call_args
        self.assertNotIn("url", kwargs["query"])
        self.assertNotIn("element_id", kwargs["query"])


class TestLogTypeRegistry(unittest.TestCase):
    """Verify LOG_TYPES registry structure."""

    def test_all_types_have_required_keys(self):
        for name, cfg in LOG_TYPES.items():
            self.assertIn("table", cfg, f"{name} missing table")
            self.assertIn("fields", cfg, f"{name} missing fields")
            self.assertIn("label", cfg, f"{name} missing label")
            self.assertIn("hint", cfg, f"{name} missing hint")
            self.assertIn("filters", cfg, f"{name} missing filters")

    def test_four_log_types_exist(self):
        self.assertEqual(sorted(LOG_TYPES.keys()), ["background", "journal", "system", "transaction"])

    def test_filters_are_tuples(self):
        for name, cfg in LOG_TYPES.items():
            for filter_name, (field, op) in cfg["filters"].items():
                self.assertIsInstance(field, str, f"{name}.{filter_name} field not str")
                self.assertIn(op, ("=", "LIKE", ">="), f"{name}.{filter_name} invalid operator")
