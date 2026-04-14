"""
Epic management tools for the ServiceNow MCP server.

This module provides tools for managing epics in ServiceNow.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class CreateEpicParams(BaseModel):
    """Parameters for creating an epic."""

    short_description: str = Field(..., description="Short description of the epic")
    description: Optional[str] = Field(default=None, description="Detailed description of the epic")
    priority: Optional[str] = Field(
        default=None,
        description="Priority of epic (1 is Critical, 2 is High, 3 is Moderate, 4 is Low, 5 is Planning)",
    )
    state: Optional[str] = Field(
        default=None,
        description="State of story (-6 is Draft,1 is Ready,2 is Work in progress, 3 is Complete, 4 is Cancelled)",
    )
    assignment_group: Optional[str] = Field(default=None, description="Group assigned to the epic")
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the epic")
    work_notes: Optional[str] = Field(
        default=None,
        description="Work notes to add to the epic. Used for adding notes and comments to an epic",
    )


class UpdateEpicParams(BaseModel):
    """Parameters for updating an epic."""

    epic_id: str = Field(..., description="Epic ID or sys_id")
    short_description: Optional[str] = Field(
        default=None, description="Short description of the epic"
    )
    description: Optional[str] = Field(default=None, description="Detailed description of the epic")
    priority: Optional[str] = Field(
        default=None,
        description="Priority of epic (1 is Critical, 2 is High, 3 is Moderate, 4 is Low, 5 is Planning)",
    )
    state: Optional[str] = Field(
        default=None,
        description="State of story (-6 is Draft,1 is Ready,2 is Work in progress, 3 is Complete, 4 is Cancelled)",
    )
    assignment_group: Optional[str] = Field(default=None, description="Group assigned to the epic")
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the epic")
    work_notes: Optional[str] = Field(
        default=None,
        description="Work notes to add to the epic. Used for adding notes and comments to an epic",
    )


class ListEpicsParams(BaseModel):
    """Parameters for listing epics."""

    limit: Optional[int] = Field(default=10, description="Maximum number of records to return")
    offset: Optional[int] = Field(default=0, description="Offset to start from")
    priority: Optional[str] = Field(default=None, description="Filter by priority")
    assignment_group: Optional[str] = Field(default=None, description="Filter by assignment group")
    timeframe: Optional[str] = Field(
        default=None, description="Filter by timeframe (upcoming, in-progress, completed)"
    )
    query: Optional[str] = Field(default=None, description="Additional query string")


@register_tool(
    name="create_epic",
    params=CreateEpicParams,
    description="Create an epic (rm_epic). Requires short_description. Optional: priority, state, assignment_group.",
    serialization="str",
    return_type=str,
)
def create_epic(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateEpicParams,
) -> Dict[str, Any]:
    """
    Create a new epic in ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for creating the epic.

    Returns:
        The created epic.
    """
    # Prepare the request data
    data: Dict[str, Any] = {
        "short_description": params.short_description,
    }

    # Add optional fields if provided
    if params.description:
        data["description"] = params.description
    if params.priority:
        data["priority"] = params.priority
    if params.state:
        data["state"] = params.state
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.assigned_to:
        data["assigned_to"] = params.assigned_to
    if params.work_notes:
        data["work_notes"] = params.work_notes

    url = f"{config.instance_url}/api/now/table/rm_epic"

    try:
        response = auth_manager.make_request("POST", url, json=data)
        response.raise_for_status()

        result = response.json()

        invalidate_query_cache(table="rm_epic")

        return {
            "success": True,
            "message": "Epic created successfully",
            "epic": result["result"],
        }
    except Exception as e:
        logger.error(f"Error creating epic: {e}")
        return {
            "success": False,
            "message": f"Error creating epic: {str(e)}",
        }


@register_tool(
    name="update_epic",
    params=UpdateEpicParams,
    description="Update an epic by sys_id. Supports description, priority, state, and assignment fields.",
    serialization="str",
    return_type=str,
)
def update_epic(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateEpicParams,
) -> Dict[str, Any]:
    """
    Update an existing epic in ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for updating the epic.

    Returns:
        The updated epic.
    """
    # Prepare the request data
    data: Dict[str, Any] = {}

    # Add optional fields if provided
    if params.short_description:
        data["short_description"] = params.short_description
    if params.description:
        data["description"] = params.description
    if params.priority:
        data["priority"] = params.priority
    if params.state:
        data["state"] = params.state
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.assigned_to:
        data["assigned_to"] = params.assigned_to
    if params.work_notes:
        data["work_notes"] = params.work_notes

    url = f"{config.instance_url}/api/now/table/rm_epic/{params.epic_id}"

    try:
        response = auth_manager.make_request("PUT", url, json=data)
        response.raise_for_status()

        result = response.json()

        invalidate_query_cache(table="rm_epic")

        return {
            "success": True,
            "message": "Epic updated successfully",
            "epic": result["result"],
        }
    except Exception as e:
        logger.error(f"Error updating epic: {e}")
        return {
            "success": False,
            "message": f"Error updating epic: {str(e)}",
        }


@register_tool(
    name="list_epics",
    params=ListEpicsParams,
    description="List epics with optional state/assignment_group/query filters.",
    serialization="json",
    return_type=str,
)
def list_epics(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListEpicsParams,
) -> Dict[str, Any]:
    """
    List epics from ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for listing epics.

    Returns:
        A list of epics.
    """
    # Build the query
    query_parts: List[str] = []

    if params.priority:
        query_parts.append(f"priority={params.priority}")
    if params.assignment_group:
        query_parts.append(f"assignment_group={params.assignment_group}")

    # Handle timeframe filtering
    if params.timeframe:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if params.timeframe == "upcoming":
            query_parts.append(f"start_date>{now}")
        elif params.timeframe == "in-progress":
            query_parts.append(f"start_date<{now}^end_date>{now}")
        elif params.timeframe == "completed":
            query_parts.append(f"end_date<{now}")

    # Add any additional query string
    if params.query:
        query_parts.append(params.query)

    # Combine query parts
    query = "^".join(query_parts) if query_parts else ""

    try:
        rows, total_count = sn_query_page(
            config,
            auth_manager,
            table="rm_epic",
            query=query,
            fields="sys_id,short_description,description,priority,state,assigned_to,assignment_group,work_notes,sys_created_on,sys_updated_on",
            limit=min(params.limit or 10, 100),
            offset=params.offset or 0,
            display_value=True,
            fail_silently=False,
        )

        return {
            "success": True,
            "epics": rows,
            "count": len(rows),
            "total": total_count or len(rows),
        }
    except Exception as e:
        logger.error(f"Error listing epics: {e}")
        return {
            "success": False,
            "message": f"Error listing epics: {str(e)}",
        }
