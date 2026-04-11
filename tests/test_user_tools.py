"""
Tests for user management tools.
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


class TestUserTools(unittest.TestCase):
    """Tests for user management tools."""

    def setUp(self):
        """Set up test environment."""
        # Create config and auth manager
        self.config = ServerConfig(
            instance_url="https://example.service-now.com",
            auth=AuthConfig(
                type=AuthType.BASIC,
                basic=BasicAuthConfig(username="admin", password="password"),
            ),
        )
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {
            "Authorization": "Basic YWRtaW46cGFzc3dvcmQ=",
        }

    def _finalize_response(self, mock_response):
        payload = mock_response.json.return_value
        mock_response.content = json.dumps(payload).encode("utf-8")
        mock_response.headers = getattr(mock_response, "headers", {}) or {}
        mock_response.raise_for_status = MagicMock()

    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_create_user(self, mock_invalidate_query_cache):
        """Test create_user function."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "user123",
                "user_name": "alice.radiology",
            }
        }
        self.auth_manager.make_request.return_value = mock_response

        # Create test params
        params = CreateUserParams(
            user_name="alice.radiology",
            first_name="Alice",
            last_name="Radiology",
            email="alice@example.com",
            department="Radiology",
            title="Doctor",
        )

        # Call function
        result = create_user(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.user_id, "user123")
        self.assertEqual(result.user_name, "alice.radiology")

        # Verify mock was called correctly
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "POST")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user")
        self.assertEqual(call_args[1]["json"]["user_name"], "alice.radiology")
        self.assertEqual(call_args[1]["json"]["first_name"], "Alice")
        self.assertEqual(call_args[1]["json"]["last_name"], "Radiology")
        self.assertEqual(call_args[1]["json"]["email"], "alice@example.com")
        self.assertEqual(call_args[1]["json"]["department"], "Radiology")
        self.assertEqual(call_args[1]["json"]["title"], "Doctor")
        mock_invalidate_query_cache.assert_called_once_with(table="sys_user")

    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_update_user(self, mock_invalidate_query_cache):
        """Test update_user function."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "user123",
                "user_name": "alice.radiology",
            }
        }
        self.auth_manager.make_request.return_value = mock_response

        # Create test params
        params = UpdateUserParams(
            user_id="user123",
            manager="user456",
            title="Senior Doctor",
        )

        # Call function
        result = update_user(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.user_id, "user123")
        self.assertEqual(result.user_name, "alice.radiology")

        # Verify mock was called correctly
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "PATCH")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user/user123")
        self.assertEqual(call_args[1]["json"]["manager"], "user456")
        self.assertEqual(call_args[1]["json"]["title"], "Senior Doctor")
        mock_invalidate_query_cache.assert_called_once_with(table="sys_user")

    def test_get_user(self):
        """Test get_user function."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "user123",
                    "user_name": "alice.radiology",
                    "first_name": "Alice",
                    "last_name": "Radiology",
                    "email": "alice@example.com",
                }
            ]
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Create test params
        params = GetUserParams(
            user_name="alice.radiology",
        )

        # Call function
        result = get_user(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result["success"])
        self.assertEqual(result["user"]["sys_id"], "user123")
        self.assertEqual(result["user"]["user_name"], "alice.radiology")

        # Verify mock was called correctly
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "GET")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user")
        self.assertEqual(call_args[1]["params"]["sysparm_query"], "user_name=alice.radiology")
        self.assertEqual(call_args[1]["params"]["sysparm_display_value"], "true")

    def test_list_users(self):
        """Test list_users function."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "user123",
                    "user_name": "alice.radiology",
                },
                {
                    "sys_id": "user456",
                    "user_name": "bob.chiefradiology",
                },
            ]
        }
        mock_response.headers = {"X-Total-Count": "2"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Create test params
        params = ListUsersParams(
            department="Radiology",
            limit=10,
        )

        # Call function
        result = list_users(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result["success"])
        self.assertEqual(len(result["users"]), 2)
        self.assertEqual(result["users"][0]["sys_id"], "user123")
        self.assertEqual(result["users"][1]["sys_id"], "user456")

        # Verify mock was called correctly
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "GET")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user")
        self.assertEqual(call_args[1]["params"]["sysparm_limit"], 10)
        self.assertEqual(call_args[1]["params"]["sysparm_offset"], 0)
        self.assertEqual(call_args[1]["params"]["sysparm_display_value"], "true")
        self.assertIn("department=Radiology", call_args[1]["params"]["sysparm_query"])
        self.assertEqual(result["total"], 2)

    def test_list_groups(self):
        """Test list_groups function."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "group123",
                    "name": "IT Support",
                    "description": "IT support team",
                    "active": "true",
                    "type": "it",
                },
                {
                    "sys_id": "group456",
                    "name": "HR Team",
                    "description": "Human Resources team",
                    "active": "true",
                    "type": "administrative",
                },
            ]
        }
        mock_response.headers = {"X-Total-Count": "2"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Create test params
        params = ListGroupsParams(
            active=True,
            type="it",
            query="support",
            limit=10,
        )

        # Call function
        result = list_groups(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result["success"])
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(result["groups"][0]["sys_id"], "group123")
        self.assertEqual(result["groups"][1]["sys_id"], "group456")
        self.assertEqual(result["count"], 2)

        # Verify mock was called correctly
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "GET")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user_group")
        self.assertEqual(call_args[1]["params"]["sysparm_limit"], 10)
        self.assertEqual(call_args[1]["params"]["sysparm_offset"], 0)
        self.assertEqual(call_args[1]["params"]["sysparm_display_value"], "true")
        self.assertIn("active=true", call_args[1]["params"]["sysparm_query"])
        self.assertIn("type=it", call_args[1]["params"]["sysparm_query"])
        self.assertIn("nameLIKE", call_args[1]["params"]["sysparm_query"])
        self.assertIn("descriptionLIKE", call_args[1]["params"]["sysparm_query"])
        self.assertEqual(result["total"], 2)

    def test_get_user_reuses_shared_query_cache(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "user123",
                    "user_name": "alice.radiology",
                    "email": "alice@example.com",
                }
            ]
        }
        mock_response.headers = {"X-Total-Count": "1"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        params = GetUserParams(user_name="alice.radiology")

        first = get_user(self.config, self.auth_manager, params)
        second = get_user(self.config, self.auth_manager, params)

        self.assertTrue(first["success"])
        self.assertEqual(first, second)
        self.assertEqual(self.auth_manager.make_request.call_count, 1)

    def test_get_role_id_reuses_shared_query_cache(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": [{"sys_id": "role123"}]}
        mock_response.headers = {"X-Total-Count": "1"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        first = get_role_id(self.config, self.auth_manager, "itil")
        second = get_role_id(self.config, self.auth_manager, "itil")

        self.assertEqual(first, "role123")
        self.assertEqual(second, "role123")
        self.assertEqual(self.auth_manager.make_request.call_count, 1)

    def test_check_user_has_role_reuses_shared_query_cache(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": [{"sys_id": "uhr123"}]}
        mock_response.headers = {"X-Total-Count": "1"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        first = check_user_has_role(self.config, self.auth_manager, "user123", "role123")
        second = check_user_has_role(self.config, self.auth_manager, "user123", "role123")

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertEqual(self.auth_manager.make_request.call_count, 1)

    def test_check_user_has_role_returns_false_when_empty(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": []}
        mock_response.headers = {"X-Total-Count": "0"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        result = check_user_has_role(self.config, self.auth_manager, "user123", "role123")

        self.assertFalse(result)

    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_create_group(self, mock_invalidate_query_cache):
        """Test create_group function."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "group123",
                "name": "Biomedical Engineering",
            }
        }
        self.auth_manager.make_request.return_value = mock_response

        # Create test params
        params = CreateGroupParams(
            name="Biomedical Engineering",
            description="Group for biomedical engineering staff",
            manager="user456",
        )

        # Call function
        result = create_group(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.group_id, "group123")
        self.assertEqual(result.group_name, "Biomedical Engineering")

        # Verify mock was called correctly
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "POST")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user_group")
        self.assertEqual(call_args[1]["json"]["name"], "Biomedical Engineering")
        self.assertEqual(
            call_args[1]["json"]["description"], "Group for biomedical engineering staff"
        )
        self.assertEqual(call_args[1]["json"]["manager"], "user456")
        mock_invalidate_query_cache.assert_called_once_with(table="sys_user_group")

    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_update_group(self, mock_invalidate_query_cache):
        """Test update_group function."""
        # Configure mock
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "group123",
                "name": "Biomedical Engineering",
            }
        }
        self.auth_manager.make_request.return_value = mock_response

        # Create test params
        params = UpdateGroupParams(
            group_id="group123",
            description="Updated description for biomedical engineering group",
            manager="user789",
        )

        # Call function
        result = update_group(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.group_id, "group123")
        self.assertEqual(result.group_name, "Biomedical Engineering")

        # Verify mock was called correctly
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "PATCH")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user_group/group123")
        self.assertEqual(
            call_args[1]["json"]["description"],
            "Updated description for biomedical engineering group",
        )
        self.assertEqual(call_args[1]["json"]["manager"], "user789")
        mock_invalidate_query_cache.assert_called_once_with(table="sys_user_group")

    @patch("servicenow_mcp.tools.user_tools.get_user")
    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_add_group_members(self, mock_invalidate_query_cache, mock_get_user):
        """Test add_group_members function."""
        # Configure mock for make_request (POST to add member)
        mock_post_response = MagicMock()
        mock_post_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_post_response

        mock_get_user.return_value = {
            "success": True,
            "message": "User found",
            "user": {
                "sys_id": "user123",
                "user_name": "alice.radiology",
            },
        }

        # Create test params
        params = AddGroupMembersParams(
            group_id="group123",
            members=["alice.radiology", "admin"],
        )

        # Call function
        result = add_group_members(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.group_id, "group123")

        # Verify mock was called correctly (once for each member)
        self.assertEqual(self.auth_manager.make_request.call_count, 2)
        call_args = self.auth_manager.make_request.call_args_list[0]
        self.assertEqual(call_args[0][0], "POST")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user_grmember")
        self.assertEqual(call_args[1]["json"]["group"], "group123")
        self.assertEqual(call_args[1]["json"]["user"], "user123")
        mock_invalidate_query_cache.assert_called_once_with(table="sys_user_grmember")

    @patch("servicenow_mcp.tools.user_tools.get_user")
    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_remove_group_members(self, mock_invalidate_query_cache, mock_get_user):
        """Test remove_group_members function."""
        # Configure mocks for make_request
        # First call: GET to find membership record
        mock_get_response = MagicMock()
        mock_get_response.raise_for_status = MagicMock()
        mock_get_response.json.return_value = {
            "result": [
                {
                    "sys_id": "member123",
                    "user": {
                        "value": "user123",
                        "display_value": "Alice Radiology",
                    },
                    "group": {
                        "value": "group123",
                        "display_value": "Biomedical Engineering",
                    },
                }
            ]
        }

        # Second call: DELETE to remove membership
        mock_delete_response = MagicMock()
        mock_delete_response.raise_for_status = MagicMock()

        self.auth_manager.make_request.side_effect = [
            mock_get_response,
            mock_delete_response,
        ]

        mock_get_user.return_value = {
            "success": True,
            "message": "User found",
            "user": {
                "sys_id": "user123",
                "user_name": "alice.radiology",
            },
        }

        # Create test params
        params = RemoveGroupMembersParams(
            group_id="group123",
            members=["alice.radiology"],
        )

        # Call function
        result = remove_group_members(self.config, self.auth_manager, params)

        # Verify result
        self.assertTrue(result.success)
        self.assertEqual(result.group_id, "group123")

        # Verify mock was called correctly
        self.assertEqual(self.auth_manager.make_request.call_count, 2)

        # Verify GET call to find membership
        get_call_args = self.auth_manager.make_request.call_args_list[0]
        self.assertEqual(get_call_args[0][0], "GET")
        self.assertEqual(get_call_args[0][1], f"{self.config.api_url}/table/sys_user_grmember")
        self.assertEqual(get_call_args[1]["params"]["sysparm_query"], "group=group123^user=user123")

        # Verify DELETE call
        delete_call_args = self.auth_manager.make_request.call_args_list[1]
        self.assertEqual(delete_call_args[0][0], "DELETE")
        self.assertEqual(
            delete_call_args[0][1],
            f"{self.config.api_url}/table/sys_user_grmember/member123",
        )
        mock_invalidate_query_cache.assert_called_once_with(table="sys_user_grmember")

    @patch("servicenow_mcp.tools.user_tools.check_user_has_role", return_value=False)
    @patch("servicenow_mcp.tools.user_tools.get_role_id", return_value="role123")
    @patch("servicenow_mcp.tools.user_tools.invalidate_query_cache")
    def test_assign_roles_to_user_invalidates_role_cache(
        self,
        mock_invalidate_query_cache,
        mock_get_role_id,
        mock_check_user_has_role,
    ):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        result = assign_roles_to_user(
            self.config,
            self.auth_manager,
            user_id="user123",
            roles=["itil"],
        )

        self.assertTrue(result)
        mock_get_role_id.assert_called_once_with(self.config, self.auth_manager, "itil")
        mock_check_user_has_role.assert_called_once_with(
            self.config, self.auth_manager, "user123", "role123"
        )
        mock_invalidate_query_cache.assert_called_once_with(table="sys_user_has_role")


if __name__ == "__main__":
    unittest.main()
