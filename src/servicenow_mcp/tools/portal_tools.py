"""
Service Portal development tools for the ServiceNow MCP server.
Optimized for speed, token efficiency, and context safety.
"""

import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from .core_plus import GenericQueryParams, sn_query

logger = logging.getLogger(__name__)

# Constants for Portal tables
WIDGET_TABLE = "sp_widget"
ANGULAR_PROVIDER_TABLE = "sp_angular_provider"
WIDGET_DEPENDENCY_TABLE = "m2m_sp_widget_dependency"
ANGULAR_PROVIDER_M2M_TABLE = "m2m_sp_widget_angular_provider"


class GetWidgetBundleParams(BaseModel):
    """Parameters for fetching a simplified widget bundle."""

    widget_id: str = Field(..., description="The sys_id or name of the widget")
    include_providers: bool = Field(
        True, description="Whether to include list of associated Angular Providers"
    )


class GetPortalComponentParams(BaseModel):
    """Parameters for fetching specific portal component code."""

    table: str = Field(
        ..., description="The table name (sp_widget, sp_angular_provider, sys_script_include)"
    )
    sys_id: str = Field(..., description="The sys_id of the component")
    fields: List[str] = Field(
        ["template", "script", "client_script", "css"], description="Specific code fields to fetch"
    )


class UpdatePortalComponentParams(BaseModel):
    """Parameters for updating portal component code."""

    table: str = Field(
        ..., description="The table name (sp_widget, sp_angular_provider, sys_script_include)"
    )
    sys_id: str = Field(..., description="The sys_id of the component")
    update_data: Dict[str, str] = Field(
        ..., description="Field-value pairs to update (e.g. {'client_script': '...'})"
    )


def _strip_metadata(record: Dict[str, Any], keep_fields: List[str]) -> Dict[str, Any]:
    """Helper to remove unnecessary system fields to save tokens."""
    return {k: v for k, v in record.items() if k in keep_fields or k == "sys_id" or k == "name"}


def get_widget_bundle(
    config: ServerConfig, auth_manager: AuthManager, params: GetWidgetBundleParams
) -> Dict[str, Any]:
    """
    Fetch a high-speed, token-efficient bundle of a Service Portal widget.
    Returns core code and metadata about dependencies.
    """
    # 1. Fetch the widget record
    query = f"sys_id={params.widget_id}^ORid={params.widget_id}"
    widget_fields = ["name", "id", "template", "script", "client_script", "css", "sys_id"]

    query_params = GenericQueryParams(
        table=WIDGET_TABLE, query=query, fields=",".join(widget_fields), limit=1
    )
    response = sn_query(config, auth_manager, query_params)

    if not response.get("success") or not response.get("results"):
        return {"error": f"Widget '{params.widget_id}' not found."}

    widget = _strip_metadata(response["results"][0], widget_fields)
    bundle: Dict[str, Any] = {"widget": widget}

    # 2. Fetch Angular Provider list (minimal info to save context)
    if params.include_providers:
        m2m_query_params = GenericQueryParams(
            table=ANGULAR_PROVIDER_M2M_TABLE,
            query=f"sp_widget={widget['sys_id']}",
            fields="sp_angular_provider",
        )
        m2m_response = sn_query(config, auth_manager, m2m_query_params)
        providers_m2m = m2m_response.get("results", [])

        provider_ids = [
            p["sp_angular_provider"]["value"]
            for p in providers_m2m
            if isinstance(p.get("sp_angular_provider"), dict)
        ]

        if provider_ids:
            prov_query_params = GenericQueryParams(
                table=ANGULAR_PROVIDER_TABLE,
                query=f"sys_idIN{','.join(provider_ids)}",
                fields="name,sys_id,type",
            )
            prov_response = sn_query(config, auth_manager, prov_query_params)
            bundle["angular_providers"] = [
                {"name": p["name"], "sys_id": p["sys_id"], "type": p.get("type", "")}
                for p in prov_response.get("results", [])
            ]
        else:
            bundle["angular_providers"] = []

    return bundle


def get_portal_component_code(
    config: ServerConfig, auth_manager: AuthManager, params: GetPortalComponentParams
) -> Dict[str, Any]:
    """Fetch specific code fields from a portal-related record."""
    query_params = GenericQueryParams(
        table=params.table,
        query=f"sys_id={params.sys_id}",
        fields=",".join(params.fields + ["name", "sys_id"]),
        limit=1,
    )
    response = sn_query(config, auth_manager, query_params)

    if not response.get("success") or not response.get("results"):
        return {"error": f"Component not found in {params.table} with sys_id {params.sys_id}"}

    # Only return requested code fields to keep context clean
    result = _strip_metadata(response["results"][0], params.fields)

    # Basic safety: check for very large scripts (though sn_query also does truncation)
    for field in params.fields:
        val = result.get(field, "")
        if isinstance(val, str) and len(val) > 10000:
            result[field] = val[:10000] + "... [TRUNCATED FOR CONTEXT SAFETY]"
            result[f"_{field}_is_truncated"] = True

    return result


def update_portal_component(
    config: ServerConfig, auth_manager: AuthManager, params: UpdatePortalComponentParams
) -> Dict[str, Any]:
    """Pinpoint update of specific portal component fields."""
    instance_url = config.instance_url
    url = f"{instance_url}/api/now/table/{params.table}/{params.sys_id}"

    headers = auth_manager.get_headers()
    response = auth_manager.make_request("PATCH", url, json=params.update_data, headers=headers)

    if response.status_code >= 400:
        return {"error": f"Update failed: {response.text}", "status": response.status_code}

    return {
        "message": "Update successful",
        "sys_id": params.sys_id,
        "fields": list(params.update_data.keys()),
    }
