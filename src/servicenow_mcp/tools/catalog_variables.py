"""
Catalog Item Variables tools for the ServiceNow MCP server.

This module provides tools for managing variables (form fields) in ServiceNow catalog items.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class CreateCatalogItemVariableParams(BaseModel):
    """Parameters for creating a catalog item variable."""

    catalog_item_id: str = Field(..., description="The sys_id of the catalog item")
    name: str = Field(..., description="The name of the variable (internal name)")
    type: str = Field(
        default=..., description="The type of variable (e.g., string, integer, boolean, reference)"
    )
    label: str = Field(..., description="The display label for the variable")
    mandatory: bool = Field(default=False, description="Whether the variable is required")
    help_text: Optional[str] = Field(
        default=None, description="Help text to display with the variable"
    )
    default_value: Optional[str] = Field(default=None, description="Default value for the variable")
    description: Optional[str] = Field(default=None, description="Description of the variable")
    order: Optional[int] = Field(default=None, description="Display order of the variable")
    reference_table: Optional[str] = Field(
        default=None, description="For reference fields, the table to reference"
    )
    reference_qualifier: Optional[str] = Field(
        default=None, description="For reference fields, the query to filter reference options"
    )
    max_length: Optional[int] = Field(default=None, description="Maximum length for string fields")
    min: Optional[int] = Field(default=None, description="Minimum value for numeric fields")
    max: Optional[int] = Field(default=None, description="Maximum value for numeric fields")


class CatalogItemVariableResponse(BaseModel):
    """Response from catalog item variable operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    variable_id: Optional[str] = Field(
        default=None, description="The sys_id of the created/updated variable"
    )
    details: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional details about the variable"
    )


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


class UpdateCatalogItemVariableParams(BaseModel):
    """Parameters for updating a catalog item variable."""

    variable_id: str = Field(..., description="The sys_id of the variable to update")
    label: Optional[str] = Field(default=None, description="The display label for the variable")
    mandatory: Optional[bool] = Field(default=None, description="Whether the variable is required")
    help_text: Optional[str] = Field(
        default=None, description="Help text to display with the variable"
    )
    default_value: Optional[str] = Field(default=None, description="Default value for the variable")
    description: Optional[str] = Field(default=None, description="Description of the variable")
    order: Optional[int] = Field(default=None, description="Display order of the variable")
    reference_qualifier: Optional[str] = Field(
        default=None, description="For reference fields, the query to filter reference options"
    )
    max_length: Optional[int] = Field(default=None, description="Maximum length for string fields")
    min: Optional[int] = Field(default=None, description="Minimum value for numeric fields")
    max: Optional[int] = Field(default=None, description="Maximum value for numeric fields")


@register_tool(
    name="create_catalog_item_variable",
    params=CreateCatalogItemVariableParams,
    description="Add a form variable to a catalog item. Requires cat_item sys_id, variable type, name, and label.",
    serialization="dict",
    return_type=dict,
)
def create_catalog_item_variable(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateCatalogItemVariableParams,
) -> CatalogItemVariableResponse:
    """
    Create a new variable (form field) for a catalog item.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for creating a catalog item variable.

    Returns:
        Response with information about the created variable.
    """
    api_url = f"{config.instance_url}/api/now/table/item_option_new"

    # Build request data
    data: Dict[str, Any] = {
        "cat_item": params.catalog_item_id,
        "name": params.name,
        "type": params.type,
        "question_text": params.label,
        "mandatory": str(params.mandatory).lower(),  # ServiceNow expects "true"/"false" strings
    }

    if params.help_text:
        data["help_text"] = params.help_text
    if params.default_value:
        data["default_value"] = params.default_value
    if params.description:
        data["description"] = params.description
    if params.order is not None:
        data["order"] = params.order
    if params.reference_table:
        data["reference"] = params.reference_table
    if params.reference_qualifier:
        data["reference_qual"] = params.reference_qualifier
    if params.max_length:
        data["max_length"] = params.max_length
    if params.min is not None:
        data["min"] = params.min
    if params.max is not None:
        data["max"] = params.max

    # Make request
    try:
        response = auth_manager.make_request(
            "POST",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})
        invalidate_query_cache(table="item_option_new")

        return CatalogItemVariableResponse(
            success=True,
            message="Catalog item variable created successfully",
            variable_id=result.get("sys_id"),
            details=result,
        )

    except Exception as e:
        logger.error(f"Failed to create catalog item variable: {e}")
        return CatalogItemVariableResponse(
            success=False,
            message=f"Failed to create catalog item variable: {str(e)}",
        )


@register_tool(
    name="list_catalog_item_variables",
    params=ListCatalogItemVariablesParams,
    description="List variable definitions for a catalog item. Returns type, order, mandatory flag, and default values.",
    serialization="dict",
    return_type=dict,
)
def list_catalog_item_variables(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListCatalogItemVariablesParams,
) -> ListCatalogItemVariablesResponse:
    """
    List all variables (form fields) for a catalog item.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for listing catalog item variables.

    Returns:
        Response with a list of variables for the catalog item.
    """
    query = f"cat_item={params.catalog_item_id}"
    limit = min(params.limit, 100) if params.limit else 100
    offset = params.offset if params.offset else 0

    # Include all fields if detailed info is requested
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


@register_tool(
    name="update_catalog_item_variable",
    params=UpdateCatalogItemVariableParams,
    description="Partial update of a catalog item variable by sys_id. Supports label, order, mandatory, and default value.",
    serialization="dict",
    return_type=dict,
)
def update_catalog_item_variable(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateCatalogItemVariableParams,
) -> CatalogItemVariableResponse:
    """
    Update an existing variable (form field) for a catalog item.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for updating a catalog item variable.

    Returns:
        Response with information about the updated variable.
    """
    api_url = f"{config.instance_url}/api/now/table/item_option_new/{params.variable_id}"

    # Build request data with only parameters that are provided
    data: Dict[str, Any] = {}

    if params.label is not None:
        data["question_text"] = params.label
    if params.mandatory is not None:
        data["mandatory"] = str(
            params.mandatory
        ).lower()  # ServiceNow expects "true"/"false" strings
    if params.help_text is not None:
        data["help_text"] = params.help_text
    if params.default_value is not None:
        data["default_value"] = params.default_value
    if params.description is not None:
        data["description"] = params.description
    if params.order is not None:
        data["order"] = params.order
    if params.reference_qualifier is not None:
        data["reference_qual"] = params.reference_qualifier
    if params.max_length is not None:
        data["max_length"] = params.max_length
    if params.min is not None:
        data["min"] = params.min
    if params.max is not None:
        data["max"] = params.max

    # If no fields to update, return early
    if not data:
        return CatalogItemVariableResponse(
            success=False,
            message="No update parameters provided",
        )

    # Make request
    try:
        response = auth_manager.make_request(
            "PATCH",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})
        invalidate_query_cache(table="item_option_new")

        return CatalogItemVariableResponse(
            success=True,
            message="Catalog item variable updated successfully",
            variable_id=params.variable_id,
            details=result,
        )

    except Exception as e:
        logger.error(f"Failed to update catalog item variable: {e}")
        return CatalogItemVariableResponse(
            success=False,
            message=f"Failed to update catalog item variable: {str(e)}",
        )
