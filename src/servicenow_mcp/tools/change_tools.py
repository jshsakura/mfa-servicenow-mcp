"""
Change management tools for the ServiceNow MCP server.

This module provides tools for managing change requests in ServiceNow.
"""

import logging
import re
from typing import Any, ClassVar, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import change as change_service
from servicenow_mcp.services.choices import resolve_choice
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from ._preview import build_create_preview
from .approval_tools import decide_approval
from .sn_api import invalidate_query_cache, sn_query_page

logger = logging.getLogger(__name__)


def _change_state(
    config: ServerConfig, auth_manager: AuthManager, requested: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """change_request.state is an integer choice (-4 = Assess, -1 = Implement, 4 = Canceled).

    These tools wrote the words "assess", "implement" and "canceled" by default:
    stored as-is, answered 200, and the change request never moved. Resolved here,
    before the FIRST write, so a bad state cannot leave the approval record
    changed and the change request not.
    """
    return resolve_choice(
        config,
        auth_manager,
        table="change_request",
        element="state",
        requested=requested,
        unknown_error="UNKNOWN_CHANGE_STATE",
        unverified_error="CHANGE_STATE_UNVERIFIED",
    )


class SubmitChangeForApprovalParams(BaseModel):
    """Parameters for submitting a change request for approval."""

    change_id: str = Field(..., description="Change request ID or sys_id")
    approval_comments: Optional[str] = Field(
        default=None, description="Comments for the approval request"
    )
    change_state: Optional[str] = Field(
        default=None, description="change_request target state (default: assess)"
    )


class ApproveChangeParams(BaseModel):
    """Parameters for approving a change request."""

    change_id: str = Field(..., description="Change request ID or sys_id")
    approver_id: Optional[str] = Field(
        default=None,
        description="Target this approver's record (sys_id or name); else first pending",
    )
    approval_comments: Optional[str] = Field(default=None, description="Comments for the approval")
    change_state: Optional[str] = Field(
        default=None,
        description="change_request target state per your change model (default: implement)",
    )
    confirm_on_behalf: Optional[str] = Field(
        default=None,
        description="Required to decide for another user: that approver's user_name.",
    )
    dry_run: bool = Field(
        default=False,
        description="Preview approval-record and change-request transitions without executing.",
    )


class RejectChangeParams(BaseModel):
    """Parameters for rejecting a change request."""

    change_id: str = Field(..., description="Change request ID or sys_id")
    approver_id: Optional[str] = Field(
        default=None,
        description="Target this approver's record (sys_id or name); else first pending",
    )
    rejection_reason: str = Field(..., description="Reason for rejection")
    change_state: Optional[str] = Field(
        default=None, description="change_request target state (default: canceled)"
    )
    confirm_on_behalf: Optional[str] = Field(
        default=None,
        description="Required to decide for another user: that approver's user_name.",
    )
    dry_run: bool = Field(
        default=False,
        description="Preview rejection transitions without executing.",
    )


def submit_change_for_approval(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: SubmitChangeForApprovalParams,
) -> Dict[str, Any]:
    """Submit a change request for approval in ServiceNow."""
    state, refusal = _change_state(config, auth_manager, params.change_state or "assess")
    if refusal is not None:
        return refusal
    data: Dict[str, Any] = {"state": state}

    if params.approval_comments:
        data["work_notes"] = params.approval_comments

    headers = {"Content-Type": "application/json"}

    try:
        # Step 1: PATCH change_request state to "assess"
        change_url = f"{config.api_url}/table/change_request/{params.change_id}"
        response = auth_manager.make_request("PATCH", change_url, json=data, headers=headers)
        response.raise_for_status()

        # Step 2: POST approval record
        approval_url = f"{config.api_url}/table/sysapproval_approver"
        approval_data = {
            "document_id": params.change_id,
            "source_table": "change_request",
            "state": "requested",
        }
        approval_response = auth_manager.make_request(
            "POST",
            approval_url,
            json=approval_data,
            headers=headers,
        )
        approval_response.raise_for_status()

        approval_result = approval_response.json()

        # Invalidate both tables
        invalidate_query_cache(table="change_request")
        invalidate_query_cache(table="sysapproval_approver")

        return {
            "success": True,
            "message": "Change request submitted for approval successfully",
            "approval": approval_result["result"],
        }
    except Exception as e:
        logger.error(f"Error submitting change for approval: {e}")
        return {
            "success": False,
            "message": f"Error submitting change for approval: {str(e)}",
        }


# ---------------------------------------------------------------------------
# Shared approval-record helpers (approve_change / reject_change)
# ---------------------------------------------------------------------------

# An approval decision is final at these states — used to prefer a still-pending
# approver record over one that was already decided.
_DECIDED_APPROVAL_STATES = {"approved", "rejected"}


def _unwrap(value: Any) -> str:
    """Flatten a Table-API field that may be a {value, display_value} dict."""
    if isinstance(value, dict):
        return str(value.get("value") or value.get("display_value") or "")
    return str(value or "")


def _ref_matches(field: Any, wanted: str) -> bool:
    """True when *field* (raw sys_id or {value, display_value}) matches *wanted*
    by either sys_id or display name."""
    if isinstance(field, dict):
        return wanted in (
            str(field.get("value") or ""),
            str(field.get("display_value") or ""),
        )
    return str(field or "") == wanted


def _find_change_approval(
    config: ServerConfig,
    auth_manager: AuthManager,
    change_id: str,
    approver_id: Optional[str],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Locate the approval record to act on.

    Broadened match (``document_id`` OR ``sysapproval``) so it works regardless
    of which reference the instance populates. When ``approver_id`` is given,
    targets THAT approver's record (by sys_id or name) — not just the first one.
    Prefers a still-pending record over one already approved/rejected.
    Returns ``(row, None)`` or ``(None, error_message)``.
    """
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sysapproval_approver",
        query=f"document_id={change_id}^ORsysapproval={change_id}",
        fields="sys_id,approver,state",
        limit=50,
        offset=0,
        display_value="all",
    )
    if not rows:
        return None, "No approval record found for this change request"
    if approver_id:
        rows = [r for r in rows if _ref_matches(r.get("approver"), approver_id)]
        if not rows:
            return None, (f"No approval record for approver '{approver_id}' on this change request")
    pending = [r for r in rows if _unwrap(r.get("state")).lower() not in _DECIDED_APPROVAL_STATES]
    return (pending[0] if pending else rows[0]), None


def approve_change(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ApproveChangeParams,
) -> Dict[str, Any]:
    """Approve a change request in ServiceNow."""
    try:
        # Step 1: Find the approval record to act on (approver-targeted).
        approval, err = _find_change_approval(
            config, auth_manager, params.change_id, params.approver_id
        )
        if err:
            return {"success": False, "message": err}
        assert approval is not None
        approval_id = _unwrap(approval.get("sys_id"))
        target_state, refusal = _change_state(
            config, auth_manager, params.change_state or "implement"
        )
        if refusal is not None:
            return refusal

        decision = decide_approval(
            config,
            auth_manager,
            approval_id=approval_id,
            decision="approved",
            comments=params.approval_comments,
            confirm_on_behalf=params.confirm_on_behalf,
            dry_run=params.dry_run,
        )
        if not decision.get("success"):
            return decision

        if params.dry_run:
            change_rows, _ = sn_query_page(
                config,
                auth_manager,
                table="change_request",
                query=f"sys_id={params.change_id}",
                fields="sys_id,number,state,short_description",
                limit=1,
                offset=0,
            )
            current_change = change_rows[0] if change_rows else {}
            return {
                "dry_run": True,
                "operation": "approve_change",
                "target": {"table": "change_request", "sys_id": params.change_id},
                "approval_record": {
                    "sys_id": approval_id,
                    "new_state": "approved",
                    "approver": _unwrap(approval.get("approver")),
                    "caller": decision.get("caller"),
                    "basis": decision.get("basis"),
                },
                "change_record": {
                    "current": current_change,
                    "proposed_state": target_state,
                },
                "warnings": (
                    [] if change_rows else [f"change_request {params.change_id} not found"]
                ),
                "precision_notes": {
                    "count_source": "table_api",
                    "dependency_check": False,
                    "acl_checked": False,
                },
            }

        headers = {"Content-Type": "application/json"}

        # Step 3: advance the change_request (override via change_state).
        change_response = auth_manager.make_request(
            "PATCH",
            f"{config.api_url}/table/change_request/{params.change_id}",
            json={"state": target_state},
            headers=headers,
        )
        change_response.raise_for_status()

        invalidate_query_cache(table="sysapproval_approver")
        invalidate_query_cache(table="change_request")

        return {
            "success": True,
            "message": f"Change request approved (change_request → {target_state}).",
            "basis": decision.get("basis"),
            "approval_state": decision.get("state_after"),
            "parent_approval": decision.get("parent_approval"),
        }
    except Exception as e:
        logger.error(f"Error approving change: {e}")
        return {
            "success": False,
            "message": f"Error approving change: {str(e)}",
        }


def reject_change(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: RejectChangeParams,
) -> Dict[str, Any]:
    """Reject a change request in ServiceNow."""
    try:
        # Step 1: Find the approval record to act on (approver-targeted).
        approval, err = _find_change_approval(
            config, auth_manager, params.change_id, params.approver_id
        )
        if err:
            return {"success": False, "message": err}
        assert approval is not None
        approval_id = _unwrap(approval.get("sys_id"))
        target_state, refusal = _change_state(
            config, auth_manager, params.change_state or "canceled"
        )
        if refusal is not None:
            return refusal

        decision = decide_approval(
            config,
            auth_manager,
            approval_id=approval_id,
            decision="rejected",
            comments=params.rejection_reason,
            confirm_on_behalf=params.confirm_on_behalf,
            dry_run=params.dry_run,
        )
        if not decision.get("success"):
            return decision

        if params.dry_run:
            change_rows, _ = sn_query_page(
                config,
                auth_manager,
                table="change_request",
                query=f"sys_id={params.change_id}",
                fields="sys_id,number,state,short_description",
                limit=1,
                offset=0,
            )
            current_change = change_rows[0] if change_rows else {}
            return {
                "dry_run": True,
                "operation": "reject_change",
                "target": {"table": "change_request", "sys_id": params.change_id},
                "approval_record": {
                    "sys_id": approval_id,
                    "new_state": "rejected",
                    "approver": _unwrap(approval.get("approver")),
                    "caller": decision.get("caller"),
                    "basis": decision.get("basis"),
                    "rejection_reason": params.rejection_reason,
                },
                "change_record": {
                    "current": current_change,
                    "proposed_state": target_state,
                },
                "warnings": (
                    [] if change_rows else [f"change_request {params.change_id} not found"]
                ),
                "precision_notes": {
                    "count_source": "table_api",
                    "dependency_check": False,
                    "acl_checked": False,
                },
            }

        headers = {"Content-Type": "application/json"}

        # Step 3: advance the change_request (override via change_state).
        change_response = auth_manager.make_request(
            "PATCH",
            f"{config.api_url}/table/change_request/{params.change_id}",
            json={
                "state": target_state,
                "work_notes": f"Change request rejected: {params.rejection_reason}",
            },
            headers=headers,
        )
        change_response.raise_for_status()

        invalidate_query_cache(table="sysapproval_approver")
        invalidate_query_cache(table="change_request")

        return {
            "success": True,
            "message": f"Change request rejected (change_request → {target_state}).",
            "basis": decision.get("basis"),
            "approval_state": decision.get("state_after"),
            "parent_approval": decision.get("parent_approval"),
        }
    except Exception as e:
        logger.error(f"Error rejecting change: {e}")
        return {
            "success": False,
            "message": f"Error rejecting change: {str(e)}",
        }


# ---------------------------------------------------------------------------
# manage_change — change_request CRUD plus the approval transitions.
#
# submit/approve/reject were three tools of their own; folded in as actions they
# reuse state (target state) and work_notes (comment / reject reason) and cost
# one field, approver_id.
# ---------------------------------------------------------------------------

_CHANGE_CREATE_FIELDS = (
    "short_description",
    "description",
    "risk",
    "impact",
    "category",
    "requested_by",
    "assignment_group",
    "start_date",
    "end_date",
)
# `parent` is resolved to a sys_id by this tool, not passed through as written.
_CHANGE_CREATE_FIELDS_WITH_PARENT = _CHANGE_CREATE_FIELDS + ("parent",)
_STANDARD_FIELDS = ("short_description", "assignment_group", "start_date", "end_date", "parent")
_CHANGE_UPDATE_FIELDS = (
    "short_description",
    "description",
    "state",
    "risk",
    "impact",
    "category",
    "assignment_group",
    "start_date",
    "end_date",
    "work_notes",
)
_CHANGE_UPDATE_FIELDS_WITH_PARENT = _CHANGE_UPDATE_FIELDS + ("parent",)


_APPROVAL_FIELDS = frozenset({"change_id", "state", "work_notes", "dry_run"})
_DECIDE_FIELDS = _APPROVAL_FIELDS | {"approver_id", "confirm_on_behalf"}


class ManageChangeParams(BaseModel):
    """Manage change requests — table: change_request.

    Required per action:
      get:      change_id (detail) or filters (list)
      create:   short_description, type ('normal' | 'standard' | 'emergency')
      list_templates: (none) active standard change templates
      create_standard: template_id (sys_id or exact name)
      update:   change_id, at least one field
      add_task: change_id, task_short_description
      submit/approve: change_id
      reject:   change_id, work_notes (the reason)
    """

    action: Literal[
        "get",
        "create",
        "update",
        "add_task",
        "submit",
        "approve",
        "reject",
        "list_templates",
        "create_standard",
    ] = Field(...)
    change_id: Optional[str] = Field(default=None, description="sys_id or CHG number")

    # get (list mode) params
    limit: int = Field(default=10, description="Max records (get list mode)")
    offset: int = Field(default=0, description="Pagination offset (get list mode)")
    timeframe: Optional[str] = Field(
        default=None, description="upcoming/in-progress/completed (get list mode)"
    )
    query: Optional[str] = Field(
        default=None, description="Additional query string (get list mode)"
    )
    count_only: bool = Field(default=False, description="Return count only (get list mode)")

    # Create-only required
    type: Optional[Literal["normal", "standard", "emergency"]] = Field(
        default=None, description="Required for create"
    )

    # Common create + update
    short_description: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    risk: Optional[str] = Field(default=None)
    impact: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    assignment_group: Optional[str] = Field(default=None)
    start_date: Optional[str] = Field(default=None)
    end_date: Optional[str] = Field(default=None)
    requested_by: Optional[str] = Field(default=None, description="Create only")
    template_id: Optional[str] = Field(
        default=None, description="create_standard: template sys_id or exact name (list_templates)"
    )
    parent: Optional[str] = Field(
        default=None, description="RITM/SCTASK number or sys_id this change is raised from"
    )
    state: Optional[str] = Field(
        default=None,
        description="Code or label. submit/approve/reject: target (assess/implement/canceled)",
    )
    work_notes: Optional[str] = Field(
        default=None, description="Update note; approval comment; reject reason (required)"
    )
    approver_id: Optional[str] = Field(
        default=None, description="Approver sys_id or name; else first pending (approve/reject)"
    )

    confirm_on_behalf: Optional[str] = Field(
        default=None,
        description="approve/reject for another user: that approver's user_name (else refused)",
    )

    # add_task-specific
    task_short_description: Optional[str] = Field(default=None, description="Required for add_task")
    task_description: Optional[str] = Field(default=None)
    task_assigned_to: Optional[str] = Field(default=None)
    task_planned_start_date: Optional[str] = Field(default=None)
    task_planned_end_date: Optional[str] = Field(default=None)

    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "get": frozenset(
            {"change_id", "limit", "offset", "timeframe", "query", "count_only", "state", "type"}
            | {"category", "assignment_group"}
        ),
        "create": frozenset({"type", "dry_run", *_CHANGE_CREATE_FIELDS_WITH_PARENT}),
        "update": frozenset({"change_id", "dry_run", *_CHANGE_UPDATE_FIELDS_WITH_PARENT}),
        "list_templates": frozenset({"limit", "query"}),
        "create_standard": frozenset({"template_id", "dry_run", *_STANDARD_FIELDS}),
        "add_task": frozenset(
            {"change_id", "dry_run", "task_short_description", "task_description"}
            | {"task_assigned_to", "task_planned_start_date", "task_planned_end_date"}
        ),
        "submit": _APPROVAL_FIELDS,
        "approve": _DECIDE_FIELDS,
        "reject": _DECIDE_FIELDS,
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageChangeParams":
        if self.action == "create":
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
            if not self.type:
                raise ValueError("type is required for action='create' (normal/standard/emergency)")
        elif self.action == "create_standard":
            if not self.template_id:
                raise ValueError("template_id is required for action='create_standard'")
        elif self.action not in ("get", "list_templates") and not self.change_id:
            raise ValueError(f"change_id is required for action='{self.action}'")
        if self.action == "update":
            if not any(getattr(self, f) is not None for f in _CHANGE_UPDATE_FIELDS_WITH_PARENT):
                raise ValueError("at least one field must be provided for action='update'")
        elif self.action == "add_task":
            if not self.task_short_description:
                raise ValueError("task_short_description is required for action='add_task'")
        elif self.action == "reject" and not self.work_notes:
            raise ValueError("work_notes (the rejection reason) is required for action='reject'")
        return self


# ---------------------------------------------------------------------------
# parent (RITM / SCTASK), standard change templates
# ---------------------------------------------------------------------------

_SYS_ID = re.compile(r"^[0-9a-f]{32}$", re.I)
_PARENT_CLASSES = {"sc_req_item", "sc_task"}
_PARENT_PREFIXES = ("RITM", "SCTASK")
_TEMPLATE_TABLE = "std_change_record_producer"
_TEMPLATE_FIELDS = "sys_id,name,category,current_version,version,short_description"


def _cell(row: Dict[str, Any], field: str) -> str:
    v = row.get(field)
    if isinstance(v, dict):
        v = v.get("value")
    return "" if v is None else str(v)


def _shown(row: Dict[str, Any], field: str) -> str:
    v = row.get(field)
    if isinstance(v, dict):
        v = v.get("display_value") or v.get("value")
    return "" if v is None else str(v)


def _resolve_parent(
    config: ServerConfig, auth_manager: AuthManager, parent: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """``(sys_id, refusal)``. Never a sys_id that was not read back from the instance."""
    wanted = parent.strip()
    if _SYS_ID.match(wanted):
        query = f"sys_id={wanted.lower()}"
    elif wanted.upper().startswith(_PARENT_PREFIXES):
        query = f"number={wanted.upper()}"
    else:
        return None, {
            "success": False,
            "error": "BAD_PARENT",
            "message": f"parent '{wanted}' is not a RITM/SCTASK number or a sys_id.",
        }
    try:
        rows, _t = sn_query_page(
            config,
            auth_manager,
            table="task",
            query=query,
            fields="sys_id,number,sys_class_name",
            limit=2,
            offset=0,
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - an unread parent is not an absent one
        return None, {
            "success": False,
            "error": "PARENT_UNDETERMINED",
            "message": f"Could not read parent '{wanted}': {str(exc)[:160]}. Nothing was written.",
        }
    if not rows:
        return None, {
            "success": False,
            "error": "PARENT_NOT_FOUND",
            "message": f"parent '{wanted}' is absent or hidden by ACL. Nothing was written.",
        }
    if len(rows) > 1:
        return None, {
            "success": False,
            "error": "PARENT_AMBIGUOUS",
            "message": f"parent '{wanted}' matched more than one task.",
        }
    cls = _cell(rows[0], "sys_class_name")
    if cls not in _PARENT_CLASSES:
        return None, {
            "success": False,
            "error": "BAD_PARENT",
            "message": f"parent '{wanted}' is a {cls or 'task'}, not a request item or catalog task.",
        }
    return _cell(rows[0], "sys_id"), None


def _template_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "sys_id": _cell(row, "sys_id"),
        "name": _cell(row, "name"),
        "category": _shown(row, "category"),
        "current_version": _shown(row, "current_version"),
    }
    if _cell(row, "version"):
        out["version"] = _cell(row, "version")
    return out


def _list_templates(
    config: ServerConfig, auth_manager: AuthManager, params: "ManageChangeParams"
) -> Dict[str, Any]:
    parts = ["active=true", "retired=false"]
    if params.query:
        parts.append(params.query)
    limit = min(params.limit, 100)
    try:
        rows, total = sn_query_page(
            config,
            auth_manager,
            table=_TEMPLATE_TABLE,
            query="^".join(parts),
            fields=_TEMPLATE_FIELDS,
            limit=limit,
            offset=params.offset,
            display_value="all",
            orderby="name",
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - never "no templates" for an unread table
        return {
            "success": False,
            "error": "TEMPLATES_UNREADABLE",
            "message": f"Could not read {_TEMPLATE_TABLE} (Standard Change Catalog not "
            f"installed, or no access): {str(exc)[:160]}",
        }
    return {
        "success": True,
        "templates": [_template_row(r) for r in rows],
        "count": len(rows),
        "total": total if total is not None else len(rows),
        "complete": (len(rows) + params.offset >= total) if total is not None else None,
        "next": "manage_change(action='create_standard', template_id=<sys_id>)",
    }


def _resolve_template(
    config: ServerConfig, auth_manager: AuthManager, template: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    wanted = template.strip()
    query = f"sys_id={wanted.lower()}" if _SYS_ID.match(wanted) else f"name={wanted}"
    try:
        rows, _t = sn_query_page(
            config,
            auth_manager,
            table=_TEMPLATE_TABLE,
            query=f"{query}^active=true^retired=false",
            fields=_TEMPLATE_FIELDS,
            limit=6,
            offset=0,
            display_value="all",
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        return None, {
            "success": False,
            "error": "TEMPLATE_UNDETERMINED",
            "message": f"Could not read standard change templates: {str(exc)[:160]}. "
            "Nothing was created.",
        }
    if len(rows) == 1:
        return rows[0], None
    if not rows:
        return None, {
            "success": False,
            "error": "TEMPLATE_NOT_FOUND",
            "message": f"No active standard change template '{wanted}' (absent, retired, or "
            "hidden by ACL). manage_change(action='list_templates') shows the available ones.",
        }
    return None, {
        "success": False,
        "error": "TEMPLATE_AMBIGUOUS",
        "message": f"{len(rows)} templates match '{wanted}'; pass the sys_id of one.",
        "candidates": [_template_row(r) for r in rows],
    }


def _extract_sys_id(result: Any) -> str:
    if isinstance(result, list) and result:
        result = result[0]
    if not isinstance(result, dict):
        return ""
    sid = result.get("sys_id")
    if isinstance(sid, dict):
        sid = sid.get("value")
    return str(sid or "")


def _create_standard(
    config: ServerConfig, auth_manager: AuthManager, params: "ManageChangeParams"
) -> Dict[str, Any]:
    assert params.template_id is not None
    template, refusal = _resolve_template(config, auth_manager, params.template_id)
    if refusal:
        return refusal
    assert template is not None
    overrides: Dict[str, Any] = {
        f: getattr(params, f) for f in _STANDARD_FIELDS if getattr(params, f)
    }
    if "parent" in overrides:
        parent_id, refusal = _resolve_parent(config, auth_manager, overrides["parent"])
        if refusal:
            return refusal
        overrides["parent"] = parent_id
    tpl = _template_row(template)
    if params.dry_run:
        preview = build_create_preview(table="change_request", proposed=overrides)
        preview["template"] = tpl
        preview["endpoint"] = "POST /api/sn_chg_rest/change/standard/<template sys_id>"
        return preview

    url = f"{config.instance_url.rstrip('/')}/api/sn_chg_rest/change/standard/{tpl['sys_id']}"
    try:
        resp = auth_manager.make_request(
            "POST", url, json=overrides, headers={"Content-Type": "application/json"}
        )
        resp.raise_for_status()
        created = resp.json().get("result")
    except Exception as exc:  # noqa: BLE001
        logger.error("Error creating standard change: %s", exc)
        return {"success": False, "message": f"Error creating standard change: {str(exc)}"}
    invalidate_query_cache(table="change_request")
    sys_id = _extract_sys_id(created)
    if not sys_id:
        return {
            "success": True,
            "created": True,
            "template": tpl,
            "verified": False,
            "message": "The API answered but returned no sys_id; the change was NOT re-read. "
            "Find it with manage_change(action='get', query=...).",
        }
    try:
        rows, _t = sn_query_page(
            config,
            auth_manager,
            table="change_request",
            query=f"sys_id={sys_id}",
            fields="sys_id,number,type,state," + ",".join(overrides),
            limit=1,
            offset=0,
            display_value="all",
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001
        rows = []
        reread_error = str(exc)[:160]
    else:
        reread_error = "no row returned (hidden by ACL?)"
    if not rows:
        return {
            "success": True,
            "created": True,
            "sys_id": sys_id,
            "template": tpl,
            "verified": False,
            "message": f"Created, but the re-read failed: {reread_error}. "
            "Overrides are unconfirmed.",
        }
    rec = rows[0]
    applied = {}
    for field, wanted in overrides.items():
        applied[field] = wanted in (_cell(rec, field), _shown(rec, field))
    out: Dict[str, Any] = {
        "success": True,
        "created": True,
        "verified": True,
        "sys_id": sys_id,
        "number": _cell(rec, "number"),
        "type": _shown(rec, "type"),
        "state": _shown(rec, "state"),
        "template": tpl,
        "applied": applied,
    }
    missed = [f for f, ok in applied.items() if not ok]
    if missed:
        out["overrides_not_applied"] = missed
    return out


def _project_change(params: ManageChangeParams, fields: tuple[str, ...]) -> Dict[str, Any]:
    return {f: getattr(params, f) for f in fields if getattr(params, f) is not None}


@register_tool(
    name="manage_change",
    params=ManageChangeParams,
    description="Change requests: get/create/update, standard templates, tasks, approval.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_change(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageChangeParams,
) -> Dict[str, Any]:
    if params.action == "get":
        return change_service.get(
            config,
            auth_manager,
            change_id=params.change_id,
            limit=params.limit,
            offset=params.offset,
            state=params.state,
            type=params.type,
            category=params.category,
            assignment_group=params.assignment_group,
            timeframe=params.timeframe,
            query=params.query,
            count_only=params.count_only,
        )
    if params.action == "list_templates":
        return _list_templates(config, auth_manager, params)
    if params.action == "create_standard":
        return _create_standard(config, auth_manager, params)
    if params.action in ("create", "update"):
        # One write path: resolve parent, resolve choices, honour dry_run (create
        # included), write, prove it by re-reading (services/change.verify_written).
        parent_id: Optional[str] = None
        if params.parent:
            parent_id, refusal = _resolve_parent(config, auth_manager, params.parent)
            if refusal:
                return refusal
        if params.action == "create":
            # ManageChangeParams validator guarantees these are present per action.
            assert params.short_description is not None
            assert params.type is not None
            return change_service.create(
                config,
                auth_manager,
                short_description=params.short_description,
                type=params.type,
                parent=parent_id,
                dry_run=params.dry_run,
                **_project_change(params, _CHANGE_CREATE_FIELDS[1:]),
            )
        assert params.change_id is not None
        return change_service.update(
            config,
            auth_manager,
            change_id=params.change_id,
            parent=parent_id,
            dry_run=params.dry_run,
            **_project_change(params, _CHANGE_UPDATE_FIELDS),
        )
    if params.action == "submit":
        assert params.change_id is not None
        return submit_change_for_approval(
            config,
            auth_manager,
            SubmitChangeForApprovalParams(
                change_id=params.change_id,
                approval_comments=params.work_notes,
                change_state=params.state,
            ),
        )
    if params.action == "approve":
        assert params.change_id is not None
        return approve_change(
            config,
            auth_manager,
            ApproveChangeParams(
                change_id=params.change_id,
                approver_id=params.approver_id,
                confirm_on_behalf=params.confirm_on_behalf,
                approval_comments=params.work_notes,
                change_state=params.state,
                dry_run=params.dry_run,
            ),
        )
    if params.action == "reject":
        assert params.change_id is not None and params.work_notes is not None
        return reject_change(
            config,
            auth_manager,
            RejectChangeParams(
                change_id=params.change_id,
                approver_id=params.approver_id,
                confirm_on_behalf=params.confirm_on_behalf,
                rejection_reason=params.work_notes,
                change_state=params.state,
                dry_run=params.dry_run,
            ),
        )
    # add_task
    assert params.change_id is not None
    assert params.task_short_description is not None
    return change_service.add_task(
        config,
        auth_manager,
        change_id=params.change_id,
        short_description=params.task_short_description,
        description=params.task_description,
        assigned_to=params.task_assigned_to,
        planned_start_date=params.task_planned_start_date,
        planned_end_date=params.task_planned_end_date,
    )
