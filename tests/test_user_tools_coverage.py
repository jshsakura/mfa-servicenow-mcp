"""Additional edge-case tests for the read-only user tools (get_user, list_users, list_groups)."""

import json
import unittest
from unittest.mock import MagicMock, patch

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


class TestGetUserEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_get_user_by_email(self):
        resp = _ok_response(
            {"result": [{"sys_id": "u1", "email": "a@b.com"}]},
            {"X-Total-Count": "1"},
        )
        self.auth.make_request.return_value = resp
        result = get_user(self.config, self.auth, GetUserParams(email="a@b.com"))
        self.assertTrue(result["success"])

    def test_get_user_no_params(self):
        result = get_user(self.config, self.auth, GetUserParams())
        self.assertFalse(result["success"])
        self.assertIn("At least one", result["message"])

    def test_get_user_not_found(self):
        resp = _ok_response({"result": []}, {"X-Total-Count": "0"})
        self.auth.make_request.return_value = resp
        result = get_user(self.config, self.auth, GetUserParams(user_id="none"))
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    def test_get_user_exception(self):
        self.auth.make_request.side_effect = Exception("Fail")
        result = get_user(self.config, self.auth, GetUserParams(user_id="u1"))
        self.assertFalse(result["success"])


class TestListUsersEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.user_tools.sn_count", return_value=99)
    def test_count_only(self, mock_count):
        params = ListUsersParams(count_only=True, active=True)
        result = list_users(self.config, self.auth, params)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 99)

    def test_list_users_with_query(self):
        resp = _ok_response({"result": []}, {"X-Total-Count": "0"})
        self.auth.make_request.return_value = resp
        params = ListUsersParams(query="alice")
        result = list_users(self.config, self.auth, params)
        self.assertTrue(result["success"])

    def test_list_users_error(self):
        self.auth.make_request.side_effect = Exception("Fail")
        params = ListUsersParams()
        result = list_users(self.config, self.auth, params)
        self.assertFalse(result["success"])


class TestListGroupsEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_list_groups_error(self):
        self.auth.make_request.side_effect = Exception("Fail")
        params = ListGroupsParams()
        result = list_groups(self.config, self.auth, params)
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
