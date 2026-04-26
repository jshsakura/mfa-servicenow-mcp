"""
Tests for the script include tools.

This module contains tests for the surviving read tools (list_script_includes,
get_script_include) after Phase 4.0 wrapper removal.
"""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.script_include_tools import (
    GetScriptIncludeParams,
    ListScriptIncludesParams,
    get_script_include,
    list_script_includes,
)
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestScriptIncludeTools(unittest.TestCase):
    """Tests for the surviving script include tools."""

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
    """Tests for the surviving script include parameters."""

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


if __name__ == "__main__":
    unittest.main()
