"""Tests for the changeset service layer (services/changeset.py)."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.services import changeset as cs_svc
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _auth(response_body=None):
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic test"}
    if response_body is not None:
        resp = MagicMock()
        resp.json.return_value = response_body
        resp.raise_for_status = MagicMock()
        auth.make_request.return_value = resp
    return auth


class TestCreate(unittest.TestCase):
    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success(self, mock_inv):
        auth = _auth({"result": {"sys_id": "abc", "name": "My CS", "application": "App1"}})
        result = cs_svc.create(_config(), auth, name="My CS", application="App1")
        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["sys_id"], "abc")
        mock_inv.assert_called_once_with(table="sys_update_set")

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success_with_optional_fields(self, mock_inv):
        auth = _auth({"result": {"sys_id": "abc", "name": "CS"}})
        result = cs_svc.create(
            _config(), auth, name="CS", application="App", description="d", developer="dev"
        )
        self.assertTrue(result["success"])
        args, kwargs = auth.make_request.call_args
        self.assertEqual(kwargs["json"]["description"], "d")
        self.assertEqual(kwargs["json"]["developer"], "dev")

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = Exception("Create failed")
        result = cs_svc.create(_config(), auth, name="CS", application="App")
        self.assertFalse(result["success"])
        self.assertIn("Create failed", result["message"])
        mock_inv.assert_not_called()


class TestUpdate(unittest.TestCase):
    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success(self, mock_inv):
        auth = _auth({"result": {"sys_id": "123", "name": "Updated", "state": "in_progress"}})
        result = cs_svc.update(_config(), auth, changeset_id="123", name="Updated")
        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["sys_id"], "123")
        mock_inv.assert_called_once_with(table="sys_update_set")

    def test_no_fields_returns_error(self):
        auth = MagicMock()
        result = cs_svc.update(_config(), auth, changeset_id="123")
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No fields to update")
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.changeset.build_update_preview")
    def test_dry_run(self, mock_preview):
        mock_preview.return_value = {"success": True, "preview": True}
        auth = MagicMock()
        result = cs_svc.update(
            _config(), auth, changeset_id="123", state="in_progress", dry_run=True
        )
        mock_preview.assert_called_once()
        self.assertTrue(result["preview"])
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = Exception("Update failed")
        result = cs_svc.update(_config(), auth, changeset_id="123", name="X")
        self.assertFalse(result["success"])
        self.assertIn("Update failed", result["message"])


class TestCommit(unittest.TestCase):
    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success(self, mock_inv):
        auth = _auth({"result": {"sys_id": "123", "state": "complete"}})
        result = cs_svc.commit(_config(), auth, changeset_id="123", commit_message="ship it")
        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["state"], "complete")
        args, kwargs = auth.make_request.call_args
        self.assertEqual(kwargs["json"]["state"], "complete")
        self.assertEqual(kwargs["json"]["description"], "ship it")
        mock_inv.assert_called_once_with(table="sys_update_set")

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success_no_message(self, mock_inv):
        auth = _auth({"result": {"sys_id": "123", "state": "complete"}})
        result = cs_svc.commit(_config(), auth, changeset_id="123")
        self.assertTrue(result["success"])
        args, kwargs = auth.make_request.call_args
        self.assertNotIn("description", kwargs["json"])

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = Exception("Commit failed")
        result = cs_svc.commit(_config(), auth, changeset_id="123")
        self.assertFalse(result["success"])
        self.assertIn("Commit failed", result["message"])


class TestPublish(unittest.TestCase):
    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success(self, mock_inv):
        auth = _auth({"result": {"sys_id": "123", "state": "published"}})
        result = cs_svc.publish(_config(), auth, changeset_id="123")
        self.assertTrue(result["success"])
        args, kwargs = auth.make_request.call_args
        self.assertEqual(kwargs["json"]["state"], "published")
        mock_inv.assert_called_once_with(table="sys_update_set")

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_with_notes(self, mock_inv):
        auth = _auth({"result": {"sys_id": "123", "state": "published"}})
        result = cs_svc.publish(_config(), auth, changeset_id="123", publish_notes="release v2")
        self.assertTrue(result["success"])
        args, kwargs = auth.make_request.call_args
        self.assertEqual(kwargs["json"]["description"], "release v2")

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = Exception("Publish failed")
        result = cs_svc.publish(_config(), auth, changeset_id="123")
        self.assertFalse(result["success"])
        self.assertIn("Publish failed", result["message"])


class TestAddFile(unittest.TestCase):
    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_success(self, mock_inv):
        auth = _auth(
            {
                "result": {
                    "sys_id": "456",
                    "name": "test.py",
                    "type": "file",
                    "update_set": "123",
                    "payload": "code here",
                }
            }
        )
        result = cs_svc.add_file(
            _config(), auth, changeset_id="123", file_path="test.py", file_content="code here"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["file"]["sys_id"], "456")
        args, kwargs = auth.make_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/api/now/table/sys_update_xml", args[1])
        self.assertEqual(kwargs["json"]["update_set"], "123")
        self.assertEqual(kwargs["json"]["name"], "test.py")
        self.assertEqual(kwargs["json"]["payload"], "code here")
        self.assertEqual(kwargs["json"]["type"], "file")
        mock_inv.assert_called_once_with(table="sys_update_xml")

    @patch("servicenow_mcp.services.changeset.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = Exception("Add failed")
        result = cs_svc.add_file(
            _config(), auth, changeset_id="123", file_path="x.py", file_content="code"
        )
        self.assertFalse(result["success"])
        self.assertIn("Add failed", result["message"])


if __name__ == "__main__":
    unittest.main()
