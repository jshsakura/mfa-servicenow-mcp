"""
Service Portal development tools for the ServiceNow MCP server.
Optimized for speed, token efficiency, and context safety.
"""

import difflib
import logging
import re
from concurrent.futures import as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Set
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils import json_fast
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .sn_api import (
    GenericQueryParams,
    _page_executor,
    invalidate_query_cache,
    sn_query,
    sn_query_all,
)

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
    script_offset: int = Field(
        0,
        description="Character offset to start reading script fields from. Use for paginating large scripts.",
    )
    script_max_length: int = Field(
        8000,
        description="Maximum characters to return per script field (default 8000, clamped to 12000). Use with script_offset to paginate.",
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


class AnalyzePortalComponentUpdateParams(UpdatePortalComponentParams):
    """Parameters for analyzing a proposed portal component update."""


class PreviewPortalComponentUpdateParams(UpdatePortalComponentParams):
    """Parameters for previewing a proposed portal component update."""


class CreatePortalComponentSnapshotParams(BaseModel):
    """Parameters for exporting the current editable state of a portal component."""

    table: str = Field(
        ..., description="The table name (sp_widget, sp_angular_provider, sys_script_include)"
    )
    sys_id: str = Field(..., description="The sys_id of the component")
    fields: List[str] | None = Field(
        None,
        description="Optional editable fields to snapshot. Defaults to all allowed editable fields for the table.",
    )
    output_dir: str | None = Field(
        None,
        description="Optional snapshot directory. Defaults to ./.servicenow_mcp/portal_component_snapshots/<instance>/",
    )


class UpdatePortalComponentFromSnapshotParams(BaseModel):
    """Parameters for restoring a portal component from a saved local snapshot."""

    snapshot_path: str = Field(
        ..., description="Path to a saved portal component snapshot JSON file"
    )


class RoutePortalComponentEditParams(BaseModel):
    """Parameters for shallow natural-language routing into the portal edit pipeline."""

    instruction: str = Field(..., description="Short natural-language instruction")
    table: str | None = Field(
        None,
        description="Optional target table (sp_widget, sp_angular_provider, sys_script_include)",
    )
    sys_id: str | None = Field(None, description="Optional target component sys_id")
    update_data: Dict[str, str] | None = Field(
        None, description="Optional explicit field updates for analyze/preview/apply routing"
    )
    snapshot_path: str | None = Field(
        None, description="Optional snapshot path for rollback/restore routing"
    )


class DownloadPortalSourcesParams(BaseModel):
    output_dir: str | None = Field(
        None, description="Output directory path. Defaults to current working directory"
    )
    scope: str | None = Field(
        None,
        description="Optional app scope filter (sys_scope). Example: x_company_bpm",
    )
    widget_ids: List[str] | None = Field(
        None,
        description="Optional list of widget sys_id/id/name. If empty, exports all widgets in scope.",
    )
    include_linked_script_includes: bool | None = Field(
        None,
        description="Include script includes referenced by exported widgets. Defaults to true for targeted widget export.",
    )
    include_linked_angular_providers: bool | None = Field(
        None,
        description="Include angular providers linked via widget-provider M2M. Defaults to true for targeted widget export.",
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
    max_widgets: int = Field(
        25,
        description="Maximum widgets to export (default 25, clamped to 100)",
    )
    page_size: int = Field(50, description="Pagination size for API queries (10..100)")


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
) -> Dict[str, Any]:
    query_fields = list(dict.fromkeys([*fields, "name", "sys_id"]))
    query_params = GenericQueryParams(
        table=table,
        query=f"sys_id={sys_id}",
        fields=",".join(query_fields),
        limit=1,
        offset=0,
        display_value=False,
    )
    response = sn_query(config, auth_manager, query_params)
    if not response.get("success") or not response.get("results"):
        raise ValueError(f"Component not found in {table} with sys_id {sys_id}")
    return response["results"][0]


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


_RE_ROLLBACK = re.compile(r"\b(rollback|roll back|restore|revert|undo)\b", re.IGNORECASE)
_RE_SNAPSHOT = re.compile(r"\b(snapshot|backup|save current|save state)\b", re.IGNORECASE)
_RE_PREVIEW = re.compile(r"\b(preview|diff|show changes|what would change)\b", re.IGNORECASE)
_RE_APPLY = re.compile(r"\b(apply|update|modify|change|patch|fix|edit)\b", re.IGNORECASE)


def _detect_portal_edit_action(instruction: str) -> str:
    if _RE_ROLLBACK.search(instruction):
        return "rollback"
    if _RE_SNAPSHOT.search(instruction):
        return "snapshot"
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

    if action == "rollback":
        missing = [name for name, value in [("snapshot_path", params.snapshot_path)] if not value]
        return {
            "tool_name": "update_portal_component_from_snapshot",
            "arguments": ({"snapshot_path": params.snapshot_path} if params.snapshot_path else {}),
            "confirmation_required": True,
            "missing_requirements": missing,
        }

    if action == "snapshot":
        missing = [
            name
            for name, value in [("table", normalized_table), ("sys_id", params.sys_id)]
            if not value
        ]
        suggested_fields = (
            _detect_portal_edit_fields(params.instruction)
            if normalized_table == WIDGET_TABLE
            else []
        )
        snapshot_arguments: Dict[str, Any] = {}
        if normalized_table:
            snapshot_arguments["table"] = normalized_table
        if params.sys_id:
            snapshot_arguments["sys_id"] = params.sys_id
        if suggested_fields:
            snapshot_arguments["fields"] = suggested_fields
        return {
            "tool_name": "create_portal_component_snapshot",
            "arguments": snapshot_arguments,
            "confirmation_required": False,
            "missing_requirements": missing,
        }

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
    elif action == "rollback":
        stage_three_goal = "검토가 끝난 snapshot 기준으로 안전하게 롤백"
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


def _resolve_snapshot_root(config: ServerConfig, output_dir: str | None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    instance_name = (urlparse(config.instance_url).hostname or "instance").split(".")[0]
    return (Path.cwd() / SNAPSHOT_ROOT_DIRNAME / instance_name).expanduser().resolve()


def _resolve_snapshot_fields(table: str, requested_fields: List[str] | None) -> List[str]:
    normalized_table = _normalize_portal_component_table(table)
    allowed_fields = PORTAL_COMPONENT_EDITABLE_FIELDS[normalized_table]
    if requested_fields is None:
        return sorted(allowed_fields)

    invalid_fields = sorted(field for field in requested_fields if field not in allowed_fields)
    if invalid_fields:
        allowed = ", ".join(sorted(allowed_fields))
        raise ValueError(
            f"Unsupported snapshot fields for {normalized_table}: {', '.join(invalid_fields)}. Allowed fields: {allowed}"
        )
    return list(dict.fromkeys(requested_fields))


def _build_snapshot_payload(
    config: ServerConfig,
    table: str,
    sys_id: str,
    record: Dict[str, Any],
    fields: List[str],
) -> Dict[str, Any]:
    return {
        "snapshot_version": 1,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "instance_url": config.instance_url,
        "component": {
            "table": table,
            "sys_id": sys_id,
            "name": str(record.get("name") or sys_id),
        },
        "fields": fields,
        "values": {field_name: str(record.get(field_name) or "") for field_name in fields},
    }


def _write_portal_component_snapshot(
    config: ServerConfig,
    table: str,
    sys_id: str,
    record: Dict[str, Any],
    fields: List[str],
    output_dir: str | None = None,
) -> Path:
    root = _resolve_snapshot_root(config, output_dir)
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_name = _safe_name(str(record.get("name") or sys_id))
    file_path = root / f"{_safe_name(table)}__{safe_name}__{_safe_name(sys_id)}__{timestamp}.json"
    _write_json_file(file_path, _build_snapshot_payload(config, table, sys_id, record, fields))
    return file_path


def _read_portal_component_snapshot(snapshot_path: str) -> Dict[str, Any]:
    path = Path(snapshot_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Snapshot file not found: {path}")

    payload = json_fast.loads(path.read_text(encoding="utf-8"))
    component = payload.get("component") or {}
    values = payload.get("values") or {}
    fields = payload.get("fields") or []
    if (
        not isinstance(component, dict)
        or not isinstance(values, dict)
        or not isinstance(fields, list)
    ):
        raise ValueError(f"Invalid snapshot format: {path}")

    table = str(component.get("table") or "")
    sys_id = str(component.get("sys_id") or "")
    if not table or not sys_id:
        raise ValueError(f"Invalid snapshot component metadata: {path}")

    _resolve_snapshot_fields(table, [str(field) for field in fields])
    for field_name, value in values.items():
        if not isinstance(value, str):
            raise ValueError(f"Snapshot value for '{field_name}' must be a string: {path}")
    return payload


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
MAX_PORTAL_DOWNLOAD_WIDGETS = 100
MAX_WIDGET_REVIEW_LIMIT = 100
MAX_WIDGET_REVIEW_MATCHES = 100
DEFAULT_WIDGET_REVIEW_SNIPPET_LENGTH = 220
MAX_ANGULAR_PROVIDER_SCAN_LIMIT = 100
MAX_ANGULAR_IMPLICIT_GLOBAL_MATCHES = 100
DEFAULT_ANGULAR_IMPLICIT_SNIPPET_LENGTH = 180
MAX_COMPONENT_SCRIPT_CHARS = 12000
MAX_PREVIEW_TEXT_LENGTH = 600
MAX_PREVIEW_DIFF_LINES = 80
SNAPSHOT_ROOT_DIRNAME = ".servicenow_mcp/portal_component_snapshots"

PORTAL_COMPONENT_EDITABLE_FIELDS: Dict[str, Set[str]] = {
    "sp_widget": {"template", "script", "client_script", "link", "css"},
    "sp_angular_provider": {"script"},
    "sys_script_include": {"script"},
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
        DEFAULT_REDIRECT_PATTERN,
        description=(
            "Pattern to find in source code. In auto mode (default), plain strings are treated literally and regex-looking patterns stay regex."
        ),
    )
    match_mode: str = Field(
        "auto",
        description="Pattern mode: auto | literal | regex. Use auto for LLM-friendly matching without manual escaping.",
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
    provider_ids: List[str] | None = Field(
        None,
        description="Optional angular provider sys_id/name filters. If provided, scan these providers directly (bypasses widget→M2M lookup).",
    )
    source_types: List[str] = Field(
        ["widget"],
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
        False,
        description="Expand scan to script includes referenced by matched widgets",
    )
    include_linked_angular_providers: bool = Field(
        False,
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
        25,
        description=f"Maximum widgets to scan after filter. Clamped to {MAX_WIDGET_REVIEW_LIMIT}.",
    )
    page_size: int = Field(50, description="Pagination size for API queries (10..100)")
    max_matches: int = Field(
        25,
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


class TracePortalRouteTargetsParams(BaseModel):
    regex: str = Field(
        DEFAULT_REDIRECT_PATTERN,
        description=(
            "Pattern for the route/target to trace. In auto mode (default), plain strings are treated literally and regex-looking patterns stay regex."
        ),
    )
    match_mode: str = Field(
        "auto",
        description="Pattern mode: auto | literal | regex. Use auto for LLM-friendly matching without manual escaping.",
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
        description="Optional widget id/sys_id/name filters. If provided, only these widgets are traced.",
    )
    provider_ids: List[str] | None = Field(
        None,
        description="Optional provider id/sys_id/name filters. When provided, linked widgets are resolved first.",
    )
    include_linked_angular_providers: bool = Field(
        True,
        description="Expand each widget trace to linked Angular Providers before scanning for route matches.",
    )
    include_widget_fields: List[str] = Field(
        ["template", "script", "client_script", "link"],
        description="Widget fields to inspect for route matches or click-handler clues.",
    )
    max_widgets: int = Field(
        10,
        description=f"Maximum widgets to analyze after filters. Clamped to {MAX_WIDGET_REVIEW_LIMIT}.",
    )
    page_size: int = Field(50, description="Pagination size for API queries (10..100)")
    max_traces: int = Field(
        25,
        description=f"Maximum widget trace rows to return. Clamped to {MAX_WIDGET_REVIEW_MATCHES}.",
    )
    snippet_length: int = Field(
        DEFAULT_WIDGET_REVIEW_SNIPPET_LENGTH,
        description="Maximum one-line evidence snippet length per match",
    )
    output_mode: str = Field(
        "minimal",
        description="Output shape: minimal | compact | full",
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
        25,
        description=f"Maximum providers to scan after filter. Clamped to {MAX_ANGULAR_PROVIDER_SCAN_LIMIT}.",
    )
    page_size: int = Field(50, description="Pagination size for API queries (10..100)")
    max_matches: int = Field(
        25,
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
            config, auth_manager, table=table, query=query,
            fields=fields, page_size=page_size, max_records=max_records,
        )

    def _fetch(chunk: List[str]) -> List[Dict[str, Any]]:
        query = query_template.format(ids=",".join(chunk))
        return sn_query_all(
            config, auth_manager, table=table, query=query,
            fields=fields, page_size=page_size, max_records=max_records,
        )

    rows: List[Dict[str, Any]] = []
    futures = {_page_executor.submit(_fetch, c): c for c in chunks}
    for future in as_completed(futures):
        try:
            rows.extend(future.result())
        except Exception:
            logger.warning("Parallel chunk query failed for table %s", table)
    return rows


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

        query_parts = ["(" + "^OR".join(candidate_clauses) + ")"]
        if scope:
            query_parts.append(f"sys_scope={_escape_query(scope)}")
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
            fields="sys_id,name,api_name,script,sys_scope,sys_updated_by,sys_updated_on",
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
) -> List[Dict[str, Any]]:
    normalized_tokens = _dedupe_preserve_order_strings(widget_tokens)
    if not normalized_tokens:
        return []

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

        query = "(" + "^OR".join(clauses) + ")"
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
            row = rows_by_sys_id.get(sys_id)
            if row is None:
                continue
            ordered_rows.append(row)
            seen_sys_ids.add(sys_id)

    for sys_id, row in rows_by_sys_id.items():
        if sys_id not in seen_sys_ids:
            ordered_rows.append(row)

    return ordered_rows


def _download_widget_fields(
    *,
    include_widget_template: bool,
    include_widget_server_script: bool,
    include_widget_client_script: bool,
    include_widget_link_script: bool,
    include_widget_css: bool,
    include_linked_script_includes: bool,
) -> str:
    fields = ["sys_id", "name", "id", "sys_scope", "option_schema", "demo_data"]
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
            "Broad widget scans should be used only when a targeted widget or small widget set is not available."
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
) -> List[Dict[str, Any]]:
    """Delegate to shared parallel-capable ``sn_query_all`` in sn_api."""
    return sn_query_all(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        page_size=page_size,
        max_records=max_records,
    )


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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
                return json_fast.loads(trimmed)
            except (ValueError, TypeError):
                return value
    return value


@register_tool(
    "get_widget_bundle",
    params=GetWidgetBundleParams,
    description="Fetch widget HTML, scripts, and provider list in a single API call. Returns complete bundle for analysis.",
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
    bundle: Dict[str, Any] = {"widget": widget}

    # 2. Fetch Angular Provider list (minimal info to save context)
    if params.include_providers:
        m2m_query_params = GenericQueryParams(
            table=ANGULAR_PROVIDER_M2M_TABLE,
            query=f"sp_widget={widget['sys_id']}",
            fields="sp_angular_provider",
            limit=100,
            offset=0,
            display_value=False,
        )
        m2m_response = sn_query(config, auth_manager, m2m_query_params)
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

    return bundle


@register_tool(
    "get_portal_component_code",
    params=GetPortalComponentParams,
    description="Fetch specific code field from a widget, provider, or script include. Token-efficient: returns only requested fields.",
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

    budget = _clamp_script_chunk_length(params.script_max_length)
    offset = max(0, params.script_offset)
    remaining_budget = budget

    for field in params.fields:
        val = result.get(field, "")
        if not isinstance(val, str):
            continue
        total_length = len(val)

        if remaining_budget <= 0:
            # Budget exhausted — don't include this field's content
            result[field] = ""
            result[f"_{field}_total_length"] = total_length
            result[f"_{field}_offset"] = offset
            result[f"_{field}_returned_length"] = 0
            if offset < total_length:
                result[f"_{field}_has_more"] = True
                result[f"_{field}_next_offset"] = offset
            continue

        # Apply windowing with remaining budget
        field_max = remaining_budget
        end = offset + field_max
        # Snap to a safe boundary so we never split mid-token
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
        result[f"_{field}_total_length"] = total_length
        result[f"_{field}_offset"] = offset
        result[f"_{field}_returned_length"] = len(chunk)
        remaining_budget -= len(chunk)
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
    current_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        list(normalized_update_data.keys()),
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
    current_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        list(normalized_update_data.keys()),
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
    "create_portal_component_snapshot",
    params=CreatePortalComponentSnapshotParams,
    description="Save the current editable state of a portal component to a local snapshot file for rollback or review",
    serialization="raw_dict",
    return_type=dict,
)
def create_portal_component_snapshot(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreatePortalComponentSnapshotParams,
) -> Dict[str, Any]:
    normalized_table = _normalize_portal_component_table(params.table)
    snapshot_fields = _resolve_snapshot_fields(normalized_table, params.fields)
    current_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        snapshot_fields,
    )
    snapshot_path = _write_portal_component_snapshot(
        config,
        normalized_table,
        params.sys_id,
        current_record,
        snapshot_fields,
        params.output_dir,
    )

    return {
        "success": True,
        "component": {
            "table": normalized_table,
            "sys_id": params.sys_id,
            "name": str(current_record.get("name") or params.sys_id),
        },
        "snapshot": {
            "path": str(snapshot_path),
            "fields": snapshot_fields,
        },
        "safety_notice": "Snapshot saved locally. No remote changes were applied.",
    }


@register_tool(
    "route_portal_component_edit",
    params=RoutePortalComponentEditParams,
    description="Shallow natural-language router that maps short portal edit instructions to bounded analyze/preview/apply/snapshot/rollback tools",
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
    if params.snapshot_path:
        target["snapshot_path"] = params.snapshot_path

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
            "Apply and rollback still require explicit confirmation and complete arguments."
        ),
    }


@register_tool(
    "search_portal_regex_matches",
    params=SearchPortalRegexMatchesParams,
    description="Regex search across widget sources (HTML/scripts/providers). Supports minimal, compact, and full output modes.",
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
            escaped_chunks = [
                [_escape_query(v) for v in chunk] for chunk in _chunked(widget_ids, 100)
            ]
            relation_rows = _parallel_chunked_query(
                config, auth_manager,
                table=ANGULAR_PROVIDER_M2M_TABLE,
                chunks=escaped_chunks,
                query_template="sp_widgetIN{ids}",
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


def search_widget_author_patterns(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: SearchPortalRegexMatchesParams,
) -> Dict[str, Any]:
    return search_portal_regex_matches(config, auth_manager, params)


@register_tool(
    "trace_portal_route_targets",
    params=TracePortalRouteTargetsParams,
    description="Map widget-to-provider-to-route relationships without raw script bodies. Returns route targets and handler clues.",
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
        widget_query_parts.append(f"sys_scope={_escape_query(params.scope)}")

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
            relation_rows = _sn_query_all(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_M2M_TABLE,
                query=f"sp_angular_providerIN{','.join(resolved_provider_ids)}",
                fields="sp_widget,sp_angular_provider",
                page_size=page_size,
                max_records=1000,
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
        relation_rows = _parallel_chunked_query(
            config, auth_manager,
            table=ANGULAR_PROVIDER_M2M_TABLE,
            chunks=escaped_chunks,
            query_template="sp_widgetIN{ids}",
            fields="sp_widget,sp_angular_provider",
            page_size=page_size,
            max_records=1000,
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
            config, auth_manager,
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
    description="Find undeclared variable assignments in Angular provider scripts that cause runtime 'not defined' errors.",
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


@register_tool(
    "update_portal_component",
    params=UpdatePortalComponentParams,
    description="Update specific code fields (HTML, CSS, or script) of a widget, provider, or script include.",
    serialization="raw_dict",
    return_type=dict,
)
def update_portal_component(
    config: ServerConfig, auth_manager: AuthManager, params: UpdatePortalComponentParams
) -> Dict[str, Any]:
    """Pinpoint update of specific portal component fields."""
    normalized_table = _normalize_portal_component_table(params.table)
    normalized_update_data = _validate_portal_component_update_data(
        normalized_table, params.update_data
    )
    current_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        list(normalized_update_data.keys()),
    )
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

    snapshot_path = _write_portal_component_snapshot(
        config,
        normalized_table,
        params.sys_id,
        current_record,
        list(effective_update_data.keys()),
    )

    instance_url = config.instance_url
    url = f"{instance_url}/api/now/table/{normalized_table}/{params.sys_id}"

    headers = auth_manager.get_headers()
    response = auth_manager.make_request("PATCH", url, json=effective_update_data, headers=headers)

    if response.status_code >= 400:
        return {"error": f"Update failed: {response.text}", "status": response.status_code}

    invalidate_query_cache(table=normalized_table)

    validated_record = _fetch_portal_component_record(
        config,
        auth_manager,
        normalized_table,
        params.sys_id,
        list(effective_update_data.keys()),
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

    return {
        "message": "Update successful",
        "sys_id": params.sys_id,
        "fields": list(effective_update_data.keys()),
        "snapshot": {
            "path": str(snapshot_path),
            "fields": list(effective_update_data.keys()),
        },
        "validation": {
            "verified_fields": verified_fields,
            "mismatched_fields": mismatched_fields,
            "post_update_name": str(validated_record.get("name") or params.sys_id),
        },
    }


@register_tool(
    "update_portal_component_from_snapshot",
    params=UpdatePortalComponentFromSnapshotParams,
    description="Restore a portal component's editable fields from a previously saved local snapshot",
    serialization="raw_dict",
    return_type=dict,
)
def update_portal_component_from_snapshot(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdatePortalComponentFromSnapshotParams,
) -> Dict[str, Any]:
    snapshot = _read_portal_component_snapshot(params.snapshot_path)
    snapshot_instance_url = str(snapshot.get("instance_url") or "")
    if snapshot_instance_url and snapshot_instance_url != config.instance_url:
        raise ValueError(
            "Snapshot instance_url does not match the current configured instance. "
            f"Snapshot: {snapshot_instance_url}, current: {config.instance_url}"
        )

    component = snapshot["component"]
    values = {str(key): str(value) for key, value in snapshot["values"].items()}
    update_result = update_portal_component(
        config,
        auth_manager,
        UpdatePortalComponentParams(
            table=str(component["table"]),
            sys_id=str(component["sys_id"]),
            update_data=values,
        ),
    )
    update_result["rollback"] = {
        "restored_from_snapshot": str(Path(params.snapshot_path).expanduser().resolve()),
    }
    return update_result


@register_tool(
    "download_portal_sources",
    params=DownloadPortalSourcesParams,
    description="Export widget, provider, and script include sources to local file structure. Supports scope and widget filters.",
    serialization="raw_dict",
    return_type=dict,
)
def download_portal_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadPortalSourcesParams,
) -> Dict[str, Any]:
    root = (
        Path(params.output_dir).expanduser().resolve()
        if params.output_dir
        else Path.cwd().expanduser().resolve()
    )
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
    scope_name = _safe_name(params.scope or "global")
    scope_root = root / scope_name
    instance_name = (urlparse(config.instance_url).hostname or "instance").split(".")[0]
    g_ck = str(getattr(auth_manager, "_browser_session_token", "") or "")

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
    widget_fields = _download_widget_fields(
        include_widget_template=params.include_widget_template,
        include_widget_server_script=params.include_widget_server_script,
        include_widget_client_script=params.include_widget_client_script,
        include_widget_link_script=params.include_widget_link_script,
        include_widget_css=params.include_widget_css,
        include_linked_script_includes=include_linked_script_includes,
    )

    widgets: List[Dict[str, Any]] = []
    if params.widget_ids:
        widgets = _fetch_targeted_widget_rows(
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
        )

    widget_map: Dict[str, str] = {}
    exported_widgets: List[Dict[str, str]] = []
    script_include_candidates: List[str] = []
    scope_sys_ids: Dict[str, str] = {}

    dictionary_by_field: Dict[str, Dict[str, Any]] = {}

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
    if include_linked_angular_providers and widgets:
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
    if include_linked_script_includes and script_include_candidates:
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
        "warnings": warnings,
        "widget_map_path": str(scope_root / "sp_widget" / "_map.json"),
        "angular_provider_map_path": str(scope_root / "sp_angular_provider" / "_map.json"),
        "script_include_map_path": str(scope_root / "sys_script_include" / "_map.json"),
        "safety_notice": "Exports structured source files only; no destructive remote operations are performed.",
    }
