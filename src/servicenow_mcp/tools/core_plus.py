"""Core cross-domain ServiceNow tools merged from legacy MCP projects."""

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl

import requests
from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

HEAVY_TABLES = {
    "sp_widget",
    "sys_script",
    "sys_script_include",
    "sys_ui_page",
    "sys_ui_macro",
    "sys_ui_script",
    "sys_metadata",
}
HEAVY_FIELDS = {"script", "template", "css", "client_script", "link", "demo_data", "html"}
DEFAULT_SAFE_FIELDS = "sys_id,name,id,sys_scope"


def truncate_results(results: List[Dict[str, Any]], max_len: int = 50000) -> List[Dict[str, Any]]:
    """Truncates long string values in results to prevent context overflow."""
    for row in results:
        for key, value in row.items():
            if isinstance(value, str) and len(value) > max_len:
                row[key] = value[:max_len] + f"... (truncated, original length: {len(value)})"
    return results


def apply_payload_safety(
    table: str, limit: int, fields: Optional[str]
) -> tuple[int, Optional[str], Optional[str]]:
    """
    Enforces payload safety by restricting limit and default fields.
    Returns: (safe_limit, safe_fields, safety_notice_message)
    """
    safe_limit = min(limit, 100)
    safety_notice = None

    if table in HEAVY_TABLES:
        if not fields:
            # If no fields specified, only fetch safe fields to prevent payload explosion
            return (
                safe_limit,
                DEFAULT_SAFE_FIELDS,
                "Fields clamped to safe defaults to prevent payload overload.",
            )

        # If fields are specified, check if they include heavy fields
        requested_fields = [f.strip().lower() for f in fields.split(",")]
        has_heavy_fields = any(hf in requested_fields for hf in HEAVY_FIELDS)

        if has_heavy_fields and safe_limit > 5:
            # If heavy fields are explicitly requested, heavily restrict the limit
            safe_limit = 5
            safety_notice = "Limit clamped to 5 because heavy fields were requested. Fetch remaining items individually."

    return safe_limit, fields, safety_notice


class HealthCheckParams(BaseModel):
    timeout: int = Field(15, description="Request timeout in seconds")


class GenericQueryParams(BaseModel):
    table: str = Field(
        ...,
        description="Target table name (e.g., incident, sp_widget). Heavy tables have automatic safety limits.",
    )
    query: Optional[str] = Field(
        default=None, description="Encoded query (sysparm_query). Filter by priority, state, etc."
    )
    fields: Optional[str] = Field(
        default=None,
        description="Comma-separated field list. Avoid large fields like 'script' for list queries.",
    )
    limit: int = Field(20, description="Max records (max 100). Default 20.")
    offset: int = Field(0, description="Pagination offset. Use with total_count to iterate.")
    orderby: Optional[str] = Field(
        default=None, description="Order by field, supports -field for desc"
    )
    display_value: bool = Field(True, description="Return display values")


class AggregateParams(BaseModel):
    table: str = Field(..., description="Target table name")
    aggregate: str = Field("COUNT", description="COUNT, SUM, AVG, MIN, MAX")
    field: Optional[str] = Field(default=None, description="Field for SUM/AVG/MIN/MAX")
    query: Optional[str] = Field(default=None, description="Encoded query")
    group_by: Optional[str] = Field(default=None, description="Group by field")


class SchemaParams(BaseModel):
    table: str = Field(..., description="Table name for schema lookup")
    limit: int = Field(500, description="Maximum schema rows")


class DiscoverParams(BaseModel):
    keyword: str = Field(..., description="Keyword to search table names and labels")
    limit: int = Field(50, description="Max matches")


class NaturalLanguageParams(BaseModel):
    text: str = Field(..., description="Natural language query")
    execute: bool = Field(False, description="Execute writes")
    confirm: bool = Field(False, description="Confirmation for destructive operations")


def _safe_json(response: requests.Response) -> Dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _is_login_redirect_response(response: requests.Response) -> bool:
    location = response.headers.get("Location", "")
    response_url = str(response.url)
    return (
        "login.do" in location.lower()
        or "sysparm_type=login" in location.lower()
        or "login.do" in response_url.lower()
    )


@register_tool(
    name="sn_health",
    params=HealthCheckParams,
    description="Run ServiceNow API connectivity and auth health checks. In browser auth mode, this may open a login window on first use and can return a warning when the browser session is valid but the configured probe path is blocked by ACLs.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_health(
    config: ServerConfig, auth_manager: AuthManager, params: HealthCheckParams
) -> Dict[str, Any]:
    probe_path = "/api/now/table/sys_user?sysparm_limit=1&sysparm_fields=sys_id"
    if config.auth.type.value == "browser" and config.auth.browser:
        probe_path = config.auth.browser.probe_path
    probe_path = probe_path.lstrip("/")
    if "?" in probe_path:
        path_only, query_string = probe_path.split("?", 1)
        probe_params = dict(parse_qsl(query_string, keep_blank_values=True))
    else:
        path_only = probe_path
        probe_params = {}
    url = f"{config.instance_url}/{path_only}"
    try:
        response = auth_manager.make_request(
            "GET",
            url,
            params=probe_params or None,
            timeout=params.timeout,
            max_retries=1,
        )
        if response.status_code >= 400:
            looks_like_login_redirect = _is_login_redirect_response(response)
            if config.auth.type.value == "browser" and not looks_like_login_redirect:
                return {
                    "ok": True,
                    "status_code": response.status_code,
                    "instance_url": config.instance_url,
                    "message": "Browser session is authenticated. Additional API credentials are not required; the configured probe path is unauthorized or blocked by ACLs.",
                    "auth_type": "browser",
                    "browser_session_authenticated": True,
                    "additional_api_credentials_required": False,
                    "warning": {
                        "probe_path": (
                            config.auth.browser.probe_path if config.auth.browser else probe_path
                        ),
                        "reason": "probe_path_unauthorized_or_acl_blocked",
                        "details": _safe_json(response),
                    },
                }
            location = response.headers.get("Location", "")
            response_url = str(response.url)
            return {
                "ok": False,
                "status_code": response.status_code,
                "message": "ServiceNow API reachable but request failed",
                "auth_type": config.auth.type.value,
                "browser_session_authenticated": (
                    False if config.auth.type.value == "browser" else None
                ),
                "additional_api_credentials_required": (
                    False if config.auth.type.value == "browser" else None
                ),
                "diagnostics": {
                    "response_url": response_url,
                    "is_redirect": bool(response.is_redirect),
                    "location": location,
                    "looks_like_login_redirect": looks_like_login_redirect,
                },
                "details": _safe_json(response),
            }
        return {
            "ok": True,
            "status_code": response.status_code,
            "instance_url": config.instance_url,
            "message": "ServiceNow API health check passed",
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": "ServiceNow API health check failed",
            "error": str(exc),
        }


@register_tool(
    name="sn_query",
    params=GenericQueryParams,
    description="Run generic query against any ServiceNow table",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_query(
    config: ServerConfig, auth_manager: AuthManager, params: GenericQueryParams
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/{params.table}"

    safe_limit, safe_fields, safety_notice = apply_payload_safety(
        params.table, params.limit, params.fields
    )

    query_params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
        "sysparm_offset": params.offset,
        "sysparm_display_value": str(params.display_value).lower(),
        "sysparm_exclude_reference_link": "true",
        "sysparm_suppress_pagination_header": "false",  # Ensure X-Total-Count is returned
    }
    if params.query:
        query_params["sysparm_query"] = params.query
    if safe_fields:
        query_params["sysparm_fields"] = safe_fields
    if params.orderby:
        key = "sysparm_orderby_desc" if params.orderby.startswith("-") else "sysparm_orderby"
        query_params[key] = params.orderby[1:] if params.orderby.startswith("-") else params.orderby

    try:
        response = auth_manager.make_request(
            "GET",
            url,
            params=query_params,
            timeout=config.timeout,
        )
        response.raise_for_status()

        total_count = response.headers.get("X-Total-Count")
        data = _safe_json(response)
        result = data.get("result", [])

        # Apply field-level truncation for stability
        safe_result = truncate_results(result)

        response_data = {
            "success": True,
            "table": params.table,
            "total_count": int(total_count) if total_count else len(result),
            "count": len(result),
            "results": safe_result,
        }
        if safety_notice:
            response_data["safety_notice"] = safety_notice

        return response_data
    except Exception as exc:
        return {
            "success": False,
            "table": params.table,
            "message": f"Query failed: {exc}",
        }


@register_tool(
    name="sn_aggregate",
    params=AggregateParams,
    description="Run aggregate statistics (count/sum/avg/min/max)",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_aggregate(
    config: ServerConfig, auth_manager: AuthManager, params: AggregateParams
) -> Dict[str, Any]:
    agg = params.aggregate.upper()
    url = f"{config.instance_url}/api/now/stats/{params.table}"
    query_params: Dict[str, Any] = {}
    if params.query:
        query_params["sysparm_query"] = params.query
    if params.group_by:
        query_params["sysparm_group_by"] = params.group_by

    if agg == "COUNT":
        query_params["sysparm_count"] = "true"
    else:
        if not params.field:
            return {
                "success": False,
                "message": f"field is required for aggregate={agg}",
            }
        query_params[f"sysparm_{agg.lower()}_fields"] = params.field

    try:
        response = auth_manager.make_request(
            "GET",
            url,
            params=query_params,
            timeout=config.timeout,
        )
        response.raise_for_status()
        return {
            "success": True,
            "table": params.table,
            "aggregate": agg,
            "result": _safe_json(response).get("result"),
        }
    except Exception as exc:
        return {
            "success": False,
            "table": params.table,
            "aggregate": agg,
            "message": f"Aggregate failed: {exc}",
        }


@register_tool(
    name="sn_schema",
    params=SchemaParams,
    description="Fetch table schema from sys_dictionary",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_schema(
    config: ServerConfig, auth_manager: AuthManager, params: SchemaParams
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/sys_dictionary"
    query_params = {
        "sysparm_query": f"name={params.table}^internal_type!=collection",
        "sysparm_fields": "element,column_label,internal_type,max_length,mandatory,reference",
        "sysparm_limit": params.limit,
        "sysparm_display_value": "true",
    }
    try:
        response = auth_manager.make_request(
            "GET",
            url,
            params=query_params,
            timeout=config.timeout,
        )
        response.raise_for_status()
        fields = _safe_json(response).get("result", [])
        shaped = [
            {
                "field": f.get("element"),
                "label": f.get("column_label"),
                "type": f.get("internal_type"),
                "max_length": f.get("max_length"),
                "mandatory": f.get("mandatory"),
                "reference": f.get("reference"),
            }
            for f in fields
            if f.get("element")
        ]
        return {
            "success": True,
            "table": params.table,
            "count": len(shaped),
            "fields": shaped,
        }
    except Exception as exc:
        return {
            "success": False,
            "table": params.table,
            "message": f"Schema fetch failed: {exc}",
        }


@register_tool(
    name="sn_discover",
    params=DiscoverParams,
    description="Discover tables by name or label keyword",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_discover(
    config: ServerConfig, auth_manager: AuthManager, params: DiscoverParams
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/sys_db_object"
    escaped = params.keyword.replace("^", "")
    query = f"nameLIKE{escaped}^ORlabelLIKE{escaped}"
    query_params = {
        "sysparm_query": query,
        "sysparm_limit": params.limit,
        "sysparm_fields": "name,label,super_class,sys_scope",
        "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
    }
    try:
        response = auth_manager.make_request(
            "GET",
            url,
            params=query_params,
            timeout=config.timeout,
        )
        response.raise_for_status()
        rows = _safe_json(response).get("result", [])
        return {
            "success": True,
            "keyword": params.keyword,
            "count": len(rows),
            "tables": rows,
        }
    except Exception as exc:
        return {
            "success": False,
            "keyword": params.keyword,
            "message": f"Discover failed: {exc}",
        }


@register_tool(
    name="sn_nl",
    params=NaturalLanguageParams,
    description="Natural language assistant for query/schema/aggregate intents",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_nl(
    config: ServerConfig, auth_manager: AuthManager, params: NaturalLanguageParams
) -> Dict[str, Any]:
    text = params.text.strip()
    lower = text.lower()

    table_alias = {
        "incident": "incident",
        "incidents": "incident",
        "change": "change_request",
        "changes": "change_request",
        "problem": "problem",
        "problems": "problem",
        "task": "task",
        "tasks": "task",
        "user": "sys_user",
        "users": "sys_user",
        "group": "sys_user_group",
        "groups": "sys_user_group",
        "server": "cmdb_ci_server",
        "servers": "cmdb_ci_server",
    }

    table = ""
    for alias in sorted(table_alias.keys(), key=len, reverse=True):
        if alias in lower:
            table = table_alias[alias]
            break

    if not table:
        table = "incident"

    if re.search(r"\b(count|how many|total)\b", lower):
        agg = AggregateParams(table=table, aggregate="COUNT")
        return sn_aggregate(config, auth_manager, agg)

    if re.search(r"\b(schema|fields|columns|describe)\b", lower):
        schema = SchemaParams(table=table, limit=500)
        return sn_schema(config, auth_manager, schema)

    query_parts: List[str] = []
    if re.search(r"\bp1\b|critical", lower):
        query_parts.append("priority=1")
    elif re.search(r"\bp2\b|high", lower):
        query_parts.append("priority=2")

    if re.search(r"\bopen|active|new\b", lower):
        query_parts.append("active=true")
    if re.search(r"\bclosed|resolved\b", lower):
        query_parts.append("state=7")

    ref_match = re.search(r"(inc|chg|prb|task)\d{5,10}", lower)
    if ref_match:
        query_parts.append(f"number={ref_match.group(0).upper()}")

    if re.search(r"\bdelete|remove\b", lower):
        return {
            "success": False,
            "executed": False,
            "message": "Natural language delete is blocked for safety. Use explicit delete tool.",
        }

    if re.search(r"\bcreate|new|open\b", lower) and not params.execute:
        return {
            "success": True,
            "executed": False,
            "message": "Write intent detected. Set execute=true to allow create operation.",
            "table": table,
        }

    query = "^".join(query_parts)
    query_params = GenericQueryParams(
        table=table,
        query=query,
        limit=20,
        offset=0,
        display_value=True,
    )
    return sn_query(config, auth_manager, query_params)
