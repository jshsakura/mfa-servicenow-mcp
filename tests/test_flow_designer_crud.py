"""Tests for Flow Designer CRUD tools and trigger-by-table lookup."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import (
    ActivateFlowDesignerParams,
    DeactivateFlowDesignerParams,
    ListFlowTriggersByTableParams,
    UpdateFlowDesignerParams,
    activate_flow_designer,
    deactivate_flow_designer,
    list_flow_triggers_by_table,
    update_flow_designer,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestFlowDesignerCRUD(unittest.TestCase):
    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        )
        self.config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=self.auth_config,
        )
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {
            "Authorization": "Bearer test",
            "Content-Type": "application/json",
        }

    # -- update_flow_designer ------------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.invalidate_query_cache")
    def test_update_flow_designer_happy(self, mock_invalidate):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": {"sys_id": "f1", "name": "Updated Flow", "active": "true"}
        }
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = update_flow_designer(
            self.config,
            self.auth_manager,
            UpdateFlowDesignerParams(flow_id="f1", name="Updated Flow", description="New desc"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["flow"]["name"], "Updated Flow")
        self.assertEqual(result["message"], "Flow updated successfully")

        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "PATCH")
        self.assertIn("/api/now/table/sys_hub_flow/f1", call_args[0][1])
        self.assertEqual(call_args[1]["json"]["name"], "Updated Flow")
        self.assertEqual(call_args[1]["json"]["description"], "New desc")
        mock_invalidate.assert_called_once_with(table="sys_hub_flow")

    def test_update_flow_designer_no_params(self):
        result = update_flow_designer(
            self.config,
            self.auth_manager,
            UpdateFlowDesignerParams(flow_id="f1"),
        )

        self.assertFalse(result["success"])
        self.assertIn("No update parameters provided", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.invalidate_query_cache")
    def test_update_flow_designer_active_flag(self, mock_invalidate):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"sys_id": "f1", "active": "false"}}
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = update_flow_designer(
            self.config,
            self.auth_manager,
            UpdateFlowDesignerParams(flow_id="f1", active=False),
        )

        self.assertTrue(result["success"])
        call_json = self.auth_manager.make_request.call_args[1]["json"]
        self.assertEqual(call_json["active"], "false")

    def test_update_flow_designer_error(self):
        self.auth_manager.make_request.side_effect = RuntimeError("Connection refused")

        result = update_flow_designer(
            self.config,
            self.auth_manager,
            UpdateFlowDesignerParams(flow_id="f1", name="Fail"),
        )

        self.assertFalse(result["success"])
        self.assertIn("Connection refused", result["error"])

    # -- activate_flow_designer ----------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.invalidate_query_cache")
    def test_activate_flow_designer_happy(self, mock_invalidate):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"sys_id": "f1", "active": "true"}}
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = activate_flow_designer(
            self.config,
            self.auth_manager,
            ActivateFlowDesignerParams(flow_id="f1"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Flow activated successfully")

        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "PATCH")
        self.assertIn("/api/now/table/sys_hub_flow/f1", call_args[0][1])
        self.assertEqual(call_args[1]["json"]["active"], "true")
        mock_invalidate.assert_called_once_with(table="sys_hub_flow")

    def test_activate_flow_designer_error(self):
        self.auth_manager.make_request.side_effect = RuntimeError("Timeout")

        result = activate_flow_designer(
            self.config,
            self.auth_manager,
            ActivateFlowDesignerParams(flow_id="f1"),
        )

        self.assertFalse(result["success"])
        self.assertIn("Timeout", result["error"])

    # -- deactivate_flow_designer --------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.invalidate_query_cache")
    def test_deactivate_flow_designer_happy(self, mock_invalidate):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"sys_id": "f1", "active": "false"}}
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = deactivate_flow_designer(
            self.config,
            self.auth_manager,
            DeactivateFlowDesignerParams(flow_id="f1"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Flow deactivated successfully")

        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "PATCH")
        self.assertEqual(call_args[1]["json"]["active"], "false")
        mock_invalidate.assert_called_once_with(table="sys_hub_flow")

    def test_deactivate_flow_designer_error(self):
        self.auth_manager.make_request.side_effect = RuntimeError("Server error")

        result = deactivate_flow_designer(
            self.config,
            self.auth_manager,
            DeactivateFlowDesignerParams(flow_id="f1"),
        )

        self.assertFalse(result["success"])
        self.assertIn("Server error", result["error"])

    # -- list_flow_triggers_by_table -----------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flow_triggers_by_table_happy(self, mock_qp):
        trigger_data = [
            {
                "sys_id": "t1",
                "table": "incident",
                "remote_trigger_id": "flow1",
                "condition": "priority=1",
                "sys_scope": "global",
                "sys_name": "P1 Incident Trigger",
            },
        ]
        flow_data = [
            {
                "sys_id": "flow1",
                "name": "P1 Incident Auto-Assign",
                "status": "Published",
                "active": "true",
            },
        ]
        mock_qp.side_effect = [
            (trigger_data, 1),
            (flow_data, 1),
        ]

        result = list_flow_triggers_by_table(
            self.config,
            self.auth_manager,
            ListFlowTriggersByTableParams(table_name="incident"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["table"], "incident")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["triggers"][0]["trigger"]["sys_id"], "t1")
        self.assertEqual(result["triggers"][0]["flow"]["sys_id"], "flow1")

        # Verify trigger query
        trigger_call = mock_qp.call_args_list[0][1]
        self.assertEqual(trigger_call["table"], "sys_flow_record_trigger")
        self.assertIn("table=incident", trigger_call["query"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flow_triggers_by_table_with_scope(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_flow_triggers_by_table(
            self.config,
            self.auth_manager,
            ListFlowTriggersByTableParams(table_name="incident", scope="global"),
        )

        trigger_call = mock_qp.call_args_list[0][1]
        query = trigger_call["query"]
        self.assertIn("table=incident", query)
        self.assertIn("sys_scope.scope=global", query)
        # Ensure dot-walking is used, NOT sys_scope=
        self.assertNotIn("sys_scope=global", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flow_triggers_by_table_no_remote_id(self, mock_qp):
        trigger_data = [
            {
                "sys_id": "t1",
                "table": "incident",
                "remote_trigger_id": "",
                "condition": "",
                "sys_scope": "global",
                "sys_name": "Orphan Trigger",
            },
        ]
        mock_qp.return_value = (trigger_data, 1)

        result = list_flow_triggers_by_table(
            self.config,
            self.auth_manager,
            ListFlowTriggersByTableParams(table_name="incident"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertIsNone(result["triggers"][0]["flow"])
        # Only one call (trigger query), no flow lookup
        self.assertEqual(mock_qp.call_count, 1)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flow_triggers_by_table_flow_not_found(self, mock_qp):
        trigger_data = [
            {
                "sys_id": "t1",
                "table": "incident",
                "remote_trigger_id": "missing_flow",
                "condition": "",
                "sys_scope": "global",
                "sys_name": "Trigger",
            },
        ]
        mock_qp.side_effect = [
            (trigger_data, 1),
            ([], 0),  # flow lookup returns nothing
        ]

        result = list_flow_triggers_by_table(
            self.config,
            self.auth_manager,
            ListFlowTriggersByTableParams(table_name="incident"),
        )

        self.assertTrue(result["success"])
        self.assertIsNone(result["triggers"][0]["flow"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flow_triggers_by_table_empty(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = list_flow_triggers_by_table(
            self.config,
            self.auth_manager,
            ListFlowTriggersByTableParams(table_name="nonexistent_table"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["triggers"], [])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flow_triggers_by_table_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Network error")

        result = list_flow_triggers_by_table(
            self.config,
            self.auth_manager,
            ListFlowTriggersByTableParams(table_name="incident"),
        )

        self.assertFalse(result["success"])
        self.assertIn("Network error", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flow_triggers_by_table_multiple_triggers(self, mock_qp):
        trigger_data = [
            {
                "sys_id": "t1",
                "table": "incident",
                "remote_trigger_id": "flow1",
                "condition": "priority=1",
                "sys_scope": "global",
                "sys_name": "Trigger 1",
            },
            {
                "sys_id": "t2",
                "table": "incident",
                "remote_trigger_id": "flow2",
                "condition": "priority=2",
                "sys_scope": "global",
                "sys_name": "Trigger 2",
            },
        ]
        flow1 = [{"sys_id": "flow1", "name": "Flow 1", "status": "Published", "active": "true"}]
        flow2 = [{"sys_id": "flow2", "name": "Flow 2", "status": "Draft", "active": "false"}]

        mock_qp.side_effect = [
            (trigger_data, 2),
            (flow1, 1),
            (flow2, 1),
        ]

        result = list_flow_triggers_by_table(
            self.config,
            self.auth_manager,
            ListFlowTriggersByTableParams(table_name="incident"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["triggers"][0]["flow"]["name"], "Flow 1")
        self.assertEqual(result["triggers"][1]["flow"]["name"], "Flow 2")


if __name__ == "__main__":
    unittest.main()
