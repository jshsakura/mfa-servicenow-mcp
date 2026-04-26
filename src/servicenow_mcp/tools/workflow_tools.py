"""
Workflow management tools for the ServiceNow MCP server.

This module provides tools for viewing and managing workflows in ServiceNow.
"""

import logging
from typing import Any, Dict, List, Literal, Optional, Type, TypeVar

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_delete_preview, build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

# Type variable for Pydantic models
T = TypeVar("T", bound=BaseModel)


class ListWorkflowsParams(BaseModel):
    """Parameters for listing workflows."""

    limit: Optional[int] = Field(default=10, description="Maximum number of records to return")
    offset: Optional[int] = Field(default=0, description="Offset to start from")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    name: Optional[str] = Field(default=None, description="Filter by name (contains)")
    query: Optional[str] = Field(default=None, description="Additional query string")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records. Uses lightweight Aggregate API.",
    )


class GetWorkflowDetailsParams(BaseModel):
    """Parameters for getting workflow details with optional versions and activities."""

    workflow_id: str = Field(..., description="Workflow ID or sys_id")
    include_versions: bool = Field(
        default=False,
        description="Include version history for this workflow",
    )
    include_activities: bool = Field(
        default=False,
        description="Include ordered activity list. Uses latest published version unless version_id is specified.",
    )
    version_id: Optional[str] = Field(
        default=None,
        description="Specific version sys_id to fetch activities for (only used with include_activities=true)",
    )


class CreateWorkflowParams(BaseModel):
    """Parameters for creating a new workflow."""

    name: str = Field(..., description="Name of the workflow")
    description: Optional[str] = Field(default=None, description="Description of the workflow")
    table: Optional[str] = Field(default=None, description="Table the workflow applies to")
    active: Optional[bool] = Field(default=True, description="Whether the workflow is active")
    attributes: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional attributes for the workflow"
    )


class UpdateWorkflowParams(BaseModel):
    """Parameters for updating a workflow."""

    workflow_id: str = Field(..., description="Workflow ID or sys_id")
    name: Optional[str] = Field(default=None, description="Name of the workflow")
    description: Optional[str] = Field(default=None, description="Description of the workflow")
    table: Optional[str] = Field(default=None, description="Table the workflow applies to")
    active: Optional[bool] = Field(default=None, description="Whether the workflow is active")
    attributes: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional attributes for the workflow"
    )
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


class ActivateWorkflowParams(BaseModel):
    """Parameters for activating a workflow."""

    workflow_id: str = Field(..., description="Workflow ID or sys_id")


class DeactivateWorkflowParams(BaseModel):
    """Parameters for deactivating a workflow."""

    workflow_id: str = Field(..., description="Workflow ID or sys_id")


class AddWorkflowActivityParams(BaseModel):
    """Parameters for adding an activity to a workflow."""

    workflow_version_id: str = Field(..., description="Workflow version ID")
    name: str = Field(..., description="Name of the activity")
    description: Optional[str] = Field(default=None, description="Description of the activity")
    activity_type: str = Field(
        default=..., description="Type of activity (e.g., 'approval', 'task', 'notification')"
    )
    attributes: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional attributes for the activity"
    )


class UpdateWorkflowActivityParams(BaseModel):
    """Parameters for updating a workflow activity."""

    activity_id: str = Field(..., description="Activity ID or sys_id")
    name: Optional[str] = Field(default=None, description="Name of the activity")
    description: Optional[str] = Field(default=None, description="Description of the activity")
    attributes: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional attributes for the activity"
    )
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


class DeleteWorkflowActivityParams(BaseModel):
    """Parameters for deleting a workflow activity."""

    activity_id: str = Field(..., description="Activity ID or sys_id")
    dry_run: bool = Field(
        default=False,
        description="Preview deletion scope without executing.",
    )


class ReorderWorkflowActivitiesParams(BaseModel):
    """Parameters for reordering workflow activities."""

    workflow_id: str = Field(..., description="Workflow ID or sys_id")
    activity_ids: List[str] = Field(..., description="List of activity IDs in the desired order")


class ListWorkflowVersionsParams(BaseModel):
    """Parameters for listing workflow versions."""

    workflow_id: str = Field(..., description="Workflow sys_id")
    limit: int = Field(default=20, description="Maximum number of versions to return")
    offset: int = Field(default=0, description="Pagination offset")
    published_only: bool = Field(
        default=False,
        description="Only return published versions",
    )


class GetWorkflowActivitiesParams(BaseModel):
    """Parameters for getting workflow activities."""

    workflow_id: str = Field(
        ...,
        description="Workflow sys_id. Used to find the latest published version unless version_id is specified.",
    )
    version_id: Optional[str] = Field(
        default=None,
        description="Specific version sys_id. If omitted, uses the latest published version.",
    )
    limit: int = Field(default=100, description="Maximum number of activities to return")


class DeleteWorkflowParams(BaseModel):
    """Parameters for deleting a workflow."""

    workflow_id: str = Field(..., description="Workflow ID or sys_id")
    dry_run: bool = Field(
        default=False,
        description="Preview deletion scope without executing.",
    )


def _unwrap_params(params: Any, param_class: Type[T]) -> Dict[str, Any]:
    """
    Unwrap parameters if they're wrapped in a Pydantic model.
    This helps handle cases where the parameters are passed as a model instead of a dict.
    """
    if isinstance(params, dict):
        return params
    if isinstance(params, param_class):
        return params.model_dump(exclude_none=True)
    return params


def list_workflows(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    List workflows from ServiceNow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for listing workflows

    Returns:
        Dictionary containing the list of workflows
    """
    params = _unwrap_params(params, ListWorkflowsParams)

    # Build query string
    query_parts = []

    if params.get("active") is not None:
        query_parts.append(f"active={str(params['active']).lower()}")

    if params.get("name"):
        query_parts.append(f"nameLIKE{params['name']}")

    if params.get("query"):
        query_parts.append(params["query"])

    query_string = "^".join(query_parts) if query_parts else ""

    if params.get("count_only"):
        count = sn_count(server_config, auth_manager, "wf_workflow", query_string)
        return {"success": True, "count": count}

    # Make the API request
    try:
        rows, total = sn_query_page(
            server_config,
            auth_manager,
            table="wf_workflow",
            query=query_string,
            fields="",
            limit=params.get("limit", 10),
            offset=params.get("offset", 0),
            display_value=False,
            fail_silently=False,
        )
        return {
            "workflows": rows,
            "count": len(rows),
            "total": total or 0,
        }
    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        return {"error": str(e)}


def get_workflow_details(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get workflow details, optionally including versions and activities."""
    params = _unwrap_params(params, GetWorkflowDetailsParams)

    workflow_id = params.get("workflow_id")
    if not workflow_id:
        return {"error": "Workflow ID is required"}

    try:
        rows, _ = sn_query_page(
            server_config,
            auth_manager,
            table="wf_workflow",
            query=f"sys_id={workflow_id}",
            fields="",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=False,
        )
        if not rows:
            return {"error": f"Workflow {workflow_id} not found"}

        result: Dict[str, Any] = {"workflow": rows[0]}

        if params.get("include_versions"):
            result["versions"] = _fetch_workflow_versions(server_config, auth_manager, workflow_id)

        if params.get("include_activities"):
            act_result = _fetch_workflow_activities(
                server_config, auth_manager, workflow_id, params.get("version_id")
            )
            result.update(act_result)

        return result
    except Exception as e:
        logger.error(f"Error getting workflow details: {e}")
        return {"error": str(e)}


def _fetch_workflow_versions(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    workflow_id: str,
) -> List[Dict[str, Any]]:
    """Fetch version history for a workflow (internal helper)."""
    rows, _ = sn_query_page(
        server_config,
        auth_manager,
        table="wf_workflow_version",
        query=f"workflow={workflow_id}",
        fields="",
        limit=20,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    return rows


def _fetch_workflow_activities(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    workflow_id: str,
    version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch activities for a workflow version (internal helper).

    If version_id is not provided, uses the latest published version.
    """
    if not version_id:
        versions, _ = sn_query_page(
            server_config,
            auth_manager,
            table="wf_workflow_version",
            query=f"workflow={workflow_id}^published=true",
            fields="",
            limit=1,
            offset=0,
            orderby="-version",
            display_value=False,
            fail_silently=False,
        )
        if not versions:
            return {
                "activities": [],
                "activities_error": f"No published versions found for workflow {workflow_id}",
            }
        version_id = versions[0]["sys_id"]

    activities, _ = sn_query_page(
        server_config,
        auth_manager,
        table="wf_activity",
        query=f"workflow_version={version_id}",
        fields="",
        limit=100,
        offset=0,
        orderby="order",
        display_value=False,
        fail_silently=False,
    )
    return {
        "activities": activities,
        "activity_count": len(activities),
        "version_id": version_id,
    }


def create_workflow(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Create a new workflow in ServiceNow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for creating a workflow

    Returns:
        Dict[str, Any]: Created workflow details
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, CreateWorkflowParams)

    # Validate required parameters
    if not params.get("name"):
        return {"error": "Workflow name is required"}

    # Prepare data for the API request
    data = {
        "name": params["name"],
    }

    if params.get("description"):
        data["description"] = params["description"]

    if params.get("table"):
        data["table"] = params["table"]

    if params.get("active") is not None:
        data["active"] = str(params["active"]).lower()

    if params.get("attributes"):
        # Add any additional attributes
        data.update(params["attributes"])

    # Make the API request
    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/wf_workflow"

        response = auth_manager.make_request("POST", url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="wf_workflow")
        return {
            "workflow": result.get("result", {}),
            "message": "Workflow created successfully",
        }
    except Exception as e:
        logger.error(f"Error creating workflow: {e}")
        return {"error": str(e)}


def update_workflow(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update an existing workflow in ServiceNow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for updating a workflow

    Returns:
        Dict[str, Any]: Updated workflow details
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, UpdateWorkflowParams)

    workflow_id = params.get("workflow_id")
    if not workflow_id:
        return {"error": "Workflow ID is required"}

    # Prepare data for the API request
    data = {}

    if params.get("name"):
        data["name"] = params["name"]

    if params.get("description") is not None:
        data["description"] = params["description"]

    if params.get("table"):
        data["table"] = params["table"]

    if params.get("active") is not None:
        data["active"] = str(params["active"]).lower()

    if params.get("attributes"):
        # Add any additional attributes
        data.update(params["attributes"])

    if not data:
        return {"error": "No update parameters provided"}

    if params.get("dry_run"):
        return build_update_preview(
            server_config,
            auth_manager,
            table="wf_workflow",
            sys_id=workflow_id,
            proposed=data,
            identifier_fields=["name", "active", "published"],
        )

    # Make the API request
    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/wf_workflow/{workflow_id}"

        response = auth_manager.make_request("PATCH", url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="wf_workflow")
        return {
            "workflow": result.get("result", {}),
            "message": "Workflow updated successfully",
        }
    except Exception as e:
        logger.error(f"Error updating workflow: {e}")
        return {"error": str(e)}


def activate_workflow(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Activate a workflow in ServiceNow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for activating a workflow

    Returns:
        Dict[str, Any]: Activated workflow details
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, ActivateWorkflowParams)

    workflow_id = params.get("workflow_id")
    if not workflow_id:
        return {"error": "Workflow ID is required"}

    # Prepare data for the API request
    data = {
        "active": "true",
    }

    # Make the API request
    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/wf_workflow/{workflow_id}"

        response = auth_manager.make_request("PATCH", url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="wf_workflow")
        return {
            "workflow": result.get("result", {}),
            "message": "Workflow activated successfully",
        }
    except Exception as e:
        logger.error(f"Error activating workflow: {e}")
        return {"error": str(e)}


def deactivate_workflow(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deactivate a workflow in ServiceNow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for deactivating a workflow

    Returns:
        Dict[str, Any]: Deactivated workflow details
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, DeactivateWorkflowParams)

    workflow_id = params.get("workflow_id")
    if not workflow_id:
        return {"error": "Workflow ID is required"}

    # Prepare data for the API request
    data = {
        "active": "false",
    }

    # Make the API request
    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/wf_workflow/{workflow_id}"

        response = auth_manager.make_request("PATCH", url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="wf_workflow")
        return {
            "workflow": result.get("result", {}),
            "message": "Workflow deactivated successfully",
        }
    except Exception as e:
        logger.error(f"Error deactivating workflow: {e}")
        return {"error": str(e)}


def add_workflow_activity(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Add a new activity to a workflow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for adding a workflow activity

    Returns:
        Dict[str, Any]: Added workflow activity details
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, AddWorkflowActivityParams)

    # Validate required parameters
    workflow_version_id = params.get("workflow_version_id")
    if not workflow_version_id:
        return {"error": "Workflow version ID is required"}

    activity_name = params.get("name")
    if not activity_name:
        return {"error": "Activity name is required"}

    # Prepare data for the API request
    data = {
        "workflow_version": workflow_version_id,
        "name": activity_name,
    }

    if params.get("description"):
        data["description"] = params["description"]

    if params.get("activity_type"):
        data["activity_type"] = params["activity_type"]

    if params.get("attributes"):
        # Add any additional attributes
        data.update(params["attributes"])

    # Make the API request
    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/wf_activity"

        response = auth_manager.make_request("POST", url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="wf_activity")
        return {
            "activity": result.get("result", {}),
            "message": "Workflow activity added successfully",
        }
    except Exception as e:
        logger.error(f"Error adding workflow activity: {e}")
        return {"error": str(e)}


def update_workflow_activity(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Update an existing activity in a workflow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for updating a workflow activity

    Returns:
        Dict[str, Any]: Updated workflow activity details
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, UpdateWorkflowActivityParams)

    activity_id = params.get("activity_id")
    if not activity_id:
        return {"error": "Activity ID is required"}

    # Prepare data for the API request
    data = {}

    if params.get("name"):
        data["name"] = params["name"]

    if params.get("description") is not None:
        data["description"] = params["description"]

    if params.get("attributes"):
        # Add any additional attributes
        data.update(params["attributes"])

    if not data:
        return {"error": "No update parameters provided"}

    if params.get("dry_run"):
        return build_update_preview(
            server_config,
            auth_manager,
            table="wf_activity",
            sys_id=activity_id,
            proposed=data,
            identifier_fields=["name", "activity_definition", "workflow_version"],
        )

    # Make the API request
    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/wf_activity/{activity_id}"

        response = auth_manager.make_request("PATCH", url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="wf_activity")
        return {
            "activity": result.get("result", {}),
            "message": "Activity updated successfully",
        }
    except Exception as e:
        logger.error(f"Error updating workflow activity: {e}")
        return {"error": str(e)}


def delete_workflow_activity(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Delete an activity from a workflow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for deleting a workflow activity

    Returns:
        Dict[str, Any]: Result of the deletion operation
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, DeleteWorkflowActivityParams)

    activity_id = params.get("activity_id")
    if not activity_id:
        return {"error": "Activity ID is required"}

    if params.get("dry_run"):
        return build_delete_preview(
            server_config,
            auth_manager,
            table="wf_activity",
            sys_id=activity_id,
            identifier_fields=["name", "activity_definition", "workflow_version"],
        )

    # Make the API request
    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/wf_activity/{activity_id}"

        response = auth_manager.make_request("DELETE", url, headers=headers)
        response.raise_for_status()

        invalidate_query_cache(table="wf_activity")
        return {
            "message": "Activity deleted successfully",
            "activity_id": activity_id,
        }
    except Exception as e:
        logger.error(f"Error deleting workflow activity: {e}")
        return {"error": str(e)}


def reorder_workflow_activities(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Reorder activities in a workflow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for reordering workflow activities

    Returns:
        Dict[str, Any]: Result of the reordering operation
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, ReorderWorkflowActivitiesParams)

    workflow_id = params.get("workflow_id")
    if not workflow_id:
        return {"error": "Workflow ID is required"}

    activity_ids = params.get("activity_ids")
    if not activity_ids:
        return {"error": "Activity IDs are required"}

    # Make the API requests to update the order of each activity
    try:
        headers = auth_manager.get_headers()
        results = []

        for i, activity_id in enumerate(activity_ids):
            # Calculate the new order value (100, 200, 300, etc.)
            new_order = (i + 1) * 100

            url = f"{server_config.instance_url}/api/now/table/wf_activity/{activity_id}"
            data = {"order": new_order}

            try:
                response = auth_manager.make_request("PATCH", url, headers=headers, json=data)
                response.raise_for_status()

                results.append(
                    {
                        "activity_id": activity_id,
                        "new_order": new_order,
                        "success": True,
                    }
                )
            except Exception as e:
                logger.error(f"Error updating activity order: {e}")
                results.append(
                    {
                        "activity_id": activity_id,
                        "error": str(e),
                        "success": False,
                    }
                )

        invalidate_query_cache(table="wf_activity")
        return {
            "message": "Activities reordered",
            "workflow_id": workflow_id,
            "results": results,
        }
    except Exception as e:
        logger.error(f"Unexpected error reordering workflow activities: {e}")
        return {"error": str(e)}


def delete_workflow(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Delete a workflow from ServiceNow.

    Args:
        auth_manager: Authentication manager
        server_config: Server configuration
        params: Parameters for deleting a workflow

    Returns:
        Dict[str, Any]: Result of the deletion operation
    """
    # Unwrap parameters if needed
    params = _unwrap_params(params, DeleteWorkflowParams)

    workflow_id = params.get("workflow_id")
    if not workflow_id:
        return {"error": "Workflow ID is required"}

    if params.get("dry_run"):
        return build_delete_preview(
            server_config,
            auth_manager,
            table="wf_workflow",
            sys_id=workflow_id,
            identifier_fields=["name", "description", "active", "published"],
            dependency_checks=[
                {"table": "wf_workflow_version", "field": "workflow", "label": "versions"},
                {
                    "table": "wf_activity",
                    "field": "workflow_version.workflow",
                    "label": "activities",
                },
                {"table": "wf_context", "field": "workflow", "label": "running_contexts"},
            ],
        )

    # Make the API request
    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/wf_workflow/{workflow_id}"

        response = auth_manager.make_request("DELETE", url, headers=headers)
        response.raise_for_status()

        invalidate_query_cache(table="wf_workflow")
        return {
            "message": f"Workflow {workflow_id} deleted successfully",
            "workflow_id": workflow_id,
        }
    except Exception as e:
        logger.error(f"Error deleting workflow: {e}")
        return {"error": str(e)}


def list_workflow_versions(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """List version history for a workflow."""
    params = _unwrap_params(params, ListWorkflowVersionsParams)

    workflow_id = params.get("workflow_id")
    if not workflow_id:
        return {"error": "Workflow ID is required"}

    query = f"workflow={workflow_id}"
    if params.get("published_only"):
        query += "^published=true"

    try:
        rows, total = sn_query_page(
            server_config,
            auth_manager,
            table="wf_workflow_version",
            query=query,
            fields="",
            limit=params.get("limit", 20),
            offset=params.get("offset", 0),
            orderby="-version",
            display_value=False,
            fail_silently=False,
        )
        return {
            "versions": rows,
            "count": len(rows),
            "total": total or 0,
            "workflow_id": workflow_id,
        }
    except Exception as e:
        logger.error(f"Error listing workflow versions: {e}")
        return {"error": str(e)}


def get_workflow_activities(
    server_config: ServerConfig,
    auth_manager: AuthManager,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get activities for a workflow version."""
    params = _unwrap_params(params, GetWorkflowActivitiesParams)

    workflow_id = params.get("workflow_id")
    if not workflow_id:
        return {"error": "Workflow ID is required"}

    try:
        result = _fetch_workflow_activities(
            server_config, auth_manager, workflow_id, params.get("version_id")
        )
        result["workflow_id"] = workflow_id
        return result
    except Exception as e:
        logger.error(f"Error getting workflow activities: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# manage_workflow — bundled CRUD + lifecycle + activity ops for wf_workflow
# ---------------------------------------------------------------------------

_WORKFLOW_UPDATE_FIELDS = ("name", "description", "table", "active", "attributes")
_ACTIVITY_UPDATE_FIELDS = ("activity_name", "activity_description", "attributes")


class ManageWorkflowParams(BaseModel):
    """Manage workflows + activities — table: wf_workflow / wf_activity.

    Required per action:
      create:             name
      update:             workflow_id, at least one workflow field
      activate:           workflow_id
      deactivate:         workflow_id
      delete:             workflow_id
      add_activity:       workflow_version_id, activity_name, activity_type
      update_activity:    activity_id, at least one activity field
      delete_activity:    activity_id
      reorder_activities: workflow_id, activity_ids (list)
    """

    action: Literal[
        "list",
        "get",
        "list_versions",
        "get_activities",
        "create",
        "update",
        "activate",
        "deactivate",
        "delete",
        "add_activity",
        "update_activity",
        "delete_activity",
        "reorder_activities",
    ] = Field(...)

    # Workflow identifier
    workflow_id: Optional[str] = Field(default=None)
    workflow_version_id: Optional[str] = Field(default=None, description="add_activity")

    # list/get params
    limit: int = Field(default=10, description="Max records (list mode)")
    offset: int = Field(default=0, description="Pagination offset (list mode)")
    query: Optional[str] = Field(default=None, description="Additional query string (list mode)")
    count_only: bool = Field(default=False, description="Return count only (list mode)")
    include_versions: bool = Field(default=False, description="Include version history (get mode)")
    include_activities: bool = Field(default=False, description="Include activity list (get mode)")
    version_id: Optional[str] = Field(default=None, description="Specific version for activities")
    published_only: bool = Field(
        default=False, description="Only published versions (list_versions mode)"
    )

    # Activity identifier
    activity_id: Optional[str] = Field(default=None)

    # Workflow create/update fields
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    table: Optional[str] = Field(default=None)
    active: Optional[bool] = Field(default=None)
    attributes: Optional[Dict[str, Any]] = Field(default=None)

    # Activity-specific (prefixed to avoid clashing with workflow `name`/`description`)
    activity_name: Optional[str] = Field(default=None)
    activity_description: Optional[str] = Field(default=None)
    activity_type: Optional[str] = Field(default=None, description="add_activity only")

    # reorder_activities
    activity_ids: Optional[List[str]] = Field(default=None)

    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageWorkflowParams":
        a = self.action
        if a in ("list", "get", "list_versions", "get_activities"):
            pass
        elif a == "create":
            if not self.name:
                raise ValueError("name is required for action='create'")
        elif a == "update":
            if not self.workflow_id:
                raise ValueError("workflow_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _WORKFLOW_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        elif a in ("activate", "deactivate", "delete"):
            if not self.workflow_id:
                raise ValueError(f"workflow_id is required for action='{a}'")
        elif a == "add_activity":
            if not self.workflow_version_id:
                raise ValueError("workflow_version_id is required for action='add_activity'")
            if not self.activity_name:
                raise ValueError("activity_name is required for action='add_activity'")
            if not self.activity_type:
                raise ValueError("activity_type is required for action='add_activity'")
        elif a == "update_activity":
            if not self.activity_id:
                raise ValueError("activity_id is required for action='update_activity'")
            if not any(getattr(self, f) is not None for f in _ACTIVITY_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update_activity'")
        elif a == "delete_activity":
            if not self.activity_id:
                raise ValueError("activity_id is required for action='delete_activity'")
        elif a == "reorder_activities":
            if not self.workflow_id:
                raise ValueError("workflow_id is required for action='reorder_activities'")
            if not self.activity_ids:
                raise ValueError("activity_ids is required for action='reorder_activities'")
        return self


@register_tool(
    name="manage_workflow",
    params=ManageWorkflowParams,
    description="List/get/CRUD + lifecycle + activity ops for workflows (table: wf_workflow / wf_activity).",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_workflow(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageWorkflowParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "list":
        return list_workflows(
            auth_manager,
            config,
            {
                "name": params.name,
                "active": params.active,
                "table": params.table,
                "query": params.query,
                "limit": params.limit,
                "offset": params.offset,
                "count_only": params.count_only,
            },
        )
    if a == "get":
        if not params.workflow_id:
            return {"error": "workflow_id is required for action='get'"}
        return get_workflow_details(
            auth_manager,
            config,
            {
                "workflow_id": params.workflow_id,
                "include_versions": params.include_versions,
                "include_activities": params.include_activities,
                "version_id": params.version_id,
            },
        )
    if a == "list_versions":
        if not params.workflow_id:
            return {"error": "workflow_id is required for action='list_versions'"}
        return list_workflow_versions(
            auth_manager,
            config,
            {
                "workflow_id": params.workflow_id,
                "limit": params.limit,
                "offset": params.offset,
                "published_only": params.published_only,
            },
        )
    if a == "get_activities":
        if not params.workflow_id:
            return {"error": "workflow_id is required for action='get_activities'"}
        return get_workflow_activities(
            auth_manager,
            config,
            {"workflow_id": params.workflow_id, "version_id": params.version_id},
        )
    if a == "create":
        kwargs: Dict[str, Any] = {"name": params.name}
        for f in ("description", "table", "active", "attributes"):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return create_workflow(config, auth_manager, CreateWorkflowParams(**kwargs))
    if a == "update":
        kwargs = {"workflow_id": params.workflow_id, "dry_run": params.dry_run}
        for f in _WORKFLOW_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return update_workflow(config, auth_manager, UpdateWorkflowParams(**kwargs))
    if a == "activate":
        return activate_workflow(
            config, auth_manager, ActivateWorkflowParams(workflow_id=params.workflow_id)
        )
    if a == "deactivate":
        return deactivate_workflow(
            config, auth_manager, DeactivateWorkflowParams(workflow_id=params.workflow_id)
        )
    if a == "delete":
        return delete_workflow(
            config,
            auth_manager,
            DeleteWorkflowParams(workflow_id=params.workflow_id, dry_run=params.dry_run),
        )
    if a == "add_activity":
        kwargs = {
            "workflow_version_id": params.workflow_version_id,
            "name": params.activity_name,
            "activity_type": params.activity_type,
        }
        if params.activity_description is not None:
            kwargs["description"] = params.activity_description
        if params.attributes is not None:
            kwargs["attributes"] = params.attributes
        return add_workflow_activity(config, auth_manager, AddWorkflowActivityParams(**kwargs))
    if a == "update_activity":
        kwargs = {"activity_id": params.activity_id, "dry_run": params.dry_run}
        if params.activity_name is not None:
            kwargs["name"] = params.activity_name
        if params.activity_description is not None:
            kwargs["description"] = params.activity_description
        if params.attributes is not None:
            kwargs["attributes"] = params.attributes
        return update_workflow_activity(
            config, auth_manager, UpdateWorkflowActivityParams(**kwargs)
        )
    if a == "delete_activity":
        return delete_workflow_activity(
            config,
            auth_manager,
            DeleteWorkflowActivityParams(activity_id=params.activity_id, dry_run=params.dry_run),
        )
    # reorder_activities
    return reorder_workflow_activities(
        config,
        auth_manager,
        ReorderWorkflowActivitiesParams(
            workflow_id=params.workflow_id, activity_ids=params.activity_ids
        ),
    )
