"""
Epic management tools for the ServiceNow MCP server.

This module provides tools for managing epics in ServiceNow.
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
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
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


def create_epic(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateEpicParams,
) -> Dict[str, Any]:
    """Create a new epic in ServiceNow."""
    data: Dict[str, Any] = {
        "short_description": params.short_description,
    }

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
        return {"success": False, "message": f"Error creating epic: {str(e)}"}


def update_epic(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateEpicParams,
) -> Dict[str, Any]:
    """Update an existing epic in ServiceNow."""
    data: Dict[str, Any] = {}

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

    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="rm_epic",
            sys_id=params.epic_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

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
        return {"success": False, "message": f"Error updating epic: {str(e)}"}


def list_epics(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListEpicsParams,
) -> Dict[str, Any]:
    """List epics from ServiceNow."""
    query_parts: List[str] = []

    if params.priority:
        query_parts.append(f"priority={params.priority}")
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
        return {"success": False, "message": f"Error listing epics: {str(e)}"}


# ---------------------------------------------------------------------------
# manage_epic — bundled CRUD for rm_epic
# ---------------------------------------------------------------------------

_EPIC_UPDATE_FIELDS = (
    "short_description",
    "description",
    "priority",
    "state",
    "assignment_group",
    "assigned_to",
    "work_notes",
)


class ManageEpicParams(BaseModel):
    """Manage epics — table: rm_epic."""

    action: Literal["list", "create", "update"] = Field(...)
    epic_id: Optional[str] = Field(default=None)
    short_description: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    priority: Optional[str] = Field(
        default=None, description="1=Critical,2=High,3=Moderate,4=Low,5=Planning"
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
    def _validate_per_action(self) -> "ManageEpicParams":
        a = self.action
        if a == "create":
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
        elif a == "update":
            if not self.epic_id:
                raise ValueError("epic_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _EPIC_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        return self


@register_tool(
    name="manage_epic",
    params=ManageEpicParams,
    description="Epic CRUD (table: rm_epic). list skips confirm.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_epic(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageEpicParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "create":
        return create_epic(
            config,
            auth_manager,
            CreateEpicParams(
                short_description=params.short_description,
                description=params.description,
                priority=params.priority,
                state=params.state,
                assignment_group=params.assignment_group,
                assigned_to=params.assigned_to,
                work_notes=params.work_notes,
            ),
        )
    if a == "update":
        return update_epic(
            config,
            auth_manager,
            UpdateEpicParams(
                epic_id=params.epic_id,
                short_description=params.short_description,
                description=params.description,
                priority=params.priority,
                state=params.state,
                assignment_group=params.assignment_group,
                assigned_to=params.assigned_to,
                work_notes=params.work_notes,
                dry_run=params.dry_run,
            ),
        )
    return list_epics(
        config,
        auth_manager,
        ListEpicsParams(
            limit=params.limit,
            offset=params.offset,
            priority=params.priority,
            assignment_group=params.assignment_group,
            timeframe=params.timeframe,
            query=params.query,
        ),
    )
