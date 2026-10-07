"""Outbound REST Message tools — sys_rest_message and its HTTP methods.

There was no surface for these at all: they were left out of the source
download on purpose (config records, not script source), and with ``sn_write``
unpackaged that made every outbound integration read-only. A caller then
handed "add Offset/Limit as query parameters" back to a human, after guessing
which of three similarly named child tables holds them. ``get_method`` answers
that in one read; the writes name the list (``param_type``), never the table.
"""

import logging
from typing import Any, ClassVar, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import rest_message as _svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

_PARAM_FIELDS = frozenset({"param_type", "name", "value", "order", "escape_type"})


class ManageRestMessageParams(BaseModel):
    """Manage outbound REST messages — tables: sys_rest_message, sys_rest_message_fn
    and its query-param/header/variable lists.

    Required per action:
      list:          (none)
      get:           sys_id (REST message)
      get_method:    sys_id (HTTP method)
      update_method: sys_id, at least one of rest_endpoint/http_method/content
      add_param:     method_sys_id, name
      update_param:  param_sys_id, at least one of name/value/order/escape_type
      remove_param:  param_sys_id
    """

    action: Literal[
        "list",
        "get",
        "get_method",
        "update_method",
        "add_param",
        "update_param",
        "remove_param",
    ] = Field(...)

    sys_id: Optional[str] = Field(
        default=None, description="REST message (get) or HTTP method (get_method/update_method)"
    )
    query: Optional[str] = Field(default=None, description="Name or endpoint search (list)")
    scope: Optional[str] = Field(default=None, description="App scope namespace filter (list)")
    limit: int = Field(default=10, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    count_only: bool = Field(default=False, description="Return count only")

    rest_endpoint: Optional[str] = Field(default=None, description="Method endpoint URL")
    http_method: Optional[Literal["get", "post", "put", "patch", "delete"]] = Field(
        default=None, description="HTTP verb"
    )
    content: Optional[str] = Field(default=None, description="Request body template")

    method_sys_id: Optional[str] = Field(
        default=None, description="HTTP method that owns the new parameter (add_param)"
    )
    param_sys_id: Optional[str] = Field(
        default=None, description="Parameter row from get_method (update/remove_param)"
    )
    param_type: Literal["query", "header", "variable"] = Field(
        default="query",
        description="query=HTTP Query Parameters, header=HTTP Headers, variable=Variable Substitutions",
    )
    name: Optional[str] = Field(default=None, description="Parameter name")
    value: Optional[str] = Field(
        default=None, description="Parameter value; ${var} is substituted at call time"
    )
    order: Optional[int] = Field(default=None, description="Query param order (default: last)")
    escape_type: Optional[str] = Field(default=None, description="Variable escape type")
    expected_updated_on: Optional[str] = Field(
        default=None, description="sys_updated_on you read; blocks the write if the server moved"
    )
    dry_run: bool = Field(default=False, description="Preview the write without committing")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"query", "scope", "limit", "offset", "count_only"}),
        "get": frozenset({"sys_id"}),
        "get_method": frozenset({"sys_id"}),
        "update_method": frozenset(
            {"sys_id", "rest_endpoint", "http_method", "content", "expected_updated_on", "dry_run"}
        ),
        "add_param": _PARAM_FIELDS | {"method_sys_id", "dry_run"},
        "update_param": _PARAM_FIELDS | {"param_sys_id", "expected_updated_on", "dry_run"},
        "remove_param": frozenset({"param_sys_id", "param_type", "dry_run"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageRestMessageParams":
        a = self.action
        if a in ("get", "get_method", "update_method") and not self.sys_id:
            raise ValueError(f"sys_id is required for action='{a}'")
        if a == "update_method" and all(
            v is None for v in (self.rest_endpoint, self.http_method, self.content)
        ):
            raise ValueError("update_method needs rest_endpoint, http_method or content")
        if a == "add_param":
            if not self.method_sys_id:
                raise ValueError("method_sys_id is required for action='add_param'")
            if not self.name:
                raise ValueError("name is required for action='add_param'")
        if a in ("update_param", "remove_param") and not self.param_sys_id:
            raise ValueError(f"param_sys_id is required for action='{a}'")
        if a == "update_param" and all(
            v is None for v in (self.name, self.value, self.order, self.escape_type)
        ):
            raise ValueError("update_param needs name, value, order or escape_type")
        return self


@register_tool(
    name="manage_rest_message",
    params=ManageRestMessageParams,
    description="Outbound REST message: read a method's endpoint/query params/headers/variables; edit them. Use list to find sys_id.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_rest_message(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageRestMessageParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "list":
        return _svc.list_messages(
            config,
            auth_manager,
            query=params.query,
            scope=params.scope,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if a == "get":
        assert params.sys_id is not None
        return _svc.get_message(config, auth_manager, sys_id=params.sys_id)
    if a == "get_method":
        assert params.sys_id is not None
        return _svc.get_method(config, auth_manager, sys_id=params.sys_id)
    if a == "update_method":
        assert params.sys_id is not None
        return _svc.update_method(
            config,
            auth_manager,
            sys_id=params.sys_id,
            rest_endpoint=params.rest_endpoint,
            http_method=params.http_method,
            content=params.content,
            expected_updated_on=params.expected_updated_on,
            dry_run=params.dry_run,
        )
    if a == "add_param":
        assert params.method_sys_id is not None and params.name is not None
        return _svc.add_param(
            config,
            auth_manager,
            method_sys_id=params.method_sys_id,
            param_type=params.param_type,
            name=params.name,
            value=params.value,
            order=params.order,
            escape_type=params.escape_type,
            dry_run=params.dry_run,
        )
    assert params.param_sys_id is not None
    if a == "update_param":
        return _svc.update_param(
            config,
            auth_manager,
            param_sys_id=params.param_sys_id,
            param_type=params.param_type,
            name=params.name,
            value=params.value,
            order=params.order,
            escape_type=params.escape_type,
            expected_updated_on=params.expected_updated_on,
            dry_run=params.dry_run,
        )
    return _svc.remove_param(
        config,
        auth_manager,
        param_sys_id=params.param_sys_id,
        param_type=params.param_type,
        dry_run=params.dry_run,
    )
