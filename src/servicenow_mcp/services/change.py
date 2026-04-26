"""Change request (change_request) service layer.

Reusable API logic for create / update / add_task on the change_request
table. Both the public ``manage_change`` MCP tool and the legacy wrapper
functions in ``servicenow_mcp.tools.change_tools`` route through this module
so behaviour stays in one place.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    short_description: str,
    type: str,
    description: Optional[str] = None,
    risk: Optional[str] = None,
    impact: Optional[str] = None,
    category: Optional[str] = None,
    requested_by: Optional[str] = None,
    assignment_group: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new change request."""
    data: Dict[str, Any] = {
        "short_description": short_description,
        "type": type,
    }
    for field_name, value in (
        ("description", description),
        ("risk", risk),
        ("impact", impact),
        ("category", category),
        ("requested_by", requested_by),
        ("assignment_group", assignment_group),
        ("start_date", start_date),
        ("end_date", end_date),
    ):
        if value:
            data[field_name] = value

    url = f"{config.api_url}/table/change_request"

    try:
        response = auth_manager.make_request(
            "POST",
            url,
            json=data,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="change_request")

        return {
            "success": True,
            "message": "Change request created successfully",
            "change_request": result["result"],
        }
    except Exception as e:
        logger.error(f"Error creating change request: {e}")
        return {
            "success": False,
            "message": f"Error creating change request: {str(e)}",
        }


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    change_id: str,
    short_description: Optional[str] = None,
    description: Optional[str] = None,
    state: Optional[str] = None,
    risk: Optional[str] = None,
    impact: Optional[str] = None,
    category: Optional[str] = None,
    assignment_group: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    work_notes: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update an existing change request. Supports a dry-run preview."""
    data: Dict[str, Any] = {}
    for field_name, value in (
        ("short_description", short_description),
        ("description", description),
        ("state", state),
        ("risk", risk),
        ("impact", impact),
        ("category", category),
        ("assignment_group", assignment_group),
        ("start_date", start_date),
        ("end_date", end_date),
        ("work_notes", work_notes),
    ):
        if value:
            data[field_name] = value

    url = f"{config.api_url}/table/change_request/{change_id}"

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="change_request",
            sys_id=change_id,
            proposed=data,
            identifier_fields=["number", "short_description", "state"],
        )

    try:
        response = auth_manager.make_request(
            "PUT",
            url,
            json=data,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="change_request")

        return {
            "success": True,
            "message": "Change request updated successfully",
            "change_request": result["result"],
        }
    except Exception as e:
        logger.error(f"Error updating change request: {e}")
        return {
            "success": False,
            "message": f"Error updating change request: {str(e)}",
        }


def add_task(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    change_id: str,
    short_description: str,
    description: Optional[str] = None,
    assigned_to: Optional[str] = None,
    planned_start_date: Optional[str] = None,
    planned_end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a change_task under a change request."""
    data: Dict[str, Any] = {
        "change_request": change_id,
        "short_description": short_description,
    }
    for field_name, value in (
        ("description", description),
        ("assigned_to", assigned_to),
        ("planned_start_date", planned_start_date),
        ("planned_end_date", planned_end_date),
    ):
        if value:
            data[field_name] = value

    url = f"{config.api_url}/table/change_task"

    try:
        response = auth_manager.make_request(
            "POST",
            url,
            json=data,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        result = response.json()
        invalidate_query_cache(table="change_task")

        return {
            "success": True,
            "message": "Change task added successfully",
            "change_task": result["result"],
        }
    except Exception as e:
        logger.error(f"Error adding change task: {e}")
        return {
            "success": False,
            "message": f"Error adding change task: {str(e)}",
        }
