"""Outbound REST Message service layer.

``sys_rest_message`` (the message: base endpoint, auth) owns HTTP methods
(``sys_rest_message_fn``), and each method owns three child lists. Their
tables are not named after what the form calls them, which is exactly how a
caller ends up guessing — measured against a live instance:

  HTTP Query Parameters  -> sys_rest_message_fn_param_defs  (name, value, order)
  HTTP Headers           -> sys_rest_message_fn_headers     (name, value)
  Variable Substitutions -> sys_rest_message_fn_parameters  (name, value=test value, type)

So ``get_method`` returns all three at once, and every write names its list by
``param_type`` instead of by table. Credentials (basic_auth_password, profiles)
are never read.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import (
    build_create_preview,
    build_delete_preview,
    build_update_preview,
)
from servicenow_mcp.tools.sn_api import count_response, invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

MESSAGE_TABLE = "sys_rest_message"
METHOD_TABLE = "sys_rest_message_fn"
MESSAGE_HEADER_TABLE = "sys_rest_message_headers"
PARAM_TABLES: Dict[str, str] = {
    "query": "sys_rest_message_fn_param_defs",
    "header": "sys_rest_message_fn_headers",
    "variable": "sys_rest_message_fn_parameters",
}
_PARAM_FIELDS: Dict[str, str] = {
    "query": "sys_id,name,value,order,rest_message_function,sys_scope,sys_updated_on",
    "header": "sys_id,name,value,rest_message_function,sys_scope,sys_updated_on",
    "variable": "sys_id,name,value,type,rest_message_function,sys_scope,sys_updated_on",
}
_MESSAGE_FIELDS = (
    "sys_id,name,rest_endpoint,description,authentication_type,access,sys_scope,sys_updated_on"
)
_METHOD_FIELDS = (
    "sys_id,function_name,http_method,rest_endpoint,content,authentication_type,"
    "rest_message,sys_scope,sys_mod_count,sys_updated_on"
)
_VAR_REF = re.compile(r"\$\{([^}]+)\}")


def _v(row: Dict[str, Any], field: str) -> str:
    """Raw value from a display_value='all' row."""
    val = row.get(field)
    if isinstance(val, dict):
        return str(val.get("value") or "")
    return str(val or "")


def _d(row: Dict[str, Any], field: str) -> str:
    """Display value from a display_value='all' row."""
    val = row.get(field)
    if isinstance(val, dict):
        return str(val.get("display_value") or val.get("value") or "")
    return str(val or "")


def _read(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    *,
    limit: int = 1,
    offset: int = 0,
    orderby: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=offset,
        display_value="all",
        orderby=orderby,
        fail_silently=False,
    )
    return rows


def _param_row(param_type: str, r: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "sys_id": _v(r, "sys_id"),
        "name": _v(r, "name"),
        "value": _v(r, "value"),
    }
    if param_type == "query":
        row["order"] = _v(r, "order")
    if param_type == "variable":
        row["escape_type"] = _v(r, "type")
    row["sys_updated_on"] = _v(r, "sys_updated_on")
    return row


def _scope(r: Dict[str, Any]) -> Dict[str, str]:
    return {"sys_id": _v(r, "sys_scope"), "name": _d(r, "sys_scope")}


def _stale(current_updated_on: str, expected: Optional[str]) -> Optional[Dict[str, Any]]:
    """Block a write when the caller pinned a version and the server moved."""
    if expected and expected.strip() != current_updated_on:
        return {
            "success": False,
            "error": "record_changed",
            "message": (
                f"The record changed after you read it (expected sys_updated_on "
                f"{expected.strip()}, server now has {current_updated_on}). Nothing was "
                "written. Read it again and re-apply against the current values."
            ),
            "server_updated_on": current_updated_on,
        }
    return None


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def list_messages(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    query: Optional[str] = None,
    scope: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    parts: List[str] = []
    if scope:
        parts.append(f"sys_scope.scope={scope}")
    if query:
        parts.append(f"nameLIKE{query}^ORrest_endpointLIKE{query}")
    query_string = "^".join(parts)
    if count_only:
        return count_response(
            config, auth_manager, MESSAGE_TABLE, query_string, what="REST messages"
        )
    rows = _read(
        config,
        auth_manager,
        MESSAGE_TABLE,
        query_string,
        _MESSAGE_FIELDS,
        limit=min(limit, 50),
        offset=offset,
        orderby="name",
    )
    messages = [
        {
            "sys_id": _v(r, "sys_id"),
            "name": _v(r, "name"),
            "rest_endpoint": _v(r, "rest_endpoint"),
            "scope": _d(r, "sys_scope"),
        }
        for r in rows
    ]
    return {
        "success": True,
        "messages": messages,
        "count": len(messages),
        "limit": limit,
        "offset": offset,
    }


def get_message(config: ServerConfig, auth_manager: AuthManager, *, sys_id: str) -> Dict[str, Any]:
    rows = _read(config, auth_manager, MESSAGE_TABLE, f"sys_id={sys_id}", _MESSAGE_FIELDS)
    if not rows:
        return {
            "success": False,
            "error": "not_found",
            "message": f"REST message not found: {sys_id}",
        }
    r = rows[0]
    methods = _read(
        config,
        auth_manager,
        METHOD_TABLE,
        f"rest_message={sys_id}",
        "sys_id,function_name,http_method,rest_endpoint",
        limit=100,
        orderby="function_name",
    )
    headers = _read(
        config,
        auth_manager,
        MESSAGE_HEADER_TABLE,
        f"rest_message={sys_id}",
        "sys_id,name,value",
        limit=100,
        orderby="name",
    )
    return {
        "success": True,
        "message_record": {
            "sys_id": _v(r, "sys_id"),
            "name": _v(r, "name"),
            "rest_endpoint": _v(r, "rest_endpoint"),
            "description": _v(r, "description"),
            "authentication_type": _v(r, "authentication_type"),
            "scope": _scope(r),
            "sys_updated_on": _v(r, "sys_updated_on"),
        },
        "methods": [
            {
                "sys_id": _v(m, "sys_id"),
                "name": _v(m, "function_name"),
                "http_method": _v(m, "http_method").upper(),
                "rest_endpoint": _v(m, "rest_endpoint"),
            }
            for m in methods
        ],
        "message_headers": [
            {"sys_id": _v(h, "sys_id"), "name": _v(h, "name"), "value": _v(h, "value")}
            for h in headers
        ],
        "hint": "Use get_method(sys_id=<method>) for its query parameters, headers and variables.",
    }


def _method_record(
    config: ServerConfig, auth_manager: AuthManager, sys_id: str
) -> Optional[Dict[str, Any]]:
    rows = _read(config, auth_manager, METHOD_TABLE, f"sys_id={sys_id}", _METHOD_FIELDS)
    return rows[0] if rows else None


def _children(
    config: ServerConfig, auth_manager: AuthManager, method_sys_id: str, param_type: str
) -> List[Dict[str, Any]]:
    rows = _read(
        config,
        auth_manager,
        PARAM_TABLES[param_type],
        f"rest_message_function={method_sys_id}",
        _PARAM_FIELDS[param_type],
        limit=200,
        orderby="order" if param_type == "query" else "name",
    )
    return [_param_row(param_type, r) for r in rows]


def get_method(config: ServerConfig, auth_manager: AuthManager, *, sys_id: str) -> Dict[str, Any]:
    m = _method_record(config, auth_manager, sys_id)
    if m is None:
        return {
            "success": False,
            "error": "not_found",
            "message": f"HTTP method not found: {sys_id}",
        }

    query_params = _children(config, auth_manager, sys_id, "query")
    headers = _children(config, auth_manager, sys_id, "header")
    variables = _children(config, auth_manager, sys_id, "variable")

    endpoint = _v(m, "rest_endpoint")
    inherited = False
    message_id = _v(m, "rest_message")
    if not endpoint and message_id:
        parent = _read(config, auth_manager, MESSAGE_TABLE, f"sys_id={message_id}", "rest_endpoint")
        endpoint = _v(parent[0], "rest_endpoint") if parent else ""
        inherited = True

    # Every ${name} the request will substitute, from every place it can appear —
    # so "is Offset wired in?" is answered here rather than by reading four lists.
    sources = [endpoint, _v(m, "content")]
    sources += [p["value"] for p in query_params] + [h["value"] for h in headers]
    referenced = sorted({name for text in sources for name in _VAR_REF.findall(text or "")})

    return {
        "success": True,
        "method": {
            "sys_id": _v(m, "sys_id"),
            "name": _v(m, "function_name"),
            "http_method": _v(m, "http_method").upper(),
            "rest_endpoint": _v(m, "rest_endpoint"),
            "effective_endpoint": endpoint,
            "endpoint_inherited_from_message": inherited,
            "content": _v(m, "content"),
            "authentication_type": _v(m, "authentication_type"),
            "rest_message": {"sys_id": message_id, "name": _d(m, "rest_message")},
            "scope": _scope(m),
            "sys_mod_count": _v(m, "sys_mod_count"),
            "sys_updated_on": _v(m, "sys_updated_on"),
        },
        "query_params": query_params,
        "headers": headers,
        "variables": variables,
        "referenced_variables": referenced,
    }


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


def _patch(
    config: ServerConfig, auth_manager: AuthManager, table: str, sys_id: str, body: Dict[str, Any]
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/{table}/{sys_id}"
    response = auth_manager.make_request(
        "PATCH", url, json=body, headers=auth_manager.get_headers(), timeout=30
    )
    response.raise_for_status()
    invalidate_query_cache(table=table)
    return response.json().get("result") or {}


def update_method(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sys_id: str,
    rest_endpoint: Optional[str] = None,
    http_method: Optional[str] = None,
    content: Optional[str] = None,
    expected_updated_on: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    m = _method_record(config, auth_manager, sys_id)
    if m is None:
        return {
            "success": False,
            "error": "not_found",
            "message": f"HTTP method not found: {sys_id}",
        }
    blocked = _stale(_v(m, "sys_updated_on"), expected_updated_on)
    if blocked:
        return blocked

    body: Dict[str, Any] = {}
    if rest_endpoint is not None:
        body["rest_endpoint"] = rest_endpoint
    if http_method is not None:
        body["http_method"] = http_method.lower()
    if content is not None:
        body["content"] = content
    if not body:
        return {"success": True, "message": "No changes requested.", "sys_id": sys_id}

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=METHOD_TABLE,
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["function_name", "rest_message"],
        )
    before = {k: _v(m, k) for k in body}
    try:
        result = _patch(config, auth_manager, METHOD_TABLE, sys_id, body)
    except Exception as e:
        logger.error("Error updating HTTP method %s: %s", sys_id, e)
        return {"success": False, "message": f"Error updating HTTP method: {e}"}
    return {
        "success": True,
        "message": f"Updated HTTP method: {_v(m, 'function_name')}",
        "sys_id": sys_id,
        "before": before,
        "after": {k: str(result.get(k, "")) for k in body},
    }


def _param_record(
    config: ServerConfig, auth_manager: AuthManager, param_type: str, sys_id: str
) -> Optional[Dict[str, Any]]:
    rows = _read(
        config,
        auth_manager,
        PARAM_TABLES[param_type],
        f"sys_id={sys_id}",
        _PARAM_FIELDS[param_type],
    )
    return rows[0] if rows else None


def _param_body(
    param_type: str,
    *,
    name: Optional[str],
    value: Optional[str],
    order: Optional[int],
    escape_type: Optional[str],
) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if value is not None:
        body["value"] = value
    if order is not None and param_type == "query":
        body["order"] = order
    if escape_type is not None and param_type == "variable":
        body["type"] = escape_type
    return body


def add_param(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    method_sys_id: str,
    param_type: str,
    name: str,
    value: Optional[str] = None,
    order: Optional[int] = None,
    escape_type: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    table = PARAM_TABLES[param_type]
    m = _method_record(config, auth_manager, method_sys_id)
    if m is None:
        return {
            "success": False,
            "error": "not_found",
            "message": f"HTTP method not found: {method_sys_id}",
        }

    existing = _children(config, auth_manager, method_sys_id, param_type)
    same = [p for p in existing if p["name"] == name]
    if same:
        return {
            "success": False,
            "error": "duplicate_name",
            "message": (
                f"'{name}' already exists in this method's {param_type} list. Nothing was "
                f"written. Change it with update_param(param_sys_id='{same[0]['sys_id']}')."
            ),
            "existing": same[0],
        }

    body = _param_body(param_type, name=name, value=value, order=order, escape_type=escape_type)
    if param_type == "query" and order is None:
        orders = [
            int(p["order"]) for p in existing if str(p.get("order", "")).lstrip("-").isdigit()
        ]
        body["order"] = (max(orders) + 100) if orders else 100
    body["rest_message_function"] = method_sys_id

    if dry_run:
        return build_create_preview(table=table, proposed=body)

    url = f"{config.instance_url}/api/now/table/{table}"
    try:
        response = auth_manager.make_request(
            "POST", url, json=body, headers=auth_manager.get_headers(), timeout=30
        )
        response.raise_for_status()
        result = response.json().get("result") or {}
    except Exception as e:
        logger.error("Error adding %s param to %s: %s", param_type, method_sys_id, e)
        return {"success": False, "message": f"Error adding {param_type} parameter: {e}"}
    invalidate_query_cache(table=table)

    out: Dict[str, Any] = {
        "success": True,
        "message": f"Added {param_type} parameter '{name}' to {_v(m, 'function_name')}",
        "sys_id": result.get("sys_id"),
        "record": {k: result.get(k) for k in body if k != "rest_message_function"},
    }
    # The row's scope comes from the session's current application, not from the
    # parent — so a child can land in another app than its method. Read, not assumed.
    new_scope = result.get("sys_scope")
    new_scope_id = new_scope.get("value") if isinstance(new_scope, dict) else new_scope
    parent_scope = _v(m, "sys_scope")
    if new_scope_id and parent_scope and new_scope_id != parent_scope:
        out["warning"] = (
            f"The new row landed in scope {new_scope_id}, but its method is in "
            f"{_d(m, 'sys_scope') or parent_scope}. It will be captured with the other app. "
            "Switch the current application (manage_session_context action='set_app') and "
            "re-create it if that is not intended."
        )
    return out


def update_param(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    param_sys_id: str,
    param_type: str,
    name: Optional[str] = None,
    value: Optional[str] = None,
    order: Optional[int] = None,
    escape_type: Optional[str] = None,
    expected_updated_on: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    table = PARAM_TABLES[param_type]
    r = _param_record(config, auth_manager, param_type, param_sys_id)
    if r is None:
        return {
            "success": False,
            "error": "not_found",
            "message": f"No {param_type} parameter {param_sys_id} in {table}. Check param_type.",
        }
    blocked = _stale(_v(r, "sys_updated_on"), expected_updated_on)
    if blocked:
        return blocked

    body = _param_body(param_type, name=name, value=value, order=order, escape_type=escape_type)
    if not body:
        return {"success": True, "message": "No changes requested.", "sys_id": param_sys_id}
    if name is not None and name != _v(r, "name"):
        siblings = _children(config, auth_manager, _v(r, "rest_message_function"), param_type)
        clash = [p for p in siblings if p["name"] == name and p["sys_id"] != param_sys_id]
        if clash:
            return {
                "success": False,
                "error": "duplicate_name",
                "message": f"'{name}' already exists in this method's {param_type} list.",
                "existing": clash[0],
            }

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=table,
            sys_id=param_sys_id,
            proposed=body,
            identifier_fields=["name", "rest_message_function"],
        )
    before = _param_row(param_type, r)
    try:
        result = _patch(config, auth_manager, table, param_sys_id, body)
    except Exception as e:
        logger.error("Error updating %s param %s: %s", param_type, param_sys_id, e)
        return {"success": False, "message": f"Error updating {param_type} parameter: {e}"}
    return {
        "success": True,
        "message": f"Updated {param_type} parameter '{result.get('name') or before['name']}'",
        "sys_id": param_sys_id,
        "before": before,
        "after": {k: str(result.get(k, "")) for k in body},
    }


def remove_param(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    param_sys_id: str,
    param_type: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    table = PARAM_TABLES[param_type]
    r = _param_record(config, auth_manager, param_type, param_sys_id)
    if r is None:
        return {
            "success": False,
            "error": "not_found",
            "message": f"No {param_type} parameter {param_sys_id} in {table}. Check param_type.",
        }
    if dry_run:
        return build_delete_preview(
            config,
            auth_manager,
            table=table,
            sys_id=param_sys_id,
            identifier_fields=["name", "value", "rest_message_function"],
        )
    removed = _param_row(param_type, r)
    url = f"{config.instance_url}/api/now/table/{table}/{param_sys_id}"
    try:
        response = auth_manager.make_request(
            "DELETE", url, headers=auth_manager.get_headers(), timeout=30
        )
        response.raise_for_status()
    except Exception as e:
        logger.error("Error removing %s param %s: %s", param_type, param_sys_id, e)
        return {"success": False, "message": f"Error removing {param_type} parameter: {e}"}
    invalidate_query_cache(table=table)
    return {
        "success": True,
        "message": f"Removed {param_type} parameter '{removed['name']}'",
        "removed": removed,
    }
