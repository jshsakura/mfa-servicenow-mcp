"""
Tests for the script include tools.

This module contains tests for the script include tools in the ServiceNow MCP server.
"""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.script_include_tools import (
    CreateScriptIncludeParams,
    DeleteScriptIncludeParams,
    GetScriptIncludeParams,
    ListScriptIncludesParams,
    ScriptIncludeResponse,
    UpdateScriptIncludeParams,
    create_script_include,
    delete_script_include,
    get_script_include,
    list_script_includes,
    update_script_include,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestScriptIncludeTools(unittest.TestCase):
    """Tests for the script include tools."""

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

    def test_list_script_includes(self):
        """Test listing script includes."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
                    "script": "var TestScriptInclude = Class.create();\nTestScriptInclude.prototype = {\n    initialize: function() {\n    },\n\n    type: 'TestScriptInclude'\n};",
                    "description": "Test Script Include",
                    "api_name": "global.TestScriptInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01 00:00:00",
                    "sys_updated_on": "2023-01-02 00:00:00",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = ListScriptIncludesParams(
            limit=10, offset=0, active=True, client_callable=True, query="Test"
        )
        result = list_script_includes(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result["success"])
        self.assertEqual(1, len(result["script_includes"]))
        self.assertEqual("123", result["script_includes"][0]["sys_id"])
        self.assertEqual("TestScriptInclude", result["script_includes"][0]["name"])
        self.assertTrue(result["script_includes"][0]["client_callable"])
        self.assertTrue(result["script_includes"][0]["active"])

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("GET", call_args[0][0])
        self.assertEqual(
            f"{self.server_config.instance_url}/api/now/table/sys_script_include",
            call_args[0][1],
        )
        self.assertEqual(10, call_args[1]["params"]["sysparm_limit"])
        self.assertEqual(0, call_args[1]["params"]["sysparm_offset"])
        self.assertEqual(
            "active=true^client_callable=true^nameLIKETest",
            call_args[1]["params"]["sysparm_query"],
        )

    def test_get_script_include(self):
        """Test getting a script include."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "123",
                "name": "TestScriptInclude",
                "script": "var TestScriptInclude = Class.create();\nTestScriptInclude.prototype = {\n    initialize: function() {\n    },\n\n    type: 'TestScriptInclude'\n};",
                "description": "Test Script Include",
                "api_name": "global.TestScriptInclude",
                "client_callable": "true",
                "active": "true",
                "access": "public",
                "sys_created_on": "2023-01-01 00:00:00",
                "sys_updated_on": "2023-01-02 00:00:00",
                "sys_created_by": {"display_value": "admin"},
                "sys_updated_by": {"display_value": "admin"},
            }
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = GetScriptIncludeParams(script_include_id="123")
        result = get_script_include(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result["success"])
        self.assertEqual("123", result["script_include"]["sys_id"])
        self.assertEqual("TestScriptInclude", result["script_include"]["name"])
        self.assertTrue(result["script_include"]["client_callable"])
        self.assertTrue(result["script_include"]["active"])

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("GET", call_args[0][0])
        self.assertEqual(
            f"{self.server_config.instance_url}/api/now/table/sys_script_include",
            call_args[0][1],
        )
        self.assertEqual("name=123", call_args[1]["params"]["sysparm_query"])

    def test_create_script_include(self):
        """Test creating a script include."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "123",
                "name": "TestScriptInclude",
            }
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = CreateScriptIncludeParams(
            name="TestScriptInclude",
            script="var TestScriptInclude = Class.create();\nTestScriptInclude.prototype = {\n    initialize: function() {\n    },\n\n    type: 'TestScriptInclude'\n};",
            description="Test Script Include",
            api_name="global.TestScriptInclude",
            client_callable=True,
            active=True,
            access="public",
        )
        result = create_script_include(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result.success)
        self.assertEqual("123", result.script_include_id)
        self.assertEqual("TestScriptInclude", result.script_include_name)

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("POST", call_args[0][0])
        self.assertEqual(
            f"{self.server_config.instance_url}/api/now/table/sys_script_include",
            call_args[0][1],
        )
        self.assertEqual("TestScriptInclude", call_args[1]["json"]["name"])
        self.assertEqual("true", call_args[1]["json"]["client_callable"])
        self.assertEqual("true", call_args[1]["json"]["active"])
        self.assertEqual("public", call_args[1]["json"]["access"])

    @patch("servicenow_mcp.tools.script_include_tools.get_script_include")
    def test_update_script_include(self, mock_get_script_include):
        """Test updating a script include."""
        # Mock get_script_include response
        mock_get_script_include.return_value = {
            "success": True,
            "message": "Found script include: TestScriptInclude",
            "script_include": {
                "sys_id": "123",
                "name": "TestScriptInclude",
                "script": "var TestScriptInclude = Class.create();\nTestScriptInclude.prototype = {\n    initialize: function() {\n    },\n\n    type: 'TestScriptInclude'\n};",
                "description": "Test Script Include",
                "api_name": "global.TestScriptInclude",
                "client_callable": True,
                "active": True,
                "access": "public",
            },
        }

        # Mock patch response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "123",
                "name": "TestScriptInclude",
            }
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = UpdateScriptIncludeParams(
            script_include_id="123",
            script="var TestScriptInclude = Class.create();\nTestScriptInclude.prototype = {\n    initialize: function() {\n        // Updated\n    },\n\n    type: 'TestScriptInclude'\n};",
            description="Updated Test Script Include",
            client_callable=False,
        )
        result = update_script_include(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result.success)
        self.assertEqual("123", result.script_include_id)
        self.assertEqual("TestScriptInclude", result.script_include_name)

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("PATCH", call_args[0][0])
        self.assertEqual(
            f"{self.server_config.instance_url}/api/now/table/sys_script_include/123",
            call_args[0][1],
        )
        self.assertEqual("Updated Test Script Include", call_args[1]["json"]["description"])
        self.assertEqual("false", call_args[1]["json"]["client_callable"])

    @patch("servicenow_mcp.tools.script_include_tools.get_script_include")
    def test_delete_script_include(self, mock_get_script_include):
        """Test deleting a script include."""
        # Mock get_script_include response
        mock_get_script_include.return_value = {
            "success": True,
            "message": "Found script include: TestScriptInclude",
            "script_include": {
                "sys_id": "123",
                "name": "TestScriptInclude",
            },
        }

        # Mock delete response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = DeleteScriptIncludeParams(script_include_id="123")
        result = delete_script_include(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result.success)
        self.assertEqual("123", result.script_include_id)
        self.assertEqual("TestScriptInclude", result.script_include_name)

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("DELETE", call_args[0][0])
        self.assertEqual(
            f"{self.server_config.instance_url}/api/now/table/sys_script_include/123",
            call_args[0][1],
        )

    def test_list_script_includes_error(self):
        """Test listing script includes with an error."""
        # Mock response
        self.auth_manager.make_request.side_effect = Exception("Test error")

        # Call the method
        params = ListScriptIncludesParams()
        result = list_script_includes(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertFalse(result["success"])
        self.assertIn("Error listing script includes", result["message"])

    def test_get_script_include_error(self):
        """Test getting a script include with an error."""
        # Mock response
        self.auth_manager.make_request.side_effect = Exception("Test error")

        # Call the method
        params = GetScriptIncludeParams(script_include_id="123")
        result = get_script_include(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertFalse(result["success"])
        self.assertIn("Error getting script include", result["message"])

    def test_create_script_include_error(self):
        """Test creating a script include with an error."""
        # Mock response
        self.auth_manager.make_request.side_effect = Exception("Test error")

        # Call the method
        params = CreateScriptIncludeParams(
            name="TestScriptInclude",
            script="var TestScriptInclude = Class.create();\nTestScriptInclude.prototype = {\n    initialize: function() {\n    },\n\n    type: 'TestScriptInclude'\n};",
        )
        result = create_script_include(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertFalse(result.success)
        self.assertIn("Error creating script include", result.message)


class TestScriptIncludeParams(unittest.TestCase):
    """Tests for the script include parameters."""

    def test_list_script_includes_params(self):
        """Test list script includes parameters."""
        params = ListScriptIncludesParams(
            limit=20, offset=10, active=True, client_callable=False, query="Test"
        )
        self.assertEqual(20, params.limit)
        self.assertEqual(10, params.offset)
        self.assertTrue(params.active)
        self.assertFalse(params.client_callable)
        self.assertEqual("Test", params.query)

    def test_get_script_include_params(self):
        """Test get script include parameters."""
        params = GetScriptIncludeParams(script_include_id="123")
        self.assertEqual("123", params.script_include_id)

    def test_create_script_include_params(self):
        """Test create script include parameters."""
        params = CreateScriptIncludeParams(
            name="TestScriptInclude",
            script="var TestScriptInclude = Class.create();\nTestScriptInclude.prototype = {\n    initialize: function() {\n    },\n\n    type: 'TestScriptInclude'\n};",
            description="Test Script Include",
            api_name="global.TestScriptInclude",
            client_callable=True,
            active=True,
            access="public",
        )
        self.assertEqual("TestScriptInclude", params.name)
        self.assertTrue(params.client_callable)
        self.assertTrue(params.active)
        self.assertEqual("public", params.access)

    def test_update_script_include_params(self):
        """Test update script include parameters."""
        params = UpdateScriptIncludeParams(
            script_include_id="123",
            script="var TestScriptInclude = Class.create();\nTestScriptInclude.prototype = {\n    initialize: function() {\n        // Updated\n    },\n\n    type: 'TestScriptInclude'\n};",
            description="Updated Test Script Include",
            client_callable=False,
        )
        self.assertEqual("123", params.script_include_id)
        self.assertEqual("Updated Test Script Include", params.description)
        self.assertFalse(params.client_callable)

    def test_delete_script_include_params(self):
        """Test delete script include parameters."""
        params = DeleteScriptIncludeParams(script_include_id="123")
        self.assertEqual("123", params.script_include_id)

    def test_script_include_response(self):
        """Test script include response."""
        response = ScriptIncludeResponse(
            success=True,
            message="Test message",
            script_include_id="123",
            script_include_name="TestScriptInclude",
        )
        self.assertTrue(response.success)
        self.assertEqual("Test message", response.message)
        self.assertEqual("123", response.script_include_id)
        self.assertEqual("TestScriptInclude", response.script_include_name)
