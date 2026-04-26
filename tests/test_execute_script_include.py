"""
Tests for the execute_script_include function.

This module contains tests for executing client-callable script includes
via the GlideAjax REST endpoint.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.script_include_tools import (
    ExecuteScriptIncludeParams,
    execute_script_include,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

_SI_CALLABLE = [{"sys_id": "si123", "name": "MyAjaxUtil", "client_callable": "true"}]
_SI_NOT_CALLABLE = [{"sys_id": "si456", "name": "ServerOnlySI", "client_callable": "false"}]


class TestExecuteScriptInclude(unittest.TestCase):
    """Tests for the execute_script_include function."""

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

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_success_json_response(self, mock_qp):
        """Test executing a script include that returns JSON."""
        mock_qp.return_value = (_SI_CALLABLE, 1)

        exec_response = MagicMock()
        exec_response.text = json.dumps({"answer": "42", "status": "ok"})
        exec_response.status_code = 200
        self.auth_manager.make_request.return_value = exec_response

        params = ExecuteScriptIncludeParams(
            name="MyAjaxUtil",
            method="getAnswer",
            params={"question": "everything"},
        )
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual("Executed MyAjaxUtil.getAnswer", result["message"])
        self.assertEqual({"answer": "42", "status": "ok"}, result["result"])

        # Verify the GlideAjax request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("GET", call_args[0][0])
        self.assertIn("/xmlhttp.do", call_args[0][1])
        req_params = call_args[1]["params"]
        self.assertEqual("MyAjaxUtil", req_params["sysparm_ajax_processor"])
        self.assertEqual("getAnswer", req_params["sysparm_name"])
        self.assertEqual("everything", req_params["sysparm_question"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_success_text_response(self, mock_qp):
        """Test executing a script include that returns non-JSON text."""
        mock_qp.return_value = (_SI_CALLABLE, 1)

        exec_response = MagicMock()
        exec_response.text = "<xml><answer>hello</answer></xml>"
        exec_response.status_code = 200
        self.auth_manager.make_request.return_value = exec_response

        params = ExecuteScriptIncludeParams(
            name="MyAjaxUtil",
            method="execute",
        )
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual("<xml><answer>hello</answer></xml>", result["result"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_default_method(self, mock_qp):
        """Test that the default method is 'execute'."""
        mock_qp.return_value = (_SI_CALLABLE, 1)

        exec_response = MagicMock()
        exec_response.text = "{}"
        exec_response.status_code = 200
        self.auth_manager.make_request.return_value = exec_response

        params = ExecuteScriptIncludeParams(name="MyAjaxUtil")
        self.assertEqual("execute", params.method)

        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        req_params = self.auth_manager.make_request.call_args[1]["params"]
        self.assertEqual("execute", req_params["sysparm_name"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_script_include_not_found(self, mock_qp):
        """Test executing a script include that doesn't exist."""
        mock_qp.return_value = ([], None)

        params = ExecuteScriptIncludeParams(
            name="NonExistent",
            method="execute",
        )
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Script include not found", result["message"])
        self.assertIn("NonExistent", result["message"])
        self.auth_manager.make_request.assert_not_called()

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_not_client_callable(self, mock_qp):
        """Test executing a script include that is not client-callable."""
        mock_qp.return_value = (_SI_NOT_CALLABLE, 1)

        params = ExecuteScriptIncludeParams(
            name="ServerOnlySI",
            method="execute",
        )
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("not client-callable", result["message"])
        self.assertIn("ServerOnlySI", result["message"])
        self.auth_manager.make_request.assert_not_called()

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_request_error(self, mock_qp):
        """Test executing a script include when the request fails."""
        mock_qp.return_value = (_SI_CALLABLE, 1)
        self.auth_manager.make_request.side_effect = Exception("Connection timeout")

        params = ExecuteScriptIncludeParams(
            name="MyAjaxUtil",
            method="execute",
        )
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error executing script include", result["message"])
        self.assertIn("Connection timeout", result["message"])

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_no_params(self, mock_qp):
        """Test executing a script include without additional params."""
        mock_qp.return_value = (_SI_CALLABLE, 1)

        exec_response = MagicMock()
        exec_response.text = '{"result": "done"}'
        exec_response.status_code = 200
        self.auth_manager.make_request.return_value = exec_response

        params = ExecuteScriptIncludeParams(
            name="MyAjaxUtil",
            method="doWork",
        )
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        req_params = self.auth_manager.make_request.call_args[1]["params"]
        self.assertEqual(
            {"sysparm_ajax_processor": "MyAjaxUtil", "sysparm_name": "doWork"},
            req_params,
        )

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_execute_with_multiple_params(self, mock_qp):
        """Test executing a script include with multiple user-supplied params."""
        mock_qp.return_value = (_SI_CALLABLE, 1)

        exec_response = MagicMock()
        exec_response.text = '{"status": "ok"}'
        exec_response.status_code = 200
        self.auth_manager.make_request.return_value = exec_response

        params = ExecuteScriptIncludeParams(
            name="MyAjaxUtil",
            method="lookup",
            params={"table": "incident", "field": "number", "value": "INC0012345"},
        )
        result = execute_script_include(self.server_config, self.auth_manager, params)

        self.assertTrue(result["success"])
        req_params = self.auth_manager.make_request.call_args[1]["params"]
        self.assertEqual("incident", req_params["sysparm_table"])
        self.assertEqual("number", req_params["sysparm_field"])
        self.assertEqual("INC0012345", req_params["sysparm_value"])


class TestExecuteScriptIncludeParams(unittest.TestCase):
    """Tests for the ExecuteScriptIncludeParams model."""

    def test_required_fields(self):
        """Test params with only required fields."""
        params = ExecuteScriptIncludeParams(name="MyAjaxUtil")
        self.assertEqual("MyAjaxUtil", params.name)
        self.assertEqual("execute", params.method)
        self.assertIsNone(params.params)

    def test_all_fields(self):
        """Test params with all fields."""
        params = ExecuteScriptIncludeParams(
            name="MyAjaxUtil",
            method="getAnswer",
            params={"key": "value"},
        )
        self.assertEqual("MyAjaxUtil", params.name)
        self.assertEqual("getAnswer", params.method)
        self.assertEqual({"key": "value"}, params.params)

    def test_custom_method(self):
        """Test params with a custom method name."""
        params = ExecuteScriptIncludeParams(
            name="TestSI",
            method="customMethod",
        )
        self.assertEqual("customMethod", params.method)
