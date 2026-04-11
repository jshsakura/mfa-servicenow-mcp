"""Legacy-compatible script include resource helpers."""

from __future__ import annotations

import requests

from servicenow_mcp.utils import json_fast
from pydantic import BaseModel

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig

RequestParams = dict[str, str | int]


class ScriptIncludeListParams(BaseModel):
    limit: int = 10
    offset: int = 0
    active: bool | None = None
    client_callable: bool | None = None
    query: str | None = None


class ScriptIncludeResource:
    def __init__(self, config: ServerConfig, auth_manager: AuthManager):
        self.config = config
        self.auth_manager = auth_manager

    async def list_script_includes(self, params: ScriptIncludeListParams) -> str:
        query_parts = []
        if params.active is not None:
            query_parts.append(f"active={'true' if params.active else 'false'}")
        if params.client_callable is not None:
            query_parts.append(f"client_callable={'true' if params.client_callable else 'false'}")
        if params.query:
            query_parts.append(f"nameLIKE{params.query}")
        request_params: RequestParams = {
            "sysparm_limit": params.limit,
            "sysparm_offset": params.offset,
            "sysparm_query": "^".join(query_parts),
        }

        try:
            response = requests.get(
                f"{self.config.instance_url}/api/now/table/sys_script_include",
                headers=self.auth_manager.get_headers(),
                params=request_params,
            )
            if response.status_code >= 400:
                raise requests.RequestException(f"HTTP {response.status_code}")
            return response.text
        except requests.RequestException as exc:
            return json_fast.dumps({"error": f"Error listing script includes: {exc}"})

    async def get_script_include(self, identifier: str) -> str:
        try:
            headers = self.auth_manager.get_headers()
            if identifier.startswith("sys_id:"):
                response = requests.get(
                    f"{self.config.instance_url}/api/now/table/sys_script_include/{identifier.removeprefix('sys_id:')}",
                    headers=headers,
                )
            else:
                response = requests.get(
                    f"{self.config.instance_url}/api/now/table/sys_script_include",
                    headers=headers,
                    params={"sysparm_query": f"name={identifier}"},
                )
            if response.status_code >= 400:
                raise requests.RequestException(f"HTTP {response.status_code}")
            return response.text
        except requests.RequestException as exc:
            return json_fast.dumps({"error": f"Error getting script include: {exc}"})
