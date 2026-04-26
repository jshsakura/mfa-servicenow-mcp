"""Service layer for portal layout CRUD (page, container, row, column, widget instance)."""

import logging
from typing import Any, Dict, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

INSTANCE_TABLE = "sp_instance"


# ---------------------------------------------------------------------------
# Private helpers (mirror portal_crud_tools._check_duplicate / _create_record)
# ---------------------------------------------------------------------------


def _check_duplicate(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    field: str,
    value: str,
    scope: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    query = f"{field}={value}"
    if scope:
        query += f"^sys_scope={scope}"
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=f"sys_id,{field},sys_scope",
            limit=1,
            offset=0,
            display_value=True,
        )
        return rows[0] if rows else None
    except Exception:
        return None


def _create_record(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    body: Dict[str, Any],
    timeout: int = 30,
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/{table}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request(
            "POST",
            url,
            json=body,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if "result" not in data:
            return {"success": False, "message": f"No result in response for {table}"}
        invalidate_query_cache(table=table)
        return {"success": True, "result": data["result"]}
    except Exception as e:
        logger.error("Error creating record in %s: %s", table, e)
        return {"success": False, "message": f"Error creating record in {table}: {e}"}


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------


def create_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    page_id: str,
    title: str,
    scope: str,
    description: Optional[str] = None,
    css: Optional[str] = None,
    internal: bool = False,
    public: bool = False,
    draft: bool = False,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_page", "id", page_id)
    if existing:
        return {
            "success": False,
            "message": f"Page with id '{page_id}' already exists.",
            "existing_sys_id": existing.get("sys_id"),
            "existing_scope": existing.get("sys_scope"),
        }

    body: Dict[str, Any] = {"id": page_id, "title": title, "sys_scope": scope}
    if description:
        body["description"] = description
    if css:
        body["css"] = css
    if internal:
        body["internal"] = "true"
    if public:
        body["public"] = "true"
    if draft:
        body["draft"] = "true"
    if category:
        body["category"] = category

    result = _create_record(config, auth_manager, "sp_page", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created page: {record.get('title')} (/{record.get('id')})",
        "sys_id": record.get("sys_id"),
        "id": record.get("id"),
        "title": record.get("title"),
        "hint": "Use manage_portal_layout add_container to add layout containers to this page.",
    }


def update_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sys_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    css: Optional[str] = None,
    internal: Optional[bool] = None,
    public: Optional[bool] = None,
    draft: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if description is not None:
        body["description"] = description
    if css is not None:
        body["css"] = css
    if internal is not None:
        body["internal"] = str(internal).lower()
    if public is not None:
        body["public"] = str(public).lower()
    if draft is not None:
        body["draft"] = str(draft).lower()

    if not body:
        return {"success": False, "message": "No fields to update"}

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sp_page",
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["title", "id", "public"],
        )

    url = f"{config.instance_url}/api/now/table/sp_page/{sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        invalidate_query_cache(table="sp_page")
        record = data.get("result", {})
        return {
            "success": True,
            "message": f"Updated page: {record.get('title')}",
            "sys_id": sys_id,
        }
    except Exception as e:
        return {"success": False, "message": f"Error updating page: {e}"}


def create_container(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sp_page: str,
    order: int = 100,
    width: Optional[str] = None,
    css_class: Optional[str] = None,
    background_color: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"sp_page": sp_page, "order": str(order)}
    if width:
        body["width"] = width
    if css_class:
        body["css_class"] = css_class
    if background_color:
        body["background_color"] = background_color

    result = _create_record(config, auth_manager, "sp_container", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": "Created container",
        "sys_id": record.get("sys_id"),
        "page": sp_page,
        "order": order,
        "hint": "Use manage_portal_layout add_row to add rows to this container.",
    }


def create_row(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sp_container: str,
    order: int = 100,
    css_class: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"sp_container": sp_container, "order": str(order)}
    if css_class:
        body["css_class"] = css_class

    result = _create_record(config, auth_manager, "sp_row", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": "Created row",
        "sys_id": record.get("sys_id"),
        "container": sp_container,
        "hint": "Use manage_portal_layout add_column to add columns to this row.",
    }


def create_column(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sp_row: str,
    order: int = 100,
    size: int = 12,
    css_class: Optional[str] = None,
) -> Dict[str, Any]:
    if size < 1 or size > 12:
        return {"success": False, "message": "Column size must be between 1 and 12"}

    body: Dict[str, Any] = {"sp_row": sp_row, "order": str(order), "size": str(size)}
    if css_class:
        body["css_class"] = css_class

    result = _create_record(config, auth_manager, "sp_column", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created column (size={size})",
        "sys_id": record.get("sys_id"),
        "row": sp_row,
        "size": size,
        "hint": "Use manage_portal_layout place_widget to place widgets in this column.",
    }


def place_widget(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    sp_widget: str,
    sp_column: str,
    order: int = 0,
    widget_parameters: Optional[str] = None,
    css: Optional[str] = None,
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/{INSTANCE_TABLE}"
    body: Dict[str, Any] = {
        "sp_widget": sp_widget,
        "sp_column": sp_column,
        "order": str(order),
    }
    if widget_parameters:
        body["widget_parameters"] = widget_parameters
    if css:
        body["css"] = css

    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "result" not in data:
            return {"success": False, "message": "Failed to create widget instance"}
        result = data["result"]
        invalidate_query_cache(table=INSTANCE_TABLE)
        return {
            "success": True,
            "message": "Created widget instance",
            "instance_id": result.get("sys_id"),
            "widget": result.get("sp_widget"),
            "column": result.get("sp_column"),
        }
    except Exception as e:
        logger.error("Error placing widget: %s", e)
        return {"success": False, "message": f"Error placing widget: {e}"}


def move_widget(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    instance_id: str,
    sp_column: Optional[str] = None,
    order: Optional[int] = None,
    widget_parameters: Optional[str] = None,
    css: Optional[str] = None,
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/{INSTANCE_TABLE}/{instance_id}"
    body: Dict[str, Any] = {}
    if order is not None:
        body["order"] = str(order)
    if sp_column is not None:
        body["sp_column"] = sp_column
    if widget_parameters is not None:
        body["widget_parameters"] = widget_parameters
    if css is not None:
        body["css"] = css

    if not body:
        return {"success": True, "message": "No changes to update"}

    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "result" not in data:
            return {"success": False, "message": "Failed to update widget instance"}
        result = data["result"]
        invalidate_query_cache(table=INSTANCE_TABLE)
        return {
            "success": True,
            "message": f"Updated widget instance {instance_id}",
            "instance_id": result.get("sys_id"),
        }
    except Exception as e:
        logger.error("Error moving widget: %s", e)
        return {"success": False, "message": f"Error moving widget: {e}"}
