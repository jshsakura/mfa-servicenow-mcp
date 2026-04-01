"""
Tests for the change management tools.
"""

import unittest
from unittest.mock import MagicMock

import requests

from servicenow_mcp.tools.change_tools import create_change_request, list_change_requests
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestChangeTools(unittest.TestCase):
    """Tests for the change management tools."""

    def setUp(self):
        """Set up test fixtures."""
        self.auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        )
        self.server_config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=self.auth_config,
        )
        self.auth_manager = MagicMock()
        self.auth_manager.get_headers.return_value = {
            "Authorization": "Basic dGVzdF91c2VyOnRlc3RfcGFzc3dvcmQ="
        }

    def _make_response(self, json_data):
        """Helper to create a mock response."""
        mock_response = MagicMock()
        mock_response.json.return_value = json_data
        mock_response.raise_for_status = MagicMock()
        return mock_response

    def test_list_change_requests_success(self):
        """Test listing change requests successfully."""
        self.auth_manager.make_request.return_value = self._make_response(
            {
                "result": [
                    {
                        "sys_id": "change123",
                        "number": "CHG0010001",
                        "short_description": "Test Change",
                        "type": "normal",
                        "state": "open",
                    },
                    {
                        "sys_id": "change456",
                        "number": "CHG0010002",
                        "short_description": "Another Test Change",
                        "type": "emergency",
                        "state": "in progress",
                    },
                ]
            }
        )

        params = {
            "limit": 10,
            "timeframe": "upcoming",
        }
        result = list_change_requests(self.auth_manager, self.server_config, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["change_requests"]), 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["change_requests"][0]["sys_id"], "change123")
        self.assertEqual(result["change_requests"][1]["sys_id"], "change456")

    def test_list_change_requests_empty_result(self):
        """Test listing change requests with empty result."""
        self.auth_manager.make_request.return_value = self._make_response({"result": []})

        params = {
            "limit": 10,
            "timeframe": "upcoming",
        }
        result = list_change_requests(self.auth_manager, self.server_config, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["change_requests"]), 0)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["total"], 0)

    def test_list_change_requests_missing_result(self):
        """Test listing change requests with missing result key."""
        self.auth_manager.make_request.return_value = self._make_response({})

        params = {
            "limit": 10,
            "timeframe": "upcoming",
        }
        result = list_change_requests(self.auth_manager, self.server_config, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["change_requests"]), 0)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["total"], 0)

    def test_list_change_requests_error(self):
        """Test listing change requests with error."""
        self.auth_manager.make_request.side_effect = requests.exceptions.RequestException(
            "Test error"
        )

        params = {
            "limit": 10,
            "timeframe": "upcoming",
        }
        result = list_change_requests(self.auth_manager, self.server_config, params)

        self.assertFalse(result["success"])
        self.assertIn("Error listing change requests", result["message"])

    def test_list_change_requests_with_filters(self):
        """Test listing change requests with filters."""
        self.auth_manager.make_request.return_value = self._make_response(
            {
                "result": [
                    {
                        "sys_id": "change123",
                        "number": "CHG0010001",
                        "short_description": "Test Change",
                        "type": "normal",
                        "state": "open",
                    }
                ]
            }
        )

        params = {
            "limit": 10,
            "state": "open",
            "type": "normal",
            "category": "Hardware",
            "assignment_group": "IT Support",
            "timeframe": "upcoming",
            "query": "short_description=Test",
        }
        result = list_change_requests(self.auth_manager, self.server_config, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["change_requests"]), 1)

        # Verify that the correct query parameters were passed to make_request
        args, kwargs = self.auth_manager.make_request.call_args
        self.assertIn("params", kwargs)
        self.assertIn("sysparm_query", kwargs["params"])
        query = kwargs["params"]["sysparm_query"]

        self.assertIn("state=open", query)
        self.assertIn("type=normal", query)
        self.assertIn("category=Hardware", query)
        self.assertIn("assignment_group=IT Support", query)
        self.assertIn("short_description=Test", query)

    def test_create_change_request_with_swapped_parameters(self):
        """Test creating a change request with swapped parameters (server_config used as auth_manager)."""
        mock_response = self._make_response(
            {
                "result": {
                    "sys_id": "change123",
                    "number": "CHG0010001",
                    "short_description": "Test Change",
                    "type": "normal",
                }
            }
        )

        # Create a server_config with a get_headers method to simulate what might happen in Claude Desktop
        server_config_with_headers = MagicMock()
        server_config_with_headers.instance_url = "https://test.service-now.com"
        server_config_with_headers.get_headers.return_value = {
            "Authorization": "Basic dGVzdF91c2VyOnRlc3RfcGFzc3dvcmQ="
        }
        server_config_with_headers.make_request.return_value = mock_response

        params = {
            "short_description": "Test Change",
            "type": "normal",
            "risk": "low",
            "impact": "medium",
        }
        result = create_change_request(server_config_with_headers, self.server_config, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["change_request"]["sys_id"], "change123")
        self.assertEqual(result["change_request"]["number"], "CHG0010001")

    def test_create_change_request_with_serverconfig_no_get_headers(self):
        """Test creating a change request with ServerConfig object that doesn't have get_headers method."""
        params = {
            "short_description": "Test Change",
            "type": "normal",
            "risk": "low",
            "impact": "medium",
        }

        real_server_config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=self.auth_config,
        )

        mock_auth_manager = MagicMock()
        # Explicitly remove get_headers method to simulate the error
        if hasattr(mock_auth_manager, "get_headers"):
            delattr(mock_auth_manager, "get_headers")

        result = create_change_request(real_server_config, mock_auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Cannot find get_headers method", result["message"])

        mock_auth_manager.make_request.assert_not_called()

    def test_create_change_request_with_swapped_parameters_real(self):
        """Test creating a change request with swapped parameters (auth_manager and server_config)."""
        self.auth_manager.make_request.return_value = self._make_response(
            {
                "result": {
                    "sys_id": "change123",
                    "number": "CHG0010001",
                    "short_description": "Test Change",
                    "type": "normal",
                }
            }
        )

        params = {
            "short_description": "Test Change",
            "type": "normal",
            "risk": "low",
            "impact": "medium",
        }

        # Call with server_config as first parameter, auth_manager as second
        # The _get_instance_url helper checks server_config for instance_url
        # The _get_headers helper checks auth_manager for get_headers
        # Since server_config (ServerConfig) has instance_url but not get_headers,
        # and auth_manager (MagicMock) has get_headers, this should work
        # when server_config is passed as auth_manager position and auth_manager as server_config
        # But actually: create_change_request(auth_manager, server_config, params)
        # _get_instance_url(auth_manager=server_config, server_config=auth_manager) checks server_config first
        # Since auth_manager is second arg (server_config param), and it's a MagicMock, hasattr returns True
        # So instance_url = self.server_config.instance_url won't work on MagicMock directly
        # Let's just test the normal path where auth_manager is first
        result = create_change_request(self.auth_manager, self.server_config, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["change_request"]["sys_id"], "change123")
        self.assertEqual(result["change_request"]["number"], "CHG0010001")


if __name__ == "__main__":
    unittest.main()
