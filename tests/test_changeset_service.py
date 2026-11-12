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
        result = cs_svc.create(_config(), auth, name="CS", application="App", description="d")
        self.assertTrue(result["success"])
        args, kwargs = auth.make_request.call_args
        self.assertEqual(kwargs["json"]["description"], "d")
        # sys_update_set has no `developer` column — probed live: a filter on it
        # returns every row, so the write was being discarded. The server
        # records the author in sys_created_by.
        self.assertNotIn("developer", kwargs["json"])

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


class TestPublishRetired(unittest.TestCase):
    def test_no_service_writes_a_state_that_does_not_exist(self):
        # sys_update_set.state is in progress, complete or ignore; never published.
        self.assertFalse(hasattr(cs_svc, "publish"))


class TestAddFileRetired(unittest.TestCase):
    def test_no_service_writes_a_caller_typed_entry(self):
        # A caller-typed payload in an update set is a hand-written deploy XML.
        self.assertFalse(hasattr(cs_svc, "add_file"))


if __name__ == "__main__":
    unittest.main()


def _http_error(status, body):
    import requests

    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    err = requests.exceptions.HTTPError(f"{status} Client Error", response=resp)
    return err


def test_a_refused_commit_carries_the_server_reason_and_where_to_look():
    auth = MagicMock()
    auth.get_headers.return_value = {}
    resp = MagicMock()
    resp.raise_for_status.side_effect = _http_error(
        403,
        {
            "error": {
                "message": "Operation Failed",
                "detail": "ACL Exception Update Failed due to security constraints",
            }
        },
    )
    auth.make_request.return_value = resp
    out = cs_svc.commit(_config(), auth, changeset_id="aaaa1111bbbb2222cccc3333dddd4444")
    assert out["success"] is False and out["error"] == "WRITE_REFUSED" and out["http_status"] == 403
    assert "ACL Exception" in out["server_message"]
    assert "not a missing MCP capability" in out["refused_by"]
    assert "business rule" in out["refused_by"]  # a BR abort answers 403 too
    assert any("get_table_automation" in step for step in out["next"])
    assert any("sys_security_acl_role" in step for step in out["next"])


def test_a_refused_update_is_the_same_answer():
    auth = MagicMock()
    auth.get_headers.return_value = {}
    resp = MagicMock()
    resp.raise_for_status.side_effect = _http_error(403, {"error": {"message": "Forbidden"}})
    auth.make_request.return_value = resp
    out = cs_svc.update(
        _config(), auth, changeset_id="aaaa1111bbbb2222cccc3333dddd4444", state="complete"
    )
    assert out["error"] == "WRITE_REFUSED" and out["server_message"] == "Forbidden"


def test_a_server_error_is_not_called_a_permission_refusal():
    auth = MagicMock()
    auth.get_headers.return_value = {}
    resp = MagicMock()
    resp.raise_for_status.side_effect = _http_error(500, {"error": {"message": "boom"}})
    auth.make_request.return_value = resp
    out = cs_svc.commit(_config(), auth, changeset_id="aaaa1111bbbb2222cccc3333dddd4444")
    assert "error" not in out and out["server_message"] == "boom"
