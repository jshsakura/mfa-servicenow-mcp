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

import requests
from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FLOW_TABLE = "sys_hub_flow"
FLOW_SNAPSHOT_TABLE = "sys_hub_flow_snapshot"
ACTION_V2_TABLE = "sys_hub_action_instance_v2"
LOGIC_V2_TABLE = "sys_hub_flow_logic_instance_v2"
SUBFLOW_V2_TABLE = "sys_hub_sub_flow_instance_v2"
COMPONENT_TABLE = "sys_hub_flow_component"
FLOW_CONTEXT_TABLE = "sys_flow_context"
FLOW_INPUT_TABLE = "sys_hub_flow_input"
FLOW_OUTPUT_TABLE = "sys_hub_flow_output"
ACTION_INPUT_TABLE = "sys_hub_action_input"
ACTION_OUTPUT_TABLE = "sys_hub_action_output"
TRIGGER_TABLE = "sys_hub_trigger_instance"

# ---------------------------------------------------------------------------
# Parameter Models
# ---------------------------------------------------------------------------


class ListFlowsParams(BaseModel):
    """Parameters for listing Flow Designer flows."""

    limit: int = Field(20, description="Maximum number of records (max 100)")
    offset: int = Field(0, description="Pagination offset")
    active: Optional[bool] = Field(None, description="Filter by active status")
    status: Optional[str] = Field(None, description="Filter by status: Draft, Published, etc.")
    name: Optional[str] = Field(None, description="Filter by name (contains)")
    scope: Optional[str] = Field(None, description="Filter by application scope name")
    query: Optional[str] = Field(None, description="Additional encoded query")
    count_only: bool = Field(
        False,
        description="Return count only without fetching records.",
    )


class GetFlowDetailsParams(BaseModel):
    """Parameters for getting flow details."""

    flow_id: str = Field(..., description="Flow sys_id from sys_hub_flow table")


class GetFlowStructureParams(BaseModel):
    """Parameters for getting the full structure of a flow."""

    flow_id: str = Field(..., description="Flow sys_id from sys_hub_flow table")
    include_variables: bool = Field(
        False,
        description="Also fetch input/output variables for each action (slower but more detailed)",
    )


class GetFlowExecutionsParams(BaseModel):
    """Parameters for getting flow execution history."""

    flow_name: Optional[str] = Field(None, description="Flow name to search (contains match)")
    flow_id: Optional[str] = Field(None, description="Flow sys_id to filter executions")
    state: Optional[str] = Field(
        None,
        description="Filter by state: Complete, Waiting, Error, Cancelled, In Progress",
    )
    source_record: Optional[str] = Field(
        None, description="Filter by source record display value (contains)"
    )
    limit: int = Field(20, description="Maximum number of records (max 100)")
    offset: int = Field(0, description="Pagination offset")
    errors_only: bool = Field(
        False,
        description="Only return executions with errors",
    )


class GetFlowExecutionDetailParams(BaseModel):
    """Parameters for getting a single flow execution detail."""

    context_id: str = Field(..., description="sys_id from sys_flow_context")


class GetFlowTriggersParams(BaseModel):
    """Parameters for getting flow triggers."""

    flow_id: str = Field(..., description="Flow sys_id from sys_hub_flow table")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _api_get(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    table: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make a GET request to the ServiceNow Table API."""
    headers = auth_manager.get_headers()
    url = f"{server_config.instance_url}/api/now/table/{table}"
    response = auth_manager.make_request("GET", url, headers=headers, params=params or {})
    response.raise_for_status()
    return response.json()


def _api_get_raw(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    path: str,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Make a GET request to an arbitrary ServiceNow REST API path."""
    headers = auth_manager.get_headers()
    url = f"{server_config.instance_url}{path}"
    response = auth_manager.make_request("GET", url, headers=headers, params=params or {})
    response.raise_for_status()
    return response.json()


def _get_snapshot_id(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    flow_id: str,
) -> Optional[str]:
    """Get the published snapshot sys_id for a flow."""
    result = _api_get(
        auth_manager,
        server_config,
        FLOW_SNAPSHOT_TABLE,
        {
            "sysparm_query": f"master_flow={flow_id}^ORsys_id={flow_id}",
            "sysparm_fields": "sys_id,name,status",
            "sysparm_limit": 5,
            "sysparm_display_value": "true",
        },
    )
    snapshots = result.get("result", [])
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


# ---------------------------------------------------------------------------
# Tool Implementations
# ---------------------------------------------------------------------------


@register_tool(
    name="list_flow_designers",
    params=ListFlowsParams,
    description=(
        "List Flow Designer flows with optional filters. "
        "Returns flow name, status, active flag, scope, and trigger type."
    ),
    serialization="json",
    return_type=dict,
)
def list_flows(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """List Flow Designer flows."""
    if isinstance(params, ListFlowsParams):
        params = params.dict(exclude_none=True)

    query_parts: List[str] = []
    if params.get("active") is not None:
        query_parts.append(f"active={str(params['active']).lower()}")
    if params.get("status"):
        query_parts.append(f"status={params['status']}")
    if params.get("name"):
        query_parts.append(f"nameLIKE{params['name']}")
    if params.get("scope"):
        query_parts.append(f"sys_scopeLIKE{params['scope']}")
    if params.get("query"):
        query_parts.append(params["query"])

    query_string = "^".join(query_parts) if query_parts else ""

    if params.get("count_only"):
        from .sn_api import sn_count

        count = sn_count(server_config, auth_manager, FLOW_TABLE, query_string)
        return {"success": True, "count": count}

    try:
        qp: Dict[str, Any] = {
            "sysparm_limit": min(params.get("limit", 20), 100),
            "sysparm_offset": params.get("offset", 0),
            "sysparm_fields": "sys_id,name,status,active,trigger_type,sys_scope,sys_updated_on,sys_updated_by,description",
            "sysparm_display_value": "true",
        }
        if query_string:
            qp["sysparm_query"] = query_string

        result = _api_get(auth_manager, server_config, FLOW_TABLE, qp)
        flows = result.get("result", [])
        return {
            "success": True,
            "flows": flows,
            "count": len(flows),
            "total": int(result.get("result", [{}])[0].get("__total", 0) if flows else 0),
        }
    except requests.RequestException as e:
        logger.error(f"Error listing flows: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_flow_designer_detail",
    params=GetFlowDetailsParams,
    description=(
        "Get detailed information about a single Flow Designer flow "
        "including metadata, trigger type, scope, and description."
    ),
    serialization="json",
    return_type=dict,
)
def get_flow_details(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get flow details by sys_id."""
    if isinstance(params, GetFlowDetailsParams):
        params = params.dict(exclude_none=True)

    flow_id = params["flow_id"]

    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/{FLOW_TABLE}/{flow_id}"
        response = auth_manager.make_request(
            "GET",
            url,
            headers=headers,
            params={"sysparm_display_value": "true"},
        )
        response.raise_for_status()
        flow = response.json().get("result", {})

        # Also get trigger info
        trigger_result = _api_get(
            auth_manager,
            server_config,
            TRIGGER_TABLE,
            {
                "sysparm_query": f"flow={flow_id}",
                "sysparm_display_value": "true",
                "sysparm_limit": 5,
            },
        )
        triggers = trigger_result.get("result", [])

        # Get input/output variables
        inputs = _api_get(
            auth_manager,
            server_config,
            FLOW_INPUT_TABLE,
            {
                "sysparm_query": f"model.id={flow_id}",
                "sysparm_display_value": "true",
                "sysparm_limit": 50,
            },
        ).get("result", [])

        outputs = _api_get(
            auth_manager,
            server_config,
            FLOW_OUTPUT_TABLE,
            {
                "sysparm_query": f"model.id={flow_id}",
                "sysparm_display_value": "true",
                "sysparm_limit": 50,
            },
        ).get("result", [])

        return {
            "success": True,
            "flow": flow,
            "triggers": triggers,
            "inputs": inputs,
            "outputs": outputs,
        }
    except requests.RequestException as e:
        logger.error(f"Error getting flow details: {e}")
        return {"success": False, "error": str(e)}


def _try_flow_designer_api(
    auth_manager: AuthManager,
    server_config: ServerConfig,
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
            result = _api_get_raw(auth_manager, server_config, api_path)
            if result and "result" in result:
                return result
        except requests.RequestException:
            continue
    return None


@register_tool(
    name="get_flow_designer_structure",
    params=GetFlowStructureParams,
    description=(
        "Analyze the full structure of a Flow Designer flow. "
        "First tries the native Flow Designer API (/api/sn_flow/designer/) "
        "for complete detail including conditions and variable mappings, "
        "then falls back to Table API for basic structure. "
        "Returns actions, flow logic, subflow calls in execution order with nesting."
    ),
    serialization="json",
    return_type=dict,
)
def get_flow_structure(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get the full component tree of a flow."""
    if isinstance(params, GetFlowStructureParams):
        p = params
    else:
        p = GetFlowStructureParams(**params)

    flow_id = p.flow_id

    # ------------------------------------------------------------------
    # Strategy 1: Native Flow Designer API (full detail)
    # ------------------------------------------------------------------
    designer_result = _try_flow_designer_api(auth_manager, server_config, flow_id)
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
        snapshot_id = _get_snapshot_id(auth_manager, server_config, flow_id)
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
        actions_result = _api_get(
            auth_manager,
            server_config,
            ACTION_V2_TABLE,
            {
                "sysparm_query": f"flow={snapshot_id}",
                "sysparm_fields": "sys_id,name,order,action_type,position,nesting_parent,compilable_type",
                "sysparm_display_value": "true",
                "sysparm_limit": 100,
            },
        )
        actions = actions_result.get("result", [])
        for a in actions:
            a["component_type"] = "action"

        logic_result = _api_get(
            auth_manager,
            server_config,
            LOGIC_V2_TABLE,
            {
                "sysparm_query": f"flow={snapshot_id}",
                "sysparm_fields": "sys_id,name,order,type,position,nesting_parent,compilable_type",
                "sysparm_display_value": "true",
                "sysparm_limit": 100,
            },
        )
        logic_nodes = logic_result.get("result", [])
        for node in logic_nodes:
            node["component_type"] = "logic"

        subflows_result = _api_get(
            auth_manager,
            server_config,
            SUBFLOW_V2_TABLE,
            {
                "sysparm_query": f"flow={snapshot_id}",
                "sysparm_fields": "sys_id,name,order,position,nesting_parent,compilable_type",
                "sysparm_display_value": "true",
                "sysparm_limit": 100,
            },
        )
        subflows = subflows_result.get("result", [])
        for s in subflows:
            s["component_type"] = "subflow"

        # Merge all components
        all_components = actions + logic_nodes + subflows
        all_components.sort(key=lambda c: int(c.get("order", 0)))

        # Build tree
        tree = _build_component_tree(all_components)

        # Step 3: Optionally fetch variables for each action
        if p.include_variables and actions:
            for action in actions:
                aid = action["sys_id"]
                try:
                    inputs = _api_get(
                        auth_manager,
                        server_config,
                        ACTION_INPUT_TABLE,
                        {
                            "sysparm_query": f"model.id={aid}",
                            "sysparm_display_value": "true",
                            "sysparm_limit": 30,
                        },
                    ).get("result", [])
                    action["inputs"] = inputs

                    outputs = _api_get(
                        auth_manager,
                        server_config,
                        ACTION_OUTPUT_TABLE,
                        {
                            "sysparm_query": f"model.id={aid}",
                            "sysparm_display_value": "true",
                            "sysparm_limit": 30,
                        },
                    ).get("result", [])
                    action["outputs"] = outputs
                except Exception:
                    pass  # Variable fetch is optional

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
    except requests.RequestException as e:
        logger.error(f"Error getting flow structure: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_flow_designer_executions",
    params=GetFlowExecutionsParams,
    description=(
        "Get execution history for Flow Designer flows from sys_flow_context. "
        "Filter by flow name, state (Complete/Waiting/Error/Cancelled), "
        "source record, or errors only. Shows run time, error messages, and state."
    ),
    serialization="json",
    return_type=dict,
)
def get_flow_executions(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get flow execution history."""
    if isinstance(params, GetFlowExecutionsParams):
        params = params.dict(exclude_none=True)

    query_parts: List[str] = []

    if params.get("flow_name"):
        query_parts.append(f"nameLIKE{params['flow_name']}")
    if params.get("flow_id"):
        query_parts.append(f"flow={params['flow_id']}")
    if params.get("state"):
        query_parts.append(f"state={params['state']}")
    if params.get("source_record"):
        query_parts.append(f"source_recordLIKE{params['source_record']}")
    if params.get("errors_only"):
        query_parts.append("stateINError,Cancelled^ORerror_messageISNOTEMPTY")

    query_string = "^".join(query_parts) if query_parts else ""

    try:
        qp: Dict[str, Any] = {
            "sysparm_limit": min(params.get("limit", 20), 100),
            "sysparm_offset": params.get("offset", 0),
            "sysparm_fields": "sys_id,name,state,error_message,error_state,sys_created_on,source_table,source_record,run_time,flow",
            "sysparm_display_value": "true",
            "sysparm_query": (
                f"{query_string}^ORDERBYDESCsys_created_on"
                if query_string
                else "ORDERBYDESCsys_created_on"
            ),
        }

        result = _api_get(auth_manager, server_config, FLOW_CONTEXT_TABLE, qp)
        executions = result.get("result", [])

        return {
            "success": True,
            "executions": executions,
            "count": len(executions),
        }
    except requests.RequestException as e:
        logger.error(f"Error getting flow executions: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_flow_designer_execution_detail",
    params=GetFlowExecutionDetailParams,
    description=(
        "Get detailed information about a single flow execution including "
        "plan data, runtime, error details, and source record context."
    ),
    serialization="json",
    return_type=dict,
)
def get_flow_execution_detail(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get detailed info for a single flow execution."""
    if isinstance(params, GetFlowExecutionDetailParams):
        params = params.dict(exclude_none=True)

    context_id = params["context_id"]

    try:
        headers = auth_manager.get_headers()
        url = f"{server_config.instance_url}/api/now/table/{FLOW_CONTEXT_TABLE}/{context_id}"
        response = auth_manager.make_request(
            "GET",
            url,
            headers=headers,
            params={"sysparm_display_value": "true"},
        )
        response.raise_for_status()
        context = response.json().get("result", {})

        return {
            "success": True,
            "execution": context,
        }
    except requests.RequestException as e:
        logger.error(f"Error getting flow execution detail: {e}")
        return {"success": False, "error": str(e)}


@register_tool(
    name="get_flow_designer_triggers",
    params=GetFlowTriggersParams,
    description=(
        "Get trigger configuration for a Flow Designer flow. "
        "Shows what events/conditions start the flow (record created, updated, scheduled, etc.)."
    ),
    serialization="json",
    return_type=dict,
)
def get_flow_triggers(
    auth_manager: AuthManager,
    server_config: ServerConfig,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get triggers for a flow."""
    if isinstance(params, GetFlowTriggersParams):
        params = params.dict(exclude_none=True)

    flow_id = params["flow_id"]

    try:
        # Try both flow and snapshot
        snapshot_id = _get_snapshot_id(auth_manager, server_config, flow_id)

        query_parts = [f"flow={flow_id}"]
        if snapshot_id:
            query_parts.append(f"flow={snapshot_id}")
        query_string = "^OR".join(query_parts)

        result = _api_get(
            auth_manager,
            server_config,
            TRIGGER_TABLE,
            {
                "sysparm_query": query_string,
                "sysparm_display_value": "true",
                "sysparm_limit": 20,
            },
        )
        triggers = result.get("result", [])

        return {
            "success": True,
            "triggers": triggers,
            "count": len(triggers),
        }
    except requests.RequestException as e:
        logger.error(f"Error getting flow triggers: {e}")
        return {"success": False, "error": str(e)}
