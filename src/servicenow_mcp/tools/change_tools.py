"""
Change management tools for the ServiceNow MCP server.

This module provides tools for managing change requests in ServiceNow.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import change as change_service
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .sn_api import invalidate_query_cache, sn_count, sn_query_page

logger = logging.getLogger(__name__)


class GetChangeRequestDetailsParams(BaseModel):
    """Parameters for getting change request details or listing change requests."""

    change_id: Optional[str] = Field(
        default=None,
        description="Change request ID or sys_id. If provided, returns full details for that single change request.",
    )
    limit: Optional[int] = Field(
        default=10, description="Maximum number of records to return (list mode)"
    )
    offset: Optional[int] = Field(default=0, description="Offset to start from (list mode)")
    state: Optional[str] = Field(default=None, description="Filter by state (list mode)")
    type: Optional[str] = Field(
        default=None, description="Filter by type (normal, standard, emergency) (list mode)"
    )
    category: Optional[str] = Field(default=None, description="Filter by category (list mode)")
    assignment_group: Optional[str] = Field(
        default=None, description="Filter by assignment group (list mode)"
    )
    timeframe: Optional[str] = Field(
        default=None,
        description="Filter by timeframe (upcoming, in-progress, completed) (list mode)",
    )
    query: Optional[str] = Field(default=None, description="Additional query string (list mode)")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records. Uses lightweight Aggregate API. (list mode)",
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
    dry_run: bool = Field(
        default=False,
        description="Preview rejection transitions without executing.",
    )


def get_change_request_details(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetChangeRequestDetailsParams,
) -> Dict[str, Any]:
    """Get details of a single change request or list change requests from ServiceNow."""
    if params.change_id:
        # Detail mode: fetch a single change request by sys_id/number
        try:
            rows, _ = sn_query_page(
                config,
                auth_manager,
                table="change_request",
                query=f"sys_id={params.change_id}",
                fields="",
                limit=1,
                offset=0,
                display_value=True,
            )

            if not rows:
                return {
                    "success": False,
                    "message": f"Change request {params.change_id} not found",
                }

            # Get tasks associated with this change request
            tasks, _ = sn_query_page(
                config,
                auth_manager,
                table="change_task",
                query=f"change_request={params.change_id}",
                fields="",
                limit=100,
                offset=0,
                display_value=True,
            )

            return {
                "success": True,
                "change_request": rows[0],
                "tasks": tasks,
            }
        except Exception as e:
            logger.error(f"Error getting change request details: {e}")
            return {
                "success": False,
                "message": f"Error getting change request details: {str(e)}",
            }
    else:
        # List mode: search change requests with filters
        query_parts: List[str] = []

        if params.state:
            query_parts.append(f"state={params.state}")
        if params.type:
            query_parts.append(f"type={params.type}")
        if params.category:
            query_parts.append(f"category={params.category}")
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

        query = "^".join(query_parts) if query_parts else ""

        if params.count_only:
            count = sn_count(config, auth_manager, "change_request", query)
            return {"success": True, "count": count}

        try:
            rows, total = sn_query_page(
                config,
                auth_manager,
                table="change_request",
                query=query,
                fields="",
                limit=min(params.limit or 10, 100),
                offset=params.offset or 0,
                display_value=True,
            )

            return {
                "success": True,
                "change_requests": rows,
                "count": len(rows),
                "total": total if total is not None else len(rows),
            }
        except Exception as e:
            logger.error(f"Error listing change requests: {e}")
            return {
                "success": False,
                "message": f"Error listing change requests: {str(e)}",
            }


@register_tool(
    name="submit_change_for_approval",
    params=SubmitChangeForApprovalParams,
    description="Transition a change request to assess state and create an approval record. Requires change_id.",
    serialization="str",
    return_type=str,
)
def submit_change_for_approval(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: SubmitChangeForApprovalParams,
) -> Dict[str, Any]:
    """Submit a change request for approval in ServiceNow."""
    data: Dict[str, Any] = {"state": params.change_state or "assess"}

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


@register_tool(
    name="approve_change",
    params=ApproveChangeParams,
    description="Approve a change's approval record (by approver_id); advance the change_request (default: implement).",
    serialization="str",
    return_type=str,
)
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
        target_state = params.change_state or "implement"

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

        # Step 2: PATCH the approval record to "approved".
        approval_data: Dict[str, Any] = {"state": "approved"}
        if params.approval_comments:
            approval_data["comments"] = params.approval_comments
        approval_update_response = auth_manager.make_request(
            "PATCH",
            f"{config.api_url}/table/sysapproval_approver/{approval_id}",
            json=approval_data,
            headers=headers,
        )
        approval_update_response.raise_for_status()

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
        }
    except Exception as e:
        logger.error(f"Error approving change: {e}")
        return {
            "success": False,
            "message": f"Error approving change: {str(e)}",
        }


@register_tool(
    name="reject_change",
    params=RejectChangeParams,
    description="Reject a change's approval record (by approver_id) with reason; advance the change_request (default: canceled).",
    serialization="str",
    return_type=str,
)
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
        target_state = params.change_state or "canceled"

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

        # Step 2: PATCH the approval record to "rejected".
        approval_update_response = auth_manager.make_request(
            "PATCH",
            f"{config.api_url}/table/sysapproval_approver/{approval_id}",
            json={"state": "rejected", "comments": params.rejection_reason},
            headers=headers,
        )
        approval_update_response.raise_for_status()

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
        }
    except Exception as e:
        logger.error(f"Error rejecting change: {e}")
        return {
            "success": False,
            "message": f"Error rejecting change: {str(e)}",
        }


# ---------------------------------------------------------------------------
# manage_change — bundled CRUD for change_request
#
# Note: approve_change, reject_change, submit_change_for_approval are kept as
# separate tools (state-machine orchestrators with 4+ API calls each), not
# folded into manage_change.
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


class ManageChangeParams(BaseModel):
    """Manage change requests — table: change_request.

    Required per action:
      get:      change_id (detail) or filters (list)
      create:   short_description, type ('normal' | 'standard' | 'emergency')
      update:   change_id, at least one field
      add_task: change_id, task_short_description
    """

    action: Literal["get", "create", "update", "add_task"] = Field(...)
    change_id: Optional[str] = Field(
        default=None, description="sys_id or CHG number for get/update/add_task"
    )

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
    state: Optional[str] = Field(default=None, description="Update only")
    work_notes: Optional[str] = Field(default=None, description="Update only")

    # add_task-specific
    task_short_description: Optional[str] = Field(default=None, description="Required for add_task")
    task_description: Optional[str] = Field(default=None)
    task_assigned_to: Optional[str] = Field(default=None)
    task_planned_start_date: Optional[str] = Field(default=None)
    task_planned_end_date: Optional[str] = Field(default=None)

    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageChangeParams":
        if self.action == "get":
            pass
        elif self.action == "create":
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
            if not self.type:
                raise ValueError("type is required for action='create' (normal/standard/emergency)")
        elif self.action == "update":
            if not self.change_id:
                raise ValueError("change_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _CHANGE_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        elif self.action == "add_task":
            if not self.change_id:
                raise ValueError("change_id is required for action='add_task'")
            if not self.task_short_description:
                raise ValueError("task_short_description is required for action='add_task'")
        return self


def _project_change(params: ManageChangeParams, fields: tuple[str, ...]) -> Dict[str, Any]:
    return {f: getattr(params, f) for f in fields if getattr(params, f) is not None}


@register_tool(
    name="manage_change",
    params=ManageChangeParams,
    description="Get/create/update a change request or add a change task (table: change_request).",
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
    if params.action == "create":
        # ManageChangeParams validator guarantees these are present per action.
        assert params.short_description is not None
        assert params.type is not None
        return change_service.create(
            config,
            auth_manager,
            short_description=params.short_description,
            type=params.type,
            **_project_change(params, _CHANGE_CREATE_FIELDS[1:]),
        )
    if params.action == "update":
        assert params.change_id is not None
        return change_service.update(
            config,
            auth_manager,
            change_id=params.change_id,
            dry_run=params.dry_run,
            **_project_change(params, _CHANGE_UPDATE_FIELDS),
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
