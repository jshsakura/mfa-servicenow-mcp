"""
Changeset tools for the ServiceNow MCP server.

This module provides tools for managing changesets in ServiceNow.
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import changeset as _cs_svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .sn_api import sn_count, sn_query_page

logger = logging.getLogger(__name__)


class GetChangesetDetailsParams(BaseModel):
    """Parameters for getting changeset details or listing changesets."""

    changeset_id: Optional[str] = Field(
        default=None,
        description="Changeset ID or sys_id. If provided, returns detail for that single update set with its entries.",
    )
    limit: Optional[int] = Field(
        default=10, description="Maximum number of records to return (list mode)"
    )
    offset: Optional[int] = Field(default=0, description="Offset to start from (list mode)")
    state: Optional[str] = Field(default=None, description="Filter by state (list mode)")
    application: Optional[str] = Field(
        default=None, description="Filter by application (list mode)"
    )
    developer: Optional[str] = Field(default=None, description="Filter by developer (list mode)")
    timeframe: Optional[str] = Field(
        default=None, description="Filter by timeframe (recent, last_week, last_month) (list mode)"
    )
    query: Optional[str] = Field(default=None, description="Additional query string (list mode)")
    count_only: bool = Field(
        default=False,
        description="Return count only without fetching records. Uses lightweight Aggregate API. (list mode)",
    )


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


# ---------------------------------------------------------------------------
# manage_changeset — bundled CRUD + lifecycle for sys_update_set
# ---------------------------------------------------------------------------

_CHANGESET_UPDATE_FIELDS = ("name", "description", "state", "developer")


class ManageChangesetParams(BaseModel):
    """Manage update sets — table: sys_update_set.

    Required per action:
      create:   name, application
      update:   changeset_id, at least one field
      commit:   changeset_id
      publish:  changeset_id
      add_file: changeset_id, file_path, file_content
    """

    action: Literal["create", "update", "commit", "publish", "add_file"] = Field(...)
    changeset_id: Optional[str] = Field(
        default=None, description="sys_id (update/commit/publish/add_file)"
    )

    # Create + update
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    application: Optional[str] = Field(default=None, description="Required for create")
    developer: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None, description="Update only")

    # Commit-specific
    commit_message: Optional[str] = Field(default=None)

    # Publish-specific
    publish_notes: Optional[str] = Field(default=None)

    # add_file-specific
    file_path: Optional[str] = Field(default=None)
    file_content: Optional[str] = Field(default=None)

    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageChangesetParams":
        if self.action == "create":
            if not self.name:
                raise ValueError("name is required for action='create'")
            if not self.application:
                raise ValueError("application is required for action='create'")
        elif self.action == "update":
            if not self.changeset_id:
                raise ValueError("changeset_id is required for action='update'")
            if not any(getattr(self, f) is not None for f in _CHANGESET_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update'")
        elif self.action in ("commit", "publish"):
            if not self.changeset_id:
                raise ValueError(f"changeset_id is required for action='{self.action}'")
        elif self.action == "add_file":
            if not self.changeset_id:
                raise ValueError("changeset_id is required for action='add_file'")
            if not self.file_path:
                raise ValueError("file_path is required for action='add_file'")
            if not self.file_content:
                raise ValueError("file_content is required for action='add_file'")
        return self


@register_tool(
    name="manage_changeset",
    params=ManageChangesetParams,
    description="Create/update/commit/publish/add_file on an update set (table: sys_update_set).",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_changeset(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageChangesetParams,
) -> Dict[str, Any]:
    if params.action == "create":
        return _cs_svc.create(
            config,
            auth_manager,
            name=params.name,
            application=params.application,
            description=params.description,
            developer=params.developer,
        )
    if params.action == "update":
        return _cs_svc.update(
            config,
            auth_manager,
            changeset_id=params.changeset_id,
            name=params.name,
            description=params.description,
            state=params.state,
            developer=params.developer,
            dry_run=params.dry_run,
        )
    if params.action == "commit":
        return _cs_svc.commit(
            config,
            auth_manager,
            changeset_id=params.changeset_id,
            commit_message=params.commit_message,
        )
    if params.action == "publish":
        return _cs_svc.publish(
            config,
            auth_manager,
            changeset_id=params.changeset_id,
            publish_notes=params.publish_notes,
        )
    # add_file
    return _cs_svc.add_file(
        config,
        auth_manager,
        changeset_id=params.changeset_id,
        file_path=params.file_path,
        file_content=params.file_content,
    )
