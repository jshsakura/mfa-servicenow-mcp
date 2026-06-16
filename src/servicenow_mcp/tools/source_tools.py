"""
Server-side source discovery tools inspired by common ServiceNow productivity workflows.
Designed for MCP use: read-only, token-efficient, and strongly scoped.
"""

import json
import logging
import os
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import (
    _RETRY_MAX_ATTEMPTS,
    _is_retryable,
    _retry_delay,
    apply_scope_namespace,
    sn_query_all,
    sn_query_page,
)
from servicenow_mcp.tools.source_resume import (
    clear_progress,
    load_progress,
    params_fingerprint,
    save_stage,
)
from servicenow_mcp.utils.atomic_io import atomic_write_text
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.download_map import (
    map_sys_ids,
    max_sync_updated_on,
    merge_map_file,
    read_download_map,
)
from servicenow_mcp.utils.progress import emit_progress
from servicenow_mcp.utils.registry import register_tool
from servicenow_mcp.utils.source_layout import FIELD_FILENAME, dep_scope_roots, field_extension

logger = logging.getLogger(__name__)

MAX_SEARCH_LIMIT = 10
PER_TYPE_LIMIT = 5
MAX_FIELD_LENGTH = 12000
DEFAULT_FIELD_LENGTH = 4000
SNIPPET_RADIUS = 120
MAX_DEP_SCAN_LIMIT = 5000
DEFAULT_DEP_SCAN_LIMIT = 500
DEFAULT_DEP_PAGE_SIZE = 100
MAX_DOWNLOAD_PER_TYPE = 50000
DEFAULT_DOWNLOAD_PER_TYPE = 10000
DEFAULT_DOWNLOAD_PAGE_SIZE = 20
MAX_TABLES_PER_RECORD = 50
DEFAULT_MAX_LINKED_SI = 20
MAX_LINKED_SI = 100

TABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
STRING_TABLE_LITERAL_RE = re.compile(r"[\"']([a-z][a-z0-9_]{1,79})[\"']")
JS_TABLE_ASSIGNMENT_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[\"']([a-z][a-z0-9_]{1,79})[\"']"
)
GLIDE_CONSTRUCTOR_RE = re.compile(
    r"\bnew\s+(?:global\.)?(GlideRecord|GlideRecordSecure|GlideAggregate)\s*\(\s*([^\)]+?)\s*\)",
    re.IGNORECASE,
)
GLIDE_DB_FUNCTION_RE = re.compile(
    r"\b(?:addToUpdateSet|newRecord|getRecordClassName|getTableName)\s*\(\s*[\"']([a-z][a-z0-9_]{1,79})[\"']\s*\)"
)
GR_SET_TABLE_RE = re.compile(
    r"\b[A-Za-z_$][\w$]*\s*\.\s*setTableName\s*\(\s*[\"']([a-z][a-z0-9_]{1,79})[\"']\s*\)"
)
SCRIPT_INCLUDE_INSTANCE_RE = re.compile(
    r"\bnew\s+(?:global\.)?((?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*)\s*\("
)
IGNORED_CLASS_NAMES = {
    "GlideRecord",
    "GlideRecordSecure",
    "GlideAggregate",
    "GlideDateTime",
    "GlideDuration",
    "GlideElement",
    "GlideAjax",
    "Object",
    "Array",
    "Date",
    "RegExp",
}

SOURCE_TYPE_ALL = "all"
# Canonical list of supported source types. Also exposed to the LLM as the
# Literal on SearchServerCodeParams/GetMetadataSourceParams below, so adding a
# type here automatically updates the JSON-schema enum.
DEFAULT_SOURCE_TYPE_ORDER = [
    "script_include",
    "widget",
    "angular_provider",
    "business_rule",
    "client_script",
    "catalog_client_script",
    "ui_action",
    "ui_script",
    "ui_page",
    "ui_macro",
    "scripted_rest",
    "fix_script",
    "scheduled_job",
    "script_action",
    "email_notification",
    "acl",
    "transform_script",
    "processor",
    "sp_header_footer",
    "sp_css",
    "ng_template",
    "update_xml",
]
SourceType = Literal[
    "all",
    "script_include",
    "widget",
    "angular_provider",
    "business_rule",
    "client_script",
    "catalog_client_script",
    "ui_action",
    "ui_script",
    "ui_page",
    "ui_macro",
    "scripted_rest",
    "fix_script",
    "scheduled_job",
    "script_action",
    "email_notification",
    "acl",
    "transform_script",
    "processor",
    "sp_header_footer",
    "sp_css",
    "ng_template",
    "update_xml",
]
SpecificSourceType = Literal[
    "script_include",
    "widget",
    "angular_provider",
    "business_rule",
    "client_script",
    "catalog_client_script",
    "ui_action",
    "ui_script",
    "ui_page",
    "ui_macro",
    "scripted_rest",
    "fix_script",
    "scheduled_job",
    "script_action",
    "email_notification",
    "acl",
    "transform_script",
    "processor",
    "sp_header_footer",
    "sp_css",
    "ng_template",
    "update_xml",
]
SOURCE_CONFIG: Dict[str, Dict[str, Any]] = {
    "script_include": {
        "table": "sys_script_include",
        "identifier_field": "api_name",
        "summary_fields": [
            "sys_id",
            "name",
            "api_name",
            "description",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "api_name", "description", "script"],
        "lookup_fields": ["sys_id", "name", "api_name"],
    },
    "business_rule": {
        "table": "sys_script",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "collection",
            "when",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script", "condition"],
        "search_fields": ["name", "collection", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "client_script": {
        "table": "sys_script_client",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "table",
            "type",
            "ui_type",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "table", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "ui_action": {
        "table": "sys_ui_action",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "table",
            "action_name",
            "active",
            "client",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "table", "action_name", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "ui_script": {
        "table": "sys_ui_script",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "global",
            "ui_type",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "ui_page": {
        "table": "sys_ui_page",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "description",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["html", "client_script", "processing_script"],
        "search_fields": ["name", "description", "html", "client_script", "processing_script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "scripted_rest": {
        "table": "sys_ws_operation",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "http_method",
            "active",
            "web_service_definition",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["operation_script"],
        "search_fields": ["name", "operation_script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "fix_script": {
        "table": "sys_script_fix",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "description",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "description", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "update_xml": {
        "table": "sys_update_xml",
        "identifier_field": "target_name",
        "summary_fields": [
            "sys_id",
            "name",
            "target_name",
            "type",
            "update_set",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["payload"],
        "search_fields": ["name", "target_name", "payload"],
        "lookup_fields": ["sys_id", "name", "target_name"],
    },
    "widget": {
        "table": "sp_widget",
        "identifier_field": "id",
        "summary_fields": [
            "sys_id",
            "name",
            "id",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["template", "script", "client_script", "css"],
        "search_fields": ["name", "id", "template", "script", "client_script", "css"],
        "lookup_fields": ["sys_id", "id", "name"],
    },
    "angular_provider": {
        "table": "sp_angular_provider",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "type",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script", "client_script"],
        "search_fields": ["name", "script", "client_script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "catalog_client_script": {
        "table": "catalog_script_client",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "cat_item",
            "type",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "cat_item", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "ui_macro": {
        "table": "sys_ui_macro",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "description",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["xml"],
        "search_fields": ["name", "description", "xml"],
        "lookup_fields": ["sys_id", "name"],
    },
    "scheduled_job": {
        "table": "sysauto_script",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "active",
            "run_type",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "script_action": {
        "table": "sysevent_script_action",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "event_name",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "event_name", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "email_notification": {
        "table": "sysevent_email_action",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "collection",
            "event_name",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["message_html", "message_text"],
        "search_fields": ["name", "collection", "event_name", "message_html", "message_text"],
        "lookup_fields": ["sys_id", "name"],
    },
    "acl": {
        "table": "sys_security_acl",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "type",
            "operation",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "transform_script": {
        "table": "sys_transform_script",
        "identifier_field": "name",
        # sys_transform_script.name is usually blank — a transform script is
        # identified by its map + when + order, not a name. Without this the
        # folder fell back to the bare sys_id. map.name is a dot-walked read so
        # the readable map name comes back even under display_value=False.
        "folder_fields": ["map.name", "when", "order"],
        "summary_fields": [
            "sys_id",
            "name",
            "map",
            "map.name",
            "when",
            "order",
            "active",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "processor": {
        "table": "sys_processor",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "path",
            "type",
            "active",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "path", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "sp_header_footer": {
        "table": "sp_header_footer",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["template", "css"],
        "search_fields": ["name", "template", "css"],
        "lookup_fields": ["sys_id", "name"],
    },
    "sp_css": {
        "table": "sp_css",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["css"],
        "search_fields": ["name", "css"],
        "lookup_fields": ["sys_id", "name"],
    },
    "ng_template": {
        "table": "sp_ng_template",
        "identifier_field": "id",
        "summary_fields": [
            "sys_id",
            "id",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["template"],
        "search_fields": ["id", "template"],
        "lookup_fields": ["sys_id", "id"],
    },
    "sp_page": {
        "table": "sp_page",
        "identifier_field": "id",
        "summary_fields": [
            "sys_id",
            "id",
            "title",
            "description",
            "category",
            "internal",
            "public",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": [],
        "search_fields": ["id", "title", "description"],
        "lookup_fields": ["sys_id", "id"],
    },
    "sp_instance": {
        "table": "sp_instance",
        "identifier_field": "sys_id",
        "summary_fields": [
            "sys_id",
            "sp_page",
            "sp_widget",
            "sp_column",
            "widget_parameters",
            "order",
            "title",
            "sys_scope",
            "sys_scope.scope",
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": [],
        "search_fields": ["title", "widget_parameters"],
        "lookup_fields": ["sys_id"],
    },
}


class SearchServerCodeParams(BaseModel):
    query: str = Field(..., description="Text to search in names, identifiers, and source fields")
    source_type: SourceType = Field(
        default="all",
        description="Source type to search; 'all' covers every supported type.",
    )
    limit: int = Field(
        default=5,
        description=f"Maximum number of total matches to return. Clamped to {MAX_SEARCH_LIMIT}.",
    )
    scope: str | None = Field(default=None, description="Optional scope filter")
    updated_by: str | None = Field(default=None, description="Optional updated_by filter")
    max_snippet_length: int = Field(
        default=300, description="Maximum snippet size returned for each match"
    )


class GetMetadataSourceParams(BaseModel):
    source_type: SpecificSourceType = Field(
        default=...,
        description="Specific source type (not 'all').",
    )
    source_id: str = Field(..., description="sys_id, name, or logical identifier")
    max_field_length: int = Field(
        default=DEFAULT_FIELD_LENGTH,
        description=f"Maximum length for each returned source field. Clamped to {MAX_FIELD_LENGTH}.",
    )


class ExtractTableDependenciesParams(BaseModel):
    scope: str | None = Field(
        default=None,
        description="App scope filter (sys_scope), e.g. x_company_bpm",
    )
    widget_id: str | None = Field(
        default=None,
        description="Limit to ONE widget (sys_id/id/name). Omit for a scope-wide scan.",
    )
    max_linked_script_includes: int = Field(
        default=DEFAULT_MAX_LINKED_SI,
        description=f"widget_id mode: max linked SIs to resolve. Clamped to {MAX_LINKED_SI}.",
    )
    include_widgets: bool = Field(
        default=True,
        description="Scan widget server scripts (sp_widget.script) for table dependencies",
    )
    include_business_rules: bool = Field(
        default=True,
        description="Scan business rules (sys_script.script) for table dependencies",
    )
    include_linked_script_includes: bool = Field(
        default=True,
        description="Also resolve + scan Script Includes referenced by scanned scripts.",
    )
    only_active: bool = Field(
        default=True,
        description="When supported by the source table, scan only active records",
    )
    max_records_per_source: int = Field(
        default=DEFAULT_DEP_SCAN_LIMIT,
        description=f"Maximum records scanned per source type. Clamped to {MAX_DEP_SCAN_LIMIT}.",
    )
    page_size: int = Field(
        default=DEFAULT_DEP_PAGE_SIZE,
        description="Fetch page size for each API call. Clamped to 10..200.",
    )
    include_loose_literal_scan: bool = Field(
        default=False,
        description="Also scan table-name-like string literals (higher recall, lower precision).",
    )


class ExtractWidgetTableDependenciesParams(BaseModel):
    widget_id: str = Field(..., description="Widget sys_id, id, or name")
    scope: str | None = Field(
        default=None,
        description="App scope filter (sys_scope), e.g. x_company_bpm",
    )
    include_linked_script_includes: bool = Field(
        default=True,
        description="Resolve script includes referenced by the widget and include their table dependencies",
    )
    only_active: bool = Field(
        default=True,
        description="When supported by table, include only active records",
    )
    include_loose_literal_scan: bool = Field(
        default=False,
        description="Also scan table-name-like string literals (higher recall, lower precision).",
    )
    max_linked_script_includes: int = Field(
        default=DEFAULT_MAX_LINKED_SI,
        description=f"Maximum linked script includes to resolve per widget. Clamped to {MAX_LINKED_SI}.",
    )


def _normalize_source_type(source_type: str) -> str:
    normalized = (source_type or SOURCE_TYPE_ALL).strip().lower()
    if normalized == SOURCE_TYPE_ALL or normalized in SOURCE_CONFIG:
        return normalized
    raise ValueError(f"Unsupported source_type '{source_type}'")


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_SEARCH_LIMIT))


def _clamp_field_length(field_length: int) -> int:
    return max(200, min(field_length, MAX_FIELD_LENGTH))


def _escape_query_value(value: str) -> str:
    return str(value).replace("^", "^^").replace("=", r"\=").replace("@", r"\@")


def _build_search_query(config: Dict[str, Any], params: SearchServerCodeParams) -> str:
    safe_query = _escape_query_value(params.query)
    query_parts: List[str] = [f"{field}LIKE{safe_query}" for field in config["search_fields"]]
    if params.scope:
        query_parts.append(f"sys_scope.scope={_escape_query_value(params.scope)}")
    if params.updated_by:
        query_parts.append(f"sys_updated_by={_escape_query_value(params.updated_by)}")
    return "^OR".join(query_parts[: len(config["search_fields"])]) + (
        "^" + "^".join(query_parts[len(config["search_fields"]) :])
        if len(query_parts) > len(config["search_fields"])
        else ""
    )


def _build_lookup_query(config: Dict[str, Any], source_id: str) -> str:
    safe_source_id = _escape_query_value(source_id)
    return "^OR".join(f"{field}={safe_source_id}" for field in config["lookup_fields"])


def _escape_query_fragment(value: str) -> str:
    return str(value).replace("^", "^^").replace("=", r"\=").replace("@", r"\@")


def _clamp_dep_scan_limit(value: int) -> int:
    return max(1, min(value, MAX_DEP_SCAN_LIMIT))


def _clamp_page_size(value: int) -> int:
    return max(10, min(value, 200))


def _clamp_linked_si_limit(value: int) -> int:
    return max(1, min(value, MAX_LINKED_SI))


def _build_dependency_query(
    *, scope: str | None, only_active: bool, source_table: str
) -> str | None:
    parts: List[str] = []
    if scope:
        parts.append(f"sys_scope.scope={_escape_query_fragment(scope)}")

    supports_active = source_table in {"sp_widget", "sys_script", "sys_script_include"}
    if only_active and supports_active:
        parts.append("active=true")

    return "^".join(parts) if parts else None


def _fetch_records_paginated(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    fields: List[str],
    query: str | None,
    page_size: int,
    max_records: int,
) -> List[Dict[str, Any]]:
    return sn_query_all(
        config,
        auth_manager,
        table=table,
        query=query or "",
        fields=",".join(fields),
        page_size=min(page_size, 100),
        max_records=max_records,
        display_value=False,
    )


def _normalize_table_candidate(candidate: str) -> str | None:
    token = candidate.strip().strip("\"'").lower()
    if not token:
        return None
    if TABLE_NAME_RE.match(token):
        return token
    return None


def _parse_string_arg(arg: str) -> str | None:
    value = arg.strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return _normalize_table_candidate(value[1:-1])
    return None


def _extract_table_names_from_script(
    script: str, *, include_loose_literal_scan: bool = False
) -> Set[str]:
    if not script:
        return set()

    tables: Set[str] = set()
    var_to_table: Dict[str, str] = {}

    for var_name, table_name in JS_TABLE_ASSIGNMENT_RE.findall(script):
        normalized = _normalize_table_candidate(table_name)
        if normalized:
            var_to_table[var_name] = normalized

    for _ctor_name, raw_arg in GLIDE_CONSTRUCTOR_RE.findall(script):
        direct = _parse_string_arg(raw_arg)
        if direct:
            tables.add(direct)
            continue

        var_name = raw_arg.strip()
        if var_name in var_to_table:
            tables.add(var_to_table[var_name])

    for table_name in GLIDE_DB_FUNCTION_RE.findall(script):
        normalized = _normalize_table_candidate(table_name)
        if normalized:
            tables.add(normalized)

    for table_name in GR_SET_TABLE_RE.findall(script):
        normalized = _normalize_table_candidate(table_name)
        if normalized:
            tables.add(normalized)

    if include_loose_literal_scan and len(tables) < MAX_TABLES_PER_RECORD:
        for candidate in STRING_TABLE_LITERAL_RE.findall(script):
            normalized = _normalize_table_candidate(candidate)
            if normalized:
                tables.add(normalized)
            if len(tables) >= MAX_TABLES_PER_RECORD:
                break

    return tables


def _extract_script_include_refs(script: str, known_script_include_names: Set[str]) -> Set[str]:
    if not script:
        return set()

    # Build a lookup dict that maps both full names and short (dotted-last) names
    # to the canonical known name — reduces two set lookups to one dict lookup.
    lookup: Dict[str, str] = {}
    for name in known_script_include_names:
        lookup[name] = name
        short = name.split(".")[-1]
        if short != name:
            lookup.setdefault(short, name)

    refs: Set[str] = set()
    for candidate in SCRIPT_INCLUDE_INSTANCE_RE.findall(script):
        found = lookup.get(candidate)
        if found:
            refs.add(found)
        else:
            short = candidate.split(".")[-1]
            found = lookup.get(short)
            if found:
                refs.add(found)
    return refs


def _extract_script_include_candidates(script: str) -> Set[str]:
    if not script:
        return set()

    candidates: Set[str] = set()
    for raw in SCRIPT_INCLUDE_INSTANCE_RE.findall(script):
        short_name = raw.split(".")[-1]
        if short_name and short_name not in IGNORED_CLASS_NAMES:
            candidates.add(short_name)
    return candidates


def _find_script_include_by_candidate(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    candidate: str,
    scope: str | None,
    only_active: bool,
) -> Dict[str, Any] | None:
    safe_candidate = _escape_query_fragment(candidate)
    query_parts = [
        f"name={safe_candidate}^ORapi_name={safe_candidate}^ORapi_nameENDSWITH.{safe_candidate}"
    ]
    if scope:
        query_parts.append(f"sys_scope.scope={_escape_query_fragment(scope)}")
    if only_active:
        query_parts.append("active=true")
    query = "^".join(query_parts)

    rows = _make_request(
        config,
        auth_manager,
        table="sys_script_include",
        query=query,
        fields=["sys_id", "name", "api_name", "script"],
        limit=1,
    )
    return rows[0] if rows else None


def _batch_resolve_script_includes(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    candidates: List[str],
    scope: str | None,
    only_active: bool,
) -> Dict[str, Dict[str, Any]]:
    """Resolve multiple SI candidates in batched queries instead of N+1."""
    if not candidates:
        return {}

    result_map: Dict[str, Dict[str, Any]] = {}
    safe_candidates = [(c, _escape_query_fragment(c)) for c in candidates]

    # Chunk size 20 — each candidate appears three times in the query
    # (nameIN, api_nameIN, api_nameENDSWITH.X), so 20 candidates produce
    # ~60 query slots. With ~30-char Script Include names, 50-chunk URLs
    # were hitting ServiceNow's "sysparm_query too long" 400 in the
    # field. Smaller chunks trade a few extra round-trips for reliability.
    for chunk in _chunked([s for _, s in safe_candidates], 20):
        name_in = ",".join(chunk)
        query_parts = [f"nameIN{name_in}^ORapi_nameIN{name_in}"]
        for sc in chunk:
            query_parts[0] += f"^ORapi_nameENDSWITH.{sc}"
        if scope:
            query_parts.append(f"sys_scope.scope={_escape_query_fragment(scope)}")
        if only_active:
            query_parts.append("active=true")
        query = "^".join(query_parts)

        rows = _make_request(
            config,
            auth_manager,
            table="sys_script_include",
            query=query,
            fields=["sys_id", "name", "api_name", "script"],
            limit=len(chunk) * 3,
        )

        row_index: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            rname = str(row.get("name") or "")
            rapi = str(row.get("api_name") or "")
            if rname:
                row_index.setdefault(rname, row)
            if rapi:
                row_index.setdefault(rapi, row)
                short = rapi.split(".")[-1]
                if short:
                    row_index.setdefault(short, row)

        for orig, safe in safe_candidates:
            if orig in result_map:
                continue
            match = row_index.get(orig) or row_index.get(safe)
            if match:
                result_map[orig] = match

    return result_map


def _chunked(values: List[str], size: int) -> List[List[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]


def _build_label_map(
    config: ServerConfig,
    auth_manager: AuthManager,
    table_names: Set[str],
) -> Dict[str, str]:
    if not table_names:
        return {}

    label_map: Dict[str, str] = {}
    sorted_names = sorted(table_names)
    for chunk in _chunked(sorted_names, 50):
        encoded_names = ",".join(_escape_query_fragment(name) for name in chunk)
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_db_object",
            query=f"nameIN{encoded_names}",
            fields="name,label",
            limit=100,
            offset=0,
            display_value=False,
            no_count=True,
            fail_silently=False,
        )
        for row in rows:
            name = row.get("name")
            label = row.get("label")
            if isinstance(name, str) and isinstance(label, str):
                label_map[name] = label

    return label_map


def _append_table_references(
    table_to_sources: Dict[str, List[Dict[str, str]]],
    source_type: str,
    source_sys_id: str,
    source_name: str,
    discovered_tables: Set[str],
) -> None:
    for table_name in discovered_tables:
        table_to_sources[table_name].append(
            {
                "source_type": source_type,
                "source_sys_id": source_sys_id,
                "source_name": source_name,
            }
        )


def _truncate_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[:max_length] + f"... (truncated, original length: {len(value)})"


def _make_request(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    table: str,
    query: str,
    fields: List[str],
    limit: int,
) -> List[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=",".join(fields),
        limit=limit,
        offset=0,
        display_value=True,
        fail_silently=False,
    )
    return rows


def _extract_match_fields(record: Dict[str, Any], fields: List[str], query: str) -> List[str]:
    lowered = query.lower()
    matched_fields: List[str] = []
    for field in fields:
        value = record.get(field)
        if isinstance(value, str) and lowered in value.lower():
            matched_fields.append(field)
    return matched_fields


def _build_snippet(record: Dict[str, Any], fields: List[str], query: str, max_length: int) -> str:
    lowered = query.lower()
    for field in fields:
        value = record.get(field)
        if not isinstance(value, str) or not value:
            continue
        index = value.lower().find(lowered)
        if index == -1:
            continue
        start = max(0, index - SNIPPET_RADIUS)
        end = min(len(value), index + len(query) + SNIPPET_RADIUS)
        return _truncate_text(value[start:end].strip(), max_length)
    return ""


@register_tool(
    "search_server_code",
    params=SearchServerCodeParams,
    description="Fast keyword search across 22 server-side code types (SI/BR/ACL). Portal regex+snippets: search_portal_regex_matches.",
    serialization="raw_dict",
    return_type=dict,
)
def search_server_code(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: SearchServerCodeParams,
) -> Dict[str, Any]:
    try:
        normalized_type = _normalize_source_type(params.source_type)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "results": []}

    limit = _clamp_limit(params.limit)
    source_types = (
        DEFAULT_SOURCE_TYPE_ORDER if normalized_type == SOURCE_TYPE_ALL else [normalized_type]
    )
    results: List[Dict[str, Any]] = []
    searched_types: List[str] = []

    for source_type in source_types:
        if len(results) >= limit:
            break
        searched_types.append(source_type)
        source_cfg = SOURCE_CONFIG[source_type]
        query = _build_search_query(source_cfg, params)
        fields = source_cfg["summary_fields"] + source_cfg["source_fields"]

        try:
            records = _make_request(
                config,
                auth_manager,
                table=source_cfg["table"],
                query=query,
                fields=fields,
                limit=min(PER_TYPE_LIMIT, max(1, limit - len(results))),
            )
        except Exception as exc:
            logger.error("Failed to search source type %s: %s", source_type, exc)
            continue

        found_in_current_type = False
        for record in records:
            matched_fields = _extract_match_fields(
                record, source_cfg["search_fields"], params.query
            )
            results.append(
                {
                    "source_type": source_type,
                    "table": source_cfg["table"],
                    "sys_id": record.get("sys_id"),
                    "name": record.get("name"),
                    "identifier": record.get(source_cfg["identifier_field"]) or record.get("name"),
                    "updated_on": record.get("sys_updated_on"),
                    "updated_by": record.get("sys_updated_by"),
                    "scope": record.get("sys_scope"),
                    "matched_fields": matched_fields,
                    "snippet": _build_snippet(
                        record,
                        source_cfg["source_fields"]
                        + ["name", source_cfg["identifier_field"], "description"],
                        params.query,
                        max(80, params.max_snippet_length),
                    ),
                }
            )
            found_in_current_type = True

        if normalized_type == SOURCE_TYPE_ALL and found_in_current_type:
            break

    trimmed_results = results[:limit]
    return {
        "success": True,
        "query": params.query,
        "searched_types": searched_types,
        "count": len(trimmed_results),
        "limit_applied": limit,
        "results": trimmed_results,
        "safety_notice": "Searches only supported source tables with capped limits and truncated snippets.",
    }


@register_tool(
    "get_metadata_source",
    params=GetMetadataSourceParams,
    description="Get a single source record (SI, BR, widget, etc.) by name or sys_id. Returns metadata + truncated script body.",
    serialization="raw_dict",
    return_type=dict,
)
def get_metadata_source(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetMetadataSourceParams,
) -> Dict[str, Any]:
    try:
        source_type = _normalize_source_type(params.source_type)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    if source_type == SOURCE_TYPE_ALL:
        return {"success": False, "message": "source_type must be a specific supported type"}

    source_cfg = SOURCE_CONFIG[source_type]
    fields = source_cfg["summary_fields"] + source_cfg["source_fields"]

    try:
        records = _make_request(
            config,
            auth_manager,
            table=source_cfg["table"],
            query=_build_lookup_query(source_cfg, params.source_id),
            fields=fields,
            limit=1,
        )
    except Exception as exc:
        logger.error("Failed to fetch source metadata for %s: %s", source_type, exc)
        return {
            "success": False,
            "message": f"Failed to fetch source from {source_cfg['table']}: {exc}",
        }

    if not records:
        return {
            "success": False,
            "message": f"Source not found for type '{source_type}' and id '{params.source_id}'",
        }

    record = records[0]
    metadata = {
        "source_type": source_type,
        "table": source_cfg["table"],
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
        "identifier": record.get(source_cfg["identifier_field"]) or record.get("name"),
        "updated_on": record.get("sys_updated_on"),
        "updated_by": record.get("sys_updated_by"),
        "scope": record.get("sys_scope"),
    }
    max_field_length = _clamp_field_length(params.max_field_length)
    sources = {
        field: _truncate_text(record.get(field, ""), max_field_length)
        for field in source_cfg["source_fields"]
        if record.get(field)
    }

    return {
        "success": True,
        "metadata": metadata,
        "sources": sources,
        "safety_notice": "Only supported source fields are returned, each with per-field truncation.",
    }


@register_tool(
    "extract_table_dependencies",
    params=ExtractTableDependenciesParams,
    description="GlideRecord table dependency graph from server scripts (SI/BR/widgets). Pass widget_id for one widget.",
    serialization="raw_dict",
    return_type=dict,
)
def extract_table_dependencies(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ExtractTableDependenciesParams,
) -> Dict[str, Any]:
    # widget_id present → single-widget mode (delegated to the widget scanner).
    if params.widget_id:
        return extract_widget_table_dependencies(
            config,
            auth_manager,
            ExtractWidgetTableDependenciesParams(
                widget_id=params.widget_id,
                scope=params.scope,
                include_linked_script_includes=params.include_linked_script_includes,
                only_active=params.only_active,
                include_loose_literal_scan=params.include_loose_literal_scan,
                max_linked_script_includes=params.max_linked_script_includes,
            ),
        )

    started = time.perf_counter()
    max_records = _clamp_dep_scan_limit(params.max_records_per_source)
    page_size = _clamp_page_size(params.page_size)

    table_to_sources: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    script_include_refs: Set[str] = set()

    scanned_counts: Counter[str] = Counter()
    failed_sources: List[Dict[str, str]] = []

    script_include_records: List[Dict[str, Any]] = []
    known_si_names: Set[str] = set()
    si_script_by_key: Dict[str, str] = {}

    if params.include_linked_script_includes:
        si_query = _build_dependency_query(
            scope=params.scope,
            only_active=params.only_active,
            source_table="sys_script_include",
        )
        try:
            script_include_records = _fetch_records_paginated(
                config,
                auth_manager,
                table="sys_script_include",
                fields=["sys_id", "name", "api_name", "script"],
                query=si_query,
                page_size=page_size,
                max_records=max_records,
            )
            scanned_counts["script_include_candidates"] = len(script_include_records)
            for row in script_include_records:
                name = row.get("name")
                api_name = row.get("api_name")
                script = row.get("script")
                if isinstance(name, str):
                    known_si_names.add(name)
                    if isinstance(script, str):
                        si_script_by_key[name] = script
                if isinstance(api_name, str):
                    known_si_names.add(api_name)
                    short_name = api_name.split(".")[-1]
                    if short_name:
                        known_si_names.add(short_name)
                    if isinstance(script, str):
                        si_script_by_key[api_name] = script
                        if short_name:
                            si_script_by_key[short_name] = script
        except Exception as exc:
            failed_sources.append(
                {
                    "source_type": "script_include_candidates",
                    "message": str(exc),
                }
            )

    if params.include_widgets:
        widget_query = _build_dependency_query(
            scope=params.scope,
            only_active=params.only_active,
            source_table="sp_widget",
        )
        try:
            widget_rows = _fetch_records_paginated(
                config,
                auth_manager,
                table="sp_widget",
                fields=["sys_id", "name", "id", "script"],
                query=widget_query,
                page_size=page_size,
                max_records=max_records,
            )
            scanned_counts["widget"] = len(widget_rows)
            for row in widget_rows:
                script = row.get("script")
                if not isinstance(script, str):
                    continue
                source_name = str(row.get("name") or row.get("id") or "")
                source_sys_id = str(row.get("sys_id") or "")

                discovered_tables = _extract_table_names_from_script(
                    script,
                    include_loose_literal_scan=params.include_loose_literal_scan,
                )
                _append_table_references(
                    table_to_sources,
                    "widget",
                    source_sys_id,
                    source_name,
                    discovered_tables,
                )

                if params.include_linked_script_includes and known_si_names:
                    refs = _extract_script_include_refs(script, known_si_names)
                    script_include_refs.update(refs)
        except Exception as exc:
            failed_sources.append({"source_type": "widget", "message": str(exc)})

    if params.include_business_rules:
        br_query = _build_dependency_query(
            scope=params.scope,
            only_active=params.only_active,
            source_table="sys_script",
        )
        try:
            br_rows = _fetch_records_paginated(
                config,
                auth_manager,
                table="sys_script",
                fields=["sys_id", "name", "collection", "script"],
                query=br_query,
                page_size=page_size,
                max_records=max_records,
            )
            scanned_counts["business_rule"] = len(br_rows)
            for row in br_rows:
                script = row.get("script")
                source_name = str(row.get("name") or "")
                source_sys_id = str(row.get("sys_id") or "")

                discovered_tables = set()
                if isinstance(script, str):
                    discovered_tables = _extract_table_names_from_script(
                        script,
                        include_loose_literal_scan=params.include_loose_literal_scan,
                    )
                collection = row.get("collection")
                if isinstance(collection, str):
                    normalized_collection = _normalize_table_candidate(collection)
                    if normalized_collection:
                        discovered_tables.add(normalized_collection)

                _append_table_references(
                    table_to_sources,
                    "business_rule",
                    source_sys_id,
                    source_name,
                    discovered_tables,
                )

                if (
                    params.include_linked_script_includes
                    and known_si_names
                    and isinstance(script, str)
                ):
                    refs = _extract_script_include_refs(script, known_si_names)
                    script_include_refs.update(refs)
        except Exception as exc:
            failed_sources.append({"source_type": "business_rule", "message": str(exc)})

    scanned_si_count = 0
    if params.include_linked_script_includes and script_include_refs:
        for ref_name in sorted(script_include_refs):
            script = si_script_by_key.get(ref_name)
            if not script:
                continue
            scanned_si_count += 1
            discovered_tables = _extract_table_names_from_script(
                script,
                include_loose_literal_scan=params.include_loose_literal_scan,
            )
            source_row = next(
                (row for row in script_include_records if row.get("name") == ref_name), None
            )
            source_sys_id = str(source_row.get("sys_id") if source_row else "")
            _append_table_references(
                table_to_sources,
                "script_include",
                source_sys_id,
                ref_name,
                discovered_tables,
            )

    scanned_counts["linked_script_include"] = scanned_si_count

    all_tables = set(table_to_sources.keys())
    try:
        label_map = _build_label_map(config, auth_manager, all_tables)
    except Exception as exc:
        label_map = {}
        failed_sources.append({"source_type": "sys_db_object", "message": str(exc)})

    table_entries: List[Dict[str, Any]] = []
    for table_name in sorted(all_tables):
        source_refs = table_to_sources[table_name]
        type_counter = Counter(ref["source_type"] for ref in source_refs)
        table_entries.append(
            {
                "table_name": table_name,
                "table_label": label_map.get(table_name, ""),
                "reference_count": len(source_refs),
                "source_type_counts": dict(type_counter),
                "sources": source_refs,
            }
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "success": True,
        "scope": params.scope,
        "scan_summary": {
            "widgets_scanned": scanned_counts["widget"],
            "business_rules_scanned": scanned_counts["business_rule"],
            "script_include_candidates_scanned": scanned_counts["script_include_candidates"],
            "linked_script_includes_scanned": scanned_counts["linked_script_include"],
            "tables_discovered": len(table_entries),
            "scan_duration_ms": elapsed_ms,
            "max_records_per_source": max_records,
            "page_size": page_size,
        },
        "tables": table_entries,
        "dependency_summary": {
            "referenced_script_include_count": len(script_include_refs),
            "referenced_script_includes": sorted(script_include_refs),
        },
        "warnings": failed_sources,
        "safety_notice": "Dependency graph output only. Raw script bodies are never returned to prevent context overload.",
    }


# Internal helper — no longer a standalone tool. Reached via
# extract_table_dependencies(widget_id=...) which delegates here. Kept as a
# function so the single-widget logic and its tests stay intact.
def extract_widget_table_dependencies(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ExtractWidgetTableDependenciesParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    table_to_sources: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    failed_sources: List[Dict[str, str]] = []

    widget_cfg = SOURCE_CONFIG["widget"]
    widget_query = _build_lookup_query(widget_cfg, params.widget_id)
    if params.scope:
        widget_query += f"^sys_scope.scope={_escape_query_fragment(params.scope)}"
    if params.only_active:
        widget_query += "^active=true"

    try:
        widget_rows = _make_request(
            config,
            auth_manager,
            table="sp_widget",
            query=widget_query,
            fields=["sys_id", "name", "id", "script", "sys_scope"],
            limit=1,
        )
    except Exception as exc:
        return {
            "success": False,
            "message": f"Failed to fetch widget: {exc}",
            "widget": None,
            "tables": [],
        }

    if not widget_rows:
        return {
            "success": False,
            "message": f"Widget not found for id '{params.widget_id}'",
            "widget": None,
            "tables": [],
        }

    widget = widget_rows[0]
    widget_sys_id = str(widget.get("sys_id") or "")
    widget_name = str(widget.get("name") or widget.get("id") or "")
    widget_identifier = str(widget.get("id") or widget.get("name") or "")
    widget_scope = str(widget.get("sys_scope") or "")
    widget_script = widget.get("script")

    if isinstance(widget_script, str):
        widget_tables = _extract_table_names_from_script(
            widget_script,
            include_loose_literal_scan=params.include_loose_literal_scan,
        )
        _append_table_references(
            table_to_sources,
            "widget",
            widget_sys_id,
            widget_name,
            widget_tables,
        )

    linked_script_includes: List[Dict[str, str]] = []
    linked_si_limit = _clamp_linked_si_limit(params.max_linked_script_includes)
    if params.include_linked_script_includes and isinstance(widget_script, str):
        si_candidates = sorted(_extract_script_include_candidates(widget_script))[:linked_si_limit]
        try:
            si_map = _batch_resolve_script_includes(
                config,
                auth_manager,
                candidates=si_candidates,
                scope=params.scope,
                only_active=params.only_active,
            )
        except Exception as exc:
            failed_sources.append(
                {
                    "source_type": "script_include_lookup",
                    "message": f"batch resolve: {exc}",
                }
            )
            si_map = {}
        for candidate in si_candidates:
            si_row = si_map.get(candidate)

            if not si_row:
                continue

            si_name = str(si_row.get("name") or candidate)
            si_api_name = str(si_row.get("api_name") or "")
            si_sys_id = str(si_row.get("sys_id") or "")
            linked_script_includes.append(
                {
                    "name": si_name,
                    "api_name": si_api_name,
                    "sys_id": si_sys_id,
                }
            )

            si_script = si_row.get("script")
            if isinstance(si_script, str):
                si_tables = _extract_table_names_from_script(
                    si_script,
                    include_loose_literal_scan=params.include_loose_literal_scan,
                )
                _append_table_references(
                    table_to_sources,
                    "script_include",
                    si_sys_id,
                    si_name,
                    si_tables,
                )

    all_tables = set(table_to_sources.keys())
    try:
        label_map = _build_label_map(config, auth_manager, all_tables)
    except Exception as exc:
        label_map = {}
        failed_sources.append({"source_type": "sys_db_object", "message": str(exc)})

    table_entries: List[Dict[str, Any]] = []
    for table_name in sorted(all_tables):
        refs = table_to_sources[table_name]
        type_counter = Counter(ref["source_type"] for ref in refs)
        table_entries.append(
            {
                "table_name": table_name,
                "table_label": label_map.get(table_name, ""),
                "reference_count": len(refs),
                "source_type_counts": dict(type_counter),
                "sources": refs,
            }
        )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "success": True,
        "widget": {
            "sys_id": widget_sys_id,
            "name": widget_name,
            "identifier": widget_identifier,
            "scope": widget_scope,
        },
        "scan_summary": {
            "linked_script_includes_scanned": len(linked_script_includes),
            "tables_discovered": len(table_entries),
            "scan_duration_ms": elapsed_ms,
            "max_linked_script_includes": linked_si_limit,
        },
        "tables": table_entries,
        "dependency_summary": {
            "linked_script_includes": linked_script_includes,
        },
        "warnings": failed_sources,
        "safety_notice": "Dependency graph output only. Raw script bodies are never returned to prevent context overload.",
    }


# ---------------------------------------------------------------------------
# Source download infrastructure
# ---------------------------------------------------------------------------

# File extension per source field — derived from the single source of truth in
# source_layout so the generic downloader writes the exact filenames the portal
# downloader and the uploader expect (no per-module drift). See source_layout.
_FIELD_EXTENSIONS: Dict[str, str] = {field: field_extension(field) for field in FIELD_FILENAME}

# Tables that support the 'active' field
_ACTIVE_SUPPORTED_TABLES = {
    "sys_script",
    "sys_script_include",
    "sys_ui_action",
    "sys_security_acl",
    "sys_script_fix",
    "sysauto_script",
    "sysevent_script_action",
    "sysevent_email_action",
    "catalog_script_client",
    "sys_ui_macro",
}


def _clamp_download_per_type(value: int) -> int:
    return max(1, min(value, MAX_DOWNLOAD_PER_TYPE))


# ---------------------------------------------------------------------------
# Dependency reference extraction patterns (cross-scope resolution)
# ---------------------------------------------------------------------------

_DEP_GS_INCLUDE_RE = re.compile(r"""\bgs\.include\s*\(\s*["']([^"']+)["']\s*\)""")
_DEP_WIDGET_EMBED_RE = re.compile(r"""<sp-widget\s+id=["']([^"']+)["']""", re.IGNORECASE)
_DEP_SP_WIDGET_RE = re.compile(r"""\$sp\.getWidget(?:FromInstance)?\s*\(\s*["']([^"']+)["']\s*\)""")
_DEP_INJECT_RE = re.compile(r"""\$inject\s*=\s*\[([^\]]+)\]""")
_DEP_ANGULAR_REQUIRES_RE = re.compile(
    r"""angular\.module\s*\(\s*["'][^"']*["']\s*,\s*\[([^\]]+)\]"""
)
# Client-side SI lookup: new GlideAjax('ScriptIncludeName')
_DEP_GLIDE_AJAX_RE = re.compile(r"""\bGlideAjax\s*\(\s*["']([A-Za-z_$][\w$.]*)["']""")
# Jelly macro references: <g:macro_name …> or <g2:macro_name …> (UI macros in global)
_DEP_JELLY_MACRO_RE = re.compile(r"""<g2?:([a-z][a-z0-9_]*)\b""", re.IGNORECASE)
_JELLY_BUILTIN_TAGS: Set[str] = {
    "evaluate",
    "if",
    "else",
    "elseif",
    "set",
    "include",
    "include_script",
    "insert",
    "call",
    "declare",
    "foreach",
    "for_each",
    "while",
    "break",
    "switch",
    "case",
    "default",
    "try",
    "catch",
    "throw",
    "return",
    "choose",
    "when",
    "otherwise",
    "ui_form",
    "ui_input_field",
    "ui_reference",
    "xml_to_json",
    "comment",
    "form",
    "panel",
    "tab",
    "section",
}


def _scan_scope_dep_refs(scope_root: Path) -> Dict[str, Set[str]]:
    """Scan downloaded source files for cross-scope (SI/widget/provider/ui_macro) refs."""
    si_refs: Set[str] = set()
    widget_refs: Set[str] = set()
    provider_refs: Set[str] = set()
    ui_macro_refs: Set[str] = set()

    for src_file in scope_root.rglob("*"):
        if not src_file.is_file():
            continue
        # Skip _deps folder to avoid re-scanning fetched deps
        if "_deps" in src_file.parts:
            continue
        if src_file.suffix.lower() not in {".js", ".html", ".xml"}:
            continue
        try:
            text = src_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for m in SCRIPT_INCLUDE_INSTANCE_RE.finditer(text):
            cls = m.group(1).split(".")[-1]
            if cls and cls[0].isupper() and cls not in IGNORED_CLASS_NAMES:
                si_refs.add(cls)
        for m in _DEP_GS_INCLUDE_RE.finditer(text):
            n = m.group(1).strip()
            if n:
                si_refs.add(n)
        for m in _DEP_GLIDE_AJAX_RE.finditer(text):
            n = m.group(1).strip()
            if n:
                si_refs.add(n)
        for wid in _DEP_WIDGET_EMBED_RE.findall(text):
            if wid:
                widget_refs.add(wid)
        for wid in _DEP_SP_WIDGET_RE.findall(text):
            if wid:
                widget_refs.add(wid)
        for block in _DEP_INJECT_RE.findall(text):
            for n in re.findall(r'["\']([^"\']+)["\']', block):
                if n:
                    provider_refs.add(n)
        for block in _DEP_ANGULAR_REQUIRES_RE.findall(text):
            for n in re.findall(r'["\']([^"\']+)["\']', block):
                if n:
                    provider_refs.add(n)
        # Jelly macros only appear in .xml / .html (legacy UI macros)
        if src_file.suffix.lower() in {".xml", ".html"}:
            for name in _DEP_JELLY_MACRO_RE.findall(text):
                n = name.lower()
                if n and n not in _JELLY_BUILTIN_TAGS:
                    ui_macro_refs.add(n)

    return {
        "script_includes": si_refs,
        "widgets": widget_refs,
        "angular_providers": provider_refs,
        "ui_macros": ui_macro_refs,
    }


def _collect_downloaded_names(scope_root: Path, table: str, id_field: str) -> Set[str]:
    """Identifier values already downloaded for a table.

    Reads BOTH metadata formats: the source download writes _metadata.json, the
    PORTAL download writes _widget.json (id lives in the nested "widget" payload).
    Counting only one made the dep resolver blind to portal-downloaded widgets, so
    it re-downloaded every widget on every run and kept recreating scope-prefixed
    folders. Both formats now count. The scope-stripped form is also added so a
    plain ref (e.g. $sp.getWidget('Name')) matches a scoped id (scope.Name).
    """
    names: Set[str] = set()
    table_dir = scope_root / table
    if not table_dir.is_dir():
        return names

    def _add(val: Any) -> None:
        if val:
            names.add(str(val))
            names.add(str(val).split(".")[-1])

    for meta_file in table_dir.rglob("_metadata.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
            _add(data.get(id_field) or data.get("name"))
        except (OSError, json.JSONDecodeError, AttributeError):
            # OSError: file vanished mid-scan; JSONDecodeError: corrupted metadata
            # written by a previous interrupted run; AttributeError: data is not a dict.
            pass
    for widget_file in table_dir.rglob("_widget.json"):
        try:
            data = json.loads(widget_file.read_text(encoding="utf-8"))
            payload = data.get("widget") if isinstance(data, dict) else None
            if isinstance(payload, dict):
                _add(payload.get(id_field) or payload.get("name"))
            _add(data.get("name") if isinstance(data, dict) else None)
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    return names


def _collect_downloaded_names_multi(base: Path, table: str, id_field: str) -> Set[str]:
    """Union of identifiers downloaded for `table` across ALL scope trees under base
    (temp/<instance>). Dependencies route to their own scope tree, so the resolver
    must look beyond the current app's scope_root to know a dep is already present —
    otherwise it re-fetches the same sibling-scope record on every pass."""
    names: Set[str] = set()
    if not base.is_dir():
        return names
    for child in sorted(base.iterdir()):
        if child.is_dir():
            names |= _collect_downloaded_names(child, table, id_field)
    return names


# Download concurrency cap. A single application scope can hold thousands of
# records across ~24 source types; fetched serially that overruns the client's
# 120s call timeout (a real scope measured ~4 min). Source types are mutually
# independent (own query, own scope_root/<table> dir), so we fan them out under
# this cap. Kept deliberately low so we stay well under per-instance rate limits
# / bot detection — the win is parallelism, not flooding the instance.
_DOWNLOAD_MAX_WORKERS = 4
_DEP_MAX_WORKERS = _DOWNLOAD_MAX_WORKERS  # max concurrent API calls during dep resolution
_DEP_CHUNK_SIZE = 30  # names per API query chunk (smaller = safer under rate limits)

# Markers that mean "no point retrying or fanning out more requests": the
# session/account can't authenticate to the API. Re-auth either already failed
# or would just produce another rejected session. When one parallel worker hits
# this, the rest abort instead of each firing the same doomed call (the "401
# bomb" — N source types × _DOWNLOAD_MAX_WORKERS all 401-ing at once).
_AUTH_FAILURE_MARKERS = (
    "fresh_session_rejected",
    "acl_blocked",
    "not authenticated",
    "401",
)


def _text_indicates_auth_failure(text: str) -> bool:
    """True when a message/error string carries an auth-failure marker."""
    t = (text or "").lower()
    return any(marker in t for marker in _AUTH_FAILURE_MARKERS)


def _is_auth_failure(exc: Exception) -> bool:
    """True when an exception indicates an unrecoverable auth failure."""
    return _text_indicates_auth_failure(str(exc))


_DEP_MAX_DEPTH_DEFAULT = 2  # transitive resolution passes (conservative default)
_DEP_MAX_DEPTH_CAP = 6  # hard ceiling — each extra pass fans out more API calls


def _dep_max_depth() -> int:
    """How many transitive dependency-resolution passes to run. Default is a
    conservative 2 (don't force deep resolution); raise it via
    SERVICENOW_DEP_MAX_DEPTH to chase longer cross-scope chains. Clamped to
    [1, _DEP_MAX_DEPTH_CAP] so a typo can't trigger runaway API fan-out."""
    raw = os.getenv("SERVICENOW_DEP_MAX_DEPTH", "").strip()
    if not raw:
        return _DEP_MAX_DEPTH_DEFAULT
    try:
        return max(1, min(int(raw), _DEP_MAX_DEPTH_CAP))
    except ValueError:
        return _DEP_MAX_DEPTH_DEFAULT


def _download_dep_records(
    config: ServerConfig,
    auth_manager: AuthManager,
    source_type: str,
    id_field: str,
    names: List[str],
    scope_root: Path,
    page_size: int,
) -> Dict[str, Any]:
    """Fetch records by name (no scope filter); route each to ITS OWN scope tree.

    A record is written under `<base>/<record_namespace>/{table}/<bare_name>` where
    base = scope_root.parent — so a global dependency lands in the `global` tree and
    an app-scope one in that app's tree, never buried under the scope that happened
    to pull it. Same-scope deps resolve back to scope_root. Returns the set of scope
    roots written (so the resolver can scan them for transitive refs).

    Parallel chunk queries are bounded by _DEP_MAX_WORKERS.
    Already-present files are skipped (idempotent / concurrency-safe).
    """
    if not names:
        return {"count": 0, "files": 0, "scope_roots": set()}

    cfg = SOURCE_CONFIG[source_type]
    table = cfg["table"]
    all_fields = list(cfg["summary_fields"]) + list(cfg["source_fields"])
    effective_page_size = min(page_size, 10) if cfg["source_fields"] else page_size

    chunks = _chunked(names, _DEP_CHUNK_SIZE)
    use_inner_page_parallel = len(chunks) <= 1

    def _fetch_chunk(chunk: List[str]) -> List[Dict[str, Any]]:
        escaped = ",".join(_escape_query_fragment(n) for n in chunk)
        try:
            return sn_query_all(
                config,
                auth_manager,
                table=table,
                query=f"{id_field}IN{escaped}",
                fields=",".join(all_fields),
                page_size=effective_page_size,
                max_records=500,
                # If dependency names split into multiple chunks, this function
                # already fans out chunk queries via _DEP_MAX_WORKERS. Keep
                # inner pagination sequential in that case so one download job
                # does not stack chunk-level and page-level parallelism. A
                # single chunk keeps the normal page fetch parallelism.
                parallel=use_inner_page_parallel,
                display_value=False,
            )
        except Exception as exc:
            logger.warning("dep fetch %s chunk: %s", source_type, exc)
            return []

    all_rows: List[Dict[str, Any]] = []
    if len(chunks) <= 1:
        all_rows = _fetch_chunk(chunks[0]) if chunks else []
    else:
        with ThreadPoolExecutor(max_workers=_DEP_MAX_WORKERS) as pool:
            for batch in pool.map(_fetch_chunk, chunks):
                all_rows.extend(batch)

    base = scope_root.parent
    fetched = 0
    file_count = 0
    written_roots: Set[str] = set()

    for record in all_rows:
        sys_id = str(record.get("sys_id") or "")
        # Route each dep to ITS OWN scope tree (global deps -> the 'global' tree,
        # app-scope deps -> that scope) so a record always lands at the same path
        # regardless of which download pulled it. The record's own namespace also
        # strips its prefix, so the folder is the same bare name as a direct download.
        ns = _record_scope_namespace(record, scope_root.name)
        rec_scope_root = base / _safe_filename(ns)
        _, safe_name = _record_identifier_and_folder(record, cfg, ns)
        rec_dir = rec_scope_root / table / safe_name
        meta_path = rec_dir / "_metadata.json"
        written_roots.add(str(rec_scope_root))

        # Skip if already present (idempotent — safe under concurrent calls)
        if meta_path.exists():
            continue

        metadata: Dict[str, Any] = {
            "source_type": source_type,
            "table": table,
            "sys_id": sys_id,
            "is_dependency": True,
            "scope_namespace": ns,
        }
        for sf in cfg["summary_fields"]:
            val = record.get(sf)
            if val is not None:
                metadata[sf] = str(val) if not isinstance(val, str) else val
        _dl_write_json(meta_path, metadata)
        fetched += 1

        for sf in cfg["source_fields"]:
            content = record.get(sf)
            if content and isinstance(content, str) and content.strip():
                ext = _FIELD_EXTENSIONS.get(sf, ".txt")
                dest = rec_dir / f"{sf}{ext}"
                if not dest.exists():
                    _dl_write_file(dest, content)
                    file_count += 1

    return {"count": fetched, "files": file_count, "scope_roots": written_roots}


def _auto_resolve_deps(
    config: ServerConfig,
    auth_manager: AuthManager,
    scope_root: Path,
    page_size: int,
) -> Dict[str, Any]:
    """Scan downloaded scope and fetch missing cross-scope SI/widget/provider/ui_macro deps.

    Saves deps into scope_root/{table}/ (same structure as main scope, marked
    with is_dependency=true in _metadata.json). Runs up to _dep_max_depth() passes
    to catch transitive dependencies. Names already attempted are never re-queried.
    """
    # Track all names ever attempted (avoids re-querying unfound names on next pass)
    attempted_si: Set[str] = set()
    attempted_widgets: Set[str] = set()
    attempted_providers: Set[str] = set()
    attempted_ui_macros: Set[str] = set()

    total_counts: Dict[str, Dict[str, int]] = {
        "script_include": {"count": 0, "files": 0},
        "widget": {"count": 0, "files": 0},
        "angular_provider": {"count": 0, "files": 0},
        "ui_macro": {"count": 0, "files": 0},
    }
    total_refs: Dict[str, int] = {
        "script_includes": 0,
        "widgets": 0,
        "angular_providers": 0,
        "ui_macros": 0,
    }

    base = scope_root.parent
    # Roots scanned for transitive refs: the app scope plus every sibling tree a
    # dep was routed into, so a routed dep's own refs are discovered on later passes.
    dep_roots: Set[Path] = {scope_root}

    def _saved_names(table: str, id_field: str) -> Set[str]:
        # Cross-scope: a dep already present in a SIBLING scope tree (e.g. global)
        # must count as downloaded so it is not re-fetched every pass. Counts BOTH
        # _metadata.json and the portal _widget.json format across all scope trees.
        return _collect_downloaded_names_multi(base, table, id_field)

    for depth in range(_dep_max_depth()):
        # Scan the app scope + every sibling tree deps were routed into (picks up
        # newly fetched deps from prior passes for transitive resolution).
        refs: Dict[str, Set[str]] = {
            "script_includes": set(),
            "widgets": set(),
            "angular_providers": set(),
            "ui_macros": set(),
        }
        for root in dep_roots:
            part = _scan_scope_dep_refs(root)
            for key in refs:
                refs[key] |= part.get(key, set())

        if depth == 0:
            total_refs["script_includes"] = len(refs["script_includes"])
            total_refs["widgets"] = len(refs["widgets"])
            total_refs["angular_providers"] = len(refs["angular_providers"])
            total_refs["ui_macros"] = len(refs.get("ui_macros", set()))

        si_saved = _saved_names("sys_script_include", "api_name")
        widget_saved = _saved_names("sp_widget", "id")
        provider_saved = _saved_names("sp_angular_provider", "name")
        ui_macro_saved = _saved_names("sys_ui_macro", "name")

        missing_si = [
            n for n in refs["script_includes"] if n not in si_saved and n not in attempted_si
        ]
        missing_widgets = [
            n for n in refs["widgets"] if n not in widget_saved and n not in attempted_widgets
        ]
        missing_providers = [
            n
            for n in refs["angular_providers"]
            if n not in provider_saved and n not in attempted_providers
        ]
        missing_ui_macros = [
            n
            for n in refs.get("ui_macros", set())
            if n not in ui_macro_saved and n not in attempted_ui_macros
        ]

        # Mark attempted before fetching — prevents infinite loops on not-found names
        attempted_si.update(missing_si)
        attempted_widgets.update(missing_widgets)
        attempted_providers.update(missing_providers)
        attempted_ui_macros.update(missing_ui_macros)

        if (
            not missing_si
            and not missing_widgets
            and not missing_providers
            and not missing_ui_macros
        ):
            break

        if missing_si:
            r = _download_dep_records(
                config, auth_manager, "script_include", "name", missing_si, scope_root, page_size
            )
            total_counts["script_include"]["count"] += r["count"]
            total_counts["script_include"]["files"] += r["files"]
            dep_roots |= {Path(p) for p in r.get("scope_roots", ())}

        if missing_widgets:
            r = _download_dep_records(
                config, auth_manager, "widget", "id", missing_widgets, scope_root, page_size
            )
            total_counts["widget"]["count"] += r["count"]
            total_counts["widget"]["files"] += r["files"]
            dep_roots |= {Path(p) for p in r.get("scope_roots", ())}

        if missing_providers:
            r = _download_dep_records(
                config,
                auth_manager,
                "angular_provider",
                "name",
                missing_providers,
                scope_root,
                page_size,
            )
            total_counts["angular_provider"]["count"] += r["count"]
            total_counts["angular_provider"]["files"] += r["files"]
            dep_roots |= {Path(p) for p in r.get("scope_roots", ())}

        if missing_ui_macros:
            r = _download_dep_records(
                config,
                auth_manager,
                "ui_macro",
                "name",
                missing_ui_macros,
                scope_root,
                page_size,
            )
            total_counts["ui_macro"]["count"] += r["count"]
            total_counts["ui_macro"]["files"] += r["files"]
            dep_roots |= {Path(p) for p in r.get("scope_roots", ())}

    # Record which sibling scopes hold this app's deps so audit/schema can include
    # exactly those trees (not unrelated apps) when scanning this scope.
    sibling_ns = sorted({r.name for r in dep_roots} - {scope_root.name})
    if sibling_ns:
        _dl_write_json(scope_root / "_dep_scopes.json", {"dep_scopes": sibling_ns})

    total_new = sum(v["count"] for v in total_counts.values())
    return {
        "refs_found": total_refs,
        "downloaded": {k: v for k, v in total_counts.items() if v["count"] > 0},
        "total_new_records": total_new,
        "dep_scopes": sibling_ns,
    }


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe.strip("._") or "unnamed"


def _strip_scope_prefix(identifier: str, scope: str) -> str:
    """Drop a redundant leading '<scope>.' from a record identifier.

    script_include is keyed on api_name ('x_app.Foo') while every other type uses
    the bare name ('Foo'); an SI with an empty api_name falls back to name. Writing
    the raw value therefore mixed 'x_app.Foo' and 'Foo' folders in one SI tree. The
    scope is already the parent directory, so the prefix is pure duplication — strip
    it so every folder lands in one consistent bare-name style.
    """
    prefix = f"{scope}."
    if scope and identifier.startswith(prefix):
        return identifier[len(prefix) :]
    return identifier


def _record_identifier_and_folder(
    record: Dict[str, Any], source_cfg: Dict[str, Any], scope: str
) -> tuple[str, str]:
    """Single source of truth for a downloaded record's identifier + folder name.

    Every download path (main scope loop, dependency fetch, by-name fetch) routes
    through this, so a record lands at the SAME readable path no matter how it was
    fetched. Order:
      1. identifier_field (api_name for SI) or `name`;
      2. if blank, compose from `folder_fields` (e.g. transform_script:
         map.name + when + order) so nameless tables stay readable, not a sys_id;
      3. else the sys_id (last resort);
      4. strip the redundant leading '<scope>.' — the scope is already the
         parent directory, so the prefix only duplicated it;
      5. sanitize to a filesystem-safe folder name.
    Returns (display_identifier, folder_name).
    """
    sys_id = str(record.get("sys_id") or "")
    name = record.get(source_cfg["identifier_field"]) or record.get("name")
    if not name:
        folder_fields = source_cfg.get("folder_fields")
        if folder_fields:
            name = "_".join(str(record[f]) for f in folder_fields if record.get(f))
    name = str(name or sys_id)
    return name, _safe_filename(_strip_scope_prefix(name, scope))


def _record_scope_namespace(record: Dict[str, Any], fallback: str) -> str:
    """The record's own application scope namespace (e.g. 'x_app', 'global').

    Under display_value=False, sys_scope is a sys_id, so the reliable source is the
    dot-walked 'sys_scope.scope' field (added to every scope-scoped summary_fields).
    For script includes the api_name prefix ('x_app.Foo') is a secondary source.
    Falls back to the current download scope when neither is present, so an unknown
    namespace never mis-routes a record away from where it would already land.
    """
    ns = str(record.get("sys_scope.scope") or "").strip()
    if not ns:
        api = str(record.get("api_name") or "")
        if "." in api:
            ns = api.split(".", 1)[0].strip()
    return ns or fallback


def _dl_write_file(path: Path, content: str) -> None:
    # Atomic: an interrupted download never leaves a truncated file that
    # resume-skip would later trust as "already downloaded".
    atomic_write_text(path, content)


def _dl_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))


def _resolve_scope_root(
    config: ServerConfig,
    scope: str,
    output_dir: Optional[str],
) -> tuple[Path, Path]:
    """Returns (root, scope_root) paths.

    When ``output_dir`` is provided, it is treated as the final scope root —
    no instance/scope segments are appended. This avoids duplicated nesting
    like ``temp/inst/x_app/inst/x_app`` when callers pre-build the full path.
    Default (no ``output_dir``): ``./temp/{instance}/{scope}``.
    """
    scope_name = _safe_filename(scope)
    if output_dir:
        scope_root = Path(output_dir).expanduser().resolve()
    else:
        instance_name = (urlparse(config.instance_url).hostname or "instance").split(".")[0]
        scope_root = Path.cwd() / "temp" / instance_name / scope_name
    root = scope_root.parent
    scope_root.mkdir(parents=True, exist_ok=True)
    return root, scope_root


def _retry_empty_source(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    source_fields: List[str],
    source_type: str,
    record: tuple,
    warnings: List[str],
) -> int:
    """Fetch source for a single record that came back empty in batch. Returns file count."""
    rid, rname, rdir = record
    fetched = 0
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=f"sys_id={rid}",
            fields=",".join(source_fields),
            limit=1,
            offset=0,
            display_value=False,
            no_count=True,
        )
        if rows:
            for sf in source_fields:
                content = rows[0].get(sf)
                if content and isinstance(content, str) and content.strip():
                    ext = _FIELD_EXTENSIONS.get(sf, ".txt")
                    _dl_write_file(rdir / f"{sf}{ext}", content)
                    fetched += 1
    except Exception as exc:
        warnings.append(f"{source_type}/{rname}: retry failed — {exc}")
    return fetched


def _download_source_types(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    scope: str,
    source_types: List[str],
    scope_root: Path,
    root: Path,
    max_per_type: int = DEFAULT_DOWNLOAD_PER_TYPE,
    page_size: int = DEFAULT_DOWNLOAD_PAGE_SIZE,
    only_active: bool = False,
    extra_query: Optional[Dict[str, str]] = None,
    query_override: Optional[Dict[str, str]] = None,
    skip_empty_source_retry: Optional[Set[str]] = None,
    incremental: bool = False,
    reconcile_deletions: bool = False,
    emit_per_type: bool = False,
) -> Dict[str, Any]:
    """Core download loop shared by all individual download tools.

    Args:
        extra_query: Per-source_type extra query clauses (e.g. {"acl": "scriptISNOTEMPTY"}).
        query_override: Per-source_type full query replacement (replaces sys_scope filter).
        skip_empty_source_retry: Source types whose blank source fields are valid and
            should not trigger per-record retry.
        incremental: Only fetch records changed since last sync (sys_updated_on watermark
            read from each family's _sync_meta.json). Disables the resume-skip so changed
            records overwrite stale local files.
        reconcile_deletions: Warn (no auto-delete) about records present locally but gone
            remotely, via a sys_id-only list query per family.

    Returns dict with keys: type_results, manifest_entries, warnings, total_files,
    deletion_candidates.
    """
    max_per_type = _clamp_download_per_type(max_per_type)
    page_size = max(10, min(page_size, 100))
    extra_query = extra_query or {}
    skip_empty_source_retry = skip_empty_source_retry or set()

    type_results: Dict[str, Dict[str, Any]] = {}
    manifest_entries: List[Dict[str, Any]] = []
    warnings: List[str] = []
    deletion_candidates: Dict[str, List[str]] = {}
    total_files = 0

    # Tripped by the first worker that hits an unrecoverable auth failure, so
    # the remaining (queued) types bail immediately instead of each re-firing
    # the same doomed call against a dead session.
    auth_failure = threading.Event()

    def _process_one_type(source_type):
        # Per-type LOCAL accumulators. Threads never touch the shared outer
        # accumulators — each type's partial result is merged back in input
        # order after the parallel run, so output stays deterministic.
        type_results: Dict[str, Dict[str, Any]] = {}
        manifest_entries: List[Dict[str, Any]] = []
        warnings: List[str] = []
        deletion_candidates: Dict[str, List[str]] = {}
        total_files = 0

        # Fail-fast: a sibling type already proved auth is dead. Skip silently
        # (the originating type carries the actionable error) — no 401 bomb.
        if auth_failure.is_set():
            type_results[source_type] = {"count": 0, "skipped": "auth_failure_abort"}
            return type_results, manifest_entries, warnings, deletion_candidates, total_files

        if source_type not in SOURCE_CONFIG:
            warnings.append(f"Unknown source type: {source_type}")
            return type_results, manifest_entries, warnings, deletion_candidates, total_files

        source_cfg = SOURCE_CONFIG[source_type]
        table = source_cfg["table"]
        type_dir = scope_root / table

        all_fields = list(source_cfg["summary_fields"]) + list(source_cfg["source_fields"])
        restrict_source_page_size = (
            bool(source_cfg["source_fields"]) and source_type not in skip_empty_source_retry
        )
        effective_page_size = min(page_size, 10) if restrict_source_page_size else page_size

        # Build base query filters (active, extra)
        base_filters: List[str] = []
        if only_active and table in _ACTIVE_SUPPORTED_TABLES:
            base_filters.append("active=true")
        if source_type in extra_query:
            base_filters.append(extra_query[source_type])

        # Incremental: only fetch records changed since the last sync. Watermark
        # uses server-side sys_updated_on (no client clock skew). Empty watermark
        # (first run / no _sync_meta) falls back to a full download.
        watermark = max_sync_updated_on(type_dir / "_sync_meta.json") if incremental else ""
        if watermark:
            base_filters.append(f"sys_updated_on>={watermark}")

        if query_override and source_type in query_override:
            parts = [query_override[source_type]] + base_filters
        else:
            parts = [f"sys_scope.scope={scope}"] + base_filters
        query = "^".join(parts)

        # Deletion reconcile (warn-only): records present locally but gone remotely.
        if reconcile_deletions:
            local_ids = map_sys_ids(type_dir / "_map.json")
            if local_ids:
                recon_query = (
                    query_override[source_type]
                    if (query_override and source_type in query_override)
                    else f"sys_scope.scope={scope}"
                )
                try:
                    remote_ids = {
                        str(r.get("sys_id") or "")
                        for r in sn_query_all(
                            config,
                            auth_manager,
                            table=table,
                            query=recon_query,
                            fields="sys_id",
                            page_size=page_size,
                            max_records=max_per_type,
                            display_value=False,
                            fail_silently=True,
                            # Serial paging: types already fan out under the
                            # _DOWNLOAD_MAX_WORKERS cap, so this worker must not
                            # also borrow the shared page pool (would stack >cap).
                            parallel=False,
                        )
                        if r.get("sys_id")
                    }
                    gone = sorted(local_ids - remote_ids)
                    if gone:
                        deletion_candidates[source_type] = gone
                        warnings.append(
                            f"{source_type}: reconcile — {len(gone)} local record(s) no longer "
                            "exist remotely (deletion candidates, not removed): "
                            + ", ".join(gone[:20])
                        )
                except Exception as exc:  # reconcile is best-effort, never fatal
                    warnings.append(f"{source_type}: reconcile check failed — {exc}")

        _last_exc: Optional[Exception] = None
        records: List[Dict[str, Any]] = []
        for _attempt in range(_RETRY_MAX_ATTEMPTS + 1):
            try:
                records = sn_query_all(
                    config,
                    auth_manager,
                    table=table,
                    query=query,
                    fields=",".join(all_fields),
                    page_size=effective_page_size,
                    max_records=max_per_type,
                    display_value=False,
                    fail_silently=False,
                    # Serial paging — see reconcile call above. Per-type workers
                    # run under the cap; the shared page pool stays unused here.
                    parallel=False,
                )
                _last_exc = None
                break
            except Exception as exc:
                _last_exc = exc
                if _attempt < _RETRY_MAX_ATTEMPTS and _is_retryable(exc):
                    _delay = _retry_delay(_attempt)
                    logger.warning(
                        "Transient error on %s (attempt %d/%d), retrying in %.1fs: %s",
                        source_type,
                        _attempt + 1,
                        _RETRY_MAX_ATTEMPTS + 1,
                        _delay,
                        exc,
                    )
                    time.sleep(_delay)
                else:
                    break
        if _last_exc is not None:
            logger.error("Failed to download %s: %s", source_type, _last_exc)
            # Auth failure → trip the shared flag so queued types abort instead
            # of re-firing. Re-auth already failed (or would); retrying is just
            # a 401 bomb. The error message stays actionable ("re-login needed").
            if _is_auth_failure(_last_exc):
                auth_failure.set()
                warnings.append(
                    f"{source_type}: auth failed — {_last_exc}. Download aborted; "
                    "remaining source types skipped. Re-authenticate and retry."
                )
            else:
                warnings.append(f"{source_type}: fetch failed — {_last_exc}")
            type_results[source_type] = {"count": 0, "error": str(_last_exc)}
            return type_results, manifest_entries, warnings, deletion_candidates, total_files

        if not records:
            type_results[source_type] = {"count": 0}
            return type_results, manifest_entries, warnings, deletion_candidates, total_files

        # Completeness guard: sn_query_all returns exactly `max_per_type` rows
        # only when the scope holds at least that many, so hitting the cap means
        # records were almost certainly left behind. Surface it loudly — a silent
        # cap makes an incomplete download look complete. Zero extra API cost.
        capped = len(records) >= max_per_type
        if capped:
            warnings.append(
                f"{source_type}: INCOMPLETE — fetched {len(records)} records, which equals the "
                f"max_records_per_type cap ({max_per_type}). The scope likely has more that were "
                f"NOT downloaded. Re-run with a higher max_records_per_type to capture everything."
            )

        type_dir = scope_root / table
        name_map: Dict[str, str] = {}
        sync_meta: Dict[str, Dict[str, str]] = {}
        # Prior on-disk watermarks. Used by the resume-skip branch to preserve a
        # record's existing sys_updated_on (never bump a skipped record to the
        # current remote value) and to flag local copies that went stale.
        prior_meta = read_download_map(type_dir / "_sync_meta.json")
        stale_skipped: List[Dict[str, str]] = []
        # Records whose resume-skip preserved existing files but had to backfill
        # one or more source-field files a prior download left missing.
        backfilled_records: List[str] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        type_file_count = 0
        retry_records: List[tuple] = []

        for record in records:
            sys_id = str(record.get("sys_id") or "")
            name, safe_name = _record_identifier_and_folder(record, source_cfg, scope)

            metadata: Dict[str, Any] = {
                "source_type": source_type,
                "table": table,
                "sys_id": sys_id,
            }
            for sf in source_cfg["summary_fields"]:
                val = record.get(sf)
                if val is not None:
                    metadata[sf] = str(val) if not isinstance(val, str) else val

            record_dir = type_dir / safe_name

            # Resume: a record downloaded in a previous run keeps its local files
            # (which may hold the user's own edits) instead of being re-written.
            # Disabled under incremental — a returned record changed, so its
            # stale local file must be overwritten, not preserved.
            #
            # The skip is PER FIELD, not all-or-nothing: a prior run may have
            # written some source fields but not others (interrupted download, or
            # a field that was empty then and has content now). Existing files are
            # preserved; MISSING ones are backfilled from the batch content already
            # in hand — no extra API call. Without this, one present field (e.g.
            # template) marked the whole record "already downloaded" and a
            # genuinely-missing field (e.g. client_script) never landed: a silent
            # "success" with the file not actually on disk.
            if source_cfg["source_fields"] and not incremental:
                field_paths = {
                    sf: record_dir / f"{sf}{_FIELD_EXTENSIONS.get(sf, '.txt')}"
                    for sf in source_cfg["source_fields"]
                }
                present = {sf for sf, p in field_paths.items() if p.exists()}
                if present:
                    name_map[safe_name] = sys_id
                    # Backfill only the MISSING field files; never clobber an
                    # existing local file. Prefer the batch content already in
                    # hand (no API call); for any field the batch left blank
                    # (some instances return empty source in bulk), do ONE
                    # targeted page fetch restricted to the missing fields so
                    # existing files stay untouched.
                    backfilled = 0
                    still_missing: List[str] = []
                    for sf in source_cfg["source_fields"]:
                        if sf in present:
                            continue
                        content = record.get(sf)
                        if content and isinstance(content, str) and content.strip():
                            _dl_write_file(field_paths[sf], content)
                            backfilled += 1
                        else:
                            still_missing.append(sf)
                    if still_missing and sys_id:
                        backfilled += _retry_empty_source(
                            config,
                            auth_manager,
                            table,
                            still_missing,
                            source_type,
                            (sys_id, safe_name, record_dir),
                            warnings,
                        )
                    if backfilled:
                        backfilled_records.append(name)
                    # Resume-skip watermark rule (unchanged): the preserved local
                    # files may be older than the remote, so DON'T bump the sync
                    # watermark — leave the key out of sync_meta so merge_map_file
                    # keeps the prior entry and a later push can flag the conflict.
                    remote_updated = str(record.get("sys_updated_on") or "")
                    prior_updated = str(prior_meta.get(safe_name, {}).get("sys_updated_on") or "")
                    if prior_updated and remote_updated and remote_updated > prior_updated:
                        stale_skipped.append(
                            {
                                "name": name,
                                "sys_id": sys_id,
                                "local_sys_updated_on": prior_updated,
                                "remote_sys_updated_on": remote_updated,
                            }
                        )
                    type_file_count += len(present) + backfilled
                    continue

            _dl_write_json(record_dir / "_metadata.json", metadata)

            # Write source from batch response
            has_source = False
            for source_field in source_cfg["source_fields"]:
                content = record.get(source_field)
                if not content or not isinstance(content, str) or not content.strip():
                    continue
                has_source = True
                ext = _FIELD_EXTENSIONS.get(source_field, ".txt")
                _dl_write_file(record_dir / f"{source_field}{ext}", content)
                type_file_count += 1

            # Queue for individual retry if batch returned empty source
            if (
                not has_source
                and sys_id
                and source_cfg["source_fields"]
                and source_type not in skip_empty_source_retry
            ):
                retry_records.append((sys_id, safe_name, record_dir))

            name_map[safe_name] = sys_id
            sync_meta[safe_name] = {
                "sys_id": sys_id,
                "name": name,
                "sys_updated_on": str(record.get("sys_updated_on") or ""),
                # Named baseline: WHO owned the record at download. Free —
                # sys_updated_by is already in every family's summary_fields. Lets
                # a later push/diff say "you downloaded when X owned it".
                "sys_updated_by": str(record.get("sys_updated_by") or ""),
                "downloaded_at": now_iso,
            }
            manifest_entries.append(
                {
                    "source_type": source_type,
                    "table": table,
                    "sys_id": sys_id,
                    "name": name,
                    "path": str(record_dir.relative_to(root)),
                }
            )

        # Serial retry: the concurrency budget is already spent fanning out
        # source types, so empty-source records are re-fetched serially here.
        # Keeps total in-flight API calls at the cap instead of workers × types.
        if retry_records:
            _src_fields = list(source_cfg["source_fields"])
            for rec in retry_records:
                type_file_count += _retry_empty_source(
                    config, auth_manager, table, _src_fields, source_type, rec, warnings
                )

        merge_map_file(
            type_dir / "_map.json",
            name_map,
            writer=_dl_write_json,
            label=f"source_{source_type}",
        )
        merge_map_file(
            type_dir / "_sync_meta.json",
            sync_meta,
            writer=_dl_write_json,
            label=f"source_{source_type}_sync_meta",
        )
        if stale_skipped:
            names = ", ".join(s["name"] for s in stale_skipped[:10])
            more = "" if len(stale_skipped) <= 10 else f" (+{len(stale_skipped) - 10} more)"
            warnings.append(
                f"{source_type}: {len(stale_skipped)} local file(s) are OLDER than the server — "
                f"the remote changed after your download, but resume kept your local copy. Nothing "
                f"was overwritten (the sync watermark was preserved, so a push will flag the "
                f"conflict). Re-download with incremental=true to pull the server's version: "
                f"{names}{more}"
            )

        if backfilled_records:
            names = ", ".join(backfilled_records[:10])
            more = (
                "" if len(backfilled_records) <= 10 else f" (+{len(backfilled_records) - 10} more)"
            )
            warnings.append(
                f"{source_type}: backfilled missing source file(s) for "
                f"{len(backfilled_records)} record(s) a prior download left incomplete "
                f"(existing files untouched): {names}{more}"
            )

        type_results[source_type] = {
            "count": len(records),
            "files": type_file_count,
            "path": str(type_dir.relative_to(root)),
            # Machine-readable completeness flag so any analysis built on this
            # tree can refuse/flag instead of trusting a truncated source.
            "capped": capped,
        }
        if backfilled_records:
            # Disk-truth signal: records whose missing field files were just
            # filled in (= a prior "success" had not actually written them).
            type_results[source_type]["backfilled"] = len(backfilled_records)
        total_files += type_file_count
        return type_results, manifest_entries, warnings, deletion_candidates, total_files

    # Fan out source types under the concurrency cap. They are independent
    # (own query, own scope_root/<table> dir — verified no two types share a
    # table), so the only shared state is the merged result, combined below in
    # input order for deterministic output. pool.map preserves that order.
    # submit + as_completed (not pool.map) so each finished type can stream a
    # progress tick as it lands; results are reassembled in input order below so
    # output stays deterministic regardless of completion order. emit_per_type is
    # set ONLY by standalone download_server_sources — download_app_sources owns
    # its own per-STAGE counter (_run_stage), and mixing a per-type counter that
    # restarts at 1 each group call would make progress non-monotonic there. emit
    # runs in the orchestrator thread, where the progress contextvar is live
    # (worker threads don't inherit it); it's a no-op without a whitelisted token.
    total_types = len(source_types)
    results_by_type: Dict[str, tuple] = {}
    with ThreadPoolExecutor(max_workers=_DOWNLOAD_MAX_WORKERS) as pool:
        future_to_type = {pool.submit(_process_one_type, st): st for st in source_types}
        done = 0
        for fut in as_completed(future_to_type):
            st = future_to_type[fut]
            results_by_type[st] = fut.result()
            done += 1
            if emit_per_type:
                emit_progress(done, total_types, f"downloaded: {st}")
    per_type_results = [results_by_type[st] for st in source_types]

    for tr, me, wn, dc, fc in per_type_results:
        type_results.update(tr)
        manifest_entries.extend(me)
        warnings.extend(wn)
        deletion_candidates.update(dc)
        total_files += fc

    return {
        "type_results": type_results,
        "manifest_entries": manifest_entries,
        "warnings": warnings,
        "total_files": total_files,
        "deletion_candidates": deletion_candidates,
    }


def _build_download_result(
    scope: str,
    scope_root: Path,
    dl: Dict[str, Any],
    elapsed_ms: int,
    tool_name: str,
    scope_resolution: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a standard return dict from _download_source_types output."""
    result: Dict[str, Any] = {
        "success": True,
        "tool": tool_name,
        "scope": scope,
        "output_root": str(scope_root),
        "duration_ms": elapsed_ms,
        "source_types": dl["type_results"],
        "total_records": sum(r.get("count", 0) for r in dl["type_results"].values()),
        "total_files": dl["total_files"],
        "safety_notice": (
            "All source files written to disk in full — no truncation. "
            "Only this summary is returned to the conversation context."
        ),
    }
    # The scope the download resolved to drives the folder name; surface it as
    # its own field (not buried in warnings) so the caller sees where it landed.
    if scope_resolution:
        result["scope_resolution"] = scope_resolution
    if dl["warnings"]:
        result["warnings"] = dl["warnings"]
    return result


# --- Common params mixin ---


class _ScopeDownloadParams(BaseModel):
    scope: str = Field(
        ..., description="Scope namespace (x_app) or app name; auto-resolved to the namespace."
    )
    max_records_per_type: int = Field(
        default=DEFAULT_DOWNLOAD_PER_TYPE,
        description=f"Max records per type. Clamped to {MAX_DOWNLOAD_PER_TYPE}.",
    )
    page_size: int = Field(
        default=DEFAULT_DOWNLOAD_PAGE_SIZE, description="Records per page (10..100)."
    )
    only_active: bool = Field(default=False, description="Download only active records.")
    output_dir: Optional[str] = Field(
        default=None,
        description="Omit — default path is canonical and reused. Set only for one-off export.",
    )


# ---------------------------------------------------------------------------
# Individual download tools (each registered as MCP tool, also called by
# download_app_sources orchestrator)
# ---------------------------------------------------------------------------

_SCRIPT_INCLUDE_TYPES = ["script_include"]
_SERVER_SCRIPT_TYPES = ["business_rule", "client_script", "catalog_client_script"]
_UI_COMPONENT_TYPES = ["ui_action", "ui_script", "ui_page", "ui_macro"]
_API_SOURCE_TYPES = ["scripted_rest", "processor"]
_SECURITY_SOURCE_TYPES = ["acl"]
_ADMIN_SCRIPT_TYPES = [
    "fix_script",
    "scheduled_job",
    "script_action",
    "email_notification",
    "transform_script",
]


# Consolidated targeted source-family download. The former six per-family tools
# (download_script_includes/server_scripts/ui_components/api_sources/
# security_sources/admin_scripts) were byte-identical but for their source-type
# list — collapsed into one tool with a `families` param to cut the LLM context
# cost of `full` without losing the targeted-refresh capability. download_app_sources
# still orchestrates a FULL dump; both call _download_source_types directly.

# family name -> source types. Short, intent-clear names for the LLM.
_SOURCE_FAMILIES: Dict[str, List[str]] = {
    "script_includes": _SCRIPT_INCLUDE_TYPES,
    "server_scripts": _SERVER_SCRIPT_TYPES,  # business rules, client + catalog client scripts
    "ui": _UI_COMPONENT_TYPES,  # UI actions/scripts/pages/macros
    "api": _API_SOURCE_TYPES,  # scripted REST + processors
    "security": _SECURITY_SOURCE_TYPES,  # ACLs
    "admin": _ADMIN_SCRIPT_TYPES,  # fix scripts, scheduled jobs, script actions, notifications, transforms
}
_SOURCE_FAMILY_NAMES = sorted(_SOURCE_FAMILIES)


class DownloadSourcesParams(_ScopeDownloadParams):
    families: List[str] = Field(
        ...,
        description="Families: script_includes, server_scripts, ui, api, security, admin.",
    )
    acl_script_only: bool = Field(
        default=True, description="security family: only ACLs that have a script."
    )


@register_tool(
    "download_server_sources",
    params=DownloadSourcesParams,
    description="Targeted server-side source families (SIs/BRs/UI/api/security/admin). Whole app: download_app_sources.",
    serialization="raw_dict",
    return_type=dict,
)
def download_server_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadSourcesParams,
) -> Dict[str, Any]:
    if not params.families:
        return {"success": False, "message": "Specify at least one source family."}
    unknown = [f for f in params.families if f not in _SOURCE_FAMILIES]
    if unknown:
        return {
            "success": False,
            "message": (
                f"Unknown source families: {unknown}. Valid: {', '.join(_SOURCE_FAMILY_NAMES)}."
            ),
        }

    params, scope_resolution = apply_scope_namespace(config, auth_manager, params)
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)

    # Preserve request order, de-dupe (families don't overlap today, but be safe).
    source_types: List[str] = []
    for fam in params.families:
        for t in _SOURCE_FAMILIES[fam]:
            if t not in source_types:
                source_types.append(t)

    extra_q: Dict[str, str] = {}
    skip_empty_source_retry: Set[str] = set()
    if "security" in params.families:
        if params.acl_script_only:
            extra_q["acl"] = "scriptISNOTEMPTY"
        else:
            skip_empty_source_retry = {"acl"}

    dl = _download_source_types(
        config,
        auth_manager,
        scope=params.scope,
        source_types=source_types,
        scope_root=scope_root,
        root=root,
        max_per_type=params.max_records_per_type,
        page_size=params.page_size,
        only_active=params.only_active,
        extra_query=extra_q or None,
        skip_empty_source_retry=skip_empty_source_retry or None,
        emit_per_type=True,
    )
    return _build_download_result(
        params.scope,
        scope_root,
        dl,
        int((time.perf_counter() - started) * 1000),
        "download_server_sources",
        scope_resolution=scope_resolution,
    )


# ---------------------------------------------------------------------------
# 7. download_table_schema
# ---------------------------------------------------------------------------


class DownloadTableSchemaParams(BaseModel):
    tables: Optional[List[str]] = Field(
        default=None,
        description="Tables to fetch schema for; omitted = auto-scan source_root for refs.",
    )
    source_root: Optional[str] = Field(
        default=None,
        description="Downloaded source dir (e.g. temp/<inst>/<scope>); scanned for GlideRecord refs.",
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Where to write schema JSON files. Defaults to <source_root>/_schema/",
    )


def _scan_tables_from_source_root(source_root: Path) -> Set[str]:
    """Scan .js/.html files for GlideRecord table references across source_root AND
    the sibling scope trees its dependencies were routed into."""
    tables: Set[str] = set()
    for root in [source_root, *dep_scope_roots(source_root)]:
        for js_file in root.rglob("*.js"):
            try:
                script_text = js_file.read_text(encoding="utf-8")
                tables.update(
                    _extract_table_names_from_script(script_text, include_loose_literal_scan=False)
                )
            except (OSError, UnicodeDecodeError):
                pass
        for meta_file in root.rglob("_metadata.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                for field in ("collection", "table"):
                    val = meta.get(field)
                    if isinstance(val, str) and TABLE_NAME_RE.match(val):
                        tables.add(val)
            except (OSError, json.JSONDecodeError, AttributeError):
                pass
    return tables


def _fetch_and_write_schema(
    config: ServerConfig,
    auth_manager: AuthManager,
    table_names: Set[str],
    schema_dir: Path,
) -> tuple[Dict[str, int], List[str]]:
    """Fetch sys_dictionary for given tables and write per-table JSON files."""
    schema_dir.mkdir(parents=True, exist_ok=True)
    schema_results: Dict[str, int] = {}
    warnings: List[str] = []

    for table_chunk in _chunked(sorted(table_names), 50):
        encoded_names = ",".join(table_chunk)
        try:
            dict_rows = sn_query_all(
                config,
                auth_manager,
                table="sys_dictionary",
                query=f"nameIN{encoded_names}^internal_type!=collection",
                fields="name,element,column_label,internal_type,max_length,mandatory,reference",
                page_size=100,
                max_records=5000,
                display_value=True,
            )
            table_fields: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for row in dict_rows:
                tbl = row.get("name")
                if tbl and row.get("element"):
                    table_fields[tbl].append(
                        {
                            "field": row["element"],
                            "label": row.get("column_label", ""),
                            "type": row.get("internal_type", ""),
                            "max_length": row.get("max_length", ""),
                            "mandatory": row.get("mandatory", ""),
                            "reference": row.get("reference", ""),
                        }
                    )
            for tbl, fields_list in table_fields.items():
                _dl_write_json(
                    schema_dir / f"{tbl}.json",
                    {
                        "table": tbl,
                        "field_count": len(fields_list),
                        "fields": fields_list,
                    },
                )
                schema_results[tbl] = len(fields_list)
        except Exception as exc:
            warnings.append(f"schema fetch failed for chunk: {exc}")

    _dl_write_json(
        schema_dir / "_index.json",
        {
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "tables": schema_results,
            "total_tables": len(schema_results),
            "total_fields": sum(schema_results.values()),
        },
    )
    return schema_results, warnings


@register_tool(
    "download_table_schema",
    params=DownloadTableSchemaParams,
    description="Download sys_dictionary field defs. Specify tables or auto-detect from local sources.",
    serialization="raw_dict",
    return_type=dict,
)
def download_table_schema(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadTableSchemaParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    if params.tables:
        table_names = {t.strip().lower() for t in params.tables if t.strip()}
    elif params.source_root:
        source_path = Path(params.source_root).expanduser().resolve()
        if not source_path.is_dir():
            return {"success": False, "message": f"source_root not found: {params.source_root}"}
        table_names = _scan_tables_from_source_root(source_path)
    else:
        return {"success": False, "message": "Either tables or source_root must be provided."}

    if not table_names:
        return {"success": True, "message": "No tables found to fetch schema for.", "tables": 0}

    if params.output_dir:
        schema_dir = Path(params.output_dir).expanduser().resolve()
    elif params.source_root:
        schema_dir = Path(params.source_root).expanduser().resolve() / "_schema"
    else:
        schema_dir = Path.cwd() / "temp" / "_schema"

    schema_results, warnings = _fetch_and_write_schema(
        config, auth_manager, table_names, schema_dir
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    result: Dict[str, Any] = {
        "success": True,
        "schema_dir": str(schema_dir),
        "tables_requested": len(table_names),
        "tables_fetched": len(schema_results),
        "total_fields": sum(schema_results.values()),
        "duration_ms": elapsed_ms,
        "safety_notice": "Schema JSON files written to disk. Only this summary returned to context.",
    }
    if warnings:
        result["warnings"] = warnings
    return result


# ---------------------------------------------------------------------------
# 8. download_app_sources  (Orchestrator)
# ---------------------------------------------------------------------------


class DownloadAppSourcesParams(BaseModel):
    scope: str = Field(
        ...,
        description="REQUIRED app namespace (x_...) or app name. Ask the user if not given.",
    )
    include_widget_sources: bool = Field(
        default=True,
        description="Download widgets, providers, header/footer, CSS via download_portal_sources.",
    )
    include_schema: bool = Field(
        default=True,
        description="Auto-detect referenced tables and download their schemas.",
    )
    max_records_per_type: int = Field(
        default=DEFAULT_DOWNLOAD_PER_TYPE,
        description=f"Max records per type. Clamped to {MAX_DOWNLOAD_PER_TYPE}.",
    )
    page_size: int = Field(
        default=DEFAULT_DOWNLOAD_PAGE_SIZE, description="Records per page (10..100)."
    )
    only_active: bool = Field(default=False, description="Download only active records.")
    acl_script_only: bool = Field(default=True, description="Only download ACLs with scripts.")
    auto_resolve_deps: bool = Field(
        default=True,
        description="After download, fetch missing cross-scope SI/widget/provider/ui_macro deps.",
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Omit — default path is canonical and reused. Set only for one-off export.",
    )
    incremental: bool = Field(
        default=False,
        description="Re-download only records changed since last sync (sys_updated_on).",
    )
    reconcile_deletions: bool = Field(
        default=False,
        description="Warn about local records deleted on the instance. No auto-delete.",
    )
    build_graph: bool = Field(
        default=False,
        description="Also run the offline audit (relationship graphs) after download. No API cost.",
    )
    resume: bool = Field(
        default=True,
        description="Replay finished stages from a prior timed-out call; skip re-downloading them.",
    )
    background: bool = Field(
        default=False,
        description="Run in background; call again (same args) to poll progress, then result.",
    )


# Background download jobs (no new tool: download_app_sources(background=true)
# starts one and polls it). Keyed by (instance host, scope, params fingerprint)
# so polling with the same args maps to the same job. The work runs in a daemon
# thread; progress is also on disk (source_resume), so a server/thread death is
# survivable — a later call resumes from disk.
_BG_JOBS: Dict[str, Dict[str, Any]] = {}
_BG_JOBS_LOCK = threading.Lock()

# Server-side long-poll: when a poll lands on a still-running job, block here up
# to _BG_POLL_MAX_BLOCK_SECONDS (re-checking every _BG_POLL_TICK_SECONDS) instead
# of returning instantly. Without this, a client busy-spins identical "still
# running" polls — wasted round-trips + context churn while the disk progress
# counter is flat across a long stage (schema/graph build). The wait is bounded
# (never indefinite) and well under the client's 120s call timeout, and it
# returns the moment the job finishes mid-wait. The cap is deterministic here so
# correct cadence does not depend on the LLM choosing to sleep between polls.
_BG_POLL_MAX_BLOCK_SECONDS = 20.0
_BG_POLL_TICK_SECONDS = 2.0


def _bg_job_key(instance_host: str, scope: str, fingerprint: str) -> str:
    return f"{instance_host}|{scope}|{fingerprint}"


def _read_job(key: str) -> Optional[Dict[str, Any]]:
    """Snapshot a job's terminal-relevant fields under the lock.

    A job marked running whose thread has died was interrupted (server restart /
    kill); mark it so the caller restarts a resume rather than reporting a dead
    thread as alive. Returns a fresh dict (never the shared one) so callers read
    status/result without holding the lock; None means no job for this key.
    """
    with _BG_JOBS_LOCK:
        job = _BG_JOBS.get(key)
        if job is None:
            return None
        if job["status"] == "running":
            thread = job.get("thread")
            if thread is None or not thread.is_alive():
                job["status"] = "interrupted"
        return {"status": job["status"], "result": job.get("result"), "error": job.get("error")}


def _bg_progress_snapshot(scope_root: Path, fingerprint: str) -> Dict[str, Any]:
    """Cheap, disk-derived progress — works even across a server restart."""
    prog = load_progress(scope_root, fingerprint) or {}
    files = sum(int((v or {}).get("files") or 0) for v in prog.values() if isinstance(v, dict))
    return {"stages_done": sorted(prog.keys()), "files_so_far": files}


def _run_or_poll_background(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadAppSourcesParams,
    scope_root: Path,
    fingerprint: str,
) -> Dict[str, Any]:
    """Start the download in a daemon thread, or report an existing job's state.

    Same tool, same args: first call starts, later calls poll, and once finished
    a call returns the full sync result. No second tool, no client-side timeout —
    the thread runs as long as it needs while polls stay fast.
    """
    instance_host = urlparse(config.instance_url).hostname or config.instance_url
    key = _bg_job_key(instance_host, params.scope, fingerprint)

    job = _read_job(key)

    # In-flight: block server-side up to the cap so each client poll is productive
    # instead of busy-spinning identical snapshots. Bounded loop, lock never held
    # across the sleep; returns early the moment the worker finishes.
    if job is not None and job["status"] == "running":
        waited = 0.0
        while waited < _BG_POLL_MAX_BLOCK_SECONDS and job["status"] == "running":
            tick = min(_BG_POLL_TICK_SECONDS, _BG_POLL_MAX_BLOCK_SECONDS - waited)
            time.sleep(tick)
            waited += tick
            job = _read_job(key) or {"status": "interrupted", "result": None, "error": None}

    snapshot = _bg_progress_snapshot(scope_root, fingerprint)

    if job is not None and job["status"] == "running":
        return {
            "success": True,
            "background": True,
            "status": "running",
            "scope": params.scope,
            "progress": snapshot,
            "next_poll_after_seconds": 0,
            "message": (
                "Download still running. This poll already waited "
                f"~{int(_BG_POLL_MAX_BLOCK_SECONDS)}s server-side — call again (same "
                "args) immediately to keep polling; no client-side sleep needed."
            ),
        }
    if job is not None and job["status"] == "done":
        return job["result"]
    if job is not None and job["status"] == "failed":
        return {
            "success": False,
            "background": True,
            "status": "failed",
            "scope": params.scope,
            "error": job.get("error"),
            "progress": snapshot,
        }

    with _BG_JOBS_LOCK:
        # Re-check under the lock: a concurrent poll may have (re)started a job
        # between the lock-free _read_job above and here. If one is now in flight
        # or finished, report it rather than starting a duplicate.
        existing = _BG_JOBS.get(key)
        if (
            existing is not None
            and existing["status"] == "running"
            and existing.get("thread") is not None
            and existing["thread"].is_alive()
        ):
            return {
                "success": True,
                "background": True,
                "status": "running",
                "scope": params.scope,
                "progress": snapshot,
                "next_poll_after_seconds": 0,
                "message": "Download still running. Call again (same args) to poll.",
            }

        # No job, or a prior one was interrupted → (re)start. Resume picks up any
        # disk progress, so a restart never re-downloads completed stages.
        # `new_job` is a distinct, definitely-non-None local so the worker
        # closure indexes a dict, not the dict|None from _BG_JOBS.get() above.
        sync_params = params.model_copy(update={"background": False})
        new_job: Dict[str, Any] = {
            "status": "running",
            "thread": None,
            "result": None,
            "error": None,
            "scope": params.scope,
        }

        def _worker() -> None:
            try:
                result = download_app_sources(config, auth_manager, sync_params)
                with _BG_JOBS_LOCK:
                    new_job["status"] = "done"
                    new_job["result"] = result
            except BaseException as exc:  # noqa: BLE001 — surfaced via poll
                with _BG_JOBS_LOCK:
                    new_job["status"] = "failed"
                    new_job["error"] = str(exc)

        thread = threading.Thread(target=_worker, name=f"dl-{params.scope}", daemon=True)
        new_job["thread"] = thread
        _BG_JOBS[key] = new_job
        thread.start()
        return {
            "success": True,
            "background": True,
            "status": "started",
            "scope": params.scope,
            "progress": snapshot,
            "message": (
                "Download started in background. Call download_app_sources again with the "
                "same args (background=true) to poll progress, then the final result."
            ),
        }


@register_tool(
    "download_app_sources",
    params=DownloadAppSourcesParams,
    description="FULL/all source of an app scope to disk (all groups+deps). scope REQUIRED — ask user. Step 1, not portal.",
    serialization="raw_dict",
    return_type=dict,
)
def download_app_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadAppSourcesParams,
) -> Dict[str, Any]:
    params, scope_resolution = apply_scope_namespace(config, auth_manager, params)
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)

    # Background mode: hand off to a daemon thread and return immediately (or
    # report an in-flight/finished job). Keeps the call under the client's 120s
    # timeout while the download runs as long as it needs. Done here — AFTER
    # scope_root is resolved — so start and poll share the same job key.
    if params.background:
        fingerprint = params_fingerprint(params.model_copy(update={"background": False}))
        return _run_or_poll_background(config, auth_manager, params, scope_root, fingerprint)

    all_type_results: Dict[str, Dict[str, Any]] = {}
    all_manifest_entries: List[Dict[str, Any]] = []
    all_warnings: List[str] = []
    all_deletion_candidates: Dict[str, List[str]] = {}
    all_files = 0
    widget_summary: Optional[Dict[str, Any]] = None
    schema_summary: Optional[Dict[str, Any]] = None
    dep_summary: Optional[Dict[str, Any]] = None

    # --- Resumable progress: replay stages a prior (timed-out) call finished ---
    # Large scopes can exceed the client's 120s call timeout. Each stage records
    # its result on completion; a re-invocation replays finished stages from disk
    # (no API) and only runs what is still missing, converging over short calls.
    fingerprint = params_fingerprint(params)
    done_stages = (load_progress(scope_root, fingerprint) or {}) if params.resume else {}
    resumed: List[str] = []

    # Orchestrator-level auth abort. The per-type abort inside
    # _download_source_types only covers the source-types stage; portal / schema
    # / deps each run independently. Without this, a dead session 401-bombs every
    # stage (observed: a 100s download of pure 401s). The first stage to surface
    # an auth failure trips this, and every later stage short-circuits.
    _auth_abort = {"hit": False}

    # Perceived-speed: report each stage as it starts so a long download streams
    # "downloading: <stage>" instead of going silent until the end. Indeterminate
    # total (None) — the group count is dynamic and replayed stages pass through
    # here too. No-op unless the server installed a progress emitter for the call.
    _stage_n = {"i": 0}

    def _run_stage(key, fn):
        """Run a stage, or replay it from saved progress.

        Captures the delta a stage adds to the shared accumulators so replay is
        equivalent to a real run. A stage is recorded ONLY after fn() returns —
        a mid-stage timeout leaves no record, so the next call re-runs it in full
        (a partially finished stage is never mistaken for a complete one).
        """
        nonlocal all_files
        _stage_n["i"] += 1
        emit_progress(_stage_n["i"], None, f"downloading: {key}")
        # A prior stage already proved auth is dead — skip without running and
        # WITHOUT caching (so a resume after re-login retries this stage).
        if _auth_abort["hit"]:
            all_warnings.append(
                f"{key}: skipped — download aborted after an auth failure. "
                "Re-authenticate and retry."
            )
            return {}
        if key in done_stages:
            p = done_stages[key] or {}
            all_type_results.update(p.get("type_results") or {})
            all_manifest_entries.extend(p.get("manifest_entries") or [])
            all_warnings.extend(p.get("warnings") or [])
            all_deletion_candidates.update(p.get("deletion_candidates") or {})
            all_files += int(p.get("files") or 0)
            resumed.append(key)
            return p.get("extra") or {}
        tr0 = set(all_type_results)
        me0 = len(all_manifest_entries)
        wn0 = len(all_warnings)
        dc0 = set(all_deletion_candidates)
        f0 = all_files
        extra = fn() or {}
        # Detect an auth failure surfaced by this stage (warnings or per-type
        # errors). If found, trip the abort and do NOT cache this stage, so a
        # resume after re-login re-runs it instead of replaying the failure.
        new_warnings = all_warnings[wn0:]
        new_results = [v for k, v in all_type_results.items() if k not in tr0]
        if _text_indicates_auth_failure(" ".join(new_warnings)) or any(
            _text_indicates_auth_failure(str(r.get("error", "")))
            for r in new_results
            if isinstance(r, dict)
        ):
            _auth_abort["hit"] = True
            all_warnings.append(
                "Download aborted: authentication failed (session rejected by "
                "ServiceNow). Re-authenticate and retry — remaining stages skipped, "
                "this stage not cached."
            )
            return extra
        save_stage(
            scope_root,
            fingerprint,
            key,
            {
                "type_results": {k: v for k, v in all_type_results.items() if k not in tr0},
                "manifest_entries": all_manifest_entries[me0:],
                "warnings": all_warnings[wn0:],
                "deletion_candidates": {
                    k: v for k, v in all_deletion_candidates.items() if k not in dc0
                },
                "files": all_files - f0,
                "extra": extra,
            },
        )
        return extra

    # --- Portal sources (widgets, providers, CSS via portal_tools) ---
    def _stage_portal():
        nonlocal all_files, widget_summary
        portal_failed = False
        try:
            from servicenow_mcp.tools.portal_tools import DownloadPortalSourcesParams as _DPSParams
            from servicenow_mcp.tools.portal_tools import download_portal_sources as _dps

            ws_params = _DPSParams(
                scope=params.scope,
                max_widgets=min(params.max_records_per_type, 1000),
                output_dir=str(scope_root),
                include_linked_angular_providers=True,
                include_linked_script_includes=True,
                incremental=params.incremental,
                reconcile_deletions=params.reconcile_deletions,
            )
            # Explicit retry: transient API errors surface as success=False.
            # Retry up to _RETRY_MAX_ATTEMPTS times before falling back.
            _portal_attempt = 0
            while True:
                # emit_phases=False: this orchestrator owns the per-stage progress
                # counter; portal phase ticks would make the stream non-monotonic.
                widget_summary = _dps(config, auth_manager, ws_params, emit_phases=False)
                assert widget_summary is not None
                if widget_summary.get("success"):
                    break
                _portal_attempt += 1
                if _portal_attempt > _RETRY_MAX_ATTEMPTS:
                    break
                _portal_delay = _retry_delay(_portal_attempt - 1)
                logger.warning(
                    "download_portal_sources failed (attempt %d/%d), retrying in %.1fs: %s",
                    _portal_attempt,
                    _RETRY_MAX_ATTEMPTS + 1,
                    _portal_delay,
                    widget_summary.get("error") or "success=False",
                )
                time.sleep(_portal_delay)

            ws = widget_summary.get("summary") or {}
            if not widget_summary.get("success"):
                portal_failed = True
                err = (
                    widget_summary.get("error")
                    or widget_summary.get("message")
                    or "download_portal_sources reported success=False"
                )
                all_warnings.append(f"widget sources: {err}")
            else:
                widget_count = int(ws.get("widgets", 0) or 0)
                provider_count = int(ws.get("angular_providers", 0) or 0)
                si_count = int(ws.get("script_includes", 0) or 0)
                all_type_results["widget"] = {"count": widget_count}
                all_type_results["angular_provider"] = {"count": provider_count}
                all_files += widget_count + provider_count
                # Forward portal's own warnings (clamps, skipped widgets, etc.) so they
                # are not lost when the orchestrator wraps the result.
                for w in widget_summary.get("warnings") or []:
                    all_warnings.append(f"widget sources: {w}")
                portal_gone = widget_summary.get("deleted_widget_candidates") or []
                if portal_gone:
                    all_deletion_candidates["widget"] = list(portal_gone)
                if widget_count == 0:
                    all_warnings.append(
                        "widget sources: 0 widgets returned for scope "
                        f"'{params.scope}' — verify scope name and sys_scope.scope filter "
                        "(run download_portal_sources directly to cross-check)."
                    )
                # Linked SI count flows through the dedicated script_include group below;
                # surface it here only as an info hint.
                if si_count:
                    all_warnings.append(
                        f"widget sources: fetched {si_count} linked script includes "
                        "(deduped against scope-wide script_include group)."
                    )
        except Exception as exc:
            portal_failed = True
            all_warnings.append(f"widget sources: {exc}")

        if portal_failed:
            # Fallback: download portal types via SOURCE_CONFIG so the user still gets
            # widget/provider source files even when the portal sub-call fails.
            try:
                dl = _download_source_types(
                    config,
                    auth_manager,
                    scope=params.scope,
                    source_types=[
                        "widget",
                        "angular_provider",
                        "sp_header_footer",
                        "sp_css",
                        "ng_template",
                    ],
                    scope_root=scope_root,
                    root=root,
                    max_per_type=params.max_records_per_type,
                    page_size=params.page_size,
                    only_active=params.only_active,
                    incremental=params.incremental,
                    reconcile_deletions=params.reconcile_deletions,
                )
                all_type_results.update(dl["type_results"])
                all_manifest_entries.extend(dl["manifest_entries"])
                all_warnings.extend(dl["warnings"])
                all_deletion_candidates.update(dl.get("deletion_candidates", {}))
                all_files += dl["total_files"]
            except Exception as exc:
                all_warnings.append(f"widget sources fallback failed: {exc}")
        return {"widget_summary": widget_summary}

    if params.include_widget_sources:
        widget_summary = _run_stage("portal", _stage_portal).get("widget_summary")

    # --- Server-side sources (7 groups) ---
    # angular_provider is always fetched here by scope — download_portal_sources
    # only fetches widget-linked providers which may be a subset.
    _groups = [
        ["script_include"],
        ["business_rule", "client_script", "catalog_client_script"],
        ["ui_action", "ui_script", "ui_page", "ui_macro"],
        ["scripted_rest", "processor"],
        ["acl"],
        ["fix_script", "scheduled_job", "script_action", "email_notification", "transform_script"],
        ["angular_provider", "sp_header_footer", "sp_css", "ng_template"],
        ["sp_page", "sp_instance"],
    ]
    extra_query: Dict[str, str] = {}
    if params.acl_script_only:
        extra_query["acl"] = "scriptISNOTEMPTY"

    def _make_group_stage(group):
        def _run():
            nonlocal all_files
            dl = _download_source_types(
                config,
                auth_manager,
                scope=params.scope,
                source_types=group,
                scope_root=scope_root,
                root=root,
                max_per_type=params.max_records_per_type,
                page_size=params.page_size,
                only_active=params.only_active,
                extra_query=extra_query,
                skip_empty_source_retry=set() if params.acl_script_only else {"acl"},
                incremental=params.incremental,
                reconcile_deletions=params.reconcile_deletions,
            )
            all_type_results.update(dl["type_results"])
            all_manifest_entries.extend(dl["manifest_entries"])
            all_warnings.extend(dl["warnings"])
            all_deletion_candidates.update(dl.get("deletion_candidates", {}))
            all_files += dl["total_files"]
            return {}

        return _run

    for _gi, group in enumerate(_groups):
        _run_stage(f"group:{_gi}", _make_group_stage(group))

    # --- Global sp_instance: widget placements live in global scope, not app scope ---
    # Query: sp_widget.sys_scope.scope=<app_scope> to get all page placements of app widgets.
    def _stage_global():
        nonlocal all_files
        global_root = root / "global"
        global_root.mkdir(parents=True, exist_ok=True)
        dl_global = _download_source_types(
            config,
            auth_manager,
            scope="global",
            source_types=["sp_instance"],
            scope_root=global_root,
            root=root,
            max_per_type=params.max_records_per_type,
            page_size=params.page_size,
            query_override={
                "sp_instance": f"sp_widget.sys_scope.scope={_escape_query_value(params.scope)}"
            },
            incremental=params.incremental,
            reconcile_deletions=params.reconcile_deletions,
        )
        gi = dl_global["type_results"].get("sp_instance", {"count": 0})
        all_type_results["sp_instance_global"] = gi
        all_warnings.extend(dl_global["warnings"])
        all_deletion_candidates.update(dl_global.get("deletion_candidates", {}))
        all_files += dl_global["total_files"]
        return {}

    _run_stage("global_sp_instance", _stage_global)

    # --- Table schema ---
    def _stage_schema():
        nonlocal schema_summary
        table_names = _scan_tables_from_source_root(scope_root)
        if table_names:
            schema_results, schema_warnings = _fetch_and_write_schema(
                config,
                auth_manager,
                table_names,
                scope_root / "_schema",
            )
            schema_summary = {
                "tables_fetched": len(schema_results),
                "total_fields": sum(schema_results.values()),
            }
            all_warnings.extend(schema_warnings)
        return {"schema_summary": schema_summary}

    if params.include_schema:
        schema_summary = _run_stage("schema", _stage_schema).get("schema_summary")

    # --- Auto-resolve cross-scope dependencies ---
    def _stage_deps():
        nonlocal all_files, dep_summary
        try:
            dep_summary = _auto_resolve_deps(config, auth_manager, scope_root, params.page_size)
            if dep_summary.get("total_new_records", 0) > 0:
                all_files += dep_summary["total_new_records"]
        except Exception as exc:
            all_warnings.append(f"dep_resolve: {exc}")
        return {"dep_summary": dep_summary}

    if params.auto_resolve_deps:
        dep_summary = _run_stage("deps", _stage_deps).get("dep_summary")

    # --- Write unified manifest ---
    _dl_write_json(
        scope_root / "_manifest.json",
        {
            "scope": params.scope,
            "instance": config.instance_url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "source_types": all_type_results,
            "total_records": sum(r.get("count", 0) for r in all_type_results.values()),
            "total_files": all_files,
            "schema": schema_summary,
            "entries": all_manifest_entries,
        },
    )

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    summary: Dict[str, Any] = {
        "success": True,
        "scope": params.scope,
        "output_root": str(scope_root),
        "duration_ms": elapsed_ms,
        "incremental": params.incremental,
        "source_types": all_type_results,
        "total_records": sum(r.get("count", 0) for r in all_type_results.values()),
        "total_files": all_files,
        "next_step": (
            f"Run audit_local_sources(source_root='{scope_root}') to build the "
            "relationship graphs (_graph.json, _page_graph.json, _cross_references.json) "
            "and answer dependency questions offline without further API calls."
        ),
    }
    # Single trustworthy completeness signal: false when any source family hit
    # its cap (records left behind). Analysis on an incomplete tree is unreliable,
    # so callers should treat complete=false as "do not trust derived results".
    capped_types = [
        t for t, r in all_type_results.items() if isinstance(r, dict) and r.get("capped")
    ]
    summary["complete"] = not capped_types
    if capped_types:
        summary["incomplete_types"] = capped_types

    if widget_summary and widget_summary.get("success"):
        summary["widget_summary"] = widget_summary.get("summary")
    if schema_summary:
        summary["schema_summary"] = schema_summary
    if dep_summary:
        summary["dep_summary"] = dep_summary
    if all_deletion_candidates:
        summary["deletion_candidates"] = all_deletion_candidates
    if params.incremental:
        all_warnings.append(
            "incremental: only records with a newer sys_updated_on were fetched per family; "
            "unchanged local files preserved. Run a full download periodically."
        )
    if scope_resolution:
        summary["scope_resolution"] = scope_resolution

    # Opt-in: build the offline relationship graphs right after download so a
    # single call yields complete metadata. No API cost. A graph is only as
    # trustworthy as the download under it — failure here never fails the
    # download, it just surfaces a warning.
    if params.build_graph:
        try:
            from servicenow_mcp.tools.source_audit_tools import (
                AuditAppSourcesParams,
                audit_local_sources,
            )

            graph = audit_local_sources(
                config, auth_manager, AuditAppSourcesParams(source_root=str(scope_root))
            )
            summary["graph"] = graph.get("summary", graph) if isinstance(graph, dict) else graph
        except Exception as exc:
            all_warnings.append(f"build_graph: relationship audit failed: {exc}")

    if resumed:
        summary["resumed_stages"] = resumed
    if all_warnings:
        summary["warnings"] = all_warnings
    summary["safety_notice"] = (
        "All source files written to disk in full — no truncation. "
        "Only this summary is returned to the conversation context."
    )
    # Reached the end → every stage finished. Drop the progress file so the next
    # call starts fresh. Done LAST (after build_graph) so a graph timeout replays
    # cheap cached stages instead of forcing a full re-download.
    clear_progress(scope_root)
    return summary
