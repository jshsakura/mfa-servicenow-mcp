"""
Script Include tools for the ServiceNow MCP server.

This module provides tools for managing script includes in ServiceNow.
"""

import logging
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import script_include as _si_svc
from servicenow_mcp.tools.sn_api import sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class ListScriptIncludesParams(BaseModel):
    """Parameters for listing script includes."""

    limit: int = Field(default=10, description="Maximum number of script includes to return")
    offset: int = Field(default=0, description="Offset for pagination")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    client_callable: Optional[bool] = Field(
        default=None, description="Filter by client callable status"
    )
    query: Optional[str] = Field(default=None, description="Search query for script includes")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records. Uses lightweight Aggregate API.",
    )


class GetScriptIncludeParams(BaseModel):
    """Parameters for getting a script include."""

    script_include_id: str = Field(..., description="Script include ID or name")


@register_tool(
    name="list_script_includes",
    params=ListScriptIncludesParams,
    description="List script includes filtered by name/scope/active. Returns metadata without script bodies.",
    serialization="raw_dict",
    return_type=dict,
)
def list_script_includes(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListScriptIncludesParams,
) -> Dict[str, Any]:
    """List script includes from ServiceNow."""
    try:
        query_parts = []

        if params.active is not None:
            query_parts.append(f"active={str(params.active).lower()}")

        if params.client_callable is not None:
            query_parts.append(f"client_callable={str(params.client_callable).lower()}")

        if params.query:
            query_parts.append(f"nameLIKE{params.query}")

        query_string = "^".join(query_parts) if query_parts else ""

        if params.count_only:
            count = sn_count(config, auth_manager, "sys_script_include", query_string)
            return {"success": True, "count": count}

        fields = "sys_id,name,description,api_name,client_callable,active,access,sys_created_on,sys_updated_on,sys_created_by,sys_updated_by"

        records, total_count = sn_query_page(
            config,
            auth_manager,
            table="sys_script_include",
            query=query_string,
            fields=fields,
            limit=min(params.limit, 50),
            offset=params.offset,
            display_value=True,
            fail_silently=False,
        )

        script_includes = []

        for item in records:
            created_by_raw = item.get("sys_created_by")
            updated_by_raw = item.get("sys_updated_by")
            script_include = {
                "sys_id": item.get("sys_id"),
                "name": item.get("name"),
                "description": item.get("description"),
                "api_name": item.get("api_name"),
                "client_callable": item.get("client_callable") == "true",
                "active": item.get("active") == "true",
                "access": item.get("access"),
                "created_on": item.get("sys_created_on"),
                "updated_on": item.get("sys_updated_on"),
                "created_by": (
                    created_by_raw.get("display_value")
                    if isinstance(created_by_raw, dict)
                    else None
                ),
                "updated_by": (
                    updated_by_raw.get("display_value")
                    if isinstance(updated_by_raw, dict)
                    else None
                ),
            }
            script_includes.append(script_include)

        return {
            "success": True,
            "message": f"Found {len(script_includes)} script includes",
            "script_includes": script_includes,
            "total": len(script_includes),
            "limit": params.limit,
            "offset": params.offset,
        }

    except Exception as e:
        logger.error(f"Error listing script includes: {e}")
        return {
            "success": False,
            "message": f"Error listing script includes: {str(e)}",
            "script_includes": [],
            "total": 0,
            "limit": params.limit,
            "offset": params.offset,
        }


@register_tool(
    name="get_script_include",
    params=GetScriptIncludeParams,
    description="Retrieve a single script include with full script body by sys_id or name.",
    serialization="raw_dict",
    return_type=dict,
)
def get_script_include(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetScriptIncludeParams,
) -> Dict[str, Any]:
    """Get a specific script include from ServiceNow."""
    try:
        fields = "sys_id,name,script,description,api_name,client_callable,active,access,sys_created_on,sys_updated_on,sys_created_by,sys_updated_by"

        if params.script_include_id.startswith("sys_id:"):
            sys_id = params.script_include_id.replace("sys_id:", "")
            query = f"sys_id={sys_id}"
        else:
            query = f"name={params.script_include_id}"

        records, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_script_include",
            query=query,
            fields=fields,
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )

        if not records:
            return {
                "success": False,
                "message": f"Script include not found: {params.script_include_id}",
            }

        item = records[0]

        created_by_raw = item.get("sys_created_by")
        updated_by_raw = item.get("sys_updated_by")
        script_include = {
            "sys_id": item.get("sys_id"),
            "name": item.get("name"),
            "script": item.get("script"),
            "description": item.get("description"),
            "api_name": item.get("api_name"),
            "client_callable": item.get("client_callable") == "true",
            "active": item.get("active") == "true",
            "access": item.get("access"),
            "created_on": item.get("sys_created_on"),
            "updated_on": item.get("sys_updated_on"),
            "created_by": (
                created_by_raw.get("display_value") if isinstance(created_by_raw, dict) else None
            ),
            "updated_by": (
                updated_by_raw.get("display_value") if isinstance(updated_by_raw, dict) else None
            ),
        }

        return {
            "success": True,
            "message": f"Found script include: {item.get('name')}",
            "script_include": script_include,
        }

    except Exception as e:
        logger.error(f"Error getting script include: {e}")
        return {
            "success": False,
            "message": f"Error getting script include: {str(e)}",
        }


# ---------------------------------------------------------------------------
# manage_script_include — bundled CRUD + execute for sys_script_include
# ---------------------------------------------------------------------------

_SI_UPDATE_FIELDS = (
    "script",
    "description",
    "api_name",
    "client_callable",
    "active",
    "access",
)


class ManageScriptIncludeParams(BaseModel):
    """Manage script includes — table: sys_script_include.

    Required per action:
      create:  name, script
      update:  script_include_id, at least one field
      delete:  script_include_id
      execute: name (and optionally method, exec_params)
    """

    action: Literal["create", "update", "delete", "execute"] = Field(...)

    # Identifier (update/delete uses script_include_id; create/execute use name)
    script_include_id: Optional[str] = Field(
        default=None, description="sys_id or name (update/delete)"
    )
    name: Optional[str] = Field(default=None, description="SI name (create/execute)")

    # Create + update
    script: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    api_name: Optional[str] = Field(default=None)
    client_callable: Optional[bool] = Field(default=None)
    active: Optional[bool] = Field(default=None)
    access: Optional[str] = Field(default=None)

    # Execute-specific
    method: Optional[str] = Field(default=None, description="Method to invoke (execute)")
    # Renamed from `params` to avoid clash with the outer Pydantic-arg name
    # convention; mapped onto ExecuteScriptIncludeParams.params at dispatch.
    exec_params: Optional[Dict[str, str]] = Field(
        default=None, description="Key-value args for the executed method"
    )

    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageScriptIncludeParams":
        if self.action == "create":
            if not self.name:
                raise ValueError("name is required for action='create'")
            if not self.script:
                raise ValueError("script is required for action='create'")
        elif self.action == "update":
            if not self.script_include_id:
                raise ValueError("script_include_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _SI_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        elif self.action == "delete":
            if not self.script_include_id:
                raise ValueError("script_include_id is required for action='delete'")
        elif self.action == "execute":
            if not self.name:
                raise ValueError("name is required for action='execute'")
        return self


@register_tool(
    name="manage_script_include",
    params=ManageScriptIncludeParams,
    description="Create/update/delete/execute a script include (table: sys_script_include).",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_script_include(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageScriptIncludeParams,
) -> Dict[str, Any]:
    if params.action == "create":
        return _si_svc.create(
            config,
            auth_manager,
            name=params.name,
            script=params.script,
            description=params.description,
            api_name=params.api_name,
            client_callable=params.client_callable if params.client_callable is not None else False,
            active=params.active if params.active is not None else True,
            access=params.access if params.access is not None else "package_private",
        )
    if params.action == "update":
        kwargs: Dict[str, Any] = {
            "script_include_id": params.script_include_id,
            "dry_run": params.dry_run,
        }
        for f in _SI_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _si_svc.update(config, auth_manager, **kwargs)
    if params.action == "delete":
        return _si_svc.delete(
            config,
            auth_manager,
            script_include_id=params.script_include_id,
        )
    # execute
    return _si_svc.execute(
        config,
        auth_manager,
        name=params.name,
        method=params.method or "execute",
        params=params.exec_params,
    )
