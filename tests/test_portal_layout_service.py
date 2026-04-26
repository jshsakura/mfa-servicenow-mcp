"""Tests for services/portal_layout.py service layer."""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import portal_layout as svc
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


class TestCreatePage(unittest.TestCase):
    @patch("servicenow_mcp.services.portal_layout._check_duplicate", return_value=None)
    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_happy(self, mock_inv, mock_dup):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {"result": {"sys_id": "pg1", "id": "landing", "title": "Landing"}}
        )
        result = svc.create_page(_config(), auth, page_id="landing", title="Landing", scope="s1")
        self.assertTrue(result["success"])
        self.assertEqual(result["sys_id"], "pg1")

    @patch(
        "servicenow_mcp.services.portal_layout._check_duplicate",
        return_value={"sys_id": "dup", "sys_scope": "s1"},
    )
    def test_duplicate_blocked(self, mock_dup):
        result = svc.create_page(_config(), _auth(), page_id="existing", title="X", scope="s1")
        self.assertFalse(result["success"])
        self.assertIn("already exists", result["message"])

    @patch("servicenow_mcp.services.portal_layout._check_duplicate", return_value=None)
    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_all_options(self, mock_inv, mock_dup):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {"result": {"sys_id": "pg2", "id": "pub", "title": "Pub"}}
        )
        svc.create_page(
            _config(),
            auth,
            page_id="pub",
            title="Pub",
            scope="s1",
            description="desc",
            css=".x{}",
            internal=True,
            public=True,
            draft=True,
            category="cat1",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["internal"], "true")
        self.assertEqual(body["public"], "true")
        self.assertEqual(body["draft"], "true")
        self.assertEqual(body["category"], "cat1")

    @patch("servicenow_mcp.services.portal_layout._check_duplicate", return_value=None)
    def test_create_fails(self, mock_dup):
        auth = _auth()
        auth.make_request.side_effect = Exception("API error")
        result = svc.create_page(_config(), auth, page_id="x", title="X", scope="s1")
        self.assertFalse(result["success"])


class TestUpdatePage(unittest.TestCase):
    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "pg1", "title": "New"}})
        result = svc.update_page(_config(), auth, sys_id="pg1", title="New")
        self.assertTrue(result["success"])
        self.assertEqual(auth.make_request.call_args[0][0], "PATCH")
        mock_inv.assert_called_once_with(table="sp_page")

    def test_no_fields(self):
        result = svc.update_page(_config(), _auth(), sys_id="pg1")
        self.assertFalse(result["success"])
        self.assertIn("No fields", result["message"])

    @patch("servicenow_mcp.services.portal_layout.build_update_preview")
    def test_dry_run(self, mock_preview):
        mock_preview.return_value = {"dry_run": True}
        result = svc.update_page(_config(), _auth(), sys_id="pg1", title="New", dry_run=True)
        self.assertEqual(result["dry_run"], True)
        mock_preview.assert_called_once()

    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_all_flags(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "pg1", "title": "T"}})
        svc.update_page(
            _config(), auth, sys_id="pg1", internal=False, public=True, draft=False, title="T"
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["internal"], "false")
        self.assertEqual(body["public"], "true")
        self.assertEqual(body["draft"], "false")

    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Timeout")
        result = svc.update_page(_config(), auth, sys_id="pg1", title="X")
        self.assertFalse(result["success"])
        mock_inv.assert_not_called()


class TestCreateContainer(unittest.TestCase):
    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "ct1"}})
        result = svc.create_container(_config(), auth, sp_page="pg1")
        self.assertTrue(result["success"])
        self.assertEqual(result["page"], "pg1")

    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_all_options(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "ct2"}})
        svc.create_container(
            _config(),
            auth,
            sp_page="pg1",
            order=200,
            width="container-fluid",
            css_class="hero",
            background_color="#000",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["width"], "container-fluid")
        self.assertEqual(body["css_class"], "hero")

    def test_error(self):
        auth = _auth()
        auth.make_request.side_effect = Exception("Fail")
        result = svc.create_container(_config(), auth, sp_page="pg1")
        self.assertFalse(result["success"])


class TestCreateRow(unittest.TestCase):
    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "rw1"}})
        result = svc.create_row(_config(), auth, sp_container="ct1")
        self.assertTrue(result["success"])

    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_with_css_class(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "rw2"}})
        svc.create_row(_config(), auth, sp_container="ct1", css_class="row-eq-height")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["css_class"], "row-eq-height")

    def test_error(self):
        auth = _auth()
        auth.make_request.side_effect = Exception("Fail")
        result = svc.create_row(_config(), auth, sp_container="ct1")
        self.assertFalse(result["success"])


class TestCreateColumn(unittest.TestCase):
    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "cl1"}})
        result = svc.create_column(_config(), auth, sp_row="rw1", size=6)
        self.assertTrue(result["success"])
        self.assertEqual(result["size"], 6)

    def test_invalid_size_zero(self):
        result = svc.create_column(_config(), _auth(), sp_row="rw1", size=0)
        self.assertFalse(result["success"])
        self.assertIn("1 and 12", result["message"])

    def test_invalid_size_13(self):
        result = svc.create_column(_config(), _auth(), sp_row="rw1", size=13)
        self.assertFalse(result["success"])

    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_with_css_class(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "cl2"}})
        svc.create_column(_config(), auth, sp_row="rw1", size=4, css_class="col-custom")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["css_class"], "col-custom")

    def test_error(self):
        auth = _auth()
        auth.make_request.side_effect = Exception("Fail")
        result = svc.create_column(_config(), auth, sp_row="rw1", size=6)
        self.assertFalse(result["success"])


class TestPlaceWidget(unittest.TestCase):
    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {"result": {"sys_id": "inst1", "sp_widget": "w1", "sp_column": "c1"}}
        )
        result = svc.place_widget(_config(), auth, sp_widget="w1", sp_column="c1")
        self.assertTrue(result["success"])
        self.assertEqual(result["instance_id"], "inst1")
        mock_inv.assert_called_once_with(table="sp_instance")

    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_with_options(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {"result": {"sys_id": "inst2", "sp_widget": "w1", "sp_column": "c1"}}
        )
        svc.place_widget(
            _config(),
            auth,
            sp_widget="w1",
            sp_column="c1",
            order=3,
            widget_parameters='{"title":"Hi"}',
            css=".w{}",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["widget_parameters"], '{"title":"Hi"}')
        self.assertEqual(body["css"], ".w{}")

    def test_no_result_key(self):
        auth = _auth()
        auth.make_request.return_value = _resp({"error": "bad"})
        result = svc.place_widget(_config(), auth, sp_widget="w1", sp_column="c1")
        self.assertFalse(result["success"])

    def test_error(self):
        auth = _auth()
        auth.make_request.side_effect = Exception("403")
        result = svc.place_widget(_config(), auth, sp_widget="w1", sp_column="c1")
        self.assertFalse(result["success"])


class TestMoveWidget(unittest.TestCase):
    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "inst1"}})
        result = svc.move_widget(_config(), auth, instance_id="inst1", order=5)
        self.assertTrue(result["success"])
        mock_inv.assert_called_once_with(table="sp_instance")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["order"], "5")

    def test_no_changes(self):
        result = svc.move_widget(_config(), _auth(), instance_id="inst1")
        self.assertTrue(result["success"])
        self.assertIn("No changes", result["message"])

    @patch("servicenow_mcp.services.portal_layout.invalidate_query_cache")
    def test_move_column(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "inst1"}})
        svc.move_widget(_config(), auth, instance_id="inst1", sp_column="col-new")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["sp_column"], "col-new")

    def test_no_result_key(self):
        auth = _auth()
        auth.make_request.return_value = _resp({"error": "not found"})
        result = svc.move_widget(_config(), auth, instance_id="inst1", order=1)
        self.assertFalse(result["success"])

    def test_error(self):
        auth = _auth()
        auth.make_request.side_effect = Exception("Timeout")
        result = svc.move_widget(_config(), auth, instance_id="inst1", order=1)
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
