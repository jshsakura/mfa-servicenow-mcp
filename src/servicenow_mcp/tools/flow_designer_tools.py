"""
Flow Designer tools for the ServiceNow MCP server.

Provides read-only tools for analyzing Flow Designer flows:
- List/search flows
- Get flow structure (actions, logic, subflows with nesting)
- Get flow execution history from sys_flow_context
- Get action/logic detail with input/output variables
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import AuthType, ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .sn_api import invalidate_query_cache, sn_count, sn_query_page

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLOW_TABLE = "sys_hub_flow"
FLOW_SNAPSHOT_TABLE = "sys_hub_flow_snapshot"
ACTION_V2_TABLE = "sys_hub_action_instance_v2"
LOGIC_V2_TABLE = "sys_hub_flow_logic_instance_v2"
SUBFLOW_V2_TABLE = "sys_hub_sub_flow_instance_v2"
FLOW_CONTEXT_TABLE = "sys_flow_context"
TRIGGER_TABLE = "sys_hub_trigger_instance"

# ---------------------------------------------------------------------------
# Parameter Models
# ---------------------------------------------------------------------------


class ListFlowsParams(BaseModel):
    """Parameters for listing Flow Designer flows."""

    limit: int = Field(default=20, description="Maximum number of records (max 100)")
    offset: int = Field(default=0, description="Pagination offset")
    include_inactive: bool = Field(
        default=False, description="Include inactive records (default: active only)"
    )
    status: Optional[str] = Field(
        default=None, description="Filter by status: Draft, Published, etc."
    )
    name: Optional[str] = Field(default=None, description="Filter by name (contains)")
    scope: Optional[str] = Field(default=None, description="Scope namespace or display name")
    query: Optional[str] = Field(default=None, description="Additional encoded query")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records.",
    )
    # 'flow' excludes subflows; 'subflow' = subflows only; 'all' = both.
    # None (default) behaves like 'flow'.
    type: Optional[Literal["flow", "subflow", "all"]] = Field(
        default=None,
        description="Filter by type (None = flows only).",
    )


class GetFlowDetailsParams(BaseModel):
    """Parameters for getting flow details with optional structure and triggers."""

    flow_id: str = Field(..., description="Flow sys_id from sys_hub_flow table")
    include_structure: bool = Field(
        default=False,
        description="Include flow structure (actions, logic, subflows with nesting tree)",
    )
    include_triggers: bool = Field(
        default=False,
        description="Include trigger configuration (what events start this flow)",
    )
    include_executions_summary: bool = Field(
        default=False,
        description="Include counts and recent executions summary",
    )
    trace_pill: Optional[str] = Field(
        default=None,
        description="Trace a data pill string across actions, logic, and subflows",
    )
    include_subflow_tree: bool = Field(
        default=False,
        description="Include recursive subflow call tree",
    )


class GetFlowExecutionsParams(BaseModel):
    """Parameters for getting flow execution history or a single execution detail."""

    context_id: Optional[str] = Field(
        default=None,
        description="If provided, return single execution detail by sys_id from sys_flow_context. Other filters are ignored.",
    )
    flow_name: Optional[str] = Field(
        default=None, description="Flow name to search (contains match)"
    )
    flow_id: Optional[str] = Field(default=None, description="Flow sys_id to filter executions")
    state: Optional[str] = Field(
        default=None,
        description="Filter by state: Complete, Waiting, Error, Cancelled, In Progress",
    )
    source_record: Optional[str] = Field(
        default=None, description="Filter by source record display value (contains)"
    )
    limit: int = Field(default=20, description="Maximum number of records (max 100)")
    offset: int = Field(default=0, description="Pagination offset")
    errors_only: bool = Field(
        default=False,
        description="Only return executions with errors",
    )


class UpdateFlowDesignerParams(BaseModel):
    """Parameters for updating a Flow Designer flow."""

    flow_id: str = Field(..., description="Flow sys_id from sys_hub_flow table")
    name: Optional[str] = Field(default=None, description="New name for the flow")
    description: Optional[str] = Field(default=None, description="New description for the flow")
    active: Optional[bool] = Field(default=None, description="Set active status")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_browser_auth(config: ServerConfig) -> bool:
    """Check if current auth type is browser (required for processflow API)."""
    return config.auth.type == AuthType.BROWSER


def _get_snapshot_id(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
) -> Optional[str]:
    """Get the published snapshot sys_id for a flow."""
    try:
        snapshots, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_SNAPSHOT_TABLE,
            query=f"master_flow={flow_id}^ORsys_id={flow_id}",
            fields="sys_id,name,status",
            limit=5,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
    except Exception as e:
        logger.error("Failed to query %s for flow %s: %s", FLOW_SNAPSHOT_TABLE, flow_id, e)
        return None
    if not snapshots:
        logger.warning("No snapshot found for flow %s in %s", flow_id, FLOW_SNAPSHOT_TABLE)
        return None
    # Prefer published snapshot
    for snap in snapshots:
        if snap.get("status") == "Published":
            return snap["sys_id"]
    # Fallback to first available
    return snapshots[0]["sys_id"]


def _build_component_tree(components: List[Dict]) -> List[Dict]:
    """Build a nested tree from flat component list using nesting_parent."""
    by_id = {}
    roots = []

    # Index all components
    for comp in sorted(components, key=lambda c: int(c.get("order", 0))):
        comp["children"] = []
        by_id[comp["sys_id"]] = comp

    # Build tree
    for comp in sorted(components, key=lambda c: int(c.get("order", 0))):
        parent_id = comp.get("nesting_parent", "")
        # nesting_parent can be a display value or sys_id
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(comp)
        else:
            roots.append(comp)

    return roots


def _safe_int(value: Any) -> int:
    """Convert a mixed order/position value to int safely."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _action_type_name(action: Dict[str, Any]) -> str:
    """Return a stable action type label from processflow action data."""
    action_type = action.get("actionType")
    if isinstance(action_type, dict):
        return action_type.get("name") or action_type.get("internal_name") or ""
    if isinstance(action_type, str):
        return action_type
    return ""


def _extract_pill_matches(value: Any, pill: str, path: str = "") -> List[Dict[str, str]]:
    """Recursively extract string values containing the target pill string."""
    matches: List[Dict[str, str]] = []
    lowered = pill.lower()

    if isinstance(value, str):
        if lowered in value.lower():
            matches.append({"path": path or "$", "value": value})
        return matches

    if isinstance(value, list):
        for index, item in enumerate(value):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            matches.extend(_extract_pill_matches(item, pill, next_path))
        return matches

    if isinstance(value, dict):
        for key, item in value.items():
            next_path = f"{path}.{key}" if path else str(key)
            matches.extend(_extract_pill_matches(item, pill, next_path))
    return matches


def _build_processflow_detail(
    flow_data: Dict[str, Any],
    include_subflow_inputs: bool = True,
) -> Dict[str, Any]:
    """Build the rich processflow detail payload reused by detail and compare paths."""

    def _order(item: Dict[str, Any]) -> int:
        return _safe_int(item.get("order") or item.get("position"))

    raw_actions = flow_data.get("actionInstances", [])
    actions: List[Dict[str, Any]] = []
    for action in sorted(raw_actions, key=_order):
        actions.append(
            {
                "order": action.get("order") or action.get("position"),
                "ui_id": action.get("uiUniqueIdentifier", ""),
                "parent_ui_id": action.get("parent", ""),
                "id": action.get("id", ""),
                "action_type_sys_id": action.get("actionTypeSysId", ""),
                "action_type_name": _action_type_name(action),
                "name": action.get("name", ""),
                "internal_name": action.get("internalName", ""),
                "deleted": action.get("deleted", False),
                "comment": action.get("comment", ""),
                "inputs": action.get("inputs", []),
                "outputs": action.get("outputs", []),
            }
        )

    raw_logic = flow_data.get("flowLogicInstances", [])
    logic_nodes: List[Dict[str, Any]] = []
    for node in sorted(raw_logic, key=_order):
        definition = (
            node.get("flowLogicDefinition")
            if isinstance(node.get("flowLogicDefinition"), dict)
            else {}
        )
        condition_label = ""
        condition_expr = ""
        for inp in node.get("inputs", []) or []:
            if not isinstance(inp, dict):
                continue
            if inp.get("name") == "condition_name":
                condition_label = inp.get("value", "") or inp.get("displayValue", "")
            elif inp.get("name") == "condition":
                condition_expr = inp.get("value", "") or inp.get("displayValue", "")
        logic_nodes.append(
            {
                "order": node.get("order") or node.get("position"),
                "ui_id": node.get("uiUniqueIdentifier", ""),
                "parent_ui_id": node.get("parent", ""),
                "id": node.get("id", ""),
                "logic_type": definition.get("type", ""),
                "logic_name": definition.get("name", "") or node.get("name", ""),
                "condition_label": condition_label,
                "condition": condition_expr,
                "connected_to": node.get("connectedTo", ""),
                "outputs_to_assign": node.get("outputsToAssign", []),
                "flow_block_id": node.get("flowBlockId", ""),
                "definition_id": node.get("definitionId", ""),
                "inputs": node.get("inputs", []),
            }
        )

    raw_subflows = flow_data.get("subFlowInstances", [])
    subflow_instances: List[Dict[str, Any]] = []
    for subflow in sorted(raw_subflows, key=_order):
        sub_meta = subflow.get("subFlow") if isinstance(subflow.get("subFlow"), dict) else {}
        subflow_instances.append(
            {
                "order": subflow.get("order") or subflow.get("position"),
                "ui_id": subflow.get("uiUniqueIdentifier", ""),
                "parent_ui_id": subflow.get("parent", ""),
                "id": subflow.get("id", ""),
                "subflow_sys_id": subflow.get("subflowSysId", "") or sub_meta.get("id", ""),
                "subflow_name": sub_meta.get("name", "") or subflow.get("name", ""),
                "subflow_internal_name": sub_meta.get("internalName", "")
                or subflow.get("internalName", ""),
                "subflow_scope": sub_meta.get("scopeName", "") or sub_meta.get("scope", ""),
                "inputs": subflow.get("inputs", []) if include_subflow_inputs else [],
            }
        )

    flow_inputs = flow_data.get("inputs", []) or []
    flow_outputs = flow_data.get("outputs", []) or []
    flow_variables = flow_data.get("flowVariables", []) or []
    triggers = flow_data.get("triggerInstances", []) or []
    label_cache = flow_data.get("label_cache") or flow_data.get("labelCache", []) or []
    deleted_logic = flow_data.get("deletedFlowLogicInstances", []) or []

    return {
        "triggers": triggers,
        "inputs": flow_inputs,
        "outputs": flow_outputs,
        "variables": flow_variables,
        "label_cache": label_cache,
        "deleted_flow_logic_instances": deleted_logic,
        "actions": actions,
        "logic": logic_nodes,
        "subflows": subflow_instances,
        "counts": {
            "triggers": len(triggers),
            "inputs": len(flow_inputs),
            "outputs": len(flow_outputs),
            "variables": len(flow_variables),
            "label_cache": (
                len(label_cache) if isinstance(label_cache, list) else len(str(label_cache))
            ),
            "actions": len(actions),
            "logic": len(logic_nodes),
            "subflows": len(subflow_instances),
        },
    }


def _trace_pill_usage(flow_data: Dict[str, Any], pill: str) -> Dict[str, Any]:
    """Trace a data pill string through processflow action, logic, and subflow payloads."""
    detail = _build_processflow_detail(flow_data)
    matches: List[Dict[str, Any]] = []

    for component_type, items in (
        ("action", detail["actions"]),
        ("logic", detail["logic"]),
        ("subflow", detail["subflows"]),
    ):
        for item in items:
            hits = _extract_pill_matches(item, pill)
            if hits:
                matches.append(
                    {
                        "component_type": component_type,
                        "name": item.get("name")
                        or item.get("logic_name")
                        or item.get("subflow_name")
                        or "",
                        "order": item.get("order", ""),
                        "ui_id": item.get("ui_id", ""),
                        "matches": hits,
                    }
                )

    return {
        "pill": pill,
        "match_count": len(matches),
        "components": matches,
    }


def _fetch_execution_summary(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
) -> Dict[str, Any]:
    """Return count and recent-history summary for a flow's executions."""
    snapshot_id = _get_snapshot_id(config, auth_manager, flow_id)
    flow_refs = [flow_id]
    if snapshot_id and snapshot_id not in flow_refs:
        flow_refs.append(snapshot_id)
    flow_query = "^OR".join(f"flow={ref}" for ref in flow_refs)

    counts = {
        "total": sn_count(config, auth_manager, FLOW_CONTEXT_TABLE, flow_query),
        "error_like": sn_count(
            config,
            auth_manager,
            FLOW_CONTEXT_TABLE,
            f"({flow_query})^stateINError,Cancelled^ORerror_messageISNOTEMPTY",
        ),
    }
    for state in ["Complete", "Error", "Cancelled", "Waiting", "In Progress"]:
        key = state.lower().replace(" ", "_")
        counts[key] = sn_count(
            config,
            auth_manager,
            FLOW_CONTEXT_TABLE,
            f"({flow_query})^state={state}",
        )

    recent, _ = sn_query_page(
        config,
        auth_manager,
        table=FLOW_CONTEXT_TABLE,
        query=flow_query,
        fields="sys_id,name,state,error_message,error_state,sys_created_on,source_table,source_record,run_time,flow",
        limit=5,
        offset=0,
        display_value=True,
        orderby="-sys_created_on",
    )
    return {"counts": counts, "recent": recent}


def _build_subflow_tree(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
    visited: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """Recursively build a subflow call tree from processflow or table data."""
    seen = set(visited or set())
    if flow_id in seen:
        return {"flow_id": flow_id, "cycle_detected": True, "children": []}
    seen.add(flow_id)

    flow_name = ""
    flow_type = ""
    scope = ""
    child_refs: List[Dict[str, Any]] = []

    if _is_browser_auth(config):
        pf_result = _try_processflow_api(config, auth_manager, flow_id)
        if pf_result and pf_result.get("result"):
            flow_data = pf_result["result"]
            flow_name = flow_data.get("name", "")
            flow_type = flow_data.get("type", "")
            scope = flow_data.get("scope", "")
            for subflow in sorted(
                flow_data.get("subFlowInstances", []),
                key=lambda item: _safe_int(item.get("order") or item.get("position")),
            ):
                sub_meta = (
                    subflow.get("subFlow") if isinstance(subflow.get("subFlow"), dict) else {}
                )
                child_id = subflow.get("subflowSysId", "") or sub_meta.get("id", "")
                child_refs.append(
                    {
                        "order": subflow.get("order") or subflow.get("position"),
                        "ui_id": subflow.get("uiUniqueIdentifier", ""),
                        "flow_id": child_id,
                        "name": sub_meta.get("name", "") or subflow.get("name", ""),
                    }
                )
    if not flow_name:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_TABLE,
            query=f"sys_id={flow_id}",
            fields="sys_id,name,type,sys_scope,label_cache",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if records:
            flow = records[0]
            flow_name = flow.get("name", "")
            flow_type = flow.get("type", "")
            scope = flow.get("sys_scope", "")
            structure = _fetch_flow_structure(config, auth_manager, flow_id)
            for binding in structure.get("subflow_bindings", []):
                child_refs.append(
                    {
                        "order": binding.get("order", ""),
                        "ui_id": binding.get("ui_id", ""),
                        "flow_id": binding.get("subflow_parent_flow_id", ""),
                        "name": binding.get("subflow_parent_flow_name", "")
                        or binding.get("subflow_snapshot_name", ""),
                    }
                )

    children: List[Dict[str, Any]] = []
    for child in child_refs:
        child_id = child.get("flow_id", "")
        node = {
            "order": child.get("order", ""),
            "ui_id": child.get("ui_id", ""),
            "flow_id": child_id,
            "name": child.get("name", ""),
        }
        if child_id:
            node["children"] = _build_subflow_tree(config, auth_manager, child_id, seen)["children"]
        else:
            node["children"] = []
        children.append(node)

    return {
        "flow_id": flow_id,
        "name": flow_name,
        "type": flow_type,
        "scope": scope,
        "children": children,
        "cycle_detected": False,
    }


def _try_processflow_api(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
) -> Optional[Dict[str, Any]]:
    """Try the processflow REST API — the actual API used by Flow Designer UI.

    Endpoint: /api/now/processflow/flow/{flow_id}
    Returns the full flow definition (68+ fields) including triggers, actions,
    logic nodes, subflows, variables, and snapshots in a single call.
    Requires browser session auth (JSESSIONID + x-usertoken).
    """
    try:
        url = f"{config.instance_url}/api/now/processflow/flow/{flow_id}"
        response = auth_manager.make_request(
            "GET",
            url,
            headers={"x-transaction-source": "Interface=Web"},
        )
        response.raise_for_status()
        raw = response.json()
        if not isinstance(raw, dict):
            return {"_error": "processflow returned non-dict response"}

        # ServiceNow standard REST wrapper: {"result": {...}, "session": {...}}
        result_value = raw.get("result")
        outer: Dict[str, Any] = result_value if isinstance(result_value, dict) else raw

        # Yokohama wraps flow data with error metadata at this level
        err_msg = outer.get("errorMessage")
        err_code = outer.get("errorCode")
        if err_msg or (isinstance(err_code, int) and err_code != 0):
            return {
                "_error": err_msg or f"processflow API error code {err_code}",
                "_error_code": err_code,
                "_plugin_active": outer.get("integrationsPluginActive"),
                "_raw_keys": list(outer.keys()),
            }

        # Yokohama: flow is under outer.data. Older versions: outer is the flow.
        if isinstance(outer.get("data"), dict) and outer["data"]:
            flow_payload = outer["data"]
        else:
            flow_payload = outer

        if not isinstance(flow_payload, dict) or not flow_payload:
            return {
                "_error": f"processflow: no flow data, keys={list(outer.keys())}",
                "_raw_keys": list(outer.keys()),
            }

        # Normalise: always return under "result" key so callers stay consistent
        return {"result": flow_payload}
    except Exception as e:
        logger.error("processflow API failed for flow %s: %s", flow_id, e)
        return {"_error": str(e)}


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------


@register_tool(
    name="list_flow_designers",
    params=ListFlowsParams,
    description="List Flow Designer workflows/subflows (modern, sys_hub_flow). For legacy wf_workflow use manage_workflow.",
    serialization="json",
    return_type=dict,
)
def list_flows(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListFlowsParams,
) -> Dict[str, Any]:
    """List Flow Designer flows (and/or subflows)."""
    query_parts: List[str] = []

    # Type filter: flow (default), subflow, all
    flow_type = (params.type or "flow").lower()
    if flow_type == "subflow":
        query_parts.append("type=subflow^substatusISEMPTY")
    elif flow_type != "all":
        # Default: exclude subflows
        query_parts.append("type!=subflow")

    if not params.include_inactive:
        query_parts.append("active=true")
    if params.status:
        query_parts.append(f"status={params.status}")
    if params.name:
        query_parts.append(f"nameLIKE{params.name}")
    if params.scope:
        query_parts.append(f"sys_scope.scope={params.scope}^ORsys_scope.name={params.scope}")
    if params.query:
        query_parts.append(params.query)

    query_string = "^".join(query_parts) if query_parts else ""

    if params.count_only:
        count = sn_count(config, auth_manager, FLOW_TABLE, query_string)
        return {"success": True, "count": count}

    try:
        flows, total_count = sn_query_page(
            config,
            auth_manager,
            table=FLOW_TABLE,
            query=query_string,
            fields="sys_id,name,status,active,trigger_type,sys_scope,sys_updated_on,sys_updated_by,description",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
        )
        return {
            "success": True,
            "flows": flows,
            "count": len(flows),
            "total": total_count if total_count is not None else len(flows),
        }
    except Exception as e:
        logger.error(f"Error listing flows: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_flow_designer_detail",
    params=GetFlowDetailsParams,
    description="Get Flow Designer workflow structure, triggers, executions. Entry point for modern workflow analysis.",
    serialization="json",
    return_type=dict,
)
def get_flow_details(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetFlowDetailsParams,
) -> Dict[str, Any]:
    """Get flow details by sys_id, optionally including structure and triggers.

    Tries the processflow API first for complete data. Falls back to Table API.
    """
    flow_id = params.flow_id

    pf_error: Optional[str] = None
    needs_processflow = any(
        [
            params.include_structure,
            params.include_triggers,
            params.include_subflow_tree,
            bool(params.trace_pill),
        ]
    )

    try:
        # processflow API — preferred when rich structure analysis is requested
        if needs_processflow and _is_browser_auth(config):
            pf_result = _try_processflow_api(config, auth_manager, flow_id)
            if pf_result and pf_result.get("result"):
                pf_data = pf_result.get("result", pf_result)
                detail = _build_processflow_detail(pf_data)
                result: Dict[str, Any] = {
                    "success": True,
                    "source": "processflow_api",
                    "flow": {
                        "sys_id": pf_data.get("id", flow_id),
                        "name": pf_data.get("name", ""),
                        "description": pf_data.get("description", ""),
                        "status": pf_data.get("status", ""),
                        "active": pf_data.get("active", ""),
                        "scope": pf_data.get("scope", ""),
                    },
                }
                if params.include_structure:
                    result["structure"] = detail
                if params.include_triggers:
                    result["triggers"] = detail["triggers"]
                if params.include_executions_summary:
                    result["executions_summary"] = _fetch_execution_summary(
                        config, auth_manager, flow_id
                    )
                if params.trace_pill:
                    result["pill_trace"] = _trace_pill_usage(pf_data, params.trace_pill)
                if params.include_subflow_tree:
                    result["subflow_tree"] = _build_subflow_tree(config, auth_manager, flow_id)
                return result
            else:
                pf_error = (
                    pf_result.get("_error", "no result key in response")
                    if pf_result
                    else "processflow API returned None"
                )

        # Fallback: Table API
        flows, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_TABLE,
            query=f"sys_id={flow_id}",
            fields="",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        flow = flows[0] if flows else {}

        result = {
            "success": True,
            "source": "table_api",
            "flow": flow,
        }
        if pf_error:
            result["processflow_note"] = pf_error

        if params.include_triggers:
            result["triggers"] = _fetch_flow_triggers(config, auth_manager, flow_id)

        if params.include_structure:
            structure = _fetch_flow_structure(config, auth_manager, flow_id)
            result["structure"] = structure
            if not structure.get("success"):
                result["structure_error"] = structure.get("error", "unknown")

        if params.include_executions_summary:
            result["executions_summary"] = _fetch_execution_summary(config, auth_manager, flow_id)

        if params.include_subflow_tree:
            result["subflow_tree"] = _build_subflow_tree(config, auth_manager, flow_id)

        if params.trace_pill:
            result["pill_trace"] = {
                "pill": params.trace_pill,
                "match_count": 0,
                "components": [],
                "note": "Data pill tracing requires browser auth via processflow API.",
            }

        return result
    except Exception as e:
        logger.error(f"Error getting flow details: {e}")
        return {"success": False, "error": str(e)}


def _extract_processflow_structure(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract a concise structure summary from a processflow API response."""
    flow_data = result.get("result", result)

    actions = flow_data.get("actionInstances", [])
    logic = flow_data.get("flowLogicInstances", [])
    subflows = flow_data.get("subFlowInstances", [])
    triggers = flow_data.get("triggerInstances", [])
    variables = flow_data.get("flowVariables", [])
    inputs_val = flow_data.get("inputs", [])
    outputs_val = flow_data.get("outputs", [])

    flat_summary = []
    for a in actions:
        flat_summary.append(
            {
                "order": a.get("position", a.get("order")),
                "type": "action",
                "name": a.get("name", ""),
                "action_type": a.get("actionType", a.get("action_type", "")),
            }
        )
    for node in logic:
        flat_summary.append(
            {
                "order": node.get("position", node.get("order")),
                "type": "logic",
                "name": node.get("name", ""),
                "logic_type": node.get("type", node.get("compilableType", "")),
            }
        )
    for s in subflows:
        flat_summary.append(
            {
                "order": s.get("position", s.get("order")),
                "type": "subflow",
                "name": s.get("name", ""),
            }
        )

    flat_summary.sort(key=lambda x: int(x.get("order", 0) or 0))

    return {
        "total_actions": len(actions),
        "total_logic": len(logic),
        "total_subflows": len(subflows),
        "total_triggers": len(triggers),
        "total_variables": len(variables),
        "inputs": inputs_val if isinstance(inputs_val, list) else [],
        "outputs": outputs_val if isinstance(outputs_val, list) else [],
        "triggers": triggers,
        "flat_summary": flat_summary,
    }


def _parse_label_cache(label_cache: str) -> List[str]:
    """Parse label_cache into a list of individual label strings."""
    if not label_cache:
        return []
    # label_cache is comma-or-newline separated
    labels = []
    for line in label_cache.replace(",", "\n").split("\n"):
        stripped = line.strip()
        if stripped:
            labels.append(stripped)
    return labels


def _fetch_subflow_bindings(
    config: ServerConfig,
    auth_manager: AuthManager,
    snapshot_id: str,
    label_cache: str,
) -> Dict[str, Any]:
    """Resolve actual subflow bindings from sys_hub_sub_flow_instance_v2.

    For each subflow instance, traces: instance → snapshot → master_flow
    to determine the REAL subflow being invoked (not just what label_cache shows).

    Returns ``subflow_bindings`` list and ``mismatch_summary`` comparing
    label_cache labels against actual subflow references.
    """
    # 1. Get subflow instances with both raw and display values in one query
    instances_all, _ = sn_query_page(
        config,
        auth_manager,
        table=SUBFLOW_V2_TABLE,
        query=f"flow={snapshot_id}",
        fields="sys_id,name,order,position,ui_id,parent_ui_id,nesting_parent,subflow",
        limit=100,
        offset=0,
        display_value="all",
    )

    if not instances_all:
        return {
            "subflow_bindings": [],
            "mismatch_summary": {"mismatch_count": 0, "mismatches": []},
        }

    # With display_value=all, reference fields become {"value": "sys_id", "display_value": "name"}.
    # Non-reference fields remain plain strings. Extract both raw and display views.
    instances_raw = []
    display_map: Dict[str, Dict] = {}
    for inst in instances_all:
        sid = inst.get("sys_id", "")
        raw_inst: Dict[str, Any] = {}
        disp_inst: Dict[str, Any] = {}
        for k, v in inst.items():
            if isinstance(v, dict) and "value" in v:
                raw_inst[k] = v["value"]
                disp_inst[k] = v.get("display_value", v["value"])
            else:
                raw_inst[k] = v
                disp_inst[k] = v
        instances_raw.append(raw_inst)
        display_map[sid] = disp_inst

    # 2. Batch-resolve snapshot references → master_flow (single query with display_value=all)
    snapshot_ids = list({inst.get("subflow", "") for inst in instances_raw if inst.get("subflow")})
    snapshot_map: Dict[str, Dict] = {}
    master_flow_ids: set = set()

    if snapshot_ids:
        snapshots_all, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_SNAPSHOT_TABLE,
            query=f"sys_idIN{','.join(snapshot_ids)}",
            fields="sys_id,name,master_flow",
            limit=100,
            offset=0,
            display_value="all",
        )
        for s in snapshots_all:
            sid = s.get("sys_id", "")
            master_ref = s.get("master_flow", {})
            if isinstance(master_ref, dict) and "value" in master_ref:
                master_id = master_ref["value"]
                master_display = master_ref.get("display_value", "")
            else:
                master_id = master_ref if isinstance(master_ref, str) else ""
                master_display = ""
            name_ref = s.get("name", "")
            raw_name = (
                name_ref["value"]
                if isinstance(name_ref, dict) and "value" in name_ref
                else name_ref
            )
            display_name = (
                name_ref.get("display_value", raw_name) if isinstance(name_ref, dict) else raw_name
            )
            snapshot_map[sid] = {
                "sys_id": sid,
                "name": raw_name,
                "master_flow": master_id,
                "snapshot_display_name": display_name,
                "master_flow_display": master_display,
            }
            if master_id:
                master_flow_ids.add(master_id)

    # 3. Batch-resolve master flow names (if not already in display values)
    master_flow_map: Dict[str, str] = {}
    remaining_ids = [
        fid
        for fid in master_flow_ids
        if not any(
            s.get("master_flow_display")
            for s in snapshot_map.values()
            if s.get("master_flow") == fid
        )
    ]
    if remaining_ids:
        flows_display, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_TABLE,
            query=f"sys_idIN{','.join(remaining_ids)}",
            fields="sys_id,name",
            limit=100,
            offset=0,
            display_value=True,
        )
        master_flow_map = {f["sys_id"]: f.get("name", "") for f in flows_display}

    # 4. Build bindings list
    labels = _parse_label_cache(label_cache)
    bindings: List[Dict[str, Any]] = []

    for inst in sorted(instances_raw, key=lambda x: int(x.get("order", 0) or 0)):
        sid = inst["sys_id"]
        disp = display_map.get(sid, {})
        subflow_ref = inst.get("subflow", "")
        snap = snapshot_map.get(subflow_ref, {})
        master_id = snap.get("master_flow", "")
        master_name = snap.get("master_flow_display", "") or master_flow_map.get(master_id, "")
        ui_id = inst.get("ui_id", "")

        # Instance name is often empty — use subflow display value instead
        inst_name = disp.get("name", "") or inst.get("name", "")
        subflow_display_name = disp.get("subflow", "")
        snapshot_name = snap.get("snapshot_display_name", snap.get("name", ""))
        # Best available name for this binding
        effective_name = inst_name or subflow_display_name or snapshot_name

        # Match labels containing ui_id or any known name for this binding
        matched_labels = [
            lbl
            for lbl in labels
            if (ui_id and ui_id in lbl)
            or (effective_name and effective_name in lbl)
            or (subflow_display_name and subflow_display_name in lbl)
            or (master_name and master_name in lbl)
        ]

        bindings.append(
            {
                "order": inst.get("order", ""),
                "ui_id": ui_id,
                "parent_ui_id": inst.get("parent_ui_id", ""),
                "instance_name": effective_name,
                "subflow_snapshot_id": subflow_ref,
                "subflow_snapshot_name": snap.get("snapshot_display_name", snap.get("name", "")),
                "subflow_parent_flow_id": master_id,
                "subflow_parent_flow_name": master_name,
                "label_matches": matched_labels,
            }
        )

    # 5. Detect mismatches: label says X but actual reference is Y
    mismatches: List[Dict[str, Any]] = []
    for b in bindings:
        actual_name = b["subflow_parent_flow_name"] or b["subflow_snapshot_name"]
        for lbl in b["label_matches"]:
            # Simple heuristic: if label contains a name prefix that differs
            # from the actual subflow parent name, flag it
            if actual_name and lbl and actual_name not in lbl:
                mismatches.append(
                    {
                        "ui_id": b["ui_id"],
                        "order": b["order"],
                        "label": lbl,
                        "actual_subflow": actual_name,
                        "actual_subflow_id": b["subflow_parent_flow_id"],
                    }
                )

    return {
        "subflow_bindings": bindings,
        "mismatch_summary": {
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
        },
    }


def _fetch_flow_structure(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
) -> Dict[str, Any]:
    """Get the full component tree of a flow (internal helper)."""

    # ------------------------------------------------------------------
    # Strategy 1: processflow API (browser auth only, full detail)
    # ------------------------------------------------------------------
    pf_result = (
        _try_processflow_api(config, auth_manager, flow_id) if _is_browser_auth(config) else None
    )
    if pf_result:
        structure = _extract_processflow_structure(pf_result)
        return {
            "success": True,
            "source": "processflow_api",
            "flow_id": flow_id,
            **structure,
        }

    # ------------------------------------------------------------------
    # Strategy 2: Table API fallback (structure + subflow binding resolution)
    # ------------------------------------------------------------------
    try:
        snapshot_id = _get_snapshot_id(config, auth_manager, flow_id)
        if not snapshot_id:
            return {
                "success": False,
                "error": (
                    f"No snapshot in {FLOW_SNAPSHOT_TABLE} for flow {flow_id}. "
                    "Possible causes: flow not published, or ACL blocks "
                    f"{FLOW_SNAPSHOT_TABLE} read. Check server logs for details."
                ),
            }

        # Fetch the flow record for label_cache (needed for mismatch detection)
        flow_records, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_TABLE,
            query=f"sys_id={flow_id}",
            fields="sys_id,name,label_cache",
            limit=1,
            offset=0,
            display_value=True,
        )
        label_cache = flow_records[0].get("label_cache", "") if flow_records else ""

        actions, _ = sn_query_page(
            config,
            auth_manager,
            table=ACTION_V2_TABLE,
            query=f"flow={snapshot_id}",
            fields="sys_id,name,order,action_type,position,nesting_parent,compilable_type",
            limit=100,
            offset=0,
            display_value=True,
        )
        for a in actions:
            a["component_type"] = "action"

        logic_nodes, _ = sn_query_page(
            config,
            auth_manager,
            table=LOGIC_V2_TABLE,
            query=f"flow={snapshot_id}",
            fields="sys_id,name,order,type,position,nesting_parent,compilable_type",
            limit=100,
            offset=0,
            display_value=True,
        )
        for node in logic_nodes:
            node["component_type"] = "logic"

        subflows, _ = sn_query_page(
            config,
            auth_manager,
            table=SUBFLOW_V2_TABLE,
            query=f"flow={snapshot_id}",
            fields="sys_id,name,order,position,nesting_parent,compilable_type",
            limit=100,
            offset=0,
            display_value=True,
        )
        for s in subflows:
            s["component_type"] = "subflow"

        all_components = actions + logic_nodes + subflows
        all_components.sort(key=lambda c: int(c.get("order", 0)))

        tree = _build_component_tree(all_components)

        flat_summary = []
        for comp in all_components:
            entry: Dict[str, Any] = {
                "order": comp.get("order"),
                "type": comp.get("component_type"),
                "name": comp.get("name", ""),
            }
            if comp.get("component_type") == "action":
                entry["action_type"] = comp.get("action_type", "")
            elif comp.get("component_type") == "logic":
                entry["logic_type"] = comp.get("type", comp.get("compilable_type", ""))
            if comp.get("nesting_parent"):
                entry["parent"] = comp["nesting_parent"]
            flat_summary.append(entry)

        result: Dict[str, Any] = {
            "success": True,
            "source": "table_api_fallback",
            "flow_id": flow_id,
            "snapshot_id": snapshot_id,
            "total_actions": len(actions),
            "total_logic": len(logic_nodes),
            "total_subflows": len(subflows),
            "flat_summary": flat_summary,
            "tree": tree,
        }

        # Include subflow binding details when subflows exist
        if subflows:
            binding_data = _fetch_subflow_bindings(config, auth_manager, snapshot_id, label_cache)
            result["subflow_bindings"] = binding_data["subflow_bindings"]
            result["mismatch_summary"] = binding_data["mismatch_summary"]
            if binding_data["mismatch_summary"]["mismatch_count"] > 0:
                result["note"] = (
                    "LABEL/BINDING MISMATCH DETECTED: label_cache contains references "
                    "that differ from actual subflow bindings. "
                    "Trust subflow_bindings (actual references) over label_cache (display metadata). "
                    "See mismatch_summary for details."
                )
            else:
                result["note"] = (
                    "Retrieved via Table API. Subflow bindings verified — "
                    "label_cache and actual references are consistent."
                )
        else:
            result["note"] = (
                "Retrieved via Table API (basic auth). "
                "Conditions and variable mappings are incomplete. "
                "Switch to browser auth for full detail via processflow API."
            )

        return result
    except Exception as e:
        logger.error(f"Error getting flow structure: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_flow_designer_executions",
    params=GetFlowExecutionsParams,
    description="Get Flow Designer workflow execution history (sys_flow_context). Modern flows only.",
    serialization="json",
    return_type=dict,
)
def get_flow_executions(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetFlowExecutionsParams,
) -> Dict[str, Any]:
    """Get flow execution history, or single execution detail if context_id given."""

    # Single execution detail mode
    if params.context_id:
        try:
            records, _ = sn_query_page(
                config,
                auth_manager,
                table=FLOW_CONTEXT_TABLE,
                query=f"sys_id={params.context_id}",
                fields="",
                limit=1,
                offset=0,
                display_value=True,
                fail_silently=False,
            )
            return {
                "success": True,
                "execution": records[0] if records else {},
            }
        except Exception as e:
            logger.error(f"Error getting flow execution detail: {e}")
            return {"success": False, "error": str(e)}

    # List mode
    query_parts: List[str] = []
    if params.flow_name:
        query_parts.append(f"nameLIKE{params.flow_name}")
    if params.flow_id:
        query_parts.append(f"flow={params.flow_id}")
    if params.state:
        query_parts.append(f"state={params.state}")
    if params.source_record:
        query_parts.append(f"source_recordLIKE{params.source_record}")
    if params.errors_only:
        query_parts.append("stateINError,Cancelled^ORerror_messageISNOTEMPTY")

    query_string = "^".join(query_parts) if query_parts else ""

    try:
        executions, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_CONTEXT_TABLE,
            query=query_string,
            fields="sys_id,name,state,error_message,error_state,sys_created_on,source_table,source_record,run_time,flow",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
            orderby="-sys_created_on",
        )

        return {
            "success": True,
            "executions": executions,
            "count": len(executions),
        }
    except Exception as e:
        logger.error(f"Error getting flow executions: {e}")
        return {"success": False, "error": str(e)}


def _fetch_flow_triggers(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
) -> List[Dict[str, Any]]:
    """Get triggers for a flow (internal helper). Returns list of trigger records."""
    snapshot_id = _get_snapshot_id(config, auth_manager, flow_id)

    query_parts = [f"flow={flow_id}"]
    if snapshot_id:
        query_parts.append(f"flow={snapshot_id}")
    query_string = "^OR".join(query_parts)

    triggers, _ = sn_query_page(
        config,
        auth_manager,
        table=TRIGGER_TABLE,
        query=query_string,
        fields="",
        limit=20,
        offset=0,
        display_value=True,
    )
    return triggers


# ---------------------------------------------------------------------------
# CRUD Tools
# ---------------------------------------------------------------------------


@register_tool(
    name="update_flow_designer",
    params=UpdateFlowDesignerParams,
    description="Update Flow Designer workflow name/description/active by sys_id (modern, sys_hub_flow).",
    serialization="json",
    return_type=dict,
)
def update_flow_designer(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateFlowDesignerParams,
) -> Dict[str, Any]:
    """Update a Flow Designer flow by sys_id."""
    flow_id = params.flow_id

    data: Dict[str, Any] = {}
    if params.name is not None:
        data["name"] = params.name
    if params.description is not None:
        data["description"] = params.description
    if params.active is not None:
        data["active"] = str(params.active).lower()

    if not data:
        return {"success": False, "error": "No update parameters provided"}

    try:
        url = f"{config.instance_url}/api/now/table/{FLOW_TABLE}/{flow_id}"
        response = auth_manager.make_request("PATCH", url, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table=FLOW_TABLE)
        return {
            "success": True,
            "flow": result.get("result", {}),
            "message": "Flow updated successfully",
        }
    except Exception as e:
        logger.error(f"Error updating flow designer: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Compare Flows (browser auth: processflow API, basic auth: Table API)
# ---------------------------------------------------------------------------


class CompareFlowsParams(BaseModel):
    """Parameters for comparing two Flow Designer flows/subflows."""

    flow_id_a: Optional[str] = Field(default=None, description="First flow sys_id")
    flow_id_b: Optional[str] = Field(default=None, description="Second flow sys_id")
    name_a: Optional[str] = Field(
        default=None, description="First flow name (used if flow_id_a empty)"
    )
    name_b: Optional[str] = Field(
        default=None, description="Second flow name (used if flow_id_b empty)"
    )
    include_label_cache: bool = Field(
        default=True, description="Include label_cache diff (shows child subflow references)"
    )


def _get_flow_for_compare(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
) -> Optional[Dict[str, Any]]:
    """Fetch flow data for comparison — processflow API or Table API with structure."""
    if _is_browser_auth(config):
        pf = _try_processflow_api(config, auth_manager, flow_id)
        if pf:
            return pf.get("result", pf)

    # Table API — get flow record + structure + triggers
    records, _ = sn_query_page(
        config,
        auth_manager,
        table=FLOW_TABLE,
        query=f"sys_id={flow_id}",
        fields="",
        limit=1,
        offset=0,
        display_value=True,
        fail_silently=False,
    )
    if not records:
        return None

    flow = records[0]
    # Enrich with structure so comparison isn't shallow
    structure = _fetch_flow_structure(config, auth_manager, flow_id)
    if structure.get("success"):
        flow["_structure"] = structure
    flow["_triggers"] = _fetch_flow_triggers(config, auth_manager, flow_id)
    return flow


def _extract_comparable(flow_data: Dict[str, Any], include_label_cache: bool) -> Dict[str, Any]:
    """Extract comparable fields from flow data."""
    # processflow API format
    if "actionInstances" in flow_data:
        actions = [
            {
                "name": a.get("name", ""),
                "type": a.get("actionType", ""),
                "order": a.get("position"),
            }
            for a in flow_data.get("actionInstances", [])
        ]
        logic = [
            {"name": n.get("name", ""), "type": n.get("type", ""), "order": n.get("position")}
            for n in flow_data.get("flowLogicInstances", [])
        ]
        subflows = [
            {"name": s.get("name", ""), "order": s.get("position")}
            for s in flow_data.get("subFlowInstances", [])
        ]
        result = {
            "name": flow_data.get("name")
            or flow_data.get("internalName")
            or flow_data.get("internal_name")
            or "",
            "status": flow_data.get("status", ""),
            "active": flow_data.get("active", ""),
            "scope": flow_data.get("scope", ""),
            "inputs": flow_data.get("inputs", []),
            "outputs": flow_data.get("outputs", []),
            "actions": sorted(actions, key=lambda x: int(x.get("order") or 0)),
            "logic": sorted(logic, key=lambda x: int(x.get("order") or 0)),
            "subflows": sorted(subflows, key=lambda x: int(x.get("order") or 0)),
            "trigger_count": len(flow_data.get("triggerInstances", [])),
            "variable_count": len(flow_data.get("flowVariables", [])),
        }
        if include_label_cache:
            lc = flow_data.get("label_cache") or flow_data.get("labelCache", "")
            result["label_cache"] = lc if isinstance(lc, str) else str(lc)
        return result

    # Table API format (enriched with _structure and _triggers)
    result = {
        "name": flow_data.get("name", ""),
        "status": flow_data.get("status", ""),
        "active": flow_data.get("active", ""),
        "scope": flow_data.get("sys_scope", ""),
    }

    structure = flow_data.get("_structure", {})
    if structure.get("success"):
        result["actions"] = [
            {"name": s.get("name", ""), "type": s.get("action_type", ""), "order": s.get("order")}
            for s in structure.get("flat_summary", [])
            if s.get("type") == "action"
        ]
        result["logic"] = [
            {"name": s.get("name", ""), "type": s.get("logic_type", ""), "order": s.get("order")}
            for s in structure.get("flat_summary", [])
            if s.get("type") == "logic"
        ]
        result["subflows"] = [
            {"name": s.get("name", ""), "order": s.get("order")}
            for s in structure.get("flat_summary", [])
            if s.get("type") == "subflow"
        ]
        result["total_actions"] = structure.get("total_actions", 0)
        result["total_logic"] = structure.get("total_logic", 0)
        result["total_subflows"] = structure.get("total_subflows", 0)
        # Actual subflow references (snapshot → master_flow resolution)
        if structure.get("subflow_bindings"):
            result["subflow_bindings"] = [
                {
                    "order": b.get("order", ""),
                    "instance_name": b.get("instance_name", ""),
                    "actual_subflow": b.get("subflow_parent_flow_name", ""),
                    "actual_subflow_id": b.get("subflow_parent_flow_id", ""),
                }
                for b in structure["subflow_bindings"]
            ]

    triggers = flow_data.get("_triggers", [])
    if triggers:
        result["trigger_count"] = len(triggers)

    if include_label_cache:
        result["label_cache"] = flow_data.get("label_cache", "")
    return result


def _diff_flows(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Compute structural diff between two comparable flow dicts."""
    differences = []
    identical = []

    all_keys = sorted(set(list(a.keys()) + list(b.keys())))
    for key in all_keys:
        va = a.get(key)
        vb = b.get(key)
        if va == vb:
            identical.append(key)
        else:
            entry: Dict[str, Any] = {"field": key, "flow_a": va, "flow_b": vb}
            # For label_cache, extract differing references
            if key == "label_cache" and isinstance(va, str) and isinstance(vb, str):
                a_refs = set(
                    line.strip() for line in va.replace(",", "\n").split("\n") if line.strip()
                )
                b_refs = set(
                    line.strip() for line in vb.replace(",", "\n").split("\n") if line.strip()
                )
                entry["only_in_a"] = sorted(a_refs - b_refs)[:50]
                entry["only_in_b"] = sorted(b_refs - a_refs)[:50]
                entry["common_count"] = len(a_refs & b_refs)
                del entry["flow_a"]
                del entry["flow_b"]
            # For subflow_bindings, show name-level diff instead of raw list
            elif key == "subflow_bindings" and isinstance(va, list) and isinstance(vb, list):
                a_names = {b_item.get("actual_subflow", "") for b_item in va}
                b_names = {b_item.get("actual_subflow", "") for b_item in vb}
                entry["only_in_a"] = sorted(a_names - b_names)
                entry["only_in_b"] = sorted(b_names - a_names)
                entry["common"] = sorted(a_names & b_names)
                del entry["flow_a"]
                del entry["flow_b"]
            differences.append(entry)

    return {
        "identical_fields": identical,
        "differences": differences,
        "total_identical": len(identical),
        "total_different": len(differences),
    }


def _resolve_flow_id(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: Optional[str],
    name: Optional[str],
    label: str,
) -> tuple:
    """Resolve flow_id from sys_id or name. Returns (sys_id, error_msg)."""
    if flow_id:
        return flow_id, None
    if not name:
        return None, f"Flow {label}: provide flow_id or name"
    # Search by exact name first, then contains
    for op in ("=", "LIKE"):
        records, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_TABLE,
            query=f"name{op}{name}",
            fields="sys_id,name",
            limit=5,
            offset=0,
            display_value=True,
        )
        if records:
            if len(records) == 1:
                return records[0]["sys_id"], None
            # Multiple matches — try exact match from results
            exact = [r for r in records if r.get("name", "").lower() == name.lower()]
            if exact:
                return exact[0]["sys_id"], None
            names = [r.get("name", "") for r in records[:5]]
            return (
                None,
                f"Flow {label}: '{name}' matched {len(records)} flows: {names}. Be more specific or use sys_id.",
            )
    return None, f"Flow {label}: no flow found with name '{name}'"


@register_tool(
    name="compare_flows",
    params=CompareFlowsParams,
    description="Diff two Flow Designer workflows by name/sys_id. Structure, subflow bindings, triggers.",
    serialization="json",
    return_type=dict,
)
def compare_flows(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CompareFlowsParams,
) -> Dict[str, Any]:
    """Compare two Flow Designer flows and return structural diff."""
    try:
        # Resolve flow IDs from sys_id or name
        id_a, err_a = _resolve_flow_id(config, auth_manager, params.flow_id_a, params.name_a, "A")
        if err_a:
            return {"success": False, "error": err_a}

        id_b, err_b = _resolve_flow_id(config, auth_manager, params.flow_id_b, params.name_b, "B")
        if err_b:
            return {"success": False, "error": err_b}

        flow_a = _get_flow_for_compare(config, auth_manager, id_a)
        if not flow_a:
            return {"success": False, "error": f"Flow A not found: {id_a}"}

        flow_b = _get_flow_for_compare(config, auth_manager, id_b)
        if not flow_b:
            return {"success": False, "error": f"Flow B not found: {id_b}"}

        comp_a = _extract_comparable(flow_a, params.include_label_cache)
        comp_b = _extract_comparable(flow_b, params.include_label_cache)
        diff = _diff_flows(comp_a, comp_b)

        return {
            "success": True,
            "flow_a": {"sys_id": id_a, "name": comp_a.get("name", "")},
            "flow_b": {"sys_id": id_b, "name": comp_b.get("name", "")},
            "summary": f"{diff['total_identical']} identical, {diff['total_different']} different",
            **diff,
        }
    except Exception as e:
        logger.error(f"Error comparing flows: {e}")
        return {"success": False, "error": str(e)}
