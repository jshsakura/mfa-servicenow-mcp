"""Legacy-compatible changeset resource helpers."""

from __future__ import annotations

from pydantic import BaseModel
from requests import RequestException

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.config import ServerConfig

RequestParams = dict[str, str | int]


class ChangesetListParams(BaseModel):
    limit: int = 10
    offset: int = 0
    state: str | None = None
    application: str | None = None
    developer: str | None = None


class ChangesetResource:
    def __init__(self, config: ServerConfig, auth_manager: AuthManager):
        self.config = config
        self.auth_manager = auth_manager

    async def list_changesets(self, params: ChangesetListParams) -> str:
        query_parts = []
        if params.state:
            query_parts.append(f"state={params.state}")
        if params.application:
            query_parts.append(f"application={params.application}")
        if params.developer:
            query_parts.append(f"developer={params.developer}")
        request_params: RequestParams = {
            "sysparm_limit": params.limit,
            "sysparm_offset": params.offset,
            "sysparm_query": "^".join(query_parts),
        }

        try:
            response = self.auth_manager.make_request(
                "GET",
                f"{self.config.instance_url}/api/now/table/sys_update_set",
                params=request_params,
            )
            response.raise_for_status()
            return response.text
        except RequestException as exc:
            return json_fast.dumps({"error": str(exc)})

    async def get_changeset(self, changeset_id: str) -> str:
        try:
            changeset_response = self.auth_manager.make_request(
                "GET",
                f"{self.config.instance_url}/api/now/table/sys_update_set/{changeset_id}",
            )
            changeset_response.raise_for_status()
            changeset = changeset_response.json().get("result", {})

            changes_response = self.auth_manager.make_request(
                "GET",
                f"{self.config.instance_url}/api/now/table/sys_update_xml",
                params={"sysparm_query": f"update_set={changeset_id}"},
            )
            changes_response.raise_for_status()
            changes = changes_response.json().get("result", [])

            return json_fast.dumps(
                {
                    "changeset": changeset,
                    "changes": changes,
                    "change_count": len(changes),
                }
            )
        except RequestException as exc:
            return json_fast.dumps({"error": str(exc)})
