"""Service layer for portal layout CRUD (page, container, row, column, widget instance)."""

import logging
import re
from typing import Any, Dict, List, Optional

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
        # sp_page has `short_description`, not `description` — the latter is not a
        # column, and ServiceNow drops an unknown field from a write without
        # complaining, so every description set through this tool was discarded
        # while the call reported success.
        body["short_description"] = description
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
        body["short_description"] = description  # see create(): sp_page has no `description`
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


_SYS_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _ref(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return str(value or "")


def replace_widget(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    instance_id: str,
    sp_widget: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Point an existing widget instance at a different widget.

    Only sp_instance.sp_widget changes; widget_parameters, css, column and order
    stay as they are. Every read here raises on failure (fail_silently=False) so
    an unreadable row is a refusal, never an empty answer.
    """

    def _read(table: str, query: str, fields: str, limit: int = 5) -> List[Dict[str, Any]]:
        invalidate_query_cache(table=table)
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=fields,
            limit=limit,
            offset=0,
            fail_silently=False,
        )
        return rows

    keep = "sp_widget,widget_parameters,css,sp_column,order"
    try:
        inst = _read(INSTANCE_TABLE, f"sys_id={instance_id}", keep, 1)
        if not inst:
            return {"success": False, "message": f"No widget instance {instance_id}."}
        column = "sys_id" if _SYS_ID_RE.match(sp_widget) else "id"
        matches = _read("sp_widget", f"{column}={sp_widget}", "sys_id,id,name,sys_scope")
        old_id = _ref(inst[0].get("sp_widget"))
        old = _read("sp_widget", f"sys_id={old_id}", "sys_id,id,name", 1) if old_id else []
    except Exception as e:
        return {"success": False, "message": f"Could not read the instance or widget: {e}"}

    if len(matches) != 1:
        return {
            "success": False,
            "message": (
                f"No sp_widget with {column}='{sp_widget}'."
                if not matches
                else f"{len(matches)} widgets match {column}='{sp_widget}'; pass the sys_id."
            ),
            "candidates": [
                {
                    "sys_id": r.get("sys_id"),
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "scope": _ref(r.get("sys_scope")),
                }
                for r in matches
            ],
        }
    new = matches[0]
    new_sys_id = str(new.get("sys_id"))
    summary = {
        "instance_id": instance_id,
        "old_widget": {
            "sys_id": old_id,
            "id": old[0].get("id") if old else None,
            "name": old[0].get("name") if old else None,
        },
        "new_widget": {"sys_id": new_sys_id, "id": new.get("id"), "name": new.get("name")},
    }
    if old_id == new_sys_id:
        return {"success": True, "message": "Instance already uses this widget", **summary}
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "operation": "replace_widget",
            **summary,
            "untouched": ["widget_parameters", "css", "sp_column", "order"],
        }

    url = f"{config.instance_url}/api/now/table/{INSTANCE_TABLE}/{instance_id}"
    try:
        response = auth_manager.make_request(
            "PATCH",
            url,
            json={"sp_widget": new_sys_id},
            headers=auth_manager.get_headers(),
            timeout=30,
        )
        response.raise_for_status()
    except Exception as e:
        logger.error("Error replacing widget: %s", e)
        return {"success": False, "message": f"Error replacing widget: {e}"}

    problems: List[str] = []
    try:
        after = _read(INSTANCE_TABLE, f"sys_id={instance_id}", keep, 1)
        if not after:
            raise RuntimeError("instance not found on read-back")
        if _ref(after[0].get("sp_widget")) != new_sys_id:
            problems.append("sp_widget did not change")
        for f in ("widget_parameters", "css", "sp_column", "order"):
            if _ref(after[0].get(f)) != _ref(inst[0].get(f)):
                problems.append(f"{f} changed unexpectedly")
    except Exception as e:
        problems.append(f"could not read back ({e})")
    return {
        "success": True,
        "complete": not problems,
        "message": (
            "Replaced widget on instance"
            if not problems
            else "Replace sent but NOT confirmed: " + "; ".join(problems)
        ),
        **summary,
        "missing": problems,
    }
