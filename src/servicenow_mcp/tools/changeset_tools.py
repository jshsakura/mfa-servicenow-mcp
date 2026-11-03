"""
Changeset tools for the ServiceNow MCP server.

This module provides tools for managing changesets in ServiceNow.
"""

import logging
import re
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
_SYS_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class ManageChangesetParams(BaseModel):
    """Manage update sets — table: sys_update_set.

    Required per action:
      get:      changeset_id (detail) or filters (list)
      create:   name, application
      update:   changeset_id, at least one field
      commit:   changeset_id
      publish:  changeset_id
      add_file: changeset_id, file_path, file_content
      move_file:   changeset_id, entry_ids, target_changeset_id
      remove_file: changeset_id, entry_ids, confirm_remove
    """

    action: Literal[
        "get", "create", "update", "commit", "publish", "add_file", "move_file", "remove_file"
    ] = Field(...)
    changeset_id: Optional[str] = Field(
        default=None, description="Update set sys_id. For move_file/remove_file, the source set."
    )

    # move_file / remove_file
    entry_ids: Optional[List[str]] = Field(
        default=None,
        description=f"sys_update_xml sys_ids from action='get' changes, max {_cs_svc.MAX_ENTRY_BATCH}.",
    )
    target_changeset_id: Optional[str] = Field(
        default=None, description="move_file: sys_id of the in-progress set to move into."
    )
    confirm_remove: Optional[str] = Field(
        default=None,
        description="remove_file: the source update set's name, after the user agrees.",
    )
    confirm_other_author: Optional[str] = Field(
        default=None,
        description="Comma list of the other authors the user agreed to; dry_run names them.",
    )

    # get (list mode) params
    limit: int = Field(default=10, description="Max records (get list mode)")
    offset: int = Field(default=0, description="Pagination offset (get list mode)")
    timeframe: Optional[str] = Field(
        default=None, description="recent/last_week/last_month (get list mode)"
    )
    query: Optional[str] = Field(
        default=None, description="Additional query string (get list mode)"
    )
    count_only: bool = Field(default=False, description="Return count only (get list mode)")

    # Create + update (application/developer also used as list filters for get)
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    application: Optional[str] = Field(
        default=None, description="Required for create; filter for get"
    )
    developer: Optional[str] = Field(default=None)
    state: Optional[str] = Field(default=None, description="Update only; filter for get")

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
        if self.action == "get":
            pass
        elif self.action == "create":
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
        elif self.action in ("move_file", "remove_file"):
            if not self.changeset_id:
                raise ValueError(f"changeset_id (the source set) is required for '{self.action}'")
            ids = [str(i).strip() for i in (self.entry_ids or []) if str(i).strip()]
            if not ids:
                raise ValueError(
                    f"entry_ids is required for '{self.action}': the sys_update_xml sys_ids "
                    "listed under 'changes' by manage_changeset(action='get', changeset_id=...)"
                )
            if len(set(ids)) > _cs_svc.MAX_ENTRY_BATCH:
                raise ValueError(
                    f"at most {_cs_svc.MAX_ENTRY_BATCH} entries per call; split the batch"
                )
            bad = [i for i in ids if not _SYS_ID_RE.match(i)]
            if bad:
                raise ValueError(
                    "entry_ids must be 32-character sys_ids, not names or queries: "
                    + ", ".join(bad[:5])
                )
            self.entry_ids = list(dict.fromkeys(i.lower() for i in ids))
            if self.action == "move_file":
                if not self.target_changeset_id:
                    raise ValueError("target_changeset_id is required for 'move_file'")
                if self.target_changeset_id.strip() == self.changeset_id.strip():
                    raise ValueError("target_changeset_id is the same set as changeset_id")
        return self


@register_tool(
    name="manage_changeset",
    params=ManageChangesetParams,
    description=(
        "Get/create/update/commit/publish/add_file on an update set (table: sys_update_set). "
        "move_file/remove_file take wrong entries out; dry_run=true first."
    ),
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_changeset(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageChangesetParams,
) -> Dict[str, Any]:
    if params.action == "get":
        return _cs_svc.get(
            config,
            auth_manager,
            changeset_id=params.changeset_id,
            limit=params.limit,
            offset=params.offset,
            state=params.state,
            application=params.application,
            developer=params.developer,
            timeframe=params.timeframe,
            query=params.query,
            count_only=params.count_only,
        )
    if params.action == "create":
        # ManageChangesetParams validator guarantees these are present per action.
        assert params.name is not None
        assert params.application is not None
        return _cs_svc.create(
            config,
            auth_manager,
            name=params.name,
            application=params.application,
            description=params.description,
            developer=params.developer,
        )
    if params.action == "update":
        assert params.changeset_id is not None
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
        assert params.changeset_id is not None
        return _cs_svc.commit(
            config,
            auth_manager,
            changeset_id=params.changeset_id,
            commit_message=params.commit_message,
        )
    if params.action == "publish":
        assert params.changeset_id is not None
        return _cs_svc.publish(
            config,
            auth_manager,
            changeset_id=params.changeset_id,
            publish_notes=params.publish_notes,
        )
    if params.action in ("move_file", "remove_file"):
        assert params.changeset_id is not None
        assert params.entry_ids is not None
        return _cs_svc.change_entries(
            config,
            auth_manager,
            action=params.action,
            changeset_id=params.changeset_id.strip(),
            entry_ids=params.entry_ids,
            target_changeset_id=(params.target_changeset_id or "").strip() or None,
            confirm_remove=params.confirm_remove,
            confirm_other_author=params.confirm_other_author,
            dry_run=params.dry_run,
        )
    # add_file
    assert params.changeset_id is not None
    assert params.file_path is not None
    assert params.file_content is not None
    return _cs_svc.add_file(
        config,
        auth_manager,
        changeset_id=params.changeset_id,
        file_path=params.file_path,
        file_content=params.file_content,
    )
