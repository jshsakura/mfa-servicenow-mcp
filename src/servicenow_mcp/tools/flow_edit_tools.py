"""Flow Designer edit tools — checkout / patch / save."""

import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .flow_designer_tools import _is_browser_auth, _try_processflow_api

logger = logging.getLogger(__name__)

_CHECKOUT_DIR = Path(tempfile.gettempdir())
_PF_BASE = "/api/now/processflow/flow"
_PF_HEADERS = {"x-transaction-source": "Interface=Web"}


def _checkout_path(flow_id: str) -> Path:
    return _CHECKOUT_DIR / f".sn_flow_edit_{flow_id}.json"


def _load_checkout(flow_id: str) -> Dict[str, Any]:
    path = _checkout_path(flow_id)
    if not path.exists():
        raise FileNotFoundError(f"No checkout for {flow_id}. Run checkout first.")
    return json.loads(path.read_text())


def _save_checkout(flow_id: str, data: Dict[str, Any]) -> None:
    _checkout_path(flow_id).write_text(json.dumps(data))


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


def _compact_summary(flow_data: Dict[str, Any]) -> Dict[str, Any]:
    actions = [
        {
            "id": a["id"],
            "name": a.get("name", ""),
            "type": a.get("internalName", ""),
            "inputs": [
                {"name": i["name"], "value": i.get("value", "")} for i in a.get("inputs", [])
            ],
        }
        for a in flow_data.get("actionInstances", [])
        if not a.get("deleted")
    ]
    logic = [
        {
            "id": n["id"],
            "name": n.get("name", ""),
            "type": (
                n.get("flowLogicDefinition", {}).get("type", "")
                if isinstance(n.get("flowLogicDefinition"), dict)
                else ""
            ),
            "condition": next(
                (i["value"] for i in n.get("inputs", []) if i.get("name") == "condition"),
                "",
            ),
            "condition_label": next(
                (i["value"] for i in n.get("inputs", []) if i.get("name") == "condition_name"),
                "",
            ),
        }
        for n in flow_data.get("flowLogicInstances", [])
        if not n.get("deleted")
    ]
    triggers = [
        {
            "id": t["id"],
            "type": t.get("type", ""),
            "condition": next(
                (i["value"] for i in t.get("inputs", []) if i.get("name") == "condition"),
                "",
            ),
        }
        for t in flow_data.get("triggerInstances", [])
    ]
    subflows = [
        {
            "id": s["id"],
            "name": (
                s.get("subFlow", {}).get("name", "")
                if isinstance(s.get("subFlow"), dict)
                else s.get("name", "")
            ),
            "inputs": [
                {"name": i["name"], "value": i.get("value", "")} for i in s.get("inputs", [])
            ],
        }
        for s in flow_data.get("subFlowInstances", [])
        if not s.get("deleted")
    ]
    return {
        "flow_id": flow_data.get("id"),
        "name": flow_data.get("name"),
        "status": flow_data.get("status"),
        "can_write": flow_data.get("security", {}).get("can_write", False),
        "triggers": triggers,
        "logic_nodes": logic,
        "actions": actions,
        "subflows": subflows,
    }


class ManageFlowEditParams(BaseModel):
    action: Literal[
        "checkout",
        "set_action_input",
        "set_trigger_condition",
        "set_branch_condition",
        "save",
        "discard",
        "status",
    ] = Field(
        ...,
        description="checkout|set_action_input|set_trigger_condition|set_branch_condition|save|discard|status",
    )
    flow_id: str = Field(..., description="Flow sys_id")
    node_id: Optional[str] = Field(
        default=None, description="Instance id of action/logic/trigger to patch"
    )
    input_name: Optional[str] = Field(
        default=None, description="Input field name (set_action_input only)"
    )
    value: Optional[str] = Field(default=None, description="New value to set")
    condition_label: Optional[str] = Field(
        default=None, description="Human label for branch condition (set_branch_condition)"
    )
    publish: bool = Field(default=False, description="Publish after save")


@register_tool(
    "manage_flow_edit",
    params=ManageFlowEditParams,
    description="Checkout/patch/save Flow Designer flows. Browser auth only. checkout→patch→save workflow.",
    serialization="raw_dict",
    return_type=dict,
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

    if action == "checkout":
        pf = _try_processflow_api(config, auth_manager, flow_id)
        if not pf or pf.get("_error"):
            return {"success": False, "error": pf.get("_error", "Failed to fetch flow")}
        flow_data = pf.get("result", pf)
        if not flow_data.get("security", {}).get("can_write", False):
            return {
                "success": False,
                "error": "Flow is read-only or locked by another user (security.can_write=false)",
            }
        _save_checkout(flow_id, flow_data)
        return {"success": True, "action": "checkout", "summary": _compact_summary(flow_data)}

    if action == "status":
        try:
            flow_data = _load_checkout(flow_id)
            return {"success": True, "action": "status", "summary": _compact_summary(flow_data)}
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
        url = f"{config.instance_url}{_PF_BASE}"
        try:
            response = auth_manager.make_request(
                "PUT",
                url,
                params={"param_only_properties": "true"},
                json=flow_data,
                headers=_PF_HEADERS,
            )
            response.raise_for_status()
            result = response.json()
        except Exception as e:
            return {"success": False, "error": f"Save failed: {e}"}

        outer = result.get("result", result)
        if isinstance(outer, dict):
            err = outer.get("errorMessage")
            if err:
                return {"success": False, "error": err}

        if params.publish:
            pub_url = f"{config.instance_url}{_PF_BASE}/{flow_id}/publish"
            try:
                pub_resp = auth_manager.make_request("POST", pub_url, headers=_PF_HEADERS, json={})
                pub_resp.raise_for_status()
            except Exception as e:
                return {"success": True, "saved": True, "published": False, "publish_error": str(e)}

        _checkout_path(flow_id).unlink(missing_ok=True)
        return {"success": True, "saved": True, "published": params.publish}

    # Patch operations require a checkout
    try:
        flow_data = _load_checkout(flow_id)
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}

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
        _set_input_value(node.get("inputs", []), "condition", params.value or "")
        if params.condition_label is not None:
            _set_input_value(node.get("inputs", []), "condition_name", params.condition_label)
            node["name"] = f"If: {params.condition_label}"
        _save_checkout(flow_id, flow_data)
        return {
            "success": True,
            "action": action,
            "node_id": params.node_id,
            "condition": params.value,
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
        if not _set_input_value(node.get("inputs", []), "condition", params.value or ""):
            return {"success": False, "error": "condition input not found on trigger"}
        _save_checkout(flow_id, flow_data)
        return {
            "success": True,
            "action": action,
            "node_id": node.get("id"),
            "condition": params.value,
        }

    return {"success": False, "error": f"Unknown action: {action}"}
