"""
Service Portal development tools for the ServiceNow MCP server.
Optimized for speed, token efficiency, and context safety.
"""

import difflib
import hashlib
import logging
import re
from concurrent.futures import as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils import json_fast
from ..utils.config import ServerConfig
from ..utils.download_map import map_sys_ids, max_sync_updated_on, merge_map_file, read_download_map
from ..utils.progress import emit_progress
from ..utils.registry import register_tool
from ..utils.source_layout import FIELD_FILENAME, field_filename, normalize_source_eol
from ..utils.sync_anchor import CONFLICT_MIRRORED, KEPT_LOCAL, REFRESHED
from ..utils.sync_anchor import field_sha as _field_sha
from ..utils.sync_anchor import reconcile_field, sweep_legacy_baseline
from ..utils.workspace_roots import known_download_roots, record_download_root
from .sn_api import (
    GenericQueryParams,
    _get_page_executor,
    apply_scope_namespace,
    invalidate_query_cache,
    sn_query,
    sn_query_all,
    sn_query_all_with_retry,
    sn_query_page,
)

logger = logging.getLogger(__name__)

# filename -> field name, so a synced file resolves to the anchor key sync_tools uses.
_FILENAME_FIELD = {v: k for k, v in FIELD_FILENAME.items()}


def _portal_field_shas(record: Dict[str, Any], fields: tuple) -> Dict[str, str]:
    """Per-field normalized content sha at download — the offline edit anchor read
    by sync_tools so a freshly downloaded component attributes yours/theirs with
    no network and no frozen snapshot (see utils/sync_anchor.py)."""
    shas: Dict[str, str] = {}
    for f in fields:
        body = record.get(f)
        if isinstance(body, str) and body.strip():
            shas[f] = _field_sha(body)
    return shas


# Constants for Portal tables
WIDGET_TABLE = "sp_widget"
ANGULAR_PROVIDER_TABLE = "sp_angular_provider"
WIDGET_DEPENDENCY_TABLE = "m2m_sp_widget_dependency"
DEPENDENCY_TABLE = "sp_dependency"
ANGULAR_PROVIDER_M2M_TABLE = "m2m_sp_widget_angular_provider"

# ---------------------------------------------------------------------------
# Cached instance name extraction — avoids re-parsing the URL every call.
# ---------------------------------------------------------------------------
_INSTANCE_NAME_CACHE: Dict[str, str] = {}


def _get_instance_name(config: ServerConfig) -> str:
    """Extract short instance name from config URL, cached."""
    url = config.instance_url
    cached = _INSTANCE_NAME_CACHE.get(url)
    if cached is not None:
        return cached
    name = (urlparse(url).hostname or "instance").split(".")[0]
    _INSTANCE_NAME_CACHE[url] = name
    return name


def _dedupe_fields(fields: List[str]) -> List[str]:
    """Deduplicate a field list while preserving order."""
    seen: Set[str] = set()
    result: List[str] = []
    for f in fields:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result


class GetWidgetBundleParams(BaseModel):
    """Parameters for fetching a simplified widget bundle."""

    widget_id: str = Field(..., description="The sys_id or name of the widget")
    include_providers: bool = Field(
        default=True, description="Whether to include list of associated Angular Providers"
    )
    include_dependencies: bool = Field(
        default=True, description="Whether to include linked CSS/JS Dependencies"
    )


class GetPortalComponentParams(BaseModel):
    """Parameters for fetching specific portal component code."""

    table: str = Field(
        default=...,
        description="The table name (sp_widget, sp_angular_provider, sys_script_include)",
    )
    sys_id: str = Field(..., description="The sys_id of the component")
    fields: List[str] = Field(
        default=["template", "script", "client_script", "css"],
        description="Specific code fields to fetch",
    )
    fetch_complete: bool = Field(
        default=True,
        description="Default True: full body in one call. False only for >12KB single-field reads.",
    )
    script_offset: int = Field(
        default=0,
        description="Rare: only when fetch_complete=False. Leave 0 for normal use.",
    )
    script_max_length: int = Field(
        default=8000,
        description="Rare: chunk size when fetch_complete=False. Leave default unless field >12KB.",
    )


class UpdatePortalComponentParams(BaseModel):
    """Parameters for updating portal component code."""

    table: str = Field(
        default=...,
        description="The table name (sp_widget, sp_angular_provider, sys_script_include)",
    )
    sys_id: str = Field(..., description="The sys_id of the component")
    update_data: Dict[str, str] = Field(default=..., description="Field-value pairs to update.")
    base_updated_on: Optional[str] = Field(
        default=None,
        description="Last-read sys_updated_on; blocks write if remote is newer.",
    )
    force: bool = Field(default=False, description="Override conflict check and write anyway.")


class AnalyzePortalComponentUpdateParams(UpdatePortalComponentParams):
    """Parameters for analyzing a proposed portal component update."""


class PreviewPortalComponentUpdateParams(UpdatePortalComponentParams):
    """Parameters for previewing a proposed portal component update."""


class RoutePortalComponentEditParams(BaseModel):
    """Parameters for shallow natural-language routing into the portal edit pipeline."""

    instruction: str = Field(..., description="Short natural-language instruction")
    table: str | None = Field(
        default=None,
        description="Optional target table (sp_widget, sp_angular_provider, sys_script_include)",
    )
    sys_id: str | None = Field(default=None, description="Optional target component sys_id")
    update_data: Dict[str, str] | None = Field(
        default=None,
        description="Optional explicit field updates for analyze/preview/apply routing",
    )


class DownloadPortalSourcesParams(BaseModel):
    output_dir: str | None = Field(
        default=None,
        description="Omit — default path is canonical and reused. Set only for one-off export.",
    )
    scope: str | None = Field(
        default=None,
        description="Scope namespace (x_app) or app name; auto-resolved to the namespace.",
    )
    widget_ids: List[str] | None = Field(
        default=None,
        description="Optional list of widget sys_id/id/name. If empty, exports all widgets in scope.",
    )
    include_linked_script_includes: bool | None = Field(
        default=None,
        description="Include SIs referenced by exported widgets (default on for targeted export).",
    )
    include_linked_angular_providers: bool | None = Field(
        default=None,
        description="Include angular providers via widget M2M (default on for targeted export).",
    )
    include_widget_client_script: bool = Field(
        default=True,
        description="Include widget client_script.js output",
    )
    include_widget_server_script: bool = Field(
        default=True,
        description="Include widget script.js output",
    )
    include_widget_link_script: bool = Field(
        default=True,
        description="Include widget link.js output",
    )
    include_widget_template: bool = Field(
        default=True,
        description="Include widget template.html output",
    )
    include_widget_css: bool = Field(
        default=True,
        description="Include widget css.scss output",
    )
    max_widgets: int = Field(
        default=25,
        description="Max widgets to export (default 25, clamped to 500; >25 allowed).",
    )
    page_size: int = Field(default=50, description="Pagination size for API queries (10..100)")
    incremental: bool = Field(
        default=False,
        description="Re-download only records changed since last sync. Full-scope only.",
    )
    reconcile_deletions: bool = Field(
        default=False,
        description="Warn about local records deleted on the instance. No auto-delete.",
    )


def _strip_metadata(record: Dict[str, Any], keep_fields: List[str]) -> Dict[str, Any]:
    """Helper to remove unnecessary system fields to save tokens."""
    return {k: v for k, v in record.items() if k in keep_fields or k == "sys_id" or k == "name"}


def _normalize_portal_component_table(table: str) -> str:
    normalized = table.strip()
    if normalized not in PORTAL_COMPONENT_EDITABLE_FIELDS:
        supported = ", ".join(sorted(PORTAL_COMPONENT_EDITABLE_FIELDS))
        raise ValueError(f"Unsupported table '{table}'. Supported tables: {supported}")
    return normalized


def _validate_portal_component_update_data(
    table: str, update_data: Dict[str, str]
) -> Dict[str, str]:
    if not update_data:
        raise ValueError("update_data must include at least one field to modify")

    normalized_table = _normalize_portal_component_table(table)
    allowed_fields = PORTAL_COMPONENT_EDITABLE_FIELDS[normalized_table]
    invalid_fields = sorted(field for field in update_data if field not in allowed_fields)
    if invalid_fields:
        allowed = ", ".join(sorted(allowed_fields))
        raise ValueError(
            f"Unsupported update fields for {normalized_table}: {', '.join(invalid_fields)}. "
            f"Allowed fields: {allowed}"
        )

    normalized_data: Dict[str, str] = {}
    for field_name, value in update_data.items():
        if not isinstance(value, str):
            raise ValueError(f"update_data['{field_name}'] must be a string")
        normalized_data[field_name] = value

    return normalized_data


def _fetch_portal_component_record(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    sys_id: str,
    fields: List[str],
    *,
    full: bool = False,
) -> Dict[str, Any]:
    """Read a single component record.

    ``full=True`` is for diff/verification: it reads via a raw direct GET so long
    fields (e.g. widget ``script``) come back complete. The default sn_query path
    applies the response-budget + per-field truncation, which would make long
    fields falsely compare as "modified"/"mismatched" against the full local copy.
    """
    query_fields = _dedupe_fields([*fields, "name", "sys_id"])

    # Direct GET /{sys_id} returns the raw record (untruncated). Scoped tables
    # often block list-ACL queries even when the record is accessible by direct
    # URL — the same bypass that lets sn_write PATCH succeed.
    def _direct() -> Dict[str, Any]:
        url = (
            f"{config.instance_url.rstrip('/')}/api/now/table/{table}/{sys_id}"
            f"?sysparm_fields={','.join(query_fields)}&sysparm_display_value=false"
        )
        headers = auth_manager.get_headers()
        direct = auth_manager.make_request("GET", url, headers=headers)
        if direct.status_code == 404:
            raise ValueError(f"Component not found in {table} with sys_id {sys_id}")
        if direct.status_code >= 400:
            raise ValueError(
                f"Failed to fetch {table}/{sys_id}: HTTP {direct.status_code} — {direct.text[:200]}"
            )
        data = direct.json().get("result") or {}
        if not data:
            raise ValueError(f"Component not found in {table} with sys_id {sys_id}")
        return data

    # Comparison reads must bypass sn_query truncation — try the raw GET first.
    if full:
        try:
            return _direct()
        except ValueError:
            pass  # direct URL blocked by ACL → fall back to the query path

    # Primary: filter query (works when list-ACL allows it).
    query_params = GenericQueryParams(
        table=table,
        query=f"sys_id={sys_id}",
        fields=",".join(query_fields),
        limit=1,
        offset=0,
        display_value=False,
    )
    response = sn_query(config, auth_manager, query_params)
    if response.get("success") and response.get("results"):
        return response["results"][0]

    return _direct()


_CLIP_MARKER = "(truncated, original length:"


def untruncate_source_fields(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    sys_id: str,
    record: Dict[str, Any],
    fields,
) -> Dict[str, Any]:
    """The single guard every source-returning read should use.

    sn_query's 50k per-field budget (a bulk-safety measure) also clips targeted
    single-record source reads. When any of ``fields`` in ``record`` carries the
    clip marker, re-fetch that record RAW (``full=True`` direct GET) and overwrite
    those fields in place — so a caller never returns, hashes, or pushes a silently
    truncated body. Mutates and returns ``record``; no-op (no extra call) when
    nothing was clipped.
    """
    if any(isinstance(record.get(f), str) and _CLIP_MARKER in record[f] for f in fields):
        try:
            full = _fetch_portal_component_record(
                config, auth_manager, table, sys_id, list(fields), full=True
            )
            for f in fields:
                if isinstance(full.get(f), str):
                    record[f] = full[f]
        except ValueError:
            pass  # keep the clipped body rather than failing the read outright
    return record


def _summarize_text_preview(value: str, max_length: int | None = None) -> str:
    if max_length is None:
        max_length = MAX_PREVIEW_TEXT_LENGTH
    if len(value) <= max_length:
        return value
    half = max_length // 2
    return value[:half] + "\n... [TRUNCATED FOR CONTEXT SAFETY] ...\n" + value[-half:]


def _build_diff_preview(before: str, after: str) -> str:
    diff_lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="current",
            tofile="proposed",
            lineterm="",
            n=3,
        )
    )
    if not diff_lines:
        return ""
    if len(diff_lines) > MAX_PREVIEW_DIFF_LINES:
        diff_lines = diff_lines[:MAX_PREVIEW_DIFF_LINES] + [
            "... [DIFF TRUNCATED FOR CONTEXT SAFETY]"
        ]
    return "\n".join(diff_lines)


def _build_field_change_summary(
    field_name: str, current_value: str, proposed_value: str
) -> Dict[str, Any]:
    changed = current_value != proposed_value
    return {
        "field": field_name,
        "changed": changed,
        "current_length": len(current_value),
        "proposed_length": len(proposed_value),
        "current_lines": len(current_value.splitlines()) if current_value else 0,
        "proposed_lines": len(proposed_value.splitlines()) if proposed_value else 0,
        "delta_length": len(proposed_value) - len(current_value),
    }


def _build_portal_update_risks(table: str, field_summaries: List[Dict[str, Any]]) -> List[str]:
    risks: List[str] = []
    changed_fields = [item for item in field_summaries if item["changed"]]
    if not changed_fields:
        return ["No effective change detected against the current record."]

    if len(changed_fields) > 1:
        risks.append(
            "Multiple fields will be modified in one write; validate widget behavior after apply."
        )

    if table == "sp_widget" and any(
        item["field"] in {"script", "client_script", "link"} for item in changed_fields
    ):
        risks.append(
            "Widget script changes can affect runtime behavior immediately; validate client/server execution paths."
        )

    if any(abs(int(item["delta_length"])) > 2000 for item in changed_fields):
        risks.append(
            "A large content change was detected; export or inspect the full artifact before applying."
        )

    if any(item["field"] == "template" for item in changed_fields):
        risks.append(
            "Template changes should be checked for route bindings and Angular expression regressions."
        )

    if any(item["field"] == "css" for item in changed_fields):
        risks.append("CSS changes can create broad visual regressions; verify selectors and scope.")

    return risks


def _classify_portal_update_risk(risks: List[str], changed_field_count: int) -> str:
    if changed_field_count == 0:
        return "low"
    if changed_field_count == 1 and len(risks) <= 1:
        return "low"
    if changed_field_count <= 2 and len(risks) <= 3:
        return "medium"
    return "high"


_RE_PREVIEW = re.compile(r"\b(preview|diff|show changes|what would change)\b", re.IGNORECASE)
_RE_APPLY = re.compile(r"\b(apply|update|modify|change|patch|fix|edit)\b", re.IGNORECASE)


def _detect_portal_edit_action(instruction: str) -> str:
    if _RE_PREVIEW.search(instruction):
        return "preview"
    if _RE_APPLY.search(instruction):
        return "apply"
    return "analyze"


def _detect_portal_edit_fields(instruction: str) -> List[str]:
    lower = instruction.lower()
    field_aliases = [
        ("client_script", ["client script", "client_script"]),
        ("template", ["template", "html", "markup"]),
        ("css", ["css", "style", "styles"]),
        ("link", ["link script", "link"]),
        ("script", ["server script", "script include script"]),
    ]
    detected: List[str] = []
    for field_name, aliases in field_aliases:
        if any(alias in lower for alias in aliases):
            detected.append(field_name)
    return detected


def _build_portal_edit_router_plan(
    action: str, params: RoutePortalComponentEditParams
) -> Dict[str, Any]:
    normalized_table = _normalize_portal_component_table(params.table) if params.table else None
    normalized_update_data = (
        _validate_portal_component_update_data(normalized_table, params.update_data)
        if normalized_table and params.update_data
        else None
    )

    tool_name = {
        "preview": "preview_portal_component_update",
        "apply": "update_portal_component",
        "analyze": "analyze_portal_component_update",
    }[action]
    missing = [
        name
        for name, value in [
            ("table", normalized_table),
            ("sys_id", params.sys_id),
            ("update_data", normalized_update_data),
        ]
        if not value
    ]
    tool_arguments: Dict[str, Any] = {}
    if normalized_table:
        tool_arguments["table"] = normalized_table
    if params.sys_id:
        tool_arguments["sys_id"] = params.sys_id
    if normalized_update_data:
        tool_arguments["update_data"] = normalized_update_data
    return {
        "tool_name": tool_name,
        "arguments": tool_arguments,
        "confirmation_required": action == "apply",
        "missing_requirements": missing,
    }


def _build_portal_edit_next_call_example(plan: Dict[str, Any]) -> Dict[str, Any]:
    example_arguments = dict(plan.get("arguments") or {})
    for missing in plan.get("missing_requirements") or []:
        example_arguments.setdefault(missing, f"<{missing}>")
    if plan.get("confirmation_required"):
        example_arguments["confirm"] = "approve"

    return {
        "tool_name": str(plan.get("tool_name") or ""),
        "arguments": example_arguments,
    }


def _build_portal_edit_three_stage_flow(
    *,
    action: str,
    params: RoutePortalComponentEditParams,
    suggested_fields: List[str],
    final_plan: Dict[str, Any],
) -> List[Dict[str, Any]]:
    fields = list(suggested_fields or ["template", "client_script"])
    identify_tool_name = (
        "trace_portal_route_targets"
        if any(
            token in params.instruction.lower()
            for token in ["route", "page", "url", "redirect", "navigate"]
        )
        else "search_portal_regex_matches"
    )
    identify_arguments: Dict[str, Any] = {
        "output_mode": "minimal",
        "max_widgets": 10,
    }
    if params.table == WIDGET_TABLE and params.sys_id:
        identify_arguments["widget_ids"] = [params.sys_id]
    elif params.sys_id and params.table == ANGULAR_PROVIDER_TABLE:
        identify_arguments["provider_ids"] = [params.sys_id]
    else:
        identify_arguments["regex"] = params.instruction

    inspect_arguments: Dict[str, Any] = {
        "table": params.table or "<table>",
        "sys_id": params.sys_id or "<sys_id>",
        "fields": fields,
    }

    stage_one_status = "completed" if params.table and params.sys_id else "required"
    stage_two_status = "ready" if params.table and params.sys_id else "blocked"
    stage_three_status = "ready" if not final_plan.get("missing_requirements") else "blocked"
    if action == "apply":
        stage_three_goal = "깊은 적용 전에 bounded analyze/preview로 바뀔 내용을 검토"
    else:
        stage_three_goal = "필요할 때만 깊은 분석/미리보기/적용 단계로 진입"

    return [
        {
            "stage": 1,
            "name": "identify",
            "goal": "빠르게 대상 위젯/라우트/컴포넌트를 식별한다",
            "status": stage_one_status,
            "tool": {
                "tool_name": identify_tool_name,
                "arguments": identify_arguments,
            },
        },
        {
            "stage": 2,
            "name": "expand_related",
            "goal": "대상 한 세트 기준으로 필요한 코드와 연관 컴포넌트만 좁게 확인한다",
            "status": stage_two_status,
            "tool": {
                "tool_name": "get_portal_component_code",
                "arguments": inspect_arguments,
            },
        },
        {
            "stage": 3,
            "name": "deep_apply",
            "goal": stage_three_goal,
            "status": stage_three_status,
            "tool": _build_portal_edit_next_call_example(final_plan),
        },
    ]


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

DEFAULT_REDIRECT_PATTERN = (
    r"(?:/\$sp\.do\?id=[A-Za-z0-9_-]+(?:&[^'\"\s]+)*)"
    r"|(?:/(?:sp|esc|[A-Za-z0-9_-]+)\?id=[A-Za-z0-9_-]+(?:&[^'\"\s]+)*)"
)
MAX_PORTAL_DOWNLOAD_WIDGETS = 500
MAX_WIDGET_REVIEW_LIMIT = 100
MAX_WIDGET_REVIEW_MATCHES = 100
DEFAULT_WIDGET_REVIEW_SNIPPET_LENGTH = 220
MAX_ANGULAR_PROVIDER_SCAN_LIMIT = 100
MAX_ANGULAR_IMPLICIT_GLOBAL_MATCHES = 100
DEFAULT_ANGULAR_IMPLICIT_SNIPPET_LENGTH = 180
MAX_COMPONENT_SCRIPT_CHARS = 12000
MAX_PREVIEW_TEXT_LENGTH = 600
MAX_PREVIEW_DIFF_LINES = 80

PORTAL_COMPONENT_EDITABLE_FIELDS: Dict[str, Set[str]] = {
    "sp_widget": {"template", "script", "client_script", "link", "css"},
    "sp_angular_provider": {"script"},
    "sys_script_include": {"script"},
    "sys_script": {"script", "condition"},
    "sp_header_footer": {"template", "script", "client_script", "link", "css"},
    "sp_css": {"css"},
    "sp_ng_template": {"template"},
    "sys_ui_page": {"html", "client_script", "processing_script"},
    # --- Code-bearing tables that download_server_sources can pull but had no
    # write path (the read/write asymmetry). Editable fields mirror each table's
    # download source_fields, so anything you can download you can push back BY
    # SYS_ID — the only safe target for these (their names aren't globally unique;
    # a folder/name-based push can hit the wrong record). sys_update_xml is
    # deliberately EXCLUDED: it's the update-set change record, not a source.
    # Scripted REST resource also exposes its path fields (relative_path /
    # operation_uri) since editing the route is a normal operation.
    "sys_ws_operation": {"operation_script", "relative_path", "operation_uri"},
    "sys_ui_action": {"script"},
    "sys_ui_script": {"script"},
    "sys_ui_macro": {"xml"},
    "sys_script_client": {"script"},
    "catalog_script_client": {"script"},
    "sys_script_fix": {"script"},
    "sys_processor": {"script"},
    "sys_security_acl": {"script"},
    "sys_transform_script": {"script"},
    "sysauto_script": {"script"},
    "sysevent_script_action": {"script"},
    "sysevent_email_action": {"subject", "message_html", "message_text"},
}

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
        default=DEFAULT_REDIRECT_PATTERN,
        description="Pattern to find in source",
    )
    match_mode: str = Field(default="auto", description="auto | literal | regex")
    updated_by: str | None = Field(default=None, description="sys_updated_by filter")
    scope: str | None = Field(default=None, description="sys_scope filter")
    widget_ids: List[str] | None = Field(default=None, description="Widget id/sys_id/name filter")
    provider_ids: List[str] | None = Field(
        default=None, description="Angular provider sys_id/name filter (bypasses M2M)"
    )
    source_types: List[str] = Field(
        default=["widget"],
        description="widget | script_include | angular_provider",
    )
    updated_after: str | None = Field(default=None, description="sys_updated_on >= (YYYY-MM-DD)")
    updated_before: str | None = Field(default=None, description="sys_updated_on <= (YYYY-MM-DD)")
    include_linked_script_includes: bool = Field(
        default=False, description="Also scan referenced Script Includes"
    )
    include_linked_angular_providers: bool = Field(
        default=False, description="Also scan linked Angular Providers"
    )
    linked_components_updated_by_only: bool = Field(
        default=False, description="Filter linked SI/Providers by same updated_by"
    )
    include_widget_fields: List[str] = Field(
        default=["template", "script", "client_script", "link", "css"],
        description="Widget fields to scan",
    )
    max_widgets: int = Field(default=25, description="Max widgets to scan")
    page_size: int = Field(default=50, description="API page size (10-100)")
    max_matches: int = Field(default=25, description="Max matches to return")
    snippet_length: int = Field(
        default=DEFAULT_WIDGET_REVIEW_SNIPPET_LENGTH, description="Max snippet length per match"
    )
    compact_output: bool = Field(default=True, description="Compact output")
    output_mode: str | None = Field(default=None, description="minimal | compact | full")


class TracePortalRouteTargetsParams(BaseModel):
    regex: str = Field(
        default=DEFAULT_REDIRECT_PATTERN, description="Route/target pattern to trace"
    )
    match_mode: str = Field(default="auto", description="auto | literal | regex")
    updated_by: str | None = Field(default=None, description="sys_updated_by filter")
    scope: str | None = Field(default=None, description="sys_scope filter")
    widget_ids: List[str] | None = Field(default=None, description="Widget id/sys_id/name filter")
    provider_ids: List[str] | None = Field(
        default=None, description="Provider id/sys_id/name filter"
    )
    include_linked_angular_providers: bool = Field(
        default=True, description="Also trace linked Angular Providers"
    )
    include_widget_fields: List[str] = Field(
        default=["template", "script", "client_script", "link"],
        description="Widget fields to inspect",
    )
    max_widgets: int = Field(default=10, description="Max widgets to analyze")
    page_size: int = Field(default=50, description="API page size (10-100)")
    max_traces: int = Field(default=25, description="Max trace rows to return")
    snippet_length: int = Field(
        default=DEFAULT_WIDGET_REVIEW_SNIPPET_LENGTH, description="Max snippet length per match"
    )
    output_mode: str = Field(default="minimal", description="minimal | compact | full")


class DetectAngularImplicitGlobalsParams(BaseModel):
    updated_by: str | None = Field(default=None, description="sys_updated_by filter")
    scope: str | None = Field(default=None, description="sys_scope filter")
    provider_ids: List[str] | None = Field(
        default=None, description="Provider id/sys_id/name filter"
    )
    updated_after: str | None = Field(default=None, description="sys_updated_on >= (YYYY-MM-DD)")
    updated_before: str | None = Field(default=None, description="sys_updated_on <= (YYYY-MM-DD)")
    max_providers: int = Field(default=25, description="Max providers to scan")
    page_size: int = Field(default=50, description="API page size (10-100)")
    max_matches: int = Field(default=25, description="Max findings to return")
    snippet_length: int = Field(
        default=DEFAULT_ANGULAR_IMPLICIT_SNIPPET_LENGTH, description="Max snippet length"
    )
    output_mode: str = Field(default="minimal", description="minimal | compact | full")


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


def _parallel_chunked_query(
    config: "ServerConfig",
    auth_manager: "AuthManager",
    *,
    table: str,
    chunks: List[List[str]],
    query_template: str,
    fields: str,
    page_size: int,
    max_records: int,
) -> List[Dict[str, Any]]:
    """Execute chunked sn_query_all calls in parallel via the shared executor.

    *query_template* must contain ``{ids}`` which is replaced with a
    comma-joined list of IDs for each chunk.
    """
    if not chunks:
        return []
    if len(chunks) == 1:
        query = query_template.format(ids=",".join(chunks[0]))
        return sn_query_all(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=fields,
            page_size=page_size,
            max_records=max_records,
        )

    def _fetch(chunk: List[str]) -> List[Dict[str, Any]]:
        query = query_template.format(ids=",".join(chunk))
        return sn_query_all(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=fields,
            page_size=page_size,
            max_records=max_records,
        )

    rows: List[Dict[str, Any]] = []
    executor = _get_page_executor()
    futures = {executor.submit(_fetch, c): c for c in chunks}
    for future in as_completed(futures):
        try:
            rows.extend(future.result())
        except Exception:
            logger.warning("Parallel chunk query failed for table %s", table)
    return rows


def _fetch_field_by_sys_id_parallel(
    config: "ServerConfig",
    auth_manager: "AuthManager",
    *,
    table: str,
    sys_ids: List[str],
    field: str,
) -> Dict[str, str]:
    """Fetch a single large text *field* (e.g. ``script``) for many records
    CONCURRENTLY — one record per request via the shared executor.

    Why one-record-per-request rather than a bulk ``sys_idIN`` query: provider
    scripts are frequently large (>12KB); bundling dozens into one response
    bloats it and risks truncation. Keeping one value per response preserves that
    safety while the shared executor removes the sequential round-trip-per-record
    bottleneck (N sequential GETs → N parallel). Missing/failed fetches map to ""
    (fail-open). Returns ``{sys_id: field_value}``."""
    unique_ids = [sid for sid in dict.fromkeys(sys_ids) if sid]
    if not unique_ids:
        return {}

    def _fetch_one(sys_id: str) -> Tuple[str, str]:
        try:
            rows, _ = sn_query_page(
                config,
                auth_manager,
                table=table,
                query=f"sys_id={sys_id}",
                fields=field,
                limit=1,
                offset=0,
                display_value=False,
                no_count=True,
            )
            return sys_id, (str(rows[0].get(field) or "") if rows else "")
        except Exception:
            return sys_id, ""

    result: Dict[str, str] = {}
    executor = _get_page_executor()
    futures = {executor.submit(_fetch_one, sid): sid for sid in unique_ids}
    for future in as_completed(futures):
        try:
            sys_id, value = future.result()
            result[sys_id] = value
        except Exception:
            logger.warning("Parallel field fetch failed for %s.%s", table, field)
    return result


def _dedupe_preserve_order_strings(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    result: List[str] = []
    for value in values:
        token = value.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def _fetch_linked_script_include_rows(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    candidates: List[str],
    page_size: int,
    scope: str | None = None,
    updated_by: str | None = None,
    updated_after: str | None = None,
    updated_before: str | None = None,
) -> List[Dict[str, Any]]:
    normalized_candidates = _dedupe_preserve_order_strings(candidates)
    if not normalized_candidates:
        return []

    rows_by_sys_id: Dict[str, Dict[str, Any]] = {}
    safe_updated_by = _escape_query(updated_by) if updated_by else ""

    for chunk in _chunked(normalized_candidates, 20):
        candidate_clauses: List[str] = []
        for candidate in chunk:
            safe_candidate = _escape_query(candidate)
            candidate_clauses.extend(
                [
                    f"name={safe_candidate}",
                    f"api_name={safe_candidate}",
                    f"api_nameENDSWITH.{safe_candidate}",
                ]
            )

        # Encoded queries have no parenthesis grouping — "(name=x" parses as an
        # invalid field and silently corrupts the first/last OR clauses.
        # `a^ORb^ORc^scope=X` already means (a OR b OR c) AND scope=X.
        query_parts = ["^OR".join(candidate_clauses)]
        if scope:
            query_parts.append(f"sys_scope.scope={_escape_query(scope)}")
        if updated_by:
            query_parts.append(f"sys_updated_by={safe_updated_by}")
        if updated_after:
            query_parts.append(f"sys_updated_on>={_escape_query(updated_after)}")
        if updated_before:
            query_parts.append(f"sys_updated_on<={_escape_query(updated_before)}")

        rows = _sn_query_all(
            config,
            auth_manager,
            table="sys_script_include",
            query="^".join(query_parts),
            fields="sys_id,name,api_name,script,sys_scope,sys_updated_by,sys_updated_on,sys_mod_count",
            page_size=page_size,
            max_records=max(20, len(chunk) * 5),
        )
        for row in rows:
            sys_id = str(row.get("sys_id") or "")
            if sys_id and sys_id not in rows_by_sys_id:
                rows_by_sys_id[sys_id] = row

    return list(rows_by_sys_id.values())


def _fetch_targeted_widget_rows(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    widget_tokens: List[str],
    widget_base_query: str,
    widget_fields: str,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Fetch exactly the requested widgets. Returns (rows, unmatched_tokens).

    Only rows that match a requested token (sys_id/id/name) are returned —
    a malformed or leniently-parsed server-side query must never turn into
    "downloaded 20 arbitrary scope widgets" masquerading as the targeted set.
    """
    normalized_tokens = _dedupe_preserve_order_strings(widget_tokens)
    if not normalized_tokens:
        return [], []

    rows_by_sys_id: Dict[str, Dict[str, Any]] = {}
    token_matches: Dict[str, List[str]] = {token: [] for token in normalized_tokens}

    for chunk in _chunked(normalized_tokens, 20):
        clauses: List[str] = []
        for token in chunk:
            safe_token = _escape_query(token)
            clauses.extend(
                [
                    f"sys_id={safe_token}",
                    f"id={safe_token}",
                    f"name={safe_token}",
                ]
            )

        # No parentheses: encoded queries don't support grouping — "(sys_id=X"
        # parses as an invalid field and, on instances that ignore invalid
        # conditions, collapses the OR-group into "match everything".
        # `a^ORb^ORc^scope=X` already binds as (a OR b OR c) AND scope=X.
        query = "^OR".join(clauses)
        if widget_base_query:
            query += f"^{widget_base_query}"

        rows = _sn_query_all(
            config,
            auth_manager,
            table=WIDGET_TABLE,
            query=query,
            fields=widget_fields,
            page_size=page_size,
            max_records=max(len(chunk) * 3, 20),
        )

        for row in rows:
            sys_id = str(row.get("sys_id") or "")
            if not sys_id:
                continue
            rows_by_sys_id.setdefault(sys_id, row)

            candidate_tokens = _dedupe_preserve_order_strings(
                [
                    str(row.get("sys_id") or ""),
                    str(row.get("id") or ""),
                    str(row.get("name") or ""),
                ]
            )
            for candidate in candidate_tokens:
                if candidate in token_matches and sys_id not in token_matches[candidate]:
                    token_matches[candidate].append(sys_id)

    ordered_rows: List[Dict[str, Any]] = []
    seen_sys_ids: Set[str] = set()
    for token in normalized_tokens:
        for sys_id in token_matches.get(token, []):
            if sys_id in seen_sys_ids:
                continue
            matched_row = rows_by_sys_id.get(sys_id)
            if matched_row is None:
                continue
            ordered_rows.append(matched_row)
            seen_sys_ids.add(sys_id)

    # Rows matching NO requested token are dropped, not appended: they can only
    # be query-parser noise, and passing them through silently replaces the
    # user's targeted set with arbitrary scope widgets.
    unmatched_tokens = [token for token in normalized_tokens if not token_matches.get(token)]
    return ordered_rows, unmatched_tokens


def _locate_missing_widget_tokens(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    missing_tokens: List[str],
    requested_scope: str | None,
    page_size: int,
) -> List[str]:
    """Explain targeted widget_ids that matched nothing — never a silent drop.

    With a scope filter active, a light no-filter probe distinguishes
    "lives in another scope" (actionable retry command) from "absent on this
    instance" (wrong sys_id, or a session connected to a different instance).
    """
    located: Dict[str, str] = {}
    still_missing = list(missing_tokens)
    if requested_scope:
        try:
            probe_rows, still_missing = _fetch_targeted_widget_rows(
                config,
                auth_manager,
                widget_tokens=missing_tokens,
                widget_base_query="",
                widget_fields="sys_id,name,id,sys_scope.scope",
                page_size=page_size,
            )
            for row in probe_rows:
                actual_scope = str(row.get("sys_scope.scope") or "") or "(unknown)"
                row_keys = {
                    str(row.get("sys_id") or ""),
                    str(row.get("id") or ""),
                    str(row.get("name") or ""),
                }
                for token in missing_tokens:
                    if token in row_keys and token not in located:
                        located[token] = actual_scope
        except Exception:
            still_missing = list(missing_tokens)

    messages: List[str] = []
    for token, actual_scope in located.items():
        messages.append(
            f"NOT DOWNLOADED — widget '{token}' exists on this instance but lives in scope "
            f"'{actual_scope}', not '{requested_scope}'. Re-run: "
            f"download_portal_sources(scope='{actual_scope}', widget_ids=['{token}'])"
        )
    # Wrong-instance detection, offline: a token absent HERE but present in
    # another instance's previously downloaded tree almost always means the
    # session/target is pointed at the wrong instance (the multi-session trap).
    # Local scan only — a live probe of sibling instances could trigger their
    # login flow (browser window) from inside a download, which is worse than
    # the miss it explains.
    hint_messages, hinted_tokens = _locate_tokens_in_other_local_trees(
        still_missing, current_instance_name=_get_instance_name(config)
    )
    messages.extend(hint_messages)
    for token in still_missing:
        if token in hinted_tokens:
            continue
        messages.append(
            f"NOT FOUND — widget '{token}' matched no sys_id/id/name on "
            f"{config.instance_url}. Verify the value, and verify this session is "
            f"connected to the intended instance."
        )
    return messages


# Bound the offline wrong-instance scan: newest N recorded roots is plenty —
# roots are LRU-recorded per download and stale trees only add noise.
_LOCAL_TREE_HINT_MAX_ROOTS = 20


def _locate_tokens_in_other_local_trees(
    missing_tokens: List[str], *, current_instance_name: str
) -> Tuple[List[str], Set[str]]:
    """Offline hint for tokens missing on the current instance.

    Scans previously downloaded ``sp_widget/_map.json`` files (id → sys_id) of
    OTHER instances' trees. Zero network. Returns (messages, hinted_tokens);
    best-effort — any read problem just yields fewer hints, never an error.
    """
    messages: List[str] = []
    hinted: Set[str] = set()
    if not missing_tokens:
        return messages, hinted
    remaining = set(missing_tokens)
    for scope_root in known_download_roots()[:_LOCAL_TREE_HINT_MAX_ROOTS]:
        if not remaining:
            break
        instance_name = scope_root.parent.name
        if instance_name == current_instance_name:
            continue
        try:
            widget_map = json_fast.loads(
                (scope_root / "sp_widget" / "_map.json").read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001 — absent/corrupt map = no hint from this tree
            continue
        if not isinstance(widget_map, dict):
            continue
        known_ids = {str(k) for k in widget_map}
        known_sys_ids = {str(v) for v in widget_map.values()}
        for token in sorted(remaining):
            if token in known_ids or token in known_sys_ids:
                remaining.discard(token)
                hinted.add(token)
                messages.append(
                    f"WRONG INSTANCE? — widget '{token}' is not on THIS instance "
                    f"('{current_instance_name}') but exists in the local download tree of "
                    f"instance '{instance_name}' ({scope_root}). If that instance was "
                    f"intended, re-run the download with instance='{instance_name}' "
                    f"(or its configured alias)."
                )
    return messages, hinted


def _download_widget_fields(
    *,
    include_widget_template: bool,
    include_widget_server_script: bool,
    include_widget_client_script: bool,
    include_widget_link_script: bool,
    include_widget_css: bool,
    include_linked_script_includes: bool,
) -> str:
    # sys_updated_by rides along (1 field, no extra call): it becomes the baseline
    # OWNER in _sync_meta, which is what a later diff compares the current editor
    # against. Without it every record's recorded owner is empty, so "who moved
    # this since my download" has no answer to give.
    fields = [
        "sys_id",
        "name",
        "id",
        "sys_scope",
        "option_schema",
        "demo_data",
        "sys_updated_on",
        "sys_updated_by",
        # Live-authority drift anchor recorded in _sync_meta (see sync_tools):
        # the server's monotonic counter, so movement is judged by fact not a
        # possibly-stale local snapshot.
        "sys_mod_count",
    ]
    if include_widget_template:
        fields.append("template")
    if include_widget_server_script or include_linked_script_includes:
        fields.append("script")
    if include_widget_client_script or include_linked_script_includes:
        fields.append("client_script")
    if include_widget_link_script:
        fields.append("link")
    if include_widget_css:
        fields.append("css")
    return ",".join(_dedupe_preserve_order_strings(fields))


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


def _clamp_download_widget_limit(value: int) -> int:
    return max(1, min(value, MAX_PORTAL_DOWNLOAD_WIDGETS))


def _clamp_script_chunk_length(value: int) -> int:
    return max(1000, min(value, MAX_COMPONENT_SCRIPT_CHARS))


def _portal_scan_warnings(
    *,
    requested_max_widgets: int | None = None,
    effective_max_widgets: int | None = None,
    requested_max_matches: int | None = None,
    effective_max_matches: int | None = None,
    include_linked_script_includes: bool = False,
    include_linked_angular_providers: bool = False,
    widget_ids: List[str] | None = None,
    provider_ids: List[str] | None = None,
) -> List[str]:
    warnings: List[str] = []
    targeted_widget_count = len(widget_ids or [])
    targeted_provider_count = len(provider_ids or [])

    if targeted_widget_count == 0 and targeted_provider_count == 0:
        warnings.append(
            "No explicit widget/provider target was provided. The server will stay conservative, but targeted IDs are recommended."
        )
    if include_linked_script_includes or include_linked_angular_providers:
        warnings.append(
            "Linked component expansion is enabled. This increases remote queries and response size."
        )
    if (
        requested_max_widgets is not None
        and effective_max_widgets is not None
        and requested_max_widgets > effective_max_widgets
    ):
        warnings.append(
            f"Requested max_widgets={requested_max_widgets} exceeds the safety cap and was reduced to {effective_max_widgets}."
        )
    if (
        requested_max_matches is not None
        and effective_max_matches is not None
        and requested_max_matches > effective_max_matches
    ):
        warnings.append(
            f"Requested max_matches={requested_max_matches} exceeds the safety cap and was reduced to {effective_max_matches}."
        )
    if requested_max_widgets is not None and requested_max_widgets > 25:
        warnings.append(
            f"Info: max_widgets={requested_max_widgets} will fetch a wider set. This is allowed and not blocked; "
            "targeted widget_ids are preferred when a specific set is known."
        )

    return warnings


def _looks_like_regex(pattern: str) -> bool:
    return bool(re.search(r"\\|\[|\]|\(|\)|\{|\}|\||\^|\$|\.\*|\.\+|\.\?|\(\?", pattern))


def _resolve_match_mode(match_mode: str) -> str:
    normalized = match_mode.strip().lower()
    if normalized in {"auto", "literal", "regex"}:
        return normalized
    raise ValueError("match_mode must be one of: auto, literal, regex")


def _compile_search_pattern(pattern: str, match_mode: str) -> tuple[re.Pattern[str], str, str]:
    raw = pattern or DEFAULT_REDIRECT_PATTERN
    mode = _resolve_match_mode(match_mode)
    effective_mode = mode
    resolved_pattern = raw

    if mode == "literal":
        resolved_pattern = re.escape(raw)
    elif mode == "auto":
        if not _looks_like_regex(raw):
            effective_mode = "literal"
            resolved_pattern = re.escape(raw)
        else:
            effective_mode = "regex"

    return re.compile(resolved_pattern), resolved_pattern, effective_mode


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
        route_details = _extract_portal_route_details(matched_text)
        hits.append(
            {
                "source_type": source_type,
                "source_sys_id": source_sys_id,
                "source_name": source_name,
                "field": field_name,
                "offset": start,
                "line": line,
                "column": column,
                "match": matched_text,
                "snippet": _slice_one_line_snippet(content, start, end, snippet_length),
                **route_details,
            }
        )
    return hits


def _extract_portal_route_details(matched_text: str) -> Dict[str, Any]:
    if not matched_text.startswith("/"):
        return {}

    parsed = urlparse(matched_text)
    if not parsed.path:
        return {}

    route_id = parse_qs(parsed.query).get("id", [None])[0]
    path = parsed.path.lower()
    if path == "/esc":
        route_family = "employee_center"
    elif path in {"/sp", "/$sp.do"}:
        route_family = "service_portal"
    else:
        route_family = "custom_portal"

    details: Dict[str, Any] = {
        "route_family": route_family,
        "route_path": parsed.path,
    }
    if route_id:
        details["route_id"] = route_id
    return details


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
                **({"route_family": item.get("route_family")} if item.get("route_family") else {}),
                **({"route_id": item.get("route_id")} if item.get("route_id") else {}),
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


_TEMPLATE_ACTION_RE = re.compile(r"(?:ng-click|ng-change|onclick)\s*=\s*[\"']([^\"']+)[\"']")
_CALLABLE_NAME_RE = re.compile(r"(?:^|[^.\w$])([A-Za-z_$][\w$]*)\s*\(")
_FUNCTION_CONTEXT_RE = re.compile(
    r"(?:function\s+([A-Za-z_$][\w$]*)\s*\(|([A-Za-z_$][\w$]*)\s*[:=]\s*function\s*\(|([A-Za-z_$][\w$]*)\s*[:=]\s*\([^)]*\)\s*=>)"
)


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen: Set[str] = set()
    deduped: List[str] = []
    for value in values:
        token = value.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _extract_click_handlers(template: str) -> List[str]:
    handlers: List[str] = []
    if not template:
        return handlers
    for expression in _TEMPLATE_ACTION_RE.findall(template):
        inner = expression.strip()
        if inner:
            handlers.append(inner)
        for callable_name in _CALLABLE_NAME_RE.findall(expression):
            handlers.append(callable_name)
    return _dedupe_preserve_order(handlers)


def _find_latest_function_context(content: str, index: int) -> str | None:
    latest: str | None = None
    for match in _FUNCTION_CONTEXT_RE.finditer(content):
        if match.start() > index:
            break
        latest = match.group(1) or match.group(2) or match.group(3)
    return latest


def _route_target_summary(value: str) -> Dict[str, str]:
    parsed = urlparse(value)
    route_path = parsed.path or value
    query = parse_qs(parsed.query)
    page_id = ""
    if "id" in query and query["id"]:
        page_id = query["id"][0]
    elif re.fullmatch(r"[A-Za-z0-9_-]+", value.strip()):
        page_id = value.strip()
    return {
        "target": value,
        "path": route_path,
        "page_id": page_id,
    }


def _shape_trace_hit(hit: Dict[str, Any], *, output_mode: str) -> Dict[str, Any]:
    base = {
        "location": _match_location(
            str(hit.get("source_type") or ""),
            str(hit.get("source_name") or ""),
            str(hit.get("field") or ""),
        ),
        "line": hit.get("line"),
        "match": hit.get("match"),
    }
    if output_mode in {"compact", "full"}:
        base["field"] = hit.get("field")
        base["column"] = hit.get("column")
        base["snippet"] = hit.get("snippet")
    if output_mode == "full":
        if hit.get("context_name"):
            base["context_name"] = hit.get("context_name")
        if hit.get("provider"):
            base["provider"] = hit.get("provider")
    return base


def _shape_route_trace(trace: Dict[str, Any], *, output_mode: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "widget": trace["widget"],
        "route_targets": trace["route_targets"],
        "service_names": trace["service_names"],
        "button_handlers": trace["button_handlers"],
        "branch_names": trace["branch_names"],
        "evidence": trace["evidence"],
    }
    if output_mode in {"compact", "full"}:
        payload["matched_provider_count"] = trace["matched_provider_count"]
        payload["matched_widget_field_count"] = trace["matched_widget_field_count"]
    if output_mode == "full":
        payload["provider_matches"] = trace["provider_matches"]
        payload["widget_matches"] = trace["widget_matches"]
        payload["linked_providers"] = trace["linked_providers"]
    return payload


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
    fail_silently: bool = True,
) -> List[Dict[str, Any]]:
    """Delegate to shared parallel-capable ``sn_query_all`` in sn_api.

    fail_silently=False callers are bulk downloads that must be COMPLETE —
    those get transient-error retry; fail_silently=True callers already
    tolerate partial results, so plain delegation keeps their semantics.
    """
    if not fail_silently:
        return sn_query_all_with_retry(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=fields,
            page_size=page_size,
            max_records=max_records,
            query_all_fn=sn_query_all,
        )
    return sn_query_all(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        page_size=page_size,
        max_records=max_records,
        fail_silently=fail_silently,
    )


# Process-lifetime capability cache: (instance_url, table) -> table exists?
# Some Service Portal m2m tables (notably the angular-provider junction
# m2m_sp_widget_angular_provider) are simply ABSENT on certain ServiceNow
# releases — the Table API hard-fails them with 400 "Invalid table" in ~12ms.
# We learn this from the FIRST real query's response (no extra probe request)
# and cache it, so subsequent dependent reads across the process skip the dead
# query instead of each 400-ing on its own. Confirmed via sys_db_object (0 rows
# on the affected instances) + transaction-log fast-fail.
_TABLE_AVAILABILITY: Dict[Tuple[str, str], bool] = {}


def _table_known_absent(config: ServerConfig, table: str) -> bool:
    """True only when a prior query proved *table* absent (400 Invalid table).

    Unknown tables return False so the real query still runs — the cache is
    populated as a side effect of that run via ``_note_table_response``.
    """
    return _TABLE_AVAILABILITY.get((config.instance_url, table)) is False


def _note_table_response(config: ServerConfig, table: str, response: Dict[str, Any]) -> None:
    """Record table availability from a real ``sn_query`` response.

    A success marks the table present; a 400 marks it absent (cached for the
    process). Other failures (401/timeout) are NOT cached, so a transient blip
    never suppresses the table for the rest of the process.
    """
    key = (config.instance_url, table)
    if response.get("success"):
        _TABLE_AVAILABILITY[key] = True
    elif "400" in str(response.get("message", "")):
        _TABLE_AVAILABILITY[key] = False
        logger.debug(
            "Table %s unavailable on %s (400 Invalid table) — skipping dependent reads",
            table,
            config.instance_url,
        )


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # EOL canonicalized to LF so the same widget downloaded from two instances
    # compares clean (no whole-file CRLF<->LF phantom diff).
    path.write_text(normalize_source_eol(content), encoding="utf-8")


def _write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_fast.dumps(payload), encoding="utf-8")


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
    except (ValueError, TypeError):
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
                return json_fast.loads(trimmed)
            except (ValueError, TypeError):
                return value
    return value


@register_tool(
    "get_widget_bundle",
    params=GetWidgetBundleParams,
    description="Fetch full widget bundle (HTML, scripts, providers, CSS/JS dependencies) in one call. Analysis starting point.",
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
    query = f"sys_id={params.widget_id}^ORid={params.widget_id}^ORname={params.widget_id}"
    widget_fields = ["name", "id", "template", "script", "client_script", "css", "sys_id"]

    query_params = GenericQueryParams(
        table=WIDGET_TABLE,
        query=query,
        fields=",".join(widget_fields),
        limit=1,
        offset=0,
        display_value=False,
    )
    response = sn_query(config, auth_manager, query_params)

    if not response.get("success") or not response.get("results"):
        return {"error": f"Widget '{params.widget_id}' not found."}

    widget = _strip_metadata(response["results"][0], widget_fields)
    # A >50KB body clipped by sn_query would be silently lost on an edit+push —
    # re-fetch raw when any body field came back truncated (shared guard).
    _body_fields = ["template", "script", "client_script", "css"]
    untruncate_source_fields(
        config, auth_manager, WIDGET_TABLE, widget["sys_id"], widget, _body_fields
    )
    # Deliberate completeness, never an opaque dump: disclose each body field's true
    # length so the caller sees exactly what it received (not a silently clipped or
    # blindly huge blob). If a field is very large, name the bounded read paths so a
    # full inline body is a choice, not a surprise.
    _oversized = [
        f for f in _body_fields if isinstance(widget.get(f), str) and len(widget[f]) > 50000
    ]
    for f in _body_fields:
        if isinstance(widget.get(f), str):
            widget[f"_{f}_length"] = len(widget[f])
    bundle: Dict[str, Any] = {"widget": widget}
    if _oversized:
        bundle["large_bodies"] = {
            "fields": _oversized,
            "note": (
                "Returned in full. For a bounded/chunked read use get_portal_component_code"
                "(table='sp_widget', sys_id=..., fetch_complete=False); download_portal_sources "
                "writes full source to disk and returns only a summary to context."
            ),
        }

    # 2. Fetch Angular Provider list (minimal info to save context)
    if params.include_providers:
        providers_m2m: List[Dict[str, Any]] = []
        if not _table_known_absent(config, ANGULAR_PROVIDER_M2M_TABLE):
            m2m_query_params = GenericQueryParams(
                table=ANGULAR_PROVIDER_M2M_TABLE,
                query=f"sp_widget={widget['sys_id']}",
                fields="sp_angular_provider",
                limit=100,
                offset=0,
                display_value=False,
            )
            m2m_response = sn_query(config, auth_manager, m2m_query_params)
            _note_table_response(config, ANGULAR_PROVIDER_M2M_TABLE, m2m_response)
            providers_m2m = m2m_response.get("results", [])

        provider_ids: List[str] = []
        for provider_row in providers_m2m:
            provider_id = _as_ref_sys_id(provider_row.get("sp_angular_provider"))
            if provider_id:
                provider_ids.append(provider_id)

        if provider_ids:
            prov_query_params = GenericQueryParams(
                table=ANGULAR_PROVIDER_TABLE,
                query=f"sys_idIN{','.join(provider_ids)}",
                fields="name,sys_id,type",
                limit=100,
                offset=0,
                display_value=False,
            )
            prov_response = sn_query(config, auth_manager, prov_query_params)
            bundle["angular_providers"] = [
                {"name": p["name"], "sys_id": p["sys_id"], "type": p.get("type", "")}
                for p in prov_response.get("results", [])
            ]
        else:
            bundle["angular_providers"] = []

    # 3. Fetch CSS/JS Dependencies (m2m_sp_widget_dependency -> sp_dependency).
    #    Surfacing these here is what stops sessions from re-discovering the
    #    overloaded "dependency" tables by hand. The Angular module name lives
    #    on sp_dependency.module — that is what gets injected into the widget.
    if params.include_dependencies:
        dep_m2m_params = GenericQueryParams(
            table=WIDGET_DEPENDENCY_TABLE,
            query=f"sp_widget={widget['sys_id']}",
            fields="sp_dependency",
            limit=100,
            offset=0,
            display_value=False,
        )
        dep_m2m_response = sn_query(config, auth_manager, dep_m2m_params)

        dependency_ids: List[str] = []
        for dep_row in dep_m2m_response.get("results", []):
            dep_id = _as_ref_sys_id(dep_row.get("sp_dependency"))
            if dep_id:
                dependency_ids.append(dep_id)

        if dependency_ids:
            dep_query_params = GenericQueryParams(
                table=DEPENDENCY_TABLE,
                query=f"sys_idIN{','.join(dependency_ids)}",
                fields="name,sys_id,module,page_load",
                limit=100,
                offset=0,
                display_value=False,
            )
            dep_response = sn_query(config, auth_manager, dep_query_params)
            bundle["dependencies"] = [
                {
                    "name": d["name"],
                    "sys_id": d["sys_id"],
                    "module": d.get("module", ""),
                    "page_load": d.get("page_load", ""),
                }
                for d in dep_response.get("results", [])
            ]
        else:
            bundle["dependencies"] = []

    return bundle


@register_tool(
    "get_portal_component_code",
    params=GetPortalComponentParams,
    description="Fetch widget/provider/SI fields. Returns full body by default. Never chunk for analysis.",
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
        display_value=False,
    )
    response = sn_query(config, auth_manager, query_params)

    if not response.get("success") or not response.get("results"):
        return {"error": f"Component not found in {params.table} with sys_id {params.sys_id}"}

    # Only return requested code fields to keep context clean
    result = _strip_metadata(response["results"][0], params.fields)

    # A clipped body would corrupt both the returned source AND the sha/length/
    # chunk-offset metadata below (fetch_complete=True would then label a capped
    # body "complete"). Re-fetch any clipped field raw (shared guard).
    untruncate_source_fields(
        config, auth_manager, params.table, params.sys_id, result, params.fields
    )

    for field in params.fields:
        val = result.get(field, "")
        if not isinstance(val, str):
            continue
        total_length = len(val)
        result[f"_{field}_sha256"] = hashlib.sha256(val.encode()).hexdigest()
        result[f"_{field}_total_length"] = total_length

        if params.fetch_complete:
            result[f"_{field}_returned_length"] = total_length
            continue

        budget = _clamp_script_chunk_length(params.script_max_length)
        offset = max(0, params.script_offset)
        end = offset + budget
        if end < total_length:
            snap = val.rfind("\n", offset, end)
            if snap <= offset:
                for delim in (";", "}", ")", "]", ",", ">", " "):
                    snap = val.rfind(delim, offset, end)
                    if snap > offset:
                        break
            if snap > offset:
                end = snap + 1
        chunk = val[offset:end]
        result[field] = chunk
        result[f"_{field}_offset"] = offset
        result[f"_{field}_returned_length"] = len(chunk)
        if end < total_length:
            result[f"_{field}_has_more"] = True
            result[f"_{field}_next_offset"] = end

    return result


@register_tool(
    "analyze_portal_component_update",
    params=AnalyzePortalComponentUpdateParams,
    description="Analyze a proposed portal component edit and return bounded risk and field-change summaries",
    serialization="raw_dict",
    return_type=dict,
)
def analyze_portal_component_update(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: AnalyzePortalComponentUpdateParams,
) -> Dict[str, Any]:
    normalized_table = _normalize_portal_component_table(params.table)
    normalized_update_data = _validate_portal_component_update_data(
        normalized_table, params.update_data
    )
    # full=True: change summaries (lengths, line counts, changed?) compare against
    # the CURRENT body — the default path clips >50k fields (truncate_results) and
    # would report a false "changed" + wrong delta for a >50KB field.
    current_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        list(normalized_update_data.keys()),
        full=True,
    )

    field_summaries = [
        _build_field_change_summary(
            field_name,
            str(current_record.get(field_name) or ""),
            proposed_value,
        )
        for field_name, proposed_value in normalized_update_data.items()
    ]
    changed_field_count = sum(1 for item in field_summaries if item["changed"])
    risks = _build_portal_update_risks(normalized_table, field_summaries)

    return {
        "success": True,
        "component": {
            "table": normalized_table,
            "sys_id": params.sys_id,
            "name": str(current_record.get("name") or params.sys_id),
        },
        "edit_scope": {
            "requested_fields": list(normalized_update_data.keys()),
            "changed_fields": [item["field"] for item in field_summaries if item["changed"]],
            "unchanged_fields": [item["field"] for item in field_summaries if not item["changed"]],
            "changed_field_count": changed_field_count,
        },
        "field_analysis": field_summaries,
        "risk_level": _classify_portal_update_risk(risks, changed_field_count),
        "risks": risks,
        "recommended_flow": [
            "Run preview_portal_component_update to inspect bounded before/after diff.",
            "Apply with update_portal_component and confirm='approve' only after review.",
            "Validate the affected widget/page after apply.",
        ],
        "safety_notice": "Analysis only. No changes were applied.",
    }


@register_tool(
    "preview_portal_component_update",
    params=PreviewPortalComponentUpdateParams,
    description="Preview bounded before/after snippets and diff for a proposed portal component edit",
    serialization="raw_dict",
    return_type=dict,
)
def preview_portal_component_update(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: PreviewPortalComponentUpdateParams,
) -> Dict[str, Any]:
    normalized_table = _normalize_portal_component_table(params.table)
    normalized_update_data = _validate_portal_component_update_data(
        normalized_table, params.update_data
    )
    # full=True: the diff/length preview compares against the CURRENT body, so it
    # must be untruncated. The default path clips >50k fields (truncate_results) —
    # a context safeguard that would make a >50KB field's before/after diff bogus.
    # Display bounding still happens below (_summarize_text_preview / bounded diff).
    current_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        list(normalized_update_data.keys()),
        full=True,
    )

    preview_items: List[Dict[str, Any]] = []
    for field_name, proposed_value in normalized_update_data.items():
        current_value = str(current_record.get(field_name) or "")
        preview_items.append(
            {
                **_build_field_change_summary(field_name, current_value, proposed_value),
                "before_preview": _summarize_text_preview(current_value),
                "after_preview": _summarize_text_preview(proposed_value),
                "diff_preview": _build_diff_preview(current_value, proposed_value),
            }
        )

    return {
        "success": True,
        "component": {
            "table": normalized_table,
            "sys_id": params.sys_id,
            "name": str(current_record.get("name") or params.sys_id),
        },
        "preview": preview_items,
        "validation_plan": [
            "Review the bounded diff for each changed field.",
            "Confirm the target table/sys_id still points to the intended component.",
            "Apply only after review with confirm='approve'.",
        ],
        "safety_notice": "Preview only. Large values and diffs are intentionally truncated for context safety.",
    }


@register_tool(
    "route_portal_component_edit",
    params=RoutePortalComponentEditParams,
    description="Route a portal edit instruction to the right analyze/preview/apply tool.",
    serialization="raw_dict",
    return_type=dict,
)
def route_portal_component_edit(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: RoutePortalComponentEditParams,
) -> Dict[str, Any]:
    del config, auth_manager

    instruction = params.instruction.strip()
    action = _detect_portal_edit_action(instruction)
    suggested_fields = _detect_portal_edit_fields(instruction)
    plan = _build_portal_edit_router_plan(action, params)
    three_stage_flow = _build_portal_edit_three_stage_flow(
        action=action,
        params=params,
        suggested_fields=suggested_fields,
        final_plan=plan,
    )

    target: Dict[str, Any] = {}
    if params.table:
        try:
            target["table"] = _normalize_portal_component_table(params.table)
        except ValueError:
            target["table"] = params.table
    if params.sys_id:
        target["sys_id"] = params.sys_id

    return {
        "success": True,
        "instruction": instruction,
        "detected_action": action,
        "target": target,
        "suggested_fields": suggested_fields,
        "workflow_rule": "Always follow 3 stages: identify quickly, expand only the related set, then deep analyze/preview/apply only when needed.",
        "three_stage_flow": three_stage_flow,
        "tool_plan": plan,
        "recommended_next_call": _build_portal_edit_next_call_example(plan),
        "safety_notice": (
            "Routing only. This tool does not fetch, diff, or mutate remote data. "
            "Apply still requires explicit confirmation and complete arguments."
        ),
    }


@register_tool(
    "search_portal_regex_matches",
    params=SearchPortalRegexMatchesParams,
    description="True regex over portal code (widget/provider/SI), offsets+context. Server-table keyword search: search_server_code.",
    serialization="raw_dict",
    return_type=dict,
)
def search_portal_regex_matches(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: SearchPortalRegexMatchesParams,
) -> Dict[str, Any]:
    try:
        regex, resolved_pattern, effective_match_mode = _compile_search_pattern(
            params.regex, params.match_mode
        )
    except (re.error, ValueError) as exc:
        return {"success": False, "message": f"Invalid regex: {exc}", "matches": []}

    try:
        output_mode = _resolve_output_mode(params.output_mode, params.compact_output)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "matches": []}

    page_size = max(10, min(params.page_size, 100))
    max_widgets = _clamp_widget_review_limit(params.max_widgets)
    max_matches = _clamp_widget_review_matches(params.max_matches)
    snippet_length = _clamp_snippet_length(params.snippet_length)
    warnings = _portal_scan_warnings(
        requested_max_widgets=params.max_widgets,
        effective_max_widgets=max_widgets,
        requested_max_matches=params.max_matches,
        effective_max_matches=max_matches,
        include_linked_script_includes=params.include_linked_script_includes,
        include_linked_angular_providers=params.include_linked_angular_providers,
        widget_ids=params.widget_ids,
        provider_ids=params.provider_ids,
    )

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
        widget_query_parts.append(f"sys_scope.scope={_escape_query(params.scope)}")
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

    requested_widget_fields = set(params.include_widget_fields)
    # Only fetch heavy code fields that will actually be scanned
    widget_fields = ["sys_id", "name", "id"]
    scannable_code_fields = {"template", "script", "client_script", "link", "css"}
    widget_fields.extend(sorted(requested_widget_fields & scannable_code_fields))
    # Always include script fields when linked SI expansion needs them for ref extraction
    if params.include_linked_script_includes and "script_include" in source_type_set:
        for f in ("script", "client_script"):
            if f not in widget_fields:
                widget_fields.append(f)
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
    if "angular_provider" in source_type_set and len(matches) < max_matches:
        provider_ids: Set[str] = set()

        # Direct provider_ids filter — bypass M2M lookup
        if params.provider_ids:
            for pid in params.provider_ids:
                if isinstance(pid, str) and pid.strip():
                    provider_ids.add(_escape_query(pid.strip()))

        # M2M lookup from widgets (only when no direct provider_ids and widgets exist)
        if not params.provider_ids and params.include_linked_angular_providers and widget_ids:
            # Chunk size 30 — large `IN` clauses with 32-char sys_ids
            # blow past URL length limits and 400 on real instances.
            escaped_chunks = [
                [_escape_query(v) for v in chunk] for chunk in _chunked(widget_ids, 30)
            ]
            relation_rows = (
                _parallel_chunked_query(
                    config,
                    auth_manager,
                    table=ANGULAR_PROVIDER_M2M_TABLE,
                    chunks=escaped_chunks,
                    query_template="sp_widgetIN{ids}",
                    fields="sp_angular_provider",
                    page_size=page_size,
                    max_records=1000,
                )
                if not _table_known_absent(config, ANGULAR_PROVIDER_M2M_TABLE)
                else []
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
                fields="sys_id,name,script",
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
        script_include_rows = _fetch_linked_script_include_rows(
            config,
            auth_manager,
            candidates=sorted(script_include_candidates),
            page_size=page_size,
            scope=params.scope,
            updated_by=params.updated_by if params.linked_components_updated_by_only else None,
            updated_after=params.updated_after,
            updated_before=params.updated_before,
        )
        script_include_scanned = len(script_include_rows)
        for row in script_include_rows:
            remaining = max_matches - len(matches)
            if remaining <= 0:
                break
            content = str(row.get("script") or "")
            if not content:
                continue
            matches.extend(
                _extract_pattern_hits(
                    source_type="script_include",
                    source_sys_id=str(row.get("sys_id") or ""),
                    source_name=str(
                        row.get("name") or row.get("api_name") or row.get("sys_id") or ""
                    ),
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
            "match_mode": params.match_mode,
            "effective_match_mode": effective_match_mode,
            "resolved_pattern": resolved_pattern,
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
        "warnings": warnings,
        "safety_notice": "Returns concise line-level snippets only; full source bodies are intentionally excluded.",
    }


@register_tool(
    "trace_portal_route_targets",
    params=TracePortalRouteTargetsParams,
    description="Map widget→provider→route relationships. Metadata only, no script bodies.",
    serialization="raw_dict",
    return_type=dict,
)
def trace_portal_route_targets(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: TracePortalRouteTargetsParams,
) -> Dict[str, Any]:
    try:
        regex, resolved_pattern, effective_match_mode = _compile_search_pattern(
            params.regex, params.match_mode
        )
    except (re.error, ValueError) as exc:
        return {"success": False, "message": f"Invalid regex: {exc}", "traces": []}

    try:
        output_mode = _resolve_fixed_output_mode(params.output_mode)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "traces": []}

    page_size = max(10, min(params.page_size, 100))
    max_widgets = _clamp_widget_review_limit(params.max_widgets)
    max_traces = _clamp_widget_review_matches(params.max_traces)
    snippet_length = _clamp_snippet_length(params.snippet_length)
    warnings = _portal_scan_warnings(
        requested_max_widgets=params.max_widgets,
        effective_max_widgets=max_widgets,
        requested_max_matches=params.max_traces,
        effective_max_matches=max_traces,
        include_linked_angular_providers=params.include_linked_angular_providers,
        widget_ids=params.widget_ids,
        provider_ids=params.provider_ids,
    )

    widget_query_parts: List[str] = []
    if params.updated_by:
        widget_query_parts.append(f"sys_updated_by={_escape_query(params.updated_by)}")
    if params.scope:
        widget_query_parts.append(f"sys_scope.scope={_escape_query(params.scope)}")

    provider_filter_tokens = [
        _escape_query(value)
        for value in (params.provider_ids or [])
        if isinstance(value, str) and value.strip()
    ]
    provider_to_widget_ids: Set[str] = set()
    provider_lookup_rows: List[Dict[str, Any]] = []
    if provider_filter_tokens:
        provider_query = (
            "("
            + "^OR".join(
                [f"sys_id={token}" for token in provider_filter_tokens]
                + [f"name={token}" for token in provider_filter_tokens]
                + [f"id={token}" for token in provider_filter_tokens]
            )
            + ")"
        )
        provider_lookup_rows = _sn_query_all(
            config,
            auth_manager,
            table=ANGULAR_PROVIDER_TABLE,
            query=provider_query,
            fields="sys_id,name,id",
            page_size=page_size,
            max_records=100,
        )
        resolved_provider_ids = [
            str(row.get("sys_id") or "") for row in provider_lookup_rows if row.get("sys_id")
        ]
        if resolved_provider_ids:
            relation_rows = (
                _sn_query_all(
                    config,
                    auth_manager,
                    table=ANGULAR_PROVIDER_M2M_TABLE,
                    query=f"sp_angular_providerIN{','.join(resolved_provider_ids)}",
                    fields="sp_widget,sp_angular_provider",
                    page_size=page_size,
                    max_records=1000,
                )
                if not _table_known_absent(config, ANGULAR_PROVIDER_M2M_TABLE)
                else []
            )
            for row in relation_rows:
                widget_sys_id = _as_ref_sys_id(row.get("sp_widget"))
                if widget_sys_id:
                    provider_to_widget_ids.add(widget_sys_id)

    widget_tokens = [
        _escape_query(value)
        for value in (params.widget_ids or [])
        if isinstance(value, str) and value.strip()
    ]
    if provider_to_widget_ids or widget_tokens:
        combined_tokens = widget_tokens + sorted(provider_to_widget_ids)
        widget_query_parts.append(
            "("
            + "^OR".join(
                [f"sys_id={token}" for token in combined_tokens]
                + [f"id={token}" for token in widget_tokens]
                + [f"name={token}" for token in widget_tokens]
            )
            + ")"
        )

    # Only fetch heavy code fields that will actually be scanned
    widget_fields = ["sys_id", "name", "id"]
    trace_scannable_fields = {"template", "script", "client_script", "link"}
    requested_trace_fields = set(params.include_widget_fields)
    effective_widget_scan_fields = set(requested_trace_fields & trace_scannable_fields)
    if params.include_linked_angular_providers:
        effective_widget_scan_fields.add("template")
    widget_fields.extend(sorted(effective_widget_scan_fields))
    widget_rows = _sn_query_all(
        config,
        auth_manager,
        table=WIDGET_TABLE,
        query="^".join(widget_query_parts),
        fields=",".join(widget_fields),
        page_size=page_size,
        max_records=max_widgets,
    )

    widget_sys_ids = [str(row.get("sys_id") or "") for row in widget_rows if row.get("sys_id")]
    widget_name_by_id = {
        str(row.get("sys_id") or ""): str(
            row.get("name") or row.get("id") or row.get("sys_id") or ""
        )
        for row in widget_rows
        if row.get("sys_id")
    }

    widget_provider_map: Dict[str, List[str]] = {}
    if params.include_linked_angular_providers and widget_sys_ids:
        escaped_chunks = [
            [_escape_query(v) for v in chunk] for chunk in _chunked(widget_sys_ids, 100)
        ]
        relation_rows = (
            _parallel_chunked_query(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_M2M_TABLE,
                chunks=escaped_chunks,
                query_template="sp_widgetIN{ids}",
                fields="sp_widget,sp_angular_provider",
                page_size=page_size,
                max_records=1000,
            )
            if not _table_known_absent(config, ANGULAR_PROVIDER_M2M_TABLE)
            else []
        )
        for row in relation_rows:
            widget_sys_id = _as_ref_sys_id(row.get("sp_widget"))
            provider_sys_id = _as_ref_sys_id(row.get("sp_angular_provider"))
            if widget_sys_id and provider_sys_id:
                widget_provider_map.setdefault(widget_sys_id, [])
                if provider_sys_id not in widget_provider_map[widget_sys_id]:
                    widget_provider_map[widget_sys_id].append(provider_sys_id)

    all_provider_ids = sorted({pid for values in widget_provider_map.values() for pid in values})
    provider_rows: List[Dict[str, Any]] = []
    if all_provider_ids:
        provider_rows = _parallel_chunked_query(
            config,
            auth_manager,
            table=ANGULAR_PROVIDER_TABLE,
            chunks=_chunked(all_provider_ids, 100),
            query_template="sys_idIN{ids}",
            fields="sys_id,name,id,script",
            page_size=page_size,
            max_records=1000,
        )

    providers_by_id = {
        str(row.get("sys_id") or ""): row for row in provider_rows if row.get("sys_id")
    }

    requested_widget_fields = effective_widget_scan_fields
    traces: List[Dict[str, Any]] = []
    total_route_hits = 0
    widgets_with_hits = 0
    providers_with_hits: Set[str] = set()

    for widget in widget_rows:
        if len(traces) >= max_traces:
            break

        widget_sys_id = str(widget.get("sys_id") or "")
        widget_name = widget_name_by_id.get(widget_sys_id, widget_sys_id)
        widget_hits_raw: List[Dict[str, Any]] = []
        route_targets: List[str] = []
        branch_names: List[str] = []

        for field_name in ["template", "script", "client_script", "link"]:
            if field_name not in requested_widget_fields:
                continue
            content = str(widget.get(field_name) or "")
            if not content:
                continue
            hits = _extract_pattern_hits(
                source_type="widget",
                source_sys_id=widget_sys_id,
                source_name=widget_name,
                field_name=field_name,
                content=content,
                regex=regex,
                snippet_length=snippet_length,
                max_matches=max_traces,
            )
            for hit in hits:
                hit["context_name"] = _find_latest_function_context(
                    content, int(hit.get("offset") or 0)
                )
                route_targets.append(str(hit.get("match") or ""))
                if hit.get("context_name"):
                    branch_names.append(str(hit["context_name"]))
            widget_hits_raw.extend(hits)

        provider_matches: List[Dict[str, Any]] = []
        matched_provider_entries: List[Dict[str, Any]] = []
        linked_providers: List[Dict[str, str]] = []
        for provider_id in widget_provider_map.get(widget_sys_id, []):
            provider = providers_by_id.get(provider_id)
            if not provider:
                continue
            provider_name = str(provider.get("name") or provider.get("id") or provider_id)
            linked_providers.append({"sys_id": provider_id, "name": provider_name})
            script = str(provider.get("script") or "")
            if not script:
                continue
            hits = _extract_pattern_hits(
                source_type="angular_provider",
                source_sys_id=provider_id,
                source_name=provider_name,
                field_name="script",
                content=script,
                regex=regex,
                snippet_length=snippet_length,
                max_matches=max_traces,
            )
            if not hits:
                continue
            providers_with_hits.add(provider_id)
            matched_provider_entries.append({"sys_id": provider_id, "name": provider_name})
            for hit in hits:
                hit["context_name"] = _find_latest_function_context(
                    script, int(hit.get("offset") or 0)
                )
                hit["provider"] = {"sys_id": provider_id, "name": provider_name}
                route_targets.append(str(hit.get("match") or ""))
                if hit.get("context_name"):
                    branch_names.append(str(hit["context_name"]))
                provider_matches.append(_shape_trace_hit(hit, output_mode=output_mode))

        if not widget_hits_raw and not provider_matches:
            continue

        widgets_with_hits += 1
        total_route_hits += len(widget_hits_raw) + len(provider_matches)
        button_handlers = _extract_click_handlers(str(widget.get("template") or ""))
        evidence = [_shape_trace_hit(hit, output_mode=output_mode) for hit in widget_hits_raw]
        evidence.extend(provider_matches)

        route_summaries = []
        for target in _dedupe_preserve_order(route_targets):
            route_summaries.append(_route_target_summary(target))

        trace_row = {
            "widget": {
                "sys_id": widget_sys_id,
                "name": str(widget.get("name") or ""),
                "id": str(widget.get("id") or ""),
            },
            "route_targets": route_summaries,
            "service_names": _dedupe_preserve_order(
                [item["name"] for item in matched_provider_entries]
            ),
            "button_handlers": button_handlers,
            "branch_names": _dedupe_preserve_order(branch_names),
            "evidence": evidence[:max_traces],
            "matched_provider_count": len(matched_provider_entries),
            "matched_widget_field_count": len(widget_hits_raw),
            "provider_matches": provider_matches,
            "widget_matches": [
                _shape_trace_hit(hit, output_mode=output_mode) for hit in widget_hits_raw
            ],
            "linked_providers": linked_providers,
        }
        traces.append(_shape_route_trace(trace_row, output_mode=output_mode))

    return {
        "success": True,
        "filters": {
            "regex": params.regex,
            "match_mode": params.match_mode,
            "effective_match_mode": effective_match_mode,
            "resolved_pattern": resolved_pattern,
            "updated_by": params.updated_by,
            "scope": params.scope,
            "widget_ids": params.widget_ids,
            "provider_ids": params.provider_ids,
            "include_linked_angular_providers": params.include_linked_angular_providers,
            "include_widget_fields": params.include_widget_fields,
            "output_mode": output_mode,
        },
        "summary": {
            "widgets_scanned": len(widget_rows),
            "widgets_with_hits": widgets_with_hits,
            "linked_angular_providers_scanned": len(provider_rows),
            "providers_with_hits": len(providers_with_hits),
            "trace_count": len(traces),
            "route_hit_count": total_route_hits,
            "max_widgets": max_widgets,
            "max_traces": max_traces,
        },
        "traces": traces,
        "warnings": warnings,
        "safety_notice": "Trace rows are condensed for LLM consumption. Use get_portal_component_code only when a returned evidence row needs full source inspection.",
    }


@register_tool(
    "detect_angular_implicit_globals",
    params=DetectAngularImplicitGlobalsParams,
    description="Detect undeclared variable assignments in Angular provider scripts that cause runtime 'not defined' errors.",
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
    warnings = _portal_scan_warnings(
        requested_max_widgets=params.max_providers,
        effective_max_widgets=max_providers,
        requested_max_matches=params.max_matches,
        effective_max_matches=max_matches,
        provider_ids=params.provider_ids,
    )

    query_parts: List[str] = []
    if params.updated_by:
        query_parts.append(f"sys_updated_by={_escape_query(params.updated_by)}")
    if params.scope:
        query_parts.append(f"sys_scope.scope={_escape_query(params.scope)}")
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
        fields="sys_id,name,id,script",
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
        "warnings": warnings,
        "safety_notice": "Findings are static-analysis heuristics; verify before patching provider scripts.",
    }


def update_portal_component(
    config: ServerConfig, auth_manager: AuthManager, params: UpdatePortalComponentParams
) -> Dict[str, Any]:
    """Pinpoint update of specific portal component fields."""
    normalized_table = _normalize_portal_component_table(params.table)
    normalized_update_data = _validate_portal_component_update_data(
        normalized_table, params.update_data
    )
    fetch_fields = list(normalized_update_data.keys())
    if params.base_updated_on:
        fetch_fields = _dedupe_fields([*fetch_fields, "sys_updated_on"])
    # sys_policy rides the fetch we already do (0 extra API) for the pre-flight
    # protection check below.
    fetch_fields = _dedupe_fields([*fetch_fields, "sys_policy"])
    current_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        fetch_fields,
    )

    # Pre-flight advisories (NON-blocking). The server is the authority on whether
    # a write is allowed — we do NOT pre-refuse on our own guess. sys_policy='read'
    # means "protected", which limits the API but NOT necessarily this caller in
    # this scope/context (the same record is editable in the UI). So we WARN and
    # let the server decide; a real rejection comes back as the 403 below.
    pre_flight_warnings: List[str] = []
    if str(current_record.get("sys_policy") or "").strip().lower() == "read":
        pre_flight_warnings.append(
            "Record is Protected (sys_policy='read'): protection limits the API, not your "
            "UI/Studio edit. Attempting the write anyway — if ServiceNow rejects it (403), "
            "edit it directly in the UI/Studio (no unprotect needed)."
        )
    # Editing an sp_widget SERVER script is gated by the SP Designer source-context
    # check on some instances (works on one, 403s on another with identical roles).
    if normalized_table == "sp_widget" and "script" in normalized_update_data:
        pre_flight_warnings.append(
            "Editing the sp_widget SERVER script ('script'). Some instances gate this "
            "behind the SP Designer source-context check and reject the Table API write "
            "(403) even with sp_admin — if that happens, edit the widget in SP Designer."
        )

    # Conflict check: remote was modified after the caller's last read.
    if params.base_updated_on and not params.force:
        remote_updated_on = str(current_record.get("sys_updated_on") or "")
        if remote_updated_on and remote_updated_on > params.base_updated_on:
            return {
                "error": "CONFLICT",
                "message": (
                    "Remote has been modified since you last read this record. "
                    "Re-read the component and reapply your changes, "
                    "or pass force=true to override."
                ),
                "remote_updated_on": remote_updated_on,
                "base_updated_on": params.base_updated_on,
                "component": {
                    "table": normalized_table,
                    "sys_id": params.sys_id,
                },
            }

    effective_update_data = {
        field_name: proposed_value
        for field_name, proposed_value in normalized_update_data.items()
        if str(current_record.get(field_name) or "") != proposed_value
    }

    if not effective_update_data:
        return {
            "message": "No changes applied",
            "sys_id": params.sys_id,
            "fields": list(normalized_update_data.keys()),
            "validation": {
                "skipped": True,
                "reason": "Proposed values already match the current record.",
            },
        }

    size_warnings = []
    for field_name, value in effective_update_data.items():
        field_bytes = len(value.encode("utf-8"))
        if field_bytes > 500_000:
            size_warnings.append(
                f"Field '{field_name}' is {field_bytes:,} bytes ({field_bytes // 1024}KB). "
                f"Large payloads may be rejected by proxy/WAF."
            )

    instance_url = config.instance_url
    url = f"{instance_url}/api/now/table/{normalized_table}/{params.sys_id}"

    headers = auth_manager.get_headers()
    response = auth_manager.make_request("PATCH", url, json=effective_update_data, headers=headers)

    if response.status_code >= 400:
        error_dict: Dict[str, Any] = {
            "error": f"Update failed: {response.text}",
            "status": response.status_code,
        }
        if pre_flight_warnings:
            error_dict["pre_flight_warnings"] = pre_flight_warnings
        return error_dict

    invalidate_query_cache(table=normalized_table)

    validated_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        list(effective_update_data.keys()),
        full=True,
    )
    verified_fields: List[str] = []
    mismatched_fields: List[Dict[str, Any]] = []
    for field_name, proposed_value in effective_update_data.items():
        actual_value = str(validated_record.get(field_name) or "")
        if actual_value == proposed_value:
            verified_fields.append(field_name)
        else:
            mismatched_fields.append(
                {
                    "field": field_name,
                    "expected_preview": _summarize_text_preview(proposed_value, 240),
                    "actual_preview": _summarize_text_preview(actual_value, 240),
                }
            )

    result_dict = {
        "message": "Update successful",
        "sys_id": params.sys_id,
        "fields": list(effective_update_data.keys()),
        "validation": {
            "verified_fields": verified_fields,
            "mismatched_fields": mismatched_fields,
            "post_update_name": str(validated_record.get("name") or params.sys_id),
        },
    }
    if size_warnings:
        result_dict["size_warnings"] = size_warnings
    if pre_flight_warnings:
        result_dict["pre_flight_warnings"] = pre_flight_warnings
    return result_dict


@register_tool(
    "download_portal_sources",
    params=DownloadPortalSourcesParams,
    description="Targeted portal widgets/providers. Whole app: download_app_sources. widget_ids=one widget.",
    serialization="raw_dict",
    return_type=dict,
)
def download_portal_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadPortalSourcesParams,
    *,
    emit_phases: bool = True,
) -> Dict[str, Any]:
    # emit_phases=False when called as the "portal" sub-stage of
    # download_app_sources: that orchestrator owns a per-STAGE progress counter,
    # and letting these phase ticks (1,2,3) interleave with it would make the
    # stream non-monotonic. Standalone (the registered tool) keeps phases on.
    # Canonicalize the scope to its namespace so the folder/query are
    # deterministic even when a display name or sys_id is passed.
    params, scope_resolution = apply_scope_namespace(config, auth_manager, params)
    scope_name = _safe_name(params.scope or "global")
    if params.output_dir:
        # output_dir is the final scope root — no auto-appending of instance/scope
        # to avoid duplicated nesting like temp/inst/x_app/inst/x_app.
        scope_root = Path(params.output_dir).expanduser().resolve()
        root = scope_root.parent
    else:
        # Default: ./temp/{instance}/{scope}/.
        instance_name = _get_instance_name(config)
        root = Path.cwd() / "temp" / instance_name
        scope_root = root / scope_name
    root.mkdir(parents=True, exist_ok=True)
    scope_root.mkdir(parents=True, exist_ok=True)
    # Remember where downloads actually land (default OR caller's output_dir)
    # so offline surfaces look at the user's real roots, not an assumed ./temp.
    record_download_root(scope_root)
    max_widgets = _clamp_download_widget_limit(params.max_widgets)
    targeted_widget_export = bool(params.widget_ids)
    include_linked_script_includes = (
        params.include_linked_script_includes
        if params.include_linked_script_includes is not None
        else targeted_widget_export
    )
    include_linked_angular_providers = (
        params.include_linked_angular_providers
        if params.include_linked_angular_providers is not None
        else targeted_widget_export
    )
    warnings = _portal_scan_warnings(
        requested_max_widgets=params.max_widgets,
        effective_max_widgets=max_widgets,
        include_linked_script_includes=include_linked_script_includes,
        include_linked_angular_providers=include_linked_angular_providers,
        widget_ids=params.widget_ids,
    )
    instance_name = _get_instance_name(config)
    g_ck = str(getattr(auth_manager, "_browser_session_token", "") or "")

    # Content-aware source writes (two-copy via utils/sync_anchor.py): a local file
    # carrying YOUR edits is never silently overwritten — kept as-is when the server
    # is unmoved, kept + an always-fresh '<field>.remote' server mirror on a true
    # conflict. Components left out-of-sync keep their PRIOR sync watermark so a
    # later push still flags the conflict. Legacy trees (no sha anchor) keep the
    # historical overwrite behavior.
    conflict_files: List[str] = []
    kept_edit_files: List[str] = []
    refreshed_files: List[str] = []
    out_of_sync_keys: Set[Tuple[str, str]] = set()

    # Prior per-field content-sha anchors, read once from the on-disk _sync_meta so
    # reconcile can tell YOUR edits from server changes with no frozen snapshot.
    _prior_shas: Dict[Tuple[str, str], Dict[str, str]] = {}
    for _tbl in ("sp_widget", "sp_angular_provider", "sys_script_include"):
        for _key, _entry in read_download_map(scope_root / _tbl / "_sync_meta.json").items():
            if isinstance(_entry, dict) and _entry.get("field_shas"):
                _prior_shas[(_tbl, _key)] = _entry["field_shas"]

    def _sync_source_file(table: str, meta_key: str, fpath: Path, content: str) -> None:
        field = _FILENAME_FIELD.get(fpath.name, fpath.stem)
        stored_sha = _prior_shas.get((table, meta_key), {}).get(field, "")
        outcome, _sha = reconcile_field(fpath, content, stored_sha, legacy_overwrite=True)
        sweep_legacy_baseline(fpath.parent)  # self-tidy any pre-anchor _baseline/
        label = f"{table}/{fpath.parent.name}/{fpath.name}"
        if outcome == CONFLICT_MIRRORED:
            conflict_files.append(label)
            out_of_sync_keys.add((table, meta_key))
        elif outcome == KEPT_LOCAL:
            kept_edit_files.append(label)
            out_of_sync_keys.add((table, meta_key))
        elif outcome == REFRESHED:
            refreshed_files.append(label)

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
        widget_base_query = f"sys_scope.scope={_escape_query(params.scope)}"
    # Incremental (full-scope only): pull just records changed since last sync.
    incremental_active = params.incremental and not targeted_widget_export
    if incremental_active:
        widget_watermark = max_sync_updated_on(scope_root / "sp_widget" / "_sync_meta.json")
        if widget_watermark:
            clause = f"sys_updated_on>={_escape_query(widget_watermark)}"
            widget_base_query = f"{widget_base_query}^{clause}" if widget_base_query else clause
    widget_fields = _download_widget_fields(
        include_widget_template=params.include_widget_template,
        include_widget_server_script=params.include_widget_server_script,
        include_widget_client_script=params.include_widget_client_script,
        include_widget_link_script=params.include_widget_link_script,
        include_widget_css=params.include_widget_css,
        include_linked_script_includes=include_linked_script_includes,
    )

    widgets: List[Dict[str, Any]] = []
    missing_widget_tokens: List[str] = []
    try:
        if params.widget_ids:
            widgets, missing_widget_tokens = _fetch_targeted_widget_rows(
                config,
                auth_manager,
                widget_tokens=params.widget_ids,
                widget_base_query=widget_base_query,
                widget_fields=widget_fields,
                page_size=params.page_size,
            )
        else:
            widgets = _sn_query_all(
                config,
                auth_manager,
                table=WIDGET_TABLE,
                query=widget_base_query,
                fields=widget_fields,
                page_size=params.page_size,
                max_records=max_widgets,
                fail_silently=False,
            )
    except Exception as _widget_exc:
        return {
            "success": False,
            "error": f"Widget fetch failed: {_widget_exc}",
            "summary": {"widgets": 0, "angular_providers": 0, "script_includes": 0},
            "warnings": warnings,
        }

    if missing_widget_tokens:
        warnings.extend(
            _locate_missing_widget_tokens(
                config,
                auth_manager,
                missing_tokens=missing_widget_tokens,
                requested_scope=params.scope,
                page_size=params.page_size,
            )
        )

    # Completeness guard: a full-scope fetch returning exactly max_widgets means
    # the scope holds at least that many and some were left behind. Surface it —
    # a silent widget cap yields an incomplete tree that analysis can't trust.
    widgets_capped = not targeted_widget_export and len(widgets) >= max_widgets
    if widgets_capped:
        warnings.append(
            f"INCOMPLETE — fetched {len(widgets)} widgets, which equals the max_widgets cap "
            f"({max_widgets}). The scope likely has more that were NOT downloaded. Re-run with a "
            f"higher max_widgets to capture everything."
        )

    widget_map: Dict[str, str] = {}
    exported_widgets: List[Dict[str, str]] = []
    script_include_candidates: List[str] = []
    scope_sys_ids: Dict[str, str] = {}

    dictionary_by_field: Dict[str, Dict[str, Any]] = {}

    # Perceived-speed: announce each phase as it starts (no-op unless the tool is
    # progress-whitelisted). Indeterminate total — phase counts are dynamic.
    if emit_phases:
        emit_progress(1, None, f"portal: writing {len(widgets)} widgets")
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
            _sync_source_file(
                "sp_widget",
                widget_id,
                widget_dir / "template.html",
                str(widget.get("template") or ""),
            )
        if params.include_widget_server_script:
            _sync_source_file(
                "sp_widget", widget_id, widget_dir / "script.js", str(widget.get("script") or "")
            )
        if params.include_widget_client_script:
            _sync_source_file(
                "sp_widget",
                widget_id,
                widget_dir / "client_script.js",
                str(widget.get("client_script") or ""),
            )
        if params.include_widget_link_script:
            _sync_source_file(
                "sp_widget", widget_id, widget_dir / "link.js", str(widget.get("link") or "")
            )
        if params.include_widget_css:
            _sync_source_file(
                "sp_widget", widget_id, widget_dir / "css.scss", str(widget.get("css") or "")
            )

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

    merge_map_file(
        scope_root / "sp_widget" / "_map.json",
        widget_map,
        writer=_write_json_file,
        label="sp_widget",
    )
    _now_iso = datetime.now(UTC).isoformat()
    _widget_sync_meta: Dict[str, Dict[str, str]] = {}
    for widget in widgets:
        _wid = str(widget.get("id") or widget.get("name") or widget.get("sys_id") or "")
        # Out-of-sync widgets (kept local edits / conflicts) keep their PRIOR
        # watermark so a later push still flags the conflict.
        if _wid and ("sp_widget", _wid) not in out_of_sync_keys:
            _widget_sync_meta[_wid] = {
                "sys_id": str(widget.get("sys_id") or ""),
                "sys_updated_on": str(widget.get("sys_updated_on") or ""),
                "sys_updated_by": str(widget.get("sys_updated_by") or ""),
                "sys_mod_count": str(widget.get("sys_mod_count") or ""),
                "field_shas": _portal_field_shas(
                    widget, ("template", "script", "client_script", "css", "link")
                ),
                "downloaded_at": _now_iso,
            }
    merge_map_file(
        scope_root / "sp_widget" / "_sync_meta.json",
        _widget_sync_meta,
        writer=_write_json_file,
        label="sp_widget_sync_meta",
    )

    provider_map: Dict[str, str] = {}
    provider_name_by_sys_id: Dict[str, str] = {}
    _provider_sync_meta: Dict[str, Dict[str, str]] = {}
    exported_providers: List[Dict[str, str]] = []
    # widget sys_id -> [provider sys_id] from the authoritative M2M (not code text)
    widget_provider_edges_by_sys_id: Dict[str, List[str]] = {}
    if include_linked_angular_providers and (widgets or incremental_active):
        widget_sys_ids = [str(w.get("sys_id")) for w in widgets if w.get("sys_id")]
        m2m_ids: List[str] = []
        m2m_available = not _table_known_absent(config, ANGULAR_PROVIDER_M2M_TABLE)
        for sys_id_chunk in _chunked(widget_sys_ids, 100) if m2m_available else []:
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
                widget_ref_id = _as_ref_sys_id(row.get("sp_widget"))
                if provider_id and provider_id not in m2m_ids:
                    m2m_ids.append(provider_id)
                if widget_ref_id and provider_id:
                    edge = widget_provider_edges_by_sys_id.setdefault(widget_ref_id, [])
                    if provider_id not in edge:
                        edge.append(provider_id)

        # Incremental: catch providers whose script changed without a widget edit
        # (M2M-by-widget can't see those). Independent watermark query on providers.
        if incremental_active:
            provider_watermark = max_sync_updated_on(
                scope_root / "sp_angular_provider" / "_sync_meta.json"
            )
            if provider_watermark:
                provider_delta_query = f"sys_updated_on>={_escape_query(provider_watermark)}"
                if params.scope:
                    provider_delta_query += f"^sys_scope.scope={_escape_query(params.scope)}"
                for row in _sn_query_all(
                    config,
                    auth_manager,
                    table=ANGULAR_PROVIDER_TABLE,
                    query=provider_delta_query,
                    fields="sys_id",
                    page_size=params.page_size,
                    max_records=1000,
                ):
                    pid = str(row.get("sys_id") or "")
                    if pid and pid not in m2m_ids:
                        m2m_ids.append(pid)

        if m2m_ids:
            if emit_phases:
                emit_progress(2, None, "portal: linked angular providers")
            # Fetch provider metadata first (no script — lightweight)
            provider_rows = _sn_query_all(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_TABLE,
                query=f"sys_idIN{','.join(m2m_ids)}",
                fields="sys_id,name,type,sys_scope,sys_updated_on,sys_updated_by,sys_mod_count",
                page_size=100,
                max_records=1000,
            )
            # Pre-fetch each provider's script CONCURRENTLY — still one record per
            # request (no bulk IN, so large scripts never truncate) but parallel
            # instead of one sequential round-trip per provider.
            provider_scripts = _fetch_field_by_sys_id_parallel(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_TABLE,
                sys_ids=[str(p.get("sys_id") or "") for p in provider_rows],
                field="script",
            )
            for provider in provider_rows:
                name = str(provider.get("name") or provider.get("sys_id") or "")
                sys_id = str(provider.get("sys_id") or "")
                file_name = _safe_name(name)
                script = provider_scripts.get(sys_id, "")
                if script.strip():
                    # Folder layout (<table>/<name>/script.js) — same as the
                    # generic downloader and what the uploader reads. See
                    # source_layout for why this must not be a flat file.
                    _sync_source_file(
                        "sp_angular_provider",
                        name,
                        scope_root / "sp_angular_provider" / file_name / field_filename("script"),
                        script,
                    )
                if name:
                    provider_map[name] = sys_id
                    if ("sp_angular_provider", name) not in out_of_sync_keys:
                        _provider_sync_meta[name] = {
                            "sys_id": sys_id,
                            "sys_updated_on": str(provider.get("sys_updated_on") or ""),
                            "sys_updated_by": str(provider.get("sys_updated_by") or ""),
                            "sys_mod_count": str(provider.get("sys_mod_count") or ""),
                            "field_shas": _portal_field_shas(provider, ("script",)),
                            "downloaded_at": _now_iso,
                        }
                if sys_id:
                    provider_name_by_sys_id[sys_id] = name or sys_id
                exported_providers.append({"name": name, "sys_id": sys_id})

    merge_map_file(
        scope_root / "sp_angular_provider" / "_map.json",
        provider_map,
        writer=_write_json_file,
        label="sp_angular_provider",
    )
    merge_map_file(
        scope_root / "sp_angular_provider" / "_sync_meta.json",
        _provider_sync_meta,
        writer=_write_json_file,
        label="sp_angular_provider_sync_meta",
    )

    # Persist authoritative widget->provider edges (name-keyed) so audit/offline
    # tools read the real M2M graph instead of re-deriving it from code text.
    widget_name_by_sys_id = {
        str(w.get("sys_id") or ""): str(w.get("name") or w.get("id") or w.get("sys_id") or "")
        for w in widgets
        if w.get("sys_id")
    }
    widget_to_providers: Dict[str, List[str]] = {}
    for widget_sid, provider_sids in widget_provider_edges_by_sys_id.items():
        widget_label = widget_name_by_sys_id.get(widget_sid)
        if not widget_label:
            continue
        provider_names = sorted(
            {
                provider_name_by_sys_id[pid]
                for pid in provider_sids
                if pid in provider_name_by_sys_id
            }
        )
        if provider_names:
            widget_to_providers[widget_label] = provider_names
    if widget_to_providers:
        merge_map_file(
            scope_root / "_graph.json",
            widget_to_providers,
            writer=_write_json_file,
            label="widget_provider_graph",
        )

    # Authoritative widget -> CSS/JS dependency edges (m2m_sp_widget_dependency ->
    # sp_dependency), captured at download so offline analysis reads the real
    # relationship graph instead of guessing from code. Fully fail-safe: chunked,
    # capped, and wrapped — a denied/empty dependency table never breaks the
    # download (this metadata is additive, not load-bearing).
    dependency_edge_count = 0
    if widgets:
        try:
            dep_widget_sys_ids = [str(w.get("sys_id")) for w in widgets if w.get("sys_id")]
            widget_dep_edges: Dict[str, List[str]] = {}
            dep_ids: List[str] = []
            for sys_id_chunk in _chunked(dep_widget_sys_ids, 100):
                for row in _sn_query_all(
                    config,
                    auth_manager,
                    table=WIDGET_DEPENDENCY_TABLE,
                    query=f"sp_widgetIN{','.join(_escape_query(v) for v in sys_id_chunk)}",
                    fields="sp_widget,sp_dependency",
                    page_size=params.page_size,
                    max_records=500,
                ):
                    dep_id = _as_ref_sys_id(row.get("sp_dependency"))
                    widget_ref_id = _as_ref_sys_id(row.get("sp_widget"))
                    if dep_id and dep_id not in dep_ids:
                        dep_ids.append(dep_id)
                    if widget_ref_id and dep_id:
                        edge = widget_dep_edges.setdefault(widget_ref_id, [])
                        if dep_id not in edge:
                            edge.append(dep_id)
            dep_name_by_sys_id: Dict[str, str] = {}
            for id_chunk in _chunked(dep_ids, 100):
                for row in _sn_query_all(
                    config,
                    auth_manager,
                    table=DEPENDENCY_TABLE,
                    query=f"sys_idIN{','.join(id_chunk)}",
                    fields="sys_id,name",
                    page_size=100,
                    max_records=1000,
                ):
                    sid = str(row.get("sys_id") or "")
                    if sid:
                        dep_name_by_sys_id[sid] = str(row.get("name") or sid)
            widget_to_deps: Dict[str, List[str]] = {}
            for widget_sid, dep_sids in widget_dep_edges.items():
                widget_label = widget_name_by_sys_id.get(widget_sid)
                if not widget_label:
                    continue
                dep_names = sorted({dep_name_by_sys_id.get(d, d) for d in dep_sids})
                if dep_names:
                    widget_to_deps[widget_label] = dep_names
            if widget_to_deps:
                merge_map_file(
                    scope_root / "_dependency_graph.json",
                    widget_to_deps,
                    writer=_write_json_file,
                    label="widget_dependency_graph",
                )
                dependency_edge_count = sum(len(v) for v in widget_to_deps.values())
        except Exception as _dep_exc:
            warnings.append(f"dependency graph: capture failed (non-fatal): {_dep_exc}")

    si_map: Dict[str, str] = {}
    _si_sync_meta: Dict[str, Dict[str, str]] = {}
    exported_script_includes: List[Dict[str, str]] = []
    if include_linked_script_includes and script_include_candidates:
        if emit_phases:
            emit_progress(3, None, "portal: linked script includes")
        script_include_rows = _fetch_linked_script_include_rows(
            config,
            auth_manager,
            candidates=script_include_candidates,
            page_size=params.page_size,
            scope=params.scope,
        )
        for row in script_include_rows:
            name = str(row.get("name") or row.get("api_name") or row.get("sys_id") or "")
            sys_id = str(row.get("sys_id") or "")
            file_name = _safe_name(name)
            # Folder layout (<table>/<name>/script.js) — match the generic
            # downloader and the uploader. See source_layout.
            _sync_source_file(
                "sys_script_include",
                name,
                scope_root / "sys_script_include" / file_name / field_filename("script"),
                str(row.get("script") or ""),
            )
            si_map[name] = sys_id
            if ("sys_script_include", name) not in out_of_sync_keys:
                _si_sync_meta[name] = {
                    "sys_id": sys_id,
                    "sys_updated_on": str(row.get("sys_updated_on") or ""),
                    "sys_updated_by": str(row.get("sys_updated_by") or ""),
                    "sys_mod_count": str(row.get("sys_mod_count") or ""),
                    "field_shas": _portal_field_shas(row, ("script",)),
                    "downloaded_at": _now_iso,
                }
            exported_script_includes.append(
                {
                    "name": name,
                    "sys_id": sys_id,
                    "api_name": str(row.get("api_name") or ""),
                }
            )

    merge_map_file(
        scope_root / "sys_script_include" / "_map.json",
        si_map,
        writer=_write_json_file,
        label="sys_script_include",
    )
    merge_map_file(
        scope_root / "sys_script_include" / "_sync_meta.json",
        _si_sync_meta,
        writer=_write_json_file,
        label="sys_script_include_sync_meta",
    )
    _write_json_file(root / "scopes.json", scope_sys_ids)

    # Deletion reconcile (warn-only): widgets present locally but gone remotely.
    deleted_widget_candidates: List[str] = []
    if params.reconcile_deletions and not targeted_widget_export:
        local_ids = map_sys_ids(scope_root / "sp_widget" / "_map.json")
        if local_ids:
            remote_ids = {
                str(r.get("sys_id") or "")
                for r in _sn_query_all(
                    config,
                    auth_manager,
                    table=WIDGET_TABLE,
                    query=(
                        f"sys_scope.scope={_escape_query(params.scope)}" if params.scope else ""
                    ),
                    fields="sys_id",
                    page_size=params.page_size,
                    max_records=max_widgets,
                )
                if r.get("sys_id")
            }
            deleted_widget_candidates = sorted(local_ids - remote_ids)
            if deleted_widget_candidates:
                warnings.append(
                    "reconcile: "
                    f"{len(deleted_widget_candidates)} local widget(s) no longer exist remotely "
                    "(deletion candidates — not removed automatically): "
                    + ", ".join(deleted_widget_candidates[:20])
                )

    if conflict_files:
        shown = ", ".join(conflict_files[:10])
        more = "" if len(conflict_files) <= 10 else f" (+{len(conflict_files) - 10} more)"
        warnings.append(
            f"CONFLICT — {len(conflict_files)} file(s) have BOTH your local edits and newer "
            f"server changes. Your files were kept; the server's version was saved next to each "
            f"as '<field>.remote.<ext>'. Merge, then push (or delete the sidecar to discard the "
            f"server's change): {shown}{more}"
        )
    if kept_edit_files:
        shown = ", ".join(kept_edit_files[:10])
        more = "" if len(kept_edit_files) <= 10 else f" (+{len(kept_edit_files) - 10} more)"
        warnings.append(
            f"kept your local edits on {len(kept_edit_files)} file(s) (server copy unchanged "
            f"since your last download/push): {shown}{more}"
        )
    if refreshed_files:
        shown = ", ".join(refreshed_files[:10])
        more = "" if len(refreshed_files) <= 10 else f" (+{len(refreshed_files) - 10} more)"
        warnings.append(
            f"auto-refreshed {len(refreshed_files)} local file(s) you had not edited but the "
            f"server had updated: {shown}{more}"
        )

    if incremental_active:
        warnings.append(
            "incremental: only records with a newer sys_updated_on were fetched; "
            "unchanged local files were preserved. Run a full download periodically."
        )

    result: Dict[str, Any] = {
        "success": True,
        "output_root": str(scope_root),
        "incremental": incremental_active,
        "deleted_widget_candidates": deleted_widget_candidates,
        "summary": {
            "widgets": len(exported_widgets),
            "angular_providers": len(exported_providers),
            "script_includes": len(exported_script_includes),
            "dependency_edges": dependency_edge_count,
        },
        "warnings": warnings,
        "widget_map_path": str(scope_root / "sp_widget" / "_map.json"),
        "angular_provider_map_path": str(scope_root / "sp_angular_provider" / "_map.json"),
        "script_include_map_path": str(scope_root / "sys_script_include" / "_map.json"),
        "safety_notice": "Exports structured source files only; no destructive remote operations are performed.",
    }
    if targeted_widget_export:
        result["missing_widget_ids"] = missing_widget_tokens
    if scope_resolution:
        result["scope_resolution"] = scope_resolution
    return result


# ---------------------------------------------------------------------------
# Deep Analysis: Resolve full dependency chain with source code
# ---------------------------------------------------------------------------

MAX_CHAIN_DEPTH = 3
MAX_CHAIN_WIDGETS = 15
MAX_CHAIN_PROVIDERS = 50
MAX_CHAIN_SI = 30
MAX_SOURCE_CHARS_PER_FIELD = 15000


class ResolveWidgetChainParams(BaseModel):
    """Parameters for deep dependency chain resolution."""

    widget_id: str = Field(
        ...,
        description="Starting widget sys_id, id, or name",
    )
    depth: int = Field(
        default=2,
        description="Resolution depth: 1=widget only, 2=+providers, 3=+script includes (max 3)",
    )
    include_fields: List[str] = Field(
        default=["script", "client_script", "template"],
        description="Widget fields to include. Options: script, client_script, template, css, link",
    )
    max_source_length: int = Field(
        default=MAX_SOURCE_CHARS_PER_FIELD,
        description="Max chars per source field. 0 for unlimited (use with caution).",
    )


def _truncate_source(text: str, max_len: int) -> str:
    if max_len <= 0 or len(text) <= max_len:
        return text
    return text[:max_len] + f"\n... [TRUNCATED at {max_len} chars, total {len(text)}]"


# NOTE: de-registered as a standalone tool — now an internal resolver invoked
# by manage_widget_dependency (get/list with include_source). Kept importable
# so its tested behavior is preserved. See widget_dependency_tools.py.
def resolve_widget_chain(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ResolveWidgetChainParams,
) -> Dict[str, Any]:
    """Resolve widget → providers → script includes with full source code."""
    depth = min(max(1, params.depth), MAX_CHAIN_DEPTH)
    max_src = params.max_source_length
    result: Dict[str, Any] = {"depth": depth, "api_calls": 0}

    # --- Step 1: Fetch the widget with full source ---
    widget_fields = ["sys_id", "name", "id", "sys_scope", "sys_updated_on", "sys_updated_by"]
    widget_fields.extend(f for f in params.include_fields if f not in widget_fields)

    query = f"sys_id={params.widget_id}^ORid={params.widget_id}^ORname={params.widget_id}"
    try:
        w_resp = sn_query(
            config,
            auth_manager,
            GenericQueryParams(
                table=WIDGET_TABLE,
                query=query,
                fields=",".join(widget_fields),
                limit=1,
                offset=0,
                display_value=False,
            ),
        )
        result["api_calls"] += 1
    except Exception as exc:
        return {"success": False, "error": f"Failed to fetch widget: {exc}"}

    if not w_resp.get("success") or not w_resp.get("results"):
        return {"success": False, "error": f"Widget '{params.widget_id}' not found."}

    widget = w_resp["results"][0]
    # Truncate source fields
    for f in params.include_fields:
        if f in widget and isinstance(widget[f], str):
            widget[f] = _truncate_source(widget[f], max_src)

    result["widget"] = widget
    result["providers"] = []
    result["script_includes"] = []

    if depth < 2:
        result["success"] = True
        return result

    # --- Step 2: Fetch linked Angular Providers with full script ---
    widget_sys_id = widget.get("sys_id", "")
    m2m_resp: Dict[str, Any] = {"results": []}
    if not _table_known_absent(config, ANGULAR_PROVIDER_M2M_TABLE):
        try:
            m2m_resp = sn_query(
                config,
                auth_manager,
                GenericQueryParams(
                    table=ANGULAR_PROVIDER_M2M_TABLE,
                    query=f"sp_widget={widget_sys_id}",
                    fields="sp_angular_provider",
                    limit=100,
                    offset=0,
                    display_value=False,
                ),
            )
            _note_table_response(config, ANGULAR_PROVIDER_M2M_TABLE, m2m_resp)
            result["api_calls"] += 1
        except Exception as exc:
            result["warnings"] = [f"Failed to fetch provider M2M: {exc}"]
            result["success"] = True
            return result

    provider_ids = []
    for row in m2m_resp.get("results", []):
        pid = _as_ref_sys_id(row.get("sp_angular_provider"))
        if pid:
            provider_ids.append(pid)

    if provider_ids:
        provider_ids = provider_ids[:MAX_CHAIN_PROVIDERS]
        try:
            prov_resp = sn_query(
                config,
                auth_manager,
                GenericQueryParams(
                    table=ANGULAR_PROVIDER_TABLE,
                    query=f"sys_idIN{','.join(provider_ids)}",
                    fields="sys_id,name,type,script,client_script",
                    limit=MAX_CHAIN_PROVIDERS,
                    offset=0,
                    display_value=False,
                ),
            )
            result["api_calls"] += 1
        except Exception as exc:
            result["warnings"] = [f"Failed to fetch providers: {exc}"]
            result["success"] = True
            return result

        for prov in prov_resp.get("results", []):
            if "script" in prov and isinstance(prov["script"], str):
                prov["script"] = _truncate_source(prov["script"], max_src)
            if "client_script" in prov and isinstance(prov["client_script"], str):
                prov["client_script"] = _truncate_source(prov["client_script"], max_src)
            result["providers"].append(prov)

    if depth < 3:
        result["success"] = True
        return result

    # --- Step 3: Extract Script Include references and fetch bodies ---
    si_names: Set[str] = set()
    # Scan widget server script for SI references
    widget_script = widget.get("script", "")
    if widget_script:
        si_names.update(_extract_si_refs_from_script(widget_script))
    # Scan provider scripts
    for prov in result["providers"]:
        prov_script = prov.get("script", "")
        if prov_script:
            si_names.update(_extract_si_refs_from_script(prov_script))

    if si_names:
        si_names_list = sorted(si_names)[:MAX_CHAIN_SI]
        si_query = "nameIN" + ",".join(si_names_list)
        try:
            si_resp = sn_query(
                config,
                auth_manager,
                GenericQueryParams(
                    table="sys_script_include",
                    query=si_query,
                    fields="sys_id,name,api_name,script,client_callable",
                    limit=MAX_CHAIN_SI,
                    offset=0,
                    display_value=False,
                ),
            )
            result["api_calls"] += 1
        except Exception as exc:
            result["warnings"] = result.get("warnings", []) + [
                f"Failed to fetch script includes: {exc}"
            ]
            result["success"] = True
            return result

        for si in si_resp.get("results", []):
            if "script" in si and isinstance(si["script"], str):
                si["script"] = _truncate_source(si["script"], max_src)
            result["script_includes"].append(si)

    result["success"] = True
    result["summary"] = (
        f"Resolved: 1 widget, {len(result['providers'])} providers, "
        f"{len(result['script_includes'])} script includes in {result['api_calls']} API calls"
    )
    return result


# Helper: extract Script Include names referenced in server scripts
_SI_REF_PATTERN = re.compile(r"\bnew\s+(\w+)\s*\(", re.MULTILINE)
_SI_GETAPPFUNCTION_PATTERN = re.compile(r"GlideAjax\s*\(\s*['\"](\w+)['\"]", re.MULTILINE)


def _extract_si_refs_from_script(script: str) -> Set[str]:
    """Extract likely Script Include names from a server-side script."""
    refs: Set[str] = set()
    # Pattern: new SomeSI()
    for m in _SI_REF_PATTERN.finditer(script):
        name = m.group(1)
        # Filter out common non-SI constructors
        if name not in {
            "GlideRecord",
            "GlideAggregate",
            "GlideDateTime",
            "GlideDate",
            "GlideDuration",
            "GlideFilter",
            "GlideRecordSecure",
            "GlideSession",
            "GlideSysAttachment",
            "GlideSchedule",
            "GlideSystem",
            "GlideElement",
            "GlideEmail",
            "Date",
            "Array",
            "Object",
            "Map",
            "Set",
            "RegExp",
            "Error",
            "JSON",
            "XMLDocument",
        }:
            refs.add(name)
    # Pattern: GlideAjax("SIName")
    for m in _SI_GETAPPFUNCTION_PATTERN.finditer(script):
        refs.add(m.group(1))
    return refs


# ---------------------------------------------------------------------------
# Page-level deep resolve: all widgets + shared dependencies in one call
# ---------------------------------------------------------------------------


class ResolvePageDependenciesParams(BaseModel):
    """Parameters for page-level dependency resolution."""

    page_id: str = Field(
        ...,
        description="Page sys_id or URL path (e.g. 'index', 'form', 'kb_view')",
    )
    depth: int = Field(
        default=3,
        description="1=widgets only, 2=+providers, 3=+script includes",
    )
    include_fields: List[str] = Field(
        default=["script", "client_script", "template"],
        description="Widget source fields to include",
    )
    max_source_length: int = Field(
        default=MAX_SOURCE_CHARS_PER_FIELD,
        description="Max chars per source field. 0=unlimited.",
    )
    save_to_disk: bool = Field(
        default=False,
        description="Save sources + dependency map to ./temp/{instance}/ for local analysis",
    )


# NOTE: de-registered as a standalone tool — now an internal resolver invoked
# by manage_widget_dependency (action=list, target=page). Kept importable so
# its tested behavior is preserved. See widget_dependency_tools.py.
def resolve_page_dependencies(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ResolvePageDependenciesParams,
) -> Dict[str, Any]:
    """Page → all widgets → providers → script includes with deduplication."""
    from .portal_management_tools import GetPageParams, get_page

    depth = min(max(1, params.depth), MAX_CHAIN_DEPTH)
    max_src = params.max_source_length
    api_calls = 0
    warnings: List[str] = []

    # --- Step 1: Get page layout to find all widget instances ---
    try:
        page_result = get_page(
            config,
            auth_manager,
            GetPageParams(page_id=params.page_id, include_layout=True),
        )
        api_calls += 1
    except Exception as exc:
        return {"success": False, "error": f"Failed to get page: {exc}"}

    if not page_result.get("success"):
        return {"success": False, "error": f"Page '{params.page_id}' not found."}

    # Extract widget sys_ids from layout tree
    page_data = page_result.get("page", {})
    widget_ids: List[str] = []
    widget_names: Dict[str, str] = {}  # sys_id → name

    def _walk_layout(node: Any) -> None:
        if isinstance(node, dict):
            w_id = node.get("widget_sys_id") or node.get("widget", {}).get("sys_id")
            w_name = node.get("widget_name") or node.get("widget", {}).get("name", "")
            if w_id and w_id not in widget_ids:
                widget_ids.append(w_id)
                if w_name:
                    widget_names[w_id] = w_name
            for v in node.values():
                _walk_layout(v)
        elif isinstance(node, list):
            for item in node:
                _walk_layout(item)

    _walk_layout(page_data.get("layout", {}))
    # Also check direct instances list
    for inst in page_result.get("instances", []):
        w_id = inst.get("widget_sys_id") or inst.get("widget", "")
        w_name = inst.get("widget_name", "")
        if w_id and w_id not in widget_ids:
            widget_ids.append(w_id)
            if w_name:
                widget_names[w_id] = w_name

    if not widget_ids:
        return {
            "success": True,
            "page": page_data.get("title", params.page_id),
            "widgets": [],
            "message": "No widgets found on this page.",
            "api_calls": api_calls,
        }

    widget_ids = widget_ids[:MAX_CHAIN_WIDGETS]

    # --- Step 2: Fetch all widgets with source ---
    widget_fields = ["sys_id", "name", "id", "sys_scope", "sys_updated_on"]
    widget_fields.extend(f for f in params.include_fields if f not in widget_fields)

    try:
        w_resp = sn_query(
            config,
            auth_manager,
            GenericQueryParams(
                table=WIDGET_TABLE,
                query=f"sys_idIN{','.join(widget_ids)}",
                fields=",".join(widget_fields),
                limit=MAX_CHAIN_WIDGETS,
                offset=0,
                display_value=False,
            ),
        )
        api_calls += 1
    except Exception as exc:
        return {"success": False, "error": f"Failed to fetch widgets: {exc}"}

    widgets = w_resp.get("results", [])
    for w in widgets:
        for f in params.include_fields:
            if f in w and isinstance(w[f], str):
                w[f] = _truncate_source(w[f], max_src)

    result: Dict[str, Any] = {
        "page": page_data.get("title", params.page_id),
        "page_url": page_data.get("id", params.page_id),
        "widgets": widgets,
        "providers": [],
        "script_includes": [],
        "dependency_map": {},
        "api_calls": api_calls,
    }

    if depth < 2:
        result["success"] = True
        return result

    # --- Step 3: Fetch ALL providers for ALL widgets (deduplicated) ---
    all_widget_sys_ids = [w["sys_id"] for w in widgets if w.get("sys_id")]
    widget_to_providers: Dict[str, List[str]] = {}  # widget_sys_id → [provider_sys_ids]

    if all_widget_sys_ids:
        m2m_resp: Dict[str, Any] = {"results": []}
        if not _table_known_absent(config, ANGULAR_PROVIDER_M2M_TABLE):
            try:
                m2m_resp = sn_query(
                    config,
                    auth_manager,
                    GenericQueryParams(
                        table=ANGULAR_PROVIDER_M2M_TABLE,
                        query=f"sp_widgetIN{','.join(all_widget_sys_ids)}",
                        fields="sp_widget,sp_angular_provider",
                        limit=500,
                        offset=0,
                        display_value=False,
                    ),
                )
                _note_table_response(config, ANGULAR_PROVIDER_M2M_TABLE, m2m_resp)
                api_calls += 1
            except Exception as exc:
                warnings.append(f"Failed to fetch provider M2M: {exc}")
                m2m_resp = {"results": []}

        all_provider_ids: Set[str] = set()
        for row in m2m_resp.get("results", []):
            w_id = _as_ref_sys_id(row.get("sp_widget"))
            p_id = _as_ref_sys_id(row.get("sp_angular_provider"))
            if w_id and p_id:
                widget_to_providers.setdefault(w_id, []).append(p_id)
                all_provider_ids.add(p_id)

        # Fetch unique providers in one batch
        if all_provider_ids:
            provider_id_list = sorted(all_provider_ids)[:MAX_CHAIN_PROVIDERS]
            try:
                prov_resp = sn_query(
                    config,
                    auth_manager,
                    GenericQueryParams(
                        table=ANGULAR_PROVIDER_TABLE,
                        query=f"sys_idIN{','.join(provider_id_list)}",
                        fields="sys_id,name,type,script,client_script",
                        limit=MAX_CHAIN_PROVIDERS,
                        offset=0,
                        display_value=False,
                    ),
                )
                api_calls += 1
            except Exception as exc:
                warnings.append(f"Failed to fetch providers: {exc}")
                prov_resp = {"results": []}

            for prov in prov_resp.get("results", []):
                if "script" in prov and isinstance(prov["script"], str):
                    prov["script"] = _truncate_source(prov["script"], max_src)
                if "client_script" in prov and isinstance(prov["client_script"], str):
                    prov["client_script"] = _truncate_source(prov["client_script"], max_src)
                result["providers"].append(prov)

    if depth < 3:
        result["success"] = True
        result["dependency_map"] = _build_dep_map(widgets, widget_to_providers, result["providers"])
        if warnings:
            result["warnings"] = warnings
        return result

    # --- Step 4: Extract SI refs from ALL scripts (deduplicated) ---
    si_names: Set[str] = set()
    for w in widgets:
        ws = w.get("script", "")
        if ws:
            si_names.update(_extract_si_refs_from_script(ws))
    for prov in result["providers"]:
        ps = prov.get("script", "")
        if ps:
            si_names.update(_extract_si_refs_from_script(ps))

    if si_names:
        si_list = sorted(si_names)[:MAX_CHAIN_SI]
        try:
            si_resp = sn_query(
                config,
                auth_manager,
                GenericQueryParams(
                    table="sys_script_include",
                    query="nameIN" + ",".join(si_list),
                    fields="sys_id,name,api_name,script,client_callable",
                    limit=MAX_CHAIN_SI,
                    offset=0,
                    display_value=False,
                ),
            )
            api_calls += 1
        except Exception as exc:
            warnings.append(f"Failed to fetch script includes: {exc}")
            si_resp = {"results": []}

        for si in si_resp.get("results", []):
            if "script" in si and isinstance(si["script"], str):
                si["script"] = _truncate_source(si["script"], max_src)
            result["script_includes"].append(si)

    result["api_calls"] = api_calls
    result["dependency_map"] = _build_dep_map(
        widgets, widget_to_providers, result["providers"], result["script_includes"]
    )
    result["success"] = True
    result["summary"] = (
        f"Page '{result['page']}': {len(widgets)} widgets, "
        f"{len(result['providers'])} providers (deduplicated), "
        f"{len(result['script_includes'])} script includes in {api_calls} API calls"
    )
    if warnings:
        result["warnings"] = warnings

    # --- Optional: save to disk for local deep analysis ---
    if params.save_to_disk:
        instance_name = _get_instance_name(config)
        out_dir = Path.cwd() / "temp" / instance_name / _safe_name(result["page_url"])
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_json_file(out_dir / "_dependency_map.json", result["dependency_map"])
        for w in widgets:
            w_dir = out_dir / "sp_widget" / _safe_name(w.get("name") or w.get("sys_id", ""))
            w_dir.mkdir(parents=True, exist_ok=True)
            for field in params.include_fields:
                if w.get(field):
                    ext = {"template": "html", "css": "css", "link": "scss"}.get(field, "js")
                    _write_text_file(w_dir / f"{field}.{ext}", str(w[field]))
        for prov in result["providers"]:
            p_dir = out_dir / "sp_angular_provider"
            p_dir.mkdir(parents=True, exist_ok=True)
            if prov.get("script"):
                _write_text_file(
                    p_dir / f"{_safe_name(prov.get('name', prov.get('sys_id', '')))}.js",
                    str(prov["script"]),
                )
        for si in result["script_includes"]:
            si_dir = out_dir / "sys_script_include"
            si_dir.mkdir(parents=True, exist_ok=True)
            if si.get("script"):
                _write_text_file(
                    si_dir / f"{_safe_name(si.get('name', si.get('sys_id', '')))}.js",
                    str(si["script"]),
                )
        result["saved_to"] = str(out_dir)

    return result


def _build_dep_map(
    widgets: List[Dict],
    widget_to_providers: Dict[str, List[str]],
    providers: List[Dict],
    script_includes: List[Dict] | None = None,
) -> Dict[str, Any]:
    """Build a human-readable dependency map for the LLM."""
    prov_by_id = {p["sys_id"]: p.get("name", p["sys_id"]) for p in providers}
    si_names = [si.get("name", si.get("sys_id", "")) for si in (script_includes or [])]

    dep_map: Dict[str, Any] = {"widgets": {}, "shared_providers": {}, "script_includes": si_names}

    # Widget → provider connections
    provider_usage_count: Dict[str, int] = {}
    for w in widgets:
        w_id = w.get("sys_id", "")
        w_name = w.get("name", w.get("id", w_id))
        prov_ids = widget_to_providers.get(w_id, [])
        prov_names = [prov_by_id.get(pid, pid) for pid in prov_ids]
        dep_map["widgets"][w_name] = {"providers": prov_names}
        for pid in prov_ids:
            provider_usage_count[pid] = provider_usage_count.get(pid, 0) + 1

    # Shared providers (used by 2+ widgets)
    for pid, count in provider_usage_count.items():
        if count >= 2:
            name = prov_by_id.get(pid, pid)
            dep_map["shared_providers"][name] = {
                "used_by_widgets": count,
                "widgets": [
                    w.get("name", w.get("id", w.get("sys_id", "")))
                    for w in widgets
                    if w.get("sys_id", "") in widget_to_providers
                    and pid in widget_to_providers[w["sys_id"]]
                ],
            }

    return dep_map
