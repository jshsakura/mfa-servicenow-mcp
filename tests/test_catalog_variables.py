"""Tests for the catalog item variables tools (surviving read tool)."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.catalog_variables import (
    ListCatalogItemVariablesParams,
    list_catalog_item_variables,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestListCatalogItemVariables(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=AuthConfig(
                type=AuthType.BASIC,
                basic=BasicAuthConfig(username="admin", password="password"),
            ),
        )
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {"Content-Type": "application/json"}

    @patch("servicenow_mcp.tools.catalog_variables.sn_query_page")
    def test_list_happy_with_details(self, mock_qp):
        records = [
            {
                "sys_id": "var1",
                "name": "variable1",
                "type": "string",
                "question_text": "Variable 1",
                "order": "100",
                "mandatory": "true",
            },
            {
                "sys_id": "var2",
                "name": "variable2",
                "type": "integer",
                "question_text": "Variable 2",
                "order": "200",
                "mandatory": "false",
            },
        ]
        mock_qp.return_value = (records, 2)

        params = ListCatalogItemVariablesParams(
            catalog_item_id="item123",
            include_details=True,
        )
        result = list_catalog_item_variables(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.count, 2)
        self.assertEqual(len(result.variables), 2)
        self.assertEqual(result.variables[0]["sys_id"], "var1")
        self.assertEqual(result.variables[1]["sys_id"], "var2")
        mock_qp.assert_called_once()
        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["table"], "item_option_new")
        self.assertEqual(call_kwargs["query"], "cat_item=item123")
        self.assertEqual(call_kwargs["fields"], "")
        self.assertTrue(call_kwargs["display_value"])
        self.assertEqual(call_kwargs["orderby"], "order")
        self.assertFalse(call_kwargs["fail_silently"])

    @patch("servicenow_mcp.tools.catalog_variables.sn_query_page")
    def test_list_without_details(self, mock_qp):
        mock_qp.return_value = (
            [{"sys_id": "var1", "name": "variable1"}],
            1,
        )

        params = ListCatalogItemVariablesParams(
            catalog_item_id="item123",
            include_details=False,
        )
        result = list_catalog_item_variables(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["fields"], "sys_id,name,type,question_text,order,mandatory")
        self.assertFalse(call_kwargs["display_value"])

    @patch("servicenow_mcp.tools.catalog_variables.sn_query_page")
    def test_list_with_pagination(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "var1"}], 10)

        params = ListCatalogItemVariablesParams(
            catalog_item_id="item123",
            include_details=False,
            limit=10,
            offset=20,
        )
        result = list_catalog_item_variables(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.count, 10)
        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["limit"], 10)
        self.assertEqual(call_kwargs["offset"], 20)

    @patch("servicenow_mcp.tools.catalog_variables.sn_query_page")
    def test_list_limit_capped_at_100(self, mock_qp):
        mock_qp.return_value = ([], 0)

        params = ListCatalogItemVariablesParams(
            catalog_item_id="item123",
            limit=500,
        )
        list_catalog_item_variables(self.config, self.auth_manager, params)

        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["limit"], 100)

    @patch("servicenow_mcp.tools.catalog_variables.sn_query_page")
    def test_list_error(self, mock_qp):
        mock_qp.side_effect = Exception("Network error")

        params = ListCatalogItemVariablesParams(
            catalog_item_id="item123",
        )
        result = list_catalog_item_variables(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertEqual(result.variables, [])
        self.assertIn("Network error", result.message)

    @patch("servicenow_mcp.tools.catalog_variables.sn_query_page")
    def test_list_empty(self, mock_qp):
        mock_qp.return_value = ([], 0)

        params = ListCatalogItemVariablesParams(
            catalog_item_id="nonexistent",
        )
        result = list_catalog_item_variables(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.variables, [])
        self.assertEqual(result.count, 0)
        self.assertEqual(result.message, "Retrieved 0 variables for catalog item")

    @patch("servicenow_mcp.tools.catalog_variables.sn_query_page")
    def test_list_no_total_count(self, mock_qp):
        records = [{"sys_id": "var1"}]
        mock_qp.return_value = (records, None)

        params = ListCatalogItemVariablesParams(
            catalog_item_id="item123",
        )
        result = list_catalog_item_variables(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.count, 1)


if __name__ == "__main__":
    unittest.main()
