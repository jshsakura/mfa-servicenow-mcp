"""Tests for surviving read-only user management tools."""

import json
import unittest
from unittest.mock import MagicMock

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.user_tools import (
    GetUserParams,
    ListGroupsParams,
    ListUsersParams,
    get_user,
    list_groups,
    list_users,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestUserTools(unittest.TestCase):
    def setUp(self):
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

    def test_get_user(self):
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

        params = GetUserParams(user_name="alice.radiology")
        result = get_user(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["user"]["sys_id"], "user123")
        self.assertEqual(result["user"]["user_name"], "alice.radiology")
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "GET")
        self.assertEqual(call_args[0][1], f"{self.config.api_url}/table/sys_user")
        self.assertEqual(call_args[1]["params"]["sysparm_query"], "user_name=alice.radiology")
        self.assertEqual(call_args[1]["params"]["sysparm_display_value"], "true")

    def test_list_users(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {"sys_id": "user123", "user_name": "alice.radiology"},
                {"sys_id": "user456", "user_name": "bob.chiefradiology"},
            ]
        }
        mock_response.headers = {"X-Total-Count": "2"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        params = ListUsersParams(department="Radiology", limit=10)
        result = list_users(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["users"]), 2)
        self.assertEqual(result["total"], 2)
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "GET")
        self.assertIn("department=Radiology", call_args[1]["params"]["sysparm_query"])

    def test_list_groups(self):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {"sys_id": "group123", "name": "IT Support"},
                {"sys_id": "group456", "name": "HR Team"},
            ]
        }
        mock_response.headers = {"X-Total-Count": "2"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        params = ListGroupsParams(active=True, type="it", query="support", limit=10)
        result = list_groups(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(result["count"], 2)
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "GET")
        self.assertIn("active=true", call_args[1]["params"]["sysparm_query"])
        self.assertIn("type=it", call_args[1]["params"]["sysparm_query"])
        self.assertIn("nameLIKE", call_args[1]["params"]["sysparm_query"])

    def test_get_user_reuses_shared_query_cache(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [{"sys_id": "user123", "user_name": "alice.radiology"}]
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


if __name__ == "__main__":
    unittest.main()
