"""
Scrum Task management tools for the ServiceNow MCP server.

This module provides tools for managing scrum tasks in ServiceNow.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class CreateScrumTaskParams(BaseModel):
    """Parameters for creating a scrum task."""

    story: str = Field(
        ..., description="Short description of the story. It requires the System ID of the story."
    )
    short_description: str = Field(..., description="Short description of the scrum task")
    priority: Optional[str] = Field(
        None,
        description="Priority of scrum task (1 is Critical, 2 is High, 3 is Moderate, 4 is Low)",
    )
    planned_hours: Optional[int] = Field(None, description="Planned hours for the scrum task")
    remaining_hours: Optional[int] = Field(None, description="Remaining hours for the scrum task")
    hours: Optional[int] = Field(None, description="Actual Hours for the scrum task")
    description: Optional[str] = Field(None, description="Detailed description of the scrum task")
    type: Optional[str] = Field(
        None,
        description="Type of scrum task (1 is Analysis, 2 is Coding, 3 is Documentation, 4 is Testing)",
    )
    state: Optional[str] = Field(
        None,
        description="State of scrum task (-6 is Draft,1 is Ready, 2 is Work in progress, 3 is Complete, 4 is Cancelled)",
    )
    assignment_group: Optional[str] = Field(None, description="Group assigned to the scrum task")
    assigned_to: Optional[str] = Field(None, description="User assigned to the scrum task")
    work_notes: Optional[str] = Field(None, description="Work notes to add to the scrum task")


class UpdateScrumTaskParams(BaseModel):
    """Parameters for updating a scrum task."""

    scrum_task_id: str = Field(..., description="Scrum Task ID or sys_id")
    short_description: Optional[str] = Field(
        None, description="Short description of the scrum task"
    )
    priority: Optional[str] = Field(
        None,
        description="Priority of scrum task (1 is Critical, 2 is High, 3 is Moderate, 4 is Low)",
    )
    planned_hours: Optional[int] = Field(None, description="Planned hours for the scrum task")
    remaining_hours: Optional[int] = Field(None, description="Remaining hours for the scrum task")
    hours: Optional[int] = Field(None, description="Actual Hours for the scrum task")
    description: Optional[str] = Field(None, description="Detailed description of the scrum task")
    type: Optional[str] = Field(
        None,
        description="Type of scrum task (1 is Analysis, 2 is Coding, 3 is Documentation, 4 is Testing)",
    )
    state: Optional[str] = Field(
        None,
        description="State of scrum task (-6 is Draft,1 is Ready, 2 is Work in progress, 3 is Complete, 4 is Cancelled)",
    )
    assignment_group: Optional[str] = Field(None, description="Group assigned to the scrum task")
    assigned_to: Optional[str] = Field(None, description="User assigned to the scrum task")
    work_notes: Optional[str] = Field(None, description="Work notes to add to the scrum task")


class ListScrumTasksParams(BaseModel):
    """Parameters for listing scrum tasks."""

    limit: Optional[int] = Field(10, description="Maximum number of records to return")
    offset: Optional[int] = Field(0, description="Offset to start from")
    state: Optional[str] = Field(None, description="Filter by state")
    assignment_group: Optional[str] = Field(None, description="Filter by assignment group")
    timeframe: Optional[str] = Field(
        None, description="Filter by timeframe (upcoming, in-progress, completed)"
    )
    query: Optional[str] = Field(None, description="Additional query string")


@register_tool(
    name="create_scrum_task",
    params=CreateScrumTaskParams,
    description="Create a new scrum task in ServiceNow",
    serialization="str",
    return_type=str,
)
def create_scrum_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateScrumTaskParams,
) -> Dict[str, Any]:
    """
    Create a new scrum task in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for creating the scrum task.

    Returns:
        The created scrum task.
    """
    data: Dict[str, Any] = {
        "story": params.story,
        "short_description": params.short_description,
    }

    if params.priority:
        data["priority"] = params.priority
    if params.planned_hours:
        data["planned_hours"] = params.planned_hours
    if params.remaining_hours:
        data["remaining_hours"] = params.remaining_hours
    if params.hours:
        data["hours"] = params.hours
    if params.description:
        data["description"] = params.description
    if params.type:
        data["type"] = params.type
    if params.state:
        data["state"] = params.state
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.assigned_to:
        data["assigned_to"] = params.assigned_to
    if params.work_notes:
        data["work_notes"] = params.work_notes

    url = f"{config.instance_url}/api/now/table/rm_scrum_task"

    try:
        headers = auth_manager.get_headers()
        headers["Content-Type"] = "application/json"

        response = auth_manager.make_request("POST", url, json=data, headers=headers)
        response.raise_for_status()

        result = response.json()

        invalidate_query_cache(table="rm_scrum_task")

        return {
            "success": True,
            "message": "Scrum Task created successfully",
            "scrum_task": result["result"],
        }
    except Exception as e:
        logger.error(f"Error creating scrum task: {e}")
        return {
            "success": False,
            "message": f"Error creating scrum task: {str(e)}",
        }


@register_tool(
    name="update_scrum_task",
    params=UpdateScrumTaskParams,
    description="Update an existing scrum task in ServiceNow",
    serialization="str",
    return_type=str,
)
def update_scrum_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateScrumTaskParams,
) -> Dict[str, Any]:
    """
    Update an existing scrum task in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for updating the scrum task.

    Returns:
        The updated scrum task.
    """
    data = {}

    if params.short_description:
        data["short_description"] = params.short_description
    if params.priority:
        data["priority"] = params.priority
    if params.planned_hours:
        data["planned_hours"] = params.planned_hours
    if params.remaining_hours:
        data["remaining_hours"] = params.remaining_hours
    if params.hours:
        data["hours"] = params.hours
    if params.description:
        data["description"] = params.description
    if params.type:
        data["type"] = params.type
    if params.state:
        data["state"] = params.state
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.assigned_to:
        data["assigned_to"] = params.assigned_to
    if params.work_notes:
        data["work_notes"] = params.work_notes

    url = f"{config.instance_url}/api/now/table/rm_scrum_task/{params.scrum_task_id}"

    try:
        headers = auth_manager.get_headers()
        headers["Content-Type"] = "application/json"

        response = auth_manager.make_request("PUT", url, json=data, headers=headers)
        response.raise_for_status()

        result = response.json()

        invalidate_query_cache(table="rm_scrum_task")

        return {
            "success": True,
            "message": "Scrum Task updated successfully",
            "scrum_task": result["result"],
        }
    except Exception as e:
        logger.error(f"Error updating scrum task: {e}")
        return {
            "success": False,
            "message": f"Error updating scrum task: {str(e)}",
        }


@register_tool(
    name="list_scrum_tasks",
    params=ListScrumTasksParams,
    description="List scrum tasks from ServiceNow",
    serialization="json",
    return_type=str,
)
def list_scrum_tasks(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListScrumTasksParams,
) -> Dict[str, Any]:
    """
    List scrum tasks from ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for listing scrum tasks.

    Returns:
        A list of scrum tasks.
    """
    query_parts = []

    if params.state:
        query_parts.append(f"state={params.state}")
    if params.assignment_group:
        query_parts.append(f"assignment_group={params.assignment_group}")

    if params.timeframe:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if params.timeframe == "upcoming":
            query_parts.append(f"start_date>{now}")
        elif params.timeframe == "in-progress":
            query_parts.append(f"start_date<{now}^end_date>{now}")
        elif params.timeframe == "completed":
            query_parts.append(f"end_date<{now}")

    if params.query:
        query_parts.append(params.query)

    query_str = "^".join(query_parts) if query_parts else ""

    try:
        result, total = sn_query_page(
            config,
            auth_manager,
            table="rm_scrum_task",
            query=query_str,
            fields="sys_id,short_description,description,story,priority,state,type,planned_hours,remaining_hours,hours,assigned_to,assignment_group,work_notes,sys_created_on,sys_updated_on",
            limit=min(params.limit or 10, 100),
            offset=params.offset or 0,
            display_value=True,
            fail_silently=False,
        )

        return {
            "success": True,
            "scrum_tasks": result,
            "count": len(result),
            "total": total if total is not None else len(result),
        }
    except Exception as e:
        logger.error(f"Error listing scrum tasks: {e}")
        return {
            "success": False,
            "message": f"Error listing scrum tasks: {str(e)}",
        }
