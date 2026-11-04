"""Tests for services/catalog.py service layer."""

import contextlib
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


_TYPE_CHOICES = [
    {"value": "6", "label": "Single Line Text"},
    {"value": "8", "label": "Reference"},
    {"value": "7", "label": "CheckBox"},
    {"value": "1", "label": "Yes / No"},
]


@contextlib.contextmanager
def _choices(rows=None):
    """Patch the live sys_choice read that resolves item_option_new.type.

    The read is one query over the table and its parents (``nameIN``); each row
    carries the table that declared it, so the rows here are declared on question.
    """
    rows = _TYPE_CHOICES if rows is None else rows
    with (
        patch(
            "servicenow_mcp.services.choices.table_ancestry",
            return_value=["item_option_new", "question"],
        ),
        patch(
            "servicenow_mcp.services.choices.sn_query_page",
            return_value=([{**r, "name": "question"} for r in rows], None),
        ) as q,
    ):
        yield q


class TestCreateVariable(unittest.TestCase):
    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "v1", "name": "qty"}})
        with _choices():
            result = svc.create_variable(
                _config(),
                auth,
                catalog_item_id="i1",
                name="qty",
                variable_type="6",
                label="Quantity",
            )
        self.assertTrue(result["success"])
        self.assertEqual(result["variable_id"], "v1")
        mock_inv.assert_called_once_with(table="item_option_new")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["cat_item"], "i1")
        self.assertEqual(body["name"], "qty")
        self.assertEqual(body["type"], "6")
        self.assertEqual(body["question_text"], "Quantity")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_label_resolves_to_its_code(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "v1"}})
        for label in ("Single Line Text", "single_line_text", "SINGLE LINE TEXT"):
            with _choices():
                svc.create_variable(
                    _config(), auth, catalog_item_id="i1", name="x", variable_type=label, label="X"
                )
            self.assertEqual(auth.make_request.call_args[1]["json"]["type"], "6")

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_a_word_that_is_not_a_type_is_refused_before_any_write(self, mock_inv):
        # "string" was the documented example and is not a value of the column:
        # the record was created with a type the form cannot render.
        auth = _auth()
        with _choices():
            result = svc.create_variable(
                _config(), auth, catalog_item_id="i1", name="x", variable_type="string", label="X"
            )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "UNKNOWN_VARIABLE_TYPE")
        self.assertIn("6=Single Line Text", result["message"])
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_unreadable_choice_list_blocks_the_write(self, mock_inv):
        auth = _auth()
        with _choices() as q:
            q.side_effect = RuntimeError("403")
            result = svc.create_variable(
                _config(), auth, catalog_item_id="i1", name="x", variable_type="6", label="X"
            )
        self.assertEqual(result["error"], "VARIABLE_TYPE_UNVERIFIED")
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_empty_choice_list_is_not_a_pass(self, mock_inv):
        auth = _auth()
        with _choices(rows=[]):
            result = svc.create_variable(
                _config(), auth, catalog_item_id="i1", name="x", variable_type="6", label="X"
            )
        self.assertEqual(result["error"], "VARIABLE_TYPE_UNVERIFIED")
        auth.make_request.assert_not_called()

    def test_choice_read_targets_the_parent_question_table(self):
        with _choices() as q:
            svc.resolve_variable_type(_config(), _auth(), "6")
        kwargs = q.call_args.kwargs
        self.assertEqual(kwargs["table"], "sys_choice")
        self.assertIn("nameINitem_option_new,question^element=type^", kwargs["query"])
        self.assertFalse(kwargs["fail_silently"])

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "v2"}})
        with _choices():
            svc.create_variable(
                _config(),
                auth,
                catalog_item_id="i1",
                name="ref",
                variable_type="Reference",
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
        self.assertEqual(body["type"], "8")
        self.assertEqual(body["mandatory"], "true")
        self.assertEqual(body["help_text"], "Pick a user")
        self.assertEqual(body["default_value"], "root")
        self.assertEqual(body["description"], "DESC")
        self.assertEqual(body["reference"], "sys_user")
        self.assertEqual(body["reference_qual"], "active=true")
        # item_option_new has no `max_length` column — the platform keeps it in
        # the `attributes` string (measured: 14 live variables carry
        # `max_length=NN` exactly like this). Asserting the old key made the
        # test agree with a write the server was silently discarding.
        self.assertEqual(body["attributes"], "max_length=50")
        self.assertNotIn("max_length", body)
        self.assertEqual(body["scale_min"], 0)
        self.assertEqual(body["scale_max"], 100)
        self.assertEqual(body["order"], 10)

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Timeout")
        with _choices():
            result = svc.create_variable(
                _config(), auth, catalog_item_id="i1", name="x", variable_type="6", label="X"
            )
        self.assertFalse(result["success"])
        self.assertIn("Timeout", result["message"])
        mock_inv.assert_not_called()


class TestUpdateVariableIdentityFields(unittest.TestCase):
    """name / type / reference were in the update schema and silently dropped."""

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_name_type_and_reference_are_written(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "v1"}})
        with _choices():
            result = svc.update_variable(
                _config(),
                auth,
                variable_id="v1",
                variable_name="renamed",
                variable_type="Reference",
                reference_table="sys_user",
            )
        self.assertTrue(result["success"])
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body, {"name": "renamed", "type": "8", "reference": "sys_user"})

    @patch("servicenow_mcp.services.catalog.invalidate_query_cache")
    def test_bad_type_on_update_writes_nothing(self, mock_inv):
        auth = _auth()
        with _choices():
            result = svc.update_variable(
                _config(), auth, variable_id="v1", variable_type="boolean", label="L"
            )
        self.assertEqual(result["error"], "UNKNOWN_VARIABLE_TYPE")
        auth.make_request.assert_not_called()

    def test_label_only_update_does_not_read_choices(self):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "v1"}})
        with _choices() as q, patch("servicenow_mcp.services.catalog.invalidate_query_cache"):
            svc.update_variable(_config(), auth, variable_id="v1", label="L")
        q.assert_not_called()


class TestListTotals(unittest.TestCase):
    """`total` used to be len(page): a page of 3 read as "3 in the catalog"."""

    def test_items_total_is_the_server_count(self):
        rows = [{"sys_id": f"i{n}", "name": "n"} for n in range(3)]
        with patch("servicenow_mcp.services.catalog.sn_query_page", return_value=(rows, 47)):
            result = svc.list_items(_config(), _auth(), limit=3)
        self.assertEqual((result["count"], result["total"]), (3, 47))
        self.assertEqual(result["more"], "44 more; offset=3")

    def test_categories_total_is_the_server_count(self):
        rows = [{"sys_id": "c1", "title": "t"}]
        with patch("servicenow_mcp.services.catalog.sn_query_page", return_value=(rows, 1)):
            result = svc.list_categories(_config(), _auth(), limit=3)
        self.assertEqual((result["count"], result["total"]), (1, 1))
        self.assertNotIn("more", result)

    def test_no_server_count_is_said_not_guessed(self):
        with patch("servicenow_mcp.services.catalog.sn_query_page", return_value=([], None)):
            result = svc.list_categories(_config(), _auth())
        self.assertNotIn("total", result)
        self.assertTrue(result["total_unknown"])

    def test_categories_count_only(self):
        with patch(
            "servicenow_mcp.services.catalog.count_response", return_value={"count": 10}
        ) as cr:
            result = svc.list_categories(_config(), _auth(), count_only=True, active=True)
        self.assertEqual(result, {"count": 10})
        self.assertEqual(cr.call_args.args[2], "sc_category")
        self.assertEqual(cr.call_args.args[3], "active=true")

    def test_category_query_cannot_widen_the_filter(self):
        with patch("servicenow_mcp.services.catalog.sn_query_page", return_value=([], 0)) as q:
            result = svc.list_categories(_config(), _auth(), query="a^ORactive=false")
        self.assertNotIn("^ORactive=false", q.call_args.kwargs["query"])
        self.assertIn("filter_notes", result)


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
        self.assertEqual(body["attributes"], "max_length=10")  # not a column; see create()
        self.assertEqual(body["scale_min"], 1)
        self.assertEqual(body["scale_max"], 100)

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

    @patch("servicenow_mcp.tools.sn_api.sn_count")
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
