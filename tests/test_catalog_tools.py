"""Tests for the ServiceNow MCP catalog tools (migrated to shared query helpers)."""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.catalog_tools import (
    CreateCatalogCategoryParams,
    GetCatalogItemParams,
    ListCatalogCategoriesParams,
    ListCatalogItemsParams,
    MoveCatalogItemsParams,
    UpdateCatalogCategoryParams,
    create_catalog_category,
    get_catalog_item,
    get_catalog_item_variables,
    list_catalog_categories,
    list_catalog_items,
    move_catalog_items,
    update_catalog_category,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_mock_response(data, status_code=200):
    mock = MagicMock()
    mock.json.return_value = data
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    mock.content = json.dumps(data).encode("utf-8")
    return mock


class TestListCatalogItems(unittest.TestCase):
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
    def test_list_items_happy(self, mock_qp):
        records = [
            {
                "sys_id": "item1",
                "name": "Laptop",
                "short_description": "Request a new laptop",
                "category": "Hardware",
                "price": "1000",
                "picture": "laptop.jpg",
                "active": "true",
                "order": "100",
            }
        ]
        mock_qp.return_value = (records, 1)

        params = ListCatalogItemsParams(
            limit=10, offset=0, category="Hardware", query="laptop", active=True
        )
        result = list_catalog_items(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["name"], "Laptop")
        self.assertEqual(result["items"][0]["category"], "Hardware")
        self.assertEqual(result["total"], 1)
        mock_qp.assert_called_once()
        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["table"], "sc_cat_item")
        self.assertIn("active=true", call_kwargs["query"])
        self.assertIn("category=Hardware", call_kwargs["query"])
        self.assertIn("short_descriptionLIKElaptop^ORnameLIKElaptop", call_kwargs["query"])
        self.assertTrue(call_kwargs["display_value"])

    @patch("servicenow_mcp.tools.catalog_tools.sn_count")
    def test_list_items_count_only(self, mock_cnt):
        mock_cnt.return_value = 42

        params = ListCatalogItemsParams(limit=10, offset=0, active=True, count_only=True)
        result = list_catalog_items(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 42)
        mock_cnt.assert_called_once_with(
            self.config, self.auth_manager, "sc_cat_item", "active=true"
        )

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_list_items_with_filters(self, mock_qp):
        mock_qp.return_value = ([], 0)

        params = ListCatalogItemsParams(
            limit=5, offset=10, category="Software", active=False, query="office"
        )
        result = list_catalog_items(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["items"], [])
        call_kwargs = mock_qp.call_args[1]
        self.assertNotIn("active=true", call_kwargs["query"])
        self.assertIn("category=Software", call_kwargs["query"])
        self.assertIn("short_descriptionLIKEoffice^ORnameLIKEoffice", call_kwargs["query"])
        self.assertEqual(call_kwargs["limit"], 5)
        self.assertEqual(call_kwargs["offset"], 10)

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_list_items_error(self, mock_qp):
        mock_qp.side_effect = Exception("Network error")

        params = ListCatalogItemsParams(limit=10, offset=0)
        result = list_catalog_items(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertEqual(result["items"], [])
        self.assertIn("Network error", result["message"])

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_list_items_empty(self, mock_qp):
        mock_qp.return_value = ([], 0)

        params = ListCatalogItemsParams(limit=10, offset=0)
        result = list_catalog_items(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["message"], "Retrieved 0 catalog items")


class TestGetCatalogItem(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.catalog_tools.get_catalog_item_variables")
    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_get_item_happy(self, mock_qp, mock_vars):
        records = [
            {
                "sys_id": "item1",
                "name": "Laptop",
                "short_description": "Request a new laptop",
                "description": "Request a new laptop for work",
                "category": "Hardware",
                "price": "1000",
                "picture": "laptop.jpg",
                "active": "true",
                "order": "100",
                "delivery_time": "3 days",
                "availability": "In Stock",
            }
        ]
        mock_qp.return_value = (records, 1)
        mock_vars.return_value = [
            {
                "sys_id": "var1",
                "name": "model",
                "label": "Laptop Model",
                "type": "string",
                "mandatory": "true",
                "default_value": "MacBook Pro",
                "help_text": "Select the laptop model",
                "order": "100",
            }
        ]

        params = GetCatalogItemParams(item_id="item1")
        result = get_catalog_item(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.data["name"], "Laptop")
        self.assertEqual(result.data["category"], "Hardware")
        self.assertEqual(result.data["delivery_time"], "3 days")
        self.assertEqual(len(result.data["variables"]), 1)
        self.assertEqual(result.data["variables"][0]["name"], "model")
        mock_qp.assert_called_once()
        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["table"], "sc_cat_item")
        self.assertEqual(call_kwargs["query"], "sys_id=item1")
        self.assertFalse(call_kwargs["fail_silently"])

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_get_item_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)

        params = GetCatalogItemParams(item_id="nonexistent")
        result = get_catalog_item(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("not found", result.message)
        self.assertIsNone(result.data)

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_get_item_error(self, mock_qp):
        mock_qp.side_effect = Exception("Server error")

        params = GetCatalogItemParams(item_id="item1")
        result = get_catalog_item(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Server error", result.message)
        self.assertIsNone(result.data)


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


class TestListCatalogCategories(unittest.TestCase):
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
    def test_list_categories_happy(self, mock_qp):
        records = [
            {
                "sys_id": "cat1",
                "title": "Hardware",
                "description": "Hardware requests",
                "parent": "",
                "icon": "hardware.png",
                "active": "true",
                "order": "100",
            }
        ]
        mock_qp.return_value = (records, 1)

        params = ListCatalogCategoriesParams(limit=10, offset=0, query="hardware", active=True)
        result = list_catalog_categories(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["categories"]), 1)
        self.assertEqual(result["categories"][0]["title"], "Hardware")
        self.assertEqual(result["categories"][0]["description"], "Hardware requests")
        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["table"], "sc_category")
        self.assertIn("active=true", call_kwargs["query"])
        self.assertIn("titleLIKEhardware^ORdescriptionLIKEhardware", call_kwargs["query"])

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_list_categories_error(self, mock_qp):
        mock_qp.side_effect = Exception("Connection refused")

        params = ListCatalogCategoriesParams(limit=10, offset=0)
        result = list_catalog_categories(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertEqual(result["categories"], [])
        self.assertIn("Connection refused", result["message"])

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_list_categories_empty(self, mock_qp):
        mock_qp.return_value = ([], 0)

        params = ListCatalogCategoriesParams(limit=10, offset=0)
        result = list_catalog_categories(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["categories"], [])

    @patch("servicenow_mcp.tools.catalog_tools.sn_query_page")
    def test_list_categories_no_active_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)

        params = ListCatalogCategoriesParams(limit=10, offset=0, active=False)
        result = list_catalog_categories(self.config, self.auth_manager, params)

        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["query"], "")


class TestCreateCatalogCategory(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_create_category_happy(self, mock_invalidate):
        mock_response = _make_mock_response(
            {
                "result": {
                    "sys_id": "new_cat_id",
                    "title": "Test Category",
                    "description": "Test Description",
                    "parent": "",
                    "icon": "icon-test",
                    "active": "true",
                    "order": "100",
                }
            }
        )
        self.auth_manager.make_request.return_value = mock_response

        params = CreateCatalogCategoryParams(
            title="Test Category",
            description="Test Description",
            icon="icon-test",
            active=True,
            order=100,
        )
        result = create_catalog_category(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.data["title"], "Test Category")
        self.assertEqual(result.data["sys_id"], "new_cat_id")
        mock_invalidate.assert_called_once_with(table="sc_category")
        self.auth_manager.make_request.assert_called_once()
        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "https://example.service-now.com/api/now/table/sc_category")
        self.assertEqual(kwargs["json"]["title"], "Test Category")

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_create_category_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Forbidden")

        params = CreateCatalogCategoryParams(title="Test")
        result = create_catalog_category(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Forbidden", result.message)
        self.assertIsNone(result.data)
        mock_invalidate.assert_not_called()


class TestUpdateCatalogCategory(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_update_category_happy(self, mock_invalidate):
        mock_response = _make_mock_response(
            {
                "result": {
                    "sys_id": "cat_id",
                    "title": "Updated Category",
                    "description": "Updated Description",
                    "parent": "",
                    "icon": "icon-test",
                    "active": "true",
                    "order": "200",
                }
            }
        )
        self.auth_manager.make_request.return_value = mock_response

        params = UpdateCatalogCategoryParams(
            category_id="cat_id",
            title="Updated Category",
            description="Updated Description",
            order=200,
        )
        result = update_catalog_category(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.data["title"], "Updated Category")
        self.assertEqual(result.data["description"], "Updated Description")
        self.assertEqual(result.data["order"], "200")
        mock_invalidate.assert_called_once_with(table="sc_category")
        self.auth_manager.make_request.assert_called_once()
        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "PATCH")
        self.assertEqual(
            args[1], "https://example.service-now.com/api/now/table/sc_category/cat_id"
        )
        self.assertEqual(kwargs["json"]["title"], "Updated Category")
        self.assertEqual(kwargs["json"]["order"], "200")

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_update_category_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Not found")

        params = UpdateCatalogCategoryParams(category_id="bad_id", title="X")
        result = update_catalog_category(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Not found", result.message)
        self.assertIsNone(result.data)
        mock_invalidate.assert_not_called()


class TestMoveCatalogItems(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_move_items_happy(self, mock_invalidate):
        mock_response = _make_mock_response(
            {"result": {"sys_id": "item_id", "category": "target_cat"}}
        )
        self.auth_manager.make_request.return_value = mock_response

        params = MoveCatalogItemsParams(
            item_ids=["item1", "item2", "item3"], target_category_id="target_cat"
        )
        result = move_catalog_items(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.data["moved_items_count"], 3)
        mock_invalidate.assert_called_once_with(table="sc_cat_item")
        self.assertEqual(self.auth_manager.make_request.call_count, 3)
        for i, call in enumerate(self.auth_manager.make_request.call_args_list):
            args, kwargs = call
            self.assertEqual(args[0], "PATCH")
            self.assertEqual(
                args[1],
                f"https://example.service-now.com/api/now/table/sc_cat_item/{params.item_ids[i]}",
            )
            self.assertEqual(kwargs["json"]["category"], "target_cat")

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_move_items_partial(self, mock_invalidate):
        mock_ok = _make_mock_response({"result": {"sys_id": "ok"}})
        mock_ok.raise_for_status = MagicMock()
        mock_fail = MagicMock()
        mock_fail.raise_for_status.side_effect = Exception("Item not found")

        self.auth_manager.make_request.side_effect = [mock_ok, mock_fail, mock_ok]

        params = MoveCatalogItemsParams(
            item_ids=["item1", "item2", "item3"], target_category_id="target_cat"
        )
        result = move_catalog_items(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertIn("Partially moved", result.message)
        self.assertEqual(result.data["moved_items_count"], 2)
        self.assertEqual(len(result.data["failed_items"]), 1)
        self.assertEqual(result.data["failed_items"][0]["item_id"], "item2")
        mock_invalidate.assert_called_once_with(table="sc_cat_item")

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_move_items_all_failed(self, mock_invalidate):
        mock_fail = MagicMock()
        mock_fail.raise_for_status.side_effect = Exception("All items invalid")
        self.auth_manager.make_request.return_value = mock_fail

        params = MoveCatalogItemsParams(
            item_ids=["item1", "item2"], target_category_id="target_cat"
        )
        result = move_catalog_items(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Failed to move", result.message)
        self.assertEqual(len(result.data["failed_items"]), 2)
        mock_invalidate.assert_called_once_with(table="sc_cat_item")

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_move_items_single_item(self, mock_invalidate):
        mock_response = _make_mock_response(
            {"result": {"sys_id": "item1", "category": "target_cat"}}
        )
        self.auth_manager.make_request.return_value = mock_response

        params = MoveCatalogItemsParams(item_ids=["item1"], target_category_id="target_cat")
        result = move_catalog_items(self.config, self.auth_manager, params)

        self.assertTrue(result.success)
        self.assertEqual(result.data["moved_items_count"], 1)
        mock_invalidate.assert_called_once_with(table="sc_cat_item")

    @patch("servicenow_mcp.tools.catalog_tools.invalidate_query_cache")
    def test_move_items_outer_exception(self, mock_invalidate):
        mock_response = _make_mock_response({"result": {"sys_id": "item1"}})
        self.auth_manager.make_request.return_value = mock_response
        mock_invalidate.side_effect = Exception("Cache flush failed")

        params = MoveCatalogItemsParams(item_ids=["item1"], target_category_id="target_cat")
        result = move_catalog_items(self.config, self.auth_manager, params)

        self.assertFalse(result.success)
        self.assertIn("Cache flush failed", result.message)
        self.assertIsNone(result.data)


if __name__ == "__main__":
    unittest.main()
