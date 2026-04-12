"""
Change management tools for the ServiceNow MCP server.

This module provides tools for managing change requests in ServiceNow.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .sn_api import invalidate_query_cache, sn_count, sn_query_page

logger = logging.getLogger(__name__)


class CreateChangeRequestParams(BaseModel):
    """Parameters for creating a change request."""

    short_description: str = Field(..., description="Short description of the change request")
    description: Optional[str] = Field(
        None, description="Detailed description of the change request"
    )
    type: str = Field(..., description="Type of change (normal, standard, emergency)")
    risk: Optional[str] = Field(None, description="Risk level of the change")
    impact: Optional[str] = Field(None, description="Impact of the change")
    category: Optional[str] = Field(None, description="Category of the change")
    requested_by: Optional[str] = Field(None, description="User who requested the change")
    assignment_group: Optional[str] = Field(None, description="Group assigned to the change")
    start_date: Optional[str] = Field(None, description="Planned start date (YYYY-MM-DD HH:MM:SS)")
    end_date: Optional[str] = Field(None, description="Planned end date (YYYY-MM-DD HH:MM:SS)")


class UpdateChangeRequestParams(BaseModel):
    """Parameters for updating a change request."""

    change_id: str = Field(..., description="Change request ID or sys_id")
    short_description: Optional[str] = Field(
        None, description="Short description of the change request"
    )
    description: Optional[str] = Field(
        None, description="Detailed description of the change request"
    )
    state: Optional[str] = Field(None, description="State of the change request")
    risk: Optional[str] = Field(None, description="Risk level of the change")
    impact: Optional[str] = Field(None, description="Impact of the change")
    category: Optional[str] = Field(None, description="Category of the change")
    assignment_group: Optional[str] = Field(None, description="Group assigned to the change")
    start_date: Optional[str] = Field(None, description="Planned start date (YYYY-MM-DD HH:MM:SS)")
    end_date: Optional[str] = Field(None, description="Planned end date (YYYY-MM-DD HH:MM:SS)")
    work_notes: Optional[str] = Field(None, description="Work notes to add to the change request")


class GetChangeRequestDetailsParams(BaseModel):
    """Parameters for getting change request details or listing change requests."""

    change_id: Optional[str] = Field(None, description="Change request ID or sys_id. If provided, returns full details for that single change request.")
    limit: Optional[int] = Field(10, description="Maximum number of records to return (list mode)")
    offset: Optional[int] = Field(0, description="Offset to start from (list mode)")
    state: Optional[str] = Field(None, description="Filter by state (list mode)")
    type: Optional[str] = Field(None, description="Filter by type (normal, standard, emergency) (list mode)")
    category: Optional[str] = Field(None, description="Filter by category (list mode)")
    assignment_group: Optional[str] = Field(None, description="Filter by assignment group (list mode)")
    timeframe: Optional[str] = Field(
        None, description="Filter by timeframe (upcoming, in-progress, completed) (list mode)"
    )
    query: Optional[str] = Field(None, description="Additional query string (list mode)")
    count_only: bool = Field(
        False,
        description="Return count only without fetching records. Uses lightweight Aggregate API. (list mode)",
    )


class AddChangeTaskParams(BaseModel):
    """Parameters for adding a task to a change request."""

    change_id: str = Field(..., description="Change request ID or sys_id")
    short_description: str = Field(..., description="Short description of the task")
    description: Optional[str] = Field(None, description="Detailed description of the task")
    assigned_to: Optional[str] = Field(None, description="User assigned to the task")
    planned_start_date: Optional[str] = Field(
        None, description="Planned start date (YYYY-MM-DD HH:MM:SS)"
    )
    planned_end_date: Optional[str] = Field(
        None, description="Planned end date (YYYY-MM-DD HH:MM:SS)"
    )


class SubmitChangeForApprovalParams(BaseModel):
    """Parameters for submitting a change request for approval."""

    change_id: str = Field(..., description="Change request ID or sys_id")
    approval_comments: Optional[str] = Field(None, description="Comments for the approval request")


class ApproveChangeParams(BaseModel):
    """Parameters for approving a change request."""

    change_id: str = Field(..., description="Change request ID or sys_id")
    approver_id: Optional[str] = Field(None, description="ID of the approver")
    approval_comments: Optional[str] = Field(None, description="Comments for the approval")


class RejectChangeParams(BaseModel):
    """Parameters for rejecting a change request."""

    change_id: str = Field(..., description="Change request ID or sys_id")
    approver_id: Optional[str] = Field(None, description="ID of the approver")
    rejection_reason: str = Field(..., description="Reason for rejection")


@register_tool(
    name="create_change_request",
    params=CreateChangeRequestParams,
    description="Create a change request. Requires short_description and type (normal/standard/emergency).",
    serialization="str",
    return_type=str,
)
def create_change_request(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateChangeRequestParams,
) -> Dict[str, Any]:
    """Create a new change request in ServiceNow."""
    data: Dict[str, Any] = {
        "short_description": params.short_description,
        "type": params.type,
    }

    for field_name in (
        "description",
        "risk",
        "impact",
        "category",
        "requested_by",
        "assignment_group",
        "start_date",
        "end_date",
    ):
        value = getattr(params, field_name)
        if value:
            data[field_name] = value

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

        return {
            "success": True,
            "message": "Change request created successfully",
            "change_request": result["result"],
        }
    except Exception as e:
        logger.error(f"Error creating change request: {e}")
        return {
            "success": False,
            "message": f"Error creating change request: {str(e)}",
        }


@register_tool(
    name="update_change_request",
    params=UpdateChangeRequestParams,
    description="Update a change request by sys_id. Supports state, description, risk, impact, dates, and work notes.",
    serialization="str",
    return_type=str,
)
def update_change_request(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateChangeRequestParams,
) -> Dict[str, Any]:
    """Update an existing change request in ServiceNow."""
    data: Dict[str, Any] = {}

    for field_name in (
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
    ):
        value = getattr(params, field_name)
        if value:
            data[field_name] = value

    url = f"{config.api_url}/table/change_request/{params.change_id}"

    try:
        response = auth_manager.make_request(
            "PUT",
            url,
            json=data,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = response.json()

        invalidate_query_cache(table="change_request")

        return {
            "success": True,
            "message": "Change request updated successfully",
            "change_request": result["result"],
        }
    except Exception as e:
        logger.error(f"Error updating change request: {e}")
        return {
            "success": False,
            "message": f"Error updating change request: {str(e)}",
        }


@register_tool(
    name="get_change_request_details",
    params=GetChangeRequestDetailsParams,
    description="Get a single change request by sys_id/number, or list change requests with filters.",
    serialization="json",
    return_type=str,
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
    name="add_change_task",
    params=AddChangeTaskParams,
    description="Create a change_task under a change request. Requires change_id and short_description.",
    serialization="json_dict",
    return_type=str,
)
def add_change_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: AddChangeTaskParams,
) -> Dict[str, Any]:
    """Add a task to a change request in ServiceNow."""
    data: Dict[str, Any] = {
        "change_request": params.change_id,
        "short_description": params.short_description,
    }

    for field_name in ("description", "assigned_to", "planned_start_date", "planned_end_date"):
        value = getattr(params, field_name)
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
    data: Dict[str, Any] = {"state": "assess"}

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


@register_tool(
    name="approve_change",
    params=ApproveChangeParams,
    description="Approve a change request and transition its state to implement. Requires change_id.",
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
        # Step 1: Find the approval record
        approval_rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sysapproval_approver",
            query=f"document_id={params.change_id}",
            fields="",
            limit=1,
            offset=0,
        )

        if not approval_rows:
            return {
                "success": False,
                "message": "No approval record found for this change request",
            }

        approval_id = approval_rows[0]["sys_id"]

        headers = {"Content-Type": "application/json"}

        # Step 2: PATCH approval record to "approved"
        approval_update_url = f"{config.api_url}/table/sysapproval_approver/{approval_id}"
        approval_data: Dict[str, Any] = {"state": "approved"}

        if params.approval_comments:
            approval_data["comments"] = params.approval_comments

        approval_update_response = auth_manager.make_request(
            "PATCH",
            approval_update_url,
            json=approval_data,
            headers=headers,
        )
        approval_update_response.raise_for_status()

        # Step 3: PATCH change_request state to "implement"
        change_url = f"{config.api_url}/table/change_request/{params.change_id}"
        change_data = {"state": "implement"}

        change_response = auth_manager.make_request(
            "PATCH",
            change_url,
            json=change_data,
            headers=headers,
        )
        change_response.raise_for_status()

        # Invalidate both tables
        invalidate_query_cache(table="sysapproval_approver")
        invalidate_query_cache(table="change_request")

        return {
            "success": True,
            "message": "Change request approved successfully",
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
    description="Reject a change request and transition its state to canceled. Requires change_id and rejection_reason.",
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
        # Step 1: Find the approval record
        approval_rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sysapproval_approver",
            query=f"document_id={params.change_id}",
            fields="",
            limit=1,
            offset=0,
        )

        if not approval_rows:
            return {
                "success": False,
                "message": "No approval record found for this change request",
            }

        approval_id = approval_rows[0]["sys_id"]

        headers = {"Content-Type": "application/json"}

        # Step 2: PATCH approval record to "rejected"
        approval_update_url = f"{config.api_url}/table/sysapproval_approver/{approval_id}"
        approval_data = {
            "state": "rejected",
            "comments": params.rejection_reason,
        }

        approval_update_response = auth_manager.make_request(
            "PATCH",
            approval_update_url,
            json=approval_data,
            headers=headers,
        )
        approval_update_response.raise_for_status()

        # Step 3: PATCH change_request state to "canceled"
        change_url = f"{config.api_url}/table/change_request/{params.change_id}"
        change_data = {
            "state": "canceled",
            "work_notes": f"Change request rejected: {params.rejection_reason}",
        }

        change_response = auth_manager.make_request(
            "PATCH",
            change_url,
            json=change_data,
            headers=headers,
        )
        change_response.raise_for_status()

        # Invalidate both tables
        invalidate_query_cache(table="sysapproval_approver")
        invalidate_query_cache(table="change_request")

        return {
            "success": True,
            "message": "Change request rejected successfully",
        }
    except Exception as e:
        logger.error(f"Error rejecting change: {e}")
        return {
            "success": False,
            "message": f"Error rejecting change: {str(e)}",
        }
