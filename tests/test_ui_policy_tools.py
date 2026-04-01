"""
Tests for the UI policy tools.

This module contains tests for the UI policy tools in the ServiceNow MCP server.
"""

import unittest
from unittest.mock import MagicMock

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.ui_policy_tools import (
    CreateUIPolicyActionParams,
    CreateUIPolicyParams,
    create_ui_policy,
    create_ui_policy_action,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestUIPolicyTools(unittest.TestCase):
    """Tests for the UI policy tools."""

    def setUp(self):
        """Set up test fixtures."""
        auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        )
        self.server_config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=auth_config,
        )
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {
            "Authorization": "Bearer test",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # create_ui_policy
    # ------------------------------------------------------------------

    def test_create_ui_policy_success(self):
        """Test creating a UI policy successfully."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "pol123",
                "table": "incident",
                "short_description": "Hide category when P1",
            }
        }
        mock_response.status_code = 201
        self.auth_manager.make_request.return_value = mock_response

        params = CreateUIPolicyParams(
            table="incident",
            short_description="Hide category when P1",
            conditions="priority=1",
            active=True,
            global_policy=True,
            on_load=True,
            reverse_if_false=True,
            order=100,
        )
        result = create_ui_policy(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual("pol123", result["ui_policy_id"])
        self.assertEqual("incident", result["table"])
        self.assertEqual("Hide category when P1", result["short_description"])

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("POST", call_args[0][0])
        self.assertEqual(
            f"{self.server_config.instance_url}/api/now/table/sys_ui_policy",
            call_args[0][1],
        )
        body = call_args[1]["json"]
        self.assertEqual("incident", body["table"])
        self.assertEqual("Hide category when P1", body["short_description"])
        self.assertEqual("true", body["active"])
        self.assertEqual("true", body["global"])
        self.assertEqual("true", body["on_load"])
        self.assertEqual("true", body["reverse_if_false"])
        self.assertEqual("100", body["order"])
        self.assertEqual("priority=1", body["conditions"])

    def test_create_ui_policy_with_optional_fields(self):
        """Test creating a UI policy with view_name and scripts."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "pol456",
                "table": "sc_req_item",
                "short_description": "Custom policy",
            }
        }
        mock_response.status_code = 201
        self.auth_manager.make_request.return_value = mock_response

        params = CreateUIPolicyParams(
            table="sc_req_item",
            short_description="Custom policy",
            global_policy=False,
            view_name="service_portal",
            script_true="g_form.setValue('state', '2');",
            script_false="g_form.setValue('state', '1');",
        )
        result = create_ui_policy(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])

        body = self.auth_manager.make_request.call_args[1]["json"]
        self.assertEqual("false", body["global"])
        self.assertEqual("service_portal", body["view"])
        self.assertEqual("g_form.setValue('state', '2');", body["script_true"])
        self.assertEqual("g_form.setValue('state', '1');", body["script_false"])

    def test_create_ui_policy_no_result(self):
        """Test creating a UI policy when API returns no result."""
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.status_code = 200
        self.auth_manager.make_request.return_value = mock_response

        params = CreateUIPolicyParams(
            table="incident",
            short_description="Test policy",
        )
        result = create_ui_policy(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Failed to create UI policy", result["message"])

    def test_create_ui_policy_error(self):
        """Test creating a UI policy with a request error."""
        self.auth_manager.make_request.side_effect = Exception("Connection refused")

        params = CreateUIPolicyParams(
            table="incident",
            short_description="Test policy",
        )
        result = create_ui_policy(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error creating UI policy", result["message"])
        self.assertIn("Connection refused", result["message"])

    def test_create_ui_policy_without_conditions(self):
        """Test that conditions field is omitted when not provided."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "pol789",
                "table": "incident",
                "short_description": "No conditions",
            }
        }
        mock_response.status_code = 201
        self.auth_manager.make_request.return_value = mock_response

        params = CreateUIPolicyParams(
            table="incident",
            short_description="No conditions",
        )
        result = create_ui_policy(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        body = self.auth_manager.make_request.call_args[1]["json"]
        self.assertNotIn("conditions", body)
        self.assertNotIn("view", body)
        self.assertNotIn("script_true", body)
        self.assertNotIn("script_false", body)

    # ------------------------------------------------------------------
    # create_ui_policy_action
    # ------------------------------------------------------------------

    def test_create_ui_policy_action_success(self):
        """Test creating a UI policy action successfully."""
        # Mock verify response (GET parent policy)
        verify_response = MagicMock()
        verify_response.json.return_value = {
            "result": {
                "sys_id": "pol123",
                "short_description": "Hide category",
                "table": "incident",
            }
        }
        verify_response.status_code = 200

        # Mock create response (POST action)
        create_response = MagicMock()
        create_response.json.return_value = {
            "result": {
                "sys_id": "act456",
                "visible": "false",
                "mandatory": "false",
                "disabled": "false",
            }
        }
        create_response.status_code = 201

        self.auth_manager.make_request.side_effect = [verify_response, create_response]

        params = CreateUIPolicyActionParams(
            ui_policy="pol123",
            field="category",
            visible="false",
            mandatory="false",
        )
        result = create_ui_policy_action(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual("act456", result["action_id"])
        self.assertEqual("pol123", result["ui_policy"])
        self.assertEqual("category", result["field"])
        self.assertIn("category", result["message"])

        # Verify the verify call
        verify_call = self.auth_manager.make_request.call_args_list[0]
        self.assertEqual("GET", verify_call[0][0])
        self.assertIn("/sys_ui_policy/pol123", verify_call[0][1])

        # Verify the create call
        create_call = self.auth_manager.make_request.call_args_list[1]
        self.assertEqual("POST", create_call[0][0])
        self.assertIn("/sys_ui_policy_action", create_call[0][1])
        body = create_call[1]["json"]
        self.assertEqual("pol123", body["ui_policy"])
        self.assertEqual("incident", body["table"])
        self.assertEqual("category", body["field"])
        self.assertEqual("false", body["visible"])
        self.assertEqual("false", body["mandatory"])

    def test_create_ui_policy_action_with_all_options(self):
        """Test creating a UI policy action with all field controls set."""
        verify_response = MagicMock()
        verify_response.json.return_value = {
            "result": {
                "sys_id": "pol123",
                "short_description": "Full policy",
                "table": "incident",
            }
        }
        verify_response.status_code = 200

        create_response = MagicMock()
        create_response.json.return_value = {
            "result": {
                "sys_id": "act789",
                "visible": "true",
                "mandatory": "true",
                "disabled": "false",
            }
        }
        create_response.status_code = 201

        self.auth_manager.make_request.side_effect = [verify_response, create_response]

        params = CreateUIPolicyActionParams(
            ui_policy="pol123",
            field="assigned_to",
            visible="true",
            mandatory="true",
            disabled="false",
            cleared="true",
        )
        result = create_ui_policy_action(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])

        body = self.auth_manager.make_request.call_args_list[1][1]["json"]
        self.assertEqual("true", body["visible"])
        self.assertEqual("true", body["mandatory"])
        self.assertEqual("false", body["disabled"])
        self.assertEqual("true", body["cleared"])

    def test_create_ui_policy_action_parent_not_found(self):
        """Test creating a UI policy action when parent policy doesn't exist."""
        verify_response = MagicMock()
        verify_response.json.return_value = {}
        verify_response.status_code = 200
        self.auth_manager.make_request.return_value = verify_response

        params = CreateUIPolicyActionParams(
            ui_policy="nonexistent",
            field="category",
        )
        result = create_ui_policy_action(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("UI policy not found", result["message"])

    def test_create_ui_policy_action_verify_error(self):
        """Test creating a UI policy action when verify request fails."""
        self.auth_manager.make_request.side_effect = Exception("Timeout")

        params = CreateUIPolicyActionParams(
            ui_policy="pol123",
            field="category",
        )
        result = create_ui_policy_action(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error verifying UI policy", result["message"])

    def test_create_ui_policy_action_create_error(self):
        """Test creating a UI policy action when create request fails."""
        verify_response = MagicMock()
        verify_response.json.return_value = {
            "result": {
                "sys_id": "pol123",
                "short_description": "Test",
                "table": "incident",
            }
        }
        verify_response.status_code = 200

        self.auth_manager.make_request.side_effect = [
            verify_response,
            Exception("Server error"),
        ]

        params = CreateUIPolicyActionParams(
            ui_policy="pol123",
            field="category",
            visible="false",
        )
        result = create_ui_policy_action(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error creating UI policy action", result["message"])

    def test_create_ui_policy_action_no_result(self):
        """Test creating a UI policy action when create returns no result."""
        verify_response = MagicMock()
        verify_response.json.return_value = {
            "result": {
                "sys_id": "pol123",
                "short_description": "Test",
                "table": "incident",
            }
        }
        verify_response.status_code = 200

        create_response = MagicMock()
        create_response.json.return_value = {}
        create_response.status_code = 200

        self.auth_manager.make_request.side_effect = [verify_response, create_response]

        params = CreateUIPolicyActionParams(
            ui_policy="pol123",
            field="category",
        )
        result = create_ui_policy_action(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Failed to create UI policy action", result["message"])

    def test_create_ui_policy_action_optional_fields_omitted(self):
        """Test that optional action fields are omitted when not provided."""
        verify_response = MagicMock()
        verify_response.json.return_value = {
            "result": {
                "sys_id": "pol123",
                "short_description": "Test",
                "table": "incident",
            }
        }
        verify_response.status_code = 200

        create_response = MagicMock()
        create_response.json.return_value = {
            "result": {
                "sys_id": "act001",
                "visible": "",
                "mandatory": "",
                "disabled": "",
            }
        }
        create_response.status_code = 201

        self.auth_manager.make_request.side_effect = [verify_response, create_response]

        params = CreateUIPolicyActionParams(
            ui_policy="pol123",
            field="category",
        )
        result = create_ui_policy_action(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        body = self.auth_manager.make_request.call_args_list[1][1]["json"]
        self.assertNotIn("visible", body)
        self.assertNotIn("mandatory", body)
        self.assertNotIn("disabled", body)
        self.assertNotIn("cleared", body)


class TestUIPolicyParams(unittest.TestCase):
    """Tests for the UI policy parameter models."""

    def test_create_ui_policy_params_required_fields(self):
        """Test create UI policy params with required fields only."""
        params = CreateUIPolicyParams(
            table="incident",
            short_description="Test policy",
        )
        self.assertEqual("incident", params.table)
        self.assertEqual("Test policy", params.short_description)
        self.assertTrue(params.active)
        self.assertTrue(params.global_policy)
        self.assertTrue(params.on_load)
        self.assertTrue(params.reverse_if_false)
        self.assertEqual(100, params.order)
        self.assertIsNone(params.conditions)
        self.assertIsNone(params.view_name)
        self.assertIsNone(params.script_true)
        self.assertIsNone(params.script_false)

    def test_create_ui_policy_params_all_fields(self):
        """Test create UI policy params with all fields."""
        params = CreateUIPolicyParams(
            table="sc_req_item",
            short_description="Full params test",
            conditions="priority=1^state=1",
            active=False,
            global_policy=False,
            view_name="service_portal",
            on_load=False,
            reverse_if_false=False,
            order=50,
            script_true="g_form.setVisible('field', true);",
            script_false="g_form.setVisible('field', false);",
        )
        self.assertEqual("sc_req_item", params.table)
        self.assertFalse(params.active)
        self.assertFalse(params.global_policy)
        self.assertEqual("service_portal", params.view_name)
        self.assertFalse(params.on_load)
        self.assertFalse(params.reverse_if_false)
        self.assertEqual(50, params.order)
        self.assertEqual("priority=1^state=1", params.conditions)

    def test_create_ui_policy_action_params_required_fields(self):
        """Test create UI policy action params with required fields only."""
        params = CreateUIPolicyActionParams(
            ui_policy="pol123",
            field="category",
        )
        self.assertEqual("pol123", params.ui_policy)
        self.assertEqual("category", params.field)
        self.assertIsNone(params.visible)
        self.assertIsNone(params.mandatory)
        self.assertIsNone(params.disabled)
        self.assertIsNone(params.cleared)

    def test_create_ui_policy_action_params_all_fields(self):
        """Test create UI policy action params with all fields."""
        params = CreateUIPolicyActionParams(
            ui_policy="pol123",
            field="assigned_to",
            visible="true",
            mandatory="true",
            disabled="false",
            cleared="true",
        )
        self.assertEqual("true", params.visible)
        self.assertEqual("true", params.mandatory)
        self.assertEqual("false", params.disabled)
        self.assertEqual("true", params.cleared)
