"""
Tests for the script include tools.

This module contains tests for the script include tools in the ServiceNow MCP server.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.script_include_tools import (
    CreateScriptIncludeParams,
    DeleteScriptIncludeParams,
    ExecuteScriptIncludeParams,
    GetScriptIncludeParams,
    ListScriptIncludesParams,
    ScriptIncludeResponse,
    UpdateScriptIncludeParams,
    create_script_include,
    delete_script_include,
    execute_script_include,
    get_script_include,
    list_script_includes,
    update_script_include,
)
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestScriptIncludeTools(unittest.TestCase):
    """Tests for the script include tools."""

    def setUp(self):
        """Set up test fixtures."""
        invalidate_query_cache()
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

    def _mock_response(self, json_body, status_code=200):
        """Helper to create a mock response with content attribute for sn_query_page compatibility."""
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_body
        resp.raise_for_status = MagicMock()
        resp.content = json.dumps(json_body).encode("utf-8")
        resp.text = json.dumps(json_body)
        resp.headers = {}
        return resp

    # --- list_script_includes ---

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_list_script_includes_happy(self, mock_query_page):
        """Test listing script includes with successful response."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
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
            ],
            1,
        )

        params = ListScriptIncludesParams(
            limit=10, offset=0, active=True, client_callable=True, query="Test"
        )
        result = list_script_includes(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(1, len(result["script_includes"]))
        self.assertEqual("123", result["script_includes"][0]["sys_id"])
        self.assertEqual("TestScriptInclude", result["script_includes"][0]["name"])
        self.assertTrue(result["script_includes"][0]["client_callable"])
        self.assertTrue(result["script_includes"][0]["active"])
        self.assertEqual("admin", result["script_includes"][0]["created_by"])
        self.assertEqual("admin", result["script_includes"][0]["updated_by"])

        mock_query_page.assert_called_once_with(
            self.server_config,
            self.auth_manager,
            table="sys_script_include",
            query="active=true^client_callable=true^nameLIKETest",
            fields="sys_id,name,description,api_name,client_callable,active,access,sys_created_on,sys_updated_on,sys_created_by,sys_updated_by",
            limit=10,
            offset=0,
            display_value=True,
            fail_silently=False,
        )

    @patch("servicenow_mcp.tools.script_include_tools.sn_count")
    def test_list_script_includes_count_only(self, mock_count):
        """Test listing script includes with count_only=True."""
        mock_count.return_value = 42

        params = ListScriptIncludesParams(count_only=True, active=True)
        result = list_script_includes(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(42, result["count"])
        mock_count.assert_called_once_with(
            self.server_config, self.auth_manager, "sys_script_include", "active=true"
        )

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_list_script_includes_with_filters(self, mock_query_page):
        """Test listing script includes with all filter combinations."""
        mock_query_page.return_value = ([], 0)

        params = ListScriptIncludesParams(
            limit=20, offset=10, active=False, client_callable=True, query="MyScript"
        )
        result = list_script_includes(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(0, len(result["script_includes"]))
        mock_query_page.assert_called_once_with(
            self.server_config,
            self.auth_manager,
            table="sys_script_include",
            query="active=false^client_callable=true^nameLIKEMyScript",
            fields="sys_id,name,description,api_name,client_callable,active,access,sys_created_on,sys_updated_on,sys_created_by,sys_updated_by",
            limit=20,
            offset=10,
            display_value=True,
            fail_silently=False,
        )

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_list_script_includes_error(self, mock_query_page):
        """Test listing script includes with an error."""
        mock_query_page.side_effect = Exception("Test error")

        params = ListScriptIncludesParams()
        result = list_script_includes(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error listing script includes", result["message"])
        self.assertEqual([], result["script_includes"])
        self.assertEqual(0, result["total"])

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_list_script_includes_no_filters(self, mock_query_page):
        """Test listing script includes with no filters."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "456",
                    "name": "AnotherSI",
                    "description": "",
                    "api_name": "global.AnotherSI",
                    "client_callable": "false",
                    "active": "true",
                    "access": "package_private",
                    "sys_created_on": "2023-02-01 00:00:00",
                    "sys_updated_on": "2023-02-02 00:00:00",
                    "sys_created_by": {"display_value": "system"},
                    "sys_updated_by": {"display_value": "system"},
                }
            ],
            1,
        )

        params = ListScriptIncludesParams()
        result = list_script_includes(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(1, len(result["script_includes"]))
        self.assertFalse(result["script_includes"][0]["client_callable"])
        mock_query_page.assert_called_once_with(
            self.server_config,
            self.auth_manager,
            table="sys_script_include",
            query="",
            fields="sys_id,name,description,api_name,client_callable,active,access,sys_created_on,sys_updated_on,sys_created_by,sys_updated_by",
            limit=10,
            offset=0,
            display_value=True,
            fail_silently=False,
        )

    # --- get_script_include ---

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_get_script_include_by_name(self, mock_query_page):
        """Test getting a script include by name."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
                    "script": "var TestScriptInclude = Class.create();",
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
            ],
            1,
        )

        params = GetScriptIncludeParams(script_include_id="TestScriptInclude")
        result = get_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual("123", result["script_include"]["sys_id"])
        self.assertEqual("TestScriptInclude", result["script_include"]["name"])
        self.assertTrue(result["script_include"]["client_callable"])
        self.assertTrue(result["script_include"]["active"])
        self.assertEqual(
            "var TestScriptInclude = Class.create();", result["script_include"]["script"]
        )

        mock_query_page.assert_called_once_with(
            self.server_config,
            self.auth_manager,
            table="sys_script_include",
            query="name=TestScriptInclude",
            fields="sys_id,name,script,description,api_name,client_callable,active,access,sys_created_on,sys_updated_on,sys_created_by,sys_updated_by",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_get_script_include_by_sys_id(self, mock_query_page):
        """Test getting a script include by sys_id prefix."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "abc123def456",
                    "name": "MyInclude",
                    "script": "gs.log('test');",
                    "description": "Desc",
                    "api_name": "global.MyInclude",
                    "client_callable": "false",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-03-01",
                    "sys_updated_on": "2023-03-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        params = GetScriptIncludeParams(script_include_id="sys_id:abc123def456")
        result = get_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual("abc123def456", result["script_include"]["sys_id"])
        self.assertFalse(result["script_include"]["client_callable"])

        mock_query_page.assert_called_once_with(
            self.server_config,
            self.auth_manager,
            table="sys_script_include",
            query="sys_id=abc123def456",
            fields="sys_id,name,script,description,api_name,client_callable,active,access,sys_created_on,sys_updated_on,sys_created_by,sys_updated_by",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_get_script_include_not_found(self, mock_query_page):
        """Test getting a script include that doesn't exist."""
        mock_query_page.return_value = ([], 0)

        params = GetScriptIncludeParams(script_include_id="NonExistent")
        result = get_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_get_script_include_error(self, mock_query_page):
        """Test getting a script include with an error."""
        mock_query_page.side_effect = Exception("Test error")

        params = GetScriptIncludeParams(script_include_id="123")
        result = get_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error getting script include", result["message"])

    # --- create_script_include ---

    @patch("servicenow_mcp.services.script_include.invalidate_query_cache")
    def test_create_script_include_happy(self, mock_invalidate):
        """Test creating a script include successfully."""
        mock_response = self._mock_response(
            {
                "result": {
                    "sys_id": "new123",
                    "name": "TestScriptInclude",
                }
            }
        )
        self.auth_manager.make_request.return_value = mock_response

        params = CreateScriptIncludeParams(
            name="TestScriptInclude",
            script="var TestScriptInclude = Class.create();",
            description="Test Script Include",
            api_name="global.TestScriptInclude",
            client_callable=True,
            active=True,
            access="public",
        )
        result = create_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual("new123", result.script_include_id)
        self.assertEqual("TestScriptInclude", result.script_include_name)

        mock_invalidate.assert_called_once_with(table="sys_script_include")

        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("POST", call_args[0][0])
        self.assertEqual("TestScriptInclude", call_args[1]["json"]["name"])
        self.assertEqual("true", call_args[1]["json"]["client_callable"])
        self.assertEqual("true", call_args[1]["json"]["active"])
        self.assertEqual("public", call_args[1]["json"]["access"])

    @patch("servicenow_mcp.services.script_include.invalidate_query_cache")
    def test_create_script_include_error(self, mock_invalidate):
        """Test creating a script include with an error."""
        self.auth_manager.make_request.side_effect = Exception("Test error")

        params = CreateScriptIncludeParams(
            name="TestScriptInclude",
            script="var TestScriptInclude = Class.create();",
        )
        result = create_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Error creating script include", result.message)
        mock_invalidate.assert_not_called()

    # --- update_script_include ---

    @patch("servicenow_mcp.services.script_include.invalidate_query_cache")
    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_update_script_include_happy(self, mock_query_page, mock_invalidate):
        """Test updating a script include successfully."""
        # Mock the get (via sn_query_page)
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
                    "script": "old script",
                    "description": "Old desc",
                    "api_name": "global.TestScriptInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        # Mock the PATCH response
        mock_patch_response = self._mock_response(
            {
                "result": {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
                }
            }
        )
        self.auth_manager.make_request.return_value = mock_patch_response

        params = UpdateScriptIncludeParams(
            script_include_id="123",
            description="Updated Test Script Include",
            client_callable=False,
        )
        result = update_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual("123", result.script_include_id)
        self.assertEqual("TestScriptInclude", result.script_include_name)
        mock_invalidate.assert_called_once_with(table="sys_script_include")

        # Verify PATCH call
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("PATCH", call_args[0][0])
        self.assertEqual("Updated Test Script Include", call_args[1]["json"]["description"])
        self.assertEqual("false", call_args[1]["json"]["client_callable"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_update_script_include_not_found(self, mock_query_page):
        """Test updating a script include that doesn't exist."""
        mock_query_page.return_value = ([], 0)

        params = UpdateScriptIncludeParams(
            script_include_id="NonExistent",
            script="new script",
        )
        result = update_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("not found", result.message)

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_update_script_include_no_changes(self, mock_query_page):
        """Test updating a script include with no fields to update."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
                    "script": "old",
                    "description": "desc",
                    "api_name": "global.TestScriptInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        params = UpdateScriptIncludeParams(script_include_id="123")
        result = update_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual("123", result.script_include_id)
        self.assertIn("No changes", result.message)
        # make_request should not be called for PATCH
        self.auth_manager.make_request.assert_not_called()

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_update_script_include_error(self, mock_query_page):
        """Test updating a script include with a PATCH error."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
                    "script": "old",
                    "description": "desc",
                    "api_name": "global.TestScriptInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        self.auth_manager.make_request.side_effect = Exception("PATCH error")

        params = UpdateScriptIncludeParams(
            script_include_id="123",
            script="new script",
        )
        result = update_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Error updating script include", result.message)

    # --- delete_script_include ---

    @patch("servicenow_mcp.services.script_include.invalidate_query_cache")
    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_delete_script_include_happy(self, mock_query_page, mock_invalidate):
        """Test deleting a script include successfully."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
                    "script": "old",
                    "description": "desc",
                    "api_name": "global.TestScriptInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        mock_delete_response = MagicMock()
        mock_delete_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_delete_response

        params = DeleteScriptIncludeParams(script_include_id="123")
        result = delete_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual("123", result.script_include_id)
        self.assertEqual("TestScriptInclude", result.script_include_name)
        mock_invalidate.assert_called_once_with(table="sys_script_include")

        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("DELETE", call_args[0][0])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_delete_script_include_not_found(self, mock_query_page):
        """Test deleting a script include that doesn't exist."""
        mock_query_page.return_value = ([], 0)

        params = DeleteScriptIncludeParams(script_include_id="NonExistent")
        result = delete_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("not found", result.message)

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_delete_script_include_error(self, mock_query_page):
        """Test deleting a script include with a DELETE error."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "TestScriptInclude",
                    "script": "old",
                    "description": "desc",
                    "api_name": "global.TestScriptInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        self.auth_manager.make_request.side_effect = Exception("DELETE error")

        params = DeleteScriptIncludeParams(script_include_id="123")
        result = delete_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Error deleting script include", result.message)

    # --- execute_script_include ---

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_script_include_happy(self, mock_query_page):
        """Test executing a client-callable script include successfully."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "CallableInclude",
                    "script": "var CallableInclude = Class.create();",
                    "description": "A callable SI",
                    "api_name": "global.CallableInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        mock_xmlhttp_response = MagicMock()
        mock_xmlhttp_response.text = '{"answer": "42"}'
        mock_xmlhttp_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_xmlhttp_response

        params = ExecuteScriptIncludeParams(
            name="CallableInclude",
            method="getAnswer",
            params={"input": "test"},
        )
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual("Executed CallableInclude.getAnswer", result["message"])
        self.assertEqual({"answer": "42"}, result["result"])

        # Verify the xmlhttp.do call
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("GET", call_args[0][0])
        self.assertIn("/xmlhttp.do", call_args[0][1])
        self.assertEqual("CallableInclude", call_args[1]["params"]["sysparm_ajax_processor"])
        self.assertEqual("getAnswer", call_args[1]["params"]["sysparm_name"])
        self.assertEqual("test", call_args[1]["params"]["sysparm_input"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_script_include_not_found(self, mock_query_page):
        """Test executing a script include that doesn't exist."""
        mock_query_page.return_value = ([], 0)

        params = ExecuteScriptIncludeParams(name="NonExistent")
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_script_include_not_client_callable(self, mock_query_page):
        """Test executing a script include that is not client-callable."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "456",
                    "name": "NonCallableInclude",
                    "script": "var NonCallableInclude = Class.create();",
                    "description": "Not callable",
                    "api_name": "global.NonCallableInclude",
                    "client_callable": "false",
                    "active": "true",
                    "access": "package_private",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        params = ExecuteScriptIncludeParams(name="NonCallableInclude")
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("not client-callable", result["message"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_script_include_error(self, mock_query_page):
        """Test executing a script include with an xmlhttp error."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "CallableInclude",
                    "script": "code",
                    "description": "desc",
                    "api_name": "global.CallableInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        self.auth_manager.make_request.side_effect = Exception("xmlhttp error")

        params = ExecuteScriptIncludeParams(name="CallableInclude")
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error executing script include", result["message"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_script_include_text_response(self, mock_query_page):
        """Test executing a script include that returns non-JSON text."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "CallableInclude",
                    "script": "code",
                    "description": "desc",
                    "api_name": "global.CallableInclude",
                    "client_callable": "true",
                    "active": "true",
                    "access": "public",
                    "sys_created_on": "2023-01-01",
                    "sys_updated_on": "2023-01-02",
                    "sys_created_by": {"display_value": "admin"},
                    "sys_updated_by": {"display_value": "admin"},
                }
            ],
            1,
        )

        mock_xmlhttp_response = MagicMock()
        mock_xmlhttp_response.text = "<html>plain text response</html>"
        mock_xmlhttp_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_xmlhttp_response

        params = ExecuteScriptIncludeParams(name="CallableInclude")
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual("<html>plain text response</html>", result["result"])

    # --- edge cases / response formatting ---

    @patch("servicenow_mcp.tools.script_include_tools.sn_query_page")
    def test_list_script_includes_display_value_none(self, mock_query_page):
        """Test that None display values are handled gracefully."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "789",
                    "name": "NoCreatorSI",
                    "description": None,
                    "api_name": "global.NoCreatorSI",
                    "client_callable": "false",
                    "active": "false",
                    "access": "package_private",
                    "sys_created_on": "",
                    "sys_updated_on": "",
                    "sys_created_by": None,
                    "sys_updated_by": None,
                }
            ],
            1,
        )

        params = ListScriptIncludesParams()
        result = list_script_includes(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertIsNone(result["script_includes"][0]["created_by"])
        self.assertIsNone(result["script_includes"][0]["updated_by"])
        self.assertFalse(result["script_includes"][0]["active"])
        self.assertFalse(result["script_includes"][0]["client_callable"])


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
            script="var TestScriptInclude = Class.create();",
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
            script="var TestScriptInclude = Class.create();",
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

    def test_execute_script_include_params(self):
        """Test execute script include parameters."""
        params = ExecuteScriptIncludeParams(
            name="MySI",
            method="doStuff",
            params={"key": "value"},
        )
        self.assertEqual("MySI", params.name)
        self.assertEqual("doStuff", params.method)
        self.assertEqual({"key": "value"}, params.params)

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


if __name__ == "__main__":
    unittest.main()
