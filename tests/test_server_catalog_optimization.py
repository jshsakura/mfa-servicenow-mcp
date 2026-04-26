"""Tests for catalog optimization tool parameters."""

import unittest

from servicenow_mcp.tools.catalog_optimization import OptimizationRecommendationsParams


class TestCatalogOptimizationToolParameters(unittest.TestCase):
    def test_optimization_recommendations_params(self):
        params = OptimizationRecommendationsParams(
            recommendation_types=["inactive_items", "low_usage"], category_id="hardware"
        )
        self.assertEqual(params.recommendation_types, ["inactive_items", "low_usage"])
        self.assertEqual(params.category_id, "hardware")

    def test_optimization_recommendations_defaults(self):
        params = OptimizationRecommendationsParams(recommendation_types=["inactive_items"])
        self.assertEqual(params.recommendation_types, ["inactive_items"])
        self.assertIsNone(params.category_id)


if __name__ == "__main__":
    unittest.main()
