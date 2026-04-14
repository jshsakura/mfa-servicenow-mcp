"""
Project management tools for the ServiceNow MCP server.

This module provides tools for managing projects in ServiceNow.
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


class CreateProjectParams(BaseModel):
    """Parameters for creating a project."""

    short_description: str = Field(..., description="Project name of the project")
    description: Optional[str] = Field(
        default=None, description="Detailed description of the project"
    )
    status: Optional[str] = Field(
        default=None, description="Status of the project (green, yellow, red)"
    )
    state: Optional[str] = Field(
        default=None,
        description="State of project (-5 is Pending,1 is Open, 2 is Work in progress, 3 is Closed Complete, 4 is Closed Incomplete, 5 is Closed Skipped)",
    )
    project_manager: Optional[str] = Field(
        default=None, description="Project manager for the project"
    )
    percentage_complete: Optional[int] = Field(
        default=None, description="Percentage complete for the project"
    )
    assignment_group: Optional[str] = Field(
        default=None, description="Group assigned to the project"
    )
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the project")
    start_date: Optional[str] = Field(default=None, description="Start date for the project")
    end_date: Optional[str] = Field(default=None, description="End date for the project")


class UpdateProjectParams(BaseModel):
    """Parameters for updating a project."""

    project_id: str = Field(..., description="Project ID or sys_id")
    short_description: Optional[str] = Field(
        default=None, description="Project name of the project"
    )
    description: Optional[str] = Field(
        default=None, description="Detailed description of the project"
    )
    status: Optional[str] = Field(
        default=None, description="Status of the project (green, yellow, red)"
    )
    state: Optional[str] = Field(
        default=None,
        description="State of project (-5 is Pending,1 is Open, 2 is Work in progress, 3 is Closed Complete, 4 is Closed Incomplete, 5 is Closed Skipped)",
    )
    project_manager: Optional[str] = Field(
        default=None, description="Project manager for the project"
    )
    percentage_complete: Optional[int] = Field(
        default=None, description="Percentage complete for the project"
    )
    assignment_group: Optional[str] = Field(
        default=None, description="Group assigned to the project"
    )
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the project")
    start_date: Optional[str] = Field(default=None, description="Start date for the project")
    end_date: Optional[str] = Field(default=None, description="End date for the project")


class ListProjectsParams(BaseModel):
    """Parameters for listing projects."""

    limit: Optional[int] = Field(default=10, description="Maximum number of records to return")
    offset: Optional[int] = Field(default=0, description="Offset to start from")
    state: Optional[str] = Field(default=None, description="Filter by state")
    assignment_group: Optional[str] = Field(default=None, description="Filter by assignment group")
    timeframe: Optional[str] = Field(
        default=None, description="Filter by timeframe (upcoming, in-progress, completed)"
    )
    query: Optional[str] = Field(default=None, description="Additional query string")


@register_tool(
    name="create_project",
    params=CreateProjectParams,
    description="Create a project (pm_project). Requires short_description. Optional: start/end dates, state.",
    serialization="str",
    return_type=str,
)
def create_project(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateProjectParams,
) -> Dict[str, Any]:
    """
    Create a new project in ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for creating the project.

    Returns:
        The created project.
    """
    # Prepare the request data
    data: Dict[str, Any] = {
        "short_description": params.short_description,
    }

    # Add optional fields if provided
    if params.description:
        data["description"] = params.description
    if params.status:
        data["status"] = params.status
    if params.state:
        data["state"] = params.state
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.percentage_complete:
        data["percentage_complete"] = params.percentage_complete
    if params.assigned_to:
        data["assigned_to"] = params.assigned_to
    if params.project_manager:
        data["project_manager"] = params.project_manager
    if params.start_date:
        data["start_date"] = params.start_date
    if params.end_date:
        data["end_date"] = params.end_date

    url = f"{config.instance_url}/api/now/table/pm_project"

    try:
        response = auth_manager.make_request("POST", url, json=data)
        response.raise_for_status()

        result = response.json()

        invalidate_query_cache(table="pm_project")

        return {
            "success": True,
            "message": "Project created successfully",
            "project": result["result"],
        }
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        return {
            "success": False,
            "message": f"Error creating project: {str(e)}",
        }


@register_tool(
    name="update_project",
    params=UpdateProjectParams,
    description="Update a project by sys_id. Supports description, dates, state, and assignment fields.",
    serialization="str",
    return_type=str,
)
def update_project(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateProjectParams,
) -> Dict[str, Any]:
    """
    Update an existing project in ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for updating the project.

    Returns:
        The updated project.
    """
    # Prepare the request data
    data: Dict[str, Any] = {}

    # Add optional fields if provided
    if params.short_description:
        data["short_description"] = params.short_description
    if params.description:
        data["description"] = params.description
    if params.status:
        data["status"] = params.status
    if params.state:
        data["state"] = params.state
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.percentage_complete:
        data["percentage_complete"] = params.percentage_complete
    if params.assigned_to:
        data["assigned_to"] = params.assigned_to
    if params.project_manager:
        data["project_manager"] = params.project_manager
    if params.start_date:
        data["start_date"] = params.start_date
    if params.end_date:
        data["end_date"] = params.end_date

    url = f"{config.instance_url}/api/now/table/pm_project/{params.project_id}"

    try:
        response = auth_manager.make_request("PUT", url, json=data)
        response.raise_for_status()

        result = response.json()

        invalidate_query_cache(table="pm_project")

        return {
            "success": True,
            "message": "Project updated successfully",
            "project": result["result"],
        }
    except Exception as e:
        logger.error(f"Error updating project: {e}")
        return {
            "success": False,
            "message": f"Error updating project: {str(e)}",
        }


@register_tool(
    name="list_projects",
    params=ListProjectsParams,
    description="List projects with optional state/assignment_group/query filters.",
    serialization="json",
    return_type=str,
)
def list_projects(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListProjectsParams,
) -> Dict[str, Any]:
    """
    List projects from ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for listing projects.

    Returns:
        A list of projects.
    """
    # Build the query
    query_parts: List[str] = []

    if params.state:
        query_parts.append(f"state={params.state}")
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
            table="pm_project",
            query=query,
            fields="sys_id,short_description,description,state,status,percent_complete,start_date,end_date,assigned_to,assignment_group,project_manager,sys_created_on,sys_updated_on",
            limit=min(params.limit or 10, 100),
            offset=params.offset or 0,
            display_value=True,
            fail_silently=False,
        )

        return {
            "success": True,
            "projects": rows,
            "count": len(rows),
            "total": total_count or len(rows),
        }
    except Exception as e:
        logger.error(f"Error listing projects: {e}")
        return {
            "success": False,
            "message": f"Error listing projects: {str(e)}",
        }
