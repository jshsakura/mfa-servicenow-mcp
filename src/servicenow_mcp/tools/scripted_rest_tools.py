"""Scripted REST API tools for the ServiceNow MCP server.

Bundled CRUD over the two-level Scripted REST structure: a service definition
(``sys_ws_definition``) and its resources/operations (``sys_ws_operation``).

Deliberately a dedicated tool rather than ``sn_write``: creating a resource must
connect it to its parent definition, and the header/detail split needs distinct
field sets. Script-body-only edits still flow through ``update_remote_from_local``
(file-based sync); this tool owns creation and header/metadata changes.
"""

import logging
from typing import Any, ClassVar, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import scripted_rest as _svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class ManageScriptedRestParams(BaseModel):
    """Manage Scripted REST APIs — tables: sys_ws_definition, sys_ws_operation.

    Required per action:
      list:            (none)
      get:             service
      create_service:  name
      create_resource: service, name, http_method
      update_service:  service, at least one header field
      update_resource: resource_id, at least one field
    """

    action: Literal[
        "list",
        "get",
        "create_service",
        "create_resource",
        "update_service",
        "update_resource",
    ] = Field(...)

    # Identifiers
    service: Optional[str] = Field(default=None, description="Service sys_id:<id> or name")
    resource_id: Optional[str] = Field(default=None, description="Resource (operation) sys_id")

    # list
    limit: int = Field(default=10, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    query: Optional[str] = Field(default=None, description="Service name search")
    count_only: bool = Field(default=False, description="Return count only")

    # Service header (create_service / update_service)
    name: Optional[str] = Field(default=None, description="Service or resource name")
    service_id: Optional[str] = Field(default=None, description="URL id segment; auto from name")
    short_description: Optional[str] = Field(default=None, description="Service short description")
    consumes: Optional[str] = Field(default=None, description="Accepted content types")
    produces: Optional[str] = Field(default=None, description="Returned content types")

    # Resource detail (create_resource / update_resource)
    http_method: Optional[str] = Field(default=None, description="GET/POST/PUT/PATCH/DELETE")
    relative_path: Optional[str] = Field(default=None, description="Path under service, e.g. /{id}")
    operation_script: Optional[str] = Field(default=None, description="Resource script body")
    requires_authentication: Optional[bool] = Field(default=None, description="Require auth")
    requires_acl_authorization: Optional[bool] = Field(default=None, description="Enforce ACLs")

    # Shared
    active: Optional[bool] = Field(default=None, description="Active flag")
    dry_run: bool = Field(default=False, description="Preview update without committing")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"limit", "offset", "query", "count_only"}),
        "get": frozenset({"service"}),
        "create_service": frozenset(
            {"name", "service_id", "short_description", "active", "consumes", "produces"}
        ),
        "create_resource": frozenset(
            {
                "service",
                "name",
                "http_method",
                "relative_path",
                "operation_script",
                "active",
                "consumes",
                "produces",
                "requires_authentication",
                "requires_acl_authorization",
            }
        ),
        "update_service": frozenset(
            {
                "service",
                "service_id",
                "short_description",
                "active",
                "consumes",
                "produces",
                "dry_run",
            }
        ),
        "update_resource": frozenset(
            {
                "resource_id",
                "http_method",
                "relative_path",
                "operation_script",
                "active",
                "consumes",
                "produces",
                "requires_authentication",
                "requires_acl_authorization",
                "dry_run",
            }
        ),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageScriptedRestParams":
        if self.action == "list":
            pass
        elif self.action == "get":
            if not self.service:
                raise ValueError("service is required for action='get'")
        elif self.action == "create_service":
            if not self.name:
                raise ValueError("name is required for action='create_service'")
        elif self.action == "create_resource":
            if not self.service:
                raise ValueError("service is required for action='create_resource'")
            if not self.name:
                raise ValueError("name is required for action='create_resource'")
            if not self.http_method:
                raise ValueError("http_method is required for action='create_resource'")
        elif self.action == "update_service":
            if not self.service:
                raise ValueError("service is required for action='update_service'")
            if not any(
                getattr(self, f) is not None
                for f in ("service_id", "short_description", "active", "consumes", "produces")
            ):
                raise ValueError(
                    "at least one header field is required for action='update_service'"
                )
        elif self.action == "update_resource":
            if not self.resource_id:
                raise ValueError("resource_id is required for action='update_resource'")
            if not any(getattr(self, f) is not None for f in _svc._OP_UPDATE_FIELDS):
                raise ValueError("at least one field is required for action='update_resource'")
        return self


@register_tool(
    name="manage_scripted_rest",
    params=ManageScriptedRestParams,
    description="CRUD Scripted REST services + resources (sys_ws_definition/sys_ws_operation). Use list/get to find sys_ids.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_scripted_rest(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageScriptedRestParams,
) -> Dict[str, Any]:
    if params.action == "list":
        return _svc.list_services(
            config,
            auth_manager,
            query=params.query,
            active=params.active,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if params.action == "get":
        assert params.service is not None
        return _svc.get_service(config, auth_manager, service_id=params.service)
    if params.action == "create_service":
        assert params.name is not None
        return _svc.create_service(
            config,
            auth_manager,
            name=params.name,
            service_id=params.service_id,
            short_description=params.short_description,
            active=params.active if params.active is not None else True,
            consumes=params.consumes,
            produces=params.produces,
        )
    if params.action == "create_resource":
        assert params.service is not None
        assert params.name is not None
        assert params.http_method is not None
        return _svc.create_resource(
            config,
            auth_manager,
            service=params.service,
            name=params.name,
            http_method=params.http_method,
            relative_path=params.relative_path or "/",
            operation_script=params.operation_script,
            active=params.active if params.active is not None else True,
            consumes=params.consumes,
            produces=params.produces,
            requires_authentication=params.requires_authentication,
            requires_acl_authorization=params.requires_acl_authorization,
        )
    if params.action == "update_service":
        assert params.service is not None
        return _svc.update_service(
            config,
            auth_manager,
            ident=params.service,
            dry_run=params.dry_run,
            service_id=params.service_id,
            short_description=params.short_description,
            active=params.active,
            consumes=params.consumes,
            produces=params.produces,
        )
    # update_resource
    assert params.resource_id is not None
    return _svc.update_resource(
        config,
        auth_manager,
        resource_id=params.resource_id,
        dry_run=params.dry_run,
        http_method=params.http_method,
        relative_path=params.relative_path,
        operation_script=params.operation_script,
        active=params.active,
        consumes=params.consumes,
        produces=params.produces,
        requires_authentication=params.requires_authentication,
        requires_acl_authorization=params.requires_acl_authorization,
    )
