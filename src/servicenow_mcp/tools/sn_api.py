"""Core cross-domain ServiceNow tools merged from legacy MCP projects."""

import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import parse_qs, parse_qsl, unquote, urlparse

import requests
from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

# Fields that explode payloads when requested. Trigger limit clamp regardless
# of table — guards every table, not a hand-picked list.
HEAVY_FIELDS = {"script", "template", "css", "client_script", "link", "demo_data", "html"}

# Default field projection applied when caller passes no `fields`.
# ServiceNow Table API silently drops fields that don't exist on the target
# table, so this list works universally — common columns return when present,
# missing ones are no-ops. Callers who need more must opt-in via `fields=`.
UNIVERSAL_SAFE_FIELDS = (
    "sys_id,sys_class_name,sys_created_on,sys_updated_on,"
    "name,number,short_description,state,active,sys_scope"
)

# Maximum total response size in characters to prevent context window overflow.
MAX_TOTAL_RESPONSE_SIZE = 200_000

# ---------------------------------------------------------------------------
# Cached field normalization — avoids repeated split/lower on identical strings.
# ---------------------------------------------------------------------------
_FIELD_NORM_CACHE: Dict[str, List[str]] = {}
_FIELD_NORM_CACHE_MAX = 128


def _normalize_fields(fields: str) -> List[str]:
    """Return lowercased, stripped field list from a comma-separated string.

    Results are cached so repeated queries with the same field string
    skip redundant split+lower work.
    """
    cached = _FIELD_NORM_CACHE.get(fields)
    if cached is not None:
        return cached
    normalized = [f.strip().lower() for f in fields.split(",")]
    if len(_FIELD_NORM_CACHE) < _FIELD_NORM_CACHE_MAX:
        _FIELD_NORM_CACHE[fields] = normalized
    return normalized


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
                orig_len = len(value)
                if orig_len > max_len:
                    suffix = f"... (truncated, original length: {orig_len})"
                    row[key] = value[:max_len] + suffix
                    row_chars += max_len + len(suffix)
                else:
                    row_chars += orig_len
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

    Defaults to UNIVERSAL_SAFE_FIELDS for ANY table when caller omits fields —
    a whitelist guards only known-bad tables, but custom app tables (x_*, u_*)
    can also explode payloads. Callers needing more pass fields= explicitly.
    """
    safe_limit = min(limit, 100)

    if not fields:
        return (
            safe_limit,
            UNIVERSAL_SAFE_FIELDS,
            "Fields defaulted to safe set. Pass fields= to opt-in to more.",
        )

    requested_fields = _normalize_fields(fields)
    has_heavy_fields = any(hf in requested_fields for hf in HEAVY_FIELDS)
    if has_heavy_fields and safe_limit > 5:
        return (
            5,
            fields,
            "Limit clamped to 5 because heavy fields were requested. Fetch remaining items individually.",
        )

    return safe_limit, fields, None


# ---------------------------------------------------------------------------
# Shared paginated query helpers (used by portal_tools, detection_tools, etc.)
# ---------------------------------------------------------------------------

_MAX_PARALLEL_PAGES = 4  # Concurrent page fetches (keep conservative for SN rate limits)
_page_executor: Optional[ThreadPoolExecutor] = None


def _get_page_executor() -> ThreadPoolExecutor:
    """Lazily create the page executor to avoid idle thread overhead at import."""
    global _page_executor
    if _page_executor is None:
        _page_executor = ThreadPoolExecutor(
            max_workers=_MAX_PARALLEL_PAGES, thread_name_prefix="sn-page"
        )
    return _page_executor


# ---------------------------------------------------------------------------
# Retry configuration for transient API errors.
# ---------------------------------------------------------------------------
# Retried: network errors, timeouts, HTTP 429 (rate-limit), HTTP 5xx.
# Not retried: 4xx client errors (except 429) — these are permanent.
_RETRY_MAX_ATTEMPTS = 3  # retries after the first attempt (4 total)
_RETRY_BASE_DELAY_S = 1.0  # first retry waits ~1 s
_RETRY_MAX_DELAY_S = 16.0  # cap for exponential back-off


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return status is not None and (status == 429 or status >= 500)
    return False


def _retry_delay(attempt: int) -> float:
    """Exponential back-off: 1 s, 2 s, 4 s, … capped at _RETRY_MAX_DELAY_S."""
    return min(_RETRY_BASE_DELAY_S * (2**attempt), _RETRY_MAX_DELAY_S)


# ---------------------------------------------------------------------------
# Lightweight TTL cache for repeated identical queries within a session.
# Entries expire after _CACHE_TTL_SECONDS to prevent stale reads.
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 30
_CACHE_MAX_ENTRIES = 256

# Cache key is a tuple — cheaper to hash than an equivalent f-string.
_CacheKey = tuple  # (table, query, fields, limit, offset, display_value, no_count, orderby)
_query_cache: "OrderedDict[_CacheKey, tuple[float, Any]]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_key(
    table: str,
    query: str,
    fields: str,
    limit: int,
    offset: int,
    *,
    display_value: "bool | str",
    no_count: bool,
    orderby: Optional[str],
) -> _CacheKey:
    return (table, query, fields, limit, offset, display_value, no_count, orderby)


def _cache_get(key: _CacheKey) -> Optional[Any]:
    with _cache_lock:
        entry = _query_cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > _CACHE_TTL_SECONDS:
            del _query_cache[key]
            return None
        # Move to end so most-recently-used items stay at the tail
        _query_cache.move_to_end(key)
        return value


def _cache_put(key: _CacheKey, value: Any) -> None:
    with _cache_lock:
        if key in _query_cache:
            # Update existing entry and move to end
            _query_cache[key] = (time.monotonic(), value)
            _query_cache.move_to_end(key)
            return
        # Evict oldest (first) entry — O(1) with OrderedDict
        if len(_query_cache) >= _CACHE_MAX_ENTRIES:
            _query_cache.popitem(last=False)
        _query_cache[key] = (time.monotonic(), value)


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
    display_value: "bool | str" = False,
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
            human-readable display values.  Pass ``"all"`` to get both raw
            and display values (each reference field becomes a dict with
            ``value`` and ``display_value`` keys).
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
        "sysparm_display_value": (
            "all" if display_value == "all" else ("true" if display_value else "false")
        ),
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
        data = json_fast.loads(response.content) if response.content else response.json()
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
    display_value: "bool | str" = False,
    fail_silently: bool = True,
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
        fail_silently: When False, HTTP/network errors raise instead of
            returning an empty list.  Pass False for bulk download operations
            so callers can surface the error rather than reporting 0 records.
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
        fail_silently=fail_silently,
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
                fail_silently=fail_silently,
            )
            return page_rows

        # Parallel fetch of remaining pages (reuse lazily-created executor)
        page_results: Dict[int, List[Dict[str, Any]]] = {}
        executor = _get_page_executor()
        future_map = {executor.submit(_fetch_page, off): off for off in offsets}
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
            fail_silently=fail_silently,
        )
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < fetch:
            break
        offset += fetch

    return rows[:cap]


def sn_query_all_with_retry(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    query: str,
    fields: str,
    page_size: int = 50,
    max_records: int = 100,
    display_value: "bool | str" = False,
    max_attempts: int = _RETRY_MAX_ATTEMPTS + 1,
) -> List[Dict[str, Any]]:
    """sn_query_all with explicit retry for bulk download operations.

    Unlike sn_query_page's fail_silently, this function retries visibly at
    the call-site level so callers see retry logs and control the attempt count.
    Raises the last exception when all attempts are exhausted.
    """
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(max_attempts):
        try:
            return sn_query_all(
                config,
                auth_manager,
                table=table,
                query=query,
                fields=fields,
                page_size=page_size,
                max_records=max_records,
                display_value=display_value,
                fail_silently=False,
            )
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < max_attempts and _is_retryable(exc):
                delay = _retry_delay(attempt)
                logger.warning(
                    "Transient error on %s (attempt %d/%d), retrying in %.1fs: %s",
                    table,
                    attempt + 1,
                    max_attempts,
                    delay,
                    exc,
                )
                time.sleep(delay)
            else:
                break
    raise last_exc


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
    timeout: int = Field(default=15, description="Request timeout in seconds")


class GenericQueryParams(BaseModel):
    table: str = Field(
        default=...,
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
    limit: int = Field(default=20, description="Max records (max 100). Default 20.")
    offset: int = Field(
        default=0, description="Pagination offset. Use with total_count to iterate."
    )
    orderby: Optional[str] = Field(
        default=None, description="Order by field, supports -field for desc"
    )
    display_value: bool = Field(
        default=False,
        description="Resolve reference fields to display labels. Slower; opt-in only.",
    )
    include_count: bool = Field(
        default=False,
        description="Compute total_count via X-Total-Count. Slower; needed for pagination.",
    )


class AggregateParams(BaseModel):
    table: str = Field(..., description="Target table name")
    aggregate: str = Field(default="COUNT", description="COUNT, SUM, AVG, MIN, MAX")
    field: Optional[str] = Field(default=None, description="Field for SUM/AVG/MIN/MAX")
    query: Optional[str] = Field(default=None, description="Encoded query")
    group_by: Optional[str] = Field(default=None, description="Group by field")


class SchemaParams(BaseModel):
    table: str = Field(..., description="Table name for schema lookup")
    limit: int = Field(default=500, description="Maximum schema rows (max 1000)")


class DiscoverParams(BaseModel):
    keyword: str = Field(..., description="Keyword to search table names and labels")
    limit: int = Field(default=50, description="Max matches (max 200)")


class NaturalLanguageParams(BaseModel):
    text: str = Field(..., description="Natural language query")
    execute: bool = Field(default=False, description="Execute writes")
    confirm: bool = Field(default=False, description="Confirmation for destructive operations")


def _generate_query_hint(query: str, error_msg: str) -> Optional[str]:
    """Generate a diagnostic hint for common sn_query failure patterns."""
    hints: List[str] = []
    if "IN" in query and "&" in query:
        hints.append(
            "Query contains '&' inside an IN clause — ServiceNow may split "
            "the parameter. Use sys_idIN instead of nameIN, or encode '&' as '%26'."
        )
    if "nameIN" in query and ("'" in query or '"' in query):
        hints.append(
            "nameIN with quotes may cause parse errors. "
            "Remove surrounding quotes from name values."
        )
    if "LIKE" in query and len(query) > 500:
        hints.append("Very long LIKE query — consider breaking into multiple smaller queries.")
    error_lower = error_msg.lower()
    if "timeout" in error_lower or "timed out" in error_lower:
        hints.append(
            "Request timed out. Try reducing limit, adding more specific filters, "
            "or querying by sys_id instead of name."
        )
    if "401" in error_lower or "unauthorized" in error_lower:
        hints.append(
            "401 Unauthorized — if a browser login just opened, the session was already refreshed. "
            "A persistent 401 after re-auth means ACL blocks this table (not a session issue). "
            "Try a different table or use a Flow Designer tool instead."
        )
    if "403" in error_lower or "forbidden" in error_lower:
        hints.append(
            "403 Forbidden — table ACL blocks REST API access. "
            "For scoped tables (x_* prefix), try browser auth or grant the API user the app role."
        )
    return " | ".join(hints) if hints else None


def _safe_json(response: requests.Response) -> Dict[str, Any]:
    try:
        if response.content:
            return json_fast.loads(response.content)
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
    probe_path = "/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id"
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
    description="Generic table query; last resort only. Domain tools exist: flows->list_flow_designers, BR->search_server_code, WF->manage_workflow.",
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
            no_count=not params.include_count,
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
        response: Dict[str, Any] = {
            "success": False,
            "table": params.table,
            "message": f"Query failed: {exc}",
            "query_echo": params.query or "",
        }
        hint = _generate_query_hint(params.query or "", str(exc))
        if hint:
            response["hint"] = hint
        return response


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
    description="Convert natural language to sn_query/sn_schema/sn_aggregate calls. Parses intent and dispatches.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_nl(
    config: ServerConfig, auth_manager: AuthManager, params: NaturalLanguageParams
) -> Dict[str, Any]:
    text = params.text.strip()

    # Phase 1: download/export intent. Resolver is pure regex, no SN calls.
    # Returns None when text isn't a download request → fall through to legacy.
    from servicenow_mcp.tools.nl_download_intents import resolve_download_intent

    download_intent = resolve_download_intent(text)
    if download_intent is not None:
        if download_intent["needs_clarification"]:
            return {
                "success": True,
                "executed": False,
                "intent": download_intent["intent"],
                "target_type": download_intent["target_type"],
                "needs_clarification": True,
                "missing": download_intent["missing"],
                "message": download_intent["question"],
                "suggested_tool": download_intent.get("suggested_tool"),
            }
        tool_name = download_intent["tool"]
        tool_params = download_intent["params"]
        if tool_name == "download_app_sources":
            from servicenow_mcp.tools.source_tools import (
                DownloadAppSourcesParams,
                download_app_sources,
            )

            return download_app_sources(
                config, auth_manager, DownloadAppSourcesParams(**tool_params)
            )
        if tool_name == "download_portal_sources":
            from servicenow_mcp.tools.portal_tools import (
                DownloadPortalSourcesParams,
                download_portal_sources,
            )

            return download_portal_sources(
                config, auth_manager, DownloadPortalSourcesParams(**tool_params)
            )

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


# ---------------------------------------------------------------------------
# sn_write — generic Table-API CRUD with hard-coded denylist
# ---------------------------------------------------------------------------

# Tables an LLM should never write to via the generic primitive. ACL/scope/
# user/role tables and the sys_remote_update_set staging area can corrupt the
# instance if mishandled. Deletes against any sys_* table are also blocked.
# Denylist is intentionally code-baked (not config) — a junior must use the
# matching specialized tool (e.g. update_user) to touch these.
SN_WRITE_DENY_TABLES = frozenset(
    {
        "sys_user",
        "sys_user_group",
        "sys_user_has_role",
        "sys_user_grmember",
        "sys_security_acl",
        "sys_app",
        "sys_scope",
        "sys_dictionary",
        "sys_db_object",
        "sys_remote_update_set",
        "sys_update_set",
    }
)


class SnWriteParams(BaseModel):
    table: str = Field(..., description="Target table name")
    action: Literal["create", "update", "delete"] = Field(...)
    sys_id: Optional[str] = Field(default=None, description="Required for update/delete")
    fields: Optional[Dict[str, Any]] = Field(
        default=None, description="Field values for create/update"
    )
    dry_run: bool = Field(default=False, description="Preview without committing")


def _sn_write_denied(table: str, action: str) -> Optional[str]:
    """Return a denial reason if this table+action is blocked, else None."""
    if table in SN_WRITE_DENY_TABLES:
        return (
            f"Table '{table}' is blocked from sn_write. Use a domain-specific "
            f"tool (e.g. manage_user, manage_group) for ACL-protected tables."
        )
    if action == "delete" and table.startswith("sys_"):
        return (
            f"delete blocked on sys_* tables (got '{table}'). System metadata "
            "deletes must go through the platform UI or update sets."
        )
    return None


@register_tool(
    name="sn_write",
    params=SnWriteParams,
    description="Generic create/update/delete on any table. Use when no manage_X tool fits. (confirm='approve')",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_write(
    config: ServerConfig, auth_manager: AuthManager, params: SnWriteParams
) -> Dict[str, Any]:
    deny = _sn_write_denied(params.table, params.action)
    if deny:
        return {"success": False, "table": params.table, "action": params.action, "error": deny}

    if params.action in ("update", "delete") and not params.sys_id:
        return {
            "success": False,
            "table": params.table,
            "action": params.action,
            "error": f"sys_id is required for action='{params.action}'.",
        }
    if params.action in ("create", "update") and not params.fields:
        return {
            "success": False,
            "table": params.table,
            "action": params.action,
            "error": f"fields is required for action='{params.action}'.",
        }

    if params.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "table": params.table,
            "action": params.action,
            "sys_id": params.sys_id,
            "fields": params.fields,
            "message": "Preview only — no changes committed.",
        }

    base = f"{config.instance_url}/api/now/table/{params.table}"
    try:
        if params.action == "create":
            response = auth_manager.make_request(
                "POST", base, json=params.fields, timeout=config.timeout
            )
        elif params.action == "update":
            response = auth_manager.make_request(
                "PATCH",
                f"{base}/{params.sys_id}",
                json=params.fields,
                timeout=config.timeout,
            )
        else:  # delete
            response = auth_manager.make_request(
                "DELETE", f"{base}/{params.sys_id}", timeout=config.timeout
            )
        response.raise_for_status()
    except Exception as exc:
        return {
            "success": False,
            "table": params.table,
            "action": params.action,
            "sys_id": params.sys_id,
            "error": f"sn_write {params.action} failed: {exc}",
        }

    body = _safe_json(response) if params.action != "delete" else {}
    return {
        "success": True,
        "table": params.table,
        "action": params.action,
        "sys_id": params.sys_id or (body.get("result") or {}).get("sys_id"),
        "result": body.get("result") if params.action != "delete" else None,
    }


# ---------------------------------------------------------------------------
# sn_resolve_url — parse a ServiceNow URL → table + sys_id + suggested next tool
# ---------------------------------------------------------------------------

# Maps ServiceNow form table names to the recommended next tool. Custom tables
# (x_*/u_*) and unknown OOTB tables fall through to sn_query/sn_write.
_TABLE_TO_TOOL: Dict[str, str] = {
    "incident": "manage_incident",
    "change_request": "manage_change",
    "kb_knowledge": "manage_kb_article",
    "sys_update_set": "manage_changeset",
    "sys_script_include": "manage_script_include",
    "wf_workflow": "manage_workflow",
    "sys_hub_flow": "get_flow_designer_detail",
    "sp_widget": "get_widget_bundle",
    "sp_page": "get_page",
    "sp_portal": "get_portal",
}


class SnResolveUrlParams(BaseModel):
    url: str = Field(..., description="A ServiceNow screen URL to inspect")


def _resolve_servicenow_url(url: str) -> Dict[str, Any]:
    """Pure URL parser — no network calls. Returns table/sys_id/scope hints."""
    parsed = urlparse(url.strip())
    path = parsed.path or ""
    fragment = parsed.fragment or ""
    query_str = parsed.query or ""
    qs = parse_qs(query_str, keep_blank_values=True)

    out: Dict[str, Any] = {"url": url, "table": None, "sys_id": None, "scope": None}

    # nav_to.do?uri=incident.do?sys_id=XXX  (uri is itself URL-encoded)
    if "nav_to.do" in path and "uri" in qs:
        inner = unquote(qs["uri"][0])
        m = re.match(r"^([a-z][a-z0-9_]*)\.do(?:\?(.*))?", inner)
        if m:
            out["table"] = m.group(1)
            inner_qs = parse_qs(m.group(2) or "")
            if "sys_id" in inner_qs:
                out["sys_id"] = inner_qs["sys_id"][0]
            return _enrich_resolution(out, "record_form")

    # /sp?id=widget_editor&sys_id=XXX  (Service Portal)
    if path.endswith("/sp") or path.endswith("/sp.do") or path == "/sp":
        page = (qs.get("id") or [""])[0]
        _sys_id_vals = qs.get("sys_id")
        out["sys_id"] = _sys_id_vals[0] if _sys_id_vals else None
        out["page"] = page
        out["table"] = "sp_page"
        return _enrich_resolution(out, "portal_page")

    # /esc?id=... (Employee Center)
    if path.endswith("/esc"):
        out["page"] = (qs.get("id") or [""])[0]
        _sys_id_vals = qs.get("sys_id")
        out["sys_id"] = _sys_id_vals[0] if _sys_id_vals else None
        out["table"] = "sp_page"
        return _enrich_resolution(out, "esc_page")

    # /kb_view.do?sysparm_article=KB0001234
    if "kb_view.do" in path:
        out["table"] = "kb_knowledge"
        _article_vals = qs.get("sysparm_article")
        out["article_number"] = _article_vals[0] if _article_vals else None
        return _enrich_resolution(out, "kb_article")

    # /sys_app_studio.do#/foo/bar/<scope>
    if "sys_app_studio" in path:
        scope_match = re.search(r"scope=([^&/]+)", fragment) or re.search(
            r"/([a-z]_[a-z0-9_]+)/", fragment
        )
        if scope_match:
            out["scope"] = scope_match.group(1)
        out["table"] = "sys_app"
        return _enrich_resolution(out, "studio")

    # /incident_list.do — check BEFORE the generic .do form pattern below,
    # otherwise "incident_list" gets captured as the table name.
    m = re.search(r"/?([a-z][a-z0-9_]*)_list\.do$", path)
    if m:
        out["table"] = m.group(1)
        return _enrich_resolution(out, "record_list")

    # Direct form: incident.do?sys_id=XXX  or  /incident.do?sys_id=XXX
    m = re.match(r"^/?([a-z][a-z0-9_]*)\.do$", path)
    if m:
        out["table"] = m.group(1)
        if "sys_id" in qs:
            out["sys_id"] = qs["sys_id"][0]
        return _enrich_resolution(out, "record_form")

    return _enrich_resolution(out, "unknown")


def _enrich_resolution(out: Dict[str, Any], context: str) -> Dict[str, Any]:
    out["context"] = context
    table = out.get("table")
    if table:
        out["suggested_tool"] = _TABLE_TO_TOOL.get(table) or (
            "sn_query" if context.endswith("_form") or context.endswith("_list") else None
        )
        # Suggest action: sys_id present → 'get' / record-form; list view → 'list'
        if out.get("sys_id") and table in _TABLE_TO_TOOL:
            out["suggested_action"] = "get"
        elif context == "record_list":
            out["suggested_action"] = "list"
    return out


@register_tool(
    name="sn_resolve_url",
    params=SnResolveUrlParams,
    description="Parse a ServiceNow URL → table, sys_id, scope, suggested next tool. Read-only.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def sn_resolve_url(
    config: ServerConfig, auth_manager: AuthManager, params: SnResolveUrlParams
) -> Dict[str, Any]:
    return _resolve_servicenow_url(params.url)
