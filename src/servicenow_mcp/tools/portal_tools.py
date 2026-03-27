"""
Service Portal development tools for the ServiceNow MCP server.
Optimized for speed, token efficiency, and context safety.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Set
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
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


class DownloadPortalSourcesParams(BaseModel):
    output_dir: str = Field(
        ".", description="Output directory path. Defaults to current working directory"
    )
    scope: str | None = Field(
        None,
        description="Optional app scope filter (sys_scope). Example: x_company_bpm",
    )
    widget_ids: List[str] | None = Field(
        None,
        description="Optional list of widget sys_id/id/name. If empty, exports all widgets in scope.",
    )
    include_linked_script_includes: bool = Field(
        True,
        description="Include script includes referenced by exported widgets",
    )
    include_linked_angular_providers: bool = Field(
        True,
        description="Include angular providers linked via widget-provider M2M",
    )
    include_widget_client_script: bool = Field(
        True,
        description="Include widget client_script.js output",
    )
    include_widget_server_script: bool = Field(
        True,
        description="Include widget script.js output",
    )
    include_widget_link_script: bool = Field(
        True,
        description="Include widget link.js output",
    )
    include_widget_template: bool = Field(
        True,
        description="Include widget template.html output",
    )
    include_widget_css: bool = Field(
        True,
        description="Include widget css.scss output",
    )
    max_widgets: int = Field(500, description="Maximum widgets to export")
    page_size: int = Field(100, description="Pagination size for API queries (10..100)")


def _strip_metadata(record: Dict[str, Any], keep_fields: List[str]) -> Dict[str, Any]:
    """Helper to remove unnecessary system fields to save tokens."""
    return {k: v for k, v in record.items() if k in keep_fields or k == "sys_id" or k == "name"}


SCRIPT_INCLUDE_REF_RE = re.compile(
    r"\bnew\s+(?:global\.)?((?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*)\s*\("
)
IGNORED_CONSTRUCTORS = {
    "GlideRecord",
    "GlideRecordSecure",
    "GlideAggregate",
    "GlideAjax",
    "GlideDateTime",
    "Object",
    "Array",
    "Date",
    "RegExp",
}
WIDGET_METADATA_FIELDS = [
    "template",
    "css",
    "roles",
    "link",
    "description",
    "demo_data",
    "option_schema",
    "script",
    "has_preview",
    "public",
    "docs",
    "client_script",
    "data_table",
    "name",
    "sys_scope",
    "id",
    "field_list",
    "controller_as",
]

DEFAULT_REDIRECT_PATTERN = r"/[A-Za-z0-9_-]+\?id=[A-Za-z0-9_-]+"
MAX_WIDGET_REVIEW_LIMIT = 1000
MAX_WIDGET_REVIEW_MATCHES = 2000
DEFAULT_WIDGET_REVIEW_SNIPPET_LENGTH = 220
MAX_ANGULAR_PROVIDER_SCAN_LIMIT = 2000
MAX_ANGULAR_IMPLICIT_GLOBAL_MATCHES = 5000
DEFAULT_ANGULAR_IMPLICIT_SNIPPET_LENGTH = 180

KNOWN_GLOBAL_IDENTIFIERS = {
    "this",
    "self",
    "window",
    "document",
    "location",
    "navigator",
    "console",
    "angular",
    "Math",
    "JSON",
    "Object",
    "Array",
    "String",
    "Number",
    "Boolean",
    "Date",
    "RegExp",
    "Promise",
    "setTimeout",
    "setInterval",
    "clearTimeout",
    "clearInterval",
    "$scope",
    "$window",
    "$document",
    "$timeout",
    "$interval",
    "c",
    "data",
    "input",
    "options",
}

DECLARATION_NAME_RE = re.compile(r"\b(?:var|let|const)\s+([A-Za-z_$][\w$]*)")
FUNCTION_DECL_RE = re.compile(r"\bfunction\s+[A-Za-z_$][\w$]*\s*\(([^)]*)\)")
FUNCTION_EXPR_RE = re.compile(r"\bfunction\s*\(([^)]*)\)")
ARROW_FN_RE = re.compile(r"\(([^)]*)\)\s*=>")
CATCH_PARAM_RE = re.compile(r"\bcatch\s*\(\s*([A-Za-z_$][\w$]*)\s*\)")
IMPLICIT_ASSIGNMENT_RE = re.compile(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*([+\-*/%]?=)(?!=)")


class SearchPortalRegexMatchesParams(BaseModel):
    regex: str = Field(
        DEFAULT_REDIRECT_PATTERN,
        description="Regex pattern to find in source code",
    )
    updated_by: str | None = Field(
        None,
        description="Optional updater filter (sys_updated_by). Example: admin@example.com",
    )
    scope: str | None = Field(
        None,
        description="Optional app scope filter (sys_scope). Example: x_company_bpm",
    )
    widget_ids: List[str] | None = Field(
        None,
        description="Optional widget id/sys_id/name filters. If provided, scan only these widgets.",
    )
    source_types: List[str] = Field(
        ["widget", "script_include", "angular_provider"],
        description="Source types to include. Allowed: widget, script_include, angular_provider",
    )
    updated_after: str | None = Field(
        None,
        description="Optional lower bound for sys_updated_on (YYYY-MM-DD or datetime)",
    )
    updated_before: str | None = Field(
        None,
        description="Optional upper bound for sys_updated_on (YYYY-MM-DD or datetime)",
    )
    include_linked_script_includes: bool = Field(
        True,
        description="Expand scan to script includes referenced by matched widgets",
    )
    include_linked_angular_providers: bool = Field(
        True,
        description="Expand scan to angular providers linked to matched widgets",
    )
    linked_components_updated_by_only: bool = Field(
        False,
        description="When true, linked Script Includes/Providers are filtered by same updated_by",
    )
    include_widget_fields: List[str] = Field(
        ["template", "script", "client_script", "link", "css"],
        description="Widget fields to scan for pattern",
    )
    max_widgets: int = Field(
        200,
        description=f"Maximum widgets to scan after filter. Clamped to {MAX_WIDGET_REVIEW_LIMIT}.",
    )
    page_size: int = Field(100, description="Pagination size for API queries (10..100)")
    max_matches: int = Field(
        300,
        description=f"Maximum total matches to return. Clamped to {MAX_WIDGET_REVIEW_MATCHES}.",
    )
    snippet_length: int = Field(
        DEFAULT_WIDGET_REVIEW_SNIPPET_LENGTH,
        description="Maximum one-line snippet length per match",
    )
    compact_output: bool = Field(
        True,
        description="Return compact output (location, line, snippet) to minimize tokens",
    )
    output_mode: str | None = Field(
        None,
        description="Optional output shape override: minimal | compact | full",
    )


class DetectAngularImplicitGlobalsParams(BaseModel):
    updated_by: str | None = Field(
        None,
        description="Optional updater filter (sys_updated_by). Example: admin@example.com",
    )
    scope: str | None = Field(
        None,
        description="Optional app scope filter (sys_scope). Example: x_company_bpm",
    )
    provider_ids: List[str] | None = Field(
        None,
        description="Optional provider id/sys_id/name filters. If provided, scan only these providers.",
    )
    updated_after: str | None = Field(
        None,
        description="Optional lower bound for sys_updated_on (YYYY-MM-DD or datetime)",
    )
    updated_before: str | None = Field(
        None,
        description="Optional upper bound for sys_updated_on (YYYY-MM-DD or datetime)",
    )
    max_providers: int = Field(
        300,
        description=f"Maximum providers to scan after filter. Clamped to {MAX_ANGULAR_PROVIDER_SCAN_LIMIT}.",
    )
    page_size: int = Field(100, description="Pagination size for API queries (10..100)")
    max_matches: int = Field(
        500,
        description=f"Maximum total findings to return. Clamped to {MAX_ANGULAR_IMPLICIT_GLOBAL_MATCHES}.",
    )
    snippet_length: int = Field(
        DEFAULT_ANGULAR_IMPLICIT_SNIPPET_LENGTH,
        description="Maximum one-line snippet length per finding",
    )
    output_mode: str = Field(
        "minimal",
        description="Output shape: minimal | compact | full",
    )


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe.strip("._") or "unnamed"


def _escape_query(value: str) -> str:
    return str(value).replace("^", "^^").replace("=", r"\=").replace("@", r"\@")


def _extract_ref_candidates(script: str) -> List[str]:
    if not script:
        return []
    found: List[str] = []
    for token in SCRIPT_INCLUDE_REF_RE.findall(script):
        short_name = token.split(".")[-1]
        if short_name and short_name not in IGNORED_CONSTRUCTORS and short_name not in found:
            found.append(short_name)
    return found


def _chunked(values: List[str], size: int) -> List[List[str]]:
    if size <= 0:
        return [values]
    return [values[i : i + size] for i in range(0, len(values), size)]


def _as_ref_sys_id(value: Any) -> str | None:
    if isinstance(value, dict):
        inner = value.get("value")
        if isinstance(inner, str) and inner:
            return inner
    if isinstance(value, str) and value:
        return value
    return None


def _clamp_widget_review_limit(value: int) -> int:
    return max(1, min(value, MAX_WIDGET_REVIEW_LIMIT))


def _clamp_widget_review_matches(value: int) -> int:
    return max(1, min(value, MAX_WIDGET_REVIEW_MATCHES))


def _clamp_snippet_length(value: int) -> int:
    return max(80, min(value, 500))


def _compile_search_pattern(pattern: str) -> re.Pattern[str]:
    raw = pattern or DEFAULT_REDIRECT_PATTERN
    return re.compile(raw)


def _to_one_line(value: str) -> str:
    return " ".join(value.split())


def _slice_one_line_snippet(source: str, start: int, end: int, max_length: int) -> str:
    left = max(0, start - 90)
    right = min(len(source), end + 90)
    return _to_one_line(source[left:right])[:max_length]


def _line_col_from_index(source: str, index: int) -> tuple[int, int]:
    line = source.count("\n", 0, index) + 1
    line_start = source.rfind("\n", 0, index)
    col = index + 1 if line_start == -1 else index - line_start
    return line, col


def _extract_pattern_hits(
    *,
    source_type: str,
    source_sys_id: str,
    source_name: str,
    field_name: str,
    content: str,
    regex: re.Pattern[str],
    snippet_length: int,
    max_matches: int,
) -> List[Dict[str, Any]]:
    if not content or max_matches <= 0:
        return []

    hits: List[Dict[str, Any]] = []
    for match in regex.finditer(content):
        if len(hits) >= max_matches:
            break
        start, end = match.span()
        line, column = _line_col_from_index(content, start)
        matched_text = match.group(0)
        hits.append(
            {
                "source_type": source_type,
                "source_sys_id": source_sys_id,
                "source_name": source_name,
                "field": field_name,
                "line": line,
                "column": column,
                "match": matched_text,
                "snippet": _slice_one_line_snippet(content, start, end, snippet_length),
            }
        )
    return hits


def _match_location(source_type: str, source_name: str, field_name: str) -> str:
    safe_name = _safe_name(source_name)
    if source_type == "widget":
        return f"sp_widget/{safe_name}/{field_name}"
    if source_type == "script_include":
        return f"sys_script_include/{safe_name}/script"
    if source_type == "angular_provider":
        return f"sp_angular_provider/{safe_name}/script"
    return f"{source_type}/{safe_name}/{field_name}"


def _compact_matches(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for item in items:
        compact.append(
            {
                "location": _match_location(
                    str(item.get("source_type") or ""),
                    str(item.get("source_name") or ""),
                    str(item.get("field") or ""),
                ),
                "line": item.get("line"),
                "column": item.get("column"),
                "snippet": item.get("snippet"),
                "match": item.get("match"),
            }
        )
    return compact


def _minimal_matches(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    minimal: List[Dict[str, Any]] = []
    for item in items:
        minimal.append(
            {
                "location": _match_location(
                    str(item.get("source_type") or ""),
                    str(item.get("source_name") or ""),
                    str(item.get("field") or ""),
                ),
                "line": item.get("line"),
            }
        )
    return minimal


def _resolve_output_mode(output_mode: str | None, compact_output: bool) -> str:
    if output_mode is None:
        return "compact" if compact_output else "full"
    normalized = output_mode.strip().lower()
    if normalized in {"minimal", "compact", "full"}:
        return normalized
    raise ValueError("output_mode must be one of: minimal, compact, full")


def _resolve_fixed_output_mode(output_mode: str) -> str:
    normalized = output_mode.strip().lower()
    if normalized in {"minimal", "compact", "full"}:
        return normalized
    raise ValueError("output_mode must be one of: minimal, compact, full")


def _clamp_provider_scan_limit(value: int) -> int:
    return max(1, min(value, MAX_ANGULAR_PROVIDER_SCAN_LIMIT))


def _clamp_implicit_global_matches(value: int) -> int:
    return max(1, min(value, MAX_ANGULAR_IMPLICIT_GLOBAL_MATCHES))


def _split_param_names(param_block: str) -> Set[str]:
    names: Set[str] = set()
    for token in param_block.split(","):
        base = token.split("=", 1)[0].strip()
        if re.fullmatch(r"[A-Za-z_$][\w$]*", base):
            names.add(base)
    return names


def _collect_declared_identifiers(script: str) -> Set[str]:
    declared: Set[str] = set()
    for name in DECLARATION_NAME_RE.findall(script):
        declared.add(name)
    for block in FUNCTION_DECL_RE.findall(script):
        declared.update(_split_param_names(block))
    for block in FUNCTION_EXPR_RE.findall(script):
        declared.update(_split_param_names(block))
    for block in ARROW_FN_RE.findall(script):
        declared.update(_split_param_names(block))
    for name in CATCH_PARAM_RE.findall(script):
        declared.add(name)
    return declared


def _extract_implicit_global_hits(
    *,
    source_sys_id: str,
    source_name: str,
    script: str,
    snippet_length: int,
    max_matches: int,
) -> List[Dict[str, Any]]:
    if not script or max_matches <= 0:
        return []

    declared = _collect_declared_identifiers(script)
    hits: List[Dict[str, Any]] = []

    for match in IMPLICIT_ASSIGNMENT_RE.finditer(script):
        if len(hits) >= max_matches:
            break
        name = match.group(1)
        op = match.group(2)
        if name in declared or name in KNOWN_GLOBAL_IDENTIFIERS:
            continue
        start, end = match.span()
        line, column = _line_col_from_index(script, start)
        hits.append(
            {
                "source_type": "angular_provider",
                "source_sys_id": source_sys_id,
                "source_name": source_name,
                "field": "script",
                "line": line,
                "column": column,
                "match": match.group(0),
                "snippet": _slice_one_line_snippet(script, start, end, snippet_length),
                "variable": name,
                "operator": op,
                "issue": "implicit_global_assignment",
            }
        )

    return hits


def _sn_query_all(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    query: str,
    fields: str,
    page_size: int,
    max_records: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    size = max(10, min(page_size, 100))
    limit_cap = max(1, max_records)

    while len(rows) < limit_cap:
        fetch = min(size, limit_cap - len(rows))
        response = sn_query(
            config,
            auth_manager,
            GenericQueryParams(
                table=table,
                query=query,
                fields=fields,
                limit=fetch,
                offset=offset,
                display_value=True,
            ),
        )
        if not response.get("success"):
            break
        chunk = response.get("results", [])
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < fetch:
            break
        offset += fetch

    return rows


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _as_display_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("display_value", "displayValue", "value"):
            inner = value.get(key)
            if isinstance(inner, str) and inner:
                return inner
        return ""
    if isinstance(value, str):
        return value
    return ""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"true", "1", "yes"}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _parse_attributes(value: Any) -> Dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {}
    attrs: Dict[str, str] = {}
    for item in text.split(","):
        token = item.strip()
        if not token:
            continue
        if "=" in token:
            key, val = token.split("=", 1)
            attrs[key.strip()] = val.strip()
        else:
            attrs[token] = "true"
    return attrs


def _build_widget_field_payload(
    field_name: str,
    value: Any,
    dictionary_row: Dict[str, Any] | None,
) -> Dict[str, Any]:
    label = str((dictionary_row or {}).get("column_label") or field_name)
    internal_type = str((dictionary_row or {}).get("internal_type") or "string")
    read_only = _as_bool((dictionary_row or {}).get("read_only"))
    mandatory = _as_bool((dictionary_row or {}).get("mandatory"))
    max_length = _as_int((dictionary_row or {}).get("max_length"), 0)
    choice = _as_int((dictionary_row or {}).get("choice"), 0)
    reference = str((dictionary_row or {}).get("reference") or "")
    attributes = _parse_attributes((dictionary_row or {}).get("attributes"))

    display_value = _as_display_text(value)
    raw_value: Any = value
    if isinstance(value, dict):
        raw_value = value.get("value", display_value)

    payload: Dict[str, Any] = {
        "sys_mandatory": mandatory,
        "visible": True,
        "dbType": 12,
        "label": label,
        "sys_readonly": read_only,
        "type": internal_type,
        "mandatory": mandatory,
        "displayValue": display_value,
        "readonly": read_only,
        "hint": "",
        "name": field_name,
        "attributes": attributes,
        "choice": choice,
        "value": raw_value if raw_value is not None else "",
        "max_length": max_length,
        "ed": {"name": field_name},
    }
    if reference:
        payload["refTable"] = reference
        payload["reference_type"] = "table"
        payload["reference_key"] = "sys_id"
        payload["ed"]["reference"] = reference
    return payload


def _build_widget_payload(
    widget: Dict[str, Any], dictionary_by_field: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for field_name in WIDGET_METADATA_FIELDS:
        payload[field_name] = _build_widget_field_payload(
            field_name,
            widget.get(field_name),
            dictionary_by_field.get(field_name),
        )
    return payload


def _json_or_raw_string(value: Any) -> Any:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                return json.loads(trimmed)
            except json.JSONDecodeError:
                return value
    return value


@register_tool(
    "get_widget_bundle",
    params=GetWidgetBundleParams,
    description="Fetch a high-speed bundle of a Service Portal widget (HTML, Scripts, and Provider list)",
    serialization="raw_dict",
    return_type=dict,
)
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
        table=WIDGET_TABLE,
        query=query,
        fields=",".join(widget_fields),
        limit=1,
        offset=0,
        display_value=True,
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
            limit=100,
            offset=0,
            display_value=True,
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
                limit=100,
                offset=0,
                display_value=True,
            )
            prov_response = sn_query(config, auth_manager, prov_query_params)
            bundle["angular_providers"] = [
                {"name": p["name"], "sys_id": p["sys_id"], "type": p.get("type", "")}
                for p in prov_response.get("results", [])
            ]
        else:
            bundle["angular_providers"] = []

    return bundle


@register_tool(
    "get_portal_component_code",
    params=GetPortalComponentParams,
    description="Fetch specific code from a portal widget, provider, or script include (token efficient)",
    serialization="raw_dict",
    return_type=dict,
)
def get_portal_component_code(
    config: ServerConfig, auth_manager: AuthManager, params: GetPortalComponentParams
) -> Dict[str, Any]:
    """Fetch specific code fields from a portal-related record."""
    query_params = GenericQueryParams(
        table=params.table,
        query=f"sys_id={params.sys_id}",
        fields=",".join(params.fields + ["name", "sys_id"]),
        limit=1,
        offset=0,
        display_value=True,
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


@register_tool(
    "search_portal_regex_matches",
    params=SearchPortalRegexMatchesParams,
    description="Regex-based match extraction across widget and linked portal sources with minimal/compact/full output modes",
    serialization="raw_dict",
    return_type=dict,
)
def search_portal_regex_matches(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: SearchPortalRegexMatchesParams,
) -> Dict[str, Any]:
    try:
        regex = _compile_search_pattern(params.regex)
    except re.error as exc:
        return {"success": False, "message": f"Invalid regex: {exc}", "matches": []}

    try:
        output_mode = _resolve_output_mode(params.output_mode, params.compact_output)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "matches": []}

    page_size = max(10, min(params.page_size, 100))
    max_widgets = _clamp_widget_review_limit(params.max_widgets)
    max_matches = _clamp_widget_review_matches(params.max_matches)
    snippet_length = _clamp_snippet_length(params.snippet_length)

    source_type_set = {value.strip().lower() for value in params.source_types if value.strip()}
    allowed_source_types = {"widget", "script_include", "angular_provider"}
    invalid_source_types = sorted(source_type_set - allowed_source_types)
    if invalid_source_types:
        return {
            "success": False,
            "message": f"Unsupported source_types: {', '.join(invalid_source_types)}",
            "matches": [],
        }

    safe_updated_by = _escape_query(params.updated_by) if params.updated_by else ""
    widget_query_parts: List[str] = []
    if params.updated_by:
        widget_query_parts.append(f"sys_updated_by={safe_updated_by}")
    if params.scope:
        widget_query_parts.append(f"sys_scope={_escape_query(params.scope)}")
    if params.updated_after:
        widget_query_parts.append(f"sys_updated_on>={_escape_query(params.updated_after)}")
    if params.updated_before:
        widget_query_parts.append(f"sys_updated_on<={_escape_query(params.updated_before)}")
    if params.widget_ids:
        id_tokens = [
            _escape_query(value)
            for value in params.widget_ids
            if isinstance(value, str) and value.strip()
        ]
        if id_tokens:
            widget_query_parts.append(
                "("
                + "^OR".join(
                    [f"sys_id={t}" for t in id_tokens]
                    + [f"id={t}" for t in id_tokens]
                    + [f"name={t}" for t in id_tokens]
                )
                + ")"
            )
    widget_query = "^".join(widget_query_parts)

    widget_fields = [
        "sys_id",
        "name",
        "id",
        "sys_updated_by",
        "sys_updated_on",
        "sys_scope",
        "template",
        "script",
        "client_script",
        "link",
        "css",
    ]
    widget_rows = _sn_query_all(
        config,
        auth_manager,
        table=WIDGET_TABLE,
        query=widget_query,
        fields=",".join(widget_fields),
        page_size=page_size,
        max_records=max_widgets,
    )

    matches: List[Dict[str, Any]] = []
    requested_widget_fields = set(params.include_widget_fields)
    script_include_candidates: Set[str] = set()
    widget_ids: List[str] = []

    for widget in widget_rows:
        if len(matches) >= max_matches:
            break
        widget_sys_id = str(widget.get("sys_id") or "")
        widget_name = str(widget.get("name") or widget.get("id") or widget_sys_id)
        if widget_sys_id:
            widget_ids.append(widget_sys_id)

        if params.include_linked_script_includes and "script_include" in source_type_set:
            script_include_candidates.update(
                _extract_ref_candidates(str(widget.get("script") or ""))
            )
            script_include_candidates.update(
                _extract_ref_candidates(str(widget.get("client_script") or ""))
            )

        if "widget" in source_type_set:
            for field_name in ["template", "script", "client_script", "link", "css"]:
                if field_name not in requested_widget_fields:
                    continue
                content = str(widget.get(field_name) or "")
                if not content:
                    continue
                remaining = max_matches - len(matches)
                if remaining <= 0:
                    break
                matches.extend(
                    _extract_pattern_hits(
                        source_type="widget",
                        source_sys_id=widget_sys_id,
                        source_name=widget_name,
                        field_name=field_name,
                        content=content,
                        regex=regex,
                        snippet_length=snippet_length,
                        max_matches=remaining,
                    )
                )

    provider_scanned = 0
    if (
        params.include_linked_angular_providers
        and "angular_provider" in source_type_set
        and widget_ids
        and len(matches) < max_matches
    ):
        provider_ids: Set[str] = set()
        for chunk in _chunked(widget_ids, 100):
            relation_rows = _sn_query_all(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_M2M_TABLE,
                query=f"sp_widgetIN{','.join(_escape_query(value) for value in chunk)}",
                fields="sp_angular_provider",
                page_size=page_size,
                max_records=1000,
            )
            for row in relation_rows:
                provider_id = _as_ref_sys_id(row.get("sp_angular_provider"))
                if provider_id:
                    provider_ids.add(provider_id)

        if provider_ids:
            provider_query = f"sys_idIN{','.join(sorted(provider_ids))}"
            if params.linked_components_updated_by_only and params.updated_by:
                provider_query += f"^sys_updated_by={safe_updated_by}"
            if params.updated_after:
                provider_query += f"^sys_updated_on>={_escape_query(params.updated_after)}"
            if params.updated_before:
                provider_query += f"^sys_updated_on<={_escape_query(params.updated_before)}"
            provider_rows = _sn_query_all(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_TABLE,
                query=provider_query,
                fields="sys_id,name,script,sys_updated_by,sys_updated_on",
                page_size=page_size,
                max_records=1000,
            )
            provider_scanned = len(provider_rows)
            for provider in provider_rows:
                remaining = max_matches - len(matches)
                if remaining <= 0:
                    break
                provider_script = str(provider.get("script") or "")
                if not provider_script:
                    continue
                matches.extend(
                    _extract_pattern_hits(
                        source_type="angular_provider",
                        source_sys_id=str(provider.get("sys_id") or ""),
                        source_name=str(provider.get("name") or provider.get("sys_id") or ""),
                        field_name="script",
                        content=provider_script,
                        regex=regex,
                        snippet_length=snippet_length,
                        max_matches=remaining,
                    )
                )

    script_include_scanned = 0
    if (
        params.include_linked_script_includes
        and "script_include" in source_type_set
        and script_include_candidates
        and len(matches) < max_matches
    ):
        for candidate in sorted(script_include_candidates):
            remaining = max_matches - len(matches)
            if remaining <= 0:
                break

            safe_candidate = _escape_query(candidate)
            query = f"name={safe_candidate}^ORapi_name={safe_candidate}^ORapi_nameENDSWITH.{safe_candidate}"
            if params.scope:
                query += f"^sys_scope={_escape_query(params.scope)}"
            if params.linked_components_updated_by_only and params.updated_by:
                query += f"^sys_updated_by={safe_updated_by}"
            if params.updated_after:
                query += f"^sys_updated_on>={_escape_query(params.updated_after)}"
            if params.updated_before:
                query += f"^sys_updated_on<={_escape_query(params.updated_before)}"

            rows = _sn_query_all(
                config,
                auth_manager,
                table="sys_script_include",
                query=query,
                fields="sys_id,name,api_name,script,sys_updated_by,sys_updated_on",
                page_size=page_size,
                max_records=1,
            )
            if not rows:
                continue
            script_include_scanned += 1
            row = rows[0]
            content = str(row.get("script") or "")
            if not content:
                continue
            matches.extend(
                _extract_pattern_hits(
                    source_type="script_include",
                    source_sys_id=str(row.get("sys_id") or ""),
                    source_name=str(row.get("name") or candidate),
                    field_name="script",
                    content=content,
                    regex=regex,
                    snippet_length=snippet_length,
                    max_matches=remaining,
                )
            )

    trimmed_matches = matches[:max_matches]
    if output_mode == "minimal":
        output_matches = _minimal_matches(trimmed_matches)
    elif output_mode == "compact":
        output_matches = _compact_matches(trimmed_matches)
    else:
        output_matches = trimmed_matches
    return {
        "success": True,
        "filters": {
            "updated_by": params.updated_by,
            "scope": params.scope,
            "regex": params.regex,
            "source_types": sorted(source_type_set),
            "widget_ids": params.widget_ids,
            "updated_after": params.updated_after,
            "updated_before": params.updated_before,
            "linked_components_updated_by_only": params.linked_components_updated_by_only,
            "output_mode": output_mode,
        },
        "scan_summary": {
            "widgets_scanned": len(widget_rows),
            "linked_script_include_candidates": len(script_include_candidates),
            "linked_script_includes_scanned": script_include_scanned,
            "linked_angular_providers_scanned": provider_scanned,
            "match_count": len(trimmed_matches),
            "max_matches": max_matches,
            "max_widgets": max_widgets,
            "output_mode": output_mode,
        },
        "matches": output_matches,
        "safety_notice": "Returns concise line-level snippets only; full source bodies are intentionally excluded.",
    }


def search_widget_author_patterns(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: SearchPortalRegexMatchesParams,
) -> Dict[str, Any]:
    return search_portal_regex_matches(config, auth_manager, params)


@register_tool(
    "detect_angular_implicit_globals",
    params=DetectAngularImplicitGlobalsParams,
    description="Detect implicit global assignments in Angular provider scripts (undeclared variables causing not defined issues)",
    serialization="raw_dict",
    return_type=dict,
)
def detect_angular_implicit_globals(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DetectAngularImplicitGlobalsParams,
) -> Dict[str, Any]:
    try:
        output_mode = _resolve_fixed_output_mode(params.output_mode)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "findings": []}

    page_size = max(10, min(params.page_size, 100))
    max_providers = _clamp_provider_scan_limit(params.max_providers)
    max_matches = _clamp_implicit_global_matches(params.max_matches)
    snippet_length = _clamp_snippet_length(params.snippet_length)

    query_parts: List[str] = []
    if params.updated_by:
        query_parts.append(f"sys_updated_by={_escape_query(params.updated_by)}")
    if params.scope:
        query_parts.append(f"sys_scope={_escape_query(params.scope)}")
    if params.updated_after:
        query_parts.append(f"sys_updated_on>={_escape_query(params.updated_after)}")
    if params.updated_before:
        query_parts.append(f"sys_updated_on<={_escape_query(params.updated_before)}")
    if params.provider_ids:
        id_tokens = [
            _escape_query(value)
            for value in params.provider_ids
            if isinstance(value, str) and value.strip()
        ]
        if id_tokens:
            query_parts.append(
                "("
                + "^OR".join(
                    [f"sys_id={token}" for token in id_tokens]
                    + [f"id={token}" for token in id_tokens]
                    + [f"name={token}" for token in id_tokens]
                )
                + ")"
            )
    query = "^".join(query_parts)

    provider_rows = _sn_query_all(
        config,
        auth_manager,
        table=ANGULAR_PROVIDER_TABLE,
        query=query,
        fields="sys_id,name,id,script,sys_updated_by,sys_updated_on,sys_scope",
        page_size=page_size,
        max_records=max_providers,
    )

    findings: List[Dict[str, Any]] = []
    for row in provider_rows:
        if len(findings) >= max_matches:
            break
        script = str(row.get("script") or "")
        if not script:
            continue
        remaining = max_matches - len(findings)
        findings.extend(
            _extract_implicit_global_hits(
                source_sys_id=str(row.get("sys_id") or ""),
                source_name=str(row.get("name") or row.get("id") or row.get("sys_id") or ""),
                script=script,
                snippet_length=snippet_length,
                max_matches=remaining,
            )
        )

    trimmed = findings[:max_matches]
    if output_mode == "minimal":
        output_findings = _minimal_matches(trimmed)
    elif output_mode == "compact":
        output_findings = _compact_matches(trimmed)
    else:
        output_findings = trimmed

    return {
        "success": True,
        "filters": {
            "updated_by": params.updated_by,
            "scope": params.scope,
            "provider_ids": params.provider_ids,
            "updated_after": params.updated_after,
            "updated_before": params.updated_before,
            "output_mode": output_mode,
        },
        "scan_summary": {
            "providers_scanned": len(provider_rows),
            "finding_count": len(trimmed),
            "max_matches": max_matches,
            "max_providers": max_providers,
            "output_mode": output_mode,
        },
        "findings": output_findings,
        "safety_notice": "Findings are static-analysis heuristics; verify before patching provider scripts.",
    }


@register_tool(
    "update_portal_component",
    params=UpdatePortalComponentParams,
    description="Pinpoint update of specific portal component fields (HTML, CSS, or scripts)",
    serialization="raw_dict",
    return_type=dict,
)
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


@register_tool(
    "download_portal_sources",
    params=DownloadPortalSourcesParams,
    description="Download widgets and linked portal/server source files in sn-utils-like local structure",
    serialization="raw_dict",
    return_type=dict,
)
def download_portal_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadPortalSourcesParams,
) -> Dict[str, Any]:
    root = Path(params.output_dir or ".").expanduser().resolve()
    scope_name = _safe_name(params.scope or "global")
    scope_root = root / scope_name
    instance_name = (urlparse(config.instance_url).hostname or "instance").split(".")[0]
    g_ck = str(auth_manager.get_headers().get("X-UserToken", ""))

    _write_json_file(
        root / "_settings.json",
        {
            "name": instance_name,
            "url": config.instance_url,
            "g_ck": g_ck,
        },
    )
    _write_json_file(root / "_last_error.json", {})

    widget_base_query = ""
    if params.scope:
        widget_base_query = f"sys_scope={_escape_query(params.scope)}"
    widget_fields = "sys_id,name,id,sys_scope,template,script,client_script,link,css,option_schema,demo_data,roles,description,has_preview,public,docs,data_table,field_list,controller_as"

    widgets: List[Dict[str, Any]] = []
    if params.widget_ids:
        for widget_id in params.widget_ids:
            safe_widget_id = _escape_query(widget_id)
            query = f"sys_id={safe_widget_id}^ORid={safe_widget_id}^ORname={safe_widget_id}"
            if widget_base_query:
                query += f"^{widget_base_query}"
            rows = _sn_query_all(
                config,
                auth_manager,
                table=WIDGET_TABLE,
                query=query,
                fields=widget_fields,
                page_size=params.page_size,
                max_records=1,
            )
            if rows:
                widgets.append(rows[0])
    else:
        widgets = _sn_query_all(
            config,
            auth_manager,
            table=WIDGET_TABLE,
            query=widget_base_query,
            fields=widget_fields,
            page_size=params.page_size,
            max_records=max(1, params.max_widgets),
        )

    widget_map: Dict[str, str] = {}
    exported_widgets: List[Dict[str, str]] = []
    script_include_candidates: List[str] = []
    scope_sys_ids: Dict[str, str] = {}

    dictionary_rows = _sn_query_all(
        config,
        auth_manager,
        table="sys_dictionary",
        query=(
            "name=sp_widget^elementIN"
            + ",".join(_escape_query(field) for field in WIDGET_METADATA_FIELDS)
        ),
        fields="element,column_label,internal_type,read_only,mandatory,max_length,choice,reference,attributes",
        page_size=params.page_size,
        max_records=300,
    )
    dictionary_by_field = {
        str(row.get("element")): row
        for row in dictionary_rows
        if isinstance(row.get("element"), str)
    }

    for widget in widgets:
        sys_id = str(widget.get("sys_id") or "")
        widget_id = str(widget.get("id") or widget.get("name") or sys_id)
        widget_name = str(widget.get("name") or widget_id)
        folder_name = _safe_name(widget_id)
        widget_dir = scope_root / "sp_widget" / folder_name

        for candidate in _extract_ref_candidates(str(widget.get("script") or "")):
            if candidate not in script_include_candidates:
                script_include_candidates.append(candidate)
        for candidate in _extract_ref_candidates(str(widget.get("client_script") or "")):
            if candidate not in script_include_candidates:
                script_include_candidates.append(candidate)

        metadata = {
            "instance": {
                "name": instance_name,
                "url": config.instance_url,
                "g_ck": g_ck,
            },
            "action": "saveWidget",
            "tableName": WIDGET_TABLE,
            "name": widget_name,
            "sys_id": sys_id,
            "widget": _build_widget_payload(widget, dictionary_by_field),
        }
        _write_json_file(widget_dir / "_widget.json", metadata)

        if params.include_widget_template:
            _write_text_file(widget_dir / "template.html", str(widget.get("template") or ""))
        if params.include_widget_server_script:
            _write_text_file(widget_dir / "script.js", str(widget.get("script") or ""))
        if params.include_widget_client_script:
            _write_text_file(
                widget_dir / "client_script.js", str(widget.get("client_script") or "")
            )
        if params.include_widget_link_script:
            _write_text_file(widget_dir / "link.js", str(widget.get("link") or ""))
        if params.include_widget_css:
            _write_text_file(widget_dir / "css.scss", str(widget.get("css") or ""))

        option_schema_raw = widget.get("option_schema") or ""
        if str(option_schema_raw).strip() == "":
            _write_text_file(widget_dir / "option_schema.json", "")
        else:
            _write_json_file(
                widget_dir / "option_schema.json",
                _json_or_raw_string(option_schema_raw),
            )

        demo_data_raw = widget.get("demo_data") or ""
        if str(demo_data_raw).strip() == "":
            _write_text_file(widget_dir / "demo_data.json", "")
        else:
            _write_json_file(
                widget_dir / "demo_data.json",
                _json_or_raw_string(demo_data_raw),
            )
        _write_text_file(
            widget_dir / "_test_urls.txt",
            "\n".join(
                [
                    f"{config.instance_url}/$sp.do?id=sp-preview&sys_id={sys_id}",
                    f"{config.instance_url}/sp_config?id={widget_id}",
                    f"{config.instance_url}/sp?id={widget_id}",
                    f"{config.instance_url}/esc?id={widget_id}",
                ]
            ),
        )

        if widget_id:
            widget_map[widget_id] = sys_id
        scope_value = _as_ref_sys_id(widget.get("sys_scope"))
        scope_label = params.scope or _as_display_text(widget.get("sys_scope"))
        if scope_label and scope_value and scope_label not in scope_sys_ids:
            scope_sys_ids[scope_label] = scope_value
        exported_widgets.append({"sys_id": sys_id, "id": widget_id, "name": widget_name})

    _write_json_file(scope_root / "sp_widget" / "_map.json", widget_map)

    provider_map: Dict[str, str] = {}
    exported_providers: List[Dict[str, str]] = []
    if params.include_linked_angular_providers and widgets:
        widget_sys_ids = [str(w.get("sys_id")) for w in widgets if w.get("sys_id")]
        m2m_ids: List[str] = []
        for sys_id_chunk in _chunked(widget_sys_ids, 100):
            m2m_rows = _sn_query_all(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_M2M_TABLE,
                query=f"sp_widgetIN{','.join(_escape_query(value) for value in sys_id_chunk)}",
                fields="sp_widget,sp_angular_provider",
                page_size=params.page_size,
                max_records=500,
            )
            for row in m2m_rows:
                provider_id = _as_ref_sys_id(row.get("sp_angular_provider"))
                if provider_id and provider_id not in m2m_ids:
                    m2m_ids.append(provider_id)

        if m2m_ids:
            provider_rows = _sn_query_all(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_TABLE,
                query=f"sys_idIN{','.join(m2m_ids)}",
                fields="sys_id,name,script,type,sys_scope",
                page_size=params.page_size,
                max_records=1000,
            )
            for provider in provider_rows:
                name = str(provider.get("name") or provider.get("sys_id") or "")
                sys_id = str(provider.get("sys_id") or "")
                file_name = _safe_name(name)
                _write_text_file(
                    scope_root / "sp_angular_provider" / f"{file_name}.script.js",
                    str(provider.get("script") or ""),
                )
                if name:
                    provider_map[name] = sys_id
                exported_providers.append({"name": name, "sys_id": sys_id})

    _write_json_file(scope_root / "sp_angular_provider" / "_map.json", provider_map)

    si_map: Dict[str, str] = {}
    exported_script_includes: List[Dict[str, str]] = []
    if params.include_linked_script_includes and script_include_candidates:
        for candidate in script_include_candidates:
            safe_candidate = _escape_query(candidate)
            query = (
                f"name={safe_candidate}^ORapi_name={safe_candidate}"
                f"^ORapi_nameENDSWITH.{safe_candidate}"
            )
            if params.scope:
                query += f"^sys_scope={_escape_query(params.scope)}"
            rows = _sn_query_all(
                config,
                auth_manager,
                table="sys_script_include",
                query=query,
                fields="sys_id,name,api_name,script,sys_scope",
                page_size=params.page_size,
                max_records=1,
            )
            if not rows:
                continue
            row = rows[0]
            name = str(row.get("name") or candidate)
            sys_id = str(row.get("sys_id") or "")
            file_name = _safe_name(name)
            _write_text_file(
                scope_root / "sys_script_include" / f"{file_name}.script.js",
                str(row.get("script") or ""),
            )
            si_map[name] = sys_id
            exported_script_includes.append(
                {
                    "name": name,
                    "sys_id": sys_id,
                    "api_name": str(row.get("api_name") or ""),
                }
            )

    _write_json_file(scope_root / "sys_script_include" / "_map.json", si_map)
    _write_json_file(root / "scopes.json", scope_sys_ids)

    return {
        "success": True,
        "output_root": str(scope_root),
        "summary": {
            "widgets": len(exported_widgets),
            "angular_providers": len(exported_providers),
            "script_includes": len(exported_script_includes),
        },
        "widget_map_path": str(scope_root / "sp_widget" / "_map.json"),
        "angular_provider_map_path": str(scope_root / "sp_angular_provider" / "_map.json"),
        "script_include_map_path": str(scope_root / "sys_script_include" / "_map.json"),
        "safety_notice": "Exports structured source files only; no destructive remote operations are performed.",
    }
