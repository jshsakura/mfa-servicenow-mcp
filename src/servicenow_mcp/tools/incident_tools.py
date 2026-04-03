"""
Incident tools for the ServiceNow MCP server.

This module provides tools for managing incidents in ServiceNow.
"""

import logging
from typing import Optional

import requests
from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class CreateIncidentParams(BaseModel):
    """Parameters for creating an incident."""

    short_description: str = Field(..., description="Short description of the incident")
    description: Optional[str] = Field(None, description="Detailed description of the incident")
    caller_id: Optional[str] = Field(None, description="User who reported the incident")
    category: Optional[str] = Field(None, description="Category of the incident")
    subcategory: Optional[str] = Field(None, description="Subcategory of the incident")
    priority: Optional[str] = Field(None, description="Priority of the incident")
    impact: Optional[str] = Field(None, description="Impact of the incident")
    urgency: Optional[str] = Field(None, description="Urgency of the incident")
    assigned_to: Optional[str] = Field(None, description="User assigned to the incident")
    assignment_group: Optional[str] = Field(None, description="Group assigned to the incident")


class UpdateIncidentParams(BaseModel):
    """Parameters for updating an incident."""

    incident_id: str = Field(..., description="Incident ID or sys_id")
    short_description: Optional[str] = Field(None, description="Short description of the incident")
    description: Optional[str] = Field(None, description="Detailed description of the incident")
    state: Optional[str] = Field(None, description="State of the incident")
    category: Optional[str] = Field(None, description="Category of the incident")
    subcategory: Optional[str] = Field(None, description="Subcategory of the incident")
    priority: Optional[str] = Field(None, description="Priority of the incident")
    impact: Optional[str] = Field(None, description="Impact of the incident")
    urgency: Optional[str] = Field(None, description="Urgency of the incident")
    assigned_to: Optional[str] = Field(None, description="User assigned to the incident")
    assignment_group: Optional[str] = Field(None, description="Group assigned to the incident")
    work_notes: Optional[str] = Field(None, description="Work notes to add to the incident")
    close_notes: Optional[str] = Field(None, description="Close notes to add to the incident")
    close_code: Optional[str] = Field(None, description="Close code for the incident")


class AddCommentParams(BaseModel):
    """Parameters for adding a comment to an incident."""

    incident_id: str = Field(..., description="Incident ID or sys_id")
    comment: str = Field(..., description="Comment to add to the incident")
    is_work_note: bool = Field(False, description="Whether the comment is a work note")


class ResolveIncidentParams(BaseModel):
    """Parameters for resolving an incident."""

    incident_id: str = Field(..., description="Incident ID or sys_id")
    resolution_code: str = Field(..., description="Resolution code for the incident")
    resolution_notes: str = Field(..., description="Resolution notes for the incident")


class ListIncidentsParams(BaseModel):
    """Parameters for listing incidents."""

    limit: int = Field(10, description="Maximum number of incidents to return")
    offset: int = Field(0, description="Offset for pagination")
    state: Optional[str] = Field(None, description="Filter by incident state")
    assigned_to: Optional[str] = Field(None, description="Filter by assigned user")
    category: Optional[str] = Field(None, description="Filter by category")
    query: Optional[str] = Field(None, description="Search query for incidents")
    count_only: bool = Field(
        False,
        description="Return count only without fetching records. Uses lightweight Aggregate API.",
    )


class GetIncidentByNumberParams(BaseModel):
    """Parameters for fetching an incident by its number."""

    incident_number: str = Field(..., description="The number of the incident to fetch")


class IncidentResponse(BaseModel):
    """Response from incident operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    incident_id: Optional[str] = Field(None, description="ID of the affected incident")
    incident_number: Optional[str] = Field(None, description="Number of the affected incident")


def _resolve_incident_sys_id(
    config: ServerConfig,
    auth_manager: AuthManager,
    incident_id: str,
) -> tuple[str | None, IncidentResponse | None]:
    """Resolve an incident identifier (sys_id or number) to a sys_id.

    Returns:
        (sys_id, None) on success, or (None, error_response) on failure.
    """
    if len(incident_id) == 32 and all(c in "0123456789abcdef" for c in incident_id):
        return incident_id, None

    try:
        query_url = f"{config.api_url}/table/incident"
        query_params = {
            "sysparm_query": f"number={incident_id}",
            "sysparm_limit": 1,
        }
        response = auth_manager.make_request(
            "GET",
            query_url,
            params=query_params,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", [])
        if not result:
            return None, IncidentResponse(
                success=False,
                message=f"Incident not found: {incident_id}",
            )

        return result[0].get("sys_id"), None

    except requests.RequestException as e:
        logger.error(f"Failed to find incident: {e}")
        return None, IncidentResponse(
            success=False,
            message=f"Failed to find incident: {str(e)}",
        )


@register_tool(
    "create_incident",
    params=CreateIncidentParams,
    description="Create a new incident (short_description required). Returns sys_id and INC number on success.",
    serialization="str",
    return_type=str,
)
def create_incident(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateIncidentParams,
) -> IncidentResponse:
    """
    Create a new incident in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for creating the incident.

    Returns:
        Response with the created incident details.
    """
    api_url = f"{config.api_url}/table/incident"

    # Build request data - only include provided fields
    data = params.model_dump(exclude_none=True)

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

        return IncidentResponse(
            success=True,
            message="Incident created successfully",
            incident_id=result.get("sys_id"),
            incident_number=result.get("number"),
        )

    except requests.RequestException as e:
        logger.error(f"Failed to create incident: {e}")
        return IncidentResponse(
            success=False,
            message=f"Failed to create incident: {str(e)}",
        )


@register_tool(
    "update_incident",
    params=UpdateIncidentParams,
    description="Update an incident by sys_id or INC number with partial field changes. Accepts any incident field.",
    serialization="str",
    return_type=str,
)
def update_incident(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateIncidentParams,
) -> IncidentResponse:
    """
    Update an existing incident in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for updating the incident.

    Returns:
        Response with the updated incident details.
    """
    sys_id, err = _resolve_incident_sys_id(config, auth_manager, params.incident_id)
    if err:
        return err
    api_url = f"{config.api_url}/table/incident/{sys_id}"

    # Build request data - only include provided fields
    data = params.model_dump(exclude={"incident_id"}, exclude_none=True)

    # Make request
    try:
        response = auth_manager.make_request(
            "PUT",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})

        return IncidentResponse(
            success=True,
            message="Incident updated successfully",
            incident_id=result.get("sys_id"),
            incident_number=result.get("number"),
        )

    except requests.RequestException as e:
        logger.error(f"Failed to update incident: {e}")
        return IncidentResponse(
            success=False,
            message=f"Failed to update incident: {str(e)}",
        )


@register_tool(
    "add_comment",
    params=AddCommentParams,
    description="Add a work note (internal) or customer-visible comment to an incident by sys_id or INC number.",
    serialization="str",
    return_type=str,
)
def add_comment(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: AddCommentParams,
) -> IncidentResponse:
    """
    Add a comment to an incident in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for adding the comment.

    Returns:
        Response with the result of the operation.
    """
    sys_id, err = _resolve_incident_sys_id(config, auth_manager, params.incident_id)
    if err:
        return err
    api_url = f"{config.api_url}/table/incident/{sys_id}"

    # Build request data
    data = {"work_notes" if params.is_work_note else "comments": params.comment}

    # Make request
    try:
        response = auth_manager.make_request(
            "PUT",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})

        return IncidentResponse(
            success=True,
            message="Comment added successfully",
            incident_id=result.get("sys_id"),
            incident_number=result.get("number"),
        )

    except requests.RequestException as e:
        logger.error(f"Failed to add comment: {e}")
        return IncidentResponse(
            success=False,
            message=f"Failed to add comment: {str(e)}",
        )


@register_tool(
    "resolve_incident",
    params=ResolveIncidentParams,
    description="Set incident state to Resolved with resolution_code and close_notes. Use update_incident for other state changes.",
    serialization="str",
    return_type=str,
)
def resolve_incident(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ResolveIncidentParams,
) -> IncidentResponse:
    """
    Resolve an incident in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for resolving the incident.

    Returns:
        Response with the result of the operation.
    """
    sys_id, err = _resolve_incident_sys_id(config, auth_manager, params.incident_id)
    if err:
        return err
    api_url = f"{config.api_url}/table/incident/{sys_id}"

    # Build request data
    data = {
        "state": "6",  # Resolved
        "close_code": params.resolution_code,
        "close_notes": params.resolution_notes,
        "resolved_at": "now",
    }

    # Make request
    try:
        response = auth_manager.make_request(
            "PUT",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})

        return IncidentResponse(
            success=True,
            message="Incident resolved successfully",
            incident_id=result.get("sys_id"),
            incident_number=result.get("number"),
        )

    except requests.RequestException as e:
        logger.error(f"Failed to resolve incident: {e}")
        return IncidentResponse(
            success=False,
            message=f"Failed to resolve incident: {str(e)}",
        )


@register_tool(
    "list_incidents",
    params=ListIncidentsParams,
    description="List incidents with state/category/assignee filters. Returns summary fields only — use get_incident_by_number for full details.",
    serialization="json",
    return_type=str,
)
def list_incidents(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListIncidentsParams,
) -> dict:
    """
    List incidents from ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for listing incidents.

    Returns:
        Dictionary with list of incidents.
    """
    api_url = f"{config.api_url}/table/incident"

    # Build filters
    filters = []
    if params.state:
        filters.append(f"state={params.state}")
    if params.assigned_to:
        filters.append(f"assigned_to={params.assigned_to}")
    if params.category:
        filters.append(f"category={params.category}")
    if params.query:
        filters.append(f"short_descriptionLIKE{params.query}^ORdescriptionLIKE{params.query}")

    query_string = "^".join(filters) if filters else ""

    if params.count_only:
        from .sn_api import sn_count

        count = sn_count(config, auth_manager, "incident", query_string)
        return {"success": True, "count": count}

    # Build query parameters
    query_params = {
        "sysparm_limit": min(params.limit, 100),
        "sysparm_offset": params.offset,
        "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
    }

    if query_string:
        query_params["sysparm_query"] = query_string

    # Make request
    try:
        response = auth_manager.make_request(
            "GET",
            api_url,
            params=query_params,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        data = response.json()
        incidents = []

        for incident_data in data.get("result", []):
            # Handle assigned_to field which could be a string or a dictionary
            assigned_to = incident_data.get("assigned_to")
            if isinstance(assigned_to, dict):
                assigned_to = assigned_to.get("display_value")

            incident = {
                "sys_id": incident_data.get("sys_id"),
                "number": incident_data.get("number"),
                "short_description": incident_data.get("short_description"),
                "description": incident_data.get("description"),
                "state": incident_data.get("state"),
                "priority": incident_data.get("priority"),
                "assigned_to": assigned_to,
                "category": incident_data.get("category"),
                "subcategory": incident_data.get("subcategory"),
                "created_on": incident_data.get("sys_created_on"),
                "updated_on": incident_data.get("sys_updated_on"),
            }
            incidents.append(incident)

        return {
            "success": True,
            "message": f"Found {len(incidents)} incidents",
            "incidents": incidents,
        }

    except requests.RequestException as e:
        logger.error(f"Failed to list incidents: {e}")
        return {"success": False, "message": f"Failed to list incidents: {str(e)}", "incidents": []}


@register_tool(
    "get_incident_by_number",
    params=GetIncidentByNumberParams,
    description="Fetch a single incident by INC number with full field details including timestamps and assignment info.",
    serialization="json_dict",
    return_type=str,
)
def get_incident_by_number(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetIncidentByNumberParams,
) -> dict:
    """
    Fetch a single incident from ServiceNow by its number.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for fetching the incident.

    Returns:
        Dictionary with the incident details.
    """
    api_url = f"{config.api_url}/table/incident"

    # Build query parameters
    query_params = {
        "sysparm_query": f"number={params.incident_number}",
        "sysparm_limit": 1,
        "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
    }

    # Make request
    try:
        response = auth_manager.make_request(
            "GET",
            api_url,
            params=query_params,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        data = response.json()
        result = data.get("result", [])

        if not result:
            return {
                "success": False,
                "message": f"Incident not found: {params.incident_number}",
            }

        incident_data = result[0]
        assigned_to = incident_data.get("assigned_to")
        if isinstance(assigned_to, dict):
            assigned_to = assigned_to.get("display_value")

        incident = {
            "sys_id": incident_data.get("sys_id"),
            "number": incident_data.get("number"),
            "short_description": incident_data.get("short_description"),
            "description": incident_data.get("description"),
            "state": incident_data.get("state"),
            "priority": incident_data.get("priority"),
            "assigned_to": assigned_to,
            "category": incident_data.get("category"),
            "subcategory": incident_data.get("subcategory"),
            "created_on": incident_data.get("sys_created_on"),
            "updated_on": incident_data.get("sys_updated_on"),
        }

        return {
            "success": True,
            "message": f"Incident {params.incident_number} found",
            "incident": incident,
        }

    except requests.RequestException as e:
        logger.error(f"Failed to fetch incident: {e}")
        return {
            "success": False,
            "message": f"Failed to fetch incident: {str(e)}",
        }
