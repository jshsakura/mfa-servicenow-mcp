"""
Changeset tools for the ServiceNow MCP server.

This module provides tools for managing changesets in ServiceNow.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .sn_api import invalidate_query_cache, sn_count, sn_query_page

logger = logging.getLogger(__name__)


class GetChangesetDetailsParams(BaseModel):
    """Parameters for getting changeset details or listing changesets."""

    changeset_id: Optional[str] = Field(
        default=None,
        description="Changeset ID or sys_id. If provided, returns detail for that single update set with its entries.",
    )
    limit: Optional[int] = Field(default=10, description="Maximum number of records to return (list mode)")
    offset: Optional[int] = Field(default=0, description="Offset to start from (list mode)")
    state: Optional[str] = Field(default=None, description="Filter by state (list mode)")
    application: Optional[str] = Field(default=None, description="Filter by application (list mode)")
    developer: Optional[str] = Field(default=None, description="Filter by developer (list mode)")
    timeframe: Optional[str] = Field(
        default=None, description="Filter by timeframe (recent, last_week, last_month) (list mode)"
    )
    query: Optional[str] = Field(default=None, description="Additional query string (list mode)")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records. Uses lightweight Aggregate API. (list mode)",
    )


class CreateChangesetParams(BaseModel):
    """Parameters for creating a changeset."""

    name: str = Field(..., description="Name of the changeset")
    description: Optional[str] = Field(default=None, description="Description of the changeset")
    application: str = Field(..., description="Application the changeset belongs to")
    developer: Optional[str] = Field(default=None, description="Developer responsible for the changeset")


class UpdateChangesetParams(BaseModel):
    """Parameters for updating a changeset."""

    changeset_id: str = Field(..., description="Changeset ID or sys_id")
    name: Optional[str] = Field(default=None, description="Name of the changeset")
    description: Optional[str] = Field(default=None, description="Description of the changeset")
    state: Optional[str] = Field(default=None, description="State of the changeset")
    developer: Optional[str] = Field(default=None, description="Developer responsible for the changeset")


class CommitChangesetParams(BaseModel):
    """Parameters for committing a changeset."""

    changeset_id: str = Field(..., description="Changeset ID or sys_id")
    commit_message: Optional[str] = Field(default=None, description="Commit message")


class PublishChangesetParams(BaseModel):
    """Parameters for publishing a changeset."""

    changeset_id: str = Field(..., description="Changeset ID or sys_id")
    publish_notes: Optional[str] = Field(default=None, description="Notes for publishing")


class AddFileToChangesetParams(BaseModel):
    """Parameters for adding a file to a changeset."""

    changeset_id: str = Field(..., description="Changeset ID or sys_id")
    file_path: str = Field(..., description="Path of the file to add")
    file_content: str = Field(..., description="Content of the file")


@register_tool(
    name="get_changeset_details",
    params=GetChangesetDetailsParams,
    description="Get a single update set by sys_id with entries, or list update sets with filters.",
    serialization="json",
    return_type=str,
)
def get_changeset_details(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetChangesetDetailsParams,
) -> Dict[str, Any]:
    """Get detailed information about a specific changeset, or list changesets."""
    # Detail mode: single changeset with entries
    if params.changeset_id:
        try:
            records, _ = sn_query_page(
                config,
                auth_manager,
                table="sys_update_set",
                query=f"sys_id={params.changeset_id}",
                fields="",
                limit=1,
                offset=0,
            )

            if not records:
                return {
                    "success": False,
                    "message": f"Changeset not found: {params.changeset_id}",
                }

            changeset = records[0]

            changes, _ = sn_query_page(
                config,
                auth_manager,
                table="sys_update_xml",
                query=f"update_set={params.changeset_id}",
                fields="",
                limit=100,
                offset=0,
            )

            return {
                "success": True,
                "changeset": changeset,
                "changes": changes,
                "change_count": len(changes),
            }
        except Exception as e:
            logger.error("Error getting changeset details: %s", e)
            return {
                "success": False,
                "message": f"Error getting changeset details: {str(e)}",
            }

    # List mode: filter and return multiple changesets
    query_parts: List[str] = []

    if params.state:
        query_parts.append(f"state={params.state}")

    if params.application:
        query_parts.append(f"application={params.application}")

    if params.developer:
        query_parts.append(f"developer={params.developer}")

    if params.timeframe:
        if params.timeframe == "recent":
            query_parts.append(
                "sys_created_onONLast 7 days@javascript:gs.beginningOfLast7Days()@javascript:gs.endOfToday()"
            )
        elif params.timeframe == "last_week":
            query_parts.append(
                "sys_created_onONLast week@javascript:gs.beginningOfLastWeek()@javascript:gs.endOfLastWeek()"
            )
        elif params.timeframe == "last_month":
            query_parts.append(
                "sys_created_onONLast month@javascript:gs.beginningOfLastMonth()@javascript:gs.endOfLastMonth()"
            )

    if params.query:
        query_parts.append(params.query)

    query_string = "^".join(query_parts) if query_parts else ""

    if params.count_only:
        count = sn_count(config, auth_manager, "sys_update_set", query_string)
        return {"success": True, "count": count}

    try:
        records, total_count = sn_query_page(
            config,
            auth_manager,
            table="sys_update_set",
            query=query_string,
            fields="",
            limit=params.limit if params.limit is not None else 10,
            offset=params.offset if params.offset is not None else 0,
        )

        return {
            "success": True,
            "changesets": records,
            "count": len(records),
        }
    except Exception as e:
        logger.error("Error listing changesets: %s", e)
        return {
            "success": False,
            "message": f"Error listing changesets: {str(e)}",
        }


@register_tool(
    name="create_changeset",
    params=CreateChangesetParams,
    description="Create a new update set. Returns the new sys_id on success.",
    serialization="json_dict",
    return_type=str,
)
def create_changeset(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateChangesetParams,
) -> Dict[str, Any]:
    """Create a new changeset in ServiceNow."""
    data: Dict[str, Any] = {
        "name": params.name,
        "application": params.application,
    }

    if params.description:
        data["description"] = params.description
    if params.developer:
        data["developer"] = params.developer

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
        return {
            "success": False,
            "message": f"Error creating changeset: {str(e)}",
        }


@register_tool(
    name="update_changeset",
    params=UpdateChangesetParams,
    description="Update an existing update set's name, description, state, or developer.",
    serialization="json_dict",
    return_type=str,
)
def update_changeset(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdateChangesetParams,
) -> Dict[str, Any]:
    """Update an existing changeset in ServiceNow."""
    data: Dict[str, Any] = {}

    if params.name:
        data["name"] = params.name
    if params.description:
        data["description"] = params.description
    if params.state:
        data["state"] = params.state
    if params.developer:
        data["developer"] = params.developer

    if not data:
        return {
            "success": False,
            "message": "No fields to update",
        }

    url = f"{config.api_url}/table/sys_update_set/{params.changeset_id}"
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
        return {
            "success": False,
            "message": f"Error updating changeset: {str(e)}",
        }


@register_tool(
    name="commit_changeset",
    params=CommitChangesetParams,
    description="Finalize an update set by marking it complete. Prevents further edits.",
    serialization="str",
    return_type=str,
)
def commit_changeset(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CommitChangesetParams,
) -> Dict[str, Any]:
    """Commit a changeset in ServiceNow."""
    data: Dict[str, Any] = {
        "state": "complete",
    }

    if params.commit_message:
        data["description"] = params.commit_message

    url = f"{config.api_url}/table/sys_update_set/{params.changeset_id}"
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
        return {
            "success": False,
            "message": f"Error committing changeset: {str(e)}",
        }


@register_tool(
    name="publish_changeset",
    params=PublishChangesetParams,
    description="Deploy a committed update set to the target instance.",
    serialization="str",
    return_type=str,
)
def publish_changeset(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: PublishChangesetParams,
) -> Dict[str, Any]:
    """Publish a changeset in ServiceNow."""
    data: Dict[str, Any] = {
        "state": "published",
    }

    if params.publish_notes:
        data["description"] = params.publish_notes

    url = f"{config.api_url}/table/sys_update_set/{params.changeset_id}"
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
        return {
            "success": False,
            "message": f"Error publishing changeset: {str(e)}",
        }


@register_tool(
    name="add_file_to_changeset",
    params=AddFileToChangesetParams,
    description="Attach a record (file path + content) to an update set.",
    serialization="str",
    return_type=str,
)
def add_file_to_changeset(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: AddFileToChangesetParams,
) -> Dict[str, Any]:
    """Add a file to a changeset in ServiceNow."""
    data = {
        "update_set": params.changeset_id,
        "name": params.file_path,
        "payload": params.file_content,
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
        return {
            "success": False,
            "message": f"Error adding file to changeset: {str(e)}",
        }
