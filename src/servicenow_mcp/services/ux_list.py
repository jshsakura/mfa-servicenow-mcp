"""UX Workspace list configuration service layer.

``sys_ux_list`` drives what a workspace module's list shows: either an
explicit ``columns`` field list, or a ``view`` (a ``sys_ui_view`` reference)
whose columns/order the list then inherits — plus a ``fixed_query`` that
always applies regardless of what the user filters by.

Kept separate from ``sn_write`` on purpose: ``view`` is a reference field.
Writing a display name straight into it stores an invalid sys_id silently —
the platform accepts whatever string arrives and just fails to resolve it at
render time, with nothing in the write response to say so. This resolves the
name to a real ``sys_ui_view`` sys_id first, or fails loud with the name that
did not match, instead of a caller finding out from a broken screen later.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import count_response, invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

TABLE = "sys_ux_list"
VIEW_TABLE = "sys_ui_view"

_META = (
    "sys_id,title,table,view,columns,fixed_query,condition,order,active," "sys_scope,sys_updated_on"
)

_UPDATE_FIELDS = ("title", "view", "columns", "fixed_query", "condition", "order", "active")


def _dv(v: Any) -> Any:
    """Unwrap a display-value dict to its value; pass scalars through."""
    return v.get("display_value") if isinstance(v, dict) else v


def _is_sys_id(value: str) -> bool:
    return len(value) == 32 and all(c in "0123456789abcdefABCDEF" for c in value)


def _resolve_view(config: ServerConfig, auth_manager: AuthManager, ident: str) -> Optional[str]:
    """A ``sys_ui_view`` sys_id for ``ident`` (already a sys_id, ``sys_id:<id>``,
    or a view name), or None when a name was given and nothing matched — never
    a guess written into a reference field."""
    if ident.startswith("sys_id:"):
        return ident[len("sys_id:") :]
    if _is_sys_id(ident):
        return ident
    records, _ = sn_query_page(
        config,
        auth_manager,
        table=VIEW_TABLE,
        query=f"name={ident}",
        fields="sys_id,name",
        limit=1,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    return records[0]["sys_id"] if records else None


def _row(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "sys_id": r.get("sys_id"),
        "title": r.get("title"),
        "table": r.get("table"),
        "view": _dv(r.get("view")),
        "columns": r.get("columns"),
        "fixed_query": r.get("fixed_query"),
        "condition": r.get("condition"),
        "order": r.get("order"),
        "active": _dv(r.get("active")) == "true",
        "scope": _dv(r.get("sys_scope")),
        "updated_on": r.get("sys_updated_on"),
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def list_lists(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    """List ``sys_ux_list`` records, optionally filtered by target table or title."""
    parts: List[str] = []
    if table:
        parts.append(f"table={table}")
    if query:
        parts.append(f"titleLIKE{query}")
    query_string = "^".join(parts)

    if count_only:
        return count_response(config, auth_manager, TABLE, query_string, what="UX list configs")

    records, _ = sn_query_page(
        config,
        auth_manager,
        table=TABLE,
        query=query_string,
        fields=_META,
        limit=min(limit, 50),
        offset=offset,
        display_value=True,
        fail_silently=False,
    )
    lists = [_row(r) for r in records]
    return {
        "success": True,
        "message": f"Found {len(lists)} UX list configs",
        "lists": lists,
        "total": len(lists),
        "limit": limit,
        "offset": offset,
    }


def get_list(config: ServerConfig, auth_manager: AuthManager, *, sys_id: str) -> Dict[str, Any]:
    """Get one ``sys_ux_list`` record by sys_id."""
    records, _ = sn_query_page(
        config,
        auth_manager,
        table=TABLE,
        query=f"sys_id={sys_id}",
        fields=_META,
        limit=1,
        offset=0,
        display_value=True,
        fail_silently=False,
    )
    if not records:
        return {"success": False, "message": f"UX list config not found: {sys_id}"}
    return {"success": True, "list": _row(records[0])}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def update_list(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sys_id: str,
    dry_run: bool = False,
    **fields: Any,
) -> Dict[str, Any]:
    """Update a ``sys_ux_list`` record's view/columns/fixed_query/etc."""
    existing = get_list(config, auth_manager, sys_id=sys_id)
    if not existing.get("success"):
        return existing

    body: Dict[str, Any] = {}
    for f in _UPDATE_FIELDS:
        v = fields.get(f)
        if v is None:
            continue
        if f == "view":
            resolved = _resolve_view(config, auth_manager, v)
            if resolved is None:
                return {
                    "success": False,
                    "message": f"sys_ui_view not found: {v!r} — check the name, or pass sys_id:<id>",
                }
            body["view"] = resolved
        elif isinstance(v, bool):
            body[f] = str(v).lower()
        else:
            body[f] = v

    if not body:
        return {
            "success": True,
            "message": f"No changes to update for UX list: {existing['list'].get('title')}",
            "sys_id": sys_id,
        }

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=TABLE,
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["title", "table", "view"],
        )

    url = f"{config.instance_url}/api/now/table/{TABLE}/{sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": f"Failed to update UX list: {sys_id}"}
        invalidate_query_cache(table=TABLE)
        return {
            "success": True,
            "message": f"Updated UX list config: {result.get('title')}",
            "sys_id": result.get("sys_id"),
            "title": result.get("title"),
        }
    except Exception as e:
        logger.error(f"Error updating UX list config: {e}")
        return {"success": False, "message": f"Error updating UX list config: {str(e)}"}
