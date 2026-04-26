"""
User management tools for the ServiceNow MCP server.

This module provides tools for managing users and groups in ServiceNow.
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import user as _usr_svc
from servicenow_mcp.tools.sn_api import sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class GetUserParams(BaseModel):
    """Parameters for getting a user."""

    user_id: Optional[str] = Field(default=None, description="User ID or sys_id")
    user_name: Optional[str] = Field(default=None, description="Username of the user")
    email: Optional[str] = Field(default=None, description="Email address of the user")


class ListUsersParams(BaseModel):
    """Parameters for listing users."""

    limit: int = Field(default=10, description="Maximum number of users to return")
    offset: int = Field(default=0, description="Offset for pagination")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    department: Optional[str] = Field(default=None, description="Filter by department")
    query: Optional[str] = Field(
        default=None,
        description="Case-insensitive search term that matches against name, username, or email fields. Uses ServiceNow's LIKE operator for partial matching.",
    )
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records. Uses lightweight Aggregate API.",
    )


class ListGroupsParams(BaseModel):
    """Parameters for listing groups."""

    limit: int = Field(default=10, description="Maximum number of groups to return")
    offset: int = Field(default=0, description="Offset for pagination")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    query: Optional[str] = Field(
        default=None,
        description="Case-insensitive search term that matches against group name or description fields. Uses ServiceNow's LIKE operator for partial matching.",
    )
    type: Optional[str] = Field(default=None, description="Filter by group type")


@register_tool(
    name="get_user",
    params=GetUserParams,
    description="Get a user by sys_id or user_name. Returns profile, roles, and group memberships.",
    serialization="raw_dict",
    return_type=dict,
)
def get_user(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetUserParams,
) -> dict:
    """Get a user from ServiceNow."""
    if params.user_id:
        query_string = f"sys_id={params.user_id}"
    elif params.user_name:
        query_string = f"user_name={params.user_name}"
    elif params.email:
        query_string = f"email={params.email}"
    else:
        return {"success": False, "message": "At least one search parameter is required"}

    try:
        result, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_user",
            query=query_string,
            fields="",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if not result:
            return {"success": False, "message": "User not found"}
        return {"success": True, "message": "User found", "user": result[0]}
    except Exception as e:
        logger.error(f"Failed to get user: {e}")
        return {"success": False, "message": f"Failed to get user: {str(e)}"}


@register_tool(
    name="list_users",
    params=ListUsersParams,
    description="List users with optional name/email/department/active filters.",
    serialization="raw_dict",
    return_type=dict,
)
def list_users(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListUsersParams,
) -> dict:
    """List users from ServiceNow."""
    query_parts = []
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.department:
        query_parts.append(f"department={params.department}")
    if params.query:
        query_parts.append(
            f"^nameLIKE{params.query}^ORuser_nameLIKE{params.query}^ORemailLIKE{params.query}"
        )
    query_string = "^".join(query_parts) if query_parts else ""

    if params.count_only:
        count = sn_count(config, auth_manager, "sys_user", query_string)
        return {"success": True, "count": count}

    try:
        result, total = sn_query_page(
            config,
            auth_manager,
            table="sys_user",
            query=query_string,
            fields="",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
            fail_silently=False,
        )
        return {
            "success": True,
            "message": f"Found {len(result)} users",
            "users": result,
            "count": len(result),
            "total": total or 0,
        }
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        return {"success": False, "message": f"Failed to list users: {str(e)}"}


@register_tool(
    name="list_groups",
    params=ListGroupsParams,
    description="List groups with optional name/type/active filters. Returns group details and member count.",
    serialization="raw_dict",
    return_type=dict,
)
def list_groups(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListGroupsParams,
) -> dict:
    """List groups from ServiceNow."""
    query_parts = []
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.type:
        query_parts.append(f"type={params.type}")
    if params.query:
        query_parts.append(f"^nameLIKE{params.query}^ORdescriptionLIKE{params.query}")
    query_string = "^".join(query_parts) if query_parts else ""

    try:
        result, total = sn_query_page(
            config,
            auth_manager,
            table="sys_user_group",
            query=query_string,
            fields="",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
            fail_silently=False,
        )
        return {
            "success": True,
            "message": f"Found {len(result)} groups",
            "groups": result,
            "count": len(result),
            "total": total or 0,
        }
    except Exception as e:
        logger.error(f"Failed to list groups: {e}")
        return {"success": False, "message": f"Failed to list groups: {str(e)}"}


# ---------------------------------------------------------------------------
# manage_user — bundled CRUD + read for sys_user
# ---------------------------------------------------------------------------

_USER_UPDATE_FIELDS = (
    "user_name",
    "first_name",
    "last_name",
    "email",
    "title",
    "department",
    "manager",
    "roles",
    "phone",
    "mobile_phone",
    "location",
    "password",
    "active",
)


class ManageUserParams(BaseModel):
    """Manage users — table: sys_user."""

    action: Literal["create", "update", "get", "list"] = Field(...)
    user_id: Optional[str] = Field(default=None)
    user_name: Optional[str] = Field(default=None)
    first_name: Optional[str] = Field(default=None)
    last_name: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    department: Optional[str] = Field(default=None)
    manager: Optional[str] = Field(default=None)
    roles: Optional[List[str]] = Field(default=None)
    phone: Optional[str] = Field(default=None)
    mobile_phone: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None)
    password: Optional[str] = Field(default=None)
    active: Optional[bool] = Field(default=None)
    limit: int = Field(default=10)
    offset: int = Field(default=0)
    query: Optional[str] = Field(default=None)
    count_only: bool = Field(default=False)
    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageUserParams":
        a = self.action
        if a == "create":
            for f in ("user_name", "first_name", "last_name", "email"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='create'")
        elif a == "update":
            if not self.user_id:
                raise ValueError("user_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _USER_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        elif a == "get":
            if not (self.user_id or self.user_name or self.email):
                raise ValueError("user_id, user_name, or email is required for action='get'")
        return self


@register_tool(
    name="manage_user",
    params=ManageUserParams,
    description="User CRUD + lookup (table: sys_user). Read actions skip confirm.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_user(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageUserParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "create":
        kwargs: Dict[str, Any] = {
            "user_name": params.user_name,
            "first_name": params.first_name,
            "last_name": params.last_name,
            "email": params.email,
        }
        for f in (
            "title",
            "department",
            "manager",
            "roles",
            "phone",
            "mobile_phone",
            "location",
            "password",
            "active",
        ):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _usr_svc.create_user(config, auth_manager, **kwargs)
    if a == "update":
        kwargs = {"user_id": params.user_id, "dry_run": params.dry_run}
        for f in _USER_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _usr_svc.update_user(config, auth_manager, **kwargs)
    if a == "get":
        return get_user(
            config,
            auth_manager,
            GetUserParams(
                user_id=params.user_id,
                user_name=params.user_name,
                email=params.email,
            ),
        )
    return list_users(
        config,
        auth_manager,
        ListUsersParams(
            limit=params.limit,
            offset=params.offset,
            active=params.active,
            department=params.department,
            query=params.query,
            count_only=params.count_only,
        ),
    )


# ---------------------------------------------------------------------------
# manage_group — bundled CRUD + membership ops for sys_user_group
# ---------------------------------------------------------------------------

_GROUP_UPDATE_FIELDS = ("name", "description", "manager", "parent", "type", "email", "active")


class ManageGroupParams(BaseModel):
    """Manage groups — table: sys_user_group."""

    action: Literal["create", "update", "list", "add_members", "remove_members"] = Field(...)
    group_id: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    manager: Optional[str] = Field(default=None)
    parent: Optional[str] = Field(default=None)
    type: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    active: Optional[bool] = Field(default=None)
    members: Optional[List[str]] = Field(default=None)
    limit: int = Field(default=10)
    offset: int = Field(default=0)
    query: Optional[str] = Field(default=None)
    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageGroupParams":
        a = self.action
        if a == "create":
            if not self.name:
                raise ValueError("name is required for action='create'")
        elif a == "update":
            if not self.group_id:
                raise ValueError("group_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _GROUP_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        elif a in ("add_members", "remove_members"):
            if not self.group_id:
                raise ValueError(f"group_id is required for action='{a}'")
            if not self.members:
                raise ValueError(f"members is required for action='{a}'")
        return self


@register_tool(
    name="manage_group",
    params=ManageGroupParams,
    description="Group CRUD + membership ops (table: sys_user_group). list skips confirm.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_group(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageGroupParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "create":
        kwargs: Dict[str, Any] = {"name": params.name}
        for f in ("description", "manager", "parent", "type", "email", "members", "active"):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _usr_svc.create_group(config, auth_manager, **kwargs)
    if a == "update":
        kwargs = {"group_id": params.group_id, "dry_run": params.dry_run}
        for f in _GROUP_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _usr_svc.update_group(config, auth_manager, **kwargs)
    if a == "list":
        return list_groups(
            config,
            auth_manager,
            ListGroupsParams(
                limit=params.limit,
                offset=params.offset,
                active=params.active,
                query=params.query,
                type=params.type,
            ),
        )
    if a == "add_members":
        return _usr_svc.add_members(
            config,
            auth_manager,
            group_id=params.group_id,
            members=params.members,
        )
    return _usr_svc.remove_members(
        config,
        auth_manager,
        group_id=params.group_id,
        members=params.members,
        dry_run=params.dry_run,
    )
