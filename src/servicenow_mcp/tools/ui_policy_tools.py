"""
UI Policy tools for the ServiceNow MCP server.

This module provides tools for managing UI policies and their actions in ServiceNow.
UI policies dynamically change the behavior of form fields (visibility, mandatory, read-only).
"""

import logging
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
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
        default=None,
        description="Encoded query condition that triggers this policy (e.g. 'priority=1^state=1')",
    )
    active: bool = Field(default=True, description="Whether the policy is active")
    global_policy: bool = Field(
        default=True,
        description="If true, applies to all views. If false, specify view_name.",
    )
    view_name: Optional[str] = Field(
        default=None, description="Specific view name when global_policy is false"
    )
    on_load: bool = Field(default=True, description="Execute when the form loads")
    reverse_if_false: bool = Field(
        default=True, description="Reverse actions when conditions are no longer met"
    )
    order: int = Field(default=100, description="Execution order (lower runs first)")
    script_true: Optional[str] = Field(
        default=None, description="Script to run when conditions are true (advanced)"
    )
    script_false: Optional[str] = Field(
        default=None, description="Script to run when conditions are false (advanced)"
    )


class CreateUIPolicyActionParams(BaseModel):
    """Parameters for creating a UI policy action."""

    ui_policy: str = Field(..., description="sys_id of the parent UI policy")
    field: str = Field(..., description="Field name to control (e.g. 'category', 'assigned_to')")
    visible: Optional[str] = Field(
        default=None,
        description="Field visibility: 'true' (show), 'false' (hide), or empty (ignore)",
    )
    mandatory: Optional[str] = Field(
        default=None,
        description="Field mandatory: 'true' (required), 'false' (optional), or empty (ignore)",
    )
    disabled: Optional[str] = Field(
        default=None,
        description="Field read-only: 'true' (read-only), 'false' (editable), or empty (ignore)",
    )
    cleared: Optional[str] = Field(
        default=None,
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
        invalidate_query_cache(table="sys_ui_policy")
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
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_ui_policy",
            query=f"sys_id={params.ui_policy}",
            fields="sys_id,short_description,table",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=False,
        )

        if not records:
            return {
                "success": False,
                "message": f"UI policy not found: {params.ui_policy}",
            }

        parent_policy = records[0]
        table = parent_policy.get("table")

    except Exception as e:
        logger.error(f"Error verifying UI policy: {e}")
        return {
            "success": False,
            "message": f"Error verifying UI policy: {str(e)}",
        }

    # Create the action
    url = f"{config.instance_url}/api/now/table/sys_ui_policy_action"
    headers = auth_manager.get_headers()

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
        invalidate_query_cache(table="sys_ui_policy_action")
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


# ---------------------------------------------------------------------------
# manage_ui_policy — bundle for sys_ui_policy + sys_ui_policy_action
# ---------------------------------------------------------------------------


class ManageUiPolicyParams(BaseModel):
    """Manage UI policies — table: sys_ui_policy / sys_ui_policy_action.

    Required per action:
      create:     table, short_description
      add_action: ui_policy, field
    """

    action: Literal["create", "add_action"] = Field(...)

    # create
    table: Optional[str] = Field(default=None, description="Target table (create)")
    short_description: Optional[str] = Field(
        default=None, description="Policy description (create)"
    )
    conditions: Optional[str] = Field(default=None)
    active: bool = Field(default=True)
    global_policy: bool = Field(default=True)
    view_name: Optional[str] = Field(default=None)
    on_load: bool = Field(default=True)
    reverse_if_false: bool = Field(default=True)
    order: int = Field(default=100)
    script_true: Optional[str] = Field(default=None)
    script_false: Optional[str] = Field(default=None)

    # add_action
    ui_policy: Optional[str] = Field(default=None, description="Policy sys_id (add_action)")
    field: Optional[str] = Field(default=None, description="Field name to control (add_action)")
    visible: Optional[str] = Field(default=None)
    mandatory: Optional[str] = Field(default=None)
    disabled: Optional[str] = Field(default=None)
    cleared: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageUiPolicyParams":
        a = self.action
        if a == "create":
            if not self.table:
                raise ValueError("table is required for action='create'")
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
        elif a == "add_action":
            if not self.ui_policy:
                raise ValueError("ui_policy is required for action='add_action'")
            if not self.field:
                raise ValueError("field is required for action='add_action'")
        return self


@register_tool(
    name="manage_ui_policy",
    params=ManageUiPolicyParams,
    description="UI Policy create + add field action (tables: sys_ui_policy / sys_ui_policy_action).",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_ui_policy(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageUiPolicyParams,
) -> Dict[str, Any]:
    if params.action == "create":
        kwargs: Dict[str, Any] = {
            "table": params.table,
            "short_description": params.short_description,
            "active": params.active,
            "global_policy": params.global_policy,
            "on_load": params.on_load,
            "reverse_if_false": params.reverse_if_false,
            "order": params.order,
        }
        for f in ("conditions", "view_name", "script_true", "script_false"):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return create_ui_policy(config, auth_manager, CreateUIPolicyParams(**kwargs))
    # add_action
    kwargs = {"ui_policy": params.ui_policy, "field": params.field}
    for f in ("visible", "mandatory", "disabled", "cleared"):
        v = getattr(params, f)
        if v is not None:
            kwargs[f] = v
    return create_ui_policy_action(config, auth_manager, CreateUIPolicyActionParams(**kwargs))
