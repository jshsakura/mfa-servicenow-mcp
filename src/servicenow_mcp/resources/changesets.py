"""Legacy-compatible changeset resource helpers."""

from __future__ import annotations

import requests

from servicenow_mcp.utils import json_fast
from pydantic import BaseModel

from servicenow_mcp.auth.auth_manager import AuthManager
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
            response = requests.get(
                f"{self.config.instance_url}/api/now/table/sys_update_set",
                headers=self.auth_manager.get_headers(),
                params=request_params,
            )
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as exc:
            return json_fast.dumps({"error": str(exc)})

    async def get_changeset(self, changeset_id: str) -> str:
        try:
            headers = self.auth_manager.get_headers()
            changeset_response = requests.get(
                f"{self.config.instance_url}/api/now/table/sys_update_set/{changeset_id}",
                headers=headers,
            )
            changeset_response.raise_for_status()
            changeset = changeset_response.json().get("result", {})

            changes_response = requests.get(
                f"{self.config.instance_url}/api/now/table/sys_update_xml",
                headers=headers,
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
        except requests.exceptions.RequestException as exc:
            return json_fast.dumps({"error": str(exc)})
