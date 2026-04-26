"""Tests for services/user.py service layer."""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import user as svc
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


class TestCreateUser(unittest.TestCase):
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "u1", "user_name": "alice"}})
        result = svc.create_user(
            _config(), auth, user_name="alice", first_name="Alice", last_name="W", email="a@w.com"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["user_id"], "u1")
        mock_inv.assert_called_once_with(table="sys_user")
        args = auth.make_request.call_args
        self.assertEqual(args[0][0], "POST")
        self.assertIn("/table/sys_user", args[0][1])

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "u1", "user_name": "bob"}})
        svc.create_user(
            _config(),
            auth,
            user_name="bob",
            first_name="Bob",
            last_name="S",
            email="b@x.com",
            manager="mgr1",
            phone="555",
            mobile_phone="556",
            location="loc1",
            password="secret",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["manager"], "mgr1")
        self.assertEqual(body["user_password"], "secret")

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Conn fail")
        result = svc.create_user(
            _config(), auth, user_name="x", first_name="X", last_name="Y", email="x@y.com"
        )
        self.assertFalse(result["success"])
        self.assertIn("Conn fail", result["message"])
        mock_inv.assert_not_called()

    @patch("servicenow_mcp.services.user._assign_roles")
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_with_roles(self, mock_inv, mock_assign):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "u1", "user_name": "alice"}})
        svc.create_user(
            _config(),
            auth,
            user_name="alice",
            first_name="Alice",
            last_name="W",
            email="a@w.com",
            roles=["itil"],
        )
        mock_assign.assert_called_once()


class TestUpdateUser(unittest.TestCase):
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "u1", "user_name": "alice2"}})
        result = svc.update_user(_config(), auth, user_id="u1", email="new@x.com")
        self.assertTrue(result["success"])
        mock_inv.assert_called_once_with(table="sys_user")
        args = auth.make_request.call_args
        self.assertEqual(args[0][0], "PATCH")
        self.assertIn("/u1", args[0][1])

    @patch("servicenow_mcp.services.user.build_update_preview")
    def test_dry_run(self, mock_preview):
        mock_preview.return_value = {"dry_run": True}
        result = svc.update_user(_config(), _auth(), user_id="u1", first_name="Bob", dry_run=True)
        self.assertEqual(result["dry_run"], True)
        mock_preview.assert_called_once()
        kw = mock_preview.call_args[1]
        self.assertEqual(kw["table"], "sys_user")
        self.assertEqual(kw["sys_id"], "u1")

    @patch("servicenow_mcp.services.user.build_update_preview")
    def test_dry_run_password_warning(self, mock_preview):
        mock_preview.return_value = {}
        svc.update_user(
            _config(), _auth(), user_id="u1", password="secret", first_name="X", dry_run=True
        )
        result = mock_preview.return_value
        self.assertIn("warnings", result)

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_active_field(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "u1"}})
        svc.update_user(_config(), auth, user_id="u1", active=False)
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["active"], "false")

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Timeout")
        result = svc.update_user(_config(), auth, user_id="u1", email="x@x.com")
        self.assertFalse(result["success"])
        mock_inv.assert_not_called()


class TestCreateGroup(unittest.TestCase):
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "g1", "name": "Eng"}})
        result = svc.create_group(_config(), auth, name="Eng")
        self.assertTrue(result["success"])
        self.assertEqual(result["group_id"], "g1")
        mock_inv.assert_called_once_with(table="sys_user_group")

    @patch("servicenow_mcp.services.user.add_members")
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_with_members(self, mock_inv, mock_add):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "g1", "name": "Eng"}})
        mock_add.return_value = {"success": True}
        svc.create_group(_config(), auth, name="Eng", members=["alice", "bob"])
        mock_add.assert_called_once()

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Fail")
        result = svc.create_group(_config(), auth, name="X")
        self.assertFalse(result["success"])
        mock_inv.assert_not_called()


class TestUpdateGroup(unittest.TestCase):
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_happy(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "g1", "name": "New"}})
        result = svc.update_group(_config(), auth, group_id="g1", name="New")
        self.assertTrue(result["success"])
        mock_inv.assert_called_once_with(table="sys_user_group")
        args = auth.make_request.call_args
        self.assertEqual(args[0][0], "PATCH")
        self.assertIn("/g1", args[0][1])

    @patch("servicenow_mcp.services.user.build_update_preview")
    def test_dry_run(self, mock_preview):
        mock_preview.return_value = {"dry_run": True}
        svc.update_group(_config(), _auth(), group_id="g1", name="X", dry_run=True)
        kw = mock_preview.call_args[1]
        self.assertEqual(kw["table"], "sys_user_group")
        self.assertEqual(kw["sys_id"], "g1")

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_active_field(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "g1"}})
        svc.update_group(_config(), auth, group_id="g1", active=False)
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["active"], "false")

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("Fail")
        result = svc.update_group(_config(), auth, group_id="g1", name="X")
        self.assertFalse(result["success"])
        mock_inv.assert_not_called()


class TestAddMembers(unittest.TestCase):
    @patch("servicenow_mcp.services.user._lookup_user_id", return_value="u1")
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_all_success(self, mock_inv, mock_lookup):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {}})
        result = svc.add_members(_config(), auth, group_id="g1", members=["alice"])
        self.assertTrue(result["success"])
        mock_inv.assert_called_once_with(table="sys_user_grmember")

    @patch("servicenow_mcp.services.user._lookup_user_id", return_value=None)
    def test_lookup_failure(self, mock_lookup):
        result = svc.add_members(_config(), _auth(), group_id="g1", members=["ghost"])
        self.assertFalse(result["success"])
        self.assertIn("ghost", result["message"])

    @patch("servicenow_mcp.services.user._lookup_user_id", return_value="u1")
    def test_post_failure(self, mock_lookup):
        auth = _auth()
        auth.make_request.side_effect = Exception("403")
        result = svc.add_members(_config(), auth, group_id="g1", members=["alice"])
        self.assertFalse(result["success"])


class TestRemoveMembers(unittest.TestCase):
    @patch("servicenow_mcp.services.user._lookup_user_id", return_value="u1")
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_happy(self, mock_inv, mock_lookup):
        auth = _auth()
        get_resp = _resp({"result": [{"sys_id": "mem1"}]})
        del_resp = _resp({})
        auth.make_request.side_effect = [get_resp, del_resp]
        result = svc.remove_members(_config(), auth, group_id="g1", members=["alice"])
        self.assertTrue(result["success"])
        mock_inv.assert_called_once_with(table="sys_user_grmember")

    @patch("servicenow_mcp.services.user._lookup_user_id", return_value="u1")
    def test_dry_run(self, mock_lookup):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": [{"sys_id": "mem1"}]})
        result = svc.remove_members(_config(), auth, group_id="g1", members=["alice"], dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["would_remove"]), 1)
        self.assertEqual(result["would_remove"][0]["member"], "alice")

    @patch("servicenow_mcp.services.user._lookup_user_id", return_value=None)
    def test_lookup_failure(self, mock_lookup):
        result = svc.remove_members(_config(), _auth(), group_id="g1", members=["ghost"])
        self.assertFalse(result["success"])

    @patch("servicenow_mcp.services.user._lookup_user_id", return_value="u1")
    def test_membership_not_found(self, mock_lookup):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": []})
        result = svc.remove_members(_config(), auth, group_id="g1", members=["alice"])
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
