"""
Script Include tools for the ServiceNow MCP server.

This module provides tools for managing script includes in ServiceNow.
"""

import logging
import re
from typing import Any, ClassVar, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import script_include as _si_svc
from servicenow_mcp.services.script_include import ScriptIncludeResponse
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


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

    action: Literal["list", "get", "create", "update", "delete", "execute"] = Field(...)

    # Identifier (get/update/delete: script_include_id; create/execute: name)
    script_include_id: Optional[str] = Field(default=None, description="sys_id or name")

    # list/get params
    limit: int = Field(default=10, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    query: Optional[str] = Field(default=None, description="Name search, or an encoded query")
    client_callable: Optional[bool] = Field(default=None, description="Filter by client_callable")
    count_only: bool = Field(default=False, description="Return count only")
    name: Optional[str] = Field(default=None, description="SI name")

    # Create + update
    script: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    api_name: Optional[str] = Field(default=None)
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

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"limit", "offset", "query", "count_only", "client_callable", "active"}),
        "get": frozenset({"script_include_id"}),
        "create": frozenset(
            {
                "name",
                "script",
                "description",
                "api_name",
                "client_callable",
                "active",
                "access",
                "dry_run",
            }
        ),
        "update": frozenset(
            {
                "script_include_id",
                "script",
                "description",
                "api_name",
                "client_callable",
                "active",
                "access",
                "dry_run",
            }
        ),
        "delete": frozenset({"script_include_id", "dry_run"}),
        "execute": frozenset({"name", "method", "exec_params"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageScriptIncludeParams":
        if self.action in ("list", "get"):
            pass
        elif self.action == "create":
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
            # script_include_id already accepts a name; a caller that put the
            # name in `name` said the same thing in the other slot. Seen in real
            # sessions: rejecting it cost a round-trip and changed nothing.
            if not self.script_include_id and self.name:
                self.script_include_id = self.name
            if not self.script_include_id:
                raise ValueError("script_include_id is required for action='delete'")
        elif self.action == "execute":
            # The mirror case — but only a NAME can stand in for `name`; a
            # sys_id there would be executed as a class called by its id.
            if (
                not self.name
                and self.script_include_id
                and not re.fullmatch(r"[0-9a-f]{32}", self.script_include_id)
            ):
                self.name = self.script_include_id
            if not self.name:
                raise ValueError(
                    "name is required for action='execute' (the script include's "
                    "name, not its sys_id)"
                )
        return self


@register_tool(
    name="manage_script_include",
    params=ManageScriptIncludeParams,
    description="List/get/create/update/delete/execute a script include (table: sys_script_include).",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_script_include(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageScriptIncludeParams,
) -> Dict[str, Any]:
    if params.action == "list":
        return _si_svc.list_si(
            config,
            auth_manager,
            query=params.query,
            active=params.active,
            client_callable=params.client_callable,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if params.action == "get":
        if not params.script_include_id:
            return {"success": False, "message": "script_include_id is required for action='get'"}
        return _si_svc.get_si(config, auth_manager, script_include_id=params.script_include_id)
    if params.action == "create":
        assert params.name is not None
        assert params.script is not None
        _create_result = _si_svc.create(
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
        return (
            _create_result.model_dump()
            if isinstance(_create_result, ScriptIncludeResponse)
            else _create_result
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
        update_result = _si_svc.update(config, auth_manager, **kwargs)
        if isinstance(update_result, ScriptIncludeResponse):
            return update_result.model_dump()
        return update_result
    if params.action == "delete":
        assert params.script_include_id is not None
        _delete_result = _si_svc.delete(
            config,
            auth_manager,
            script_include_id=params.script_include_id,
        )
        return (
            _delete_result.model_dump()
            if isinstance(_delete_result, ScriptIncludeResponse)
            else _delete_result
        )
    # execute
    assert params.name is not None
    return _si_svc.execute(
        config,
        auth_manager,
        name=params.name,
        method=params.method or "execute",
        params=params.exec_params,
    )
