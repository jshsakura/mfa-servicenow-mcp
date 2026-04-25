"""
User management tools for the ServiceNow MCP server.

This module provides tools for managing users and groups in ServiceNow.
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class CreateUserParams(BaseModel):
    """Parameters for creating a user."""

    user_name: str = Field(..., description="Username for the user")
    first_name: str = Field(..., description="First name of the user")
    last_name: str = Field(..., description="Last name of the user")
    email: str = Field(..., description="Email address of the user")
    title: Optional[str] = Field(default=None, description="Job title of the user")
    department: Optional[str] = Field(default=None, description="Department the user belongs to")
    manager: Optional[str] = Field(
        default=None, description="Manager of the user (sys_id or username)"
    )
    roles: Optional[List[str]] = Field(default=None, description="Roles to assign to the user")
    phone: Optional[str] = Field(default=None, description="Phone number of the user")
    mobile_phone: Optional[str] = Field(default=None, description="Mobile phone number of the user")
    location: Optional[str] = Field(default=None, description="Location of the user")
    password: Optional[str] = Field(default=None, description="Password for the user account")
    active: Optional[bool] = Field(default=True, description="Whether the user account is active")


class UpdateUserParams(BaseModel):
    """Parameters for updating a user."""

    user_id: str = Field(..., description="User ID or sys_id to update")
    user_name: Optional[str] = Field(default=None, description="Username for the user")
    first_name: Optional[str] = Field(default=None, description="First name of the user")
    last_name: Optional[str] = Field(default=None, description="Last name of the user")
    email: Optional[str] = Field(default=None, description="Email address of the user")
    title: Optional[str] = Field(default=None, description="Job title of the user")
    department: Optional[str] = Field(default=None, description="Department the user belongs to")
    manager: Optional[str] = Field(
        default=None, description="Manager of the user (sys_id or username)"
    )
    roles: Optional[List[str]] = Field(default=None, description="Roles to assign to the user")
    phone: Optional[str] = Field(default=None, description="Phone number of the user")
    mobile_phone: Optional[str] = Field(default=None, description="Mobile phone number of the user")
    location: Optional[str] = Field(default=None, description="Location of the user")
    password: Optional[str] = Field(default=None, description="Password for the user account")
    active: Optional[bool] = Field(default=None, description="Whether the user account is active")
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


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


class CreateGroupParams(BaseModel):
    """Parameters for creating a group."""

    name: str = Field(..., description="Name of the group")
    description: Optional[str] = Field(default=None, description="Description of the group")
    manager: Optional[str] = Field(
        default=None, description="Manager of the group (sys_id or username)"
    )
    parent: Optional[str] = Field(default=None, description="Parent group (sys_id or name)")
    type: Optional[str] = Field(default=None, description="Type of the group")
    email: Optional[str] = Field(default=None, description="Email address for the group")
    members: Optional[List[str]] = Field(
        default=None, description="List of user sys_ids or usernames to add as members"
    )
    active: Optional[bool] = Field(default=True, description="Whether the group is active")


class UpdateGroupParams(BaseModel):
    """Parameters for updating a group."""

    group_id: str = Field(..., description="Group ID or sys_id to update")
    name: Optional[str] = Field(default=None, description="Name of the group")
    description: Optional[str] = Field(default=None, description="Description of the group")
    manager: Optional[str] = Field(
        default=None, description="Manager of the group (sys_id or username)"
    )
    parent: Optional[str] = Field(default=None, description="Parent group (sys_id or name)")
    type: Optional[str] = Field(default=None, description="Type of the group")
    email: Optional[str] = Field(default=None, description="Email address for the group")
    active: Optional[bool] = Field(default=None, description="Whether the group is active")
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


class AddGroupMembersParams(BaseModel):
    """Parameters for adding members to a group."""

    group_id: str = Field(..., description="Group ID or sys_id")
    members: List[str] = Field(
        default=..., description="List of user sys_ids or usernames to add as members"
    )


class RemoveGroupMembersParams(BaseModel):
    """Parameters for removing members from a group."""

    group_id: str = Field(..., description="Group ID or sys_id")
    members: List[str] = Field(
        default=..., description="List of user sys_ids or usernames to remove as members"
    )
    dry_run: bool = Field(
        default=False,
        description="Preview resolved memberships without deleting.",
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


class UserResponse(BaseModel):
    """Response from user operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    user_id: Optional[str] = Field(default=None, description="ID of the affected user")
    user_name: Optional[str] = Field(default=None, description="Username of the affected user")


class GroupResponse(BaseModel):
    """Response from group operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    group_id: Optional[str] = Field(default=None, description="ID of the affected group")
    group_name: Optional[str] = Field(default=None, description="Name of the affected group")


@register_tool(
    name="create_user",
    params=CreateUserParams,
    description="Create a user (sys_user). Requires user_name. Optional: email, first/last name, roles.",
    serialization="raw_dict",
    return_type=dict,
)
def create_user(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateUserParams,
) -> UserResponse:
    """
    Create a new user in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for creating the user.

    Returns:
        Response with the created user details.
    """
    api_url = f"{config.api_url}/table/sys_user"

    # Build request data
    data = {
        "user_name": params.user_name,
        "first_name": params.first_name,
        "last_name": params.last_name,
        "email": params.email,
        "active": str(params.active).lower(),
    }

    if params.title:
        data["title"] = params.title
    if params.department:
        data["department"] = params.department
    if params.manager:
        data["manager"] = params.manager
    if params.phone:
        data["phone"] = params.phone
    if params.mobile_phone:
        data["mobile_phone"] = params.mobile_phone
    if params.location:
        data["location"] = params.location
    if params.password:
        data["user_password"] = params.password

    # Make request
    try:
        response = auth_manager.make_request(
            "POST",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})

        # Handle role assignments if provided
        if params.roles and result.get("sys_id"):
            assign_roles_to_user(config, auth_manager, result.get("sys_id"), params.roles)

        invalidate_query_cache(table="sys_user")

        return UserResponse(
            success=True,
            message="User created successfully",
            user_id=result.get("sys_id"),
            user_name=result.get("user_name"),
        )

    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        return UserResponse(
            success=False,
            message=f"Failed to create user: {str(e)}",
        )


@register_tool(
    name="update_user",
    params=UpdateUserParams,
    description="Update a user by sys_id. Supports name, email, active, department, and role fields.",
    serialization="raw_dict",
    return_type=dict,
)
def update_user(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateUserParams,
) -> UserResponse:
    """
    Update an existing user in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for updating the user.

    Returns:
        Response with the updated user details.
    """
    api_url = f"{config.api_url}/table/sys_user/{params.user_id}"

    # Build request data
    data = {}
    if params.user_name:
        data["user_name"] = params.user_name
    if params.first_name:
        data["first_name"] = params.first_name
    if params.last_name:
        data["last_name"] = params.last_name
    if params.email:
        data["email"] = params.email
    if params.title:
        data["title"] = params.title
    if params.department:
        data["department"] = params.department
    if params.manager:
        data["manager"] = params.manager
    if params.phone:
        data["phone"] = params.phone
    if params.mobile_phone:
        data["mobile_phone"] = params.mobile_phone
    if params.location:
        data["location"] = params.location
    if params.password:
        data["user_password"] = params.password
    if params.active is not None:
        data["active"] = str(params.active).lower()

    if params.dry_run:
        # Exclude password from preview — don't echo secrets in the diff
        preview_data = {k: v for k, v in data.items() if k != "user_password"}
        preview = build_update_preview(
            config,
            auth_manager,
            table="sys_user",
            sys_id=params.user_id,
            proposed=preview_data,
            identifier_fields=["user_name", "email", "active"],
        )
        if params.password:
            preview.setdefault("warnings", []).append(
                "password change proposed (value omitted from preview)"
            )
        if params.roles:
            preview["proposed_roles"] = list(params.roles)
        return preview

    # Make request
    try:
        response = auth_manager.make_request(
            "PATCH",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})

        # Handle role assignments if provided
        if params.roles:
            assign_roles_to_user(config, auth_manager, params.user_id, params.roles)

        invalidate_query_cache(table="sys_user")

        return UserResponse(
            success=True,
            message="User updated successfully",
            user_id=result.get("sys_id"),
            user_name=result.get("user_name"),
        )

    except Exception as e:
        logger.error(f"Failed to update user: {e}")
        return UserResponse(
            success=False,
            message=f"Failed to update user: {str(e)}",
        )


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
    """
    Get a user from ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for getting the user.

    Returns:
        Dictionary containing user details.
    """
    query_string = ""

    # Build query parameters
    if params.user_id:
        query_string = f"sys_id={params.user_id}"
    elif params.user_name:
        query_string = f"user_name={params.user_name}"
    elif params.email:
        query_string = f"email={params.email}"
    else:
        return {"success": False, "message": "At least one search parameter is required"}

    # Make request
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
    """
    List users from ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for listing users.

    Returns:
        Dictionary containing list of users.
    """
    # Build query
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

    # Make request
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
    """
    List groups from ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for listing groups.

    Returns:
        Dictionary containing list of groups.
    """
    # Build query
    query_parts = []
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.type:
        query_parts.append(f"type={params.type}")
    if params.query:
        query_parts.append(f"^nameLIKE{params.query}^ORdescriptionLIKE{params.query}")

    query_string = "^".join(query_parts) if query_parts else ""

    # Make request
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


def assign_roles_to_user(
    config: ServerConfig,
    auth_manager: AuthManager,
    user_id: str,
    roles: List[str],
) -> bool:
    """
    Assign roles to a user in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        user_id: User ID or sys_id.
        roles: List of roles to assign.

    Returns:
        Boolean indicating success.
    """
    # For each role, create a user_role record
    api_url = f"{config.api_url}/table/sys_user_has_role"

    success = True
    assigned_any = False
    for role in roles:
        # First check if the role exists
        role_id = get_role_id(config, auth_manager, role)
        if not role_id:
            logger.warning(f"Role '{role}' not found, skipping assignment")
            continue

        # Check if the user already has this role
        if check_user_has_role(config, auth_manager, user_id, role_id):
            logger.info(f"User already has role '{role}', skipping assignment")
            continue

        # Create the user role assignment
        data = {
            "user": user_id,
            "role": role_id,
        }

        try:
            response = auth_manager.make_request(
                "POST",
                api_url,
                json=data,
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            response.raise_for_status()
            assigned_any = True
        except Exception as e:
            logger.error(f"Failed to assign role '{role}' to user: {e}")
            success = False

    if assigned_any:
        invalidate_query_cache(table="sys_user_has_role")

    return success


def get_role_id(
    config: ServerConfig,
    auth_manager: AuthManager,
    role_name: str,
) -> Optional[str]:
    """
    Get the sys_id of a role by its name.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        role_name: Name of the role.

    Returns:
        sys_id of the role if found, None otherwise.
    """
    try:
        result, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_user_role",
            query=f"name={role_name}",
            fields="sys_id",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if not result:
            return None

        return result[0].get("sys_id")

    except Exception as e:
        logger.error(f"Failed to get role ID: {e}")
        return None


def check_user_has_role(
    config: ServerConfig,
    auth_manager: AuthManager,
    user_id: str,
    role_id: str,
) -> bool:
    """
    Check if a user has a specific role.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        user_id: User ID or sys_id.
        role_id: Role ID or sys_id.

    Returns:
        Boolean indicating whether the user has the role.
    """
    try:
        result, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_user_has_role",
            query=f"user={user_id}^role={role_id}",
            fields="sys_id",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        return len(result) > 0

    except Exception as e:
        logger.error(f"Failed to check if user has role: {e}")
        return False


@register_tool(
    name="create_group",
    params=CreateGroupParams,
    description="Create a group (sys_user_group). Requires name. Optional: manager, description, type.",
    serialization="raw_dict",
    return_type=dict,
)
def create_group(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateGroupParams,
) -> GroupResponse:
    """
    Create a new group in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for creating the group.

    Returns:
        Response with the created group details.
    """
    api_url = f"{config.api_url}/table/sys_user_group"

    # Build request data
    data = {
        "name": params.name,
        "active": str(params.active).lower(),
    }

    if params.description:
        data["description"] = params.description
    if params.manager:
        data["manager"] = params.manager
    if params.parent:
        data["parent"] = params.parent
    if params.type:
        data["type"] = params.type
    if params.email:
        data["email"] = params.email

    # Make request
    try:
        response = auth_manager.make_request(
            "POST",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})
        group_id = result.get("sys_id")

        # Add members if provided
        if params.members and group_id:
            add_group_members(
                config,
                auth_manager,
                AddGroupMembersParams(group_id=group_id, members=params.members),
            )

        invalidate_query_cache(table="sys_user_group")

        return GroupResponse(
            success=True,
            message="Group created successfully",
            group_id=group_id,
            group_name=result.get("name"),
        )

    except Exception as e:
        logger.error(f"Failed to create group: {e}")
        return GroupResponse(
            success=False,
            message=f"Failed to create group: {str(e)}",
        )


@register_tool(
    name="update_group",
    params=UpdateGroupParams,
    description="Update a group by sys_id. Supports name, manager, description, and active fields.",
    serialization="raw_dict",
    return_type=dict,
)
def update_group(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateGroupParams,
) -> GroupResponse:
    """
    Update an existing group in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for updating the group.

    Returns:
        Response with the updated group details.
    """
    api_url = f"{config.api_url}/table/sys_user_group/{params.group_id}"

    # Build request data
    data = {}
    if params.name:
        data["name"] = params.name
    if params.description:
        data["description"] = params.description
    if params.manager:
        data["manager"] = params.manager
    if params.parent:
        data["parent"] = params.parent
    if params.type:
        data["type"] = params.type
    if params.email:
        data["email"] = params.email
    if params.active is not None:
        data["active"] = str(params.active).lower()

    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sys_user_group",
            sys_id=params.group_id,
            proposed=data,
            identifier_fields=["name", "description", "active"],
        )

    # Make request
    try:
        response = auth_manager.make_request(
            "PATCH",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})
        invalidate_query_cache(table="sys_user_group")

        return GroupResponse(
            success=True,
            message="Group updated successfully",
            group_id=result.get("sys_id"),
            group_name=result.get("name"),
        )

    except Exception as e:
        logger.error(f"Failed to update group: {e}")
        return GroupResponse(
            success=False,
            message=f"Failed to update group: {str(e)}",
        )


@register_tool(
    name="add_group_members",
    params=AddGroupMembersParams,
    description="Add one or more users to a group. Requires group sys_id and user sys_ids.",
    serialization="raw_dict",
    return_type=dict,
)
def add_group_members(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: AddGroupMembersParams,
) -> GroupResponse:
    """
    Add members to a group in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for adding members to the group.

    Returns:
        Response with the result of the operation.
    """
    api_url = f"{config.api_url}/table/sys_user_grmember"

    success = True
    failed_members = []

    for member in params.members:
        # Get user ID if username is provided
        user_id = member
        if not member.startswith("sys_id:"):
            user = get_user(config, auth_manager, GetUserParams(user_name=member))
            if not user.get("success"):
                user = get_user(config, auth_manager, GetUserParams(email=member))

            if user.get("success"):
                user_id = user.get("user", {}).get("sys_id")
            else:
                success = False
                failed_members.append(member)
                continue

        # Create group membership
        data = {
            "group": params.group_id,
            "user": user_id,
        }

        try:
            response = auth_manager.make_request(
                "POST",
                api_url,
                json=data,
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to add member '{member}' to group: {e}")
            success = False
            failed_members.append(member)

    if failed_members:
        message = f"Some members could not be added to the group: {', '.join(failed_members)}"
    else:
        message = "All members added to the group successfully"

    if success:
        invalidate_query_cache(table="sys_user_grmember")

    return GroupResponse(
        success=success,
        message=message,
        group_id=params.group_id,
    )


@register_tool(
    name="remove_group_members",
    params=RemoveGroupMembersParams,
    description="Remove one or more users from a group. Requires group sys_id and user sys_ids.",
    serialization="raw_dict",
    return_type=dict,
)
def remove_group_members(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: RemoveGroupMembersParams,
) -> GroupResponse:
    """
    Remove members from a group in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for removing members from the group.

    Returns:
        Response with the result of the operation.
    """
    success = True
    failed_members = []
    dry_run_removals: List[Dict[str, Any]] = []

    for member in params.members:
        # Get user ID if username is provided
        user_id = member
        if not member.startswith("sys_id:"):
            user = get_user(config, auth_manager, GetUserParams(user_name=member))
            if not user.get("success"):
                user = get_user(config, auth_manager, GetUserParams(email=member))

            if user.get("success"):
                user_id = user.get("user", {}).get("sys_id")
            else:
                success = False
                failed_members.append(member)
                continue

        # Find and delete the group membership
        api_url = f"{config.api_url}/table/sys_user_grmember"
        query_params = {
            "sysparm_query": f"group={params.group_id}^user={user_id}",
            "sysparm_limit": "1",
        }

        try:
            # First find the membership record
            response = auth_manager.make_request(
                "GET",
                api_url,
                params=query_params,
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            response.raise_for_status()

            result = response.json().get("result", [])
            if not result:
                success = False
                failed_members.append(member)
                continue

            membership_id = result[0].get("sys_id")

            if params.dry_run:
                # Record what would be deleted — no DELETE call issued
                dry_run_removals.append(
                    {"member": member, "user_id": user_id, "membership_id": membership_id}
                )
                continue

            # Then delete the membership record
            delete_url = f"{api_url}/{membership_id}"

            response = auth_manager.make_request(
                "DELETE",
                delete_url,
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            response.raise_for_status()

        except Exception as e:
            logger.error(f"Failed to remove member '{member}' from group: {e}")
            success = False
            failed_members.append(member)

    if params.dry_run:
        return {
            "dry_run": True,
            "operation": "delete",
            "target": {"table": "sys_user_grmember", "group_id": params.group_id},
            "would_remove": dry_run_removals,
            "unresolved_members": failed_members,
            "warnings": (
                [f"{len(failed_members)} member(s) could not be resolved"] if failed_members else []
            ),
            "precision_notes": {
                "count_source": "table_api",
                "dependency_check": False,
                "acl_checked": False,
            },
        }

    if failed_members:
        message = f"Some members could not be removed from the group: {', '.join(failed_members)}"
    else:
        message = "All members removed from the group successfully"

    if success:
        invalidate_query_cache(table="sys_user_grmember")

    return GroupResponse(
        success=success,
        message=message,
        group_id=params.group_id,
    )


# ---------------------------------------------------------------------------
# manage_user — bundled CRUD + read for sys_user
#
# Read actions ('get', 'list') are exempted from the manage_* confirm gate
# via server.MANAGE_READ_ACTIONS.
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
        return create_user(config, auth_manager, CreateUserParams(**kwargs))
    if a == "update":
        kwargs = {"user_id": params.user_id, "dry_run": params.dry_run}
        for f in _USER_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return update_user(config, auth_manager, UpdateUserParams(**kwargs))
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
        return create_group(config, auth_manager, CreateGroupParams(**kwargs))
    if a == "update":
        kwargs = {"group_id": params.group_id, "dry_run": params.dry_run}
        for f in _GROUP_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return update_group(config, auth_manager, UpdateGroupParams(**kwargs))
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
        return add_group_members(
            config,
            auth_manager,
            AddGroupMembersParams(group_id=params.group_id, members=params.members),
        )
    return remove_group_members(
        config,
        auth_manager,
        RemoveGroupMembersParams(
            group_id=params.group_id, members=params.members, dry_run=params.dry_run
        ),
    )
