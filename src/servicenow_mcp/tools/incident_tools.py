"""
Incident tools for the ServiceNow MCP server.

This module provides tools for managing incidents in ServiceNow.
"""

import logging
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import incident as incident_service
from servicenow_mcp.services.incident import IncidentResponse
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .sn_api import sn_count, sn_query_page

logger = logging.getLogger(__name__)


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
      get:     incident_id (detail) or filters (list)
      create:  short_description
      update:  incident_id, at least one field to change
      comment: incident_id, comment
      resolve: incident_id, resolution_code, resolution_notes
    """

    action: Literal["get", "create", "update", "comment", "resolve"] = Field(
        ..., description="Operation to perform"
    )

    # Identifier (get/update/comment/resolve)
    incident_id: Optional[str] = Field(
        default=None, description="sys_id or INC number for get/update/comment/resolve"
    )

    # get (list mode) params
    limit: int = Field(default=10, description="Max records (get list mode)")
    offset: int = Field(default=0, description="Pagination offset (get list mode)")
    query: Optional[str] = Field(default=None, description="Search query (get list mode)")
    count_only: bool = Field(default=False, description="Return count only (get list mode)")

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
        if self.action == "get":
            pass  # incident_id optional (omit for list mode)
        elif self.action == "create":
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
    description="Get/create/update/comment/resolve an incident (table: incident). One call, no schema lookup needed.",
    serialization="str",
    return_type=str,
)
def manage_incident(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageIncidentParams,
) -> IncidentResponse:
    if params.action == "get":
        return incident_service.get(
            config,
            auth_manager,
            incident_id=params.incident_id,
            limit=params.limit,
            offset=params.offset,
            state=params.state,
            assigned_to=params.assigned_to,
            category=params.category,
            query=params.query,
            count_only=params.count_only,
        )
    if params.action == "create":
        return incident_service.create(
            config,
            auth_manager,
            **_project(params, _INCIDENT_CREATE_FIELDS),
        )
    if params.action == "update":
        return incident_service.update(
            config,
            auth_manager,
            incident_id=params.incident_id,
            dry_run=params.dry_run,
            **_project(params, _INCIDENT_UPDATE_FIELDS),
        )
    if params.action == "comment":
        return incident_service.add_comment(
            config,
            auth_manager,
            incident_id=params.incident_id,
            comment=params.comment,
            is_work_note=params.is_work_note,
        )
    # resolve
    return incident_service.resolve(
        config,
        auth_manager,
        incident_id=params.incident_id,
        resolution_code=params.resolution_code,
        resolution_notes=params.resolution_notes,
        dry_run=params.dry_run,
    )
