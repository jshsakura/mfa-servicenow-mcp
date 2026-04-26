"""
Story management tools for the ServiceNow MCP server.

This module provides tools for managing stories in ServiceNow.
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


class CreateStoryParams(BaseModel):
    """Parameters for creating a story."""

    short_description: str = Field(..., description="Short description of the story")
    acceptance_criteria: str = Field(..., description="Acceptance criteria for the story")
    description: Optional[str] = Field(
        default=None, description="Detailed description of the story"
    )
    # -6 Draft, -7 Ready for Testing, -8 Testing, 1 Ready,
    # 2 Work in progress, 3 Complete, 4 Cancelled.
    state: Optional[Literal["-6", "-7", "-8", "1", "2", "3", "4"]] = Field(
        default=None,
        description="Story state code.",
    )
    assignment_group: Optional[str] = Field(default=None, description="Group assigned to the story")
    story_points: Optional[int] = Field(default=10, description="Points value for the story")
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the story")
    epic: Optional[str] = Field(
        default=None,
        description="Epic that the story belongs to. It requires the System ID of the epic.",
    )
    project: Optional[str] = Field(
        default=None,
        description="Project that the story belongs to. It requires the System ID of the project.",
    )
    work_notes: Optional[str] = Field(
        default=None,
        description="Work notes to add to the story. Used for adding notes and comments to a story",
    )


class UpdateStoryParams(BaseModel):
    """Parameters for updating a story."""

    story_id: str = Field(
        default=...,
        description="Story IDNumber or sys_id. You will need to fetch the story to get the sys_id if you only have the story number",
    )
    short_description: Optional[str] = Field(
        default=None, description="Short description of the story"
    )
    acceptance_criteria: Optional[str] = Field(
        default=None, description="Acceptance criteria for the story"
    )
    description: Optional[str] = Field(
        default=None, description="Detailed description of the story"
    )
    # -6 Draft, -7 Ready for Testing, -8 Testing, 1 Ready,
    # 2 Work in progress, 3 Complete, 4 Cancelled.
    state: Optional[Literal["-6", "-7", "-8", "1", "2", "3", "4"]] = Field(
        default=None,
        description="Story state code.",
    )
    assignment_group: Optional[str] = Field(default=None, description="Group assigned to the story")
    story_points: Optional[int] = Field(default=None, description="Points value for the story")
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the story")
    epic: Optional[str] = Field(
        default=None,
        description="Epic that the story belongs to. It requires the System ID of the epic.",
    )
    project: Optional[str] = Field(
        default=None,
        description="Project that the story belongs to. It requires the System ID of the project.",
    )
    work_notes: Optional[str] = Field(
        default=None,
        description="Work notes to add to the story. Used for adding notes and comments to a story",
    )
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


class ListStoriesParams(BaseModel):
    """Parameters for listing stories."""

    limit: Optional[int] = Field(default=10, description="Maximum number of records to return")
    offset: Optional[int] = Field(default=0, description="Offset to start from")
    state: Optional[str] = Field(default=None, description="Filter by state")
    assignment_group: Optional[str] = Field(default=None, description="Filter by assignment group")
    timeframe: Optional[str] = Field(
        default=None, description="Filter by timeframe (upcoming, in-progress, completed)"
    )
    query: Optional[str] = Field(default=None, description="Additional query string")


class ListStoryDependenciesParams(BaseModel):
    """Parameters for listing story dependencies."""

    limit: Optional[int] = Field(default=10, description="Maximum number of records to return")
    offset: Optional[int] = Field(default=0, description="Offset to start from")
    query: Optional[str] = Field(default=None, description="Additional query string")
    dependent_story: Optional[str] = Field(
        default=None, description="Sys_id of the dependent story is required"
    )
    prerequisite_story: Optional[str] = Field(
        default=None, description="Sys_id that this story depends on is required"
    )


class CreateStoryDependencyParams(BaseModel):
    """Parameters for creating a story dependency."""

    dependent_story: str = Field(..., description="Sys_id of the dependent story is required")
    prerequisite_story: str = Field(
        default=..., description="Sys_id that this story depends on is required"
    )


class DeleteStoryDependencyParams(BaseModel):
    """Parameters for deleting a story dependency."""

    dependency_id: str = Field(..., description="Sys_id of the dependency is required")


def create_story(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateStoryParams,
) -> Dict[str, Any]:
    """Create a new story in ServiceNow."""
    data: Dict[str, Any] = {
        "short_description": params.short_description,
        "acceptance_criteria": params.acceptance_criteria,
    }

    if params.description:
        data["description"] = params.description
    if params.state:
        data["state"] = params.state
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.story_points:
        data["story_points"] = params.story_points
    if params.assigned_to:
        data["assigned_to"] = params.assigned_to
    if params.epic:
        data["epic"] = params.epic
    if params.project:
        data["project"] = params.project
    if params.work_notes:
        data["work_notes"] = params.work_notes

    url = f"{config.instance_url}/api/now/table/rm_story"

    try:
        response = auth_manager.make_request("POST", url, json=data)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="rm_story")
        return {
            "success": True,
            "message": "Story created successfully",
            "story": result["result"],
        }
    except Exception as e:
        logger.error(f"Error creating story: {e}")
        return {"success": False, "message": f"Error creating story: {str(e)}"}


def update_story(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateStoryParams,
) -> Dict[str, Any]:
    """Update an existing story in ServiceNow."""
    data: Dict[str, Any] = {}

    if params.short_description:
        data["short_description"] = params.short_description
    if params.acceptance_criteria:
        data["acceptance_criteria"] = params.acceptance_criteria
    if params.description:
        data["description"] = params.description
    if params.state:
        data["state"] = params.state
    if params.assignment_group:
        data["assignment_group"] = params.assignment_group
    if params.story_points:
        data["story_points"] = params.story_points
    if params.epic:
        data["epic"] = params.epic
    if params.project:
        data["project"] = params.project
    if params.assigned_to:
        data["assigned_to"] = params.assigned_to
    if params.work_notes:
        data["work_notes"] = params.work_notes

    url = f"{config.instance_url}/api/now/table/rm_story/{params.story_id}"

    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="rm_story",
            sys_id=params.story_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

    try:
        response = auth_manager.make_request("PUT", url, json=data)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="rm_story")
        return {
            "success": True,
            "message": "Story updated successfully",
            "story": result["result"],
        }
    except Exception as e:
        logger.error(f"Error updating story: {e}")
        return {"success": False, "message": f"Error updating story: {str(e)}"}


def list_stories(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListStoriesParams,
) -> Dict[str, Any]:
    """List stories from ServiceNow."""
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
            table="rm_story",
            query=query,
            fields="sys_id,short_description,description,state,story_points,assigned_to,assignment_group,epic,project,acceptance_criteria,start_date,end_date,sys_created_on,sys_updated_on",
            limit=min(params.limit or 10, 100),
            offset=params.offset or 0,
            display_value=True,
            fail_silently=False,
        )
        return {
            "success": True,
            "stories": rows,
            "count": len(rows),
            "total": total_count or len(rows),
        }
    except Exception as e:
        logger.error(f"Error listing stories: {e}")
        return {"success": False, "message": f"Error listing stories: {str(e)}"}


def list_story_dependencies(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListStoryDependenciesParams,
) -> Dict[str, Any]:
    """List story dependencies from ServiceNow."""
    query_parts: List[str] = []

    if params.dependent_story:
        query_parts.append(f"dependent_story={params.dependent_story}")
    if params.prerequisite_story:
        query_parts.append(f"prerequisite_story={params.prerequisite_story}")
    if params.query:
        query_parts.append(params.query)

    query = "^".join(query_parts) if query_parts else ""

    try:
        rows, total_count = sn_query_page(
            config,
            auth_manager,
            table="m2m_story_dependencies",
            query=query,
            fields="sys_id,dependent_story,prerequisite_story,sys_created_on,sys_updated_on",
            limit=min(params.limit or 10, 100),
            offset=params.offset or 0,
            display_value=True,
            fail_silently=False,
        )
        return {
            "success": True,
            "story_dependencies": rows,
            "count": len(rows),
            "total": total_count or len(rows),
        }
    except Exception as e:
        logger.error(f"Error listing story dependencies: {e}")
        return {"success": False, "message": f"Error listing story dependencies: {str(e)}"}


def create_story_dependency(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateStoryDependencyParams,
) -> Dict[str, Any]:
    """Create a dependency between two stories in ServiceNow."""
    data = {
        "dependent_story": params.dependent_story,
        "prerequisite_story": params.prerequisite_story,
    }

    url = f"{config.instance_url}/api/now/table/m2m_story_dependencies"

    try:
        response = auth_manager.make_request("POST", url, json=data)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="m2m_story_dependencies")
        return {
            "success": True,
            "message": "Story dependency created successfully",
            "story_dependency": result["result"],
        }
    except Exception as e:
        logger.error(f"Error creating story dependency: {e}")
        return {"success": False, "message": f"Error creating story dependency: {str(e)}"}


def delete_story_dependency(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DeleteStoryDependencyParams,
) -> Dict[str, Any]:
    """Delete a story dependency in ServiceNow."""
    url = f"{config.instance_url}/api/now/table/m2m_story_dependencies/{params.dependency_id}"

    try:
        response = auth_manager.make_request("DELETE", url)
        response.raise_for_status()
        invalidate_query_cache(table="m2m_story_dependencies")
        return {"success": True, "message": "Story dependency deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting story dependency: {e}")
        return {"success": False, "message": f"Error deleting story dependency: {str(e)}"}


# ---------------------------------------------------------------------------
# manage_story — bundled CRUD + dependency ops for rm_story
# ---------------------------------------------------------------------------

_STORY_UPDATE_FIELDS = (
    "short_description",
    "acceptance_criteria",
    "description",
    "state",
    "assignment_group",
    "story_points",
    "assigned_to",
    "epic",
    "project",
    "work_notes",
)


class ManageStoryParams(BaseModel):
    """Manage stories — tables: rm_story, m2m_story_dependencies."""

    action: Literal[
        "list", "create", "update", "list_dependencies", "create_dependency", "delete_dependency"
    ] = Field(...)
    story_id: Optional[str] = Field(default=None)
    short_description: Optional[str] = Field(default=None)
    acceptance_criteria: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    state: Optional[Literal["-6", "-7", "-8", "1", "2", "3", "4"]] = Field(
        default=None, description="Story state code"
    )
    assignment_group: Optional[str] = Field(default=None)
    story_points: Optional[int] = Field(default=None)
    assigned_to: Optional[str] = Field(default=None)
    epic: Optional[str] = Field(default=None, description="Epic sys_id")
    project: Optional[str] = Field(default=None, description="Project sys_id")
    work_notes: Optional[str] = Field(default=None)
    dependent_story: Optional[str] = Field(
        default=None, description="Dependent story sys_id (dependency ops)"
    )
    prerequisite_story: Optional[str] = Field(
        default=None, description="Prerequisite story sys_id (dependency ops)"
    )
    dependency_id: Optional[str] = Field(
        default=None, description="Dependency sys_id (delete_dependency)"
    )
    limit: int = Field(default=10)
    offset: int = Field(default=0)
    timeframe: Optional[str] = Field(default=None, description="upcoming | in-progress | completed")
    query: Optional[str] = Field(default=None)
    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageStoryParams":
        a = self.action
        if a == "create":
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
            if not self.acceptance_criteria:
                raise ValueError("acceptance_criteria is required for action='create'")
        elif a == "update":
            if not self.story_id:
                raise ValueError("story_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _STORY_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        elif a == "create_dependency":
            if not self.dependent_story:
                raise ValueError("dependent_story is required for action='create_dependency'")
            if not self.prerequisite_story:
                raise ValueError("prerequisite_story is required for action='create_dependency'")
        elif a == "delete_dependency":
            if not self.dependency_id:
                raise ValueError("dependency_id is required for action='delete_dependency'")
        return self


@register_tool(
    name="manage_story",
    params=ManageStoryParams,
    description="Story CRUD + dependency ops (rm_story/m2m_story_dependencies). list/list_dependencies skip confirm.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_story(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageStoryParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "create":
        return create_story(
            config,
            auth_manager,
            CreateStoryParams(
                short_description=params.short_description,
                acceptance_criteria=params.acceptance_criteria,
                description=params.description,
                state=params.state,
                assignment_group=params.assignment_group,
                story_points=params.story_points,
                assigned_to=params.assigned_to,
                epic=params.epic,
                project=params.project,
                work_notes=params.work_notes,
            ),
        )
    if a == "update":
        return update_story(
            config,
            auth_manager,
            UpdateStoryParams(
                story_id=params.story_id,
                short_description=params.short_description,
                acceptance_criteria=params.acceptance_criteria,
                description=params.description,
                state=params.state,
                assignment_group=params.assignment_group,
                story_points=params.story_points,
                assigned_to=params.assigned_to,
                epic=params.epic,
                project=params.project,
                work_notes=params.work_notes,
                dry_run=params.dry_run,
            ),
        )
    if a == "list_dependencies":
        return list_story_dependencies(
            config,
            auth_manager,
            ListStoryDependenciesParams(
                limit=params.limit,
                offset=params.offset,
                query=params.query,
                dependent_story=params.dependent_story,
                prerequisite_story=params.prerequisite_story,
            ),
        )
    if a == "create_dependency":
        return create_story_dependency(
            config,
            auth_manager,
            CreateStoryDependencyParams(
                dependent_story=params.dependent_story,
                prerequisite_story=params.prerequisite_story,
            ),
        )
    if a == "delete_dependency":
        return delete_story_dependency(
            config,
            auth_manager,
            DeleteStoryDependencyParams(dependency_id=params.dependency_id),
        )
    return list_stories(
        config,
        auth_manager,
        ListStoriesParams(
            limit=params.limit,
            offset=params.offset,
            state=params.state,
            assignment_group=params.assignment_group,
            timeframe=params.timeframe,
            query=params.query,
        ),
    )
