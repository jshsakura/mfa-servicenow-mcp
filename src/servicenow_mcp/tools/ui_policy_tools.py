"""
UI Policy tools for the ServiceNow MCP server.

This module provides tools for managing UI policies and their actions in ServiceNow.
UI policies dynamically change the behavior of form fields (visibility, mandatory, read-only).
"""

import logging
from typing import Any, ClassVar, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import ui_policy as ui_policy_service
from servicenow_mcp.services import ui_policy_manage
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Parameter models
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# manage_ui_policy — bundle for sys_ui_policy + sys_ui_policy_action
# ---------------------------------------------------------------------------


_FORM_ONLY = frozenset({"table", "conditions", "global_policy", "view_name", "cleared", "field"})
_CATALOG_ONLY = frozenset(
    {
        "catalog_item",
        "variable_set",
        "catalog_conditions",
        "applies_catalog",
        "applies_req_item",
        "applies_sc_task",
        "applies_target_record",
        "variable",
    }
)
_POLICY_COMMON = ("short_description", "active", "order", "on_load", "reverse_if_false")
_POLICY_SCRIPTS = ("script_true", "script_false")
_FORM_POLICY = ("conditions", "global_policy", "view_name")
_CATALOG_POLICY = (
    "catalog_conditions",
    "applies_catalog",
    "applies_req_item",
    "applies_sc_task",
    "applies_target_record",
)
_ACTION_COMMON = ("visible", "mandatory", "disabled")


def _update_fields(kind: str) -> tuple:
    extra = _FORM_POLICY if kind == "form" else _CATALOG_POLICY
    return (*_POLICY_COMMON, *_POLICY_SCRIPTS, *extra)


def _action_fields(kind: str) -> tuple:
    return (*_ACTION_COMMON, *(("cleared",) if kind == "form" else ("variable", "order")))


class ManageUiPolicyParams(BaseModel):
    """Manage UI policies — kind=form (sys_ui_policy) or kind=catalog (catalog_ui_policy).

    Required per action:
      list:          (all optional)
      get:           ui_policy
      create:        form: table, short_description | catalog: short_description + catalog_item OR variable_set
      update:        ui_policy + at least one policy field
      add_action:    form: ui_policy, field | catalog: ui_policy, variable (name)
      update_action: action_id + at least one action field
      remove_action: action_id
    """

    action: Literal[
        "list", "get", "create", "update", "add_action", "update_action", "remove_action"
    ] = Field(...)
    kind: Literal["form", "catalog"] = Field(
        default="form", description="form = sys_ui_policy; catalog = catalog_ui_policy"
    )

    # create / update — policy fields
    table: Optional[str] = Field(default=None, description="Target table (form)")
    short_description: Optional[str] = Field(default=None, description="Policy description")
    conditions: Optional[str] = Field(default=None, description="Encoded query (form)")
    active: Optional[bool] = Field(default=None, description="Default true on create")
    global_policy: Optional[bool] = Field(default=None, description="Default true on create")
    view_name: Optional[str] = Field(default=None)
    on_load: Optional[bool] = Field(default=None, description="Default true on create")
    reverse_if_false: Optional[bool] = Field(default=None, description="Default true on create")
    order: Optional[int] = Field(default=None, description="Default 100 on create")
    script_true: Optional[str] = Field(default=None)
    script_false: Optional[str] = Field(default=None)

    # catalog policy
    catalog_item: Optional[str] = Field(default=None, description="Catalog item sys_id (catalog)")
    variable_set: Optional[str] = Field(
        default=None, description="Variable set sys_id; exactly one of item/set (catalog)"
    )
    catalog_conditions: Optional[str] = Field(
        default=None,
        description="Encoded query using variable NAMES, e.g. type=single^EQ; stored as IO:<id>",
    )
    applies_catalog: Optional[bool] = Field(default=None)
    applies_req_item: Optional[bool] = Field(default=None)
    applies_sc_task: Optional[bool] = Field(default=None)
    applies_target_record: Optional[bool] = Field(default=None)

    # get / update / add_action / list
    ui_policy: Optional[str] = Field(default=None, description="Policy sys_id")
    # update_action / remove_action
    action_id: Optional[str] = Field(default=None, description="Policy action sys_id")

    # action fields
    field: Optional[str] = Field(default=None, description="Field name to control (form)")
    variable: Optional[str] = Field(
        default=None, description="Variable NAME (or sys_id) of the item/set (catalog)"
    )
    visible: Optional[Union[bool, str]] = Field(default=None, description="true/false/ignore")
    mandatory: Optional[Union[bool, str]] = Field(default=None, description="true/false/ignore")
    disabled: Optional[Union[bool, str]] = Field(default=None, description="true/false/ignore")
    cleared: Optional[Union[bool, str]] = Field(default=None, description="Clear value (form)")

    # list
    query: Optional[str] = Field(default=None, description="short_description contains")
    limit: int = Field(default=20, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    count_only: bool = Field(default=False, description="Return count only")

    dry_run: bool = Field(default=False, description="Preview the write without sending it")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset(
            {
                "kind",
                "table",
                "catalog_item",
                "variable_set",
                "query",
                "active",
                "limit",
                "offset",
                "count_only",
            }
        ),
        "get": frozenset({"kind", "ui_policy"}),
        "create": frozenset(
            {"kind", "dry_run", *_POLICY_COMMON, *_POLICY_SCRIPTS, *_FORM_POLICY, *_CATALOG_POLICY}
            | {"table", "catalog_item", "variable_set"}
        ),
        "update": frozenset(
            {"kind", "ui_policy", "dry_run", *_POLICY_COMMON, *_POLICY_SCRIPTS}
            | set(_FORM_POLICY)
            | set(_CATALOG_POLICY)
        ),
        "add_action": frozenset(
            {
                "kind",
                "ui_policy",
                "dry_run",
                "field",
                "variable",
                "order",
                *_ACTION_COMMON,
                "cleared",
            }
        ),
        "update_action": frozenset(
            {"kind", "action_id", "dry_run", "variable", "order", *_ACTION_COMMON, "cleared"}
        ),
        "remove_action": frozenset({"kind", "action_id", "ui_policy", "dry_run"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageUiPolicyParams":
        a, kind = self.action, self.kind
        # A field of the other kind is a mistake, not an extra: say so.
        other = _CATALOG_ONLY if kind == "form" else _FORM_ONLY
        allowed = self._FIELDS_BY_ACTION[a]
        wrong = sorted(f for f in self.model_fields_set & other if f in allowed)
        if wrong:
            raise ValueError(f"{wrong} do not apply to kind='{kind}'")
        for f in ("visible", "mandatory", "disabled"):
            v = getattr(self, f)
            if kind == "catalog" or isinstance(v, bool) or v is None:
                if v is not None:
                    try:
                        ui_policy_manage.tristate(v)
                    except ValueError as exc:
                        raise ValueError(f"{f}: {exc}") from None
        if self.dry_run and kind == "form" and a in ("create", "add_action"):
            raise ValueError(f"dry_run is not supported for kind='form' action='{a}'")

        if a == "create":
            if not self.short_description:
                raise ValueError("short_description is required for action='create'")
            if kind == "form" and not self.table:
                raise ValueError("table is required for action='create'")
            if kind == "catalog" and bool(self.catalog_item) == bool(self.variable_set):
                raise ValueError("exactly one of catalog_item / variable_set is required")
        elif a == "add_action":
            if not self.ui_policy:
                raise ValueError("ui_policy is required for action='add_action'")
            if kind == "form" and not self.field:
                raise ValueError("field is required for action='add_action'")
            if kind == "catalog" and not self.variable:
                raise ValueError("variable (name) is required for catalog action='add_action'")
        elif a in ("get", "update"):
            if not self.ui_policy:
                raise ValueError(f"ui_policy is required for action='{a}'")
            if a == "update" and not any(
                getattr(self, f) is not None for f in _update_fields(kind)
            ):
                raise ValueError("at least one policy field must be provided for action='update'")
        elif a in ("update_action", "remove_action"):
            if not self.action_id:
                raise ValueError(f"action_id is required for action='{a}'")
            if a == "update_action" and not any(
                getattr(self, f) is not None for f in _action_fields(kind)
            ):
                raise ValueError("at least one action field must be provided for update_action")
        return self


@register_tool(
    name="manage_ui_policy",
    params=ManageUiPolicyParams,
    description="List/get/create/update UI policies + field actions; kind=catalog for catalog UI policies (variable names).",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_ui_policy(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageUiPolicyParams,
) -> Dict[str, Any]:
    kind, a = params.kind, params.action
    p = {f: getattr(params, f) for f in type(params).model_fields if f not in ("action", "kind")}

    if kind == "form" and a == "create":
        kwargs: Dict[str, Any] = {
            "table": params.table,
            "short_description": params.short_description,
            "active": True if params.active is None else params.active,
            "global_policy": True if params.global_policy is None else params.global_policy,
            "on_load": True if params.on_load is None else params.on_load,
            "reverse_if_false": (
                True if params.reverse_if_false is None else params.reverse_if_false
            ),
            "order": 100 if params.order is None else params.order,
        }
        for f in ("conditions", "view_name", "script_true", "script_false"):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return ui_policy_service.create(config, auth_manager, **kwargs)
    if kind == "form" and a == "add_action":
        kwargs = {"ui_policy": params.ui_policy, "field": params.field}
        for f in ("visible", "mandatory", "disabled", "cleared"):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = str(v).lower() if isinstance(v, bool) else v
        return ui_policy_service.add_action(config, auth_manager, **kwargs)

    if a == "create":
        return ui_policy_manage.create_catalog_policy(config, auth_manager, p)
    if a == "add_action":
        return ui_policy_manage.add_catalog_action(config, auth_manager, p)
    if a == "list":
        return ui_policy_manage.list_policies(config, auth_manager, kind, p)
    if a == "get":
        return ui_policy_manage.get_policy(config, auth_manager, kind, p)
    if a == "update":
        return ui_policy_manage.update_policy(config, auth_manager, kind, p)
    if a == "update_action":
        return ui_policy_manage.update_action(config, auth_manager, kind, p)
    return ui_policy_manage.remove_action(config, auth_manager, kind, p)
