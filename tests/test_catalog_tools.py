"""Tests for the ServiceNow MCP catalog tools (surviving read tools)."""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.catalog_tools import (
    get_catalog_item_variables,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_mock_response(data, status_code=200):
    mock = MagicMock()
    mock.json.return_value = data
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    mock.content = json.dumps(data).encode("utf-8")
    return mock


class TestGetCatalogItemVariables(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://example.service-now.com",
            auth=AuthConfig(
                type=AuthType.BASIC,
                basic=BasicAuthConfig(username="admin", password="password"),
            ),
        )
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {"Authorization": "Basic YWRtaW46cGFzc3dvcmQ="}

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_get_variables_happy(self, mock_qp):
        records = [
            {
                "sys_id": "var1",
                "name": "model",
                "question_text": "Laptop Model",
                "type": "string",
                "mandatory": "true",
                "default_value": "MacBook Pro",
                "help_text": "Select the laptop model",
                "order": "100",
            }
        ]
        mock_qp.return_value = (records, 1)

        result = get_catalog_item_variables(self.config, self.auth_manager, "item1")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "model")
        self.assertEqual(result[0]["label"], "Laptop Model")
        self.assertEqual(result[0]["type"], "string")
        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["table"], "item_option_new")
        self.assertEqual(call_kwargs["query"], "cat_item=item1^ORDERBYorder")

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_get_variables_error(self, mock_qp):
        mock_qp.return_value = ([], None)

        result = get_catalog_item_variables(self.config, self.auth_manager, "item1")

        self.assertEqual(result, [])

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_get_variables_empty(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_catalog_item_variables(self.config, self.auth_manager, "bad_item")

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
