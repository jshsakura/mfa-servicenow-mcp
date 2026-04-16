"""
Flow Designer tools for the ServiceNow MCP server.

Provides read-only tools for analyzing Flow Designer flows:
- List/search flows
- Get flow structure (actions, logic, subflows with nesting)
- Get flow execution history from sys_flow_context
- Get action/logic detail with input/output variables
"""

import logging
from typing import Any, Dict, List, Optional

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
RECORD_TRIGGER_TABLE = "sys_flow_record_trigger"
ACTION_TYPE_TABLE = "sys_hub_action_type_definition"
PLAYBOOK_TABLE = "sys_pd_process_definition"
DECISION_TABLE = "sys_decision"

# ---------------------------------------------------------------------------
# Parameter Models
# ---------------------------------------------------------------------------


class ListFlowsParams(BaseModel):
    """Parameters for listing Flow Designer flows."""

    limit: int = Field(default=20, description="Maximum number of records (max 100)")
    offset: int = Field(default=0, description="Pagination offset")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    status: Optional[str] = Field(
        default=None, description="Filter by status: Draft, Published, etc."
    )
    name: Optional[str] = Field(default=None, description="Filter by name (contains)")
    scope: Optional[str] = Field(default=None, description="Scope namespace to filter by")
    query: Optional[str] = Field(default=None, description="Additional encoded query")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records.",
    )
    type: Optional[str] = Field(
        default=None,
        description=(
            "Filter by type: 'flow' (default — excludes subflows), "
            "'subflow' (subflows only), 'all' (both flows and subflows). "
            "If not set, returns flows only."
        ),
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


class ActivateFlowDesignerParams(BaseModel):
    """Parameters for activating a Flow Designer flow."""

    flow_id: str = Field(..., description="Flow sys_id from sys_hub_flow table")


class DeactivateFlowDesignerParams(BaseModel):
    """Parameters for deactivating a Flow Designer flow."""

    flow_id: str = Field(..., description="Flow sys_id from sys_hub_flow table")


class ListFlowTriggersByTableParams(BaseModel):
    """Parameters for listing flow triggers by table name."""

    table_name: str = Field(..., description="ServiceNow table name (e.g. 'incident')")
    scope: Optional[str] = Field(
        default=None, description="Filter by application scope (e.g. 'global')"
    )
    limit: int = Field(default=50, description="Maximum number of trigger records (max 200)")


class ListActionsParams(BaseModel):
    """Parameters for listing Flow Designer actions (sys_hub_action_type_definition)."""

    limit: int = Field(default=20, description="Maximum number of records (max 100)")
    offset: int = Field(default=0, description="Pagination offset")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    name: Optional[str] = Field(default=None, description="Filter by name (contains)")
    scope: Optional[str] = Field(default=None, description="Scope namespace to filter by")
    query: Optional[str] = Field(default=None, description="Additional encoded query")
    count_only: bool = Field(
        default=False, description="Return count only without fetching records."
    )


class GetActionDetailParams(BaseModel):
    """Parameters for getting a single action definition."""

    action_id: str = Field(
        ..., description="Action sys_id from sys_hub_action_type_definition table"
    )


class ListPlaybooksParams(BaseModel):
    """Parameters for listing Playbooks (sys_pd_process_definition)."""

    limit: int = Field(default=20, description="Maximum number of records (max 100)")
    offset: int = Field(default=0, description="Pagination offset")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    status: Optional[str] = Field(default=None, description="Filter by status")
    name: Optional[str] = Field(default=None, description="Filter by label/name (contains)")
    scope: Optional[str] = Field(default=None, description="Scope namespace to filter by")
    query: Optional[str] = Field(default=None, description="Additional encoded query")
    count_only: bool = Field(
        default=False, description="Return count only without fetching records."
    )


class GetPlaybookDetailParams(BaseModel):
    """Parameters for getting a single playbook."""

    playbook_id: str = Field(
        ..., description="Playbook sys_id from sys_pd_process_definition table"
    )


class ListDecisionTablesParams(BaseModel):
    """Parameters for listing Decision Tables (sys_decision)."""

    limit: int = Field(default=20, description="Maximum number of records (max 100)")
    offset: int = Field(default=0, description="Pagination offset")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    name: Optional[str] = Field(default=None, description="Filter by name (contains)")
    scope: Optional[str] = Field(default=None, description="Scope namespace to filter by")
    query: Optional[str] = Field(default=None, description="Additional encoded query")
    count_only: bool = Field(
        default=False, description="Return count only without fetching records."
    )


class GetDecisionTableDetailParams(BaseModel):
    """Parameters for getting a single decision table."""

    decision_table_id: str = Field(..., description="Decision table sys_id from sys_decision table")


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
    snapshots, _ = sn_query_page(
        config,
        auth_manager,
        table=FLOW_SNAPSHOT_TABLE,
        query=f"master_flow={flow_id}^ORsys_id={flow_id}",
        fields="sys_id,name,status",
        limit=5,
        offset=0,
        display_value=True,
    )
    # Prefer published snapshot
    for snap in snapshots:
        if snap.get("status") == "Published":
            return snap["sys_id"]
    # Fallback to first available
    return snapshots[0]["sys_id"] if snapshots else None


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
        response = auth_manager.make_request("GET", url)
        response.raise_for_status()
        data = response.json()
        if data and isinstance(data, dict):
            result = data.get("result", data)
            if result.get("id") or result.get("name"):
                return data
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------


@register_tool(
    name="list_flow_designers",
    params=ListFlowsParams,
    description="Search flows/subflows by name or scope. Use compare_flows to diff two results.",
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

    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.status:
        query_parts.append(f"status={params.status}")
    if params.name:
        query_parts.append(f"nameLIKE{params.name}")
    if params.scope:
        query_parts.append(f"sys_scope.scope={params.scope}")
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
    description="Get one flow's structure and triggers. For comparing two flows, use compare_flows instead.",
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

    try:
        # processflow API — only available with browser auth
        if (params.include_structure or params.include_triggers) and _is_browser_auth(config):
            pf_result = _try_processflow_api(config, auth_manager, flow_id)
            if pf_result:
                pf_data = pf_result.get("result", pf_result)
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
                    result["structure"] = _extract_processflow_structure(pf_result)
                if params.include_triggers:
                    result["triggers"] = pf_data.get("triggerInstances", [])
                return result

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

        result = {"success": True, "flow": flow}

        if params.include_triggers:
            result["triggers"] = _fetch_flow_triggers(config, auth_manager, flow_id)

        if params.include_structure:
            result["structure"] = _fetch_flow_structure(config, auth_manager, flow_id)

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
    # 1. Get subflow instances with raw sys_ids for reference resolution
    instances_raw, _ = sn_query_page(
        config,
        auth_manager,
        table=SUBFLOW_V2_TABLE,
        query=f"flow={snapshot_id}",
        fields="sys_id,name,order,position,ui_id,parent_ui_id,nesting_parent,subflow",
        limit=100,
        offset=0,
        display_value=False,
    )

    if not instances_raw:
        return {
            "subflow_bindings": [],
            "mismatch_summary": {"mismatch_count": 0, "mismatches": []},
        }

    # Also get display values for human-readable names
    instances_display, _ = sn_query_page(
        config,
        auth_manager,
        table=SUBFLOW_V2_TABLE,
        query=f"flow={snapshot_id}",
        fields="sys_id,name,order,ui_id,subflow",
        limit=100,
        offset=0,
        display_value=True,
    )
    display_map = {r["sys_id"]: r for r in instances_display}

    # 2. Batch-resolve snapshot references → master_flow
    snapshot_ids = list({inst.get("subflow", "") for inst in instances_raw if inst.get("subflow")})
    snapshot_map: Dict[str, Dict] = {}
    master_flow_ids: set = set()

    if snapshot_ids:
        snapshots_raw, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_SNAPSHOT_TABLE,
            query=f"sys_idIN{','.join(snapshot_ids)}",
            fields="sys_id,name,master_flow",
            limit=100,
            offset=0,
            display_value=False,
        )
        for s in snapshots_raw:
            snapshot_map[s["sys_id"]] = s
            if s.get("master_flow"):
                master_flow_ids.add(s["master_flow"])

        # Get display names for snapshots
        snapshots_display, _ = sn_query_page(
            config,
            auth_manager,
            table=FLOW_SNAPSHOT_TABLE,
            query=f"sys_idIN{','.join(snapshot_ids)}",
            fields="sys_id,name,master_flow",
            limit=100,
            offset=0,
            display_value=True,
        )
        for sd in snapshots_display:
            if sd["sys_id"] in snapshot_map:
                snapshot_map[sd["sys_id"]]["snapshot_display_name"] = sd.get("name", "")
                snapshot_map[sd["sys_id"]]["master_flow_display"] = sd.get("master_flow", "")

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
                    f"No snapshot found for flow {flow_id}. "
                    "The flow may not be published. "
                    "Use browser auth mode for unpublished flow structure via processflow API."
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
    description="Get flow execution history. Use after compare_flows to check runtime behavior.",
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
    description="Update a Flow Designer flow name, description, or active status by sys_id.",
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


@register_tool(
    name="activate_flow_designer",
    params=ActivateFlowDesignerParams,
    description="Set a Flow Designer flow to active state by sys_id.",
    serialization="json",
    return_type=dict,
)
def activate_flow_designer(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ActivateFlowDesignerParams,
) -> Dict[str, Any]:
    """Activate a Flow Designer flow by sys_id."""
    flow_id = params.flow_id
    data = {"active": "true"}

    try:
        url = f"{config.instance_url}/api/now/table/{FLOW_TABLE}/{flow_id}"
        response = auth_manager.make_request("PATCH", url, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table=FLOW_TABLE)
        return {
            "success": True,
            "flow": result.get("result", {}),
            "message": "Flow activated successfully",
        }
    except Exception as e:
        logger.error(f"Error activating flow designer: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="deactivate_flow_designer",
    params=DeactivateFlowDesignerParams,
    description="Set a Flow Designer flow to inactive state by sys_id.",
    serialization="json",
    return_type=dict,
)
def deactivate_flow_designer(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DeactivateFlowDesignerParams,
) -> Dict[str, Any]:
    """Deactivate a Flow Designer flow by sys_id."""
    flow_id = params.flow_id
    data = {"active": "false"}

    try:
        url = f"{config.instance_url}/api/now/table/{FLOW_TABLE}/{flow_id}"
        response = auth_manager.make_request("PATCH", url, json=data)
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table=FLOW_TABLE)
        return {
            "success": True,
            "flow": result.get("result", {}),
            "message": "Flow deactivated successfully",
        }
    except Exception as e:
        logger.error(f"Error deactivating flow designer: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="list_flow_triggers_by_table",
    params=ListFlowTriggersByTableParams,
    description="Find flow triggers for a table. Returns triggers with linked flow info.",
    serialization="json",
    return_type=dict,
)
def list_flow_triggers_by_table(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListFlowTriggersByTableParams,
) -> Dict[str, Any]:
    """List flow record triggers for a specific table, with linked flow details."""
    query_parts: List[str] = [f"table={params.table_name}"]
    if params.scope:
        query_parts.append(f"sys_scope.scope={params.scope}")

    query_string = "^".join(query_parts)

    try:
        triggers, total = sn_query_page(
            config,
            auth_manager,
            table=RECORD_TRIGGER_TABLE,
            query=query_string,
            fields="sys_id,table,remote_trigger_id,condition,sys_scope,sys_name",
            limit=min(params.limit, 200),
            offset=0,
            display_value=True,
        )

        # Look up linked flows via remote_trigger_id
        results: List[Dict[str, Any]] = []
        for trigger in triggers:
            entry: Dict[str, Any] = {"trigger": trigger}
            remote_id = trigger.get("remote_trigger_id", "")
            if remote_id:
                flows, _ = sn_query_page(
                    config,
                    auth_manager,
                    table=FLOW_TABLE,
                    query=f"sys_id={remote_id}",
                    fields="sys_id,name,status,active,trigger_type,sys_scope,description",
                    limit=1,
                    offset=0,
                    display_value=True,
                )
                entry["flow"] = flows[0] if flows else None
            else:
                entry["flow"] = None
            results.append(entry)

        return {
            "success": True,
            "table": params.table_name,
            "triggers": results,
            "count": len(results),
            "total": total if total is not None else len(results),
        }
    except Exception as e:
        logger.error(f"Error listing flow triggers by table: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Actions (sys_hub_action_type_definition)
# ---------------------------------------------------------------------------


@register_tool(
    name="list_actions",
    params=ListActionsParams,
    description="List Flow Designer action definitions. Use to find sys_ids for get_action_detail.",
    serialization="json",
    return_type=dict,
)
def list_actions(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListActionsParams,
) -> Dict[str, Any]:
    """List Flow Designer action type definitions."""
    query_parts: List[str] = []
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.name:
        query_parts.append(f"nameLIKE{params.name}")
    if params.scope:
        query_parts.append(f"sys_scope.scope={params.scope}")
    if params.query:
        query_parts.append(params.query)

    query_string = "^".join(query_parts) if query_parts else ""

    if params.count_only:
        count = sn_count(config, auth_manager, ACTION_TYPE_TABLE, query_string)
        return {"success": True, "count": count}

    try:
        records, total_count = sn_query_page(
            config,
            auth_manager,
            table=ACTION_TYPE_TABLE,
            query=query_string,
            fields="sys_id,name,description,active,sys_scope,sys_updated_on,sys_updated_by,status",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
        )
        return {
            "success": True,
            "actions": records,
            "count": len(records),
            "total": total_count if total_count is not None else len(records),
        }
    except Exception as e:
        logger.error(f"Error listing actions: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_action_detail",
    params=GetActionDetailParams,
    description="Get a single Flow Designer action definition by sys_id. Returns all fields. Use list_actions first to find the sys_id.",
    serialization="json",
    return_type=dict,
)
def get_action_detail(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetActionDetailParams,
) -> Dict[str, Any]:
    """Get action type definition detail by sys_id."""
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table=ACTION_TYPE_TABLE,
            query=f"sys_id={params.action_id}",
            fields="",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if not records:
            return {"success": False, "error": f"Action not found: {params.action_id}"}
        return {"success": True, "action": records[0]}
    except Exception as e:
        logger.error(f"Error getting action detail: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Playbooks (sys_pd_process_definition)
# ---------------------------------------------------------------------------


@register_tool(
    name="list_playbooks",
    params=ListPlaybooksParams,
    description="List Playbooks (process automation). Use to find sys_ids for get_playbook_detail.",
    serialization="json",
    return_type=dict,
)
def list_playbooks(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListPlaybooksParams,
) -> Dict[str, Any]:
    """List playbook definitions."""
    query_parts: List[str] = []
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.status:
        query_parts.append(f"status={params.status}")
    if params.name:
        query_parts.append(f"labelLIKE{params.name}")
    if params.scope:
        query_parts.append(f"sys_scope.scope={params.scope}")
    if params.query:
        query_parts.append(params.query)

    query_string = "^".join(query_parts) if query_parts else ""

    if params.count_only:
        count = sn_count(config, auth_manager, PLAYBOOK_TABLE, query_string)
        return {"success": True, "count": count}

    try:
        records, total_count = sn_query_page(
            config,
            auth_manager,
            table=PLAYBOOK_TABLE,
            query=query_string,
            fields="sys_id,label,description,active,sys_scope,status,sys_updated_on,sys_updated_by,sys_created_on",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
        )
        return {
            "success": True,
            "playbooks": records,
            "count": len(records),
            "total": total_count if total_count is not None else len(records),
        }
    except Exception as e:
        logger.error(f"Error listing playbooks: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_playbook_detail",
    params=GetPlaybookDetailParams,
    description="Get a single Playbook by sys_id. Returns all fields. Use list_playbooks first to find the sys_id.",
    serialization="json",
    return_type=dict,
)
def get_playbook_detail(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetPlaybookDetailParams,
) -> Dict[str, Any]:
    """Get playbook detail by sys_id."""
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table=PLAYBOOK_TABLE,
            query=f"sys_id={params.playbook_id}",
            fields="",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if not records:
            return {"success": False, "error": f"Playbook not found: {params.playbook_id}"}
        return {"success": True, "playbook": records[0]}
    except Exception as e:
        logger.error(f"Error getting playbook detail: {e}")
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Decision Tables (sys_decision)
# ---------------------------------------------------------------------------


@register_tool(
    name="list_decision_tables",
    params=ListDecisionTablesParams,
    description="List Decision Tables (sys_decision) used in Flow Designer for routing logic. Use to find decision table sys_ids.",
    serialization="json",
    return_type=dict,
)
def list_decision_tables(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListDecisionTablesParams,
) -> Dict[str, Any]:
    """List decision tables."""
    query_parts: List[str] = []
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.name:
        query_parts.append(f"nameLIKE{params.name}")
    if params.scope:
        query_parts.append(f"sys_scope.scope={params.scope}")
    if params.query:
        query_parts.append(params.query)

    query_string = "^".join(query_parts) if query_parts else ""

    if params.count_only:
        count = sn_count(config, auth_manager, DECISION_TABLE, query_string)
        return {"success": True, "count": count}

    try:
        records, total_count = sn_query_page(
            config,
            auth_manager,
            table=DECISION_TABLE,
            query=query_string,
            fields="sys_id,name,label,description,active,sys_scope,sys_updated_on,sys_updated_by",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
        )
        return {
            "success": True,
            "decision_tables": records,
            "count": len(records),
            "total": total_count if total_count is not None else len(records),
        }
    except Exception as e:
        logger.error(f"Error listing decision tables: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_decision_table_detail",
    params=GetDecisionTableDetailParams,
    description="Get a single Decision Table by sys_id. Returns all fields. Use list_decision_tables first to find the sys_id.",
    serialization="json",
    return_type=dict,
)
def get_decision_table_detail(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetDecisionTableDetailParams,
) -> Dict[str, Any]:
    """Get decision table detail by sys_id."""
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table=DECISION_TABLE,
            query=f"sys_id={params.decision_table_id}",
            fields="",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if not records:
            return {
                "success": False,
                "error": f"Decision table not found: {params.decision_table_id}",
            }
        return {"success": True, "decision_table": records[0]}
    except Exception as e:
        logger.error(f"Error getting decision table detail: {e}")
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
            "name": flow_data.get("name", ""),
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
    result: Dict[str, Any] = {
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


@register_tool(
    name="compare_flows",
    params=CompareFlowsParams,
    description="Compare two flows by name or sys_id. Diffs structure, subflow bindings, and triggers.",
    serialization="json",
    return_type=dict,
)
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
