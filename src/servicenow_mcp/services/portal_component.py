"""Service layer for portal component creation (widget, provider, header/footer, theme, template, ui_page)."""

import logging
from typing import Any, Dict, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)


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


def create_widget(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    scope: str,
    widget_id: Optional[str] = None,
    template: Optional[str] = None,
    css: Optional[str] = None,
    script: Optional[str] = None,
    client_script: Optional[str] = None,
    link: Optional[str] = None,
    internal: bool = False,
    data_table: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_widget", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"Widget with name '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
            "existing_scope": existing.get("sys_scope"),
        }
    if widget_id:
        existing_id = _check_duplicate(config, auth_manager, "sp_widget", "id", widget_id)
        if existing_id:
            return {
                "success": False,
                "message": f"Widget with id '{widget_id}' already exists.",
                "existing_sys_id": existing_id.get("sys_id"),
                "existing_scope": existing_id.get("sys_scope"),
            }

    body: Dict[str, Any] = {"name": name, "sys_scope": scope}
    if widget_id:
        body["id"] = widget_id
    if template is not None:
        body["template"] = template
    if css is not None:
        body["css"] = css
    if script is not None:
        body["script"] = script
    if client_script is not None:
        body["client_script"] = client_script
    if link is not None:
        body["link"] = link
    if internal:
        body["internal"] = "true"
    if data_table:
        body["data_table"] = data_table
    if description:
        body["description"] = description

    result = _create_record(config, auth_manager, "sp_widget", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created widget: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "id": record.get("id"),
        "name": record.get("name"),
    }


def create_angular_provider(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    script: str,
    scope: str,
    provider_type: str = "factory",
    description: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_angular_provider", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"Angular provider '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {
        "name": name,
        "script": script,
        "type": provider_type,
        "sys_scope": scope,
    }
    if description:
        body["description"] = description

    result = _create_record(config, auth_manager, "sp_angular_provider", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created angular provider: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
        "type": record.get("type"),
    }


def create_header_footer(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    scope: str,
    template: Optional[str] = None,
    css: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_header_footer", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"Header/footer '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": name, "sys_scope": scope}
    if template is not None:
        body["template"] = template
    if css is not None:
        body["css"] = css

    result = _create_record(config, auth_manager, "sp_header_footer", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created header/footer: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }


def create_css_theme(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    scope: str,
    css: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_css", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"CSS theme '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": name, "sys_scope": scope}
    if css is not None:
        body["css"] = css

    result = _create_record(config, auth_manager, "sp_css", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created CSS theme: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }


def create_ng_template(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    template_id: str,
    template: str,
    scope: str,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_ng_template", "id", template_id, scope)
    if existing:
        return {
            "success": False,
            "message": f"ng-template with id '{template_id}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {
        "id": template_id,
        "template": template,
        "sys_scope": scope,
    }

    result = _create_record(config, auth_manager, "sp_ng_template", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created ng-template: {record.get('id')}",
        "sys_id": record.get("sys_id"),
        "id": record.get("id"),
    }


def create_ui_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    scope: str,
    html: Optional[str] = None,
    client_script: Optional[str] = None,
    processing_script: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sys_ui_page", "name", name, scope)
    if existing:
        return {
            "success": False,
            "message": f"UI page '{name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": name, "sys_scope": scope}
    if html is not None:
        body["html"] = html
    if client_script is not None:
        body["client_script"] = client_script
    if processing_script is not None:
        body["processing_script"] = processing_script
    if description:
        body["description"] = description
    if category:
        body["category"] = category

    result = _create_record(config, auth_manager, "sys_ui_page", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created UI page: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }
