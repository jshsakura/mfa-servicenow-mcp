"""Focused tests for Flow Designer write behavior."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import UpdateFlowDesignerParams, update_flow_designer
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
    def test_update_flow_designer_active_flag_false(self, mock_invalidate):
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
        self.assertEqual(self.auth_manager.make_request.call_args[1]["json"]["active"], "false")
        mock_invalidate.assert_called_once_with(table="sys_hub_flow")

    @patch("servicenow_mcp.tools.flow_designer_tools.invalidate_query_cache")
    def test_update_flow_designer_active_flag_true(self, mock_invalidate):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"sys_id": "f1", "active": "true"}}
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = update_flow_designer(
            self.config,
            self.auth_manager,
            UpdateFlowDesignerParams(flow_id="f1", active=True),
        )

        self.assertTrue(result["success"])
        self.assertEqual(self.auth_manager.make_request.call_args[1]["json"]["active"], "true")
        mock_invalidate.assert_called_once_with(table="sys_hub_flow")

    def test_update_flow_designer_error(self):
        self.auth_manager.make_request.side_effect = RuntimeError("Connection refused")

        result = update_flow_designer(
            self.config,
            self.auth_manager,
            UpdateFlowDesignerParams(flow_id="f1", name="Fail"),
        )

        self.assertFalse(result["success"])
        self.assertIn("Connection refused", result["error"])
