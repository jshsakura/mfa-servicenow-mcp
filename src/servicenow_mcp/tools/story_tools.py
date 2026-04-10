"""
Story management tools for the ServiceNow MCP server.

This module provides tools for managing stories in ServiceNow.
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


class CreateStoryParams(BaseModel):
    """Parameters for creating a story."""

    short_description: str = Field(..., description="Short description of the story")
    acceptance_criteria: str = Field(..., description="Acceptance criteria for the story")
    description: Optional[str] = Field(None, description="Detailed description of the story")
    state: Optional[str] = Field(
        None,
        description="State of story (-6 is Draft,-7 is Ready for Testing,-8 is Testing,1 is Ready, 2 is Work in progress, 3 is Complete, 4 is Cancelled)",
    )
    assignment_group: Optional[str] = Field(None, description="Group assigned to the story")
    story_points: Optional[int] = Field(10, description="Points value for the story")
    assigned_to: Optional[str] = Field(None, description="User assigned to the story")
    epic: Optional[str] = Field(
        None, description="Epic that the story belongs to. It requires the System ID of the epic."
    )
    project: Optional[str] = Field(
        None,
        description="Project that the story belongs to. It requires the System ID of the project.",
    )
    work_notes: Optional[str] = Field(
        None,
        description="Work notes to add to the story. Used for adding notes and comments to a story",
    )


class UpdateStoryParams(BaseModel):
    """Parameters for updating a story."""

    story_id: str = Field(
        ...,
        description="Story IDNumber or sys_id. You will need to fetch the story to get the sys_id if you only have the story number",
    )
    short_description: Optional[str] = Field(None, description="Short description of the story")
    acceptance_criteria: Optional[str] = Field(
        None, description="Acceptance criteria for the story"
    )
    description: Optional[str] = Field(None, description="Detailed description of the story")
    state: Optional[str] = Field(
        None,
        description="State of story (-6 is Draft,-7 is Ready for Testing,-8 is Testing,1 is Ready, 2 is Work in progress, 3 is Complete, 4 is Cancelled)",
    )
    assignment_group: Optional[str] = Field(None, description="Group assigned to the story")
    story_points: Optional[int] = Field(None, description="Points value for the story")
    assigned_to: Optional[str] = Field(None, description="User assigned to the story")
    epic: Optional[str] = Field(
        None, description="Epic that the story belongs to. It requires the System ID of the epic."
    )
    project: Optional[str] = Field(
        None,
        description="Project that the story belongs to. It requires the System ID of the project.",
    )
    work_notes: Optional[str] = Field(
        None,
        description="Work notes to add to the story. Used for adding notes and comments to a story",
    )


class ListStoriesParams(BaseModel):
    """Parameters for listing stories."""

    limit: Optional[int] = Field(10, description="Maximum number of records to return")
    offset: Optional[int] = Field(0, description="Offset to start from")
    state: Optional[str] = Field(None, description="Filter by state")
    assignment_group: Optional[str] = Field(None, description="Filter by assignment group")
    timeframe: Optional[str] = Field(
        None, description="Filter by timeframe (upcoming, in-progress, completed)"
    )
    query: Optional[str] = Field(None, description="Additional query string")


class ListStoryDependenciesParams(BaseModel):
    """Parameters for listing story dependencies."""

    limit: Optional[int] = Field(10, description="Maximum number of records to return")
    offset: Optional[int] = Field(0, description="Offset to start from")
    query: Optional[str] = Field(None, description="Additional query string")
    dependent_story: Optional[str] = Field(
        None, description="Sys_id of the dependent story is required"
    )
    prerequisite_story: Optional[str] = Field(
        None, description="Sys_id that this story depends on is required"
    )


class CreateStoryDependencyParams(BaseModel):
    """Parameters for creating a story dependency."""

    dependent_story: str = Field(..., description="Sys_id of the dependent story is required")
    prerequisite_story: str = Field(
        ..., description="Sys_id that this story depends on is required"
    )


class DeleteStoryDependencyParams(BaseModel):
    """Parameters for deleting a story dependency."""

    dependency_id: str = Field(..., description="Sys_id of the dependency is required")


@register_tool(
    name="create_story",
    params=CreateStoryParams,
    description="Create a new story in ServiceNow",
    serialization="str",
    return_type=str,
)
def create_story(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateStoryParams,
) -> Dict[str, Any]:
    """
    Create a new story in ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for creating the story.

    Returns:
        The created story.
    """
    # Prepare the request data
    data: Dict[str, Any] = {
        "short_description": params.short_description,
        "acceptance_criteria": params.acceptance_criteria,
    }

    # Add optional fields if provided
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
        return {
            "success": False,
            "message": f"Error creating story: {str(e)}",
        }


@register_tool(
    name="update_story",
    params=UpdateStoryParams,
    description="Update an existing story in ServiceNow",
    serialization="str",
    return_type=str,
)
def update_story(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateStoryParams,
) -> Dict[str, Any]:
    """
    Update an existing story in ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for updating the story.

    Returns:
        The updated story.
    """
    # Prepare the request data
    data: Dict[str, Any] = {}

    # Add optional fields if provided
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
        return {
            "success": False,
            "message": f"Error updating story: {str(e)}",
        }


@register_tool(
    name="list_stories",
    params=ListStoriesParams,
    description="List stories from ServiceNow",
    serialization="json",
    return_type=str,
)
def list_stories(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListStoriesParams,
) -> Dict[str, Any]:
    """
    List stories from ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for listing stories.

    Returns:
        A list of stories.
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
        return {
            "success": False,
            "message": f"Error listing stories: {str(e)}",
        }


@register_tool(
    name="list_story_dependencies",
    params=ListStoryDependenciesParams,
    description="List story dependencies from ServiceNow",
    serialization="json",
    return_type=str,
)
def list_story_dependencies(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListStoryDependenciesParams,
) -> Dict[str, Any]:
    """
    List story dependencies from ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for listing story dependencies.

    Returns:
        A list of story dependencies.
    """
    # Build the query
    query_parts: List[str] = []

    if params.dependent_story:
        query_parts.append(f"dependent_story={params.dependent_story}")
    if params.prerequisite_story:
        query_parts.append(f"prerequisite_story={params.prerequisite_story}")

    # Add any additional query string
    if params.query:
        query_parts.append(params.query)

    # Combine query parts
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
        return {
            "success": False,
            "message": f"Error listing story dependencies: {str(e)}",
        }


@register_tool(
    name="create_story_dependency",
    params=CreateStoryDependencyParams,
    description="Create a dependency between two stories in ServiceNow",
    serialization="str",
    return_type=str,
)
def create_story_dependency(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateStoryDependencyParams,
) -> Dict[str, Any]:
    """
    Create a dependency between two stories in ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for creating a story dependency.

    Returns:
        The created story dependency.
    """
    # Prepare the request data
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
        return {
            "success": False,
            "message": f"Error creating story dependency: {str(e)}",
        }


@register_tool(
    name="delete_story_dependency",
    params=DeleteStoryDependencyParams,
    description="Delete a story dependency in ServiceNow",
    serialization="str",
    return_type=str,
)
def delete_story_dependency(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DeleteStoryDependencyParams,
) -> Dict[str, Any]:
    """
    Delete a story dependency in ServiceNow.

    Args:
        config: The server configuration.
        auth_manager: The authentication manager.
        params: The parameters for deleting a story dependency.

    Returns:
        The deleted story dependency.
    """
    url = f"{config.instance_url}/api/now/table/m2m_story_dependencies/{params.dependency_id}"

    try:
        response = auth_manager.make_request("DELETE", url)
        response.raise_for_status()

        invalidate_query_cache(table="m2m_story_dependencies")

        return {
            "success": True,
            "message": "Story dependency deleted successfully",
        }
    except Exception as e:
        logger.error(f"Error deleting story dependency: {e}")
        return {
            "success": False,
            "message": f"Error deleting story dependency: {str(e)}",
        }
