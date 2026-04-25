"""
Incident tools for the ServiceNow MCP server.

This module provides tools for managing incidents in ServiceNow.
"""

import logging
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from ._preview import build_update_preview
from .sn_api import invalidate_query_cache, sn_count, sn_query_page

logger = logging.getLogger(__name__)


class CreateIncidentParams(BaseModel):
    """Parameters for creating an incident."""

    short_description: str = Field(..., description="Short description of the incident")
    description: Optional[str] = Field(
        default=None, description="Detailed description of the incident"
    )
    caller_id: Optional[str] = Field(default=None, description="User who reported the incident")
    category: Optional[str] = Field(default=None, description="Category of the incident")
    subcategory: Optional[str] = Field(default=None, description="Subcategory of the incident")
    priority: Optional[str] = Field(default=None, description="Priority of the incident")
    impact: Optional[str] = Field(default=None, description="Impact of the incident")
    urgency: Optional[str] = Field(default=None, description="Urgency of the incident")
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the incident")
    assignment_group: Optional[str] = Field(
        default=None, description="Group assigned to the incident"
    )


class UpdateIncidentParams(BaseModel):
    """Parameters for updating an incident."""

    incident_id: str = Field(..., description="Incident ID or sys_id")
    short_description: Optional[str] = Field(
        default=None, description="Short description of the incident"
    )
    description: Optional[str] = Field(
        default=None, description="Detailed description of the incident"
    )
    state: Optional[str] = Field(default=None, description="State of the incident")
    category: Optional[str] = Field(default=None, description="Category of the incident")
    subcategory: Optional[str] = Field(default=None, description="Subcategory of the incident")
    priority: Optional[str] = Field(default=None, description="Priority of the incident")
    impact: Optional[str] = Field(default=None, description="Impact of the incident")
    urgency: Optional[str] = Field(default=None, description="Urgency of the incident")
    assigned_to: Optional[str] = Field(default=None, description="User assigned to the incident")
    assignment_group: Optional[str] = Field(
        default=None, description="Group assigned to the incident"
    )
    work_notes: Optional[str] = Field(default=None, description="Work notes to add to the incident")
    close_notes: Optional[str] = Field(
        default=None, description="Close notes to add to the incident"
    )
    close_code: Optional[str] = Field(default=None, description="Close code for the incident")
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


class AddCommentParams(BaseModel):
    """Parameters for adding a comment to an incident."""

    incident_id: str = Field(..., description="Incident ID or sys_id")
    comment: str = Field(..., description="Comment to add to the incident")
    is_work_note: bool = Field(default=False, description="Whether the comment is a work note")


class ResolveIncidentParams(BaseModel):
    """Parameters for resolving an incident."""

    incident_id: str = Field(..., description="Incident ID or sys_id")
    resolution_code: str = Field(..., description="Resolution code for the incident")
    resolution_notes: str = Field(..., description="Resolution notes for the incident")
    dry_run: bool = Field(
        default=False,
        description="Preview state transition without executing.",
    )


class GetIncidentByNumberParams(BaseModel):
    """Parameters for fetching an incident by number, or listing incidents with filters."""

    incident_number: Optional[str] = Field(
        default=None,
        description="The number of the incident to fetch. If provided, returns full details for that single incident.",
    )
    limit: int = Field(default=10, description="Maximum number of incidents to return (list mode)")
    offset: int = Field(default=0, description="Offset for pagination (list mode)")
    state: Optional[str] = Field(default=None, description="Filter by incident state (list mode)")
    assigned_to: Optional[str] = Field(
        default=None, description="Filter by assigned user (list mode)"
    )
    category: Optional[str] = Field(default=None, description="Filter by category (list mode)")
    query: Optional[str] = Field(default=None, description="Search query for incidents (list mode)")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records. Uses lightweight Aggregate API. (list mode)",
    )


class IncidentResponse(BaseModel):
    """Response from incident operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    incident_id: Optional[str] = Field(default=None, description="ID of the affected incident")
    incident_number: Optional[str] = Field(
        default=None, description="Number of the affected incident"
    )


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

    except Exception as e:
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

        invalidate_query_cache(table="incident")

        return IncidentResponse(
            success=True,
            message="Incident created successfully",
            incident_id=result.get("sys_id"),
            incident_number=result.get("number"),
        )

    except Exception as e:
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
    data = params.model_dump(exclude={"incident_id", "dry_run"}, exclude_none=True)

    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="incident",
            sys_id=sys_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

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

        invalidate_query_cache(table="incident")

        return IncidentResponse(
            success=True,
            message="Incident updated successfully",
            incident_id=result.get("sys_id"),
            incident_number=result.get("number"),
        )

    except Exception as e:
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

        invalidate_query_cache(table="incident")

        return IncidentResponse(
            success=True,
            message="Comment added successfully",
            incident_id=result.get("sys_id"),
            incident_number=result.get("number"),
        )

    except Exception as e:
        logger.error(f"Failed to add comment: {e}")
        return IncidentResponse(
            success=False,
            message=f"Failed to add comment: {str(e)}",
        )


@register_tool(
    "resolve_incident",
    params=ResolveIncidentParams,
    description="Set incident to Resolved state. Requires resolution_code and close_notes. Use update_incident for other state changes.",
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

    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="incident",
            sys_id=sys_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

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

        invalidate_query_cache(table="incident")

        return IncidentResponse(
            success=True,
            message="Incident resolved successfully",
            incident_id=result.get("sys_id"),
            incident_number=result.get("number"),
        )

    except Exception as e:
        logger.error(f"Failed to resolve incident: {e}")
        return IncidentResponse(
            success=False,
            message=f"Failed to resolve incident: {str(e)}",
        )


@register_tool(
    "get_incident_by_number",
    params=GetIncidentByNumberParams,
    description="Get a single incident by number, or list incidents with filters. Provide incident_number for detail.",
    serialization="json_dict",
    return_type=str,
)
def get_incident_by_number(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetIncidentByNumberParams,
) -> dict:
    """
    Fetch a single incident by number (detail mode) or list incidents with
    filters (list mode).

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters — supply incident_number for detail, omit for list.

    Returns:
        Dictionary with the incident details or a list of incidents.
    """
    # ── Detail mode: single incident lookup ──────────────────────────
    if params.incident_number:
        try:
            records, _ = sn_query_page(
                config,
                auth_manager,
                table="incident",
                query=f"number={params.incident_number}",
                fields="",
                limit=1,
                offset=0,
                display_value=True,
                fail_silently=False,
            )

            if not records:
                return {
                    "success": False,
                    "message": f"Incident not found: {params.incident_number}",
                }

            incident_data = records[0]
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

        except Exception as e:
            logger.error(f"Failed to fetch incident: {e}")
            return {
                "success": False,
                "message": f"Failed to fetch incident: {str(e)}",
            }

    # ── List mode: filtered incident list ────────────────────────────
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
        count = sn_count(config, auth_manager, "incident", query_string)
        return {"success": True, "count": count}

    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="incident",
            query=query_string,
            fields="sys_id,number,short_description,description,state,priority,assigned_to,category,subcategory,sys_created_on,sys_updated_on",
            limit=params.limit,
            offset=params.offset,
            display_value=True,
            fail_silently=False,
        )

        incidents = []
        for incident_data in records:
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

    except Exception as e:
        logger.error(f"Failed to list incidents: {e}")
        return {"success": False, "message": f"Failed to list incidents: {str(e)}", "incidents": []}


# ---------------------------------------------------------------------------
# manage_incident — bundled CRUD for the incident table
# ---------------------------------------------------------------------------

# Fields that map straight from manage_incident params → CreateIncidentParams /
# UpdateIncidentParams. Defined once so the dispatch helpers stay terse and a
# new field gets picked up automatically.
_INCIDENT_CREATE_FIELDS = (
    "short_description",
    "description",
    "caller_id",
    "category",
    "subcategory",
    "priority",
    "impact",
    "urgency",
    "assigned_to",
    "assignment_group",
)
_INCIDENT_UPDATE_FIELDS = (
    "short_description",
    "description",
    "state",
    "category",
    "subcategory",
    "priority",
    "impact",
    "urgency",
    "assigned_to",
    "assignment_group",
    "work_notes",
    "close_notes",
    "close_code",
)


class ManageIncidentParams(BaseModel):
    """Manage incidents — table: incident.

    Required per action:
      create:  short_description
      update:  incident_id, at least one field to change
      comment: incident_id, comment
      resolve: incident_id, resolution_code, resolution_notes
    """

    action: Literal["create", "update", "comment", "resolve"] = Field(
        ..., description="Operation to perform"
    )

    # Identifier (update/comment/resolve)
    incident_id: Optional[str] = Field(
        default=None, description="sys_id or INC number for update/comment/resolve"
    )

    # Create + update common fields
    short_description: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    caller_id: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    subcategory: Optional[str] = Field(default=None)
    priority: Optional[str] = Field(default=None)
    impact: Optional[str] = Field(default=None)
    urgency: Optional[str] = Field(default=None)
    assigned_to: Optional[str] = Field(default=None)
    assignment_group: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None, description="Update only")
    work_notes: Optional[str] = Field(default=None, description="Update only")
    close_notes: Optional[str] = Field(default=None, description="Update only")
    close_code: Optional[str] = Field(default=None, description="Update only")

    # Comment-specific
    comment: Optional[str] = Field(default=None, description="Body for comment action")
    is_work_note: bool = Field(
        default=False, description="True = internal work note, False = customer comment"
    )

    # Resolve-specific
    resolution_code: Optional[str] = Field(default=None, description="Required for resolve")
    resolution_notes: Optional[str] = Field(default=None, description="Required for resolve")

    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageIncidentParams":
        if self.action == "create":
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
        elif self.action == "update":
            if not self.incident_id:
                raise ValueError("incident_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _INCIDENT_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        elif self.action == "comment":
            if not self.incident_id:
                raise ValueError("incident_id is required for action='comment'")
            if not self.comment:
                raise ValueError("comment is required for action='comment'")
        elif self.action == "resolve":
            if not self.incident_id:
                raise ValueError("incident_id is required for action='resolve'")
            if not self.resolution_code or not self.resolution_notes:
                raise ValueError(
                    "resolution_code and resolution_notes are required for action='resolve'"
                )
        return self


def _project(params: ManageIncidentParams, fields: tuple[str, ...]) -> Dict[str, Any]:
    return {f: getattr(params, f) for f in fields if getattr(params, f) is not None}


@register_tool(
    "manage_incident",
    params=ManageIncidentParams,
    description="Create/update/comment/resolve an incident (table: incident). One call, no schema lookup needed.",
    serialization="str",
    return_type=str,
)
def manage_incident(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageIncidentParams,
) -> IncidentResponse:
    """Dispatch to the legacy create/update/add_comment/resolve_incident impls
    based on `action`. Reusing the existing wrappers keeps a single source of
    truth — bug fixes only need to land in one place."""
    if params.action == "create":
        return create_incident(
            config,
            auth_manager,
            CreateIncidentParams(**_project(params, _INCIDENT_CREATE_FIELDS)),
        )
    if params.action == "update":
        return update_incident(
            config,
            auth_manager,
            UpdateIncidentParams(
                incident_id=params.incident_id,
                dry_run=params.dry_run,
                **_project(params, _INCIDENT_UPDATE_FIELDS),
            ),
        )
    if params.action == "comment":
        return add_comment(
            config,
            auth_manager,
            AddCommentParams(
                incident_id=params.incident_id,
                comment=params.comment,
                is_work_note=params.is_work_note,
            ),
        )
    # resolve
    return resolve_incident(
        config,
        auth_manager,
        ResolveIncidentParams(
            incident_id=params.incident_id,
            resolution_code=params.resolution_code,
            resolution_notes=params.resolution_notes,
            dry_run=params.dry_run,
        ),
    )
