"""
Catalog Item Variables tools for the ServiceNow MCP server.

This module provides tools for viewing variables (form fields) in ServiceNow catalog items.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)


class ListCatalogItemVariablesParams(BaseModel):
    """Parameters for listing catalog item variables."""

    catalog_item_id: str = Field(..., description="The sys_id of the catalog item")
    include_details: bool = Field(
        default=True, description="Whether to include detailed information about each variable"
    )
    limit: Optional[int] = Field(default=None, description="Maximum number of variables to return")
    offset: Optional[int] = Field(default=None, description="Offset for pagination")


class ListCatalogItemVariablesResponse(BaseModel):
    """Response from listing catalog item variables."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    variables: List[Dict[str, Any]] = Field(default=[], description="List of variables")
    count: int = Field(default=0, description="Total number of variables found")


def list_catalog_item_variables(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListCatalogItemVariablesParams,
) -> ListCatalogItemVariablesResponse:
    """List all variables (form fields) for a catalog item."""
    query = f"cat_item={params.catalog_item_id}"
    limit = min(params.limit, 100) if params.limit else 100
    offset = params.offset if params.offset else 0

    if params.include_details:
        fields = ""
        display_value = True
    else:
        fields = "sys_id,name,type,question_text,order,mandatory"
        display_value = False

    try:
        result, total_count = sn_query_page(
            config,
            auth_manager,
            table="item_option_new",
            query=query,
            fields=fields,
            limit=limit,
            offset=offset,
            display_value=display_value,
            orderby="order",
            fail_silently=False,
        )

        count = total_count if total_count is not None else len(result)

        return ListCatalogItemVariablesResponse(
            success=True,
            message=f"Retrieved {len(result)} variables for catalog item",
            variables=result,
            count=count,
        )

    except Exception as e:
        logger.error(f"Failed to list catalog item variables: {e}")
        return ListCatalogItemVariablesResponse(
            success=False,
            message=f"Failed to list catalog item variables: {str(e)}",
        )
