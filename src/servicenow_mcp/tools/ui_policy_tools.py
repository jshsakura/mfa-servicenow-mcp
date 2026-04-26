"""
UI Policy tools for the ServiceNow MCP server.

This module provides tools for managing UI policies and their actions in ServiceNow.
UI policies dynamically change the behavior of form fields (visibility, mandatory, read-only).
"""

import logging
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import ui_policy as ui_policy_service
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter models
# ---------------------------------------------------------------------------


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
        return ui_policy_service.create(config, auth_manager, **kwargs)
    # add_action
    kwargs = {"ui_policy": params.ui_policy, "field": params.field}
    for f in ("visible", "mandatory", "disabled", "cleared"):
        v = getattr(params, f)
        if v is not None:
            kwargs[f] = v
    return ui_policy_service.add_action(config, auth_manager, **kwargs)
