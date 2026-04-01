"""
Audit tools for reviewing pending update set changes.

Consolidates 20+ sequential MCP calls into a single server-side operation:
1. Fetch sys_update_xml entries for a developer
2. Group by record type (widget, provider, script, OAuth, layout, etc.)
3. Batch-fetch code bodies and scan for risk patterns
4. Detect clones and cross-references
5. Return a structured audit report

Design: App Engine Studio-style change list — one call, full picture.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map sys_update_xml `name` (table name) to human-readable category
ENTRY_CATEGORY_MAP: Dict[str, str] = {
    "sp_widget": "widget",
    "sp_angular_provider": "angular_provider",
    "sp_header_footer": "header_footer",
    "sp_page": "page",
    "sp_portal": "portal",
    "sp_css": "css",
    "sp_js_include": "js_include",
    "sp_row": "layout",
    "sp_column": "layout",
    "sp_container": "layout",
    "sp_instance": "widget_instance",
    "sp_instance_with_items": "widget_instance",
    "m2m_sp_widget_angular_provider": "m2m_dependency",
    "m2m_sp_ng_pro_sp_widget": "m2m_dependency",
    "sys_script_include": "script_include",
    "sys_script": "business_rule",
    "sys_client_script": "client_script",
    "sys_ui_action": "ui_action",
    "sys_ui_page": "ui_page",
    "sys_ui_script": "ui_script",
    "sys_ws_operation": "scripted_rest",
    "sys_ws_definition": "scripted_rest_api",
    "sys_script_fix": "fix_script",
    "oauth_entity": "oauth_credential",
    "oauth_entity_profile": "oauth_credential",
    "oauth_entity_scope": "oauth_credential",
    "sys_properties": "system_property",
    "sys_ui_policy": "ui_policy",
    "sys_ui_policy_action": "ui_policy",
    "sys_dictionary": "dictionary",
    "sys_db_object": "table_definition",
    "sys_choice": "choice_list",
}

# Default risk patterns with severity
DEFAULT_RISK_PATTERNS: Dict[str, List[tuple]] = {
    "high": [
        (r"\beval\s*\(", "eval_usage", "Direct eval() — code injection risk"),
        (r"\.innerHTML\s*=", "xss_risk", "innerHTML assignment — XSS risk"),
        (r"Function\s*\(", "dynamic_function", "Dynamic Function() constructor — injection risk"),
    ],
    "medium": [
        (
            r"document\.getElementById",
            "dom_manipulation",
            "Direct DOM access — bypasses Angular digest",
        ),
        (r"window\.location", "redirect_risk", "window.location manipulation"),
        (r"document\.cookie", "cookie_access", "Direct cookie access"),
        (
            r"\$http\s*\.\s*(get|post|put|delete)\s*\(",
            "direct_http",
            "Direct $http — consider using a provider",
        ),
    ],
    "low": [
        (
            r"\bconsole\.\s*(log|debug|warn|error)\s*\(",
            "console_log",
            "Console statement left in code",
        ),
        (r"https?://[^\s'\"}{]+\.(com|net|org|io|kr)", "hardcoded_url", "Hardcoded external URL"),
    ],
}

# Fields to fetch from sys_update_xml
UPDATE_XML_FIELDS = (
    "sys_id,name,action,update_set,target_name,type," "sys_created_by,sys_updated_on,sys_updated_by"
)

# Tables whose code bodies we scan for risks
CODE_TABLES: Dict[str, Dict[str, Any]] = {
    "sp_widget": {
        "fields": "sys_id,name,id,script,client_script,template,css",
        "code_fields": ["script", "client_script", "template"],
    },
    "sp_angular_provider": {
        "fields": "sys_id,name,script",
        "code_fields": ["script"],
    },
    "sys_script_include": {
        "fields": "sys_id,name,api_name,script,client_callable",
        "code_fields": ["script"],
    },
}

MAX_IN_CHUNK = 50  # ServiceNow IN query limit per chunk


# ---------------------------------------------------------------------------
# Helpers (duplicated from portal_dev_tools for self-containment)
# ---------------------------------------------------------------------------


def _escape_query(value: str) -> str:
    return str(value).replace("^", "^^").replace("=", r"\=").replace("@", r"\@")


def _sn_get(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int = 200,
    offset: int = 0,
    orderby: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], Optional[int]]:
    url = f"{config.instance_url}/api/now/table/{table}"
    params: Dict[str, Any] = {
        "sysparm_query": query,
        "sysparm_fields": fields,
        "sysparm_limit": limit,
        "sysparm_offset": offset,
        "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
        "sysparm_suppress_pagination_header": "false",
    }
    if orderby:
        if orderby.startswith("-"):
            params["sysparm_orderby_desc"] = orderby[1:]
        else:
            params["sysparm_orderby"] = orderby
    response = auth_manager.make_request("GET", url, params=params, timeout=config.timeout)
    response.raise_for_status()
    data = response.json()
    total = response.headers.get("X-Total-Count")
    return data.get("result", []), int(total) if total else None


def _compact_record(row: Dict[str, Any]) -> Dict[str, Any]:
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
# Risk scanning
# ---------------------------------------------------------------------------


def _compile_risk_patterns(
    custom_patterns: Optional[List[str]] = None,
) -> List[tuple]:
    """Return list of (compiled_re, severity, category, description)."""
    compiled = []
    for severity, patterns in DEFAULT_RISK_PATTERNS.items():
        for pattern_str, category, desc in patterns:
            try:
                compiled.append((re.compile(pattern_str), severity, category, desc))
            except re.error:
                logger.warning("Invalid default risk pattern: %s", pattern_str)
    if custom_patterns:
        for p in custom_patterns:
            try:
                compiled.append((re.compile(p), "medium", "custom", f"Custom pattern: {p}"))
            except re.error:
                logger.warning("Invalid custom risk pattern: %s", p)
    return compiled


def _scan_code(
    code: str,
    field_name: str,
    record_name: str,
    patterns: List[tuple],
    include_snippets: bool = False,
    snippet_chars: int = 80,
) -> List[Dict[str, Any]]:
    """Scan a code string for risk patterns. Returns list of findings."""
    findings: List[Dict[str, Any]] = []
    if not code:
        return findings
    lines = code.split("\n")
    for compiled_re, severity, category, desc in patterns:
        for i, line in enumerate(lines, 1):
            if compiled_re.search(line):
                finding: Dict[str, Any] = {
                    "severity": severity,
                    "category": category,
                    "description": desc,
                    "source": record_name,
                    "field": field_name,
                    "line": i,
                }
                if include_snippets:
                    finding["snippet"] = line.strip()[:snippet_chars]
                findings.append(finding)
    return findings


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _classify_entry(table_name: str) -> str:
    """Map a sys_update_xml `name` (table name) to a category."""
    return ENTRY_CATEGORY_MAP.get(table_name, "other")


def _detect_clones(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Detect potential clone/duplicate entries (same target_name, multiple sys_ids)."""
    name_map: Dict[str, List[Dict[str, Any]]] = {}
    for entry in entries:
        target = entry.get("target_name", "")
        if not target:
            continue
        name_map.setdefault(target, []).append(entry)

    clones = []
    for target_name, group in name_map.items():
        if len(group) > 1:
            actions = list({e.get("action", "") for e in group})
            clones.append(
                {
                    "target_name": target_name,
                    "occurrences": len(group),
                    "actions": actions,
                    "table": group[0].get("name", ""),
                }
            )
    return clones


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------


class AuditPendingChangesParams(BaseModel):
    """Parameters for auditing pending update set changes."""

    developer: str = Field(
        ...,
        description="Developer username (sys_updated_by). Example: admin@example.com",
    )
    date_from: Optional[str] = Field(
        None,
        description="Start date (YYYY-MM-DD). Defaults to 7 days ago.",
    )
    date_to: Optional[str] = Field(
        None,
        description="End date (YYYY-MM-DD). Defaults to today.",
    )
    exclude_pattern: Optional[str] = Field(
        None,
        description=(
            "Exclude entries whose target_name matches this substring "
            "(case-insensitive). Example: 'hopes'"
        ),
    )
    scope: Optional[str] = Field(
        None,
        description="App scope filter (application name). Example: x_company_bpm",
    )
    update_set: Optional[str] = Field(
        None,
        description="Filter to specific update set name. Example: 'My Feature v2'",
    )
    custom_risk_patterns: Optional[List[str]] = Field(
        None,
        description="Additional regex patterns to scan for. Auto-classified as medium severity.",
    )
    max_entries: int = Field(
        200,
        description="Maximum update_xml entries to process (max 500).",
    )
    include_code_snippets: bool = Field(
        False,
        description="Include code snippets around risk matches. Default false for token efficiency.",
    )
    snippet_chars: int = Field(
        100,
        description="Max snippet length when include_code_snippets=true.",
    )
    scan_code: bool = Field(
        True,
        description="Fetch and scan code bodies for risk patterns. Set false for inventory-only mode.",
    )


@register_tool(
    name="audit_pending_changes",
    params=AuditPendingChangesParams,
    description=(
        "Audit a developer's pending update set changes in one call. "
        "Returns an App Engine Studio-style change inventory grouped by type "
        "(widget, provider, script, OAuth, layout, etc.), risk pattern scan results, "
        "clone detection, and cross-reference analysis. "
        "Replaces 20+ sequential queries with a single consolidated report."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def audit_pending_changes(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: AuditPendingChangesParams,
) -> Dict[str, Any]:
    """Audit pending update set changes for a developer."""
    api_calls = 0
    max_entries = min(params.max_entries, 500)

    # --- Date range ---
    today = datetime.now()
    date_from = params.date_from or (today - timedelta(days=7)).strftime("%Y-%m-%d")
    date_to = params.date_to or today.strftime("%Y-%m-%d")

    # --- Phase 1: Fetch sys_update_xml entries ---
    query_parts = [
        f"sys_updated_by={_escape_query(params.developer)}",
        f"sys_updated_on>={date_from}",
        f"sys_updated_on<={date_to} 23:59:59",
    ]
    if params.exclude_pattern:
        escaped = _escape_query(params.exclude_pattern)
        query_parts.append(f"target_nameNOT LIKE{escaped}")
        query_parts.append(f"nameNOT LIKE{escaped}")
    if params.scope:
        query_parts.append(f"update_set.application.name={_escape_query(params.scope)}")
    if params.update_set:
        query_parts.append(f"update_set.name={_escape_query(params.update_set)}")

    query = "^".join(query_parts) + "^ORDERBYDESCsys_updated_on"

    entries, total = _sn_get(
        config,
        auth_manager,
        "sys_update_xml",
        query,
        UPDATE_XML_FIELDS,
        limit=max_entries,
        orderby="-sys_updated_on",
    )
    api_calls += 1

    if not entries:
        return {
            "success": True,
            "developer": params.developer,
            "date_range": {"from": date_from, "to": date_to},
            "total_entries": 0,
            "api_calls": api_calls,
            "inventory": {},
            "risk_findings": [],
            "risk_summary": {"high": 0, "medium": 0, "low": 0},
            "clone_candidates": [],
            "cross_references": {},
            "recommendations": ["No pending changes found for the given filters."],
        }

    # --- Phase 2: Group and classify ---
    inventory: Dict[str, List[Dict[str, Any]]] = {}
    table_sys_ids: Dict[str, set] = {}  # table -> set of target sys_ids

    for entry in entries:
        table_name = entry.get("name", "")
        category = _classify_entry(table_name)
        compact = _compact_record(entry)

        inventory.setdefault(category, []).append(compact)

        # Collect sys_ids for code tables we want to scan
        target_name = entry.get("target_name", "")
        if table_name in CODE_TABLES and target_name:
            table_sys_ids.setdefault(table_name, set()).add(target_name)

    # Build summary
    inventory_summary: Dict[str, Any] = {}
    for cat, items in sorted(inventory.items()):
        # Deduplicate by target_name for display
        seen = set()
        unique_items = []
        for item in items:
            key = item.get("target_name", item.get("sys_id", ""))
            if key not in seen:
                seen.add(key)
                unique_items.append(item)
        inventory_summary[cat] = {
            "count": len(items),
            "unique_records": len(unique_items),
            "entries": unique_items[:50],  # Cap for token efficiency
        }

    # Clone detection
    clone_candidates = _detect_clones(entries)

    # --- Phase 3: Fetch code bodies and scan risks ---
    risk_findings: List[Dict[str, Any]] = []
    risk_patterns = _compile_risk_patterns(params.custom_risk_patterns)

    if params.scan_code and table_sys_ids:
        for table_name, target_names in table_sys_ids.items():
            table_info = CODE_TABLES[table_name]
            # Batch IN query by target_name (chunked)
            name_list = list(target_names)
            for chunk_start in range(0, len(name_list), MAX_IN_CHUNK):
                chunk = name_list[chunk_start : chunk_start + MAX_IN_CHUNK]
                in_query = "nameIN" + ",".join(_escape_query(n) for n in chunk)
                records, _ = _sn_get(
                    config,
                    auth_manager,
                    table_name,
                    in_query,
                    table_info["fields"],
                    limit=len(chunk),
                )
                api_calls += 1

                for rec in records:
                    rec_name = rec.get("name", rec.get("id", "unknown"))
                    for code_field in table_info["code_fields"]:
                        code = rec.get(code_field, "")
                        if code:
                            findings = _scan_code(
                                code,
                                code_field,
                                rec_name,
                                risk_patterns,
                                params.include_code_snippets,
                                params.snippet_chars,
                            )
                            risk_findings.extend(findings)

    # Risk summary
    risk_summary = {"high": 0, "medium": 0, "low": 0}
    for f in risk_findings:
        sev = f.get("severity", "low")
        if sev in risk_summary:
            risk_summary[sev] += 1

    # --- Phase 4: Cross-reference analysis ---
    cross_refs: Dict[str, Any] = {}

    # Check for OAuth credentials in the update set
    oauth_entries = inventory.get("oauth_credential", [])
    cross_refs["oauth_in_update_set"] = len(oauth_entries) > 0
    if oauth_entries:
        cross_refs["oauth_entries"] = [
            {"target_name": e.get("target_name", ""), "action": e.get("action", "")}
            for e in oauth_entries
        ]

    # Check widget-provider M2M relationships
    widget_ids_in_set = set()
    for entry in entries:
        if entry.get("name") == "sp_widget":
            widget_ids_in_set.add(entry.get("target_name", ""))

    if widget_ids_in_set:
        # Query M2M to find shared providers
        try:
            m2m_query = "sp_widget.nameIN" + ",".join(
                _escape_query(n) for n in list(widget_ids_in_set)[:MAX_IN_CHUNK]
            )
            m2m_records, _ = _sn_get(
                config,
                auth_manager,
                "m2m_sp_widget_angular_provider",
                m2m_query,
                "sys_id,sp_widget,sp_angular_provider",
                limit=200,
            )
            api_calls += 1

            provider_to_widgets: Dict[str, List[str]] = {}
            for rec in m2m_records:
                provider = rec.get("sp_angular_provider", "")
                widget = rec.get("sp_widget", "")
                if provider and widget:
                    provider_to_widgets.setdefault(provider, []).append(widget)

            shared = [
                {"provider": p, "used_by_widgets": ws}
                for p, ws in provider_to_widgets.items()
                if len(ws) > 1
            ]
            cross_refs["shared_providers"] = shared
            cross_refs["total_provider_links"] = len(m2m_records)
        except Exception as exc:
            logger.warning("M2M cross-reference query failed: %s", exc)
            cross_refs["shared_providers"] = []

    # --- Phase 5: Build recommendations ---
    recommendations: List[str] = []

    if risk_summary["high"] > 0:
        recommendations.append(
            f"HIGH: {risk_summary['high']} high-severity risk(s) found — "
            "review eval(), innerHTML, or Function() usage immediately."
        )
    if risk_summary["medium"] > 0:
        recommendations.append(
            f"MEDIUM: {risk_summary['medium']} medium-severity finding(s) — "
            "check DOM manipulation, direct $http calls, and window.location usage."
        )
    if cross_refs.get("oauth_in_update_set"):
        recommendations.append(
            "HIGH: OAuth credential entries detected in the update set — "
            "verify no secrets are exposed in the payload."
        )
    if clone_candidates:
        clone_names = ", ".join(c["target_name"] for c in clone_candidates[:5])
        recommendations.append(
            f"INFO: {len(clone_candidates)} potential duplicate/clone entries: {clone_names}"
        )

    m2m_count = len(inventory.get("m2m_dependency", []))
    layout_count = len(inventory.get("layout", []))
    if m2m_count > 0 or layout_count > 0:
        recommendations.append(
            f"INFO: {m2m_count} M2M dependency + {layout_count} layout records auto-included — "
            "these are typically pulled in by widget saves, verify they belong."
        )

    if not recommendations:
        recommendations.append("No significant risks detected. Review inventory for completeness.")

    return {
        "success": True,
        "developer": params.developer,
        "date_range": {"from": date_from, "to": date_to},
        "total_entries": total or len(entries),
        "api_calls": api_calls,
        "inventory": inventory_summary,
        "risk_findings": risk_findings[:100],  # Cap for token efficiency
        "risk_summary": risk_summary,
        "clone_candidates": clone_candidates,
        "cross_references": cross_refs,
        "recommendations": recommendations,
    }
