"""
Unified log query tool for ServiceNow MCP.

Single get_logs tool covers all log types: system, journal, transaction, background.
LLM selects log_type based on intent — no ambiguity about which tool to call.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

DEFAULT_LOG_LIMIT = 10
MAX_LOG_LIMIT = 20
DEFAULT_TEXT_PREVIEW = 500
MAX_TEXT_PREVIEW = 2000

# ---------------------------------------------------------------------------
# Log type registry
# ---------------------------------------------------------------------------

LOG_TYPES: Dict[str, Dict[str, Any]] = {
    "system": {
        "table": "syslog",
        "fields": "sys_id,level,source,message,sys_created_on",
        "label": "System Log",
        "hint": "Script errors, warnings, gs.log output, platform messages",
        "filters": {
            "level": ("level", "="),
            "source": ("source", "LIKE"),
            "contains": ("message", "LIKE"),
        },
    },
    "journal": {
        "table": "sys_journal_field",
        "fields": "sys_id,name,element,element_id,value,sys_created_by,sys_created_on",
        "label": "Journal Entries",
        "hint": "Work notes, comments, activity log on records",
        "filters": {
            "table": ("name", "="),
            "record_sys_id": ("element_id", "="),
            "field_name": ("element", "="),
            "created_by": ("sys_created_by", "="),
            "contains": ("value", "LIKE"),
        },
    },
    "transaction": {
        "table": "syslog_transaction",
        "fields": "sys_id,url,response_status,response_time,transaction_id,sys_created_by,sys_created_on",
        "label": "Transaction Log",
        "hint": "HTTP request/response logs — URL, status code, response time",
        "filters": {
            "url_contains": ("url", "LIKE"),
            "response_status": ("response_status", "="),
            "min_response_time_ms": ("response_time", ">="),
            "created_by": ("sys_created_by", "="),
        },
    },
    "background": {
        "table": "sys_execution_tracker",
        "fields": "sys_id,name,state,source,message,detail,percent_complete,sys_created_on,sys_updated_on",
        "label": "Background Execution",
        "hint": "Scheduled jobs, fix scripts, background script runs",
        "filters": {
            "name": ("name", "LIKE"),
            "state": ("state", "="),
            "source": ("source", "LIKE"),
            "contains": ("message", "LIKE"),
        },
    },
}

# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


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
    clamped_limit = _clamp_limit(limit)
    safe_offset = max(0, offset)

    timeframe_part = _timeframe_query(timeframe)
    all_parts: List[str] = []
    if timeframe_part:
        all_parts.append(timeframe_part)
    all_parts.extend(part for part in query_parts if part)
    query_str = "^".join(all_parts)

    try:
        rows, total_count = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query_str,
            fields=fields,
            limit=clamped_limit,
            offset=safe_offset,
            display_value=True,
            orderby="-sys_created_on",
            fail_silently=False,
        )

        return {
            "success": True,
            "table": table,
            "count": len(rows),
            "total_count": total_count if total_count is not None else len(rows),
            "limit_applied": clamped_limit,
            "fields": fields.split(","),
            "results": _truncate_results(rows, _clamp_text_length(text_preview_length)),
        }
    except Exception as exc:
        logger.error("Error querying log table %s: %s", table, exc)
        return {
            "success": False,
            "table": table,
            "message": f"Failed to query log table '{table}'",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Unified MCP tool
# ---------------------------------------------------------------------------

_LOG_TYPE_NAMES = ", ".join(sorted(LOG_TYPES.keys()))


class GetLogsParams(BaseModel):
    log_type: str = Field(
        ...,
        description=(
            "Log type to query. One of: system, journal, transaction, background. "
            "system = script errors, gs.log output. "
            "journal = work notes/comments on records. "
            "transaction = HTTP request/response. "
            "background = scheduled job/fix script runs."
        ),
    )
    limit: int = Field(
        default=DEFAULT_LOG_LIMIT,
        description=f"Max records. Clamped to {MAX_LOG_LIMIT}.",
    )
    offset: int = Field(default=0, description="Pagination offset.")
    timeframe: str = Field(
        default="last_24h",
        description="Time filter: last_hour, last_24h, last_7d, all",
    )
    # --- Universal filter ---
    contains: Optional[str] = Field(
        default=None,
        description="Text search on the main content field (message/value).",
    )
    # --- system filters ---
    level: Optional[str] = Field(default=None, description="[system] Log level: error, warning, info, debug")
    source: Optional[str] = Field(default=None, description="[system/background] Source name (LIKE match)")
    # --- journal filters ---
    table: Optional[str] = Field(default=None, description="[journal] Target table (e.g. incident, x_app_request)")
    record_sys_id: Optional[str] = Field(default=None, description="[journal] Specific record sys_id")
    field_name: Optional[str] = Field(default=None, description="[journal] Field name (work_notes, comments)")
    created_by: Optional[str] = Field(default=None, description="[journal/transaction] Filter by user")
    # --- transaction filters ---
    url_contains: Optional[str] = Field(default=None, description="[transaction] URL pattern (LIKE match)")
    response_status: Optional[str] = Field(default=None, description="[transaction] HTTP status code")
    min_response_time_ms: Optional[int] = Field(default=None, description="[transaction] Slow request threshold (ms)")
    # --- background filters ---
    name: Optional[str] = Field(default=None, description="[background] Execution name (LIKE match)")
    state: Optional[str] = Field(default=None, description="[background] State: running, complete, cancelled")
    # --- advanced ---
    query: Optional[str] = Field(
        default=None, description="Raw encoded query appended to filters.",
    )
    max_text_length: int = Field(
        default=DEFAULT_TEXT_PREVIEW,
        description=f"Max text field length. Clamped to {MAX_TEXT_PREVIEW}.",
    )


@register_tool(
    "get_logs",
    params=GetLogsParams,
    description=(
        "Query ServiceNow logs. "
        "log_type: system (script errors, gs.log), journal (work notes/comments), "
        "transaction (HTTP requests), background (scheduled jobs). "
        "Each type has specific filters. Hard-capped at 20 rows."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def get_logs(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetLogsParams,
) -> Dict[str, Any]:
    log_type = params.log_type.strip().lower()
    if log_type not in LOG_TYPES:
        return {
            "success": False,
            "message": f"Unknown log_type '{params.log_type}'. Valid: {_LOG_TYPE_NAMES}",
            "available_types": {
                name: cfg["hint"] for name, cfg in LOG_TYPES.items()
            },
        }

    type_cfg = LOG_TYPES[log_type]
    filter_defs = type_cfg["filters"]

    # Build query from applicable filters
    query_parts: List[str] = []
    param_dict = params.model_dump(exclude_none=True)
    for param_name, (field_name, operator) in filter_defs.items():
        value = param_dict.get(param_name)
        if value is not None:
            query_parts.append(f"{field_name}{operator}{value}")
    if params.query:
        query_parts.append(params.query)

    result = _fetch_logs(
        config,
        auth_manager,
        table=type_cfg["table"],
        fields=type_cfg["fields"],
        limit=params.limit,
        offset=params.offset,
        timeframe=params.timeframe,
        query_parts=query_parts,
        text_preview_length=params.max_text_length,
    )

    if result.get("success"):
        result["log_type"] = log_type
        result["log_label"] = type_cfg["label"]
        result["safety_notice"] = (
            f"Queried {type_cfg['table']} with hard limit cap and text truncation."
        )

    return result
