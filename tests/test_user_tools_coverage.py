"""
Additional tests for user_tools to increase coverage to 80%+.

Covers: create_user with optional fields and error path, update_user with all
optional fields and error path, get_user by email / no params / not found / error,
list_users count_only / query / error, list_groups error, assign_roles_to_user
edge cases (role not found, user already has role, assignment failure),
get_role_id not found / error, check_user_has_role error,
create_group with members and optional fields / error, update_group with all fields / error,
add_group_members with sys_id prefix and lookup failure and POST failure,
remove_group_members with lookup failure and membership not found and DELETE error.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.user_tools import (
    AddGroupMembersParams,
    CreateGroupParams,
    CreateUserParams,
    GetUserParams,
    ListGroupsParams,
    ListUsersParams,
    RemoveGroupMembersParams,
    UpdateGroupParams,
    UpdateUserParams,
    add_group_members,
    assign_roles_to_user,
    check_user_has_role,
    create_group,
    create_user,
    get_role_id,
    get_user,
    list_groups,
    list_users,
    remove_group_members,
    update_group,
    update_user,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


def _make_auth():
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {"Authorization": "Basic YWRtaW46cGFzc3dvcmQ="}
    return auth


def _ok_response(payload, headers=None):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.status_code = 200
    mock.raise_for_status = MagicMock()
    mock.content = json.dumps(payload).encode("utf-8")
    mock.headers = headers or {}
    return mock


class TestCreateUserEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.user_tools.assign_roles_to_user")
    def test_create_user_with_all_optional_fields(self, mock_assign, mock_cache):
        """Cover lines 206-214: manager, phone, mobile_phone, location, password."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "u1", "user_name": "bob"}}
        self.auth.make_request.return_value = resp

        params = CreateUserParams(
            user_name="bob",
            first_name="Bob",
            last_name="Smith",
            email="bob@example.com",
            manager="mgr1",
            phone="555-1234",
            mobile_phone="555-5678",
            location="loc1",
            password="secret",
            roles=["itil", "admin"],
        )
        result = create_user(self.config, self.auth, params)
        self.assertTrue(result.success)
        # Verify optional fields sent in request
        call_kwargs = self.auth.make_request.call_args[1]["json"]
        self.assertEqual(call_kwargs["manager"], "mgr1")
        self.assertEqual(call_kwargs["phone"], "555-1234")
        self.assertEqual(call_kwargs["mobile_phone"], "555-5678")
        self.assertEqual(call_kwargs["location"], "loc1")
        self.assertEqual(call_kwargs["user_password"], "secret")
        mock_assign.assert_called_once()

    def test_create_user_error(self):
        """Cover lines 242-244."""
        self.auth.make_request.side_effect = Exception("Boom")
        params = CreateUserParams(user_name="bob", first_name="B", last_name="S", email="b@x.com")
        result = create_user(self.config, self.auth, params)
        self.assertFalse(result.success)
        self.assertIn("Failed to create user", result.message)


class TestUpdateUserEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.user_tools.assign_roles_to_user")
    def test_update_user_all_fields(self, mock_assign, mock_cache):
        """Cover lines 278-300: all optional update fields."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "u1", "user_name": "bob"}}
        self.auth.make_request.return_value = resp

        params = UpdateUserParams(
            user_id="u1",
            user_name="bob2",
            first_name="Bob",
            last_name="Jones",
            email="bob2@x.com",
            title="Sr Dev",
            department="eng",
            manager="mgr2",
            phone="111",
            mobile_phone="222",
            location="loc2",
            password="newsecret",
            active=False,
            roles=["admin"],
        )
        result = update_user(self.config, self.auth, params)
        self.assertTrue(result.success)
        call_kwargs = self.auth.make_request.call_args[1]["json"]
        self.assertEqual(call_kwargs["user_name"], "bob2")
        self.assertEqual(call_kwargs["active"], "false")
        self.assertEqual(call_kwargs["user_password"], "newsecret")
        mock_assign.assert_called_once_with(self.config, self.auth, "u1", ["admin"])

    def test_update_user_error(self):
        """Cover lines 328-330."""
        self.auth.make_request.side_effect = Exception("Fail")
        params = UpdateUserParams(user_id="u1", first_name="X")
        result = update_user(self.config, self.auth, params)
        self.assertFalse(result.success)


class TestGetUserEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_get_user_by_email(self):
        """Cover line 366-367: email-based lookup."""
        resp = _ok_response(
            {"result": [{"sys_id": "u1", "email": "a@b.com"}]},
            {"X-Total-Count": "1"},
        )
        self.auth.make_request.return_value = resp
        result = get_user(self.config, self.auth, GetUserParams(email="a@b.com"))
        self.assertTrue(result["success"])

    def test_get_user_no_params(self):
        """Cover lines 368-369: no search params."""
        result = get_user(self.config, self.auth, GetUserParams())
        self.assertFalse(result["success"])
        self.assertIn("At least one", result["message"])

    def test_get_user_not_found(self):
        """Cover lines 384-385: user not found."""
        resp = _ok_response({"result": []}, {"X-Total-Count": "0"})
        self.auth.make_request.return_value = resp
        result = get_user(self.config, self.auth, GetUserParams(user_id="none"))
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    def test_get_user_exception(self):
        """Cover lines 389-391."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = get_user(self.config, self.auth, GetUserParams(user_id="u1"))
        self.assertFalse(result["success"])


class TestListUsersEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.sn_count", return_value=99)
    def test_count_only(self, mock_count):
        """Cover lines 430-432: count_only branch."""
        params = ListUsersParams(count_only=True, active=True)
        result = list_users(self.config, self.auth, params)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 99)

    def test_list_users_with_query(self):
        """Cover line 423-426: query filter branch."""
        resp = _ok_response({"result": []}, {"X-Total-Count": "0"})
        self.auth.make_request.return_value = resp
        params = ListUsersParams(query="alice")
        result = list_users(self.config, self.auth, params)
        self.assertTrue(result["success"])

    def test_list_users_error(self):
        """Cover lines 456-458."""
        self.auth.make_request.side_effect = Exception("Fail")
        params = ListUsersParams()
        result = list_users(self.config, self.auth, params)
        self.assertFalse(result["success"])


class TestListGroupsEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_list_groups_error(self):
        """Cover lines 517-519."""
        self.auth.make_request.side_effect = Exception("Fail")
        params = ListGroupsParams()
        result = list_groups(self.config, self.auth, params)
        self.assertFalse(result["success"])


class TestAssignRolesToUserEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.check_user_has_role")
    @patch("servicenow_mcp.tools.user_tools.get_role_id")
    def test_role_not_found(self, mock_get_role, mock_check):
        """Cover lines 549-550: role not found, skipped."""
        mock_get_role.return_value = None
        result = assign_roles_to_user(self.config, self.auth, "u1", ["nonexistent"])
        self.assertTrue(result)
        mock_check.assert_not_called()

    @patch("servicenow_mcp.tools.user_tools.check_user_has_role", return_value=True)
    @patch("servicenow_mcp.tools.user_tools.get_role_id", return_value="r1")
    def test_user_already_has_role(self, mock_get_role, mock_check):
        """Cover lines 553-555: user already has role."""
        result = assign_roles_to_user(self.config, self.auth, "u1", ["itil"])
        self.assertTrue(result)
        self.auth.make_request.assert_not_called()

    @patch("servicenow_mcp.tools.user_tools.check_user_has_role", return_value=False)
    @patch("servicenow_mcp.tools.user_tools.get_role_id", return_value="r1")
    def test_role_assignment_failure(self, mock_get_role, mock_check):
        """Cover lines 573-575: POST to assign role raises."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = assign_roles_to_user(self.config, self.auth, "u1", ["itil"])
        self.assertFalse(result)


class TestGetRoleIdEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_role_not_found(self):
        """Cover lines 612-613."""
        resp = _ok_response({"result": []}, {"X-Total-Count": "0"})
        self.auth.make_request.return_value = resp
        result = get_role_id(self.config, self.auth, "nonexistent")
        self.assertIsNone(result)

    def test_exception(self):
        """Cover lines 616-618."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = get_role_id(self.config, self.auth, "itil")
        self.assertIsNone(result)


class TestCheckUserHasRoleEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_exception_returns_false(self):
        """Cover lines 653-655."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = check_user_has_role(self.config, self.auth, "u1", "r1")
        self.assertFalse(result)


class TestCreateGroupEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.user_tools.add_group_members")
    def test_create_group_with_all_optional_fields_and_members(self, mock_add, mock_cache):
        """Cover lines 694-698, 716: parent, type, email, members."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "g1", "name": "Eng"}}
        self.auth.make_request.return_value = resp

        params = CreateGroupParams(
            name="Eng",
            description="Engineering",
            manager="mgr1",
            parent="parent_g",
            type="it",
            email="eng@x.com",
            members=["alice", "bob"],
        )
        result = create_group(self.config, self.auth, params)
        self.assertTrue(result.success)
        mock_add.assert_called_once()

    def test_create_group_error(self):
        """Cover lines 731-733."""
        self.auth.make_request.side_effect = Exception("Fail")
        params = CreateGroupParams(name="Eng")
        result = create_group(self.config, self.auth, params)
        self.assertFalse(result.success)


class TestUpdateGroupEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_update_group_all_fields(self, mock_cache):
        """Cover lines 767-779: all optional fields."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "g1", "name": "Eng"}}
        self.auth.make_request.return_value = resp

        params = UpdateGroupParams(
            group_id="g1",
            name="Eng2",
            description="Updated",
            manager="mgr2",
            parent="pg2",
            type="admin",
            email="eng2@x.com",
            active=False,
        )
        result = update_group(self.config, self.auth, params)
        self.assertTrue(result.success)
        call_kwargs = self.auth.make_request.call_args[1]["json"]
        self.assertEqual(call_kwargs["active"], "false")
        self.assertEqual(call_kwargs["parent"], "pg2")
        self.assertEqual(call_kwargs["type"], "admin")
        self.assertEqual(call_kwargs["email"], "eng2@x.com")

    def test_update_group_error(self):
        """Cover lines 802-804."""
        self.auth.make_request.side_effect = Exception("Fail")
        params = UpdateGroupParams(group_id="g1", name="X")
        result = update_group(self.config, self.auth, params)
        self.assertFalse(result.success)


class TestAddGroupMembersEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.get_user")
    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_member_with_sysid_prefix(self, mock_cache, mock_get_user):
        """Cover line 841: member starts with 'sys_id:'."""
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        self.auth.make_request.return_value = resp

        params = AddGroupMembersParams(group_id="g1", members=["sys_id:u1"])
        result = add_group_members(self.config, self.auth, params)
        self.assertTrue(result.success)
        mock_get_user.assert_not_called()

    @patch("servicenow_mcp.tools.user_tools.get_user")
    def test_user_lookup_fails_both_ways(self, mock_get_user):
        """Cover lines 844-851: username and email lookups both fail."""
        mock_get_user.return_value = {"success": False, "message": "Not found"}
        params = AddGroupMembersParams(group_id="g1", members=["unknown_user"])
        result = add_group_members(self.config, self.auth, params)
        self.assertFalse(result.success)
        self.assertIn("unknown_user", result.message)

    @patch("servicenow_mcp.tools.user_tools.get_user")
    def test_post_failure(self, mock_get_user):
        """Cover lines 868-871: POST to add member raises."""
        mock_get_user.return_value = {"success": True, "user": {"sys_id": "u1"}}
        self.auth.make_request.side_effect = Exception("Fail")
        params = AddGroupMembersParams(group_id="g1", members=["alice"])
        result = add_group_members(self.config, self.auth, params)
        self.assertFalse(result.success)


class TestRemoveGroupMembersEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.get_user")
    def test_user_lookup_fails(self, mock_get_user):
        """Cover lines 920-927: user lookup fails for remove."""
        mock_get_user.return_value = {"success": False, "message": "Not found"}
        params = RemoveGroupMembersParams(group_id="g1", members=["unknown"])
        result = remove_group_members(self.config, self.auth, params)
        self.assertFalse(result.success)
        self.assertIn("unknown", result.message)

    @patch("servicenow_mcp.tools.user_tools.get_user")
    def test_membership_not_found(self, mock_get_user):
        """Cover lines 949-951: GET returns empty result for membership."""
        mock_get_user.return_value = {"success": True, "user": {"sys_id": "u1"}}
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"result": []}
        self.auth.make_request.return_value = resp

        params = RemoveGroupMembersParams(group_id="g1", members=["alice"])
        result = remove_group_members(self.config, self.auth, params)
        self.assertFalse(result.success)

    @patch("servicenow_mcp.tools.user_tools.get_user")
    def test_delete_exception(self, mock_get_user):
        """Cover lines 965-968: DELETE raises exception."""
        mock_get_user.return_value = {"success": True, "user": {"sys_id": "u1"}}
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()
        get_resp.json.return_value = {"result": [{"sys_id": "mem1"}]}

        self.auth.make_request.side_effect = [get_resp, Exception("Delete fail")]
        params = RemoveGroupMembersParams(group_id="g1", members=["alice"])
        result = remove_group_members(self.config, self.auth, params)
        self.assertFalse(result.success)

    @patch("servicenow_mcp.tools.user_tools.get_user")
    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_remove_with_sysid_prefix(self, mock_cache, mock_get_user):
        """Cover line 917: member starts with 'sys_id:'."""
        get_resp = MagicMock()
        get_resp.raise_for_status = MagicMock()
        get_resp.json.return_value = {"result": [{"sys_id": "mem1"}]}
        del_resp = MagicMock()
        del_resp.raise_for_status = MagicMock()
        self.auth.make_request.side_effect = [get_resp, del_resp]

        params = RemoveGroupMembersParams(group_id="g1", members=["sys_id:u1"])
        result = remove_group_members(self.config, self.auth, params)
        self.assertTrue(result.success)
        mock_get_user.assert_not_called()


if __name__ == "__main__":
    unittest.main()
