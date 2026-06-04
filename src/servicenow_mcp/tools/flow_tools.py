"""Unified Flow Designer tool — manage_flow_designer.

Consolidates 6 individual flow tools into one composite tool with action
dispatch. Lets the package config (tool_packages.yaml) expose read-only
actions in 'standard' while unlocking write actions in 'portal_developer'
and above.

Backed by existing implementations in:
- flow_designer_tools.py (list/get_detail/get_executions/compare/update)
- flow_edit_tools.py     (checkout/save/discard/patch workflow)
"""

import logging
from typing import Any, ClassVar, Dict, Literal, Optional, cast

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .flow_designer_tools import (
    CompareFlowsParams,
    GetActionSourceParams,
    GetFlowDetailsParams,
    GetFlowExecutionsParams,
    ListFlowsParams,
    UpdateFlowDesignerParams,
    compare_flows,
    get_action_source,
    get_flow_details,
    get_flow_executions,
    list_flows,
    update_flow_designer,
)
from .flow_edit_tools import ManageFlowEditParams, manage_flow_edit

logger = logging.getLogger(__name__)

# Action groups — used by validator and by docs.
_READ_ACTIONS = frozenset(
    {"list", "get_detail", "get_executions", "compare", "edit_status", "get_action_source"}
)
_EDIT_ACTIONS = frozenset(
    {
        "checkout",
        "set_action_input",
        "set_trigger_condition",
        "set_branch_condition",
        "save",
        "discard",
        "edit_status",
    }
)
_NEEDS_FLOW_ID = frozenset(
    {
        "get_detail",
        "get_executions",
        "update",
        "checkout",
        "set_action_input",
        "set_trigger_condition",
        "set_branch_condition",
        "save",
        "discard",
        "edit_status",
    }
)


class ManageFlowDesignerParams(BaseModel):
    """Unified Flow Designer tool — list/inspect/compare flows + full edit workflow.

    Required per action:
      list:                  (none — all params optional)
      get_detail:            flow_id
      get_executions:        flow_id (or context_id for single execution)
      compare:               flow_id_a|name_a AND flow_id_b|name_b
      update:                flow_id + at least one of new_name/description/active
      checkout:              flow_id (browser auth required)
      set_action_input:      flow_id, node_id, input_name, value
      set_trigger_condition: flow_id, value (node_id optional — first trigger if omitted)
      set_branch_condition:  flow_id, node_id, value
      save:                  flow_id
      discard:               flow_id
      edit_status:           flow_id (reads local checkout file)
    """

    action: Literal[
        # Read
        "list",
        "get_detail",
        "get_executions",
        "compare",
        "get_action_source",
        # Write — metadata
        "update",
        # Write — edit workflow (browser auth)
        "checkout",
        "set_action_input",
        "set_trigger_condition",
        "set_branch_condition",
        "save",
        "discard",
        "edit_status",
    ] = Field(
        ...,
        description="Writes (checkout/set_*/save/update/discard) need browser auth; rest are reads.",
    )

    # ---- Common ----
    flow_id: Optional[str] = Field(
        default=None,
        description="Flow sys_id; required for get_detail/get_executions/update/edit",
    )
    limit: int = Field(default=20, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")

    # ---- list ----
    include_inactive: bool = Field(default=False, description="Include inactive flows")
    flow_status: Optional[str] = Field(default=None, description="Status: Draft/Published/etc")
    name_filter: Optional[str] = Field(default=None, description="Name contains-match")
    scope: Optional[str] = Field(default=None, description="Scope namespace")
    query: Optional[str] = Field(default=None, description="Additional encoded query")
    count_only: bool = Field(default=False, description="Return count only")
    flow_type: Optional[Literal["flow", "subflow", "all"]] = Field(
        default=None, description="Type filter; None = flows only"
    )

    # ---- get_detail ----
    include_structure: bool = Field(default=False, description="Include flow structure tree")
    include_triggers: bool = Field(default=False, description="Include trigger config")
    include_executions_summary: bool = Field(
        default=False, description="Include recent execution summary"
    )
    trace_pill: Optional[str] = Field(default=None, description="Trace data pill through flow")
    include_subflow_tree: bool = Field(
        default=False, description="Include recursive subflow call tree"
    )
    summary_format: bool = Field(default=True, description="Compact format; False = raw JSON")

    # ---- get_executions ----
    context_id: Optional[str] = Field(
        default=None, description="Execution sys_id (sys_flow_context)"
    )
    flow_name: Optional[str] = Field(default=None, description="Flow name contains-match")
    exec_state: Optional[str] = Field(
        default=None, description="Complete/Error/Waiting/Cancelled/In Progress"
    )
    source_record: Optional[str] = Field(default=None, description="Source record display value")
    errors_only: bool = Field(default=False, description="Only errored executions")

    # ---- compare ----
    flow_id_a: Optional[str] = Field(default=None, description="First flow sys_id")
    flow_id_b: Optional[str] = Field(default=None, description="Second flow sys_id")
    name_a: Optional[str] = Field(default=None, description="First flow name fallback")
    name_b: Optional[str] = Field(default=None, description="Second flow name fallback")
    include_label_cache: bool = Field(default=True, description="Include label_cache diff")

    # ---- update ----
    new_name: Optional[str] = Field(default=None, description="New flow name")
    description: Optional[str] = Field(default=None, description="New flow description")
    active: Optional[bool] = Field(default=None, description="New active status")

    # ---- get_action_source ----
    action_ref: Optional[str] = Field(
        default=None, description="Action sys_id/name/internal_name (get_action_source)"
    )
    include_versions: bool = Field(
        default=False, description="get_action_source: include published-snapshot versions"
    )

    # ---- edit workflow ----
    node_id: Optional[str] = Field(default=None, description="Action/logic/trigger instance id")
    input_name: Optional[str] = Field(default=None, description="Input field name")
    value: Optional[str] = Field(default=None, description="New value")
    condition_label: Optional[str] = Field(default=None, description="Branch condition label")
    publish: bool = Field(default=False, description="Publish after save")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset(
            {
                "limit",
                "offset",
                "include_inactive",
                "flow_status",
                "name_filter",
                "scope",
                "query",
                "count_only",
                "flow_type",
            }
        ),
        "get_detail": frozenset(
            {
                "flow_id",
                "include_structure",
                "include_triggers",
                "include_executions_summary",
                "trace_pill",
                "include_subflow_tree",
                "summary_format",
            }
        ),
        "get_executions": frozenset(
            {
                "flow_id",
                "limit",
                "offset",
                "context_id",
                "flow_name",
                "exec_state",
                "source_record",
                "errors_only",
            }
        ),
        "compare": frozenset({"flow_id_a", "flow_id_b", "name_a", "name_b", "include_label_cache"}),
        "get_action_source": frozenset({"action_ref", "include_versions", "limit"}),
        "update": frozenset({"flow_id", "new_name", "description", "active"}),
        "checkout": frozenset({"flow_id"}),
        "set_action_input": frozenset({"flow_id", "node_id", "input_name", "value"}),
        "set_trigger_condition": frozenset({"flow_id", "node_id", "value"}),
        "set_branch_condition": frozenset({"flow_id", "node_id", "value", "condition_label"}),
        "save": frozenset({"flow_id", "publish"}),
        "discard": frozenset({"flow_id"}),
        "edit_status": frozenset({"flow_id"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageFlowDesignerParams":
        action = self.action

        if action in _NEEDS_FLOW_ID and not self.flow_id:
            raise ValueError(f"flow_id is required for action='{action}'")

        if action == "compare":
            if not (self.flow_id_a or self.name_a):
                raise ValueError("compare requires flow_id_a or name_a")
            if not (self.flow_id_b or self.name_b):
                raise ValueError("compare requires flow_id_b or name_b")

        if action == "get_action_source" and not self.action_ref:
            raise ValueError("get_action_source requires action_ref")

        if action == "update":
            if self.new_name is None and self.description is None and self.active is None:
                raise ValueError("update requires at least one of: new_name, description, active")

        if action == "set_action_input":
            if not self.node_id:
                raise ValueError("set_action_input requires node_id")
            if not self.input_name:
                raise ValueError("set_action_input requires input_name")
            if self.value is None:
                raise ValueError("set_action_input requires value")

        if action == "set_branch_condition":
            if not self.node_id:
                raise ValueError("set_branch_condition requires node_id")
            if self.value is None:
                raise ValueError("set_branch_condition requires value")

        if action == "set_trigger_condition":
            if self.value is None:
                raise ValueError("set_trigger_condition requires value")

        return self


# ---------------------------------------------------------------------------
# Sub-action adapters — translate unified params → original impl params
# ---------------------------------------------------------------------------


def _do_list(
    config: ServerConfig, auth_manager: AuthManager, p: ManageFlowDesignerParams
) -> Dict[str, Any]:
    return list_flows(
        config,
        auth_manager,
        ListFlowsParams(
            limit=p.limit,
            offset=p.offset,
            include_inactive=p.include_inactive,
            status=p.flow_status,
            name=p.name_filter,
            scope=p.scope,
            query=p.query,
            count_only=p.count_only,
            type=p.flow_type,
        ),
    )


def _do_get_detail(
    config: ServerConfig, auth_manager: AuthManager, p: ManageFlowDesignerParams
) -> Dict[str, Any]:
    assert p.flow_id is not None  # guaranteed by _validate_per_action
    return get_flow_details(
        config,
        auth_manager,
        GetFlowDetailsParams(
            flow_id=p.flow_id,
            include_structure=p.include_structure,
            include_triggers=p.include_triggers,
            include_executions_summary=p.include_executions_summary,
            trace_pill=p.trace_pill,
            include_subflow_tree=p.include_subflow_tree,
            summary_format=p.summary_format,
        ),
    )


def _do_get_executions(
    config: ServerConfig, auth_manager: AuthManager, p: ManageFlowDesignerParams
) -> Dict[str, Any]:
    return get_flow_executions(
        config,
        auth_manager,
        GetFlowExecutionsParams(
            context_id=p.context_id,
            flow_name=p.flow_name,
            flow_id=p.flow_id,
            state=p.exec_state,
            source_record=p.source_record,
            limit=p.limit,
            offset=p.offset,
            errors_only=p.errors_only,
        ),
    )


def _do_compare(
    config: ServerConfig, auth_manager: AuthManager, p: ManageFlowDesignerParams
) -> Dict[str, Any]:
    return compare_flows(
        config,
        auth_manager,
        CompareFlowsParams(
            flow_id_a=p.flow_id_a,
            flow_id_b=p.flow_id_b,
            name_a=p.name_a,
            name_b=p.name_b,
            include_label_cache=p.include_label_cache,
        ),
    )


def _do_update(
    config: ServerConfig, auth_manager: AuthManager, p: ManageFlowDesignerParams
) -> Dict[str, Any]:
    assert p.flow_id is not None  # guaranteed by _validate_per_action
    return update_flow_designer(
        config,
        auth_manager,
        UpdateFlowDesignerParams(
            flow_id=p.flow_id,
            name=p.new_name,
            description=p.description,
            active=p.active,
        ),
    )


def _do_get_action_source(
    config: ServerConfig, auth_manager: AuthManager, p: ManageFlowDesignerParams
) -> Dict[str, Any]:
    assert p.action_ref is not None  # guaranteed by _validate_per_action
    return get_action_source(
        config,
        auth_manager,
        GetActionSourceParams(
            action_ref=p.action_ref,
            include_versions=p.include_versions,
            limit=p.limit,
        ),
    )


# Map unified action → ManageFlowEditParams.action (1:1 except edit_status).
_EDIT_ACTION_MAP: Dict[str, str] = {
    "checkout": "checkout",
    "set_action_input": "set_action_input",
    "set_trigger_condition": "set_trigger_condition",
    "set_branch_condition": "set_branch_condition",
    "save": "save",
    "discard": "discard",
    "edit_status": "status",  # rename to avoid collision with flow_status field
}


_EditActionT = Literal[
    "checkout",
    "set_action_input",
    "set_trigger_condition",
    "set_branch_condition",
    "save",
    "discard",
    "status",
]


def _do_edit(
    config: ServerConfig, auth_manager: AuthManager, p: ManageFlowDesignerParams
) -> Dict[str, Any]:
    assert p.flow_id is not None  # guaranteed by _validate_per_action
    edit_action = cast(_EditActionT, _EDIT_ACTION_MAP[p.action])
    return manage_flow_edit(
        config,
        auth_manager,
        ManageFlowEditParams(
            action=edit_action,
            flow_id=p.flow_id,
            node_id=p.node_id,
            input_name=p.input_name,
            value=p.value,
            condition_label=p.condition_label,
            publish=p.publish,
        ),
    )


# ---------------------------------------------------------------------------
# Composite tool
# ---------------------------------------------------------------------------


_DISPATCH = {
    "list": _do_list,
    "get_detail": _do_get_detail,
    "get_executions": _do_get_executions,
    "compare": _do_compare,
    "get_action_source": _do_get_action_source,
    "update": _do_update,
}


@register_tool(
    name="manage_flow_designer",
    params=ManageFlowDesignerParams,
    description=(
        "Flow Designer (sys_hub_flow) read+edit. "
        "Edit: checkout→set_*→save+publish. Browser auth to write."
    ),
    serialization="json",
    return_type=dict,
)
def manage_flow_designer(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageFlowDesignerParams,
) -> Dict[str, Any]:
    """Dispatch to the underlying implementation by action."""
    handler = _DISPATCH.get(params.action)
    if handler is not None:
        return handler(config, auth_manager, params)
    if params.action in _EDIT_ACTION_MAP:
        return _do_edit(config, auth_manager, params)
    # Should be unreachable — Literal[...] gates this at parse time.
    return {"success": False, "error": f"Unknown action: {params.action}"}
