"""
Tests for the ServiceNow MCP catalog optimization tools.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.catalog_optimization import (
    OptimizationRecommendationsParams,
    _get_inactive_items,
    _get_poor_description_items,
    get_optimization_recommendations,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestCatalogOptimizationTools(unittest.TestCase):
    """Test cases for the catalog optimization tools."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock server config
        self.config = ServerConfig(
            instance_url="https://example.service-now.com",
            auth=AuthConfig(
                type=AuthType.BASIC,
                basic=BasicAuthConfig(username="admin", password="password"),
            ),
        )

        # Create a mock auth manager
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {"Authorization": "Basic YWRtaW46cGFzc3dvcmQ="}

    def _finalize_response(self, mock_response):
        payload = mock_response.json.return_value
        mock_response.content = json.dumps(payload).encode("utf-8")
        mock_response.headers = getattr(mock_response, "headers", {}) or {}
        mock_response.raise_for_status = MagicMock()

    def test_get_inactive_items(self):
        """Test getting inactive catalog items."""
        # Mock the response from ServiceNow
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "item1",
                    "name": "Old Laptop",
                    "short_description": "Outdated laptop model",
                    "category": "hardware",
                },
                {
                    "sys_id": "item2",
                    "name": "Legacy Software",
                    "short_description": "Deprecated software package",
                    "category": "software",
                },
            ]
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        result = _get_inactive_items(self.config, self.auth_manager)

        # Verify the results
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Old Laptop")
        self.assertEqual(result[1]["name"], "Legacy Software")

        # Verify the API call
        self.auth_manager.make_request.assert_called_once()
        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(kwargs["params"]["sysparm_query"], "active=false")

    def test_get_inactive_items_with_category(self):
        """Test getting inactive catalog items filtered by category."""
        # Mock the response from ServiceNow
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "item1",
                    "name": "Old Laptop",
                    "short_description": "Outdated laptop model",
                    "category": "hardware",
                },
            ]
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the function with a category filter
        result = _get_inactive_items(self.config, self.auth_manager, "hardware")

        # Verify the results
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Old Laptop")

        # Verify the API call
        self.auth_manager.make_request.assert_called_once()
        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(kwargs["params"]["sysparm_query"], "active=false^category=hardware")

    def test_get_inactive_items_error(self):
        """Test error handling when getting inactive catalog items."""
        # Mock an error response
        self.auth_manager.make_request.side_effect = requests.exceptions.RequestException(
            "API Error"
        )

        # Call the function
        result = _get_inactive_items(self.config, self.auth_manager)

        # Verify the results
        self.assertEqual(result, [])

    def test_get_poor_description_items(self):
        """Test getting catalog items with poor description quality."""
        # Mock the response from ServiceNow
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "item1",
                    "name": "Laptop",
                    "short_description": "",  # Empty description
                    "category": "hardware",
                },
                {
                    "sys_id": "item2",
                    "name": "Software",
                    "short_description": "Software package",  # Short description
                    "category": "software",
                },
                {
                    "sys_id": "item3",
                    "name": "Service",
                    "short_description": "Please click here to request this service",  # Instructional language
                    "category": "services",
                },
            ]
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        result = _get_poor_description_items(self.config, self.auth_manager)

        # Verify the results
        self.assertEqual(len(result), 3)

        # Check the first item (empty description)
        self.assertEqual(result[0]["name"], "Laptop")
        self.assertEqual(result[0]["description_quality"], 0)
        self.assertEqual(result[0]["quality_issues"], ["Missing description"])

        # Check the second item (short description)
        self.assertEqual(result[1]["name"], "Software")
        self.assertEqual(result[1]["description_quality"], 30)
        self.assertEqual(result[1]["quality_issues"], ["Description too short", "Lacks detail"])

        # Check the third item (instructional language)
        self.assertEqual(result[2]["name"], "Service")
        self.assertEqual(result[2]["description_quality"], 50)
        self.assertEqual(
            result[2]["quality_issues"], ["Uses instructional language instead of descriptive"]
        )

    @patch("servicenow_mcp.tools.catalog_optimization._get_inactive_items")
    @patch("servicenow_mcp.tools.catalog_optimization._get_poor_description_items")
    def test_get_optimization_recommendations(self, mock_poor_desc, mock_inactive):
        """Test getting optimization recommendations."""
        # Mock the helper functions to return test data
        mock_inactive.return_value = [
            {
                "sys_id": "item1",
                "name": "Old Laptop",
                "short_description": "Outdated laptop model",
                "category": "hardware",
            },
        ]

        mock_poor_desc.return_value = [
            {
                "sys_id": "item5",
                "name": "Laptop",
                "short_description": "",
                "category": "hardware",
                "description_quality": 0,
                "quality_issues": ["Missing description"],
            },
        ]

        # Create the parameters
        params = OptimizationRecommendationsParams(
            recommendation_types=["inactive_items", "description_quality"]
        )

        # Call the function
        result = get_optimization_recommendations(self.config, self.auth_manager, params)

        # Verify the results
        self.assertTrue(result["success"])
        self.assertEqual(len(result["recommendations"]), 2)

        # Check each recommendation type
        recommendation_types = [rec["type"] for rec in result["recommendations"]]
        self.assertIn("inactive_items", recommendation_types)
        self.assertIn("description_quality", recommendation_types)

        # Check that each recommendation has the expected fields
        for rec in result["recommendations"]:
            self.assertIn("title", rec)
            self.assertIn("description", rec)
            self.assertIn("items", rec)
            self.assertIn("impact", rec)
            self.assertIn("effort", rec)
            self.assertIn("action", rec)

    @patch("servicenow_mcp.tools.catalog_optimization._get_inactive_items")
    def test_get_optimization_recommendations_filtered(self, mock_inactive):
        """Test getting filtered optimization recommendations."""
        mock_inactive.return_value = [
            {
                "sys_id": "item1",
                "name": "Old Laptop",
                "short_description": "Outdated laptop model",
                "category": "hardware",
            },
        ]

        # Create the parameters with only inactive_items
        params = OptimizationRecommendationsParams(recommendation_types=["inactive_items"])

        # Call the function
        result = get_optimization_recommendations(self.config, self.auth_manager, params)

        # Verify the results
        self.assertTrue(result["success"])
        self.assertEqual(len(result["recommendations"]), 1)

        recommendation_types = [rec["type"] for rec in result["recommendations"]]
        self.assertIn("inactive_items", recommendation_types)
        self.assertNotIn("description_quality", recommendation_types)

    def test_get_inactive_items_reuses_shared_query_cache(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "item1",
                    "name": "Old Laptop",
                    "short_description": "Outdated laptop model",
                    "category": "hardware",
                }
            ]
        }
        mock_response.headers = {"X-Total-Count": "1"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        first = _get_inactive_items(self.config, self.auth_manager)
        second = _get_inactive_items(self.config, self.auth_manager)

        self.assertEqual(first, second)
        self.assertEqual(self.auth_manager.make_request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
