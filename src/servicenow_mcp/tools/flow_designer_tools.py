"""
Flow Designer tools for the ServiceNow MCP server.

Provides read-only tools for analyzing Flow Designer flows:
- List/search flows
- Get flow structure (actions, logic, subflows with nesting)
- Get flow execution history from sys_flow_context
- Get action/logic detail with input/output variables
"""

import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import AuthType, ServerConfig

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

# Custom Action source retrieval (Action Designer).
# The internal Script-step body of a custom action does NOT live on the action
# definition/base/snapshot records — it is stored in sys_variable_value, keyed
# by the step instance. The structural chain (confirmed live):
#   sys_hub_action_type_definition (the action)
#     └─ sys_hub_step_instance WHERE action = <def sys_id>   (live edit = current source)
#           └─ sys_variable_value WHERE document='sys_hub_step_instance'
#                                   AND document_key=<step sys_id>   (value = plaintext body)
# sys_hub_step_instance.action also points at base sys_ids (master/latest snapshot)
# for published versions — include_versions surfaces those too.
ACTION_DEF_TABLE = "sys_hub_action_type_definition"
PLAYBOOK_DEF_TABLE = "sys_pd_process_definition"
DECISION_TABLE = "sys_decision"
STEP_INSTANCE_TABLE = "sys_hub_step_instance"

# Non-flow Workflow Studio tabs reachable through list (flow_type=...). Each is a
# distinct table, not sys_hub_flow — restoring list_actions/playbooks/decisions
# that the flow-designer consolidation folded away. result_key names the payload.
_NON_FLOW_LIST_TABLES: Dict[str, Tuple[str, str]] = {
    "action": (ACTION_DEF_TABLE, "actions"),
    "playbook": (PLAYBOOK_DEF_TABLE, "playbooks"),
    "decision": (DECISION_TABLE, "decisions"),
}
VARIABLE_VALUE_TABLE = "sys_variable_value"
# OOB "Script step" script-input variable. Used as the preferred selector for
# the script body; falls back to the longest variable value when a step is a
# different type (REST/Lookup/etc.) whose input variable differs.
SCRIPT_STEP_VAR_SYSID = "71aa7f6647032200b4fad7527c9a719b"
_MIN_SCRIPT_LEN = 40

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
    # 'flow' excludes subflows; 'subflow' = subflows only; 'all' = both;
    # action/playbook/decision = other Workflow Studio tabs (separate tables).
    # None (default) behaves like 'flow'.
    type: Optional[Literal["flow", "subflow", "all", "action", "playbook", "decision"]] = Field(
        default=None,
        description="flow (default) | subflow | all | action | playbook | decision.",
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
    summary_format: bool = Field(
        default=True,
        description="Compact tree+warnings+index (default). Set False only if raw JSON needed.",
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


def _summarize_node_inputs(node: Dict[str, Any]) -> Dict[str, str]:
    """Flatten a node's inputs into {name: value} preserving full values verbatim.

    When `value` and `displayValue` differ (raw pill vs. human label), keep both
    in the form ``"<value> / <displayValue>"`` — the UI shows both, so the
    summary should too. Never truncate.
    """
    flat: Dict[str, str] = {}
    for inp in node.get("inputs", []) or []:
        if not isinstance(inp, dict):
            continue
        name = inp.get("name") or ""
        if not name:
            continue
        value = inp.get("value")
        display = inp.get("displayValue")
        value_str = "" if value in (None, "") else str(value)
        display_str = "" if display in (None, "") else str(display)
        if value_str and display_str and value_str != display_str:
            flat[name] = f"{value_str} / {display_str}"
        elif value_str:
            flat[name] = value_str
        else:
            flat[name] = display_str
    return flat


class FlowSummaryIntegrityError(ValueError):
    """Raised when a flow structure cannot be summarized without data loss."""


def _build_action_row(node: Dict[str, Any], ui: str, depth: int) -> Dict[str, Any]:
    """Action row — keeps every semantically meaningful field, drops verbose IDs."""
    row: Dict[str, Any] = {
        "order": node.get("order", ""),
        "depth": depth,
        "kind": "ACTION",
        "ui_id": ui,
        "type": node.get("action_type_name") or "",
        "name": node.get("name") or "",
        "inputs": _summarize_node_inputs(node),
    }
    outputs = node.get("outputs") or []
    output_names = [o.get("name", "") for o in outputs if isinstance(o, dict) and o.get("name")]
    if output_names:
        row["outputs"] = output_names
    if node.get("internal_name"):
        row["internal_name"] = node["internal_name"]
    if node.get("deleted"):
        row["deleted"] = True
    if node.get("comment"):
        row["comment"] = node["comment"]
    return row


def _build_logic_row(node: Dict[str, Any], ui: str, depth: int) -> Dict[str, Any]:
    """Logic row — branching context, full condition verbatim."""
    row: Dict[str, Any] = {
        "order": node.get("order", ""),
        "depth": depth,
        "kind": "LOGIC",
        "ui_id": ui,
        "type": node.get("logic_type") or node.get("logic_name") or "",
        "label": node.get("condition_label") or "",
        "condition": node.get("condition") or "",
    }
    extra_inputs = {
        k: v
        for k, v in _summarize_node_inputs(node).items()
        if k not in ("condition_name", "condition")
    }
    if extra_inputs:
        row["other_inputs"] = extra_inputs
    if node.get("connected_to"):
        row["connected_to"] = node["connected_to"]
    if node.get("outputs_to_assign"):
        row["outputs_to_assign"] = node["outputs_to_assign"]
    return row


def _build_subflow_row(node: Dict[str, Any], ui: str, depth: int) -> Dict[str, Any]:
    """Subflow row — exposes sys_id + scope so caller can chain into the subflow."""
    row: Dict[str, Any] = {
        "order": node.get("order", ""),
        "depth": depth,
        "kind": "SUBFLOW",
        "ui_id": ui,
        "type": "Call Subflow",
        "name": node.get("subflow_name") or "",
        "subflow_sys_id": node.get("subflow_sys_id") or "",
        "inputs": _summarize_node_inputs(node),
    }
    if node.get("subflow_internal_name"):
        row["subflow_internal_name"] = node["subflow_internal_name"]
    if node.get("subflow_scope"):
        row["subflow_scope"] = node["subflow_scope"]
    return row


def _render_row_lines(row: Dict[str, Any]) -> List[str]:
    """Render a single tree row to one or more text lines (no truncation)."""
    indent = "  " * int(row.get("depth") or 0)
    order = row.get("order", "")
    kind = row.get("kind", "")
    marker = (
        f" ⚠orphan(parent={row['_orphan_missing_parent']})"
        if "_orphan_missing_parent" in row
        else ""
    )
    lines: List[str] = []
    if kind == "LOGIC":
        label = row.get("label") or row.get("type") or "logic"
        head = f"[{order}] {indent}LOGIC {row.get('type','')}: {label}{marker}"
        lines.append(head)
        if row.get("condition"):
            lines.append(f"     {indent}  cond= {row['condition']}")
        if row.get("connected_to"):
            lines.append(f"     {indent}  connected_to= {row['connected_to']}")
        if row.get("outputs_to_assign"):
            lines.append(f"     {indent}  outputs_to_assign= {row['outputs_to_assign']}")
        for k, v in (row.get("other_inputs") or {}).items():
            lines.append(f"     {indent}  {k}= {v}")
    elif kind == "SUBFLOW":
        scope_part = f", scope={row['subflow_scope']}" if row.get("subflow_scope") else ""
        internal_part = (
            f", internal={row['subflow_internal_name']}" if row.get("subflow_internal_name") else ""
        )
        head = (
            f"[{order}] {indent}SUBFLOW→ {row.get('name','')} "
            f"(sys_id={row.get('subflow_sys_id','')}{scope_part}{internal_part})"
            f"{marker}"
        )
        lines.append(head)
        for k, v in (row.get("inputs") or {}).items():
            lines.append(f"     {indent}  in.{k}= {v}")
    else:  # ACTION
        deleted_tag = " [DELETED]" if row.get("deleted") else ""
        head = (
            f"[{order}] {indent}ACTION {row.get('type','')}: "
            f"{row.get('name','')}{deleted_tag}{marker}"
        )
        lines.append(head)
        for k, v in (row.get("inputs") or {}).items():
            lines.append(f"     {indent}  in.{k}= {v}")
        if row.get("outputs"):
            lines.append(f"     {indent}  out= {','.join(row['outputs'])}")
        if row.get("internal_name"):
            lines.append(f"     {indent}  internal_name= {row['internal_name']}")
        if row.get("comment"):
            lines.append(f"     {indent}  // {row['comment']}")
    return lines


def _render_tree_text(
    tree: List[Dict[str, Any]],
    orphans: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    index: Dict[str, List[Dict[str, Any]]],
) -> str:
    """Compact text rendering — denser than JSON, never truncated.

    Sections:
      1. WARNINGS (sorted critical → low) — show first so reviewers see issues immediately
      2. INDEX — quick navigator: approvals / state_changes / subflows / branches
      3. TREE — canonical flat tree with full conditions and inputs
      4. ORPHANS — nodes with missing parents (preserved with full subtree)
    """
    sections: List[str] = []

    if warnings:
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_warnings = sorted(
            warnings, key=lambda w: severity_rank.get(w.get("severity", "low"), 3)
        )
        sections.append("=== WARNINGS ===")
        for w in sorted_warnings:
            ref = (
                f"[{w['order']}]"
                if w.get("order") not in (None, "")
                else f"(count={w.get('count','')})"
            )
            sections.append(f"  {w['severity'].upper():8} {w['code']:30} {ref}  {w['message']}")
        sections.append("")

    if any(index.values()):
        sections.append("=== INDEX ===")
        if index["approvals"]:
            sections.append(f"  Approvals ({len(index['approvals'])}):")
            for a in index["approvals"]:
                approver = a.get("approval_conditions") or a.get("approvers") or "(none)"
                sections.append(f"    [{a['order']}] {a['name']}  approver= {approver}")
        if index["state_changes"]:
            sections.append(f"  State changes ({len(index['state_changes'])}):")
            for s in index["state_changes"]:
                sections.append(
                    f"    [{s['order']}] {s.get('table_name','')} "
                    f"record={s.get('record','')} values={s.get('values','')}"
                )
        if index["subflow_calls"]:
            sections.append(f"  Subflows ({len(index['subflow_calls'])}):")
            for sf in index["subflow_calls"]:
                sections.append(
                    f"    [{sf['order']}] {sf['name']}  "
                    f"sys_id={sf['subflow_sys_id']}  scope={sf.get('subflow_scope','')}"
                )
        if index["branch_conditions"]:
            sections.append(f"  Branches ({len(index['branch_conditions'])}):")
            for b in index["branch_conditions"]:
                sections.append(f"    [{b['order']}] {b.get('type','')}  cond= {b['condition']}")
        sections.append("")

    sections.append("=== TREE ===")
    for row in tree:
        sections.extend(_render_row_lines(row))

    if orphans:
        sections.append("")
        sections.append("=== ORPHANS (missing parents) ===")
        for row in orphans:
            sections.extend(_render_row_lines(row))

    return "\n".join(sections)


def _detect_flow_warnings(
    tree: List[Dict[str, Any]],
    orphans: List[Dict[str, Any]],
    deleted_logic: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Mechanical config-error detection — surfaces obvious misconfigurations."""
    warnings: List[Dict[str, Any]] = []
    all_rows = tree + orphans

    # Sibling order collision: same depth+parent-stack with duplicate `order`
    # We approximate parent grouping by walking depth (consecutive same-depth peers).
    last_seen_at_depth: Dict[int, Dict[Any, Dict[str, Any]]] = {}
    current_branch_at_depth: Dict[int, int] = {}
    for row in all_rows:
        depth = int(row.get("depth") or 0)
        # Reset deeper buckets when we move back to a shallower depth
        for d in list(last_seen_at_depth.keys()):
            if d > depth:
                last_seen_at_depth.pop(d, None)
                current_branch_at_depth.pop(d, None)
        bucket = last_seen_at_depth.setdefault(depth, {})
        order_key = row.get("order")
        if order_key in bucket:
            warnings.append(
                {
                    "code": "DUPLICATE_SIBLING_ORDER",
                    "severity": "medium",
                    "order": order_key,
                    "ui_id": row.get("ui_id"),
                    "message": (
                        f"Duplicate order={order_key} at depth={depth} — "
                        "execution sequence is ambiguous."
                    ),
                }
            )
        else:
            bucket[order_key] = row

    for row in all_rows:
        kind = row.get("kind")
        order = row.get("order", "")
        ui_id = row.get("ui_id")
        if kind == "LOGIC":
            type_lower = (row.get("type") or "").lower()
            if type_lower in {"if", "else_if", "elseif", "while"} and not row.get("condition"):
                warnings.append(
                    {
                        "code": "EMPTY_LOGIC_CONDITION",
                        "severity": "high",
                        "order": order,
                        "ui_id": ui_id,
                        "message": (
                            f"{row.get('type')} branch has no condition — "
                            "always evaluates to default."
                        ),
                    }
                )
        elif kind == "ACTION":
            type_name = (row.get("type") or "").lower()
            inputs = row.get("inputs") or {}
            if type_name == "ask for approval":
                approval = inputs.get("approval_conditions") or inputs.get("approvers")
                if not approval:
                    warnings.append(
                        {
                            "code": "EMPTY_APPROVAL_CONDITIONS",
                            "severity": "critical",
                            "order": order,
                            "ui_id": ui_id,
                            "message": (
                                "Ask For Approval has no approver pill — "
                                "approval will fail at runtime."
                            ),
                        }
                    )
            elif type_name == "update record":
                if not inputs.get("record") and not inputs.get("table_name"):
                    warnings.append(
                        {
                            "code": "UPDATE_RECORD_NO_TARGET",
                            "severity": "high",
                            "order": order,
                            "ui_id": ui_id,
                            "message": "Update Record has no record/table_name input.",
                        }
                    )
                if not inputs.get("values") and not inputs.get("fields_values"):
                    warnings.append(
                        {
                            "code": "UPDATE_RECORD_NO_VALUES",
                            "severity": "medium",
                            "order": order,
                            "ui_id": ui_id,
                            "message": "Update Record has no values to set.",
                        }
                    )
        if "_orphan_missing_parent" in row:
            warnings.append(
                {
                    "code": "ORPHAN_NODE",
                    "severity": "high",
                    "order": order,
                    "ui_id": ui_id,
                    "message": (
                        f"Node references missing parent "
                        f"{row['_orphan_missing_parent']} — likely deleted."
                    ),
                }
            )

    if deleted_logic:
        warnings.append(
            {
                "code": "DELETED_LOGIC_PRESENT",
                "severity": "low",
                "count": len(deleted_logic),
                "message": (
                    f"{len(deleted_logic)} deleted_flow_logic_instances entries "
                    "exist — verify they are not still referenced."
                ),
            }
        )
    return warnings


def _build_summary_index(
    tree: List[Dict[str, Any]],
    orphans: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Navigator index — quick lookup for approvals, state changes, subflows, branches."""
    approvals: List[Dict[str, Any]] = []
    state_changes: List[Dict[str, Any]] = []
    subflow_calls: List[Dict[str, Any]] = []
    branch_conditions: List[Dict[str, Any]] = []

    for row in tree + orphans:
        kind = row.get("kind")
        order = row.get("order", "")
        ui_id = row.get("ui_id")
        depth = row.get("depth", 0)
        if kind == "ACTION":
            type_name = (row.get("type") or "").lower()
            inputs = row.get("inputs") or {}
            if type_name == "ask for approval":
                approvals.append(
                    {
                        "order": order,
                        "ui_id": ui_id,
                        "depth": depth,
                        "name": row.get("name", ""),
                        "approval_conditions": inputs.get("approval_conditions", ""),
                        "approvers": inputs.get("approvers", ""),
                        "due_date": inputs.get("due_date", ""),
                        "wait_for_completion": inputs.get("wait_for_completion", ""),
                    }
                )
            elif type_name == "update record":
                state_changes.append(
                    {
                        "order": order,
                        "ui_id": ui_id,
                        "depth": depth,
                        "name": row.get("name", ""),
                        "record": inputs.get("record", ""),
                        "table_name": inputs.get("table_name", ""),
                        "values": inputs.get("values", "") or inputs.get("fields_values", ""),
                    }
                )
        elif kind == "SUBFLOW":
            subflow_calls.append(
                {
                    "order": order,
                    "ui_id": ui_id,
                    "depth": depth,
                    "name": row.get("name", ""),
                    "subflow_sys_id": row.get("subflow_sys_id", ""),
                    "subflow_internal_name": row.get("subflow_internal_name", ""),
                    "subflow_scope": row.get("subflow_scope", ""),
                }
            )
        elif kind == "LOGIC" and row.get("condition"):
            branch_conditions.append(
                {
                    "order": order,
                    "ui_id": ui_id,
                    "depth": depth,
                    "type": row.get("type", ""),
                    "label": row.get("label", ""),
                    "condition": row.get("condition", ""),
                }
            )
    return {
        "approvals": approvals,
        "state_changes": state_changes,
        "subflow_calls": subflow_calls,
        "branch_conditions": branch_conditions,
    }


def _build_flow_summary(structure: Dict[str, Any]) -> Dict[str, Any]:
    """Flat tree summary (depth + full conditions) for analysis use cases.

    Works on processflow-shape structure (actions/logic/subflows with parent_ui_id).
    Conditions and input values are preserved verbatim (no truncation).

    Correctness guarantees:
    - Every input node with a ui_id appears exactly once in `tree` or `orphans`.
    - Nodes with no ui_id are reported in `dropped_no_ui_id` (never silently lost).
    - A child whose parent_ui_id is unknown becomes an orphan-root, marked with
      `_orphan_missing_parent`; its descendants keep their normal (non-marked) rows.
    - Duplicate ui_id and cycles raise FlowSummaryIntegrityError instead of
      producing partial output.
    - `integrity.input_total_with_ui_id == len(tree) + len(orphans)` always holds.
    """
    actions = structure.get("actions", []) or []
    logic = structure.get("logic", []) or []
    subflows = structure.get("subflows", []) or []
    deleted_logic = structure.get("deleted_flow_logic_instances", []) or []

    nodes_by_ui: Dict[str, Dict[str, Any]] = {}
    duplicate_ui_ids: List[str] = []
    dropped_no_ui_id: List[Dict[str, Any]] = []

    def _ingest(items: List[Dict[str, Any]], kind: str) -> None:
        for item in items:
            ui = item.get("ui_id") or ""
            if not ui:
                dropped_no_ui_id.append(
                    {
                        "kind": kind,
                        "order": item.get("order", ""),
                        "name": item.get("name")
                        or item.get("logic_name")
                        or item.get("subflow_name")
                        or "",
                    }
                )
                continue
            if ui in nodes_by_ui:
                duplicate_ui_ids.append(ui)
                continue
            nodes_by_ui[ui] = {**item, "_kind": kind}

    _ingest(actions, "ACTION")
    _ingest(logic, "LOGIC")
    _ingest(subflows, "SUBFLOW")

    if duplicate_ui_ids:
        raise FlowSummaryIntegrityError(
            f"duplicate ui_id(s) across actions/logic/subflows: {duplicate_ui_ids[:5]}"
        )

    children_by_parent: Dict[str, List[str]] = {}
    for ui, node in nodes_by_ui.items():
        parent = node.get("parent_ui_id") or ""
        children_by_parent.setdefault(parent, []).append(ui)
    for siblings in children_by_parent.values():
        siblings.sort(key=lambda u: _safe_int(nodes_by_ui[u].get("order")))

    def _row(ui: str, depth: int) -> Dict[str, Any]:
        node = nodes_by_ui[ui]
        kind = node["_kind"]
        if kind == "LOGIC":
            return _build_logic_row(node, ui, depth)
        if kind == "SUBFLOW":
            return _build_subflow_row(node, ui, depth)
        return _build_action_row(node, ui, depth)

    visited: set = set()

    def _walk(ui: str, depth: int, path: List[str], dest: List[Dict[str, Any]]) -> None:
        if ui in path:
            raise FlowSummaryIntegrityError(f"cycle detected: {' -> '.join(path + [ui])}")
        visited.add(ui)
        dest.append(_row(ui, depth))
        next_path = path + [ui]
        for child_ui in children_by_parent.get(ui, []):
            _walk(child_ui, depth + 1, next_path, dest)

    tree: List[Dict[str, Any]] = []
    for root_ui in children_by_parent.get("", []):
        _walk(root_ui, 0, [], tree)

    orphans: List[Dict[str, Any]] = []
    orphan_roots = sorted(
        (
            ui
            for ui, node in nodes_by_ui.items()
            if (node.get("parent_ui_id") or "") not in {"", *nodes_by_ui.keys()}
            and ui not in visited
        ),
        key=lambda u: _safe_int(nodes_by_ui[u].get("order")),
    )
    for orphan_ui in orphan_roots:
        before = len(orphans)
        _walk(orphan_ui, 0, [], orphans)
        orphans[before]["_orphan_missing_parent"] = nodes_by_ui[orphan_ui].get("parent_ui_id") or ""

    unreachable = [ui for ui in nodes_by_ui if ui not in visited]
    if unreachable:
        raise FlowSummaryIntegrityError(
            f"{len(unreachable)} node(s) unreachable from any root: {unreachable[:5]}"
        )

    warnings = _detect_flow_warnings(tree, orphans, deleted_logic)
    index = _build_summary_index(tree, orphans)

    summary: Dict[str, Any] = {
        "tree": tree,
        "summary_index": index,
        "warnings": warnings,
        "counts": {
            "actions": len(actions),
            "logic": len(logic),
            "subflows": len(subflows),
            "deleted_flow_logic_instances": len(deleted_logic),
            "approvals": len(index["approvals"]),
            "state_changes": len(index["state_changes"]),
            "subflow_calls": len(index["subflow_calls"]),
            "branch_conditions": len(index["branch_conditions"]),
        },
        "integrity": {
            "input_total_with_ui_id": len(nodes_by_ui),
            "tree_nodes": len(tree),
            "orphan_nodes": len(orphans),
            "dropped_no_ui_id": len(dropped_no_ui_id),
        },
    }
    if orphans:
        summary["orphans"] = orphans
    if dropped_no_ui_id:
        summary["dropped_no_ui_id"] = dropped_no_ui_id
    if deleted_logic:
        # Surface deleted-but-still-referenced logic so analyzers don't miss
        # silent dependencies. Keep raw entries — they may explain orphan parents.
        summary["deleted_flow_logic_instances"] = deleted_logic
    summary["tree_text"] = _render_tree_text(tree, orphans, warnings, index)
    return summary


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


def _list_non_flow_definitions(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListFlowsParams,
    table: str,
    result_key: str,
) -> Dict[str, Any]:
    """List a non-flow Workflow Studio surface (actions/playbooks/decisions).

    These live in their own tables (not sys_hub_flow), so rows come back under
    result_key (not "flows"). Same filters (active/name/scope/query/count_only)
    apply; the flow-only type!=subflow filter is omitted. Restores the
    list_actions/playbooks/decisions tools the flow-designer consolidation dropped.
    """
    query_parts: List[str] = []
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
        count = sn_count(config, auth_manager, table, query_string)
        return {"success": True, "count": count}

    try:
        rows, total_count = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query_string,
            fields="sys_id,name,status,active,sys_scope,sys_updated_on,sys_updated_by,description",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
        )
        return {
            "success": True,
            result_key: rows,
            "count": len(rows),
            "total": total_count if total_count is not None else len(rows),
        }
    except Exception as e:
        logger.error(f"Error listing {result_key}: {e}")
        return {"success": False, "error": str(e)}


def list_flows(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListFlowsParams,
) -> Dict[str, Any]:
    """List Flow Designer flows, subflows, or custom action definitions."""
    flow_type = (params.type or "flow").lower()

    # Actions/playbooks/decisions are separate Workflow Studio tabs in their own
    # tables (NOT sys_hub_flow) — branch to their own query. Restores the
    # list_actions/playbooks/decisions discovery the consolidation folded away.
    if flow_type in _NON_FLOW_LIST_TABLES:
        table, result_key = _NON_FLOW_LIST_TABLES[flow_type]
        return _list_non_flow_definitions(config, auth_manager, params, table, result_key)

    query_parts: List[str] = []

    # Type filter: flow (default), subflow, all
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
                    result["structure"] = (
                        _build_flow_summary(detail) if params.summary_format else detail
                    )
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
            if params.summary_format and structure.get("success") and "actions" in structure:
                result["structure"] = _build_flow_summary(structure)
            else:
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


# ---------------------------------------------------------------------------
# Custom Action source retrieval (read-only)
# ---------------------------------------------------------------------------


class GetActionSourceParams(BaseModel):
    """Read a custom Flow Designer action's step source (scripts)."""

    action_ref: str = Field(
        ..., description="Action sys_id, name, or internal_name (sys_hub_action_type_definition)"
    )
    include_versions: bool = Field(
        default=False, description="Also return published-snapshot step versions, not just live"
    )
    limit: int = Field(default=50, description="Max step instances to read")


def _looks_like_sys_id(value: str) -> bool:
    """True when *value* is a 32-char lowercase-hex sys_id."""
    if len(value) != 32:
        return False
    return all(c in "0123456789abcdef" for c in value.lower())


def _resolve_action_definition(
    config: ServerConfig, auth_manager: AuthManager, action_ref: str
) -> Optional[Dict[str, Any]]:
    """Resolve an action_ref (sys_id|internal_name|name) to its definition row."""
    ref = action_ref.strip()
    fields = "sys_id,name,internal_name,master_snapshot,latest_snapshot,sys_scope"

    if _looks_like_sys_id(ref):
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=ACTION_DEF_TABLE,
            query=f"sys_id={ref}",
            fields=fields,
            limit=1,
            offset=0,
        )
        if rows:
            return rows[0]

    # Exact internal_name / name, then contains-match as a last resort.
    for query in (
        f"internal_name={ref}^ORname={ref}",
        f"nameLIKE{ref}^ORinternal_nameLIKE{ref}",
    ):
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=ACTION_DEF_TABLE,
            query=query,
            fields=fields,
            limit=5,
            offset=0,
        )
        if rows:
            return rows[0]
    return None


def _extract_step_script(variables: List[Dict[str, str]]) -> str:
    """Pick the script body from a step's variable rows.

    Prefer the OOB Script-step script variable; otherwise fall back to the
    longest value (covers non-Script steps whose input variable differs).
    """
    for row in variables:
        if str(row.get("variable") or "") == SCRIPT_STEP_VAR_SYSID:
            return str(row.get("value") or "")
    longest = ""
    for row in variables:
        value = str(row.get("value") or "")
        if len(value) > len(longest):
            longest = value
    return longest if len(longest) >= _MIN_SCRIPT_LEN else ""


def get_action_source(
    config: ServerConfig, auth_manager: AuthManager, params: GetActionSourceParams
) -> Dict[str, Any]:
    """Return the step scripts of a custom Flow Designer action (read-only).

    Surfaces what Action Designer's UI shows but no source/metadata tool covers:
    the real Script-step body, read from sys_variable_value via the step chain.
    """
    try:
        definition = _resolve_action_definition(config, auth_manager, params.action_ref)
        if not definition:
            return {"success": False, "error": f"Action not found: {params.action_ref}"}

        def_sys_id = str(definition.get("sys_id") or "")
        # Live source = steps whose action is the definition itself. Optionally
        # add the published snapshots (base sys_ids on the definition).
        action_refs = [def_sys_id]
        if params.include_versions:
            for key in ("master_snapshot", "latest_snapshot"):
                snap = str(definition.get(key) or "")
                if snap and snap not in action_refs:
                    action_refs.append(snap)

        step_rows, _ = sn_query_page(
            config,
            auth_manager,
            table=STEP_INSTANCE_TABLE,
            query="action=" + "^ORaction=".join(action_refs),
            fields="sys_id,label,order,step_type,action",
            limit=params.limit,
            offset=0,
            orderby="order",
        )

        steps: List[Dict[str, Any]] = []
        for step in step_rows:
            step_sys_id = str(step.get("sys_id") or "")
            if not step_sys_id:
                continue
            var_rows, _ = sn_query_page(
                config,
                auth_manager,
                table=VARIABLE_VALUE_TABLE,
                query=f"document={STEP_INSTANCE_TABLE}^document_key={step_sys_id}",
                fields="variable,value",
                limit=100,
                offset=0,
            )
            variables = [
                {"variable": str(r.get("variable") or ""), "value": str(r.get("value") or "")}
                for r in var_rows
            ]
            steps.append(
                {
                    "sys_id": step_sys_id,
                    "label": str(step.get("label") or ""),
                    "order": _safe_int(step.get("order")),
                    "step_type": str(step.get("step_type") or ""),
                    "action_ref": str(step.get("action") or ""),
                    "is_live": str(step.get("action") or "") == def_sys_id,
                    "script": _extract_step_script(variables),
                    "variables": variables,
                }
            )

        return {
            "success": True,
            "action": {
                "sys_id": def_sys_id,
                "name": str(definition.get("name") or ""),
                "internal_name": str(definition.get("internal_name") or ""),
                "scope": str(definition.get("sys_scope") or ""),
                "master_snapshot": str(definition.get("master_snapshot") or ""),
                "latest_snapshot": str(definition.get("latest_snapshot") or ""),
            },
            "step_count": len(steps),
            "steps": steps,
            "note": (
                "Live source = steps where is_live=true (action == definition). "
                "Creation/copy of actions is not supported via API — recreate in "
                "Action Designer using this source."
            ),
        }
    except Exception as e:  # noqa: BLE001
        logger.error("Error reading action source: %s", e)
        return {"success": False, "error": str(e)}
