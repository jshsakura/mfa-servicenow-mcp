"""
Incident tools for the ServiceNow MCP server.

This module provides tools for managing incidents in ServiceNow.
"""

import logging
from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import incident as incident_service
from servicenow_mcp.services.choices import resolve_payload_choices
from servicenow_mcp.services.incident import IncidentResponse
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from ._preview import build_update_preview
from .problem_tools import _patch, _resolve_record
from .sn_api import invalidate_query_cache, sn_count, sn_query_page

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
# Link + hold fields. They are not in the service layer's signature, so a call
# that carries any of them takes the verified path in this module.
_LINK_FIELDS = {
    # field -> (table the value lives on, number prefix, human label)
    "parent_incident": ("incident", "INC", "parent incident"),
    "problem_id": ("problem", "PRB", "problem"),
    "rfc": ("change_request", "CHG", "fixing change"),
    "caused_by": ("change_request", "CHG", "causing change"),
}
_EXTRA_FIELDS = tuple(_LINK_FIELDS) + ("hold_reason",)
_JOURNAL_FIELDS = ("work_notes",)
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
) + _EXTRA_FIELDS


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

    parent_incident: Optional[str] = Field(default=None, description="INC number or sys_id")
    problem_id: Optional[str] = Field(default=None, description="PRB number or sys_id")
    rfc: Optional[str] = Field(default=None, description="CHG number or sys_id that fixes it")
    caused_by: Optional[str] = Field(
        default=None, description="CHG number or sys_id that caused it"
    )
    hold_reason: Optional[str] = Field(
        default=None, description="Required with state On Hold: value or label"
    )

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


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "message": message, **extra}


def _raw(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def _disp(value: Any) -> Any:
    return value.get("display_value") if isinstance(value, dict) else value


def _on_hold_without_reason(params: ManageIncidentParams) -> bool:
    """Cheap pre-check for the service path (no network): state On Hold, no hold_reason."""
    state = str(params.state or "").strip().lower().replace("_", " ")
    return state in ("3", "on hold") and not params.hold_reason


def _build_payload(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageIncidentParams,
    fields: tuple[str, ...],
) -> tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Resolve links and choices; a refusal means nothing is written."""
    data = _project(params, fields)
    for field, (table, prefix, label) in _LINK_FIELDS.items():
        if field not in data:
            continue
        ident = str(data[field]).strip()
        is_sys_id = len(ident) == 32 and all(c in "0123456789abcdef" for c in ident)
        if not is_sys_id and ident[:3].upper() != prefix:
            return data, _fail(
                f"{field} takes a {prefix} number or a sys_id of the {label}; "
                f"got {ident!r}. Nothing was written.",
                field=field,
            )
        try:
            sys_id, _, reason = _resolve_record(config, auth_manager, ident, table)
        except Exception as e:
            return data, _fail(f"Could not resolve {field} {ident}: {e}. Nothing was written.")
        if reason:
            return data, _fail(reason, field=field, determined=False)
        data[field] = sys_id
    refusal = resolve_payload_choices(
        config,
        auth_manager,
        table="incident",
        data=data,
        elements=incident_service.INCIDENT_CHOICE_FIELDS + ("hold_reason",),
    )
    if refusal is not None:
        return data, refusal
    if str(data.get("state", "")) == "3" and not data.get("hold_reason"):
        return data, _fail(
            "state On Hold needs hold_reason (the platform rejects it otherwise: "
            "Awaiting Caller / Change / Problem / Vendor). Nothing was written.",
            field="hold_reason",
        )
    return data, None


def _verify(
    config: ServerConfig, auth_manager: AuthManager, sys_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """Re-read the incident and report per-field `applied` (equal to what was sent)."""
    # written=True: the server accepted the write. A failed re-read is never a
    # success (unconfirmed) and never a reason to retry (it may duplicate).
    out: Dict[str, Any] = {"sys_id": sys_id, "incident_id": sys_id, "written": True}
    checked = {f: v for f, v in data.items() if f not in _JOURNAL_FIELDS}
    unverifiable = [f for f in data if f in _JOURNAL_FIELDS]
    if unverifiable:
        out["unverifiable"] = unverifiable  # journal fields read back empty
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="incident",
            query=f"sys_id={sys_id}",
            fields="number," + ",".join(checked),
            limit=1,
            offset=0,
            display_value="all",
            fail_silently=False,
        )
    except Exception as e:
        out.update(success=False, verified=False, applied=None)
        out["message"] = (
            f"Write sent but the re-read failed ({e}); the result is UNVERIFIED — do not retry blindly."
        )
        return out
    if not rows:
        out.update(success=False, verified=False, applied=None)
        out["message"] = (
            "Write sent but the record was not returned on re-read; UNVERIFIED — do not retry blindly."
        )
        return out
    row = rows[0]
    applied: Dict[str, bool] = {}
    not_applied: Dict[str, Any] = {}
    for field, wanted in checked.items():
        got = row.get(field)
        ok = str(wanted) in (str(_raw(got)), str(_disp(got)))
        applied[field] = ok
        if not ok:
            not_applied[field] = {"requested": wanted, "actual": _raw(got), "label": _disp(got)}
    number = _raw(row.get("number"))
    out.update(verified=True, number=number, incident_number=number, applied=applied)
    if not_applied:
        out["not_applied"] = not_applied
        out["message"] = "The write was accepted but these fields do not hold the requested value."
    else:
        out["message"] = "Incident written and confirmed by re-read."
    out["success"] = not not_applied
    return out


def _write(
    config: ServerConfig, auth_manager: AuthManager, params: ManageIncidentParams
) -> Dict[str, Any]:
    creating = params.action == "create"
    fields = _INCIDENT_CREATE_FIELDS + _EXTRA_FIELDS if creating else _INCIDENT_UPDATE_FIELDS
    sys_id: Optional[str] = None
    if not creating:
        assert params.incident_id
        try:
            sys_id, _, reason = _resolve_record(
                config, auth_manager, params.incident_id, "incident"
            )
        except Exception as e:
            return _fail(f"Could not resolve {params.incident_id}: {e}. Nothing was written.")
        if reason:
            return _fail(reason, determined=False)
    data, refusal = _build_payload(config, auth_manager, params, fields)
    if refusal is not None:
        return refusal
    if params.dry_run:
        if creating:
            return {"success": True, "dry_run": True, "operation": "create", "would_write": data}
        assert sys_id
        return build_update_preview(
            config,
            auth_manager,
            table="incident",
            sys_id=sys_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )
    try:
        if creating:
            resp = auth_manager.make_request(
                "POST",
                f"{config.api_url}/table/incident",
                json=data,
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            invalidate_query_cache(table="incident")
            sys_id = _raw(result.get("sys_id"))
            if not sys_id:
                return _fail("Incident created but no sys_id returned; UNVERIFIED.")
        else:
            assert sys_id
            _patch(config, auth_manager, "incident", sys_id, data)
    except Exception as e:
        logger.error(f"Failed to write incident: {e}")
        return _fail(f"Failed to {params.action} incident: {e}")
    return _verify(config, auth_manager, sys_id, data)


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
) -> Union[IncidentResponse, Dict[str, Any]]:
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
    if params.action == "update" and _on_hold_without_reason(params):
        return _fail(
            "state On Hold needs hold_reason (the platform rejects it otherwise). "
            "Nothing was written.",
            field="hold_reason",
        )
    # One write path for create and update: resolve links and choices, honour
    # dry_run (create included), write, then prove it by re-reading.
    if params.action in ("create", "update"):
        return _write(config, auth_manager, params)
    if params.action == "comment":
        assert params.incident_id is not None
        assert params.comment is not None
        return incident_service.add_comment(
            config,
            auth_manager,
            incident_id=params.incident_id,
            comment=params.comment,
            is_work_note=params.is_work_note,
        )
    # resolve
    assert params.incident_id is not None
    assert params.resolution_code is not None
    assert params.resolution_notes is not None
    return incident_service.resolve(
        config,
        auth_manager,
        incident_id=params.incident_id,
        resolution_code=params.resolution_code,
        resolution_notes=params.resolution_notes,
        dry_run=params.dry_run,
    )
