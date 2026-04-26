"""
Scrum Task management tools for the ServiceNow MCP server.

This module provides tools for managing scrum tasks in ServiceNow.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class CreateScrumTaskParams(BaseModel):
    """Parameters for creating a scrum task."""

    story: str = Field(
        default=...,
        description="Short description of the story. It requires the System ID of the story.",
    )
    short_description: str = Field(..., description="Short description of the scrum task")
    priority: Optional[str] = Field(
        default=None,
        description="Priority of scrum task (1 is Critical, 2 is High, 3 is Moderate, 4 is Low)",
    )
    planned_hours: Optional[int] = Field(
        default=None, description="Planned hours for the scrum task"
    )
    remaining_hours: Optional[int] = Field(
        default=None, description="Remaining hours for the scrum task"
    )
    hours: Optional[int] = Field(default=None, description="Actual Hours for the scrum task")
    description: Optional[str] = Field(
        default=None, description="Detailed description of the scrum task"
    )
    type: Optional[str] = Field(
        default=None,
        description="Type of scrum task (1 is Analysis, 2 is Coding, 3 is Documentation, 4 is Testing)",
    )
    state: Optional[str] = Field(
        default=None,
        description="State of scrum task (-6 is Draft,1 is Ready, 2 is Work in progress, 3 is Complete, 4 is Cancelled)",
    )
    assignment_group: Optional[str] = Field(
        default=None, description="Group assigned to the scrum task"
    )
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the scrum task")
    work_notes: Optional[str] = Field(
        default=None, description="Work notes to add to the scrum task"
    )


class UpdateScrumTaskParams(BaseModel):
    """Parameters for updating a scrum task."""

    scrum_task_id: str = Field(..., description="Scrum Task ID or sys_id")
    short_description: Optional[str] = Field(
        default=None, description="Short description of the scrum task"
    )
    priority: Optional[str] = Field(
        default=None,
        description="Priority of scrum task (1 is Critical, 2 is High, 3 is Moderate, 4 is Low)",
    )
    planned_hours: Optional[int] = Field(
        default=None, description="Planned hours for the scrum task"
    )
    remaining_hours: Optional[int] = Field(
        default=None, description="Remaining hours for the scrum task"
    )
    hours: Optional[int] = Field(default=None, description="Actual Hours for the scrum task")
    description: Optional[str] = Field(
        default=None, description="Detailed description of the scrum task"
    )
    type: Optional[str] = Field(
        default=None,
        description="Type of scrum task (1 is Analysis, 2 is Coding, 3 is Documentation, 4 is Testing)",
    )
    state: Optional[str] = Field(
        default=None,
        description="State of scrum task (-6 is Draft,1 is Ready, 2 is Work in progress, 3 is Complete, 4 is Cancelled)",
    )
    assignment_group: Optional[str] = Field(
        default=None, description="Group assigned to the scrum task"
    )
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the scrum task")
    work_notes: Optional[str] = Field(
        default=None, description="Work notes to add to the scrum task"
    )
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


class ListScrumTasksParams(BaseModel):
    """Parameters for listing scrum tasks."""

    limit: Optional[int] = Field(default=10, description="Maximum number of records to return")
    offset: Optional[int] = Field(default=0, description="Offset to start from")
    state: Optional[str] = Field(default=None, description="Filter by state")
    assignment_group: Optional[str] = Field(default=None, description="Filter by assignment group")
    timeframe: Optional[str] = Field(
        default=None, description="Filter by timeframe (upcoming, in-progress, completed)"
    )
    query: Optional[str] = Field(default=None, description="Additional query string")


def create_scrum_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateScrumTaskParams,
) -> Dict[str, Any]:
    """Create a new scrum task in ServiceNow."""
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
        return {"success": False, "message": f"Error creating scrum task: {str(e)}"}


def update_scrum_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateScrumTaskParams,
) -> Dict[str, Any]:
    """Update an existing scrum task in ServiceNow."""
    data: Dict[str, Any] = {}

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

    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="rm_scrum_task",
            sys_id=params.scrum_task_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

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
        return {"success": False, "message": f"Error updating scrum task: {str(e)}"}


def list_scrum_tasks(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListScrumTasksParams,
) -> Dict[str, Any]:
    """List scrum tasks from ServiceNow."""
    query_parts: List[str] = []

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
        return {"success": False, "message": f"Error listing scrum tasks: {str(e)}"}


# ---------------------------------------------------------------------------
# manage_scrum_task — bundled CRUD for rm_scrum_task
# ---------------------------------------------------------------------------

_SCRUM_TASK_UPDATE_FIELDS = (
    "short_description",
    "priority",
    "planned_hours",
    "remaining_hours",
    "hours",
    "description",
    "type",
    "state",
    "assignment_group",
    "assigned_to",
    "work_notes",
)


class ManageScrumTaskParams(BaseModel):
    """Manage scrum tasks — table: rm_scrum_task."""

    action: Literal["list", "create", "update"] = Field(...)
    scrum_task_id: Optional[str] = Field(default=None)
    story: Optional[str] = Field(default=None, description="Story sys_id (required for create)")
    short_description: Optional[str] = Field(default=None)
    priority: Optional[str] = Field(default=None, description="1=Critical,2=High,3=Moderate,4=Low")
    planned_hours: Optional[int] = Field(default=None)
    remaining_hours: Optional[int] = Field(default=None)
    hours: Optional[int] = Field(default=None, description="Actual hours")
    description: Optional[str] = Field(default=None)
    type: Optional[str] = Field(
        default=None, description="1=Analysis,2=Coding,3=Documentation,4=Testing"
    )
    state: Optional[str] = Field(
        default=None, description="-6=Draft,1=Ready,2=WIP,3=Complete,4=Cancelled"
    )
    assignment_group: Optional[str] = Field(default=None)
    assigned_to: Optional[str] = Field(default=None)
    work_notes: Optional[str] = Field(default=None)
    limit: int = Field(default=10)
    offset: int = Field(default=0)
    timeframe: Optional[str] = Field(default=None, description="upcoming | in-progress | completed")
    query: Optional[str] = Field(default=None)
    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageScrumTaskParams":
        a = self.action
        if a == "create":
            if not self.story:
                raise ValueError("story is required for action='create'")
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
        elif a == "update":
            if not self.scrum_task_id:
                raise ValueError("scrum_task_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _SCRUM_TASK_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        return self


@register_tool(
    name="manage_scrum_task",
    params=ManageScrumTaskParams,
    description="Scrum task CRUD (table: rm_scrum_task). list skips confirm.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_scrum_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageScrumTaskParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "create":
        return create_scrum_task(
            config,
            auth_manager,
            CreateScrumTaskParams(
                story=params.story,
                short_description=params.short_description,
                priority=params.priority,
                planned_hours=params.planned_hours,
                remaining_hours=params.remaining_hours,
                hours=params.hours,
                description=params.description,
                type=params.type,
                state=params.state,
                assignment_group=params.assignment_group,
                assigned_to=params.assigned_to,
                work_notes=params.work_notes,
            ),
        )
    if a == "update":
        return update_scrum_task(
            config,
            auth_manager,
            UpdateScrumTaskParams(
                scrum_task_id=params.scrum_task_id,
                short_description=params.short_description,
                priority=params.priority,
                planned_hours=params.planned_hours,
                remaining_hours=params.remaining_hours,
                hours=params.hours,
                description=params.description,
                type=params.type,
                state=params.state,
                assignment_group=params.assignment_group,
                assigned_to=params.assigned_to,
                work_notes=params.work_notes,
                dry_run=params.dry_run,
            ),
        )
    return list_scrum_tasks(
        config,
        auth_manager,
        ListScrumTasksParams(
            limit=params.limit,
            offset=params.offset,
            state=params.state,
            assignment_group=params.assignment_group,
            timeframe=params.timeframe,
            query=params.query,
        ),
    )
