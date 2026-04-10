"""
Portal developer productivity tools for the ServiceNow MCP server.
Focuses on developer-centric views: activity tracking, uncommitted changes,
and Angular Provider dependency mapping.

Design principles:
- Minimize API calls (use Aggregate API for counts, batch IN queries)
- Pre-report query cost before fetching large datasets
- Strip script bodies from list results — return metadata only
- Parse and compact all results for LLM token efficiency
"""

import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from .sn_api import sn_count as _sn_count_shared
from .sn_api import sn_query_page as _sn_query_page_shared
from ..utils.config import ServerConfig
from ..utils.registry import register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & Shared Config
# ---------------------------------------------------------------------------

PORTAL_DEV_TABLES: Dict[str, Dict[str, Any]] = {
    "widget": {
        "table": "sp_widget",
        "label": "Widget",
        # Metadata only — no script/template/css
        "fields": "sys_id,name,id,sys_scope,sys_updated_on,sys_updated_by",
    },
    "angular_provider": {
        "table": "sp_angular_provider",
        "label": "Angular Provider",
        "fields": "sys_id,name,sys_scope,sys_updated_on,sys_updated_by",
    },
    "script_include": {
        "table": "sys_script_include",
        "label": "Script Include",
        "fields": "sys_id,name,api_name,sys_scope,sys_updated_on,sys_updated_by,client_callable,active",
    },
    "business_rule": {
        "table": "sys_script",
        "label": "Business Rule",
        "fields": "sys_id,name,collection,sys_scope,sys_updated_on,sys_updated_by,active,when",
    },
    "client_script": {
        "table": "sys_client_script",
        "label": "Client Script",
        "fields": "sys_id,name,table,type,ui_type,sys_scope,sys_updated_on,sys_updated_by,active",
    },
    "ui_action": {
        "table": "sys_ui_action",
        "label": "UI Action",
        "fields": "sys_id,name,table,action_name,sys_scope,sys_updated_on,sys_updated_by,active",
    },
    "ui_script": {
        "table": "sys_ui_script",
        "label": "UI Script",
        "fields": "sys_id,name,sys_scope,sys_updated_on,sys_updated_by",
    },
    "ui_page": {
        "table": "sys_ui_page",
        "label": "UI Page",
        "fields": "sys_id,name,sys_scope,sys_updated_on,sys_updated_by",
    },
    "scripted_rest": {
        "table": "sys_ws_operation",
        "label": "Scripted REST",
        "fields": "sys_id,name,http_method,active,sys_scope,sys_updated_on,sys_updated_by",
    },
    "fix_script": {
        "table": "sys_script_fix",
        "label": "Fix Script",
        "fields": "sys_id,name,sys_scope,sys_updated_on,sys_updated_by,active",
    },
}

MAX_DEVELOPER_CHANGES_PER_TABLE = 50
MAX_UNCOMMITTED_RECORDS = 100
MAX_DEPENDENCY_WIDGETS = 30

SCRIPT_INCLUDE_REF_RE = re.compile(
    r"\bnew\s+(?:global\.)?((?:[A-Za-z_$][\w$]*\.)*[A-Za-z_$][\w$]*)\s*\("
)
IGNORED_CONSTRUCTORS = {
    "GlideRecord",
    "GlideRecordSecure",
    "GlideAggregate",
    "GlideAjax",
    "GlideDateTime",
    "GlideDuration",
    "GlideElement",
    "Object",
    "Array",
    "Date",
    "RegExp",
}


def _escape_query(value: str) -> str:
    return str(value).replace("^", "^^").replace("=", r"\=").replace("@", r"\@")


def _sn_count(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
) -> int:
    """Aggregate COUNT via shared helper."""
    return _sn_count_shared(config, auth_manager, table=table, query=query)


def _sn_get(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int = 20,
    offset: int = 0,
    orderby: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], Optional[int]]:
    """Lightweight ServiceNow table GET via shared cached page helper."""
    return _sn_query_page_shared(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=offset,
        orderby=orderby,
        display_value=True,
        no_count=False,
        fail_silently=False,
    )


def _compact_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """Strip empty/null values and flatten display_value dicts for token savings."""
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if v is None or v == "":
            continue
        if isinstance(v, dict) and "display_value" in v:
            dv = v.get("display_value")
            if dv:
                out[k] = dv
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Tool 1: get_developer_changes
# ---------------------------------------------------------------------------


class GetDeveloperChangesParams(BaseModel):
    developer: str = Field(
        ...,
        description="Developer username (sys_updated_by value). Example: admin@example.com",
    )
    scope: Optional[str] = Field(
        None,
        description="Optional app scope filter (sys_scope). Example: x_company_bpm",
    )
    source_types: List[str] = Field(
        ["widget", "angular_provider", "script_include"],
        description=(
            "Source types to scan. Allowed: widget, angular_provider, "
            "script_include, ui_script, business_rule"
        ),
    )
    updated_after: Optional[str] = Field(
        None,
        description="Lower bound for sys_updated_on (YYYY-MM-DD or datetime). Example: 2026-03-01",
    )
    updated_before: Optional[str] = Field(
        None,
        description="Upper bound for sys_updated_on (YYYY-MM-DD or datetime)",
    )
    filter_by: str = Field(
        "updated_by",
        description="Filter mode: updated_by (default) or created_by",
    )
    limit_per_table: int = Field(
        20,
        description=f"Max records per source type (max {MAX_DEVELOPER_CHANGES_PER_TABLE}). Default 20.",
    )
    count_only: bool = Field(
        False,
        description="When true, returns counts per table without fetching records (fast preview).",
    )
    orderby: str = Field(
        "-sys_updated_on",
        description="Order by field. Default: -sys_updated_on (newest first)",
    )


@register_tool(
    name="get_developer_changes",
    params=GetDeveloperChangesParams,
    description=(
        "List a developer's recent changes across portal tables (widgets, providers, SI, etc.). "
        "Returns metadata only, no script bodies. Use count_only=true to preview volume first."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def get_developer_changes(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetDeveloperChangesParams,
) -> Dict[str, Any]:
    safe_developer = _escape_query(params.developer)
    safe_limit = min(max(1, params.limit_per_table), MAX_DEVELOPER_CHANGES_PER_TABLE)
    filter_field = "sys_created_by" if params.filter_by == "created_by" else "sys_updated_by"

    results_by_type: Dict[str, Any] = {}
    total_items = 0
    total_api_calls = 0
    errors: List[str] = []
    cost_warnings: List[str] = []

    for stype in params.source_types:
        tconfig = PORTAL_DEV_TABLES.get(stype)
        if not tconfig:
            errors.append(f"Unknown source_type: {stype}")
            continue

        query_parts = [f"{filter_field}={safe_developer}"]
        if params.scope:
            query_parts.append(f"sys_scope={_escape_query(params.scope)}")
        if params.updated_after:
            query_parts.append(f"sys_updated_on>={params.updated_after}")
        if params.updated_before:
            query_parts.append(f"sys_updated_on<={params.updated_before}")
        query = "^".join(query_parts)

        try:
            # Always fetch count first (1 lightweight API call)
            count = _sn_count(config, auth_manager, tconfig["table"], query)
            total_api_calls += 1

            if params.count_only:
                results_by_type[stype] = {
                    "label": tconfig["label"],
                    "table": tconfig["table"],
                    "total_count": count,
                }
                total_items += count
                continue

            # Warn if large result set
            if count > safe_limit:
                cost_warnings.append(
                    f"{tconfig['label']}: {count} records found, returning first {safe_limit}. "
                    f"Use updated_after/updated_before or scope to narrow results."
                )

            if count == 0:
                results_by_type[stype] = {
                    "label": tconfig["label"],
                    "table": tconfig["table"],
                    "count": 0,
                    "total_count": 0,
                    "items": [],
                }
                continue

            rows, _ = _sn_get(
                config,
                auth_manager,
                tconfig["table"],
                query,
                tconfig["fields"],
                limit=safe_limit,
                orderby=params.orderby,
            )
            total_api_calls += 1

            # Compact results for LLM token efficiency
            compact_rows = [_compact_record(r) for r in rows]

            results_by_type[stype] = {
                "label": tconfig["label"],
                "table": tconfig["table"],
                "count": len(compact_rows),
                "total_count": count,
                "items": compact_rows,
            }
            total_items += len(compact_rows)
        except Exception as exc:
            errors.append(f"{stype}: {exc}")

    response: Dict[str, Any] = {
        "success": True,
        "developer": params.developer,
        "filter_by": filter_field,
        "total_items": total_items,
        "api_calls_made": total_api_calls,
        "results": results_by_type,
    }
    if cost_warnings:
        response["cost_warnings"] = cost_warnings
    if errors:
        response["errors"] = errors
    return response


# ---------------------------------------------------------------------------
# Tool 2: get_uncommitted_changes
# ---------------------------------------------------------------------------


class GetUncommittedChangesParams(BaseModel):
    developer: Optional[str] = Field(
        None,
        description="Developer username (sys_updated_by on update set). Example: admin@example.com",
    )
    scope: Optional[str] = Field(
        None,
        description="Optional app scope filter (application). Example: x_company_bpm",
    )
    update_set_name: Optional[str] = Field(
        None,
        description="Optional update set name filter (LIKE match)",
    )
    source_types: List[str] = Field(
        ["widget", "angular_provider", "script_include"],
        description="Filter update XML entries by these table types only",
    )
    limit: int = Field(
        50,
        description=f"Max update XML entries to return (max {MAX_UNCOMMITTED_RECORDS}). Default 50.",
    )
    count_only: bool = Field(
        False,
        description="When true, returns update set counts and entry count estimate without fetching details.",
    )


@register_tool(
    name="get_uncommitted_changes",
    params=GetUncommittedChangesParams,
    description=(
        "List uncommitted update set entries for a developer. "
        "Use count_only=true first to check volume before fetching full list."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def get_uncommitted_changes(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetUncommittedChangesParams,
) -> Dict[str, Any]:
    safe_limit = min(max(1, params.limit), MAX_UNCOMMITTED_RECORDS)
    total_api_calls = 0

    # Step 1: Find in-progress update sets for the developer
    us_query_parts = ["state=in progress"]
    if params.developer:
        us_query_parts.append(f"sys_updated_by={_escape_query(params.developer)}")
    if params.scope:
        us_query_parts.append(f"application.name={_escape_query(params.scope)}")
    if params.update_set_name:
        us_query_parts.append(f"nameLIKE{_escape_query(params.update_set_name)}")
    us_query = "^".join(us_query_parts)

    try:
        update_sets, us_total = _sn_get(
            config,
            auth_manager,
            "sys_update_set",
            us_query,
            "sys_id,name,application,state,sys_created_by,sys_updated_by,sys_updated_on",
            limit=20,
            orderby="-sys_updated_on",
        )
        total_api_calls += 1
    except Exception as exc:
        return {"success": False, "message": f"Failed to query update sets: {exc}"}

    if not update_sets:
        return {
            "success": True,
            "message": "No in-progress update sets found for the given filters.",
            "update_sets": [],
            "total_entries": 0,
            "api_calls_made": total_api_calls,
        }

    us_ids = [us.get("sys_id", "") for us in update_sets if us.get("sys_id")]
    us_map = {us.get("sys_id", ""): us.get("name", "Unknown") for us in update_sets}

    # Build table filter from source_types
    table_names = []
    for stype in params.source_types:
        tconfig = PORTAL_DEV_TABLES.get(stype)
        if tconfig:
            table_names.append(tconfig["table"])

    # Build XML query for count/fetch
    xml_query_parts = ["update_setIN" + ",".join(us_ids)]
    if table_names:
        xml_query_parts.append("nameIN" + ",".join(table_names))
    xml_query = "^".join(xml_query_parts)

    # Count entries first
    try:
        entry_count = _sn_count(config, auth_manager, "sys_update_xml", xml_query)
        total_api_calls += 1
    except Exception as exc:
        return {
            "success": False,
            "message": f"Failed to count update XML entries: {exc}",
        }

    compact_update_sets = [_compact_record(us) for us in update_sets]
    cost_warnings: List[str] = []

    if entry_count > safe_limit:
        cost_warnings.append(
            f"{entry_count} entries found across {len(us_ids)} update sets, "
            f"returning first {safe_limit}. Use source_types or scope to narrow."
        )

    if params.count_only:
        response: Dict[str, Any] = {
            "success": True,
            "developer": params.developer,
            "update_sets": compact_update_sets,
            "total_update_sets": us_total,
            "total_entries": entry_count,
            "api_calls_made": total_api_calls,
        }
        if cost_warnings:
            response["cost_warnings"] = cost_warnings
        return response

    if entry_count == 0:
        return {
            "success": True,
            "developer": params.developer,
            "update_sets": compact_update_sets,
            "total_update_sets": us_total,
            "entries_by_update_set": {},
            "total_entries": 0,
            "api_calls_made": total_api_calls,
        }

    # Fetch actual entries
    try:
        all_entries, _ = _sn_get(
            config,
            auth_manager,
            "sys_update_xml",
            xml_query,
            "sys_id,name,action,update_set,target_name,type,sys_created_by,sys_updated_on",
            limit=safe_limit,
            orderby="-sys_updated_on",
        )
        total_api_calls += 1
    except Exception as exc:
        return {
            "success": False,
            "message": f"Failed to fetch update XML entries: {exc}",
        }

    # Group entries by update set — compact output
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for entry in all_entries:
        us_ref = entry.get("update_set", "")
        if isinstance(us_ref, dict):
            us_name = us_ref.get("display_value", "")
        else:
            us_name = us_map.get(str(us_ref), str(us_ref))
        key = us_name or "Unknown"
        grouped.setdefault(key, []).append(
            {
                "target": entry.get("target_name", ""),
                "table": entry.get("name", ""),
                "action": entry.get("action", ""),
                "updated": entry.get("sys_updated_on", ""),
            }
        )

    response = {
        "success": True,
        "developer": params.developer,
        "update_sets": compact_update_sets,
        "total_update_sets": us_total,
        "entries_by_update_set": grouped,
        "total_entries": entry_count,
        "returned_entries": len(all_entries),
        "api_calls_made": total_api_calls,
    }
    if cost_warnings:
        response["cost_warnings"] = cost_warnings
    return response


# ---------------------------------------------------------------------------
# Tool 3: get_provider_dependency_map
# ---------------------------------------------------------------------------


class GetProviderDependencyMapParams(BaseModel):
    widget_ids: Optional[List[str]] = Field(
        None,
        description="Widget sys_id, id, or name values to map. Strongly recommended for targeted queries.",
    )
    scope: Optional[str] = Field(
        None,
        description="App scope filter (sys_scope). Example: x_company_bpm",
    )
    developer: Optional[str] = Field(
        None,
        description="Developer filter (sys_updated_by). Example: admin@example.com",
    )
    include_script_include_refs: bool = Field(
        True,
        description="Extract Script Include references (new ClassName()) from provider/widget server scripts",
    )
    max_widgets: int = Field(
        10,
        description=f"Max widgets to process (max {MAX_DEPENDENCY_WIDGETS}). Default 10.",
    )


def _extract_si_refs(script: Optional[str]) -> List[str]:
    """Extract Script Include class name references from a script."""
    if not script:
        return []
    found: List[str] = []
    for token in SCRIPT_INCLUDE_REF_RE.findall(script):
        short_name = token.split(".")[-1]
        if short_name and short_name not in IGNORED_CONSTRUCTORS and short_name not in found:
            found.append(short_name)
    return found


@register_tool(
    name="get_provider_dependency_map",
    params=GetProviderDependencyMapParams,
    description="Build widget-to-provider-to-script-include dependency graph. Returns metadata only, no script bodies.",
    serialization="raw_dict",
    return_type=dict,
)
def get_provider_dependency_map(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetProviderDependencyMapParams,
) -> Dict[str, Any]:
    safe_max = min(max(1, params.max_widgets), MAX_DEPENDENCY_WIDGETS)
    total_api_calls = 0
    cost_warnings: List[str] = []

    # Step 1: Count matching widgets first
    widget_query_parts: List[str] = []
    if params.widget_ids:
        id_filter = ",".join(params.widget_ids)
        widget_query_parts.append(f"sys_idIN{id_filter}^ORidIN{id_filter}^ORnameIN{id_filter}")
    if params.scope:
        widget_query_parts.append(f"sys_scope={_escape_query(params.scope)}")
    if params.developer:
        widget_query_parts.append(f"sys_updated_by={_escape_query(params.developer)}")

    if not widget_query_parts:
        return {
            "success": False,
            "message": "At least one of widget_ids, scope, or developer is required.",
        }

    widget_query = "^".join(widget_query_parts)

    try:
        widget_count = _sn_count(config, auth_manager, "sp_widget", widget_query)
        total_api_calls += 1
    except Exception as exc:
        return {"success": False, "message": f"Failed to count widgets: {exc}"}

    if widget_count == 0:
        return {
            "success": True,
            "message": "No widgets found matching the filters.",
            "widget_count": 0,
            "dependency_map": [],
            "api_calls_made": total_api_calls,
        }

    if widget_count > safe_max:
        cost_warnings.append(
            f"{widget_count} widgets match your filter, processing first {safe_max}. "
            f"This will require ~{2 + safe_max // 50 + 1} API calls. "
            f"Use widget_ids to target specific widgets for faster results."
        )

    # Step 2: Fetch widgets — include server script ONLY for SI ref extraction
    # Script bodies will be parsed then discarded from the response
    widget_fields = "sys_id,name,id,sys_scope,sys_updated_by"
    if params.include_script_include_refs:
        widget_fields += ",script"

    try:
        widgets, widget_total = _sn_get(
            config,
            auth_manager,
            "sp_widget",
            widget_query,
            widget_fields,
            limit=safe_max,
            orderby="name",
        )
        total_api_calls += 1
    except Exception as exc:
        return {"success": False, "message": f"Failed to fetch widgets: {exc}"}

    widget_ids = [w["sys_id"] for w in widgets if w.get("sys_id")]

    # Step 3: Fetch M2M widget → angular provider (single batch query)
    m2m_query = "sp_widgetIN" + ",".join(widget_ids)
    try:
        m2m_rows, _ = _sn_get(
            config,
            auth_manager,
            "m2m_sp_widget_angular_provider",
            m2m_query,
            "sys_id,sp_widget,sp_angular_provider",
            limit=500,
        )
        total_api_calls += 1
    except Exception as exc:
        logger.warning("Failed to fetch M2M widget-provider: %s", exc)
        m2m_rows = []

    # Map provider IDs per widget
    widget_provider_map: Dict[str, List[str]] = {}
    all_provider_ids: List[str] = []
    for row in m2m_rows:
        w_ref = row.get("sp_widget", "")
        p_ref = row.get("sp_angular_provider", "")
        w_id = w_ref.get("value", w_ref) if isinstance(w_ref, dict) else str(w_ref)
        p_id = p_ref.get("value", p_ref) if isinstance(p_ref, dict) else str(p_ref)
        if w_id and p_id:
            widget_provider_map.setdefault(w_id, []).append(p_id)
            if p_id not in all_provider_ids:
                all_provider_ids.append(p_id)

    # Step 4: Fetch provider details (single batch, include script only for ref extraction)
    providers_by_id: Dict[str, Dict[str, Any]] = {}
    if all_provider_ids:
        p_fields = "sys_id,name,sys_scope,sys_updated_by"
        if params.include_script_include_refs:
            p_fields += ",script"
        chunk_size = 50
        for i in range(0, len(all_provider_ids), chunk_size):
            chunk = all_provider_ids[i : i + chunk_size]
            p_query = "sys_idIN" + ",".join(chunk)
            try:
                p_rows, _ = _sn_get(
                    config,
                    auth_manager,
                    "sp_angular_provider",
                    p_query,
                    p_fields,
                    limit=len(chunk),
                )
                total_api_calls += 1
                for p in p_rows:
                    providers_by_id[p.get("sys_id", "")] = p
            except Exception as exc:
                logger.warning("Failed to fetch provider chunk: %s", exc)

    # Step 5: Extract Script Include references (parse scripts, then discard bodies)
    all_si_names: List[str] = []
    provider_si_map: Dict[str, List[str]] = {}
    widget_si_map: Dict[str, List[str]] = {}

    if params.include_script_include_refs:
        for pid, pdata in providers_by_id.items():
            refs = _extract_si_refs(pdata.get("script", ""))
            if refs:
                provider_si_map[pid] = refs
                for r in refs:
                    if r not in all_si_names:
                        all_si_names.append(r)
            # Discard script body after extraction
            pdata.pop("script", None)

        for w in widgets:
            refs = _extract_si_refs(w.get("script", ""))
            if refs:
                widget_si_map[w.get("sys_id", "")] = refs
                for r in refs:
                    if r not in all_si_names:
                        all_si_names.append(r)
            # Discard script body after extraction
            w.pop("script", None)

    # Step 6: Resolve Script Include names (single batch query)
    si_details: Dict[str, Dict[str, Any]] = {}
    if all_si_names:
        chunk_size = 50
        for i in range(0, len(all_si_names), chunk_size):
            chunk = all_si_names[i : i + chunk_size]
            si_query = "nameIN" + ",".join(chunk)
            try:
                si_rows, _ = _sn_get(
                    config,
                    auth_manager,
                    "sys_script_include",
                    si_query,
                    "sys_id,name,api_name,sys_scope,sys_updated_by,client_callable,active",
                    limit=len(chunk),
                )
                total_api_calls += 1
                for si in si_rows:
                    si_details[si.get("name", "")] = _compact_record(si)
            except Exception as exc:
                logger.warning("Failed to resolve script includes: %s", exc)

    # Step 7: Build compact dependency map
    dependency_map: List[Dict[str, Any]] = []

    for w in widgets:
        w_id = w.get("sys_id", "")
        w_providers = widget_provider_map.get(w_id, [])

        provider_entries = []
        for pid in w_providers:
            pdata = providers_by_id.get(pid, {})
            p_entry: Dict[str, Any] = {
                "sys_id": pid,
                "name": pdata.get("name", ""),
            }
            p_si_refs = provider_si_map.get(pid, [])
            if p_si_refs:
                p_entry["si_refs"] = [
                    si_details.get(ref, {"name": ref, "resolved": False}) for ref in p_si_refs
                ]
            provider_entries.append(p_entry)

        w_si_refs = widget_si_map.get(w_id, [])

        entry: Dict[str, Any] = {
            "widget": _compact_record(w),
            "providers": provider_entries,
        }
        if w_si_refs:
            entry["server_si_refs"] = [
                si_details.get(ref, {"name": ref, "resolved": False}) for ref in w_si_refs
            ]
        dependency_map.append(entry)

    # Summary
    total_providers = len(all_provider_ids)
    total_si_refs = len(all_si_names)
    resolved_si = sum(1 for n in all_si_names if n in si_details)
    unresolved = [n for n in all_si_names if n not in si_details]

    response: Dict[str, Any] = {
        "success": True,
        "summary": {
            "widgets": len(widgets),
            "widgets_total": widget_total,
            "providers": total_providers,
            "script_include_refs": total_si_refs,
            "resolved": resolved_si,
            "api_calls": total_api_calls,
        },
        "dependency_map": dependency_map,
    }
    if unresolved:
        response["unresolved_script_includes"] = unresolved
    if cost_warnings:
        response["cost_warnings"] = cost_warnings
    return response


# ---------------------------------------------------------------------------
# Tool 4: get_developer_daily_summary
# ---------------------------------------------------------------------------

# Source code fields to analyse per table type (fetched, parsed, then discarded)
_SUMMARY_SOURCE_FIELDS: Dict[str, Dict[str, Any]] = {
    "widget": {
        "table": "sp_widget",
        "label": "Widget",
        "name_field": "name",
        "meta_fields": "sys_id,name,id,sys_scope,sys_updated_on",
        "source_fields": ["script", "client_script", "template", "css"],
    },
    "angular_provider": {
        "table": "sp_angular_provider",
        "label": "Angular Provider",
        "name_field": "name",
        "meta_fields": "sys_id,name,sys_scope,sys_updated_on",
        "source_fields": ["script"],
    },
    "script_include": {
        "table": "sys_script_include",
        "label": "Script Include",
        "name_field": "name",
        "meta_fields": "sys_id,name,api_name,sys_scope,sys_updated_on",
        "source_fields": ["script"],
    },
    "business_rule": {
        "table": "sys_script",
        "label": "Business Rule",
        "name_field": "name",
        "meta_fields": "sys_id,name,collection,sys_scope,sys_updated_on",
        "source_fields": ["script"],
    },
    "client_script": {
        "table": "sys_client_script",
        "label": "Client Script",
        "name_field": "name",
        "meta_fields": "sys_id,name,table,type,sys_scope,sys_updated_on",
        "source_fields": ["script"],
    },
    "ui_action": {
        "table": "sys_ui_action",
        "label": "UI Action",
        "name_field": "name",
        "meta_fields": "sys_id,name,table,action_name,sys_scope,sys_updated_on",
        "source_fields": ["script"],
    },
    "ui_script": {
        "table": "sys_ui_script",
        "label": "UI Script",
        "name_field": "name",
        "meta_fields": "sys_id,name,sys_scope,sys_updated_on",
        "source_fields": ["script"],
    },
    "ui_page": {
        "table": "sys_ui_page",
        "label": "UI Page",
        "name_field": "name",
        "meta_fields": "sys_id,name,sys_scope,sys_updated_on",
        "source_fields": ["html", "client_script", "processing_script"],
    },
    "scripted_rest": {
        "table": "sys_ws_operation",
        "label": "Scripted REST",
        "name_field": "name",
        "meta_fields": "sys_id,name,http_method,sys_scope,sys_updated_on",
        "source_fields": ["operation_script"],
    },
    "fix_script": {
        "table": "sys_script_fix",
        "label": "Fix Script",
        "name_field": "name",
        "meta_fields": "sys_id,name,sys_scope,sys_updated_on",
        "source_fields": ["script"],
    },
}

MAX_DAILY_SUMMARY_PER_TABLE = 30

# Regex for extracting top-level function/class names from scripts
_FUNC_NAME_RE = re.compile(
    r"(?:"
    r"\bfunction\s+([A-Za-z_$][\w$]*)"  # function declarations
    r"|\b([A-Za-z_$][\w$]*)\s*[:=]\s*function"  # function expressions
    r"|\b([A-Za-z_$][\w$]*)\s*[:=]\s*\([^)]*\)\s*=>"  # arrow functions
    r"|\bClass\.create\(\)"  # ServiceNow class pattern
    r"|\bvar\s+([A-Za-z_$][\w$]*)\s*=\s*Class\.create"  # SI class name
    r")"
)


def _extract_script_profile(content: str) -> Dict[str, Any]:
    """Extract lightweight profile from a script: line count, function names."""
    if not content or not content.strip():
        return {}
    lines = content.count("\n") + 1
    funcs: List[str] = []
    for m in _FUNC_NAME_RE.finditer(content):
        name = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        if name and name not in funcs and len(funcs) < 15:
            funcs.append(name)
    profile: Dict[str, Any] = {"lines": lines}
    if funcs:
        profile["functions"] = funcs
    return profile


class GetDeveloperDailySummaryParams(BaseModel):
    developer: str = Field(
        ...,
        description="Developer username (sys_updated_by). Example: admin@example.com",
    )
    date: str = Field(
        ...,
        description="Target date (YYYY-MM-DD). Example: 2026-03-31",
    )
    scope: Optional[str] = Field(
        None,
        description="Optional app scope filter (sys_scope). Example: x_company_bpm",
    )
    source_types: List[str] = Field(
        ["widget", "angular_provider", "script_include"],
        description="Portal source types to include in summary",
    )
    include_update_sets: bool = Field(
        True,
        description="Include list of update sets touched on that date",
    )
    include_details: bool = Field(
        True,
        description=(
            "When true, fetch source fields to extract line counts, function names, "
            "and field presence. Script bodies are parsed then discarded (not returned). "
            "For widgets, also resolves linked Angular Providers."
        ),
    )
    output_format: str = Field(
        "jira",
        description="Output format: jira (markdown table), plain (flat list), structured (JSON)",
    )


@register_tool(
    name="get_developer_daily_summary",
    params=GetDeveloperDailySummaryParams,
    description=(
        "Generate a developer's daily work summary for Jira/Confluence. "
        "Returns line counts, functions, and provider links. Supports jira/plain/structured formats."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def get_developer_daily_summary(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetDeveloperDailySummaryParams,
) -> Dict[str, Any]:
    safe_developer = _escape_query(params.developer)
    date_str = params.date.strip()
    date_start = f"{date_str} 00:00:00"
    date_end = f"{date_str} 23:59:59"

    total_api_calls = 0
    categories: Dict[str, List[Dict[str, Any]]] = {}
    total_changes = 0
    all_widget_ids: List[str] = []

    for stype in params.source_types:
        tconfig = _SUMMARY_SOURCE_FIELDS.get(stype)
        if not tconfig:
            continue

        query_parts = [
            f"sys_updated_by={safe_developer}",
            f"sys_updated_on>={date_start}",
            f"sys_updated_on<={date_end}",
        ]
        if params.scope:
            query_parts.append(f"sys_scope={_escape_query(params.scope)}")
        query = "^".join(query_parts)

        # Build fields: metadata + source fields if details requested
        fields = tconfig["meta_fields"]
        if params.include_details:
            fields += "," + ",".join(tconfig["source_fields"])

        try:
            rows, _ = _sn_get(
                config,
                auth_manager,
                tconfig["table"],
                query,
                fields,
                limit=MAX_DAILY_SUMMARY_PER_TABLE,
                orderby="sys_updated_on",
            )
            total_api_calls += 1
        except Exception as exc:
            logger.warning("Daily summary fetch failed for %s: %s", stype, exc)
            continue

        if not rows:
            continue

        items: List[Dict[str, Any]] = []
        for row in rows:
            item: Dict[str, Any] = {
                "name": row.get(tconfig["name_field"], ""),
                "sys_id": row.get("sys_id", ""),
            }
            # Time portion only for brevity
            updated = row.get("sys_updated_on", "")
            item["time"] = updated.split(" ")[-1] if " " in updated else updated

            scope_val = row.get("sys_scope", "")
            if isinstance(scope_val, dict):
                scope_val = scope_val.get("display_value", "")
            if scope_val:
                item["scope"] = scope_val

            # Extra metadata fields (id, collection, table, etc.)
            for mf in tconfig["meta_fields"].split(","):
                mf = mf.strip()
                if mf not in (
                    "sys_id",
                    "name",
                    tconfig["name_field"],
                    "sys_scope",
                    "sys_updated_on",
                ):
                    val = row.get(mf, "")
                    if val:
                        item[mf] = val

            # Source analysis: extract profiles then discard bodies
            if params.include_details:
                field_profiles: Dict[str, Any] = {}
                for sf in tconfig["source_fields"]:
                    content = row.get(sf, "")
                    if content and isinstance(content, str) and content.strip():
                        profile = _extract_script_profile(content)
                        if profile:
                            field_profiles[sf] = profile
                if field_profiles:
                    item["fields"] = field_profiles

            # Track widget IDs for provider lookup
            if stype == "widget" and row.get("sys_id"):
                all_widget_ids.append(row["sys_id"])

            items.append(item)

        categories[tconfig["label"]] = items
        total_changes += len(items)

    # Resolve Widget → Angular Provider links
    widget_providers: Dict[str, List[str]] = {}
    if params.include_details and all_widget_ids:
        try:
            m2m_query = "sp_widgetIN" + ",".join(all_widget_ids)
            m2m_rows, _ = _sn_get(
                config,
                auth_manager,
                "m2m_sp_widget_angular_provider",
                m2m_query,
                "sp_widget,sp_angular_provider",
                limit=100,
            )
            total_api_calls += 1

            provider_ids: List[str] = []
            w_p_map: Dict[str, List[str]] = {}
            for row in m2m_rows:
                w_ref = row.get("sp_widget", "")
                p_ref = row.get("sp_angular_provider", "")
                w_id = w_ref.get("value", w_ref) if isinstance(w_ref, dict) else str(w_ref)
                p_id = p_ref.get("value", p_ref) if isinstance(p_ref, dict) else str(p_ref)
                if w_id and p_id:
                    w_p_map.setdefault(w_id, []).append(p_id)
                    if p_id not in provider_ids:
                        provider_ids.append(p_id)

            # Resolve provider names
            if provider_ids:
                p_query = "sys_idIN" + ",".join(provider_ids)
                p_rows, _ = _sn_get(
                    config,
                    auth_manager,
                    "sp_angular_provider",
                    p_query,
                    "sys_id,name",
                    limit=100,
                )
                total_api_calls += 1
                p_names = {p.get("sys_id", ""): p.get("name", "") for p in p_rows}

                for w_id, p_ids in w_p_map.items():
                    widget_providers[w_id] = [p_names.get(pid, pid) for pid in p_ids]

        except Exception as exc:
            logger.warning("Failed to resolve widget providers: %s", exc)

    # Attach provider names to widget items
    if widget_providers and "Widget" in categories:
        for item in categories["Widget"]:
            providers = widget_providers.get(item.get("sys_id", ""), [])
            if providers:
                item["providers"] = providers

    # Update XML cross-match for action type (INSERT vs UPDATE)
    all_sys_ids: List[str] = []
    for items in categories.values():
        for item in items:
            if item.get("sys_id"):
                all_sys_ids.append(item["sys_id"])

    action_map: Dict[str, str] = {}
    if params.include_details and all_sys_ids:
        try:
            # sys_update_xml.action field: INSERT_OR_UPDATE, etc.
            xml_query = (
                f"sys_updated_by={safe_developer}"
                f"^sys_updated_on>={date_start}"
                f"^sys_updated_on<={date_end}"
            )
            xml_rows, _ = _sn_get(
                config,
                auth_manager,
                "sys_update_xml",
                xml_query,
                "target_name,action,name",
                limit=100,
                orderby="-sys_updated_on",
            )
            total_api_calls += 1
            for xr in xml_rows:
                target = xr.get("target_name", "")
                action = xr.get("action", "")
                if target and action:
                    action_map[target] = action
        except Exception as exc:
            logger.warning("Failed to fetch update XML for action mapping: %s", exc)

    # Attach action to items
    if action_map:
        for items in categories.values():
            for item in items:
                action = action_map.get(item.get("name", ""))
                if action:
                    item["action"] = action

    # Optionally include update sets
    update_set_summary: List[Dict[str, str]] = []
    if params.include_update_sets:
        us_query_parts = [
            f"sys_updated_by={safe_developer}",
            f"sys_updated_on>={date_start}",
            f"sys_updated_on<={date_end}",
        ]
        if params.scope:
            us_query_parts.append(f"application.name={_escape_query(params.scope)}")
        us_query = "^".join(us_query_parts)

        try:
            us_rows, _ = _sn_get(
                config,
                auth_manager,
                "sys_update_set",
                us_query,
                "sys_id,name,state,application",
                limit=20,
                orderby="-sys_updated_on",
            )
            total_api_calls += 1
            for us in us_rows:
                app_val = us.get("application", "")
                if isinstance(app_val, dict):
                    app_val = app_val.get("display_value", "")
                update_set_summary.append(
                    {
                        "name": us.get("name", ""),
                        "state": us.get("state", ""),
                        "application": app_val,
                    }
                )
        except Exception as exc:
            logger.warning("Failed to fetch update sets for daily summary: %s", exc)

    # Format output
    fmt = params.output_format.strip().lower()

    if fmt == "jira":
        lines: List[str] = [
            f"## 작업 내역 — {date_str}",
            f"**개발자:** {params.developer}",
            f"**총 변경 항목:** {total_changes}",
            "",
        ]
        for cat_label, items in categories.items():
            lines.append(f"### {cat_label} ({len(items)}건)")
            if params.include_details:
                lines.append("| Name | Action | Details | Time |")
                lines.append("|------|--------|---------|------|")
                for item in items:
                    name = item.get("name", "")
                    action = item.get("action", "")
                    time_val = item.get("time", "")
                    # Build details string
                    details_parts: List[str] = []
                    if item.get("scope"):
                        details_parts.append(item["scope"])
                    fields_info = item.get("fields", {})
                    for fname, fprofile in fields_info.items():
                        line_count = fprofile.get("lines", 0)
                        details_parts.append(f"{fname}:{line_count}L")
                    if item.get("providers"):
                        details_parts.append("→ " + ", ".join(item["providers"]))
                    details = " · ".join(details_parts) if details_parts else ""
                    lines.append(f"| {name} | {action} | {details} | {time_val} |")
            else:
                lines.append("| Name | Scope | Updated |")
                lines.append("|------|-------|---------|")
                for item in items:
                    lines.append(
                        f"| {item.get('name', '')} | {item.get('scope', '')} | {item.get('time', '')} |"
                    )
            lines.append("")

        if update_set_summary:
            lines.append(f"### Update Sets ({len(update_set_summary)}건)")
            lines.append("| Name | State | Application |")
            lines.append("|------|-------|-------------|")
            for us in update_set_summary:
                lines.append(
                    f"| {us.get('name', '')} | {us.get('state', '')} | {us.get('application', '')} |"
                )
            lines.append("")

        return {
            "success": True,
            "developer": params.developer,
            "date": date_str,
            "total_changes": total_changes,
            "jira_markdown": "\n".join(lines),
            "api_calls_made": total_api_calls,
        }

    elif fmt == "plain":
        lines = [f"[{date_str}] {params.developer} 작업 내역 ({total_changes}건)"]
        for cat_label, items in categories.items():
            lines.append(f"\n● {cat_label} ({len(items)}건)")
            for item in items:
                name = item.get("name", "")
                action = item.get("action", "")
                parts = [name]
                if action:
                    parts.append(f"[{action}]")
                if item.get("scope"):
                    parts.append(f"({item['scope']})")
                fields_info = item.get("fields", {})
                if fields_info:
                    field_str = ", ".join(
                        f"{k}:{v.get('lines', 0)}L" for k, v in fields_info.items()
                    )
                    parts.append(f"({field_str})")
                if item.get("providers"):
                    parts.append(f"→ {', '.join(item['providers'])}")
                lines.append(f"  - {' '.join(parts)}")

        if update_set_summary:
            lines.append(f"\n● Update Sets ({len(update_set_summary)}건)")
            for us in update_set_summary:
                lines.append(f"  - {us.get('name', '')} [{us.get('state', '')}]")

        return {
            "success": True,
            "developer": params.developer,
            "date": date_str,
            "total_changes": total_changes,
            "plain_text": "\n".join(lines),
            "api_calls_made": total_api_calls,
        }

    else:  # structured
        return {
            "success": True,
            "developer": params.developer,
            "date": date_str,
            "total_changes": total_changes,
            "categories": categories,
            "update_sets": update_set_summary if params.include_update_sets else [],
            "api_calls_made": total_api_calls,
        }
