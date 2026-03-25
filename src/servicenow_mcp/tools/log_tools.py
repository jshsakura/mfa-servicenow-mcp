"""
Safe, token-efficient log query tools for the ServiceNow MCP server.
"""

import logging
from typing import Any, Dict, List, Optional

import requests
from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

DEFAULT_LOG_LIMIT = 10
MAX_LOG_LIMIT = 20
DEFAULT_TEXT_PREVIEW = 500
MAX_TEXT_PREVIEW = 2000

SYSTEM_LOG_FIELDS = "sys_id,level,source,message,sys_created_on"
JOURNAL_FIELDS = "sys_id,name,element,element_id,value,sys_created_by,sys_created_on"
TRANSACTION_LOG_FIELDS = (
    "sys_id,url,response_status,response_time,transaction_id,sys_created_by,sys_created_on"
)
BACKGROUND_LOG_FIELDS = (
    "sys_id,name,state,source,message,detail,percent_complete,sys_created_on,sys_updated_on"
)


class BaseLogQueryParams(BaseModel):
    limit: int = Field(
        DEFAULT_LOG_LIMIT,
        description=f"Maximum number of records to return. Clamped to {MAX_LOG_LIMIT}.",
    )
    offset: int = Field(0, description="Pagination offset")
    timeframe: str = Field(
        "last_24h",
        description="Relative time filter: last_hour, last_24h, last_7d, all",
    )
    contains: Optional[str] = Field(
        None, description="Text filter applied to the main message/value field"
    )
    query: Optional[str] = Field(
        None, description="Additional encoded query. Safety limits still apply."
    )
    max_text_length: int = Field(
        DEFAULT_TEXT_PREVIEW,
        description=f"Maximum length for large text fields. Clamped to {MAX_TEXT_PREVIEW}.",
    )


class GetSystemLogsParams(BaseLogQueryParams):
    level: Optional[str] = Field(None, description="Filter by log level")
    source: Optional[str] = Field(None, description="Filter by source (LIKE match)")


class GetJournalEntriesParams(BaseLogQueryParams):
    table: Optional[str] = Field(None, description="Filter by target table name")
    record_sys_id: Optional[str] = Field(None, description="Filter by target record sys_id")
    field_name: Optional[str] = Field(None, description="Filter by journal field name")
    created_by: Optional[str] = Field(None, description="Filter by creator")


class GetTransactionLogsParams(BaseLogQueryParams):
    url_contains: Optional[str] = Field(None, description="Filter by request URL (LIKE match)")
    response_status: Optional[str] = Field(None, description="Filter by response status")
    min_response_time_ms: Optional[int] = Field(
        None, description="Only include requests slower than this threshold"
    )
    created_by: Optional[str] = Field(None, description="Filter by creator")


class GetBackgroundScriptLogsParams(BaseLogQueryParams):
    name: Optional[str] = Field(None, description="Filter by execution name (LIKE match)")
    state: Optional[str] = Field(None, description="Filter by execution state")
    source: Optional[str] = Field(None, description="Filter by execution source")


def _safe_json(response: requests.Response) -> Dict[str, Any]:
    try:
        return response.json()
    except Exception:
        return {"raw": response.text}


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LOG_LIMIT))


def _clamp_text_length(length: int) -> int:
    return max(100, min(length, MAX_TEXT_PREVIEW))


def _timeframe_query(timeframe: str) -> Optional[str]:
    normalized = (timeframe or "last_24h").strip().lower()
    if normalized == "all":
        return None
    if normalized == "last_hour":
        return "sys_created_on>=javascript:gs.hoursAgoStart(1)"
    if normalized == "last_7d":
        return "sys_created_on>=javascript:gs.daysAgoStart(7)"
    return "sys_created_on>=javascript:gs.hoursAgoStart(24)"


def _truncate_results(results: List[Dict[str, Any]], max_text_length: int) -> List[Dict[str, Any]]:
    truncated_rows: List[Dict[str, Any]] = []
    for row in results:
        safe_row: Dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, str) and len(value) > max_text_length:
                safe_row[key] = (
                    value[:max_text_length] + f"... (truncated, original length: {len(value)})"
                )
            else:
                safe_row[key] = value
        truncated_rows.append(safe_row)
    return truncated_rows


def _fetch_logs(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    fields: str,
    limit: int,
    offset: int,
    timeframe: str,
    query_parts: List[str],
    text_preview_length: int,
) -> Dict[str, Any]:
    query_params: Dict[str, Any] = {
        "sysparm_limit": _clamp_limit(limit),
        "sysparm_offset": max(0, offset),
        "sysparm_fields": fields,
        "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
        "sysparm_suppress_pagination_header": "false",
        "sysparm_orderby_desc": "sys_created_on",
    }

    timeframe_part = _timeframe_query(timeframe)
    if timeframe_part:
        query_parts.insert(0, timeframe_part)
    if query_parts:
        query_params["sysparm_query"] = "^".join(part for part in query_parts if part)

    url = f"{config.instance_url}/api/now/table/{table}"

    try:
        response = auth_manager.make_request(
            "GET",
            url,
            params=query_params,
            timeout=config.timeout,
        )
        response.raise_for_status()

        data = _safe_json(response)
        results = data.get("result", [])
        total_count = response.headers.get("X-Total-Count")

        return {
            "success": True,
            "table": table,
            "count": len(results),
            "total_count": int(total_count) if total_count else len(results),
            "limit_applied": query_params["sysparm_limit"],
            "fields": fields.split(","),
            "results": _truncate_results(results, _clamp_text_length(text_preview_length)),
        }
    except requests.RequestException as exc:
        logger.error("Error querying log table %s: %s", table, exc)
        return {
            "success": False,
            "table": table,
            "message": f"Failed to query log table '{table}'",
            "error": str(exc),
        }


def get_system_logs(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetSystemLogsParams,
) -> Dict[str, Any]:
    query_parts: List[str] = []
    if params.level:
        query_parts.append(f"level={params.level}")
    if params.source:
        query_parts.append(f"sourceLIKE{params.source}")
    if params.contains:
        query_parts.append(f"messageLIKE{params.contains}")
    if params.query:
        query_parts.append(params.query)

    result = _fetch_logs(
        config,
        auth_manager,
        table="syslog",
        fields=SYSTEM_LOG_FIELDS,
        limit=params.limit,
        offset=params.offset,
        timeframe=params.timeframe,
        query_parts=query_parts,
        text_preview_length=params.max_text_length,
    )
    if result.get("success"):
        result[
            "safety_notice"
        ] = "System logs use fixed summary fields and a hard limit cap to avoid large payloads."
    return result


def get_journal_entries(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetJournalEntriesParams,
) -> Dict[str, Any]:
    query_parts: List[str] = []
    if params.table:
        query_parts.append(f"name={params.table}")
    if params.record_sys_id:
        query_parts.append(f"element_id={params.record_sys_id}")
    if params.field_name:
        query_parts.append(f"element={params.field_name}")
    if params.created_by:
        query_parts.append(f"sys_created_by={params.created_by}")
    if params.contains:
        query_parts.append(f"valueLIKE{params.contains}")
    if params.query:
        query_parts.append(params.query)

    result = _fetch_logs(
        config,
        auth_manager,
        table="sys_journal_field",
        fields=JOURNAL_FIELDS,
        limit=params.limit,
        offset=params.offset,
        timeframe=params.timeframe,
        query_parts=query_parts,
        text_preview_length=params.max_text_length,
    )
    if result.get("success"):
        result[
            "safety_notice"
        ] = "Journal entry queries are restricted to summary fields. Filter by record_sys_id or table when possible."
    return result


def get_transaction_logs(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetTransactionLogsParams,
) -> Dict[str, Any]:
    query_parts: List[str] = []
    if params.url_contains:
        query_parts.append(f"urlLIKE{params.url_contains}")
    if params.response_status:
        query_parts.append(f"response_status={params.response_status}")
    if params.min_response_time_ms is not None:
        query_parts.append(f"response_time>={params.min_response_time_ms}")
    if params.created_by:
        query_parts.append(f"sys_created_by={params.created_by}")
    if params.query:
        query_parts.append(params.query)

    result = _fetch_logs(
        config,
        auth_manager,
        table="syslog_transaction",
        fields=TRANSACTION_LOG_FIELDS,
        limit=params.limit,
        offset=params.offset,
        timeframe=params.timeframe,
        query_parts=query_parts,
        text_preview_length=params.max_text_length,
    )
    if result.get("success"):
        result[
            "safety_notice"
        ] = "Transaction logs are returned as summaries only. Use filters such as url_contains or min_response_time_ms."
    return result


def get_background_script_logs(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetBackgroundScriptLogsParams,
) -> Dict[str, Any]:
    query_parts: List[str] = []
    if params.name:
        query_parts.append(f"nameLIKE{params.name}")
    if params.state:
        query_parts.append(f"state={params.state}")
    if params.source:
        query_parts.append(f"sourceLIKE{params.source}")
    if params.contains:
        query_parts.append(f"messageLIKE{params.contains}")
    if params.query:
        query_parts.append(params.query)

    result = _fetch_logs(
        config,
        auth_manager,
        table="sys_execution_tracker",
        fields=BACKGROUND_LOG_FIELDS,
        limit=params.limit,
        offset=params.offset,
        timeframe=params.timeframe,
        query_parts=query_parts,
        text_preview_length=params.max_text_length,
    )
    if result.get("success"):
        result[
            "safety_notice"
        ] = "Background execution logs come from sys_execution_tracker with capped result size and truncated text fields."
    return result
