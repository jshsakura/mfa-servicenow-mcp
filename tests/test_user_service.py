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


class TestHelpers(unittest.TestCase):
    @patch("servicenow_mcp.services.user.sn_query_page")
    def test_lookup_user_id_sys_id(self, mock_qp):
        result = svc._lookup_user_id(_config(), _auth(), "sys_id:123")
        self.assertEqual(result, "123")
        mock_qp.assert_not_called()

    @patch("servicenow_mcp.services.user.sn_query_page")
    def test_lookup_user_id_username(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "u1"}], 1)
        result = svc._lookup_user_id(_config(), _auth(), "alice")
        self.assertEqual(result, "u1")
        self.assertEqual(mock_qp.call_args.kwargs["query"], "user_name=alice")

    @patch("servicenow_mcp.services.user.sn_query_page")
    def test_lookup_user_id_email(self, mock_qp):
        mock_qp.side_effect = [([], 0), ([{"sys_id": "u1"}], 1)]
        result = svc._lookup_user_id(_config(), _auth(), "a@b.com")
        self.assertEqual(result, "u1")
        self.assertEqual(mock_qp.call_count, 2)

    @patch("servicenow_mcp.services.user.sn_query_page")
    def test_lookup_user_id_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = svc._lookup_user_id(_config(), _auth(), "ghost")
        self.assertIsNone(result)

    @patch("servicenow_mcp.services.user.sn_query_page")
    def test_get_role_id(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "r1"}], 1)
        result = svc._get_role_id(_config(), _auth(), "itil")
        self.assertEqual(result, "r1")

    @patch("servicenow_mcp.services.user.sn_query_page")
    def test_has_role(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "hr1"}], 1)
        self.assertTrue(svc._has_role(_config(), _auth(), "u1", "r1"))
        mock_qp.return_value = ([], 0)
        self.assertFalse(svc._has_role(_config(), _auth(), "u1", "r2"))


class TestAssignRoles(unittest.TestCase):
    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    @patch("servicenow_mcp.services.user._has_role", return_value=False)
    @patch("servicenow_mcp.services.user._get_role_id", return_value="r1")
    def test_happy(self, mock_grid, mock_has, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({})
        svc._assign_roles(_config(), auth, "u1", ["itil"])
        auth.make_request.assert_called_once()
        mock_inv.assert_called_once_with(table="sys_user_has_role")

    @patch("servicenow_mcp.services.user._get_role_id", return_value=None)
    def test_role_not_found(self, mock_grid):
        auth = _auth()
        svc._assign_roles(_config(), auth, "u1", ["ghost"])
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.user._has_role", return_value=True)
    @patch("servicenow_mcp.services.user._get_role_id", return_value="r1")
    def test_already_has_role(self, mock_grid, mock_has):
        auth = _auth()
        svc._assign_roles(_config(), auth, "u1", ["itil"])
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.user._has_role", return_value=False)
    @patch("servicenow_mcp.services.user._get_role_id", return_value="r1")
    def test_error(self, mock_grid, mock_has):
        auth = _auth()
        auth.make_request.side_effect = Exception("Fail")
        svc._assign_roles(_config(), auth, "u1", ["itil"])
        auth.make_request.assert_called_once()


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
            title="T",
            department="D",
            manager="mgr1",
            phone="555",
            mobile_phone="556",
            location="loc1",
            password="secret",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["title"], "T")
        self.assertEqual(body["department"], "D")
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

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "u1"}})
        svc.update_user(
            _config(),
            auth,
            user_id="u1",
            user_name="new_alice",
            last_name="NewW",
            title="T2",
            department="D2",
            manager="mgr2",
            phone="111",
            mobile_phone="222",
            location="loc2",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["user_name"], "new_alice")
        self.assertEqual(body["last_name"], "NewW")
        self.assertEqual(body["title"], "T2")
        self.assertEqual(body["department"], "D2")
        self.assertEqual(body["manager"], "mgr2")

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
    def test_dry_run_password_and_roles(self, mock_preview):
        mock_preview.return_value = {}
        result = svc.update_user(
            _config(),
            _auth(),
            user_id="u1",
            password="secret",
            roles=["itil"],
            first_name="X",
            dry_run=True,
        )
        self.assertIn("warnings", result)
        self.assertIn("proposed_roles", result)

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

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "g1"}})
        svc.create_group(
            _config(),
            auth,
            name="Eng",
            description="DESC",
            manager="m1",
            parent="p1",
            type="t1",
            email="e@e.com",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["description"], "DESC")
        self.assertEqual(body["manager"], "m1")
        self.assertEqual(body["parent"], "p1")
        self.assertEqual(body["type"], "t1")
        self.assertEqual(body["email"], "e@e.com")

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

    @patch("servicenow_mcp.services.user.invalidate_query_cache")
    def test_optional_fields(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "g1"}})
        svc.update_group(
            _config(),
            auth,
            group_id="g1",
            description="D2",
            manager="m2",
            parent="p2",
            type="t2",
            email="e2@e.com",
        )
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["description"], "D2")
        self.assertEqual(body["manager"], "m2")

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

    @patch("servicenow_mcp.services.user._lookup_user_id", return_value="u1")
    def test_error(self, mock_lookup):
        auth = _auth()
        auth.make_request.side_effect = Exception("Fail")
        result = svc.remove_members(_config(), auth, group_id="g1", members=["alice"])
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
