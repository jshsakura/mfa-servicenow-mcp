"""Scripted REST API service layer.

Two-level structure: a service definition (``sys_ws_definition``) owns one or
more resources/operations (``sys_ws_operation``). The tool wrapper in
``tools/scripted_rest_tools.py`` is a thin dispatch over these functions so the
tool module can import them without a circular cycle.

Kept separate from ``sn_write`` on purpose: creating a resource must connect it
to its parent definition and resolve that parent by name or sys_id — a single
raw table write cannot express the header/detail relationship safely.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

DEF_TABLE = "sys_ws_definition"
OP_TABLE = "sys_ws_operation"

_DEF_META = (
    "sys_id,name,service_id,short_description,active,consumes,produces,sys_scope,sys_updated_on"
)
_OP_META = (
    "sys_id,name,http_method,relative_path,operation_uri,active,"
    "web_service_definition,requires_authentication,requires_acl_authorization,sys_updated_on"
)
_OP_FULL = _OP_META + ",operation_script,consumes,produces"

# Fields an update may touch on a resource. operation_uri is derived by the
# platform from service base + relative_path; we never set it directly.
_OP_UPDATE_FIELDS = (
    "http_method",
    "relative_path",
    "operation_script",
    "active",
    "consumes",
    "produces",
    "requires_authentication",
    "requires_acl_authorization",
)
_DEF_UPDATE_FIELDS = ("service_id", "short_description", "active", "consumes", "produces")


def _dv(v: Any) -> Any:
    """Unwrap a display-value dict to its value; pass scalars through."""
    return v.get("display_value") if isinstance(v, dict) else v


def _resolve_service(
    config: ServerConfig, auth_manager: AuthManager, ident: str
) -> Optional[Dict[str, Any]]:
    """Resolve a service definition by ``sys_id:<id>`` or by name."""
    if ident.startswith("sys_id:"):
        query = f"sys_id={ident.replace('sys_id:', '')}"
    else:
        query = f"name={ident}"
    records, _ = sn_query_page(
        config,
        auth_manager,
        table=DEF_TABLE,
        query=query,
        fields=_DEF_META,
        limit=1,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    return records[0] if records else None


def _resolve_operation(
    config: ServerConfig, auth_manager: AuthManager, sys_id: str
) -> Optional[Dict[str, Any]]:
    records, _ = sn_query_page(
        config,
        auth_manager,
        table=OP_TABLE,
        query=f"sys_id={sys_id}",
        fields=_OP_FULL,
        limit=1,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    return records[0] if records else None


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def list_services(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    query: Optional[str] = None,
    active: Optional[bool] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    """List Scripted REST service definitions."""
    parts: List[str] = []
    if active is not None:
        parts.append(f"active={str(active).lower()}")
    if query:
        parts.append(f"nameLIKE{query}")
    query_string = "^".join(parts)

    if count_only:
        return {"success": True, "count": sn_count(config, auth_manager, DEF_TABLE, query_string)}

    records, _ = sn_query_page(
        config,
        auth_manager,
        table=DEF_TABLE,
        query=query_string,
        fields=_DEF_META,
        limit=min(limit, 50),
        offset=offset,
        display_value=True,
        fail_silently=False,
    )
    services = [
        {
            "sys_id": r.get("sys_id"),
            "name": r.get("name"),
            "service_id": r.get("service_id"),
            "short_description": r.get("short_description"),
            "active": _dv(r.get("active")) == "true",
            "scope": _dv(r.get("sys_scope")),
            "updated_on": r.get("sys_updated_on"),
        }
        for r in records
    ]
    return {
        "success": True,
        "message": f"Found {len(services)} scripted REST services",
        "services": services,
        "total": len(services),
        "limit": limit,
        "offset": offset,
    }


def get_service(
    config: ServerConfig, auth_manager: AuthManager, *, service_id: str
) -> Dict[str, Any]:
    """Get a service definition plus its resource/operation headers."""
    svc = _resolve_service(config, auth_manager, service_id)
    if svc is None:
        result: Dict[str, Any] = {
            "success": False,
            "message": f"Scripted REST service not found: {service_id}",
        }
        if not service_id.startswith("sys_id:"):
            near, _ = sn_query_page(
                config,
                auth_manager,
                table=DEF_TABLE,
                query=f"nameLIKE{service_id}",
                fields="name,sys_id,service_id",
                limit=5,
                offset=0,
                display_value=False,
                fail_silently=True,
            )
            hits = [
                {
                    "name": r.get("name"),
                    "sys_id": r.get("sys_id"),
                    "service_id": r.get("service_id"),
                }
                for r in near
                if r.get("name")
            ]
            if hits:
                result["did_you_mean"] = hits
                result["hint"] = "No exact match. Retry with a name above or sys_id:<sys_id>."
        return result

    ops, _ = sn_query_page(
        config,
        auth_manager,
        table=OP_TABLE,
        query=f"web_service_definition={svc['sys_id']}",
        fields=_OP_META,
        limit=100,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    resources = [
        {
            "sys_id": o.get("sys_id"),
            "name": o.get("name"),
            "http_method": o.get("http_method"),
            "relative_path": o.get("relative_path"),
            "operation_uri": o.get("operation_uri"),
            "active": o.get("active") == "true",
        }
        for o in ops
    ]
    return {
        "success": True,
        "message": f"Found scripted REST service: {svc.get('name')}",
        "service": {
            "sys_id": svc.get("sys_id"),
            "name": svc.get("name"),
            "service_id": svc.get("service_id"),
            "short_description": svc.get("short_description"),
            "active": svc.get("active") == "true",
            "consumes": svc.get("consumes"),
            "produces": svc.get("produces"),
        },
        "resources": resources,
        "resource_count": len(resources),
    }


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def create_service(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    service_id: Optional[str] = None,
    short_description: Optional[str] = None,
    active: bool = True,
    consumes: Optional[str] = None,
    produces: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a Scripted REST service definition (``sys_ws_definition``)."""
    url = f"{config.instance_url}/api/now/table/{DEF_TABLE}"
    body: Dict[str, Any] = {"name": name, "active": str(active).lower()}
    if service_id:
        body["service_id"] = service_id
    if short_description:
        body["short_description"] = short_description
    if consumes:
        body["consumes"] = consumes
    if produces:
        body["produces"] = produces

    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": "Failed to create scripted REST service"}
        invalidate_query_cache(table=DEF_TABLE)
        return {
            "success": True,
            "message": f"Created scripted REST service: {result.get('name')}",
            "sys_id": result.get("sys_id"),
            "name": result.get("name"),
            "service_id": result.get("service_id"),
        }
    except Exception as e:
        logger.error(f"Error creating scripted REST service: {e}")
        return {"success": False, "message": f"Error creating scripted REST service: {str(e)}"}


def create_resource(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    service: str,
    name: str,
    http_method: str,
    relative_path: str = "/",
    operation_script: Optional[str] = None,
    active: bool = True,
    consumes: Optional[str] = None,
    produces: Optional[str] = None,
    requires_authentication: Optional[bool] = None,
    requires_acl_authorization: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a resource/operation (``sys_ws_operation``) under a service.

    ``service`` resolves the parent by ``sys_id:<id>`` or by name so the
    caller never has to pre-look-up the definition's sys_id.
    """
    parent = _resolve_service(config, auth_manager, service)
    if parent is None:
        return {"success": False, "message": f"Parent scripted REST service not found: {service}"}

    url = f"{config.instance_url}/api/now/table/{OP_TABLE}"
    body: Dict[str, Any] = {
        "name": name,
        "web_service_definition": parent["sys_id"],
        "http_method": http_method.upper(),
        "relative_path": relative_path,
        "active": str(active).lower(),
    }
    if operation_script:
        body["operation_script"] = operation_script
    if consumes:
        body["consumes"] = consumes
    if produces:
        body["produces"] = produces
    if requires_authentication is not None:
        body["requires_authentication"] = str(requires_authentication).lower()
    if requires_acl_authorization is not None:
        body["requires_acl_authorization"] = str(requires_acl_authorization).lower()

    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": "Failed to create scripted REST resource"}
        invalidate_query_cache(table=OP_TABLE)
        return {
            "success": True,
            "message": f"Created scripted REST resource: {result.get('name')}",
            "sys_id": result.get("sys_id"),
            "name": result.get("name"),
            "http_method": result.get("http_method"),
            "operation_uri": result.get("operation_uri"),
            "service_sys_id": parent["sys_id"],
        }
    except Exception as e:
        logger.error(f"Error creating scripted REST resource: {e}")
        return {"success": False, "message": f"Error creating scripted REST resource: {str(e)}"}


def update_resource(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    resource_id: str,
    dry_run: bool = False,
    **fields: Any,
) -> Dict[str, Any]:
    """Update a resource/operation's header metadata or script body."""
    op = _resolve_operation(config, auth_manager, resource_id)
    if op is None:
        return {"success": False, "message": f"Scripted REST resource not found: {resource_id}"}

    sys_id = op["sys_id"]
    body: Dict[str, Any] = {}
    for f in _OP_UPDATE_FIELDS:
        v = fields.get(f)
        if v is None:
            continue
        if f == "http_method":
            body[f] = str(v).upper()
        elif isinstance(v, bool):
            body[f] = str(v).lower()
        else:
            body[f] = v

    if not body:
        return {
            "success": True,
            "message": f"No changes to update for resource: {op.get('name')}",
            "sys_id": sys_id,
        }

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=OP_TABLE,
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["name", "http_method", "relative_path"],
        )

    url = f"{config.instance_url}/api/now/table/{OP_TABLE}/{sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": f"Failed to update resource: {op.get('name')}"}
        invalidate_query_cache(table=OP_TABLE)
        return {
            "success": True,
            "message": f"Updated scripted REST resource: {result.get('name')}",
            "sys_id": result.get("sys_id"),
            "name": result.get("name"),
        }
    except Exception as e:
        logger.error(f"Error updating scripted REST resource: {e}")
        return {"success": False, "message": f"Error updating scripted REST resource: {str(e)}"}


def update_service(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    ident: str,
    dry_run: bool = False,
    **fields: Any,
) -> Dict[str, Any]:
    """Update a service definition's header metadata.

    ``ident`` is how the definition is located (name or ``sys_id:<id>``); the
    updatable ``service_id`` URL segment arrives via ``fields`` — the two are
    intentionally distinct despite the similar names.
    """
    svc = _resolve_service(config, auth_manager, ident)
    if svc is None:
        return {"success": False, "message": f"Scripted REST service not found: {ident}"}

    sys_id = svc["sys_id"]
    body: Dict[str, Any] = {}
    for f in _DEF_UPDATE_FIELDS:
        v = fields.get(f)
        if v is None:
            continue
        body[f] = str(v).lower() if isinstance(v, bool) else v

    if not body:
        return {
            "success": True,
            "message": f"No changes to update for service: {svc.get('name')}",
            "sys_id": sys_id,
        }

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table=DEF_TABLE,
            sys_id=sys_id,
            proposed=body,
            identifier_fields=["name", "service_id", "active"],
        )

    url = f"{config.instance_url}/api/now/table/{DEF_TABLE}/{sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request("PATCH", url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json().get("result")
        if not result:
            return {"success": False, "message": f"Failed to update service: {svc.get('name')}"}
        invalidate_query_cache(table=DEF_TABLE)
        return {
            "success": True,
            "message": f"Updated scripted REST service: {result.get('name')}",
            "sys_id": result.get("sys_id"),
            "name": result.get("name"),
        }
    except Exception as e:
        logger.error(f"Error updating scripted REST service: {e}")
        return {"success": False, "message": f"Error updating scripted REST service: {str(e)}"}
