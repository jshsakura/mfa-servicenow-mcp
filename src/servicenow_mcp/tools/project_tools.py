"""
Project management tools for the ServiceNow MCP server.

This module provides tools for managing projects in ServiceNow.
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


class CreateProjectParams(BaseModel):
    """Parameters for creating a project."""

    short_description: str = Field(..., description="Project name of the project")
    description: Optional[str] = Field(
        default=None, description="Detailed description of the project"
    )
    status: Optional[str] = Field(
        default=None, description="Status of the project (green, yellow, red)"
    )
    # -5 Pending, 1 Open, 2 Work in progress, 3 Closed Complete,
    # 4 Closed Incomplete, 5 Closed Skipped.
    state: Optional[Literal["-5", "1", "2", "3", "4", "5"]] = Field(
        default=None,
        description="Project state code.",
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
    # -5 Pending, 1 Open, 2 Work in progress, 3 Closed Complete,
    # 4 Closed Incomplete, 5 Closed Skipped.
    state: Optional[Literal["-5", "1", "2", "3", "4", "5"]] = Field(
        default=None,
        description="Project state code.",
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
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


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


def create_project(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateProjectParams,
) -> Dict[str, Any]:
    """Create a new project in ServiceNow."""
    data: Dict[str, Any] = {
        "short_description": params.short_description,
    }

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
        return {"success": False, "message": f"Error creating project: {str(e)}"}


def update_project(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateProjectParams,
) -> Dict[str, Any]:
    """Update an existing project in ServiceNow."""
    data: Dict[str, Any] = {}

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

    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="pm_project",
            sys_id=params.project_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

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
        return {"success": False, "message": f"Error updating project: {str(e)}"}


def list_projects(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListProjectsParams,
) -> Dict[str, Any]:
    """List projects from ServiceNow."""
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
        return {"success": False, "message": f"Error listing projects: {str(e)}"}


# ---------------------------------------------------------------------------
# manage_project — bundled CRUD for pm_project
# ---------------------------------------------------------------------------

_PROJECT_UPDATE_FIELDS = (
    "short_description",
    "description",
    "status",
    "state",
    "project_manager",
    "percentage_complete",
    "assignment_group",
    "assigned_to",
    "start_date",
    "end_date",
)


class ManageProjectParams(BaseModel):
    """Manage projects — table: pm_project."""

    action: Literal["list", "create", "update"] = Field(...)
    project_id: Optional[str] = Field(default=None)
    short_description: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None, description="Status (green, yellow, red)")
    state: Optional[Literal["-5", "1", "2", "3", "4", "5"]] = Field(
        default=None, description="Project state code"
    )
    project_manager: Optional[str] = Field(default=None)
    percentage_complete: Optional[int] = Field(default=None)
    assignment_group: Optional[str] = Field(default=None)
    assigned_to: Optional[str] = Field(default=None)
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    limit: int = Field(default=10)
    offset: int = Field(default=0)
    timeframe: Optional[str] = Field(default=None, description="upcoming | in-progress | completed")
    query: Optional[str] = Field(default=None)
    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageProjectParams":
        a = self.action
        if a == "create":
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
        elif a == "update":
            if not self.project_id:
                raise ValueError("project_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _PROJECT_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        return self


@register_tool(
    name="manage_project",
    params=ManageProjectParams,
    description="Project CRUD (table: pm_project). list skips confirm.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_project(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageProjectParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "create":
        return create_project(
            config,
            auth_manager,
            CreateProjectParams(
                short_description=params.short_description,
                description=params.description,
                status=params.status,
                state=params.state,
                project_manager=params.project_manager,
                percentage_complete=params.percentage_complete,
                assignment_group=params.assignment_group,
                assigned_to=params.assigned_to,
                start_date=params.start_date,
                end_date=params.end_date,
            ),
        )
    if a == "update":
        return update_project(
            config,
            auth_manager,
            UpdateProjectParams(
                project_id=params.project_id,
                short_description=params.short_description,
                description=params.description,
                status=params.status,
                state=params.state,
                project_manager=params.project_manager,
                percentage_complete=params.percentage_complete,
                assignment_group=params.assignment_group,
                assigned_to=params.assigned_to,
                start_date=params.start_date,
                end_date=params.end_date,
                dry_run=params.dry_run,
            ),
        )
    return list_projects(
        config,
        auth_manager,
        ListProjectsParams(
            limit=params.limit,
            offset=params.offset,
            state=params.state,
            assignment_group=params.assignment_group,
            timeframe=params.timeframe,
            query=params.query,
        ),
    )
