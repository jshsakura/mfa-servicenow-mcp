"""Tests for the catalog item variables tools (migrated to shared query helpers)."""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.catalog_variables import (
    CreateCatalogItemVariableParams,
    ListCatalogItemVariablesParams,
    UpdateCatalogItemVariableParams,
    create_catalog_item_variable,
    list_catalog_item_variables,
    update_catalog_item_variable,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_mock_response(data, status_code=200):
    mock = MagicMock()
    mock.json.return_value = data
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    mock.content = json.dumps(data).encode("utf-8")
    return mock


class TestCreateCatalogItemVariable(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_create_happy(self, mock_invalidate):
        mock_response = _make_mock_response(
            {
                "result": {
                    "sys_id": "abc123",
                    "name": "test_variable",
                    "type": "string",
                    "question_text": "Test Variable",
                    "mandatory": "false",
                }
            }
        )
        self.auth_manager.make_request.return_value = mock_response

        params = CreateCatalogItemVariableParams(
            catalog_item_id="item123",
            name="test_variable",
            type="string",
            label="Test Variable",
            mandatory=False,
        )
        result = create_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.variable_id, "abc123")
        self.assertIsNotNone(result.details)
        mock_invalidate.assert_called_once_with(table="item_option_new")
        self.auth_manager.make_request.assert_called_once()
        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "https://test.service-now.com/api/now/table/item_option_new")
        self.assertEqual(kwargs["json"]["cat_item"], "item123")
        self.assertEqual(kwargs["json"]["name"], "test_variable")
        self.assertEqual(kwargs["json"]["type"], "string")
        self.assertEqual(kwargs["json"]["question_text"], "Test Variable")
        self.assertEqual(kwargs["json"]["mandatory"], "false")

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_create_with_optional_params(self, mock_invalidate):
        mock_response = _make_mock_response(
            {
                "result": {
                    "sys_id": "abc123",
                    "name": "test_variable",
                    "type": "reference",
                    "question_text": "Test Reference",
                    "mandatory": "true",
                    "reference": "sys_user",
                    "reference_qual": "active=true",
                    "help_text": "Select a user",
                    "default_value": "admin",
                    "description": "Reference to a user",
                    "order": 100,
                }
            }
        )
        self.auth_manager.make_request.return_value = mock_response

        params = CreateCatalogItemVariableParams(
            catalog_item_id="item123",
            name="test_variable",
            type="reference",
            label="Test Reference",
            mandatory=True,
            help_text="Select a user",
            default_value="admin",
            description="Reference to a user",
            order=100,
            reference_table="sys_user",
            reference_qualifier="active=true",
        )
        result = create_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.variable_id, "abc123")
        mock_invalidate.assert_called_once_with(table="item_option_new")
        call_kwargs = self.auth_manager.make_request.call_args[1]
        self.assertEqual(call_kwargs["json"]["reference"], "sys_user")
        self.assertEqual(call_kwargs["json"]["reference_qual"], "active=true")
        self.assertEqual(call_kwargs["json"]["help_text"], "Select a user")
        self.assertEqual(call_kwargs["json"]["default_value"], "admin")
        self.assertEqual(call_kwargs["json"]["description"], "Reference to a user")
        self.assertEqual(call_kwargs["json"]["order"], 100)

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_create_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Server error")

        params = CreateCatalogItemVariableParams(
            catalog_item_id="item123",
            name="test_variable",
            type="string",
            label="Test Variable",
        )
        result = create_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Server error", result.message)
        mock_invalidate.assert_not_called()

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_create_with_min_max(self, mock_invalidate):
        mock_response = _make_mock_response(
            {"result": {"sys_id": "var1", "name": "qty", "type": "integer"}}
        )
        self.auth_manager.make_request.return_value = mock_response

        params = CreateCatalogItemVariableParams(
            catalog_item_id="item1",
            name="qty",
            type="integer",
            label="Quantity",
            min=1,
            max=100,
            max_length=50,
        )
        result = create_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        call_kwargs = self.auth_manager.make_request.call_args[1]
        self.assertEqual(call_kwargs["json"]["min"], 1)
        self.assertEqual(call_kwargs["json"]["max"], 100)
        self.assertEqual(call_kwargs["json"]["max_length"], 50)
        mock_invalidate.assert_called_once_with(table="item_option_new")


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


class TestUpdateCatalogItemVariable(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_update_happy(self, mock_invalidate):
        mock_response = _make_mock_response(
            {
                "result": {
                    "sys_id": "var1",
                    "question_text": "Updated Variable",
                    "mandatory": "true",
                    "help_text": "This is help text",
                }
            }
        )
        self.auth_manager.make_request.return_value = mock_response

        params = UpdateCatalogItemVariableParams(
            variable_id="var1",
            label="Updated Variable",
            mandatory=True,
            help_text="This is help text",
        )
        result = update_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.variable_id, "var1")
        self.assertIsNotNone(result.details)
        mock_invalidate.assert_called_once_with(table="item_option_new")
        self.auth_manager.make_request.assert_called_once()
        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "PATCH")
        self.assertEqual(
            args[1],
            "https://test.service-now.com/api/now/table/item_option_new/var1",
        )
        self.assertEqual(kwargs["json"]["question_text"], "Updated Variable")
        self.assertEqual(kwargs["json"]["mandatory"], "true")
        self.assertEqual(kwargs["json"]["help_text"], "This is help text")

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_update_no_params(self, mock_invalidate):
        params = UpdateCatalogItemVariableParams(
            variable_id="var1",
        )
        result = update_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertEqual(result.message, "No update parameters provided")
        self.auth_manager.make_request.assert_not_called()
        mock_invalidate.assert_not_called()

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_update_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Not found")

        params = UpdateCatalogItemVariableParams(
            variable_id="var1",
            label="Updated Variable",
        )
        result = update_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Not found", result.message)
        mock_invalidate.assert_not_called()

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_update_all_fields(self, mock_invalidate):
        mock_response = _make_mock_response({"result": {"sys_id": "var1"}})
        self.auth_manager.make_request.return_value = mock_response

        params = UpdateCatalogItemVariableParams(
            variable_id="var1",
            label="New Label",
            mandatory=False,
            help_text="Help",
            default_value="default",
            description="Desc",
            order=50,
            reference_qualifier="active=true",
            max_length=255,
            min=0,
            max=999,
        )
        result = update_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        mock_invalidate.assert_called_once_with(table="item_option_new")
        call_kwargs = self.auth_manager.make_request.call_args[1]
        self.assertEqual(call_kwargs["json"]["question_text"], "New Label")
        self.assertEqual(call_kwargs["json"]["mandatory"], "false")
        self.assertEqual(call_kwargs["json"]["help_text"], "Help")
        self.assertEqual(call_kwargs["json"]["default_value"], "default")
        self.assertEqual(call_kwargs["json"]["description"], "Desc")
        self.assertEqual(call_kwargs["json"]["order"], 50)
        self.assertEqual(call_kwargs["json"]["reference_qual"], "active=true")
        self.assertEqual(call_kwargs["json"]["max_length"], 255)
        self.assertEqual(call_kwargs["json"]["min"], 0)
        self.assertEqual(call_kwargs["json"]["max"], 999)

    @patch("servicenow_mcp.tools.catalog_variables.invalidate_query_cache")
    def test_update_mandatory_false_string(self, mock_invalidate):
        mock_response = _make_mock_response({"result": {"sys_id": "var1"}})
        self.auth_manager.make_request.return_value = mock_response

        params = UpdateCatalogItemVariableParams(
            variable_id="var1",
            mandatory=False,
        )
        result = update_catalog_item_variable(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        call_kwargs = self.auth_manager.make_request.call_args[1]
        self.assertEqual(call_kwargs["json"]["mandatory"], "false")


if __name__ == "__main__":
    unittest.main()
