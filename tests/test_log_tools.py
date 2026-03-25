import unittest
from unittest.mock import MagicMock

from servicenow_mcp.tools.log_tools import (
    GetBackgroundScriptLogsParams,
    GetJournalEntriesParams,
    GetSystemLogsParams,
    GetTransactionLogsParams,
    get_background_script_logs,
    get_journal_entries,
    get_system_logs,
    get_transaction_logs,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestLogTools(unittest.TestCase):
    def setUp(self):
        auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        )
        self.server_config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=auth_config,
        )
        self.auth_manager = MagicMock()

    def test_get_system_logs_applies_safety_limits(self):
        response = MagicMock()
        response.json.return_value = {
            "result": [
                {
                    "sys_id": "1",
                    "level": "error",
                    "source": "Update Set",
                    "message": "x" * 900,
                    "sys_created_on": "2026-03-25 10:00:00",
                }
            ]
        }
        response.headers = {"X-Total-Count": "25"}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        result = get_system_logs(
            self.server_config,
            self.auth_manager,
            GetSystemLogsParams(limit=999, level="error", contains="commit", max_text_length=300),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["limit_applied"], 20)
        self.assertEqual(result["table"], "syslog")
        self.assertIn("truncated", result["results"][0]["message"])

        _, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(kwargs["params"]["sysparm_limit"], 20)
        self.assertEqual(
            kwargs["params"]["sysparm_fields"], "sys_id,level,source,message,sys_created_on"
        )
        self.assertIn("level=error", kwargs["params"]["sysparm_query"])
        self.assertIn("messageLIKEcommit", kwargs["params"]["sysparm_query"])

    def test_get_journal_entries_uses_fixed_summary_fields(self):
        response = MagicMock()
        response.json.return_value = {"result": []}
        response.headers = {}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        result = get_journal_entries(
            self.server_config,
            self.auth_manager,
            GetJournalEntriesParams(
                table="incident", record_sys_id="abc123", field_name="comments"
            ),
        )

        self.assertTrue(result["success"])
        _, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(
            kwargs["params"]["sysparm_fields"],
            "sys_id,name,element,element_id,value,sys_created_by,sys_created_on",
        )
        self.assertIn("name=incident", kwargs["params"]["sysparm_query"])
        self.assertIn("element_id=abc123", kwargs["params"]["sysparm_query"])
        self.assertIn("element=comments", kwargs["params"]["sysparm_query"])

    def test_get_transaction_logs_applies_filters(self):
        response = MagicMock()
        response.json.return_value = {"result": []}
        response.headers = {}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

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
        _, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(
            kwargs["params"]["sysparm_fields"],
            "sys_id,url,response_status,response_time,transaction_id,sys_created_by,sys_created_on",
        )
        self.assertIn("urlLIKE/api/now/table", kwargs["params"]["sysparm_query"])
        self.assertIn("response_status=500", kwargs["params"]["sysparm_query"])
        self.assertIn("response_time>=1000", kwargs["params"]["sysparm_query"])

    def test_get_background_script_logs_uses_execution_tracker(self):
        response = MagicMock()
        response.json.return_value = {"result": []}
        response.headers = {}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        result = get_background_script_logs(
            self.server_config,
            self.auth_manager,
            GetBackgroundScriptLogsParams(name="nightly", state="error", source="script"),
        )

        self.assertTrue(result["success"])
        _, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(
            kwargs["params"]["sysparm_fields"],
            "sys_id,name,state,source,message,detail,percent_complete,sys_created_on,sys_updated_on",
        )
        self.assertEqual(
            self.auth_manager.make_request.call_args.args[1],
            "https://test.service-now.com/api/now/table/sys_execution_tracker",
        )
        self.assertIn("nameLIKEnightly", kwargs["params"]["sysparm_query"])
        self.assertIn("state=error", kwargs["params"]["sysparm_query"])
        self.assertIn("sourceLIKEscript", kwargs["params"]["sysparm_query"])
