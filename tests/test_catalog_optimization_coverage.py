"""
Additional tests for catalog_optimization to increase coverage to 80%+.

Covers: get_optimization_recommendations exception path, empty recommendation
results, update_catalog_item with all fields (active, order, description,
category), _get_high_abandonment_items with category filter and error,
_get_slow_fulfillment_items with category and error, _get_low_usage_items
with category and error, _get_poor_description_items with vague terms / error.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.catalog_optimization import (
    OptimizationRecommendationsParams,
    UpdateCatalogItemParams,
    _get_high_abandonment_items,
    _get_low_usage_items,
    _get_poor_description_items,
    _get_slow_fulfillment_items,
    get_optimization_recommendations,
    update_catalog_item,
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
        """Cover lines 173-175: exception in get_optimization_recommendations."""
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


class TestUpdateCatalogItemEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("servicenow_mcp.tools.catalog_optimization.invalidate_query_cache")
    def test_all_fields(self, mock_cache):
        """Cover lines 213, 215, 219, 221: description, category, active, order fields."""
        resp = _ok_response(
            {"result": {"sys_id": "item1", "name": "Laptop", "active": "false", "order": "5"}}
        )
        self.auth.make_request.return_value = resp

        params = UpdateCatalogItemParams(
            item_id="item1",
            name="Laptop",
            short_description="A laptop",
            description="Full description",
            category="hardware",
            price="999",
            active=False,
            order=5,
        )
        result = update_catalog_item(self.config, self.auth, params)
        self.assertTrue(result["success"])
        call_kwargs = self.auth.make_request.call_args[1]["json"]
        self.assertEqual(call_kwargs["description"], "Full description")
        self.assertEqual(call_kwargs["category"], "hardware")
        self.assertEqual(call_kwargs["active"], "false")
        self.assertEqual(call_kwargs["order"], "5")


class TestGetHighAbandonmentItems(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("random.randint", return_value=50)
    @patch("random.sample")
    def test_with_category(self, mock_sample, mock_randint):
        """Cover lines 320-343: high abandonment with category filter."""
        resp = _ok_response(
            {
                "result": [
                    {"sys_id": "i1", "name": "Item1", "short_description": "Desc", "category": "hw"}
                ]
            }
        )
        self.auth.make_request.return_value = resp
        mock_sample.return_value = [
            {"sys_id": "i1", "name": "Item1", "short_description": "Desc", "category": "hw"}
        ]

        result = _get_high_abandonment_items(self.config, self.auth, "cat1")
        self.assertEqual(len(result), 1)
        self.assertIn("abandonment_rate", result[0])
        self.assertIn("cart_adds", result[0])
        self.assertIn("orders", result[0])

    def test_error_path(self):
        """Cover line 342-343: exception returns []."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = _get_high_abandonment_items(self.config, self.auth)
        self.assertEqual(result, [])


class TestGetSlowFulfillmentItems(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("random.uniform", return_value=8.0)
    @patch("random.sample")
    def test_with_category(self, mock_sample, mock_uniform):
        """Cover line 363: slow fulfillment with category."""
        resp = _ok_response(
            {"result": [{"sys_id": "i1", "name": "HW", "short_description": "D", "category": "hw"}]}
        )
        self.auth.make_request.return_value = resp
        mock_sample.return_value = [
            {"sys_id": "i1", "name": "HW", "short_description": "D", "category": "hw"}
        ]

        result = _get_slow_fulfillment_items(self.config, self.auth, "cat1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["avg_fulfillment_time"], 8.0)

    def test_error_path(self):
        """Cover lines 381-383."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = _get_slow_fulfillment_items(self.config, self.auth)
        self.assertEqual(result, [])


class TestGetLowUsageItems(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    @patch("random.randint", return_value=3)
    @patch("random.sample")
    def test_with_category(self, mock_sample, mock_randint):
        """Cover line 289: low usage with category filter."""
        resp = _ok_response(
            {"result": [{"sys_id": "i1", "name": "SW", "short_description": "D", "category": "sw"}]}
        )
        self.auth.make_request.return_value = resp
        mock_sample.return_value = [
            {"sys_id": "i1", "name": "SW", "short_description": "D", "category": "sw"}
        ]

        result = _get_low_usage_items(self.config, self.auth, "cat1")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["order_count"], 3)

    def test_error_path(self):
        """Cover lines 301-303."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = _get_low_usage_items(self.config, self.auth)
        self.assertEqual(result, [])


class TestGetPoorDescriptionItems(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_vague_terms(self):
        """Cover lines 432-433: vague terms detection."""
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
        """Cover line 403: category filter."""
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
        """Cover lines 446-448."""
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
