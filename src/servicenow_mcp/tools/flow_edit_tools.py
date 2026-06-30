"""Flow Designer edit tools — checkout / patch / save."""

import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from .flow_designer_tools import (
    _condition_to_text,
    _decode_condition,
    _encode_condition,
    _is_browser_auth,
    _try_processflow_api,
    render_flow_compact,
)

logger = logging.getLogger(__name__)

_CHECKOUT_DIR = Path(tempfile.gettempdir())
_PF_BASE = "/api/now/processflow/flow"
_PF_HEADERS = {"x-transaction-source": "Interface=Web"}

# Write-path headers captured 1:1 from the real Flow Designer UI (see
# FLOW_TOOL_NETWORK_BASELINE.md). The stock _PF_HEADERS used for reads is too
# thin for save/publish — the UI sends a richer x-transaction-source plus a
# Referer and Accept. Cookie / X-UserToken / Content-Type are added downstream
# by make_request (_apply_browser_session_headers) and the json= body.
_PF_WRITE_TRANSACTION_SOURCE = (
    "Interface=Web,Interface-Type=Classic Environment,Interface-Name=Core UI"
)


def _pf_write_headers(config: ServerConfig) -> Dict[str, str]:
    return {
        "x-transaction-source": _PF_WRITE_TRANSACTION_SOURCE,
        "Referer": f"{config.instance_url}/$flow-designer.do?sysparm_nostack=true",
        "Accept": "application/json",
        "x-wantsessionnotificationmessages": "true",
    }


def _flow_scope(flow_data: Dict[str, Any]) -> Optional[str]:
    """sysparm_transaction_scope the UI sends on every flow-edit write — it is
    the flow's application sys_scope sys_id, carried on the flow payload itself
    (no separate concoursepicker call needed)."""
    scope = flow_data.get("scope")
    return scope if isinstance(scope, str) and scope else None


def _create_version(
    auth_manager: AuthManager,
    config: ServerConfig,
    flow_id: str,
    scope: str,
    version_type: str = "Save",
) -> None:
    """Best-effort version row the UI creates around a save/publish. Not fatal
    if it fails — the PUT/snapshot is what actually persists; this just mirrors
    the UI so version history stays consistent."""
    try:
        auth_manager.make_request(
            "POST",
            f"{config.instance_url}{_PF_BASE.rsplit('/', 1)[0]}/versioning/create_version",
            params={"sysparm_transaction_scope": scope},
            headers=_pf_write_headers(config),
            json={
                "item_sys_id": flow_id,
                "type": version_type,
                "annotation": "",
                "favorite": False,
            },
        )
    except Exception as e:  # noqa: BLE001 — version row is non-critical
        logger.warning("create_version (%s) failed for %s: %s", version_type, flow_id, e)


_PF_API_BASE = "/api/now/processflow"
_PF_ACTION_BASE = f"{_PF_API_BASE}/action/action_types"


def _pf_get_json(auth_manager: AuthManager, url: str) -> Dict[str, Any]:
    """GET a processflow endpoint and unwrap the standard {result:{data}}
    envelope. Raises on transport error; returns {} on a non-dict body."""
    resp = auth_manager.make_request("GET", url, headers=_PF_HEADERS)
    resp.raise_for_status()
    raw = resp.json()
    if not isinstance(raw, dict):
        return {}
    result = raw.get("result")
    outer: Dict[str, Any] = result if isinstance(result, dict) else raw
    data = outer.get("data")
    if isinstance(data, dict) and data:
        return data
    return outer


def _try_processflow_action(
    config: ServerConfig, auth_manager: AuthManager, action_id: str
) -> Dict[str, Any]:
    """Fetch a CUSTOM Action type the way the Action Designer does: the type
    definition (inputs/outputs/meta) plus its internal step_instances (Script
    step bodies etc.). Returns {"action": {...}, "steps": {...}} or {"_error"}.
    """
    try:
        action = _pf_get_json(auth_manager, f"{config.instance_url}{_PF_ACTION_BASE}/{action_id}")
        if not action:
            return {"_error": f"No action type data for {action_id}"}
        err = action.get("errorMessage")
        if err:
            return {"_error": err}
        steps = _pf_get_json(
            auth_manager,
            f"{config.instance_url}{_PF_ACTION_BASE}/{action_id}/step_instances",
        )
        return {"action": action, "steps": steps}
    except Exception as e:  # noqa: BLE001
        logger.error("processflow action fetch failed for %s: %s", action_id, e)
        return {"_error": str(e)}


def _copy_flow(
    config: ServerConfig,
    auth_manager: AuthManager,
    source_id: str,
    new_name: str,
    scope: Optional[str] = None,
) -> Dict[str, Any]:
    """Native flow/subflow clone — the exact call Workflow Studio's "Copy flow"
    makes. The server remaps every instance sys_id and snapshots; we just POST
    name+scope. Returns {success, new_flow_id, new_name} ({new_flow_id} is the
    server-assigned sys_id from result.data)."""
    if not scope:
        rows = _table_lookup(
            config, auth_manager, _FLOW_DEF_TABLE, f"sys_id={source_id}", fields="sys_id,sys_scope"
        )
        raw_scope = rows[0].get("sys_scope") if rows else None
        # Table API may return a reference as a {"value": ...} dict.
        scope = raw_scope.get("value") if isinstance(raw_scope, dict) else raw_scope
    if not scope:
        return {"success": False, "error": "Could not resolve source flow scope for copy."}
    try:
        resp = auth_manager.make_request(
            "POST",
            f"{config.instance_url}{_PF_BASE}/{source_id}/copy",
            params={"sysparm_transaction_scope": scope},
            headers=_pf_write_headers(config),
            json={"name": new_name, "scope": scope},
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Copy failed: {e}"}
    outer = raw.get("result", raw) if isinstance(raw, dict) else {}
    if isinstance(outer, dict) and outer.get("errorMessage"):
        return {"success": False, "error": outer["errorMessage"]}
    new_id = outer.get("data") if isinstance(outer, dict) else None
    if not new_id:
        return {
            "success": False,
            "error": "Copy returned no new flow sys_id.",
            "raw": str(raw)[:300],
        }
    return {
        "success": True,
        "action": "copy",
        "source_id": source_id,
        "new_flow_id": new_id,
        "new_name": new_name,
    }


def _manual_publish_response(config: ServerConfig, flow_id: str) -> Dict[str, Any]:
    """Publish (snapshot recompile) is NOT programmatically reachable. Proven
    exhaustively (see FLOW_TOOL_NETWORK_BASELINE.md): the recompile is gated
    behind the interactive Workflow Studio editor — every API path (curl_cffi
    POST /snapshot, with/without edit-flow GET priming, and even a
    cookie-injected headless browser fetch) fast-fails 500 in ~20-280ms because
    the server-side 'working copy' is only created when a human enters edit mode
    in the SPA. So publish is the one manual step: open the flow and click
    Activate / Publish. Everything else (read/edit/save/copy/activate-toggle) is
    automated."""
    return {
        "success": False,
        "published": False,
        "manual_publish_required": True,
        "ui_url": f"{config.instance_url}/now/wsd/flow-designer/{flow_id}",
        "message": (
            "Snapshot recompile (publish) is gated behind the interactive Flow "
            "Designer editor and cannot be done via API. Open the flow in "
            "Workflow Studio and click Activate/Publish. (Design-time changes are "
            "already saved; this only recompiles the runtime snapshot.)"
        ),
    }


def _toggle_active(
    config: ServerConfig, auth_manager: AuthManager, flow_id: str, scope: str, activate: bool
) -> Dict[str, Any]:
    """Activate/deactivate an ALREADY-published flow — a plain toggle, NO
    recompile. Captured 1:1: GET /flow/{id}/activate|deactivate then
    create_version 'Activate'|'Deactivate'."""
    verb = "activate" if activate else "deactivate"
    try:
        resp = auth_manager.make_request(
            "GET",
            f"{config.instance_url}{_PF_BASE}/{flow_id}/{verb}",
            params={"sysparm_transaction_scope": scope},
            headers=_pf_write_headers(config),
        )
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"{verb} failed: {e}"}
    _create_version(auth_manager, config, flow_id, scope, "Activate" if activate else "Deactivate")
    return {"success": True, "action": verb, "active": activate}


_HEX32 = re.compile(r"^[0-9a-f]{32}$")

# Workflow Studio surfaces and the table each lives in, for name/id resolution.
_FLOW_DEF_TABLE = "sys_hub_flow"
_ACTION_DEF_TABLE = "sys_hub_action_type_definition"
_DECISION_TABLE = "sys_decision"


def _table_lookup(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str = "sys_id,name,type",
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Small Table API GET used to resolve a name/sys_id to a concrete record."""
    try:
        resp = auth_manager.make_request(
            "GET",
            f"{config.instance_url}/api/now/table/{table}",
            params={
                "sysparm_query": query,
                "sysparm_fields": fields,
                "sysparm_limit": str(limit),
            },
        )
        resp.raise_for_status()
        result = resp.json().get("result", [])
        return result if isinstance(result, list) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("table lookup %s '%s' failed: %s", table, query, e)
        return []


def _resolve_target(config: ServerConfig, auth_manager: AuthManager, target: str) -> Dict[str, Any]:
    """Resolve a flow/subflow/action/decision by NAME or sys_id to a concrete
    {kind, sys_id, name} so one read entry point can serve them all. kind is one
    of: flow, subflow, action, decision, unknown. On an ambiguous name returns
    {"candidates": [...]} so the caller can disambiguate."""
    is_id = bool(_HEX32.match(target.strip().lower()))
    id_q = f"sys_id={target}"
    name_q = f"name={target}"

    def _classify_flow(row: Dict[str, Any]) -> str:
        return "subflow" if (row.get("type") or "").lower() == "subflow" else "flow"

    if is_id:
        rows = _table_lookup(config, auth_manager, _FLOW_DEF_TABLE, id_q)
        if rows:
            return {"kind": _classify_flow(rows[0]), "sys_id": target, "name": rows[0].get("name")}
        rows = _table_lookup(config, auth_manager, _ACTION_DEF_TABLE, id_q, fields="sys_id,name")
        if rows:
            return {"kind": "action", "sys_id": target, "name": rows[0].get("name")}
        rows = _table_lookup(
            config, auth_manager, _DECISION_TABLE, id_q, fields="sys_id,name,label"
        )
        if rows:
            return {"kind": "decision", "sys_id": target, "name": rows[0].get("name")}
        return {"kind": "unknown", "sys_id": target}

    # by name — search each surface, collect candidates
    candidates: List[Dict[str, Any]] = []
    for row in _table_lookup(config, auth_manager, _FLOW_DEF_TABLE, name_q):
        candidates.append(
            {"kind": _classify_flow(row), "sys_id": row.get("sys_id"), "name": row.get("name")}
        )
    for row in _table_lookup(config, auth_manager, _ACTION_DEF_TABLE, name_q, fields="sys_id,name"):
        candidates.append({"kind": "action", "sys_id": row.get("sys_id"), "name": row.get("name")})
    for row in _table_lookup(
        config, auth_manager, _DECISION_TABLE, name_q, fields="sys_id,name,label"
    ):
        candidates.append(
            {"kind": "decision", "sys_id": row.get("sys_id"), "name": row.get("name")}
        )
    if not candidates:
        return {"kind": "unknown", "name": target}
    if len(candidates) == 1:
        return candidates[0]
    return {"candidates": candidates}


def _checkout_path(flow_id: str) -> Path:
    return _CHECKOUT_DIR / f".sn_flow_edit_{flow_id}.json"


def _load_checkout(flow_id: str) -> Dict[str, Any]:
    path = _checkout_path(flow_id)
    if not path.exists():
        raise FileNotFoundError(f"No checkout for {flow_id}. Run checkout first.")
    return json.loads(path.read_text())


def _save_checkout(flow_id: str, data: Dict[str, Any]) -> None:
    _checkout_path(flow_id).write_text(json.dumps(data))


def _resolve_condition_value(value: Any) -> str:
    """Accept a condition as EITHER a raw encoded query string
    ('state=6^priority=1') OR a human-friendly list of rows
    ([{"field":"state","operator":"is","value":"6"}, ...]) — encoding the latter.
    A JSON-array string is parsed too, so callers that can only pass strings can
    still send structured rows. This is what makes "what do I put here?" easy:
    describe the conditions, don't hand-write the encoded blob."""
    if isinstance(value, list):
        return _encode_condition(value)
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                rows = json.loads(s)
                if isinstance(rows, list):
                    return _encode_condition(rows)
            except (ValueError, TypeError):
                pass
        return value
    return "" if value is None else str(value)


def _find_node(lst: List[Dict[str, Any]], node_id: str) -> Optional[Dict[str, Any]]:
    for item in lst:
        if item.get("id") == node_id or item.get("uiUniqueIdentifier") == node_id:
            return item
    return None


def _set_input_value(
    inputs: List[Dict[str, Any]],
    name: str,
    value: str,
    display_value: Optional[str] = None,
) -> bool:
    for inp in inputs:
        if inp.get("name") == name:
            inp["value"] = value
            if display_value is not None:
                inp["displayValue"] = display_value
            return True
    return False


# ServiceNow encoded-query operators, longest/most-specific token first so e.g.
# ">=" is matched before ">" and "ISNOTEMPTY" before "ISEMPTY". Mapped to the
# human label the Flow Designer condition builder shows.
# Inputs whose value is a script/code body — surfaced in full (never truncated)
# and flagged so the reader shows the actual code of a Run Script step.
_SCRIPT_INPUT_NAMES = frozenset({"script", "source", "client_script", "server_script"})

# Flow-level properties the UI's "Flow properties" dialog edits and saves via
# PUT /flow?...&param_only_properties=true. Allow-listed so set_property can't
# scribble arbitrary keys onto the flow payload.
# runAs: "system" (System User) | "user" (User who initiates session).
_FLOW_PROPERTY_NAMES = frozenset(
    {"runAs", "protection", "flowPriority", "name", "description", "active"}
)
_FLOW_BOOL_PROPERTIES = frozenset({"active"})


def _render_inputs(
    inputs: List[Dict[str, Any]], label_map: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """Render a node's inputs at Flow Designer screen fidelity: keep only the
    fields the user actually sees set, and surface the human `display` label
    (displayValue) alongside the raw value — e.g. table value
    'x_myapp_table' shows display 'My Table'."""
    out: List[Dict[str, Any]] = []
    for i in inputs or []:
        name = i.get("name", "")
        value = i.get("value", "")
        display = i.get("displayValue", "")
        if value in ("", None) and display in ("", None):
            continue
        item: Dict[str, Any] = {"name": name, "value": value}
        if display not in ("", None) and display != value:
            item["display"] = display
        # Condition fields hold an encoded query — decode to builder rows so the
        # reader shows 'field / operator / value' the way the canvas does,
        # instead of an opaque 'a=1^ORb=2' blob that confuses follow-up edits.
        if name in ("condition", "conditions") and isinstance(value, str) and value:
            rows = _decode_condition(value, label_map)
            if rows:
                item["conditions"] = rows
        # Script steps: keep the whole body and flag it as code so the reader
        # can actually show what a Run Script step does.
        elif name in _SCRIPT_INPUT_NAMES and isinstance(value, str) and value.strip():
            item["is_script"] = True
            item["line_count"] = value.count("\n") + 1
        out.append(item)
    return out


def _collect_input_values(flow_data: Dict[str, Any]) -> Dict[tuple, Any]:
    """(instance_id, input_name) -> value across all step instances + triggers,
    for post-save verification (did the value we sent actually persist?)."""
    out: Dict[tuple, Any] = {}
    for coll in (
        "actionInstances",
        "flowLogicInstances",
        "subFlowInstances",
        "triggerInstances",
    ):
        for n in flow_data.get(coll, []) or []:
            if n.get("deleted"):
                continue
            nid = n.get("id")
            for i in n.get("inputs", []) or []:
                out[(nid, i.get("name"))] = i.get("value")
    return out


def _verify_persisted(intended: Dict[str, Any], fresh: Dict[str, Any]) -> Dict[str, Any]:
    """Compare the input values we PUT against a fresh read. Returns
    {verified: bool, mismatches: [...]} — a mismatch means the server did NOT
    keep our value (the silent-revert failure mode)."""
    want = _collect_input_values(intended)
    got = _collect_input_values(fresh)
    mismatches = []
    for key, val in want.items():
        if got.get(key) != val:
            mismatches.append(
                {
                    "node_id": key[0],
                    "input": key[1],
                    "expected": val,
                    "actual": got.get(key),
                }
            )
    return {"verified": not mismatches, "mismatches": mismatches[:20]}


def _order_key(node: Dict[str, Any]) -> float:
    val = node.get("order")
    if val is None:
        return 1e9
    try:
        return float(val)
    except (TypeError, ValueError):
        return 1e9


def _render_variables(variables: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Render an Action's Input/Output Variables panel: name, human label, type
    — the chips the Data panel shows (e.g. 'service_close | Record')."""
    out: List[Dict[str, Any]] = []
    for v in variables or []:
        name = v.get("name", "")
        if not name:
            continue
        item: Dict[str, Any] = {
            "name": name,
            "label": v.get("label") or name,
            "type": v.get("type") or v.get("fieldType") or "",
        }
        default = v.get("value", "")
        if default not in ("", None):
            item["value"] = default
        out.append(item)
    return out


def _compact_action_summary(
    action_data: Dict[str, Any], steps_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Screen-fidelity view of a CUSTOM Action type (Action Designer). Unlike a
    flow it has no triggers/logic tree — it is Input Variables -> ordered steps
    (Script step / Look Up / Ask For Approval ...) -> Output Variables. Steps
    come from the separate /step_instances payload and use step_type_name/label
    rather than the flow action fields."""
    raw_steps: List[Any] = []
    if isinstance(steps_data, dict):
        raw_steps = steps_data.get("steps") or steps_data.get("result", {}).get("steps") or []
    elif isinstance(steps_data, list):
        raw_steps = steps_data
    steps = [
        {
            "step_id": s.get("step_id") or s.get("cid"),
            "label": s.get("label") or s.get("step_type_name") or "",
            "step_type": s.get("step_type_name") or "",
            "category": s.get("step_type_category") or "",
            "order": s.get("order"),
            "section": s.get("section"),
            "error_handling": s.get("error_handling_type"),
            "inputs": _render_inputs(s.get("inputs", [])),
            "outputs": _render_variables(s.get("outputs", [])),
        }
        for s in sorted(raw_steps, key=_order_key)
    ]
    return {
        "action_id": action_data.get("id"),
        "kind": "action",
        "name": action_data.get("name"),
        "internal_name": action_data.get("internal_name"),
        "description": action_data.get("description"),
        "state": action_data.get("state"),
        "active": action_data.get("active"),
        "scope": action_data.get("scope"),
        "scope_name": action_data.get("scopename") or action_data.get("scopeName"),
        "can_write": action_data.get("security", {}).get("can_write", False),
        "input_variables": _render_variables(action_data.get("inputs", [])),
        "output_variables": _render_variables(action_data.get("outputs", [])),
        "steps": steps,
    }


class ManageFlowEditParams(BaseModel):
    action: Literal[
        "read",
        "checkout",
        "read_action",
        "set_action_input",
        "set_trigger_condition",
        "set_branch_condition",
        "set_property",
        "save",
        "save_properties",
        "publish",
        "activate",
        "deactivate",
        "copy",
        "discard",
        "status",
    ] = Field(
        ...,
        description="read|checkout|read_action|set_action_input|set_trigger_condition|set_branch_condition|set_property|save|save_properties|publish(snapshot recompile)|activate|deactivate|copy(value=new name)|discard|status",
    )
    flow_id: str = Field(
        ..., description="sys_id of flow/subflow/action; for action='read' a NAME or sys_id"
    )
    node_id: Optional[str] = Field(
        default=None, description="Instance id of action/logic/trigger to patch"
    )
    input_name: Optional[str] = Field(
        default=None,
        description="Input/property name (set_action_input, set_property: runAs|protection|flowPriority|active|name|description)",
    )
    value: Optional[str] = Field(default=None, description="New value to set")
    condition_label: Optional[str] = Field(
        default=None, description="Human label for branch condition (set_branch_condition)"
    )
    publish: bool = Field(
        default=False,
        description="Publish (recompile snapshot) after save. Required for the edit to appear in get_detail / take effect; publish != active.",
    )
    verify: bool = Field(
        default=True,
        description="After save, re-read the flow and confirm the edits persisted (catches silent reverts). Safe default on.",
    )
    dry_run: bool = Field(
        default=False,
        description="Plan only: show what would be sent (endpoint/params/changed fields) without writing.",
    )


def manage_flow_edit(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageFlowEditParams,
) -> Dict[str, Any]:
    if not _is_browser_auth(config):
        return {"success": False, "error": "manage_flow_edit requires browser auth"}

    action = params.action
    flow_id = params.flow_id

    if action == "read":
        # One read entry point for the whole Workflow Studio set: resolve a NAME
        # or sys_id to its surface (flow/subflow/action/decision) and render it
        # at screen fidelity. Read-only — no checkout file is written.
        target = _resolve_target(config, auth_manager, flow_id)
        if target.get("candidates"):
            return {
                "success": False,
                "error": "Ambiguous name — multiple matches; read by sys_id.",
                "candidates": target["candidates"],
            }
        kind = target.get("kind")
        sys_id = target.get("sys_id")
        if not sys_id:
            return {"success": False, "error": "Could not resolve a sys_id for this flow."}
        if kind in ("flow", "subflow"):
            pf = _try_processflow_api(config, auth_manager, sys_id)
            if not pf or pf.get("_error"):
                return {"success": False, "error": (pf or {}).get("_error", "Failed to fetch flow")}
            return {
                "success": True,
                "action": "read",
                "kind": kind,
                "summary": render_flow_compact(pf.get("result", pf)),
            }
        if kind == "action":
            pf = _try_processflow_action(config, auth_manager, sys_id)
            if pf.get("_error"):
                return {"success": False, "error": pf["_error"]}
            return {
                "success": True,
                "action": "read",
                "kind": "action",
                "summary": _compact_action_summary(pf.get("action", {}), pf.get("steps")),
            }
        if kind == "decision":
            # Decision tables use the sys_decision* model (not processflow); a
            # dedicated reader is not built yet. Surface what we resolved so the
            # caller knows it exists rather than silently failing.
            return {
                "success": False,
                "kind": "decision",
                "sys_id": sys_id,
                "name": target.get("name"),
                "error": "Decision table reader not implemented yet (sys_decision model).",
            }
        return {"success": False, "error": f"Could not resolve '{flow_id}' to a flow/action."}

    if action == "checkout":
        pf = _try_processflow_api(config, auth_manager, flow_id)
        if not pf or pf.get("_error"):
            return {"success": False, "error": (pf or {}).get("_error", "Failed to fetch flow")}
        flow_data = pf.get("result", pf)
        if not flow_data.get("security", {}).get("can_write", False):
            return {
                "success": False,
                "error": "Flow is read-only or locked by another user (security.can_write=false)",
            }
        _save_checkout(flow_id, flow_data)
        return {"success": True, "action": "checkout", "summary": render_flow_compact(flow_data)}

    if action == "read_action":
        # Custom Action types use a different model than flows — fetch the type
        # definition + its internal steps (Script bodies included) and render at
        # screen fidelity. Read-only (no checkout/save for actions yet).
        pf = _try_processflow_action(config, auth_manager, flow_id)
        if pf.get("_error"):
            return {"success": False, "error": pf["_error"]}
        return {
            "success": True,
            "action": "read_action",
            "summary": _compact_action_summary(pf.get("action", {}), pf.get("steps")),
        }

    if action == "copy":
        # Native clone — server remaps all instance sys_ids + snapshots. The new
        # name comes via `value`; defaults to "Copy of <id>" if omitted.
        new_name = params.value or f"Copy of {flow_id}"
        return _copy_flow(config, auth_manager, flow_id, new_name)

    if action == "publish":
        # Recompile is editor-gated, not API-reachable — return UI guidance.
        return _manual_publish_response(config, flow_id)

    if action in ("activate", "deactivate"):
        # Toggle an ALREADY-published flow (GET /activate|/deactivate). Resolve
        # the flow's app scope for the transaction-scope param.
        rows = _table_lookup(
            config, auth_manager, _FLOW_DEF_TABLE, f"sys_id={flow_id}", fields="sys_id,sys_scope"
        )
        raw_scope = rows[0].get("sys_scope") if rows else None
        scope = raw_scope.get("value") if isinstance(raw_scope, dict) else raw_scope
        if not scope:
            return {"success": False, "error": f"Could not resolve scope for flow {flow_id}."}
        return _toggle_active(config, auth_manager, flow_id, scope, activate=(action == "activate"))

    if action == "status":
        try:
            flow_data = _load_checkout(flow_id)
            return {"success": True, "action": "status", "summary": render_flow_compact(flow_data)}
        except FileNotFoundError as e:
            return {"success": False, "error": str(e)}

    if action == "discard":
        _checkout_path(flow_id).unlink(missing_ok=True)
        return {"success": True, "action": "discard", "flow_id": flow_id}

    if action == "save":
        try:
            flow_data = _load_checkout(flow_id)
        except FileNotFoundError as e:
            return {"success": False, "error": str(e)}
        # The real UI scopes every flow-edit write with the flow's app sys_scope
        # (sysparm_transaction_scope). Without it the PUT only saves "properties"
        # and the structural edit silently reverts — the exact persist bug.
        scope = _flow_scope(flow_data)
        if not scope:
            return {
                "success": False,
                "error": "Flow payload has no 'scope' — re-run checkout (the scope "
                "field is required for save/publish transaction scoping).",
            }
        url = f"{config.instance_url}{_PF_BASE}"
        if params.dry_run:
            return {
                "success": True,
                "dry_run": True,
                "plan": {
                    "method": "PUT",
                    "url": _PF_BASE,
                    "params": {"sysparm_transaction_scope": scope},
                    "then_publish": bool(params.publish),
                    "summary": render_flow_compact(flow_data),
                },
            }
        # Mirror the UI: create a Save version row, then PUT the full flow.
        _create_version(auth_manager, config, flow_id, scope, "Save")
        response = None
        try:
            response = auth_manager.make_request(
                "PUT",
                url,
                params={"sysparm_transaction_scope": scope},
                json=flow_data,
                headers=_pf_write_headers(config),
            )
            response.raise_for_status()
            result = response.json()
        except Exception as e:
            # Capture the raw body so the real reason (not just "400") is visible.
            body = ""
            if response is not None:
                try:
                    body = response.text[:2000]
                except Exception:
                    pass
            return {"success": False, "error": f"Save failed: {e}", "save_response_body": body}

        outer = result.get("result", result)
        if isinstance(outer, dict):
            err = outer.get("errorMessage")
            if err:
                return {"success": False, "error": err}

        if params.publish:
            # Design-time saved; the recompile (publish) is editor-gated and not
            # API-reachable — tell the caller to click Activate/Publish in the UI.
            _checkout_path(flow_id).unlink(missing_ok=True)
            resp = _manual_publish_response(config, flow_id)
            resp["saved"] = True
            resp["warning"] = (
                "Saved to DESIGN-TIME. Publish (recompile) must be done in the UI — "
                "open the flow and click Activate/Publish."
            )
            return resp

        # Safety: re-read and confirm our values actually persisted (catches the
        # silent-revert failure mode) BEFORE we drop the checkout.
        verification: Optional[Dict[str, Any]] = None
        if params.verify:
            fresh = _try_processflow_api(config, auth_manager, flow_id)
            if fresh and not fresh.get("_error"):
                verification = _verify_persisted(flow_data, fresh.get("result", fresh))

        _checkout_path(flow_id).unlink(missing_ok=True)
        base: Dict[str, Any] = {"success": True, "saved": True, "published": bool(params.publish)}
        if verification is not None:
            base["verified"] = verification["verified"]
            if not verification["verified"]:
                base["success"] = False
                base["mismatches"] = verification["mismatches"]
                base["warning"] = (
                    "VERIFY FAILED — the server did not keep some values we sent (they "
                    "reverted). The edit is NOT reliably saved; inspect mismatches."
                )
                return base
        if params.publish:
            base["note"] = (
                "Published — flow snapshot recompiled; the edit now appears in get_detail "
                "and takes effect. publish does NOT activate an inactive flow."
            )
            return base
        # Saved without publishing: the design-time model changed, but the
        # compiled snapshot that get_detail and the runtime read did NOT. This
        # is the #1 'edit looks lost' trap — surface it loudly instead of
        # reporting a bare success.
        base["warning"] = (
            "Saved to DESIGN-TIME ONLY (not published). This edit will NOT appear in "
            "get_detail and will NOT take effect until you re-run save with publish=true "
            "(which recompiles the flow snapshot). publish does not activate an inactive flow."
        )
        return base

    if action == "save_properties":
        # Flow PROPERTIES save (Run As / Protection / Priority / active / name).
        # Same endpoint as a structure save but WITH param_only_properties=true —
        # that flag tells the server to persist only the property fields. This is
        # exactly what the "Flow properties" dialog's Update button sends.
        try:
            flow_data = _load_checkout(flow_id)
        except FileNotFoundError as e:
            return {"success": False, "error": str(e)}
        scope = _flow_scope(flow_data)
        if not scope:
            return {"success": False, "error": "Flow payload has no 'scope' — re-run checkout."}
        _create_version(auth_manager, config, flow_id, scope, "Save")
        response = None
        try:
            response = auth_manager.make_request(
                "PUT",
                f"{config.instance_url}{_PF_BASE}",
                params={"sysparm_transaction_scope": scope, "param_only_properties": "true"},
                json=flow_data,
                headers=_pf_write_headers(config),
            )
            response.raise_for_status()
            result = response.json()
        except Exception as e:
            body = ""
            if response is not None:
                try:
                    body = response.text[:2000]
                except Exception:
                    pass
            return {
                "success": False,
                "error": f"Property save failed: {e}",
                "save_response_body": body,
            }
        outer = result.get("result", result)
        if isinstance(outer, dict) and outer.get("errorMessage"):
            return {"success": False, "error": outer["errorMessage"]}
        _checkout_path(flow_id).unlink(missing_ok=True)
        return {
            "success": True,
            "action": "save_properties",
            "saved_properties": {
                k: flow_data.get(k) for k in _FLOW_PROPERTY_NAMES if k in flow_data
            },
        }

    # Patch operations require a checkout
    try:
        flow_data = _load_checkout(flow_id)
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

    if action == "set_property":
        prop = params.input_name or ""
        if prop not in _FLOW_PROPERTY_NAMES:
            return {
                "success": False,
                "error": f"Unknown/unsupported property '{prop}'. Allowed: "
                + ", ".join(sorted(_FLOW_PROPERTY_NAMES)),
            }
        raw = params.value
        if prop in _FLOW_BOOL_PROPERTIES:
            val: Any = str(raw).strip().lower() in ("true", "1", "yes")
        else:
            val = raw if raw is not None else ""
        flow_data[prop] = val
        _save_checkout(flow_id, flow_data)
        return {
            "success": True,
            "action": "set_property",
            "property": prop,
            "value": val,
            "note": "Staged in checkout — run save_properties to persist.",
        }

    if action == "set_action_input":
        node = _find_node(flow_data.get("actionInstances", []), params.node_id or "") or _find_node(
            flow_data.get("subFlowInstances", []), params.node_id or ""
        )
        if not node:
            return {"success": False, "error": f"Node not found: {params.node_id}"}
        if not _set_input_value(
            node.get("inputs", []), params.input_name or "", params.value or ""
        ):
            return {
                "success": False,
                "error": f"Input '{params.input_name}' not found on node {params.node_id}",
            }
        _save_checkout(flow_id, flow_data)
        return {
            "success": True,
            "action": action,
            "node_id": params.node_id,
            "input_name": params.input_name,
            "value": params.value,
        }

    if action == "set_branch_condition":
        node = _find_node(flow_data.get("flowLogicInstances", []), params.node_id or "")
        if not node:
            return {"success": False, "error": f"Logic node not found: {params.node_id}"}
        encoded = _resolve_condition_value(params.value)
        _set_input_value(node.get("inputs", []), "condition", encoded)
        if params.condition_label is not None:
            _set_input_value(node.get("inputs", []), "condition_name", params.condition_label)
            node["name"] = f"If: {params.condition_label}"
        _save_checkout(flow_id, flow_data)
        return {
            "success": True,
            "action": action,
            "node_id": params.node_id,
            "condition": encoded,
            "condition_readable": _condition_to_text(encoded),
        }

    if action == "set_trigger_condition":
        triggers = flow_data.get("triggerInstances", [])
        node = (
            _find_node(triggers, params.node_id or "")
            if params.node_id
            else (triggers[0] if triggers else None)
        )
        if not node:
            return {"success": False, "error": "No trigger instance found"}
        encoded = _resolve_condition_value(params.value)
        if not _set_input_value(node.get("inputs", []), "condition", encoded):
            return {"success": False, "error": "condition input not found on trigger"}
        _save_checkout(flow_id, flow_data)
        return {
            "success": True,
            "action": action,
            "node_id": node.get("id"),
            "condition": encoded,
            "condition_readable": _condition_to_text(encoded),
        }

    return {"success": False, "error": f"Unknown action: {action}"}
