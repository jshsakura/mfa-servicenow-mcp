"""
Server-side source discovery tools inspired by common ServiceNow productivity workflows.
Designed for MCP use: read-only, token-efficient, and strongly scoped.
"""

import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

MAX_SEARCH_LIMIT = 10
PER_TYPE_LIMIT = 5
MAX_FIELD_LENGTH = 12000
DEFAULT_FIELD_LENGTH = 4000
SNIPPET_RADIUS = 120

SOURCE_TYPE_ALL = "all"
DEFAULT_SOURCE_TYPE_ORDER = [
    "script_include",
    "widget",
    "business_rule",
    "ui_script",
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
}


class SearchServerCodeParams(BaseModel):
    query: str = Field(..., description="Text to search in names, identifiers, and source fields")
    source_type: str = Field(SOURCE_TYPE_ALL, description="One of: all, script_include, widget")
    limit: int = Field(
        5, description=f"Maximum number of total matches to return. Clamped to {MAX_SEARCH_LIMIT}."
    )
    scope: str | None = Field(None, description="Optional scope filter")
    updated_by: str | None = Field(None, description="Optional updated_by filter")
    max_snippet_length: int = Field(300, description="Maximum snippet size returned for each match")


class GetMetadataSourceParams(BaseModel):
    source_type: str = Field(..., description="One of: script_include, widget")
    source_id: str = Field(..., description="sys_id, name, or logical identifier")
    max_field_length: int = Field(
        DEFAULT_FIELD_LENGTH,
        description=f"Maximum length for each returned source field. Clamped to {MAX_FIELD_LENGTH}.",
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
        query_parts.append(f"sys_scope={_escape_query_value(params.scope)}")
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
    response = auth_manager.make_request(
        "GET",
        f"{config.instance_url}/api/now/table/{table}",
        headers=auth_manager.get_headers(),
        params={
            "sysparm_query": query,
            "sysparm_fields": ",".join(fields),
            "sysparm_limit": limit,
            "sysparm_display_value": "true",
            "sysparm_exclude_reference_link": "true",
            "sysparm_suppress_pagination_header": "false",
        },
        timeout=config.timeout,
    )
    response.raise_for_status()
    return response.json().get("result", [])


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
