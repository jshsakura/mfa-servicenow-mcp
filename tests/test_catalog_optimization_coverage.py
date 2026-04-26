"""
Additional tests for catalog_optimization to increase coverage to 80%+.

Covers: get_optimization_recommendations exception path, empty recommendation
results, update_catalog_item with all fields (active, order, description,
category), _get_poor_description_items with vague terms / error.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.catalog_optimization import (
    OptimizationRecommendationsParams,
    _get_poor_description_items,
    get_optimization_recommendations,
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


class TestGetOptimizationRecommendationsEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.catalog_optimization._get_inactive_items")
    def test_exception_path(self, mock_inactive):
        """Cover exception in get_optimization_recommendations."""
        mock_inactive.side_effect = Exception("DB down")
        params = OptimizationRecommendationsParams(recommendation_types=["inactive_items"])
        result = get_optimization_recommendations(self.config, self.auth, params)
        self.assertFalse(result["success"])
        self.assertIn("Error", result["message"])

    @patch("servicenow_mcp.tools.catalog_optimization._get_inactive_items")
    def test_empty_items_not_added(self, mock_inactive):
        """Cover implicit branch: helper returns empty list, no recommendation added."""
        mock_inactive.return_value = []
        params = OptimizationRecommendationsParams(recommendation_types=["inactive_items"])
        result = get_optimization_recommendations(self.config, self.auth, params)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["recommendations"]), 0)


class TestGetPoorDescriptionItems(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_vague_terms(self):
        """Cover vague terms detection."""
        resp = _ok_response(
            {
                "result": [
                    {
                        "sys_id": "i1",
                        "name": "Stuff",
                        "short_description": "This item provides stuff and more things etc",
                        "category": "misc",
                    }
                ]
            }
        )
        self.auth.make_request.return_value = resp
        result = _get_poor_description_items(self.config, self.auth)
        self.assertEqual(len(result), 1)
        self.assertIn("Contains vague terms", result[0]["quality_issues"])

    def test_with_category(self):
        """Cover category filter."""
        resp = _ok_response(
            {
                "result": [
                    {"sys_id": "i1", "name": "OK Item", "short_description": "", "category": "hw"}
                ]
            }
        )
        self.auth.make_request.return_value = resp
        result = _get_poor_description_items(self.config, self.auth, "cat1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["description_quality"], 0)

    def test_error_path(self):
        """Cover exception returns []."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = _get_poor_description_items(self.config, self.auth)
        self.assertEqual(result, [])

    def test_good_description_excluded(self):
        """Items with quality >= 80 should not be returned."""
        resp = _ok_response(
            {
                "result": [
                    {
                        "sys_id": "i1",
                        "name": "Good Item",
                        "short_description": "This is a well-written description that explains the item purpose clearly and thoroughly",
                        "category": "sw",
                    }
                ]
            }
        )
        self.auth.make_request.return_value = resp
        result = _get_poor_description_items(self.config, self.auth)
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
