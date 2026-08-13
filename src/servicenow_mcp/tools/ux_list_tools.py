"""UX Workspace list configuration tools for the ServiceNow MCP server.

Bundled CRUD over ``sys_ux_list`` — the record that decides what a workspace
module's list renders (view, columns, fixed query).

Deliberately a dedicated tool rather than ``sn_write``: ``view`` is a
reference to ``sys_ui_view``, and a raw table write leaves the caller to
resolve that reference correctly by hand — get it wrong and the write still
succeeds, just into a field nothing renders. This tool resolves it or fails
loud; see ``services/ux_list.py`` for why.
"""

import logging
from typing import Any, ClassVar, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import ux_list as _svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class ManageUxListParams(BaseModel):
    """Manage UX Workspace list configs — table: sys_ux_list.

    Required per action:
      list:   (none)
      get:    sys_id
      update: sys_id, at least one field
    """

    action: Literal["list", "get", "update"] = Field(...)

    sys_id: Optional[str] = Field(default=None, description="sys_ux_list record (get/update)")

    # list
    table: Optional[str] = Field(default=None, description="Filter by target table name (list)")
    query: Optional[str] = Field(default=None, description="Title search (list)")
    limit: int = Field(default=10, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    count_only: bool = Field(default=False, description="Return count only")

    # update
    title: Optional[str] = Field(default=None, description="List title")
    view: Optional[str] = Field(
        default=None,
        description="sys_ui_view name or sys_id:<id> — list inherits its columns/order (update)",
    )
    columns: Optional[str] = Field(
        default=None, description="Comma-separated field list; '' clears it (update)"
    )
    fixed_query: Optional[str] = Field(
        default=None, description="Encoded query, always applied regardless of user filters"
    )
    condition: Optional[str] = Field(
        default=None, description="Encoded query, user-editable filter"
    )
    order: Optional[int] = Field(default=None, description="Sort order among sibling lists")
    active: Optional[bool] = Field(default=None, description="Active flag")
    dry_run: bool = Field(default=False, description="Preview update without committing")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"table", "query", "limit", "offset", "count_only"}),
        "get": frozenset({"sys_id"}),
        "update": frozenset(
            {
                "sys_id",
                "title",
                "view",
                "columns",
                "fixed_query",
                "condition",
                "order",
                "active",
                "dry_run",
            }
        ),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageUxListParams":
        if self.action == "get":
            if not self.sys_id:
                raise ValueError("sys_id is required for action='get'")
        elif self.action == "update":
            if not self.sys_id:
                raise ValueError("sys_id is required for action='update'")
            if not any(
                getattr(self, f) is not None
                for f in ("title", "view", "columns", "fixed_query", "condition", "order", "active")
            ):
                raise ValueError("at least one field is required for action='update'")
        return self


@register_tool(
    name="manage_ux_list",
    params=ManageUxListParams,
    description="UX Workspace list config CRUD (sys_ux_list: view/columns/fixed_query). Use list to find sys_id.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_ux_list(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageUxListParams,
) -> Dict[str, Any]:
    if params.action == "list":
        return _svc.list_lists(
            config,
            auth_manager,
            table=params.table,
            query=params.query,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if params.action == "get":
        assert params.sys_id is not None
        return _svc.get_list(config, auth_manager, sys_id=params.sys_id)
    # update
    assert params.sys_id is not None
    return _svc.update_list(
        config,
        auth_manager,
        sys_id=params.sys_id,
        dry_run=params.dry_run,
        title=params.title,
        view=params.view,
        columns=params.columns,
        fixed_query=params.fixed_query,
        condition=params.condition,
        order=params.order,
        active=params.active,
    )
