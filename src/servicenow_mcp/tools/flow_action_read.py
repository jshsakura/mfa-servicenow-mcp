"""Reading a Flow Designer custom ACTION (not a flow).

An Action type uses a different model from a flow: the type definition plus its
internal steps, script bodies included. This is the read behind
`manage_flow_designer(action='read_action')`.

It was extracted from the flow-edit module when Flow Designer writes were
withdrawn — that module was deleted, and this read was the only thing in it
worth keeping.
"""

import logging
from typing import Any, Dict, List, Optional

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from .flow_designer_tools import _decode_condition

logger = logging.getLogger(__name__)


_PF_HEADERS = {"x-transaction-source": "Interface=Web"}


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


_SCRIPT_INPUT_NAMES = frozenset({"script", "source", "client_script", "server_script"})


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
    — the chips the Data panel shows (e.g. 'sample_ref | Record')."""
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
