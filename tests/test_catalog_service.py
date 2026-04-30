"""Tests for services/catalog.py service layer."""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import catalog as svc
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _auth():
    m = MagicMock(spec=AuthManager)
    m.get_headers.return_value = {"Authorization": "Basic dTpw"}
    return m


def _resp(payload, status=200):
    r = MagicMock()
    r.json.return_value = payload
    r.status_code = status
    r.raise_for_status = MagicMock()
    r.content = json.dumps(payload).encode()
    return r


class TestCreateCategory(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {
                "result": {
                    "sys_id": "cat1",
                    "title": "Hardware",
                    "description": "",
                    "parent": "",
                    "icon": "",
                    "active": "true",
                    "order": "0",
                }
            }
        )
        result = svc.create_category(_config(), auth, title="Hardware", icon="hw")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["title"], "Hardware")
        mock_inv.assert_called_once_with(table="sc_category")
        args = auth.make_request.call_args
        self.assertEqual(args[0][0], "POST")
        self.assertIn("/api/now/table/sc_category", args[0][1])
        self.assertEqual(args[1]["json"]["title"], "Hardware")
        self.assertEqual(args[1]["json"]["icon"], "hw")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Conn fail")
        result = svc.create_category(_config(), auth, title="X")
        self.assertFalse(result["success"])
        self.assertIn("Conn fail", result["message"])
        mock_inv.assert_not_called()

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {
                "result": {
                    "sys_id": "c1",
                    "title": "T",
                    "description": "D",
                    "parent": "p1",
                    "icon": "",
                    "active": "false",
                    "order": "10",
                }
            }
        )
        result = svc.create_category(
            _config(), auth, title="T", description="D", parent="p1", active=False, order=10
        )
        self.assertTrue(result["success"])
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["description"], "D")
        self.assertEqual(body["parent"], "p1")
        self.assertEqual(body["active"], "false")
        self.assertEqual(body["order"], "10")


class TestUpdateCategory(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {
                "result": {
                    "sys_id": "c1",
                    "title": "New",
                    "description": "",
                    "parent": "",
                    "icon": "",
                    "active": "true",
                    "order": "0",
                }
            }
        )
        result = svc.update_category(_config(), auth, category_id="c1", title="New")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["title"], "New")
        mock_inv.assert_called_once_with(table="sc_category")
        args = auth.make_request.call_args
        self.assertEqual(args[0][0], "PATCH")
        self.assertIn("/c1", args[0][1])

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "c1"}})
        svc.update_category(
            _config(),
            auth,
            category_id="c1",
            description="D",
            parent="p1",
            icon="i",
            active=False,
            order=10,
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["description"], "D")
        self.assertEqual(body["parent"], "p1")
        self.assertEqual(body["icon"], "i")
        self.assertEqual(body["active"], "false")
        self.assertEqual(body["order"], "10")

    @patch("servicenow_mcp.services.catalog.build_update_preview")
    def test_dry_run(self, mock_preview):
        mock_preview.return_value = {"success": True, "preview": {}}
        svc.update_category(_config(), _auth(), category_id="c1", title="New", dry_run=True)
        mock_preview.assert_called_once()
        call_kwargs = mock_preview.call_args[1]
        self.assertEqual(call_kwargs["table"], "sc_category")
        self.assertEqual(call_kwargs["sys_id"], "c1")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Fail")
        result = svc.update_category(_config(), auth, category_id="c1", title="X")
        self.assertFalse(result["success"])
        mock_inv.assert_not_called()


class TestUpdateItem(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {"result": {"sys_id": "i1", "name": "Laptop", "price": "999"}}
        )
        result = svc.update_item(_config(), auth, item_id="i1", name="Laptop", price="999")
        self.assertTrue(result["success"])
        mock_inv.assert_called_once_with(table="sc_cat_item")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["name"], "Laptop")
        self.assertEqual(body["price"], "999")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "i1"}})
        svc.update_item(
            _config(),
            auth,
            item_id="i1",
            short_description="S",
            description="D",
            category="c1",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["short_description"], "S")
        self.assertEqual(body["description"], "D")
        self.assertEqual(body["category"], "c1")

    @patch("servicenow_mcp.services.catalog.build_update_preview")
    def test_dry_run(self, mock_preview):
        mock_preview.return_value = {"success": True, "preview": {}}
        svc.update_item(_config(), _auth(), item_id="i1", name="X", dry_run=True)
        call_kwargs = mock_preview.call_args[1]
        self.assertEqual(call_kwargs["table"], "sc_cat_item")
        self.assertEqual(call_kwargs["sys_id"], "i1")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_active_and_order(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "i1"}})
        svc.update_item(_config(), auth, item_id="i1", active=False, order=5)
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["active"], "false")
        self.assertEqual(body["order"], "5")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Err")
        result = svc.update_item(_config(), auth, item_id="i1", name="X")
        self.assertFalse(result["success"])
        mock_inv.assert_not_called()


class TestMoveItems(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_all_success(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {}})
        result = svc.move_items(_config(), auth, item_ids=["i1", "i2"], target_category_id="cat2")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["moved_items_count"], 2)
        self.assertEqual(auth.make_request.call_count, 2)
        mock_inv.assert_called_once_with(table="sc_cat_item")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_partial_failure(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = [_resp({"result": {}}), Exception("404")]
        result = svc.move_items(_config(), auth, item_ids=["i1", "i2"], target_category_id="cat2")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["moved_items_count"], 1)
        self.assertEqual(len(result["data"]["failed_items"]), 1)

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_all_fail(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Err")
        result = svc.move_items(_config(), auth, item_ids=["i1"], target_category_id="cat2")
        self.assertFalse(result["success"])


class TestCreateVariable(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "v1", "name": "qty"}})
        result = svc.create_variable(
            _config(),
            auth,
            catalog_item_id="i1",
            name="qty",
            variable_type="integer",
            label="Quantity",
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["variable_id"], "v1")
        mock_inv.assert_called_once_with(table="item_option_new")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["cat_item"], "i1")
        self.assertEqual(body["name"], "qty")
        self.assertEqual(body["type"], "integer")
        self.assertEqual(body["question_text"], "Quantity")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "v2"}})
        svc.create_variable(
            _config(),
            auth,
            catalog_item_id="i1",
            name="ref",
            variable_type="reference",
            label="User",
            mandatory=True,
            help_text="Pick a user",
            default_value="root",
            description="DESC",
            reference_table="sys_user",
            reference_qualifier="active=true",
            max_length=50,
            min=0,
            max=100,
            order=10,
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["mandatory"], "true")
        self.assertEqual(body["help_text"], "Pick a user")
        self.assertEqual(body["default_value"], "root")
        self.assertEqual(body["description"], "DESC")
        self.assertEqual(body["reference"], "sys_user")
        self.assertEqual(body["reference_qual"], "active=true")
        self.assertEqual(body["max_length"], 50)
        self.assertEqual(body["min"], 0)
        self.assertEqual(body["max"], 100)
        self.assertEqual(body["order"], 10)

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Timeout")
        result = svc.create_variable(
            _config(), auth, catalog_item_id="i1", name="x", variable_type="string", label="X"
        )
        self.assertFalse(result["success"])
        mock_inv.assert_not_called()


class TestUpdateVariable(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "v1"}})
        result = svc.update_variable(
            _config(),
            auth,
            variable_id="v1",
            label="New Label",
            mandatory=False,
            help_text="H",
            default_value="DV",
            description="D",
            order=5,
            reference_qualifier="Q",
            max_length=10,
            min=1,
            max=100,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["variable_id"], "v1")
        mock_inv.assert_called_once_with(table="item_option_new")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["question_text"], "New Label")
        self.assertEqual(body["mandatory"], "false")
        self.assertEqual(body["help_text"], "H")
        self.assertEqual(body["default_value"], "DV")
        self.assertEqual(body["description"], "D")
        self.assertEqual(body["order"], 5)
        self.assertEqual(body["reference_qual"], "Q")
        self.assertEqual(body["max_length"], 10)
        self.assertEqual(body["min"], 1)
        self.assertEqual(body["max"], 100)

    def test_no_fields(self):
        result = svc.update_variable(_config(), _auth(), variable_id="v1")
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No update parameters provided")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("403")
        result = svc.update_variable(_config(), auth, variable_id="v1", label="X")
        self.assertFalse(result["success"])
        mock_inv.assert_not_called()


class TestListItems(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_happy(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "i1", "name": "N"}], 1)
        result = svc.list_items(_config(), _auth(), active=True, category="c1", query="q")
        self.assertTrue(result["success"])
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("active=true", mock_qp.call_args.kwargs["query"])
        self.assertIn("category=c1", mock_qp.call_args.kwargs["query"])

    @patch("servicenow_mcp.services.catalog.sn_count")
    def test_count_only(self, mock_cnt):
        mock_cnt.return_value = 5
        result = svc.list_items(_config(), _auth(), count_only=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 5)

    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_error(self, mock_qp):
        mock_qp.side_effect = Exception("Fail")
        result = svc.list_items(_config(), _auth())
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Fail")


class TestGetItem(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.list_item_variables")
    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_happy(self, mock_qp, mock_vars):
        mock_qp.return_value = ([{"sys_id": "i1", "name": "N"}], 1)
        mock_vars.return_value = [{"sys_id": "v1"}]
        result = svc.get_item(_config(), _auth(), item_id="i1")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["sys_id"], "i1")
        self.assertEqual(result["data"]["variables"], [{"sys_id": "v1"}])

    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = svc.get_item(_config(), _auth(), item_id="i1")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_error(self, mock_qp):
        mock_qp.side_effect = Exception("Fail")
        result = svc.get_item(_config(), _auth(), item_id="i1")
        self.assertFalse(result["success"])


class TestListCategories(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_happy(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "c1", "title": "T"}], 1)
        result = svc.list_categories(_config(), _auth(), active=True, query="q")
        self.assertTrue(result["success"])
        self.assertEqual(len(result["categories"]), 1)

    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_error(self, mock_qp):
        mock_qp.side_effect = Exception("Fail")
        result = svc.list_categories(_config(), _auth())
        self.assertFalse(result["success"])


class TestListItemVariables(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_happy(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "v1", "name": "V"}], 1)
        result = svc.list_item_variables(_config(), _auth(), catalog_item_id="i1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sys_id"], "v1")

    @patch("servicenow_mcp.services.catalog.sn_query_page")
    def test_error(self, mock_qp):
        mock_qp.side_effect = Exception("Fail")
        result = svc.list_item_variables(_config(), _auth(), catalog_item_id="i1")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
