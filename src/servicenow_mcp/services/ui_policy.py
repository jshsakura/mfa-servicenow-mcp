"""UI Policy (sys_ui_policy + sys_ui_policy_action) service layer."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    short_description: str,
    conditions: Optional[str] = None,
    active: bool = True,
    global_policy: bool = True,
    view_name: Optional[str] = None,
    on_load: bool = True,
    reverse_if_false: bool = True,
    order: int = 100,
    script_true: Optional[str] = None,
    script_false: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a UI policy on the ``sys_ui_policy`` table."""
    url = f"{config.instance_url}/api/now/table/sys_ui_policy"

    body: Dict[str, Any] = {
        "table": table,
        "short_description": short_description,
        "active": str(active).lower(),
        "global": str(global_policy).lower(),
        "on_load": str(on_load).lower(),
        "reverse_if_false": str(reverse_if_false).lower(),
        "order": str(order),
    }

    if conditions:
        body["conditions"] = conditions
    if view_name:
        body["view"] = view_name
    if script_true:
        body["script_true"] = script_true
    if script_false:
        body["script_false"] = script_false

    headers = auth_manager.get_headers()

    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "result" not in data:
            return {"success": False, "message": "Failed to create UI policy"}

        result = data["result"]
        invalidate_query_cache(table="sys_ui_policy")
        return {
            "success": True,
            "message": f"Created UI policy: {result.get('short_description')}",
            "ui_policy_id": result.get("sys_id"),
            "table": result.get("table"),
            "short_description": result.get("short_description"),
        }

    except Exception as e:
        logger.error(f"Error creating UI policy: {e}")
        return {"success": False, "message": f"Error creating UI policy: {str(e)}"}


def add_action(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    ui_policy: str,
    field: str,
    visible: Optional[str] = None,
    mandatory: Optional[str] = None,
    disabled: Optional[str] = None,
    cleared: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a per-field action to an existing UI policy."""
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_ui_policy",
            query=f"sys_id={ui_policy}",
            fields="sys_id,short_description,table",
            limit=1,
            offset=0,
            display_value=False,
            fail_silently=False,
        )

        if not records:
            return {
                "success": False,
                "message": f"UI policy not found: {ui_policy}",
            }

        parent_policy = records[0]
        table = parent_policy.get("table")

    except Exception as e:
        logger.error(f"Error verifying UI policy: {e}")
        return {
            "success": False,
            "message": f"Error verifying UI policy: {str(e)}",
        }

    url = f"{config.instance_url}/api/now/table/sys_ui_policy_action"
    headers = auth_manager.get_headers()

    body: Dict[str, Any] = {
        "ui_policy": ui_policy,
        "table": table,
        "field": field,
    }

    if visible is not None:
        body["visible"] = visible
    if mandatory is not None:
        body["mandatory"] = mandatory
    if disabled is not None:
        body["disabled"] = disabled
    if cleared is not None:
        body["cleared"] = cleared

    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "result" not in data:
            return {"success": False, "message": "Failed to create UI policy action"}

        result = data["result"]
        invalidate_query_cache(table="sys_ui_policy_action")
        return {
            "success": True,
            "message": f"Created UI policy action for field '{field}'",
            "action_id": result.get("sys_id"),
            "ui_policy": ui_policy,
            "field": field,
            "visible": result.get("visible"),
            "mandatory": result.get("mandatory"),
            "disabled": result.get("disabled"),
        }

    except Exception as e:
        logger.error(f"Error creating UI policy action: {e}")
        return {
            "success": False,
            "message": f"Error creating UI policy action: {str(e)}",
        }
