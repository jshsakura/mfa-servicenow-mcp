import unittest
from unittest.mock import MagicMock

from servicenow_mcp.tools.incident_tools import GetIncidentByNumberParams, get_incident_by_number
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestIncidentTools(unittest.TestCase):
    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="test", password="test")
        )
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com", auth=self.auth_config
        )
        self.auth_manager = MagicMock()
        self.auth_manager.get_headers.return_value = {"Authorization": "Bearer FAKE_TOKEN"}

    def test_get_incident_by_number_success(self):
        # Mock the make_request response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "12345",
                    "number": "INC0010001",
                    "short_description": "Test incident",
                    "description": "This is a test incident",
                    "state": "New",
                    "priority": "1 - Critical",
                    "assigned_to": "John Doe",
                    "category": "Software",
                    "subcategory": "Email",
                    "sys_created_on": "2025-06-25 10:00:00",
                    "sys_updated_on": "2025-06-25 10:00:00",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function with test data
        params = GetIncidentByNumberParams(incident_number="INC0010001")
        result = get_incident_by_number(self.config, self.auth_manager, params)

        # Assert the results
        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "Incident INC0010001 found")
        self.assertIn("incident", result)
        self.assertEqual(result["incident"]["number"], "INC0010001")

    def test_get_incident_by_number_not_found(self):
        # Mock the make_request response for a not found scenario
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": []}
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function with a non-existent incident number
        params = GetIncidentByNumberParams(incident_number="INC9999999")
        result = get_incident_by_number(self.config, self.auth_manager, params)

        # Assert the results
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Incident not found: INC9999999")


if __name__ == "__main__":
    unittest.main()
