"""Incident (incident table) service layer.

Reusable API logic for create / update / comment / resolve operations on the
ServiceNow ``incident`` table. Both the public ``manage_incident`` MCP tool
and the legacy wrapper functions in ``servicenow_mcp.tools.incident_tools``
route through this module.

The ``IncidentResponse`` model and the ``resolve_incident_sys_id`` helper
live here (rather than in the tools module) so anything that depends on them
can import without creating an import cycle when wrappers route through
services.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)


class IncidentResponse(BaseModel):
    """Response from incident operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    incident_id: Optional[str] = Field(default=None, description="ID of the affected incident")
    incident_number: Optional[str] = Field(
        default=None, description="Number of the affected incident"
    )


def resolve_incident_sys_id(
    config: ServerConfig,
    auth_manager: AuthManager,
    incident_id: str,
) -> tuple[str | None, IncidentResponse | None]:
    """Resolve an incident identifier (sys_id or INC number) to a sys_id.

    Returns ``(sys_id, None)`` on success, or ``(None, error_response)`` on
    failure — callers return the error_response directly to preserve the
    legacy wrapper response shape.
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


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    short_description: str,
    description: Optional[str] = None,
    caller_id: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    priority: Optional[str] = None,
    impact: Optional[str] = None,
    urgency: Optional[str] = None,
    assigned_to: Optional[str] = None,
    assignment_group: Optional[str] = None,
) -> IncidentResponse:
    """Create a new incident."""
    api_url = f"{config.api_url}/table/incident"

    data = {
        "short_description": short_description,
    }
    for field_name, value in (
        ("description", description),
        ("caller_id", caller_id),
        ("category", category),
        ("subcategory", subcategory),
        ("priority", priority),
        ("impact", impact),
        ("urgency", urgency),
        ("assigned_to", assigned_to),
        ("assignment_group", assignment_group),
    ):
        if value is not None:
            data[field_name] = value

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


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    incident_id: str,
    short_description: Optional[str] = None,
    description: Optional[str] = None,
    state: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    priority: Optional[str] = None,
    impact: Optional[str] = None,
    urgency: Optional[str] = None,
    assigned_to: Optional[str] = None,
    assignment_group: Optional[str] = None,
    work_notes: Optional[str] = None,
    close_notes: Optional[str] = None,
    close_code: Optional[str] = None,
    dry_run: bool = False,
) -> Union[IncidentResponse, Dict[str, Any]]:
    """Update an existing incident. Supports a dry-run preview."""
    sys_id, err = resolve_incident_sys_id(config, auth_manager, incident_id)
    if err:
        return err
    assert sys_id is not None
    api_url = f"{config.api_url}/table/incident/{sys_id}"

    data = {}
    for field_name, value in (
        ("short_description", short_description),
        ("description", description),
        ("state", state),
        ("category", category),
        ("subcategory", subcategory),
        ("priority", priority),
        ("impact", impact),
        ("urgency", urgency),
        ("assigned_to", assigned_to),
        ("assignment_group", assignment_group),
        ("work_notes", work_notes),
        ("close_notes", close_notes),
        ("close_code", close_code),
    ):
        if value is not None:
            data[field_name] = value

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="incident",
            sys_id=sys_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

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


def add_comment(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    incident_id: str,
    comment: str,
    is_work_note: bool = False,
) -> IncidentResponse:
    """Add a work note (internal) or customer-visible comment to an incident."""
    sys_id, err = resolve_incident_sys_id(config, auth_manager, incident_id)
    if err:
        return err
    api_url = f"{config.api_url}/table/incident/{sys_id}"

    data = {"work_notes" if is_work_note else "comments": comment}

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


def resolve(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    incident_id: str,
    resolution_code: str,
    resolution_notes: str,
    dry_run: bool = False,
) -> Union[IncidentResponse, Dict[str, Any]]:
    """Transition an incident to the Resolved state."""
    sys_id, err = resolve_incident_sys_id(config, auth_manager, incident_id)
    if err:
        return err
    assert sys_id is not None
    api_url = f"{config.api_url}/table/incident/{sys_id}"

    data = {
        "state": "6",  # Resolved
        "close_code": resolution_code,
        "close_notes": resolution_notes,
        "resolved_at": "now",
    }

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="incident",
            sys_id=sys_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

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


_INCIDENT_FIELDS = "sys_id,number,short_description,description,state,priority,assigned_to,category,subcategory,sys_created_on,sys_updated_on"


def get(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    incident_id: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    state: Optional[str] = None,
    assigned_to: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    count_only: bool = False,
) -> Dict[str, Any]:
    """Fetch a single incident by number/sys_id (detail) or list with filters."""
    if incident_id:
        try:
            records, _ = sn_query_page(
                config,
                auth_manager,
                table="incident",
                query=(
                    f"number={incident_id}"
                    if not (
                        len(incident_id) == 32 and all(c in "0123456789abcdef" for c in incident_id)
                    )
                    else f"sys_id={incident_id}"
                ),
                fields="",
                limit=1,
                offset=0,
                display_value=True,
                fail_silently=False,
            )
            if not records:
                return {"success": False, "message": f"Incident not found: {incident_id}"}
            d = records[0]
            assigned = d.get("assigned_to")
            if isinstance(assigned, dict):
                assigned = assigned.get("display_value")
            return {
                "success": True,
                "message": f"Incident {incident_id} found",
                "incident": {
                    "sys_id": d.get("sys_id"),
                    "number": d.get("number"),
                    "short_description": d.get("short_description"),
                    "description": d.get("description"),
                    "state": d.get("state"),
                    "priority": d.get("priority"),
                    "assigned_to": assigned,
                    "category": d.get("category"),
                    "subcategory": d.get("subcategory"),
                    "created_on": d.get("sys_created_on"),
                    "updated_on": d.get("sys_updated_on"),
                },
            }
        except Exception as e:
            logger.error(f"Failed to fetch incident: {e}")
            return {"success": False, "message": f"Failed to fetch incident: {str(e)}"}

    filters = []
    if state:
        filters.append(f"state={state}")
    if assigned_to:
        filters.append(f"assigned_to={assigned_to}")
    if category:
        filters.append(f"category={category}")
    if query:
        filters.append(f"short_descriptionLIKE{query}^ORdescriptionLIKE{query}")
    query_string = "^".join(filters) if filters else ""

    if count_only:
        count = sn_count(config, auth_manager, "incident", query_string)
        return {"success": True, "count": count}

    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="incident",
            query=query_string,
            fields=_INCIDENT_FIELDS,
            limit=limit,
            offset=offset,
            display_value=True,
            fail_silently=False,
        )
        incidents = []
        for d in records:
            assigned = d.get("assigned_to")
            if isinstance(assigned, dict):
                assigned = assigned.get("display_value")
            incidents.append(
                {
                    "sys_id": d.get("sys_id"),
                    "number": d.get("number"),
                    "short_description": d.get("short_description"),
                    "description": d.get("description"),
                    "state": d.get("state"),
                    "priority": d.get("priority"),
                    "assigned_to": assigned,
                    "category": d.get("category"),
                    "subcategory": d.get("subcategory"),
                    "created_on": d.get("sys_created_on"),
                    "updated_on": d.get("sys_updated_on"),
                }
            )
        return {
            "success": True,
            "message": f"Found {len(incidents)} incidents",
            "incidents": incidents,
        }
    except Exception as e:
        logger.error(f"Failed to list incidents: {e}")
        return {"success": False, "message": f"Failed to list incidents: {str(e)}", "incidents": []}
