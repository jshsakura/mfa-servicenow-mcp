"""Values the Table API accepts with a 200 and then does not store.

Measured on a live instance (2026-11), each one silently, with no error:

- ``sys_ui_policy_action.ui_policy`` (and so ``catalog_ui_policy_action``): an
  out-of-box deny ACL on create and write whose only passing role is
  ``nobody``. No API, admin included, can link an action to its policy; only the
  policy form's related list does it. An action written over the API is left
  attached to nothing and does nothing.
- ``catalog_script_client.cat_variable``, ``catalog_ui_policy_action.catalog_variable``
  and an inactive ``item_option_new.type`` choice (e.g. 40): stored empty or
  changed by the Table API, stored as sent by the JSONv2 web service.

So: write, read back, and say what did not land. Never report a write that a
read-back contradicts as done.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

POLICY_LINK_BLOCKED = (
    "This instance does not let any API link a UI policy action to its policy "
    "(sys_ui_policy_action.ui_policy is denied on create and write, admin included), "
    "so the action would do nothing. Add it from the policy's 'UI Policy Actions' "
    "related list in the platform UI."
)


def _rv(v: Any) -> Any:
    return v.get("value") if isinstance(v, dict) else v


def jsonv2_update(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    sys_id: str,
    fields: Dict[str, Any],
) -> None:
    """Write ``fields`` on one row through the JSONv2 web service. Raises on failure."""
    url = f"{config.instance_url}/{table}.do?JSONv2&sysparm_action=update&sysparm_query=sys_id={sys_id}"
    headers = auth_manager.get_headers()
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"
    response = auth_manager.make_request(
        "POST", url, json=fields, headers=headers, timeout=config.timeout
    )
    response.raise_for_status()
    invalidate_query_cache(table=table)


def stored_values(
    config: ServerConfig, auth_manager: AuthManager, table: str, sys_id: str, fields: str
) -> Optional[Dict[str, str]]:
    """The row's stored values; None when it cannot be read (never 'empty')."""
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=f"sys_id={sys_id}",
            fields=fields,
            limit=1,
            offset=0,
            display_value=False,
            no_count=True,
            fail_silently=False,
        )
    except Exception as exc:  # noqa: BLE001 - unread is reported by the caller
        logger.debug("Read-back of %s %s failed: %s", table, sys_id, exc)
        return None
    if not rows:
        return None
    return {k: str(_rv(v) or "") for k, v in rows[0].items()}


def rewrite_dropped(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    sys_id: str,
    wanted: Dict[str, str],
) -> Dict[str, Any]:
    """Re-send through JSONv2 what the Table API did not store; read back again.

    Returns ``{"stored": bool, "missing": {field: stored}, "error"?: str}``.
    ``stored`` is True only when every wanted value was read back as sent.
    """
    fields = "sys_id," + ",".join(wanted)
    back = stored_values(config, auth_manager, table, sys_id, fields)
    if back is None:
        return {"stored": False, "missing": dict(wanted), "error": "could not read the row back"}
    missing = {f: back.get(f, "") for f, v in wanted.items() if back.get(f, "") != str(v)}
    if not missing:
        return {"stored": True, "missing": {}}
    try:
        jsonv2_update(config, auth_manager, table, sys_id, {f: wanted[f] for f in missing})
    except Exception as exc:  # noqa: BLE001 - the value stays reported as not stored
        return {"stored": False, "missing": missing, "error": f"JSONv2 write failed: {exc}"}
    back = stored_values(config, auth_manager, table, sys_id, fields)
    if back is None:
        return {"stored": False, "missing": missing, "error": "could not read the row back"}
    missing = {f: back.get(f, "") for f, v in wanted.items() if back.get(f, "") != str(v)}
    return {"stored": not missing, "missing": missing}


def unlinked_action_removed(
    config: ServerConfig, auth_manager: AuthManager, table: str, sys_id: str, policy_id: str
) -> Optional[Dict[str, Any]]:
    """None when the new action is linked to ``policy_id``; else remove it and say so.

    An action the instance left unlinked is never handed back as created.
    """
    back = stored_values(config, auth_manager, table, sys_id, "sys_id,ui_policy")
    if back is None:
        # Unread is not unlinked: the action is kept and named, not deleted.
        return {
            "success": False,
            "error": "POLICY_LINK_UNCONFIRMED",
            "message": (
                f"Created action {sys_id} but could not read it back to confirm it is "
                f"linked to policy {policy_id}. Check it before relying on it."
            ),
            "action_id": sys_id,
        }
    if back.get("ui_policy") == policy_id:
        return None
    removed = False
    try:
        url = f"{config.instance_url}/api/now/table/{table}/{sys_id}"
        response = auth_manager.make_request(
            "DELETE", url, headers=auth_manager.get_headers(), timeout=config.timeout
        )
        response.raise_for_status()
        invalidate_query_cache(table=table)
        removed = True
    except Exception as exc:  # noqa: BLE001 - reported: the orphan is named
        logger.debug("Could not remove unlinked action %s: %s", sys_id, exc)
    return {
        "success": False,
        "error": "POLICY_LINK_NOT_STORED",
        "message": POLICY_LINK_BLOCKED
        + (
            f" The unlinked action {sys_id} was removed."
            if removed
            else f" The unlinked action {sys_id} could NOT be removed; delete it."
        ),
        "action_id": None if removed else sys_id,
    }
