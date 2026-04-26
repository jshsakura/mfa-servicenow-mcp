"""Update set (sys_update_set) service layer.

Business logic for create / update / commit / publish / add_file operations.
``manage_changeset`` in tools/changeset_tools.py is the sole public entry point.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

_CHANGESET_UPDATE_FIELDS = ("name", "description", "state", "developer")


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    application: str,
    description: Optional[str] = None,
    developer: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new update set."""
    data: Dict[str, Any] = {"name": name, "application": application}
    if description:
        data["description"] = description
    if developer:
        data["developer"] = developer

    url = f"{config.api_url}/table/sys_update_set"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("POST", url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="sys_update_set")
        return {
            "success": True,
            "message": "Changeset created successfully",
            "changeset": result["result"],
        }
    except Exception as e:
        logger.error("Error creating changeset: %s", e)
        return {"success": False, "message": f"Error creating changeset: {str(e)}"}


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    changeset_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    state: Optional[str] = None,
    developer: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update an existing update set. Supports dry-run preview."""
    data: Dict[str, Any] = {}
    if name:
        data["name"] = name
    if description:
        data["description"] = description
    if state:
        data["state"] = state
    if developer:
        data["developer"] = developer

    if not data:
        return {"success": False, "message": "No fields to update"}

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sys_update_set",
            sys_id=changeset_id,
            proposed=data,
            identifier_fields=["name", "state", "application"],
        )

    url = f"{config.api_url}/table/sys_update_set/{changeset_id}"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("PATCH", url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="sys_update_set")
        return {
            "success": True,
            "message": "Changeset updated successfully",
            "changeset": result["result"],
        }
    except Exception as e:
        logger.error("Error updating changeset: %s", e)
        return {"success": False, "message": f"Error updating changeset: {str(e)}"}


def commit(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    changeset_id: str,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Finalize an update set by marking it complete."""
    data: Dict[str, Any] = {"state": "complete"}
    if commit_message:
        data["description"] = commit_message

    url = f"{config.api_url}/table/sys_update_set/{changeset_id}"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("PATCH", url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="sys_update_set")
        return {
            "success": True,
            "message": "Changeset committed successfully",
            "changeset": result["result"],
        }
    except Exception as e:
        logger.error("Error committing changeset: %s", e)
        return {"success": False, "message": f"Error committing changeset: {str(e)}"}


def publish(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    changeset_id: str,
    publish_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Deploy a committed update set to the target instance."""
    data: Dict[str, Any] = {"state": "published"}
    if publish_notes:
        data["description"] = publish_notes

    url = f"{config.api_url}/table/sys_update_set/{changeset_id}"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("PATCH", url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="sys_update_set")
        return {
            "success": True,
            "message": "Changeset published successfully",
            "changeset": result["result"],
        }
    except Exception as e:
        logger.error("Error publishing changeset: %s", e)
        return {"success": False, "message": f"Error publishing changeset: {str(e)}"}


def add_file(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    changeset_id: str,
    file_path: str,
    file_content: str,
) -> Dict[str, Any]:
    """Attach a record (file path + content) to an update set."""
    data = {
        "update_set": changeset_id,
        "name": file_path,
        "payload": file_content,
        "type": "file",
    }

    url = f"{config.api_url}/table/sys_update_xml"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("POST", url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        invalidate_query_cache(table="sys_update_xml")
        return {
            "success": True,
            "message": "File added to changeset successfully",
            "file": result["result"],
        }
    except Exception as e:
        logger.error("Error adding file to changeset: %s", e)
        return {"success": False, "message": f"Error adding file to changeset: {str(e)}"}
