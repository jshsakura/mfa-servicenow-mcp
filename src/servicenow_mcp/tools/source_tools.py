"""
Server-side source discovery tools inspired by common ServiceNow productivity workflows.
Designed for MCP use: read-only, token-efficient, and strongly scoped.
"""

import json
import logging
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import sn_query_all, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

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
            "sys_updated_on",
            "sys_updated_by",
        ],
        "source_fields": ["script"],
        "search_fields": ["name", "collection", "script"],
        "lookup_fields": ["sys_id", "name"],
    },
    "client_script": {
        "table": "sys_client_script",
        "identifier_field": "name",
        "summary_fields": [
            "sys_id",
            "name",
            "table",
            "type",
            "ui_type",
            "active",
            "sys_scope",
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
        "summary_fields": [
            "sys_id",
            "name",
            "map",
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
    source_type: str = Field(
        default=SOURCE_TYPE_ALL,
        description="'all' or a specific type: script_include, widget, angular_provider, business_rule, client_script, catalog_client_script, ui_action, ui_script, ui_page, ui_macro, scripted_rest, fix_script, scheduled_job, script_action, email_notification, acl, transform_script, processor, sp_header_footer, sp_css, ng_template, update_xml",
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
    source_type: str = Field(
        default=...,
        description="Specific source type (e.g. script_include, widget, business_rule, acl, scheduled_job). Same types as search_server_code.",
    )
    source_id: str = Field(..., description="sys_id, name, or logical identifier")
    max_field_length: int = Field(
        default=DEFAULT_FIELD_LENGTH,
        description=f"Maximum length for each returned source field. Clamped to {MAX_FIELD_LENGTH}.",
    )


class ExtractTableDependenciesParams(BaseModel):
    scope: str | None = Field(
        default=None,
        description="Optional app scope filter (sys_scope). Example: x_company_bpm",
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
        description="From scanned widget/business rule scripts, resolve referenced Script Includes and scan them too",
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
        description="If true, also scan generic string literals that look like table names (higher recall, lower precision)",
    )


class ExtractWidgetTableDependenciesParams(BaseModel):
    widget_id: str = Field(..., description="Widget sys_id, id, or name")
    scope: str | None = Field(
        default=None,
        description="Optional app scope filter (sys_scope). Example: x_company_bpm",
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
        description="If true, also scan generic string literals that look like table names (higher recall, lower precision)",
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
    description="Search across 22 server-side source types (SI, BR, widget, ACL, etc.) by keyword/regex. Returns matching snippets.",
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
    description="Build a GlideRecord table dependency graph from server scripts. Scans SI, BR, and widget code.",
    serialization="raw_dict",
    return_type=dict,
)
def extract_table_dependencies(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ExtractTableDependenciesParams,
) -> Dict[str, Any]:
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


@register_tool(
    "extract_widget_table_dependencies",
    params=ExtractWidgetTableDependenciesParams,
    description="Build a table dependency graph for a single widget, optionally expanding linked script includes.",
    serialization="raw_dict",
    return_type=dict,
)
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
        for candidate in si_candidates:
            try:
                si_row = _find_script_include_by_candidate(
                    config,
                    auth_manager,
                    candidate=candidate,
                    scope=params.scope,
                    only_active=params.only_active,
                )
            except Exception as exc:
                failed_sources.append(
                    {
                        "source_type": "script_include_lookup",
                        "message": f"{candidate}: {exc}",
                    }
                )
                continue

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

# File extension mapping based on source field content
_FIELD_EXTENSIONS: Dict[str, str] = {
    "script": ".js",
    "client_script": ".client.js",
    "operation_script": ".js",
    "processing_script": ".server.js",
    "html": ".html",
    "template": ".html",
    "css": ".scss",
    "xml": ".xml",
    "message_html": ".html",
    "message_text": ".txt",
    "payload": ".xml",
}

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


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return safe.strip("._") or "unnamed"


def _dl_write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _dl_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _resolve_scope_root(
    config: ServerConfig,
    scope: str,
    output_dir: Optional[str],
) -> tuple[Path, Path]:
    """Returns (root, scope_root) paths."""
    if output_dir:
        root = Path(output_dir).expanduser().resolve()
    else:
        instance_name = (urlparse(config.instance_url).hostname or "instance").split(".")[0]
        root = Path.cwd() / "temp" / instance_name
    scope_name = _safe_filename(scope)
    scope_root = root / scope_name
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
) -> Dict[str, Any]:
    """Core download loop shared by all individual download tools.

    Args:
        extra_query: Per-source_type extra query clauses (e.g. {"acl": "scriptISNOTEMPTY"}).

    Returns dict with keys: type_results, manifest_entries, warnings, total_files.
    """
    max_per_type = _clamp_download_per_type(max_per_type)
    page_size = max(10, min(page_size, 100))
    extra_query = extra_query or {}

    type_results: Dict[str, Dict[str, Any]] = {}
    manifest_entries: List[Dict[str, Any]] = []
    warnings: List[str] = []
    total_files = 0

    for source_type in source_types:
        if source_type not in SOURCE_CONFIG:
            warnings.append(f"Unknown source type: {source_type}")
            continue

        source_cfg = SOURCE_CONFIG[source_type]
        table = source_cfg["table"]

        all_fields = list(source_cfg["summary_fields"]) + list(source_cfg["source_fields"])
        effective_page_size = min(page_size, 10) if source_cfg["source_fields"] else page_size

        # Build base query filters (active, extra)
        base_filters: List[str] = []
        if only_active and table in _ACTIVE_SUPPORTED_TABLES:
            base_filters.append("active=true")
        if source_type in extra_query:
            base_filters.append(extra_query[source_type])

        query_parts = [f"sys_scope.scope={scope}"] + base_filters
        query = "^".join(query_parts)

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
            )
        except Exception as exc:
            logger.error("Failed to download %s: %s", source_type, exc)
            warnings.append(f"{source_type}: fetch failed — {exc}")
            type_results[source_type] = {"count": 0, "error": str(exc)}
            continue

        if not records:
            type_results[source_type] = {"count": 0}
            continue

        type_dir = scope_root / table
        name_map: Dict[str, str] = {}
        sync_meta: Dict[str, Dict[str, str]] = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        type_file_count = 0
        retry_records: List[tuple] = []

        for record in records:
            sys_id = str(record.get("sys_id") or "")
            identifier_field = source_cfg["identifier_field"]
            name = str(record.get(identifier_field) or record.get("name") or sys_id)
            safe_name = _safe_filename(name)

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

            # Resume: skip if source files already exist from a previous run
            if source_cfg["source_fields"]:
                existing_source = any(
                    (record_dir / f"{sf}{_FIELD_EXTENSIONS.get(sf, '.txt')}").exists()
                    for sf in source_cfg["source_fields"]
                )
                if existing_source:
                    name_map[safe_name] = sys_id
                    sync_meta[safe_name] = {
                        "sys_id": sys_id,
                        "name": name,
                        "sys_updated_on": str(record.get("sys_updated_on") or ""),
                        "downloaded_at": now_iso,
                    }
                    type_file_count += sum(
                        1
                        for sf in source_cfg["source_fields"]
                        if (record_dir / f"{sf}{_FIELD_EXTENSIONS.get(sf, '.txt')}").exists()
                    )
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
            if not has_source and sys_id and source_cfg["source_fields"]:
                retry_records.append((sys_id, safe_name, record_dir))

            name_map[safe_name] = sys_id
            sync_meta[safe_name] = {
                "sys_id": sys_id,
                "name": name,
                "sys_updated_on": str(record.get("sys_updated_on") or ""),
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

        # Parallel retry: individually fetch records whose source was empty in batch
        if retry_records:
            _src_fields = list(source_cfg["source_fields"])
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        _retry_empty_source,
                        config,
                        auth_manager,
                        table,
                        _src_fields,
                        source_type,
                        rec,
                        warnings,
                    )
                    for rec in retry_records
                ]
                type_file_count += sum(f.result() for f in futures)

        _dl_write_json(type_dir / "_map.json", name_map)
        _dl_write_json(type_dir / "_sync_meta.json", sync_meta)
        type_results[source_type] = {
            "count": len(records),
            "files": type_file_count,
            "path": str(type_dir.relative_to(root)),
        }
        total_files += type_file_count

    return {
        "type_results": type_results,
        "manifest_entries": manifest_entries,
        "warnings": warnings,
        "total_files": total_files,
    }


def _build_download_result(
    scope: str,
    scope_root: Path,
    dl: Dict[str, Any],
    elapsed_ms: int,
    tool_name: str,
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
    if dl["warnings"]:
        result["warnings"] = dl["warnings"]
    return result


# --- Common params mixin ---


class _ScopeDownloadParams(BaseModel):
    scope: str = Field(..., description="Application scope (e.g. x_yergb_bpm).")
    max_records_per_type: int = Field(
        default=DEFAULT_DOWNLOAD_PER_TYPE,
        description=f"Max records per type. Clamped to {MAX_DOWNLOAD_PER_TYPE}.",
    )
    page_size: int = Field(
        default=DEFAULT_DOWNLOAD_PAGE_SIZE, description="Records per page (10..100)."
    )
    only_active: bool = Field(default=False, description="Download only active records.")
    output_dir: Optional[str] = Field(default=None, description="Custom output directory.")


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


# --- 1. download_script_includes ---


class DownloadScriptIncludesParams(_ScopeDownloadParams):
    pass


@register_tool(
    "download_script_includes",
    params=DownloadScriptIncludesParams,
    description="Download all Script Includes for a scope to local files.",
    serialization="raw_dict",
    return_type=dict,
)
def download_script_includes(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadScriptIncludesParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)
    dl = _download_source_types(
        config,
        auth_manager,
        scope=params.scope,
        source_types=_SCRIPT_INCLUDE_TYPES,
        scope_root=scope_root,
        root=root,
        max_per_type=params.max_records_per_type,
        page_size=params.page_size,
        only_active=params.only_active,
    )
    return _build_download_result(
        params.scope,
        scope_root,
        dl,
        int((time.perf_counter() - started) * 1000),
        "download_script_includes",
    )


# --- 2. download_server_scripts ---


class DownloadServerScriptsParams(_ScopeDownloadParams):
    pass


@register_tool(
    "download_server_scripts",
    params=DownloadServerScriptsParams,
    description="Download Business Rules, Client Scripts, and Catalog Client Scripts for a scope.",
    serialization="raw_dict",
    return_type=dict,
)
def download_server_scripts(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadServerScriptsParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)
    dl = _download_source_types(
        config,
        auth_manager,
        scope=params.scope,
        source_types=_SERVER_SCRIPT_TYPES,
        scope_root=scope_root,
        root=root,
        max_per_type=params.max_records_per_type,
        page_size=params.page_size,
        only_active=params.only_active,
    )
    return _build_download_result(
        params.scope,
        scope_root,
        dl,
        int((time.perf_counter() - started) * 1000),
        "download_server_scripts",
    )


# --- 3. download_ui_components ---


class DownloadUIComponentsParams(_ScopeDownloadParams):
    pass


@register_tool(
    "download_ui_components",
    params=DownloadUIComponentsParams,
    description="Download UI Actions, UI Scripts, UI Pages, and UI Macros for a scope.",
    serialization="raw_dict",
    return_type=dict,
)
def download_ui_components(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadUIComponentsParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)
    dl = _download_source_types(
        config,
        auth_manager,
        scope=params.scope,
        source_types=_UI_COMPONENT_TYPES,
        scope_root=scope_root,
        root=root,
        max_per_type=params.max_records_per_type,
        page_size=params.page_size,
        only_active=params.only_active,
    )
    return _build_download_result(
        params.scope,
        scope_root,
        dl,
        int((time.perf_counter() - started) * 1000),
        "download_ui_components",
    )


# --- 4. download_api_sources ---


class DownloadAPISourcesParams(_ScopeDownloadParams):
    pass


@register_tool(
    "download_api_sources",
    params=DownloadAPISourcesParams,
    description="Download Scripted REST API operations and Processors for a scope.",
    serialization="raw_dict",
    return_type=dict,
)
def download_api_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadAPISourcesParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)
    dl = _download_source_types(
        config,
        auth_manager,
        scope=params.scope,
        source_types=_API_SOURCE_TYPES,
        scope_root=scope_root,
        root=root,
        max_per_type=params.max_records_per_type,
        page_size=params.page_size,
        only_active=params.only_active,
    )
    return _build_download_result(
        params.scope,
        scope_root,
        dl,
        int((time.perf_counter() - started) * 1000),
        "download_api_sources",
    )


# --- 5. download_security_sources ---


class DownloadSecuritySourcesParams(_ScopeDownloadParams):
    acl_script_only: bool = Field(default=True, description="Only download ACLs with scripts.")


@register_tool(
    "download_security_sources",
    params=DownloadSecuritySourcesParams,
    description="Download ACL rules for a scope. By default only ACLs with scripts.",
    serialization="raw_dict",
    return_type=dict,
)
def download_security_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadSecuritySourcesParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)
    extra_q: Dict[str, str] = {}
    if params.acl_script_only:
        extra_q["acl"] = "scriptISNOTEMPTY"
    dl = _download_source_types(
        config,
        auth_manager,
        scope=params.scope,
        source_types=_SECURITY_SOURCE_TYPES,
        scope_root=scope_root,
        root=root,
        max_per_type=params.max_records_per_type,
        page_size=params.page_size,
        only_active=params.only_active,
        extra_query=extra_q,
    )
    return _build_download_result(
        params.scope,
        scope_root,
        dl,
        int((time.perf_counter() - started) * 1000),
        "download_security_sources",
    )


# --- 6. download_admin_scripts ---


class DownloadAdminScriptsParams(_ScopeDownloadParams):
    pass


@register_tool(
    "download_admin_scripts",
    params=DownloadAdminScriptsParams,
    description="Download Fix Scripts, Scheduled Jobs, Script Actions, and Email Notifications for a scope.",
    serialization="raw_dict",
    return_type=dict,
)
def download_admin_scripts(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadAdminScriptsParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)
    dl = _download_source_types(
        config,
        auth_manager,
        scope=params.scope,
        source_types=_ADMIN_SCRIPT_TYPES,
        scope_root=scope_root,
        root=root,
        max_per_type=params.max_records_per_type,
        page_size=params.page_size,
        only_active=params.only_active,
    )
    return _build_download_result(
        params.scope,
        scope_root,
        dl,
        int((time.perf_counter() - started) * 1000),
        "download_admin_scripts",
    )


# ---------------------------------------------------------------------------
# 7. download_table_schema
# ---------------------------------------------------------------------------


class DownloadTableSchemaParams(BaseModel):
    tables: Optional[List[str]] = Field(
        default=None,
        description=(
            "Explicit list of table names to fetch schema for. "
            "When omitted, auto-scans source_root for GlideRecord references."
        ),
    )
    source_root: Optional[str] = Field(
        default=None,
        description=(
            "Path to a downloaded source directory (e.g. temp/<instance>/<scope>). "
            "Scripts inside will be scanned for GlideRecord table references. "
            "Ignored when tables is provided."
        ),
    )
    output_dir: Optional[str] = Field(
        default=None,
        description="Where to write schema JSON files. Defaults to <source_root>/_schema/",
    )


def _scan_tables_from_source_root(source_root: Path) -> Set[str]:
    """Scan .js/.html files under source_root for GlideRecord table references."""
    tables: Set[str] = set()
    for js_file in source_root.rglob("*.js"):
        try:
            script_text = js_file.read_text(encoding="utf-8")
            tables.update(
                _extract_table_names_from_script(script_text, include_loose_literal_scan=False)
            )
        except Exception:
            pass
    for meta_file in source_root.rglob("_metadata.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            for field in ("collection", "table"):
                val = meta.get(field)
                if isinstance(val, str) and TABLE_NAME_RE.match(val):
                    tables.add(val)
        except Exception:
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
    description=(
        "Download sys_dictionary field definitions for ServiceNow tables. "
        "Specify table names directly, or point to a downloaded source directory "
        "to auto-detect referenced tables from GlideRecord calls."
    ),
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
    scope: str = Field(..., description="Application scope (e.g. x_yergb_bpm).")
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
    output_dir: Optional[str] = Field(default=None, description="Custom output directory.")


@register_tool(
    "download_app_sources",
    params=DownloadAppSourcesParams,
    description=(
        "Orchestrator: download ALL source code for an application scope. "
        "Calls download_portal_sources, download_script_includes, download_server_scripts, "
        "download_ui_components, download_api_sources, download_security_sources, "
        "download_admin_scripts, and download_table_schema in sequence. "
        "Returns a unified summary."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def download_app_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DownloadAppSourcesParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    root, scope_root = _resolve_scope_root(config, params.scope, params.output_dir)

    all_type_results: Dict[str, Dict[str, Any]] = {}
    all_manifest_entries: List[Dict[str, Any]] = []
    all_warnings: List[str] = []
    all_files = 0

    # --- Portal sources (widgets, providers, CSS via portal_tools) ---
    widget_summary: Optional[Dict[str, Any]] = None
    if params.include_widget_sources:
        try:
            from servicenow_mcp.tools.portal_tools import DownloadPortalSourcesParams as _DPSParams
            from servicenow_mcp.tools.portal_tools import download_portal_sources as _dps

            ws_params = _DPSParams(
                scope=params.scope,
                max_widgets=min(params.max_records_per_type, 1000),
                output_dir=str(root),
                include_linked_angular_providers=True,
                include_linked_script_includes=True,
            )
            widget_summary = _dps(config, auth_manager, ws_params)
            if widget_summary.get("success"):
                ws = widget_summary.get("summary", {})
                all_type_results["widget"] = {"count": ws.get("widgets", 0)}
                all_type_results["angular_provider"] = {"count": ws.get("angular_providers", 0)}
                all_files += ws.get("widgets", 0) + ws.get("angular_providers", 0)
        except Exception as exc:
            all_warnings.append(f"widget sources: {exc}")
            # Fallback: download portal types via SOURCE_CONFIG
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
            )
            all_type_results.update(dl["type_results"])
            all_manifest_entries.extend(dl["manifest_entries"])
            all_warnings.extend(dl["warnings"])
            all_files += dl["total_files"]

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

    for group in _groups:
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
        )
        all_type_results.update(dl["type_results"])
        all_manifest_entries.extend(dl["manifest_entries"])
        all_warnings.extend(dl["warnings"])
        all_files += dl["total_files"]

    # --- Table schema ---
    schema_summary: Optional[Dict[str, Any]] = None
    if params.include_schema:
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
        "source_types": all_type_results,
        "total_records": sum(r.get("count", 0) for r in all_type_results.values()),
        "total_files": all_files,
    }
    if widget_summary and widget_summary.get("success"):
        summary["widget_summary"] = widget_summary.get("summary")
    if schema_summary:
        summary["schema_summary"] = schema_summary
    if all_warnings:
        summary["warnings"] = all_warnings
    summary["safety_notice"] = (
        "All source files written to disk in full — no truncation. "
        "Only this summary is returned to the conversation context."
    )
    return summary
