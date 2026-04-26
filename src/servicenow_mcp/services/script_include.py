"""Script include (sys_script_include) service layer.

Reusable API logic for create / update / delete / execute operations on the
ServiceNow ``sys_script_include`` table. Both the public ``manage_script_include``
MCP tool and the legacy wrapper functions in
``servicenow_mcp.tools.script_include_tools`` route through this module.

The ``ScriptIncludeResponse`` model lives here so that anything in the tools
module can import it without creating a circular import cycle when wrappers
route through services.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_count, sn_query_page
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

_SI_FIELDS = "sys_id,name,client_callable"

_SI_UPDATE_FIELDS = (
    "script",
    "description",
    "api_name",
    "client_callable",
    "active",
    "access",
)


class ScriptIncludeResponse(BaseModel):
    """Response from script include operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    script_include_id: Optional[str] = Field(
        default=None, description="ID of the affected script include"
    )
    script_include_name: Optional[str] = Field(
        default=None, description="Name of the affected script include"
    )


def _fetch_si(
    config: ServerConfig,
    auth_manager: AuthManager,
    script_include_id: str,
) -> dict | None:
    """Resolve a script include by sys_id or name. Returns the raw record or None."""
    if script_include_id.startswith("sys_id:"):
        query = f"sys_id={script_include_id.replace('sys_id:', '')}"
    else:
        query = f"name={script_include_id}"

    records, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_script_include",
        query=query,
        fields=_SI_FIELDS,
        limit=1,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    return records[0] if records else None


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    script: str,
    description: Optional[str] = None,
    api_name: Optional[str] = None,
    client_callable: bool = False,
    active: bool = True,
    access: str = "package_private",
) -> ScriptIncludeResponse:
    """Create a new script include."""
    url = f"{config.instance_url}/api/now/table/sys_script_include"
    body: Dict[str, Any] = {
        "name": name,
        "script": script,
        "active": str(active).lower(),
        "client_callable": str(client_callable).lower(),
        "access": access,
    }
    if description:
        body["description"] = description
    if api_name:
        body["api_name"] = api_name

    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "result" not in data:
            return ScriptIncludeResponse(success=False, message="Failed to create script include")
        result = data["result"]
        invalidate_query_cache(table="sys_script_include")
        return ScriptIncludeResponse(
            success=True,
            message=f"Created script include: {result.get('name')}",
            script_include_id=result.get("sys_id"),
            script_include_name=result.get("name"),
        )
    except Exception as e:
        logger.error(f"Error creating script include: {e}")
        return ScriptIncludeResponse(
            success=False,
            message=f"Error creating script include: {str(e)}",
        )


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    script_include_id: str,
    script: Optional[str] = None,
    description: Optional[str] = None,
    api_name: Optional[str] = None,
    client_callable: Optional[bool] = None,
    active: Optional[bool] = None,
    access: Optional[str] = None,
    dry_run: bool = False,
) -> ScriptIncludeResponse:
    """Update an existing script include. Supports dry-run preview."""
    item = _fetch_si(config, auth_manager, script_include_id)
    if item is None:
        return ScriptIncludeResponse(
            success=False,
            message=f"Script include not found: {script_include_id}",
        )

    sys_id = item["sys_id"]
    si_name = item["name"]
    url = f"{config.instance_url}/api/now/table/sys_script_include/{sys_id}"

    body: Dict[str, Any] = {}
    if script is not None:
        body["script"] = script
    if description is not None:
        body["description"] = description
    if api_name is not None:
        body["api_name"] = api_name
    if client_callable is not None:
        body["client_callable"] = str(client_callable).lower()
    if active is not None:
        body["active"] = str(active).lower()
    if access is not None:
        body["access"] = access

    if not body:
        return ScriptIncludeResponse(
            success=True,
            message=f"No changes to update for script include: {si_name}",
            script_include_id=sys_id,
            script_include_name=si_name,
        )

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sys_script_include",
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["name", "api_name", "active"],
        )

    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        if "result" not in data:
            return ScriptIncludeResponse(
                success=False,
                message=f"Failed to update script include: {si_name}",
            )
        result = data["result"]
        invalidate_query_cache(table="sys_script_include")
        return ScriptIncludeResponse(
            success=True,
            message=f"Updated script include: {result.get('name')}",
            script_include_id=result.get("sys_id"),
            script_include_name=result.get("name"),
        )
    except Exception as e:
        logger.error(f"Error updating script include: {e}")
        return ScriptIncludeResponse(
            success=False,
            message=f"Error updating script include: {str(e)}",
        )


def delete(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    script_include_id: str,
) -> ScriptIncludeResponse:
    """Permanently delete a script include."""
    item = _fetch_si(config, auth_manager, script_include_id)
    if item is None:
        return ScriptIncludeResponse(
            success=False,
            message=f"Script include not found: {script_include_id}",
        )

    sys_id = item["sys_id"]
    name = item["name"]
    url = f"{config.instance_url}/api/now/table/sys_script_include/{sys_id}"

    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("DELETE", url, headers=headers, timeout=30)
        response.raise_for_status()
        invalidate_query_cache(table="sys_script_include")
        return ScriptIncludeResponse(
            success=True,
            message=f"Deleted script include: {name}",
            script_include_id=sys_id,
            script_include_name=name,
        )
    except Exception as e:
        logger.error(f"Error deleting script include: {e}")
        return ScriptIncludeResponse(
            success=False,
            message=f"Error deleting script include: {str(e)}",
        )


def execute(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    method: str = "execute",
    params: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute a client-callable script include via GlideAjax REST endpoint."""
    try:
        item = _fetch_si(config, auth_manager, name)
        if item is None:
            return {"success": False, "message": f"Script include not found: {name}"}

        if item.get("client_callable") not in ("true", True):
            return {
                "success": False,
                "message": f"Script include '{name}' is not client-callable. "
                "Set client_callable=true to enable remote execution.",
            }

        ajax_params: Dict[str, str] = {
            "sysparm_ajax_processor": name,
            "sysparm_name": method,
        }
        if params:
            for key, value in params.items():
                ajax_params[f"sysparm_{key}"] = value

        headers = auth_manager.get_headers()
        response = auth_manager.make_request(
            "GET",
            f"{config.instance_url}/xmlhttp.do",
            params=ajax_params,
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()

        response_text = response.text
        try:
            result_data = json_fast.loads(response_text)
        except (ValueError, TypeError):
            result_data = response_text

        return {"success": True, "message": f"Executed {name}.{method}", "result": result_data}

    except Exception as e:
        logger.error(f"Error executing script include: {e}")
        return {"success": False, "message": f"Error executing script include: {str(e)}"}


_SI_FIELDS = "sys_id,name,description,api_name,client_callable,active,access,sys_created_on,sys_updated_on,sys_created_by,sys_updated_by"
_SI_FIELDS_FULL = _SI_FIELDS + ",script"


def _fmt(item: Dict[str, Any], include_script: bool = False) -> Dict[str, Any]:
    created_by = item.get("sys_created_by")
    updated_by = item.get("sys_updated_by")
    r = {
        "sys_id": item.get("sys_id"),
        "name": item.get("name"),
        "description": item.get("description"),
        "api_name": item.get("api_name"),
        "client_callable": item.get("client_callable") == "true",
        "active": item.get("active") == "true",
        "access": item.get("access"),
        "created_on": item.get("sys_created_on"),
        "updated_on": item.get("sys_updated_on"),
        "created_by": created_by.get("display_value") if isinstance(created_by, dict) else None,
        "updated_by": updated_by.get("display_value") if isinstance(updated_by, dict) else None,
    }
    if include_script:
        r["script"] = item.get("script")
    return r


def list_si(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    query: Optional[str] = None,
    active: Optional[bool] = None,
    client_callable: Optional[bool] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    """List script includes with filters."""
    parts: List[str] = []
    if active is not None:
        parts.append(f"active={str(active).lower()}")
    if client_callable is not None:
        parts.append(f"client_callable={str(client_callable).lower()}")
    if query:
        parts.append(f"nameLIKE{query}")
    qs = "^".join(parts)
    if count_only:
        return {"success": True, "count": sn_count(config, auth_manager, "sys_script_include", qs)}
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_script_include",
            query=qs,
            fields=_SI_FIELDS,
            limit=min(limit, 50),
            offset=offset,
            display_value=True,
            fail_silently=False,
        )
        return {
            "success": True,
            "message": f"Found {len(records)} script includes",
            "script_includes": [_fmt(r) for r in records],
            "total": len(records),
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"Error listing script includes: {e}")
        return {
            "success": False,
            "message": str(e),
            "script_includes": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }


def get_si(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    script_include_id: str,
) -> Dict[str, Any]:
    """Get a single script include by sys_id or name."""
    if script_include_id.startswith("sys_id:"):
        q = f"sys_id={script_include_id[7:]}"
    else:
        q = f"name={script_include_id}"
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_script_include",
            query=q,
            fields=_SI_FIELDS_FULL,
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if not records:
            return {"success": False, "message": f"Script include not found: {script_include_id}"}
        return {
            "success": True,
            "message": f"Found script include: {records[0].get('name')}",
            "script_include": _fmt(records[0], include_script=True),
        }
    except Exception as e:
        logger.error(f"Error getting script include: {e}")
        return {"success": False, "message": str(e)}
