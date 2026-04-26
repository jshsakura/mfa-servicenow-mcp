"""User and group (sys_user, sys_user_group) service layer.

Business logic for create/update user and create/update/add_members/remove_members
group operations. ``manage_user`` and ``manage_group`` in tools/user_tools.py are
the sole public entry points.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lookup_user_id(
    config: ServerConfig, auth_manager: AuthManager, identifier: str
) -> Optional[str]:
    """Return sys_id for an identifier (username, email, or raw sys_id prefix)."""
    if identifier.startswith("sys_id:"):
        return identifier[7:]
    for field in ("user_name", "email"):
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_user",
            query=f"{field}={identifier}",
            fields="sys_id",
            limit=1,
            offset=0,
            display_value=False,
        )
        if rows:
            return rows[0].get("sys_id")
    return None


def _get_role_id(config: ServerConfig, auth_manager: AuthManager, role_name: str) -> Optional[str]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_user_role",
        query=f"name={role_name}",
        fields="sys_id",
        limit=1,
        offset=0,
        display_value=False,
    )
    return rows[0].get("sys_id") if rows else None


def _has_role(config: ServerConfig, auth_manager: AuthManager, user_id: str, role_id: str) -> bool:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_user_has_role",
        query=f"user={user_id}^role={role_id}",
        fields="sys_id",
        limit=1,
        offset=0,
        display_value=False,
    )
    return bool(rows)


def _assign_roles(
    config: ServerConfig, auth_manager: AuthManager, user_id: str, roles: List[str]
) -> None:
    assigned_any = False
    for role in roles:
        role_id = _get_role_id(config, auth_manager, role)
        if not role_id:
            logger.warning(f"Role '{role}' not found, skipping")
            continue
        if _has_role(config, auth_manager, user_id, role_id):
            continue
        try:
            r = auth_manager.make_request(
                "POST",
                f"{config.api_url}/table/sys_user_has_role",
                json={"user": user_id, "role": role_id},
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            r.raise_for_status()
            assigned_any = True
        except Exception as e:
            logger.error(f"Failed to assign role '{role}': {e}")
    if assigned_any:
        invalidate_query_cache(table="sys_user_has_role")


# ---------------------------------------------------------------------------
# User operations
# ---------------------------------------------------------------------------


def create_user(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    user_name: str,
    first_name: str,
    last_name: str,
    email: str,
    title: Optional[str] = None,
    department: Optional[str] = None,
    manager: Optional[str] = None,
    roles: Optional[List[str]] = None,
    phone: Optional[str] = None,
    mobile_phone: Optional[str] = None,
    location: Optional[str] = None,
    password: Optional[str] = None,
    active: Optional[bool] = True,
) -> Dict[str, Any]:
    """Create a new user in ServiceNow."""
    data: Dict[str, Any] = {
        "user_name": user_name,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "active": str(active).lower(),
    }
    if title:
        data["title"] = title
    if department:
        data["department"] = department
    if manager:
        data["manager"] = manager
    if phone:
        data["phone"] = phone
    if mobile_phone:
        data["mobile_phone"] = mobile_phone
    if location:
        data["location"] = location
    if password:
        data["user_password"] = password

    try:
        response = auth_manager.make_request(
            "POST",
            f"{config.api_url}/table/sys_user",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        result = response.json().get("result", {})
        if roles and result.get("sys_id"):
            _assign_roles(config, auth_manager, result["sys_id"], roles)
        invalidate_query_cache(table="sys_user")
        return {
            "success": True,
            "message": "User created successfully",
            "user_id": result.get("sys_id"),
            "user_name": result.get("user_name"),
        }
    except Exception as e:
        logger.error(f"Failed to create user: {e}")
        return {"success": False, "message": f"Failed to create user: {str(e)}"}


def update_user(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    user_id: str,
    user_name: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    title: Optional[str] = None,
    department: Optional[str] = None,
    manager: Optional[str] = None,
    roles: Optional[List[str]] = None,
    phone: Optional[str] = None,
    mobile_phone: Optional[str] = None,
    location: Optional[str] = None,
    password: Optional[str] = None,
    active: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update an existing user in ServiceNow."""
    data: Dict[str, Any] = {}
    if user_name:
        data["user_name"] = user_name
    if first_name:
        data["first_name"] = first_name
    if last_name:
        data["last_name"] = last_name
    if email:
        data["email"] = email
    if title:
        data["title"] = title
    if department:
        data["department"] = department
    if manager:
        data["manager"] = manager
    if phone:
        data["phone"] = phone
    if mobile_phone:
        data["mobile_phone"] = mobile_phone
    if location:
        data["location"] = location
    if password:
        data["user_password"] = password
    if active is not None:
        data["active"] = str(active).lower()

    if dry_run:
        preview_data = {k: v for k, v in data.items() if k != "user_password"}
        preview = build_update_preview(
            config,
            auth_manager,
            table="sys_user",
            sys_id=user_id,
            proposed=preview_data,
            identifier_fields=["user_name", "email", "active"],
        )
        if password:
            preview.setdefault("warnings", []).append(
                "password change proposed (value omitted from preview)"
            )
        if roles:
            preview["proposed_roles"] = list(roles)
        return preview

    try:
        response = auth_manager.make_request(
            "PATCH",
            f"{config.api_url}/table/sys_user/{user_id}",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        result = response.json().get("result", {})
        if roles:
            _assign_roles(config, auth_manager, user_id, roles)
        invalidate_query_cache(table="sys_user")
        return {
            "success": True,
            "message": "User updated successfully",
            "user_id": result.get("sys_id"),
            "user_name": result.get("user_name"),
        }
    except Exception as e:
        logger.error(f"Failed to update user: {e}")
        return {"success": False, "message": f"Failed to update user: {str(e)}"}


# ---------------------------------------------------------------------------
# Group operations
# ---------------------------------------------------------------------------


def create_group(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    description: Optional[str] = None,
    manager: Optional[str] = None,
    parent: Optional[str] = None,
    type: Optional[str] = None,
    email: Optional[str] = None,
    members: Optional[List[str]] = None,
    active: Optional[bool] = True,
) -> Dict[str, Any]:
    """Create a new group in ServiceNow."""
    data: Dict[str, Any] = {"name": name, "active": str(active).lower()}
    if description:
        data["description"] = description
    if manager:
        data["manager"] = manager
    if parent:
        data["parent"] = parent
    if type:
        data["type"] = type
    if email:
        data["email"] = email

    try:
        response = auth_manager.make_request(
            "POST",
            f"{config.api_url}/table/sys_user_group",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        result = response.json().get("result", {})
        group_id = result.get("sys_id")
        if members and group_id:
            add_members(config, auth_manager, group_id=group_id, members=members)
        invalidate_query_cache(table="sys_user_group")
        return {
            "success": True,
            "message": "Group created successfully",
            "group_id": group_id,
            "group_name": result.get("name"),
        }
    except Exception as e:
        logger.error(f"Failed to create group: {e}")
        return {"success": False, "message": f"Failed to create group: {str(e)}"}


def update_group(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    group_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    manager: Optional[str] = None,
    parent: Optional[str] = None,
    type: Optional[str] = None,
    email: Optional[str] = None,
    active: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update an existing group in ServiceNow."""
    data: Dict[str, Any] = {}
    if name:
        data["name"] = name
    if description:
        data["description"] = description
    if manager:
        data["manager"] = manager
    if parent:
        data["parent"] = parent
    if type:
        data["type"] = type
    if email:
        data["email"] = email
    if active is not None:
        data["active"] = str(active).lower()

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sys_user_group",
            sys_id=group_id,
            proposed=data,
            identifier_fields=["name", "description", "active"],
        )

    try:
        response = auth_manager.make_request(
            "PATCH",
            f"{config.api_url}/table/sys_user_group/{group_id}",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        result = response.json().get("result", {})
        invalidate_query_cache(table="sys_user_group")
        return {
            "success": True,
            "message": "Group updated successfully",
            "group_id": result.get("sys_id"),
            "group_name": result.get("name"),
        }
    except Exception as e:
        logger.error(f"Failed to update group: {e}")
        return {"success": False, "message": f"Failed to update group: {str(e)}"}


def add_members(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    group_id: str,
    members: List[str],
) -> Dict[str, Any]:
    """Add users to a group. Members can be usernames, emails, or sys_id: prefixed IDs."""
    success = True
    failed: List[str] = []

    for member in members:
        user_id = _lookup_user_id(config, auth_manager, member)
        if not user_id:
            success = False
            failed.append(member)
            continue
        try:
            r = auth_manager.make_request(
                "POST",
                f"{config.api_url}/table/sys_user_grmember",
                json={"group": group_id, "user": user_id},
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to add member '{member}': {e}")
            success = False
            failed.append(member)

    if success:
        invalidate_query_cache(table="sys_user_grmember")

    return {
        "success": success,
        "message": (
            "All members added to the group successfully"
            if not failed
            else f"Some members could not be added: {', '.join(failed)}"
        ),
        "group_id": group_id,
    }


def remove_members(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    group_id: str,
    members: List[str],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Remove users from a group. Supports dry_run to preview removals."""
    success = True
    failed: List[str] = []
    dry_run_removals: List[Dict[str, Any]] = []

    for member in members:
        user_id = _lookup_user_id(config, auth_manager, member)
        if not user_id:
            success = False
            failed.append(member)
            continue

        try:
            response = auth_manager.make_request(
                "GET",
                f"{config.api_url}/table/sys_user_grmember",
                params={"sysparm_query": f"group={group_id}^user={user_id}", "sysparm_limit": "1"},
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            response.raise_for_status()
            result = response.json().get("result", [])
            if not result:
                success = False
                failed.append(member)
                continue

            membership_id = result[0].get("sys_id")

            if dry_run:
                dry_run_removals.append(
                    {"member": member, "user_id": user_id, "membership_id": membership_id}
                )
                continue

            r = auth_manager.make_request(
                "DELETE",
                f"{config.api_url}/table/sys_user_grmember/{membership_id}",
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to remove member '{member}': {e}")
            success = False
            failed.append(member)

    if dry_run:
        return {
            "dry_run": True,
            "operation": "delete",
            "target": {"table": "sys_user_grmember", "group_id": group_id},
            "would_remove": dry_run_removals,
            "unresolved_members": failed,
            "warnings": ([f"{len(failed)} member(s) could not be resolved"] if failed else []),
            "precision_notes": {
                "count_source": "table_api",
                "dependency_check": False,
                "acl_checked": False,
            },
        }

    if success:
        invalidate_query_cache(table="sys_user_grmember")

    return {
        "success": success,
        "message": (
            "All members removed from the group successfully"
            if not failed
            else f"Some members could not be removed: {', '.join(failed)}"
        ),
        "group_id": group_id,
    }
