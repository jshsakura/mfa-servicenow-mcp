"""Change request (change_request) service layer.

Reusable API logic for create / update / add_task on the change_request
table. Both the public ``manage_change`` MCP tool and the legacy wrapper
functions in ``servicenow_mcp.tools.change_tools`` route through this module
so behaviour stays in one place.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services.choices import resolve_payload_choices
from servicenow_mcp.tools._preview import build_create_preview, build_update_preview
from servicenow_mcp.tools.sn_api import count_response, invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

# A change task is a full task row (~100 columns, ~2.3 KB like an incident), and
# a change can carry many. The listing reads these; sn_query reads one in full.
CHANGE_LISTING_FIELDS = (
    "sys_id,number,short_description,state,type,category,priority,risk,impact,approval,"
    "assignment_group,assigned_to,requested_by,start_date,end_date,sys_created_on,"
    "sys_updated_on"
)
TASK_LISTING_FIELDS = (
    "sys_id,number,short_description,state,change_task_type,assigned_to,"
    "assignment_group,order,on_hold,planned_start_date,planned_end_date,"
    "close_code,close_notes,sys_created_on,sys_updated_on"
)


# Integer choices on change_request (state -4 = Assess, risk 3 = Moderate, ...).
# A word is stored as-is, answered 200, and the change never moves. Resolved
# against the live choice list; `category` is left alone because instances
# commonly run it as free text.
CHANGE_CHOICE_FIELDS = ("type", "state", "risk", "impact")


# Journal fields are write-only through the Table API: they read back empty.
_JOURNAL_FIELDS = frozenset({"work_notes", "comments"})


def _cell_value(value: Any) -> str:
    return str(value.get("value") if isinstance(value, dict) else value or "")


def verify_written(
    config: ServerConfig, auth_manager: AuthManager, sys_id: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """Re-read the change and report, per field, whether it holds what was sent.

    The state model and business rules can accept a write (200) and leave the
    record elsewhere, so a 200 is not the answer — the re-read is. ``written``
    says the server accepted it; a failed re-read is unconfirmed, never success,
    and never a reason to retry blindly.
    """
    out: Dict[str, Any] = {"sys_id": sys_id, "written": True}
    if not sys_id:
        out.update(success=False, verified=False, applied=None)
        out["message"] = (
            "Write accepted but no sys_id came back; UNVERIFIED — do not retry blindly."
        )
        return out
    checked = {f: v for f, v in data.items() if f not in _JOURNAL_FIELDS}
    unverifiable = sorted(f for f in data if f in _JOURNAL_FIELDS)
    if unverifiable:
        out["unverifiable"] = unverifiable
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="change_request",
            query=f"sys_id={sys_id}",
            fields=",".join(["number", *checked]),
            limit=1,
            offset=0,
            display_value="all",
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        out.update(success=False, verified=False, applied=None)
        out["message"] = (
            f"Write sent but the re-read failed ({exc}); UNVERIFIED — do not retry blindly."
        )
        return out
    if not rows:
        out.update(success=False, verified=False, applied=None)
        out["message"] = "Write sent but the change was not returned on re-read; UNVERIFIED."
        return out
    row = rows[0]
    applied: Dict[str, bool] = {}
    not_applied: Dict[str, Any] = {}
    for field, wanted in checked.items():
        got = row.get(field)
        raw = _cell_value(got)
        label = str(got.get("display_value") or "") if isinstance(got, dict) else raw
        ok = str(wanted) in (raw, label)
        applied[field] = ok
        if not ok:
            not_applied[field] = {"requested": wanted, "actual": raw, "label": label}
    out.update(verified=True, number=_cell_value(row.get("number")), applied=applied)
    out["success"] = not not_applied
    if not_applied:
        out["not_applied"] = not_applied
        out["message"] = (
            "The write was accepted but these fields do not hold the requested value — "
            "a state model or business rule refused them; use the form's UI action, do not retry."
        )
    else:
        out["message"] = "Change request written and confirmed by re-read."
    return out


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    short_description: str,
    type: str,
    description: Optional[str] = None,
    risk: Optional[str] = None,
    impact: Optional[str] = None,
    category: Optional[str] = None,
    requested_by: Optional[str] = None,
    assignment_group: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    parent: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create a change request. ``parent`` is a resolved sys_id. Proven by re-read."""
    data: Dict[str, Any] = {
        "short_description": short_description,
        "type": type,
    }
    for field_name, value in (
        ("description", description),
        ("risk", risk),
        ("impact", impact),
        ("category", category),
        ("requested_by", requested_by),
        ("assignment_group", assignment_group),
        ("start_date", start_date),
        ("end_date", end_date),
        ("parent", parent),
    ):
        if value:
            data[field_name] = value

    refusal = resolve_payload_choices(
        config, auth_manager, table="change_request", data=data, elements=CHANGE_CHOICE_FIELDS
    )
    if refusal is not None:
        return refusal

    if dry_run:
        return build_create_preview(table="change_request", proposed=data)

    url = f"{config.api_url}/table/change_request"

    try:
        response = auth_manager.make_request(
            "POST",
            url,
            json=data,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="change_request")
        created = result.get("result") or {}
        return verify_written(config, auth_manager, _cell_value(created.get("sys_id")), data)
    except Exception as e:
        logger.error(f"Error creating change request: {e}")
        return {
            "success": False,
            "message": f"Error creating change request: {str(e)}",
        }


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    change_id: str,
    short_description: Optional[str] = None,
    description: Optional[str] = None,
    state: Optional[str] = None,
    risk: Optional[str] = None,
    impact: Optional[str] = None,
    category: Optional[str] = None,
    assignment_group: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    work_notes: Optional[str] = None,
    parent: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update a change request (dry-run preview supported). Proven by re-read."""
    data: Dict[str, Any] = {}
    for field_name, value in (
        ("short_description", short_description),
        ("description", description),
        ("state", state),
        ("risk", risk),
        ("impact", impact),
        ("category", category),
        ("assignment_group", assignment_group),
        ("start_date", start_date),
        ("end_date", end_date),
        ("work_notes", work_notes),
        ("parent", parent),
    ):
        if value:
            data[field_name] = value

    refusal = resolve_payload_choices(
        config, auth_manager, table="change_request", data=data, elements=CHANGE_CHOICE_FIELDS
    )
    if refusal is not None:
        return refusal

    url = f"{config.api_url}/table/change_request/{change_id}"

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="change_request",
            sys_id=change_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

    try:
        response = auth_manager.make_request(
            "PUT",
            url,
            json=data,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        invalidate_query_cache(table="change_request")
        return verify_written(config, auth_manager, change_id, data)
    except Exception as e:
        logger.error(f"Error updating change request: {e}")
        return {
            "success": False,
            "message": f"Error updating change request: {str(e)}",
        }


def add_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    change_id: str,
    short_description: str,
    description: Optional[str] = None,
    assigned_to: Optional[str] = None,
    planned_start_date: Optional[str] = None,
    planned_end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a change_task under a change request."""
    data: Dict[str, Any] = {
        "change_request": change_id,
        "short_description": short_description,
    }
    for field_name, value in (
        ("description", description),
        ("assigned_to", assigned_to),
        ("planned_start_date", planned_start_date),
        ("planned_end_date", planned_end_date),
    ):
        if value:
            data[field_name] = value

    url = f"{config.api_url}/table/change_task"

    try:
        response = auth_manager.make_request(
            "POST",
            url,
            json=data,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="change_task")

        return {
            "success": True,
            "message": "Change task added successfully",
            "change_task": result["result"],
        }
    except Exception as e:
        logger.error(f"Error adding change task: {e}")
        return {
            "success": False,
            "message": f"Error adding change task: {str(e)}",
        }


def get(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    change_id: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    state: Optional[str] = None,
    type: Optional[str] = None,
    category: Optional[str] = None,
    assignment_group: Optional[str] = None,
    timeframe: Optional[str] = None,
    query: Optional[str] = None,
    count_only: bool = False,
) -> Dict[str, Any]:
    """Fetch a single change request (detail) or list with filters."""
    if change_id:
        try:
            rows, _ = sn_query_page(
                config,
                auth_manager,
                table="change_request",
                query=f"sys_id={change_id}",
                fields="",
                limit=1,
                offset=0,
                display_value=True,
            )
            if not rows:
                return {"success": False, "message": f"Change request {change_id} not found"}
            # Loud on failure: a silenced read would come back as "no tasks".
            tasks, task_total = sn_query_page(
                config,
                auth_manager,
                table="change_task",
                query=f"change_request={change_id}",
                fields=TASK_LISTING_FIELDS,
                limit=100,
                offset=0,
                orderby="order",
                display_value=True,
                fail_silently=False,
            )
            result: Dict[str, Any] = {
                "success": True,
                "change_request": rows[0],
                "tasks": tasks,
                "full_task": (
                    "Tasks carry their listing columns. One task in full: "
                    "sn_query(table='change_task', query='sys_id=<task>')."
                ),
            }
            if task_total is None or task_total > len(tasks):
                result["tasks_complete"] = False
                result["task_total"] = task_total
            return result
        except Exception as e:
            logger.error(f"Error getting change request details: {e}")
            return {"success": False, "message": f"Error getting change request details: {str(e)}"}

    query_parts: List[str] = []
    if state:
        query_parts.append(f"state={state}")
    if type:
        query_parts.append(f"type={type}")
    if category:
        query_parts.append(f"category={category}")
    if assignment_group:
        query_parts.append(f"assignment_group={assignment_group}")
    if timeframe:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if timeframe == "upcoming":
            query_parts.append(f"start_date>{now}")
        elif timeframe == "in-progress":
            query_parts.append(f"start_date<{now}^end_date>{now}")
        elif timeframe == "completed":
            query_parts.append(f"end_date<{now}")
    if query:
        query_parts.append(query)
    query_str = "^".join(query_parts) if query_parts else ""

    if count_only:
        return count_response(
            config, auth_manager, "change_request", query_str, what="change requests"
        )

    try:
        rows, total = sn_query_page(
            config,
            auth_manager,
            table="change_request",
            query=query_str,
            fields=CHANGE_LISTING_FIELDS,
            limit=min(limit, 100),
            offset=offset,
            display_value=True,
            # Loud on failure: a silenced read would come back as "0 changes".
            fail_silently=False,
        )
        return {
            "success": True,
            "change_requests": rows,
            "count": len(rows),
            "total": total if total is not None else len(rows),
            "full_record": (
                "A listing carries its summary columns. One change in full, with its "
                "tasks: manage_change(action='get', change_id=<sys_id>)."
            ),
        }
    except Exception as e:
        logger.error(f"Error listing change requests: {e}")
        return {"success": False, "message": f"Error listing change requests: {str(e)}"}
