"""Core cross-domain ServiceNow tools merged from legacy MCP projects."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl

import requests
from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

HEAVY_TABLES = {
    "sp_widget",
    "sys_script",
    "sys_script_include",
    "sys_client_script",
    "sys_ui_action",
    "sys_ui_page",
    "sys_ui_macro",
    "sys_ui_script",
    "sys_ws_operation",
    "sys_script_fix",
    "sys_metadata",
}
HEAVY_FIELDS = {"script", "template", "css", "client_script", "link", "demo_data", "html"}
DEFAULT_SAFE_FIELDS = "sys_id,name,id,sys_scope"

# Maximum total response size in characters to prevent context window overflow.
MAX_TOTAL_RESPONSE_SIZE = 200_000


def truncate_results(
    results: List[Dict[str, Any]],
    max_len: int = 50000,
    max_total: int = MAX_TOTAL_RESPONSE_SIZE,
) -> tuple[List[Dict[str, Any]], Optional[str]]:
    """Truncates long string values in results to prevent context overflow.

    Returns (safe_results, truncation_notice). The notice is None when no
    total-budget trimming occurred.
    """
    total_chars = 0
    truncation_notice = None
    safe: List[Dict[str, Any]] = []

    for row in results:
        row_chars = 0
        for key, value in row.items():
            if isinstance(value, str):
                if len(value) > max_len:
                    row[key] = value[:max_len] + f"... (truncated, original length: {len(value)})"
                row_chars += len(row[key]) if isinstance(row[key], str) else len(str(row[key]))
            else:
                row_chars += len(str(value))

        if total_chars + row_chars > max_total and safe:
            truncation_notice = (
                f"Response truncated at {len(safe)}/{len(results)} records "
                f"to stay within {max_total:,} character budget. "
                "Use offset/limit pagination to fetch remaining records."
            )
            break
        total_chars += row_chars
        safe.append(row)

    return safe, truncation_notice


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


# ---------------------------------------------------------------------------
# Shared paginated query helpers (used by portal_tools, detection_tools, etc.)
# ---------------------------------------------------------------------------

_MAX_PARALLEL_PAGES = 4  # Concurrent page fetches (keep conservative for SN rate limits)
_page_executor = ThreadPoolExecutor(max_workers=_MAX_PARALLEL_PAGES)

# ---------------------------------------------------------------------------
# Lightweight TTL cache for repeated identical queries within a session.
# Entries expire after _CACHE_TTL_SECONDS to prevent stale reads.
# ---------------------------------------------------------------------------

import threading as _threading
import time as _time
from collections import OrderedDict as _OrderedDict

_CACHE_TTL_SECONDS = 30
_CACHE_MAX_ENTRIES = 256

# Cache key is a tuple — cheaper to hash than an equivalent f-string.
_CacheKey = tuple  # (table, query, fields, limit, offset, display_value, no_count, orderby)
_query_cache: _OrderedDict[_CacheKey, tuple[float, Any]] = _OrderedDict()
_cache_lock = _threading.Lock()


def _cache_key(
    table: str,
    query: str,
    fields: str,
    limit: int,
    offset: int,
    *,
    display_value: bool,
    no_count: bool,
    orderby: Optional[str],
) -> _CacheKey:
    return (table, query, fields, limit, offset, display_value, no_count, orderby)


def _cache_get(key: str) -> Optional[Any]:
    with _cache_lock:
        entry = _query_cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if _time.monotonic() - ts > _CACHE_TTL_SECONDS:
            del _query_cache[key]
            return None
        # Move to end so most-recently-used items stay at the tail
        _query_cache.move_to_end(key)
        return value


def _cache_put(key: str, value: Any) -> None:
    with _cache_lock:
        if key in _query_cache:
            # Update existing entry and move to end
            _query_cache[key] = (_time.monotonic(), value)
            _query_cache.move_to_end(key)
            return
        # Evict oldest (first) entry — O(1) with OrderedDict
        if len(_query_cache) >= _CACHE_MAX_ENTRIES:
            _query_cache.popitem(last=False)
        _query_cache[key] = (_time.monotonic(), value)


def invalidate_query_cache(*, table: Optional[str] = None) -> int:
    """Invalidate cached query pages.

    When ``table`` is provided, only entries for that table are removed.
    Otherwise the full in-memory query cache is cleared.
    Returns the number of removed entries.
    """
    with _cache_lock:
        if table is None:
            removed = len(_query_cache)
            _query_cache.clear()
            return removed

        keys_to_delete = [key for key in _query_cache if key[0] == table]
        for key in keys_to_delete:
            del _query_cache[key]
        return len(keys_to_delete)


def sn_query_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    query: str,
    fields: str,
    limit: int,
    offset: int,
    display_value: bool = False,
    no_count: bool = False,
    orderby: Optional[str] = None,
    fail_silently: bool = True,
) -> tuple[List[Dict[str, Any]], Optional[int]]:
    """Fetch a single page from ServiceNow Table API.

    Returns ``(rows, total_count)``.  ``total_count`` is the server-reported
    X-Total-Count header (None when unavailable).  This bypasses
    ``apply_payload_safety`` — callers are responsible for limit clamping.

    Args:
        display_value: When False (default for internal use), skips expensive
            server-side reference joins.  Set True only when callers need
            human-readable display values.
        no_count: When True, sends ``sysparm_no_count=true`` to skip
            server-side total count computation for faster responses.

    Results are cached for ``_CACHE_TTL_SECONDS`` to avoid duplicate round-trips
    for identical queries within the same session.
    """
    ck = _cache_key(
        table,
        query,
        fields,
        limit,
        offset,
        display_value=display_value,
        no_count=no_count,
        orderby=orderby,
    )
    cached = _cache_get(ck)
    if cached is not None:
        return cached  # type: ignore[return-value]

    url = f"{config.instance_url}/api/now/table/{table}"
    params: Dict[str, Any] = {
        "sysparm_limit": limit,
        "sysparm_offset": offset,
        "sysparm_display_value": "true" if display_value else "false",
        "sysparm_exclude_reference_link": "true",
    }
    if no_count:
        params["sysparm_no_count"] = "true"
    else:
        params["sysparm_suppress_pagination_header"] = "false"
    if query:
        params["sysparm_query"] = query
    if fields:
        params["sysparm_fields"] = fields
    if orderby:
        key = "sysparm_orderby_desc" if orderby.startswith("-") else "sysparm_orderby"
        params[key] = orderby[1:] if orderby.startswith("-") else orderby
    try:
        response = auth_manager.make_request(
            "GET",
            url,
            params=params,
            timeout=config.request_timeout,
        )
        response.raise_for_status()
        total = response.headers.get("X-Total-Count")
        data = (
            json_fast.loads(response.content)
            if getattr(response, "content", None)
            else response.json()
        )
        rows = data.get("result", [])
        result = (rows, int(total) if total else None)
        _cache_put(ck, result)
        return result
    except Exception:
        if not fail_silently:
            raise
        return [], None


def sn_query_all(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    query: str,
    fields: str,
    page_size: int = 50,
    max_records: int = 100,
    parallel: bool = True,
    display_value: bool = False,
) -> List[Dict[str, Any]]:
    """Paginated fetch with optional parallel page retrieval.

    Strategy:
    1. Fetch the first page sequentially to get ``X-Total-Count``.
    2. If more pages are needed *and* ``parallel=True``, fetch remaining
       pages concurrently via ``ThreadPoolExecutor`` (up to ``_MAX_PARALLEL_PAGES``
       workers to stay within ServiceNow rate limits).
    3. Fall back to sequential if total count is unknown.

    Args:
        display_value: Passed through to ``sn_query_page``.  Default False
            for internal bulk fetches (faster); set True when callers need
            human-readable reference display values.
    """
    size = max(10, min(page_size, 100))
    cap = max(1, max_records)
    # --- First page (sequential, needs total count) ---
    first_fetch = min(size, cap)
    first_rows, total_count = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=first_fetch,
        offset=0,
        display_value=display_value,
    )
    if not first_rows:
        return []

    rows: List[Dict[str, Any]] = list(first_rows)
    if len(first_rows) < first_fetch:
        return rows[:cap]

    # Determine how many records remain
    remaining = cap - len(rows)
    if remaining <= 0:
        return rows[:cap]

    # If we know the total, we can calculate exact page offsets for parallel fetch
    if parallel and total_count is not None:
        server_remaining = min(total_count - len(rows), remaining)
        if server_remaining <= 0:
            return rows[:cap]

        # --- Dynamic page_size: if remaining fits in one page (<=100), enlarge ---
        dynamic_size = min(server_remaining, 100) if server_remaining <= 100 else size

        offsets = []
        off = len(rows)
        while off < len(rows) + server_remaining:
            offsets.append(off)
            off += dynamic_size

        def _fetch_page(page_offset: int) -> List[Dict[str, Any]]:
            fetch = min(dynamic_size, cap - page_offset)
            if fetch <= 0:
                return []
            # Subsequent pages skip total count for speed
            page_rows, _ = sn_query_page(
                config,
                auth_manager,
                table=table,
                query=query,
                fields=fields,
                limit=fetch,
                offset=page_offset,
                no_count=True,
                display_value=display_value,
            )
            return page_rows

        # Parallel fetch of remaining pages (reuse module-level executor)
        page_results: Dict[int, List[Dict[str, Any]]] = {}
        future_map = {_page_executor.submit(_fetch_page, off): off for off in offsets}
        for future in as_completed(future_map):
            page_offset = future_map[future]
            try:
                page_results[page_offset] = future.result()
            except Exception:
                logger.warning("Parallel page fetch failed at offset %s", page_offset)
                page_results[page_offset] = []

        # Merge in offset order
        for off in sorted(page_results.keys()):
            chunk = page_results[off]
            if not chunk:
                break  # Stop on empty page (end of data)
            rows.extend(chunk)
            if len(rows) >= cap:
                break

        return rows[:cap]

    # --- Fallback: sequential pagination (total_count unknown or parallel=False) ---
    offset = len(rows)
    while len(rows) < cap:
        fetch = min(size, cap - len(rows))
        chunk, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=fields,
            limit=fetch,
            offset=offset,
            no_count=True,
            display_value=display_value,
        )
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < fetch:
            break
        offset += fetch

    return rows[:cap]


# ---------------------------------------------------------------------------
# Shared count-only helper (Aggregate API)
# ---------------------------------------------------------------------------


def sn_count(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str = "",
) -> int:
    """Return record count via Aggregate API — single lightweight call, no bodies."""
    url = f"{config.instance_url}/api/now/stats/{table}"
    params: Dict[str, str] = {"sysparm_count": "true"}
    if query:
        params["sysparm_query"] = query
    try:
        resp = auth_manager.make_request("GET", url, params=params, timeout=config.timeout)
        data = resp.json() if hasattr(resp, "json") else {}
        result = data.get("result", {})
        stats = result.get("stats", result)
        return int(stats.get("count", 0))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Batch API — combine multiple queries into a single HTTP roundtrip
# ---------------------------------------------------------------------------

SN_BATCH_MAX_REQUESTS = 150  # ServiceNow batch endpoint limit


def sn_batch(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    requests: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Send multiple REST sub-requests in a single ``/api/now/batch`` call.

    Each item in *requests* must have ``id``, ``method``, and ``url`` keys.
    Returns a dict keyed by request ``id`` → response body.

    Automatically chunks into multiple batch calls when the list exceeds
    ``SN_BATCH_MAX_REQUESTS``.
    """
    if not requests:
        return {}

    results: Dict[str, Any] = {}

    # Chunk into SN_BATCH_MAX_REQUESTS-sized batches
    for i in range(0, len(requests), SN_BATCH_MAX_REQUESTS):
        chunk = requests[i : i + SN_BATCH_MAX_REQUESTS]
        payload = {
            "rest_requests": [
                {
                    "id": r["id"],
                    "method": r.get("method", "GET"),
                    "url": r["url"],
                    "headers": [{"name": "Accept", "value": "application/json"}],
                }
                for r in chunk
            ]
        }

        url = f"{config.instance_url}/api/now/batch"
        try:
            response = auth_manager.make_request(
                "POST",
                url,
                json=payload,
                timeout=config.request_timeout,
            )
            raw = getattr(response, "content", None)
            data = (
                json_fast.loads(raw) if isinstance(raw, (bytes, str)) and raw else response.json()
            )

            for sub in data.get("serviced_requests", []):
                req_id = sub.get("id", "")
                body = sub.get("body", {})
                status = sub.get("status_code", 0)
                if status >= 400:
                    # Preserve error info
                    if not body.get("error"):
                        body["error"] = {
                            "message": f"Batch sub-request failed with status {status}"
                        }
                results[req_id] = body
        except Exception as exc:
            logger.warning("Batch API call failed: %s", exc)
            for r in chunk:
                results[r["id"]] = {"error": {"message": str(exc)}}

    return results


class HealthCheckParams(BaseModel):
    timeout: int = Field(15, description="Request timeout in seconds")


class GenericQueryParams(BaseModel):
    table: str = Field(
        ...,
        description=(
            "Target table name for general record lookup (e.g., incident, kb_knowledge). "
            "For portal/widget/provider source analysis, prefer specialized portal tools instead of raw table reads. "
            "Heavy tables have automatic safety limits."
        ),
    )
    query: Optional[str] = Field(
        default=None,
        description=(
            "Encoded query (sysparm_query) for generic filtering. Use portal tracing/search tools when the goal is to map widget/provider logic or route targets."
        ),
    )
    fields: Optional[str] = Field(
        default=None,
        description=(
            "Comma-separated field list. Avoid large fields like 'script' for list queries; use specialized source-aware tools when code evidence is needed."
        ),
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
    limit: int = Field(500, description="Maximum schema rows (max 1000)")


class DiscoverParams(BaseModel):
    keyword: str = Field(..., description="Keyword to search table names and labels")
    limit: int = Field(50, description="Max matches (max 200)")


class NaturalLanguageParams(BaseModel):
    text: str = Field(..., description="Natural language query")
    execute: bool = Field(False, description="Execute writes")
    confirm: bool = Field(False, description="Confirmation for destructive operations")


def _safe_json(response: requests.Response) -> Dict[str, Any]:
    try:
        raw = getattr(response, "content", None)
        if isinstance(raw, (bytes, str)) and raw:
            return json_fast.loads(raw)
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
    description="Check ServiceNow API connectivity and auth status. Triggers browser login on first use in MFA mode.",
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
    description="Query any ServiceNow table with encoded query filters. Fallback only — prefer specialized tools for portal/widget/code tasks.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_query(
    config: ServerConfig, auth_manager: AuthManager, params: GenericQueryParams
) -> Dict[str, Any]:
    safe_limit, safe_fields, safety_notice = apply_payload_safety(
        params.table, params.limit, params.fields
    )

    try:
        result, total_count = sn_query_page(
            config,
            auth_manager,
            table=params.table,
            query=params.query or "",
            fields=safe_fields or "",
            limit=safe_limit,
            offset=params.offset,
            display_value=params.display_value,
            no_count=False,
            orderby=params.orderby,
            fail_silently=False,
        )

        # Apply field-level and total-budget truncation for stability
        safe_result, budget_notice = truncate_results(result)

        response_data: Dict[str, Any] = {
            "success": True,
            "table": params.table,
            "total_count": total_count if total_count is not None else len(result),
            "count": len(safe_result),
            "results": safe_result,
        }
        notices: List[str] = []
        if safety_notice:
            notices.append(safety_notice)
        if budget_notice:
            notices.append(budget_notice)
        if notices:
            response_data["safety_notice"] = " | ".join(notices)

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
    description="Run COUNT/SUM/AVG/MIN/MAX on any table with optional group_by. Returns stats without fetching records.",
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
    description="Fetch field names, types, labels, and constraints from sys_dictionary for a given table.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_schema(
    config: ServerConfig, auth_manager: AuthManager, params: SchemaParams
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/sys_dictionary"
    safe_limit = min(params.limit, 1000)
    query_params = {
        "sysparm_query": f"name={params.table}^internal_type!=collection",
        "sysparm_fields": "element,column_label,internal_type,max_length,mandatory,reference",
        "sysparm_limit": safe_limit,
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
    description="Find tables by name or label keyword. Returns table name, label, scope, and parent class.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_discover(
    config: ServerConfig, auth_manager: AuthManager, params: DiscoverParams
) -> Dict[str, Any]:
    url = f"{config.instance_url}/api/now/table/sys_db_object"
    escaped = params.keyword.replace("^", "")
    query = f"nameLIKE{escaped}^ORlabelLIKE{escaped}"
    safe_limit = min(params.limit, 200)
    query_params = {
        "sysparm_query": query,
        "sysparm_limit": safe_limit,
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
    description="Convert natural language to query, schema, or aggregate calls. Parses intent and dispatches to sn_query/sn_schema/sn_aggregate.",
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
