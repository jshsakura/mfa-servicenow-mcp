"""
UI Policy tools for the ServiceNow MCP server.

This module provides tools for managing UI policies and their actions in ServiceNow.
UI policies dynamically change the behavior of form fields (visibility, mandatory, read-only).
"""

import logging
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter models
# ---------------------------------------------------------------------------


class CreateUIPolicyParams(BaseModel):
    """Parameters for creating a UI policy."""

    table: str = Field(..., description="Target table name (e.g. 'incident', 'sc_req_item')")
    short_description: str = Field(..., description="Short description of the UI policy")
    conditions: Optional[str] = Field(
        None,
        description="Encoded query condition that triggers this policy "
        "(e.g. 'priority=1^state=1')",
    )
    active: bool = Field(True, description="Whether the policy is active")
    global_policy: bool = Field(
        True,
        description="If true, applies to all views. If false, specify view_name.",
    )
    view_name: Optional[str] = Field(
        None, description="Specific view name when global_policy is false"
    )
    on_load: bool = Field(True, description="Execute when the form loads")
    reverse_if_false: bool = Field(
        True, description="Reverse actions when conditions are no longer met"
    )
    order: int = Field(100, description="Execution order (lower runs first)")
    script_true: Optional[str] = Field(
        None, description="Script to run when conditions are true (advanced)"
    )
    script_false: Optional[str] = Field(
        None, description="Script to run when conditions are false (advanced)"
    )


class CreateUIPolicyActionParams(BaseModel):
    """Parameters for creating a UI policy action."""

    ui_policy: str = Field(..., description="sys_id of the parent UI policy")
    field: str = Field(..., description="Field name to control (e.g. 'category', 'assigned_to')")
    visible: Optional[str] = Field(
        None,
        description="Field visibility: 'true' (show), 'false' (hide), or empty (ignore)",
    )
    mandatory: Optional[str] = Field(
        None,
        description="Field mandatory: 'true' (required), 'false' (optional), or empty (ignore)",
    )
    disabled: Optional[str] = Field(
        None,
        description="Field read-only: 'true' (read-only), 'false' (editable), or empty (ignore)",
    )
    cleared: Optional[str] = Field(
        None,
        description="Clear field value: 'true' (clear), 'false' (keep), or empty (ignore)",
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@register_tool(
    name="create_ui_policy",
    params=CreateUIPolicyParams,
    description="Create a form field behavior rule (show/hide/mandatory) triggered by encoded query conditions.",
    serialization="raw_dict",
    return_type=dict,
)
def create_ui_policy(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateUIPolicyParams,
) -> Dict[str, Any]:
    """Create a UI policy in ServiceNow."""
    url = f"{config.instance_url}/api/now/table/sys_ui_policy"

    body: Dict[str, Any] = {
        "table": params.table,
        "short_description": params.short_description,
        "active": str(params.active).lower(),
        "global": str(params.global_policy).lower(),
        "on_load": str(params.on_load).lower(),
        "reverse_if_false": str(params.reverse_if_false).lower(),
        "order": str(params.order),
    }

    if params.conditions:
        body["conditions"] = params.conditions
    if params.view_name:
        body["view"] = params.view_name
    if params.script_true:
        body["script_true"] = params.script_true
    if params.script_false:
        body["script_false"] = params.script_false

    headers = auth_manager.get_headers()

    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "result" not in data:
            return {"success": False, "message": "Failed to create UI policy"}

        result = data["result"]
        return {
            "success": True,
            "message": f"Created UI policy: {result.get('short_description')}",
            "ui_policy_id": result.get("sys_id"),
            "table": result.get("table"),
            "short_description": result.get("short_description"),
        }

    except Exception as e:
        logger.error(f"Error creating UI policy: {e}")
        return {"success": False, "message": f"Error creating UI policy: {str(e)}"}


@register_tool(
    name="create_ui_policy_action",
    params=CreateUIPolicyActionParams,
    description="Add a field-level action to a UI policy: set visibility, mandatory, or read-only per field.",
    serialization="raw_dict",
    return_type=dict,
)
def create_ui_policy_action(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateUIPolicyActionParams,
) -> Dict[str, Any]:
    """Create a UI policy action in ServiceNow."""
    # Verify parent UI policy exists
    verify_url = f"{config.instance_url}/api/now/table/sys_ui_policy/{params.ui_policy}"
    headers = auth_manager.get_headers()

    try:
        verify_resp = auth_manager.make_request(
            "GET",
            verify_url,
            params={"sysparm_fields": "sys_id,short_description,table"},
            headers=headers,
            timeout=30,
        )
        verify_resp.raise_for_status()
        verify_data = verify_resp.json()

        if "result" not in verify_data:
            return {
                "success": False,
                "message": f"UI policy not found: {params.ui_policy}",
            }

        parent_policy = verify_data["result"]
        table = parent_policy.get("table")

    except Exception as e:
        logger.error(f"Error verifying UI policy: {e}")
        return {
            "success": False,
            "message": f"Error verifying UI policy: {str(e)}",
        }

    # Create the action
    url = f"{config.instance_url}/api/now/table/sys_ui_policy_action"

    body: Dict[str, Any] = {
        "ui_policy": params.ui_policy,
        "table": table,
        "field": params.field,
    }

    if params.visible is not None:
        body["visible"] = params.visible
    if params.mandatory is not None:
        body["mandatory"] = params.mandatory
    if params.disabled is not None:
        body["disabled"] = params.disabled
    if params.cleared is not None:
        body["cleared"] = params.cleared

    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "result" not in data:
            return {"success": False, "message": "Failed to create UI policy action"}

        result = data["result"]
        return {
            "success": True,
            "message": f"Created UI policy action for field '{params.field}'",
            "action_id": result.get("sys_id"),
            "ui_policy": params.ui_policy,
            "field": params.field,
            "visible": result.get("visible"),
            "mandatory": result.get("mandatory"),
            "disabled": result.get("disabled"),
        }

    except Exception as e:
        logger.error(f"Error creating UI policy action: {e}")
        return {
            "success": False,
            "message": f"Error creating UI policy action: {str(e)}",
        }
