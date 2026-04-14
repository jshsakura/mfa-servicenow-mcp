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
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .sn_api import sn_count, sn_query_page

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
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    status: Optional[str] = Field(
        default=None, description="Filter by status: Draft, Published, etc."
    )
    name: Optional[str] = Field(default=None, description="Filter by name (contains)")
    scope: Optional[str] = Field(default=None, description="Filter by application scope name")
    query: Optional[str] = Field(default=None, description="Additional encoded query")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records.",
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _try_flow_designer_api(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
) -> Optional[Dict[str, Any]]:
    """Try the native Flow Designer REST API (/api/sn_flow/designer/flows/{id}).

    Returns the full flow definition if available, None if the API is not present.
    """
    for api_path in [
        f"/api/sn_flow/designer/flows/{flow_id}",
        f"/api/sn_fd/designer/flows/{flow_id}",
    ]:
        try:
            url = f"{config.instance_url}{api_path}"
            response = auth_manager.make_request("GET", url)
            response.raise_for_status()
            result = response.json()
            if result and "result" in result:
                return result
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------


@register_tool(
    name="list_flow_designers",
    params=ListFlowsParams,
    description="List Flow Designer flows with optional filters. Returns name, status, scope, and trigger type.",
    serialization="json",
    return_type=dict,
)
def list_flows(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListFlowsParams,
) -> Dict[str, Any]:
    """List Flow Designer flows."""
    query_parts: List[str] = []
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.status:
        query_parts.append(f"status={params.status}")
    if params.name:
        query_parts.append(f"nameLIKE{params.name}")
    if params.scope:
        query_parts.append(f"sys_scopeLIKE{params.scope}")
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
    description="Get a single Flow Designer flow by sys_id. Optionally include structure tree and trigger config.",
    serialization="json",
    return_type=dict,
)
def get_flow_details(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetFlowDetailsParams,
) -> Dict[str, Any]:
    """Get flow details by sys_id, optionally including structure and triggers."""
    flow_id = params.flow_id

    try:
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

        result: Dict[str, Any] = {"success": True, "flow": flow}

        if params.include_triggers:
            result["triggers"] = _fetch_flow_triggers(config, auth_manager, flow_id)

        if params.include_structure:
            result["structure"] = _fetch_flow_structure(config, auth_manager, flow_id)

        return result
    except Exception as e:
        logger.error(f"Error getting flow details: {e}")
        return {"success": False, "error": str(e)}


def _fetch_flow_structure(
    config: ServerConfig,
    auth_manager: AuthManager,
    flow_id: str,
) -> Dict[str, Any]:
    """Get the full component tree of a flow (internal helper)."""

    # ------------------------------------------------------------------
    # Strategy 1: Native Flow Designer API (full detail)
    # ------------------------------------------------------------------
    designer_result = _try_flow_designer_api(config, auth_manager, flow_id)
    if designer_result:
        return {
            "success": True,
            "source": "flow_designer_api",
            "flow_id": flow_id,
            "data": designer_result.get("result", designer_result),
        }

    # ------------------------------------------------------------------
    # Strategy 2: Table API fallback (structure only)
    # ------------------------------------------------------------------
    try:
        # Step 1: Find the published snapshot
        snapshot_id = _get_snapshot_id(config, auth_manager, flow_id)
        if not snapshot_id:
            return {
                "success": False,
                "error": (
                    f"No snapshot found for flow {flow_id}. "
                    "The flow may not be published. "
                    "Also, the native Flow Designer API (/api/sn_flow/designer/) "
                    "was not available on this instance."
                ),
            }

        # Step 2: Get all components via v2 tables using snapshot_id
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

        # Merge all components
        all_components = actions + logic_nodes + subflows
        all_components.sort(key=lambda c: int(c.get("order", 0)))

        # Build tree
        tree = _build_component_tree(all_components)

        # Flat summary for quick reading
        flat_summary = []
        for comp in all_components:
            entry = {
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

        return {
            "success": True,
            "source": "table_api_fallback",
            "flow_id": flow_id,
            "snapshot_id": snapshot_id,
            "total_actions": len(actions),
            "total_logic": len(logic_nodes),
            "total_subflows": len(subflows),
            "note": (
                "Retrieved via Table API. Conditions and variable mappings may be incomplete. "
                "The native Flow Designer API was not available on this instance."
            ),
            "flat_summary": flat_summary,
            "tree": tree,
        }
    except Exception as e:
        logger.error(f"Error getting flow structure: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_flow_designer_executions",
    params=GetFlowExecutionsParams,
    description="Get flow execution history or single execution detail. Filter by name, state, or errors.",
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
