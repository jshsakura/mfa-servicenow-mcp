"""
Tools for optimizing the ServiceNow Service Catalog.

This module provides tools for analyzing the ServiceNow Service Catalog,
including identifying inactive items and items with poor descriptions.
"""

import logging
from typing import Dict, List, Optional

from pydantic import BaseModel

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


def _fetch_catalog_items(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    query: str,
    limit: int = 50,
) -> List[Dict]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sc_cat_item",
        query=query,
        fields="sys_id,name,short_description,category",
        limit=limit,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    return rows if isinstance(rows, list) else []


class OptimizationRecommendationsParams(BaseModel):
    """Parameters for getting optimization recommendations."""

    recommendation_types: List[str] = ["inactive_items", "description_quality"]
    category_id: Optional[str] = None


class UpdateCatalogItemParams(BaseModel):
    """Parameters for updating a catalog item."""

    item_id: str
    name: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[str] = None
    active: Optional[bool] = None
    order: Optional[int] = None
    dry_run: bool = False


@register_tool(
    name="get_optimization_recommendations",
    params=OptimizationRecommendationsParams,
    description="Analyze catalog structure — find inactive items and items with poor descriptions. Returns improvement suggestions.",
    serialization="json",
    return_type=str,
)
def get_optimization_recommendations(
    config: ServerConfig, auth_manager: AuthManager, params: OptimizationRecommendationsParams
) -> Dict:
    """
    Get optimization recommendations for the ServiceNow Service Catalog.

    Args:
        config: The server configuration
        auth_manager: The authentication manager
        params: The parameters for getting optimization recommendations

    Returns:
        A dictionary containing the optimization recommendations
    """
    logger.info("Getting catalog optimization recommendations")

    recommendations = []
    category_id = params.category_id

    try:
        # Get recommendations based on the requested types
        for rec_type in params.recommendation_types:
            if rec_type == "inactive_items":
                items = _get_inactive_items(config, auth_manager, category_id)
                if items:
                    recommendations.append(
                        {
                            "type": "inactive_items",
                            "title": "Inactive Catalog Items",
                            "description": "Items that are currently inactive in the catalog",
                            "items": items,
                            "impact": "medium",
                            "effort": "low",
                            "action": "Review and either update or remove these items",
                        }
                    )

            elif rec_type == "description_quality":
                items = _get_poor_description_items(config, auth_manager, category_id)
                if items:
                    recommendations.append(
                        {
                            "type": "description_quality",
                            "title": "Poor Description Quality",
                            "description": "Items with missing, short, or low-quality descriptions",
                            "items": items,
                            "impact": "medium",
                            "effort": "low",
                            "action": "Improve the descriptions to better explain the item's purpose and benefits",
                        }
                    )

        return {
            "success": True,
            "recommendations": recommendations,
        }

    except Exception as e:
        logger.error(f"Error getting optimization recommendations: {e}")
        return {
            "success": False,
            "message": f"Error getting optimization recommendations: {str(e)}",
            "recommendations": [],
        }


@register_tool(
    name="update_catalog_item",
    params=UpdateCatalogItemParams,
    description="Update a catalog item by sys_id. Partial field update.",
    serialization="json",
    return_type=str,
)
def update_catalog_item(
    config: ServerConfig, auth_manager: AuthManager, params: UpdateCatalogItemParams
) -> Dict:
    """
    Update a catalog item.

    Args:
        config: The server configuration
        auth_manager: The authentication manager
        params: The parameters for updating the catalog item

    Returns:
        A dictionary containing the result of the update operation
    """
    logger.info(f"Updating catalog item: {params.item_id}")

    try:
        # Build the request body with only the provided parameters
        body = {}
        if params.name is not None:
            body["name"] = params.name
        if params.short_description is not None:
            body["short_description"] = params.short_description
        if params.description is not None:
            body["description"] = params.description
        if params.category is not None:
            body["category"] = params.category
        if params.price is not None:
            body["price"] = params.price
        if params.active is not None:
            body["active"] = str(params.active).lower()
        if params.order is not None:
            body["order"] = str(params.order)

        if params.dry_run:
            return build_update_preview(
                config,
                auth_manager,
                table="sc_cat_item",
                sys_id=params.item_id,
                proposed=body,
                identifier_fields=["name", "category", "active"],
            )

        # Make the API request
        url = f"{config.instance_url}/api/now/table/sc_cat_item/{params.item_id}"
        headers = auth_manager.get_headers()
        headers["Content-Type"] = "application/json"

        response = auth_manager.make_request("PATCH", url, headers=headers, json=body)
        response.raise_for_status()
        invalidate_query_cache(table="sc_cat_item")

        return {
            "success": True,
            "message": "Catalog item updated successfully",
            "data": response.json()["result"],
        }

    except Exception as e:
        logger.error(f"Error updating catalog item: {e}")
        return {
            "success": False,
            "message": f"Error updating catalog item: {str(e)}",
            "data": None,
        }


def _get_inactive_items(
    config: ServerConfig, auth_manager: AuthManager, category_id: Optional[str] = None
) -> List[Dict]:
    """
    Get inactive catalog items.

    Args:
        config: The server configuration
        auth_manager: The authentication manager
        category_id: Optional category ID to filter by

    Returns:
        A list of inactive catalog items
    """
    try:
        query = "active=false"
        if category_id:
            query += f"^category={category_id}"
        return _fetch_catalog_items(config, auth_manager, query=query)

    except Exception as e:
        logger.error(f"Error getting inactive items: {e}")
        return []


def _get_poor_description_items(
    config: ServerConfig, auth_manager: AuthManager, category_id: Optional[str] = None
) -> List[Dict]:
    """
    Get catalog items with poor description quality.

    Args:
        config: The server configuration
        auth_manager: The authentication manager
        category_id: Optional category ID to filter by

    Returns:
        A list of catalog items with poor description quality
    """
    try:
        query = "active=true"
        if category_id:
            query += f"^category={category_id}"
        items = _fetch_catalog_items(config, auth_manager, query=query)
        poor_description_items = []

        # Analyze each item's description quality
        for item in items:
            description = item.get("short_description", "")
            quality_issues = []
            quality_score = 100  # Start with perfect score

            # Check for empty description
            if not description:
                quality_issues.append("Missing description")
                quality_score = 0
            else:
                # Check for short description
                if len(description) < 30:
                    quality_issues.append("Description too short")
                    quality_issues.append("Lacks detail")
                    quality_score -= 70

                # Check for instructional language instead of descriptive
                if "click here" in description.lower() or "request this" in description.lower():
                    quality_issues.append("Uses instructional language instead of descriptive")
                    quality_score -= 50

                # Check for vague terms
                vague_terms = ["etc", "and more", "and so on", "stuff", "things"]
                if any(term in description.lower() for term in vague_terms):
                    quality_issues.append("Contains vague terms")
                    quality_score -= 30

            # Ensure score is between 0 and 100
            quality_score = max(0, min(100, quality_score))

            # Add to poor description items if quality is below threshold
            if quality_score < 80:
                item["description_quality"] = quality_score
                item["quality_issues"] = quality_issues
                poor_description_items.append(item)

        return poor_description_items

    except Exception as e:
        logger.error(f"Error getting poor description items: {e}")
        return []
