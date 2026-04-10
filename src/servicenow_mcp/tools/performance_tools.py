"""
Performance analysis tools for ServiceNow widgets and scripts.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .log_tools import GetTransactionLogsParams, get_transaction_logs
from .sn_api import GenericQueryParams, sn_query
from .source_tools import get_metadata_source

logger = logging.getLogger(__name__)

PERFORMANCE_PATTERNS = {
    "glide_record_loop": {
        "pattern": r"while\s*\(\s*\w+\.next\(\)\s*\)",
        "description": "GlideRecord loop detected - check for N+1 queries",
        "severity": "medium",
    },
    "nested_gr_query": {
        "pattern": r"(?:new\s+GlideRecord|gr\s*=\s*new\s+GlideRecord).*?(?:new\s+GlideRecord|gr\s*=\s*new\s+GlideRecord)",
        "description": "Nested GlideRecord queries - potential N+1 issue",
        "severity": "high",
    },
    "getvalue_in_loop": {
        "pattern": r"\.getValue\s*\([^)]+\)",
        "description": "Multiple getValue() calls - consider using displayValue or single query",
        "severity": "low",
    },
    "heavy_validation": {
        "pattern": r"(?:gs\.getUser|gs\.getUserName|gs\.getUserID)\s*\(",
        "description": "User lookups in validation - consider caching",
        "severity": "low",
    },
    "ajax_in_loop": {
        "pattern": r"(?:for|while)\s*\([^)]*\)\s*\{[^}]*(?:GlideAjax|\$http|\.ajax)[^}]*\}",
        "description": "AJAX calls inside loop - severe performance impact",
        "severity": "critical",
    },
    "missing_setlimit": {
        "pattern": r"new\s+GlideRecord\s*\([^)]+\)[^}]*\.query\s*\(\s*\)",
        "description": "GlideRecord query without setLimit - potential memory issue",
        "severity": "medium",
    },
    "unindexed_query": {
        "pattern": r"addQuery\s*\(\s*['\"](?:u_|[a-z_]+_)",
        "description": "Query on potentially unindexed custom field",
        "severity": "info",
    },
    "client_update_no_debounce": {
        "pattern": r"\$watch\s*\([^)]*,\s*function",
        "description": "Angular watch without debounce - can trigger excessive updates",
        "severity": "medium",
    },
    "server_update_bulk": {
        "pattern": r"server\.update\s*\([^)]*\)",
        "description": "Server update call - check if batching is possible",
        "severity": "info",
    },
}

OPTIMIZATION_SUGGESTIONS = {
    "glide_record_loop": [
        "Use GlideAggregate for count/sum operations",
        "Consider query() with JOIN instead of nested queries",
        "Add setLimit() to prevent unbounded queries",
    ],
    "nested_gr_query": [
        "Refactor to use a single query with proper joins",
        "Consider using GlideAggregate for aggregation",
        "Cache reference field lookups",
    ],
    "ajax_in_loop": [
        "Collect all data first, then make single AJAX call",
        "Use server-side batching",
        "Consider using server.update() with batch data",
    ],
    "missing_setlimit": [
        "Add .setLimit(n) before .query()",
        "Implement pagination for large datasets",
    ],
    "client_update_no_debounce": [
        "Add debounce with $timeout or _.debounce()",
        "Use ng-model-options with debounce",
    ],
}

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
    "JSON",
    "Error",
    "Function",
    "Number",
    "String",
    "Boolean",
    "Math",
}


class AnalyzeWidgetPerformanceParams(BaseModel):
    """Parameters for widget performance analysis."""

    widget_id: str = Field(..., description="Widget sys_id, id, or name to analyze")
    page_id: Optional[str] = Field(
        None, description="Optional page id to correlate with transaction logs"
    )
    min_response_time_ms: int = Field(
        3000, description="Minimum response time threshold in milliseconds"
    )
    timeframe: str = Field("last_7d", description="Time window: last_hour, last_24h, last_7d")
    analysis_depth: str = Field("standard", description="Analysis depth: quick, standard, deep")
    include_auto_fix_suggestions: bool = Field(
        True, description="Include auto-fix suggestions where applicable"
    )
    include_script_includes: bool = Field(True, description="Analyze linked script includes")
    include_angular_providers: bool = Field(True, description="Analyze linked Angular providers")
    max_script_length: int = Field(8000, description="Maximum script length to analyze")


class PatternMatch(BaseModel):
    """Detected performance pattern."""

    pattern_type: str
    description: str
    severity: str
    line: Optional[int] = None
    snippet: Optional[str] = None
    source: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)


class PerformanceReport(BaseModel):
    """Structured performance analysis report."""

    widget_id: str
    widget_name: Optional[str] = None
    page_id: Optional[str] = None
    slow_transactions_count: int = 0
    avg_response_time_ms: Optional[float] = None
    max_response_time_ms: Optional[float] = None
    slow_transactions: List[Dict[str, Any]] = Field(default_factory=list)
    patterns_found: List[PatternMatch] = Field(default_factory=list)
    pattern_summary: Dict[str, int] = Field(default_factory=dict)
    recommendations: List[str] = Field(default_factory=list)
    auto_fix_available: bool = False
    analysis_depth: str = "standard"
    sources_analyzed: List[str] = Field(default_factory=list)


def _extract_script_references(script: str) -> Set[str]:
    """Extract Script Include class references from script code."""
    if not script:
        return set()

    pattern = r"\bnew\s+(?:global\.)?([A-Z][A-Za-z0-9_]*)\s*\("
    matches = re.findall(pattern, script)
    return {m for m in matches if m not in IGNORED_CONSTRUCTORS}


def _detect_patterns(script: str, source_name: str) -> List[PatternMatch]:
    """Detect performance anti-patterns in script code."""
    if not script:
        return []

    patterns: List[PatternMatch] = []
    lines = script.split("\n")

    for pattern_type, config in PERFORMANCE_PATTERNS.items():
        try:
            regex = re.compile(config["pattern"], re.DOTALL | re.IGNORECASE)
            for match in regex.finditer(script):
                line_num = script[: match.start()].count("\n") + 1
                start_line = max(0, line_num - 2)
                end_line = min(len(lines), line_num + 2)
                snippet = "\n".join(lines[start_line:end_line])
                if len(snippet) > 200:
                    snippet = snippet[:200] + "..."

                patterns.append(
                    PatternMatch(
                        pattern_type=pattern_type,
                        description=config["description"],
                        severity=config["severity"],
                        line=line_num,
                        snippet=snippet,
                        source=source_name,
                        suggestions=OPTIMIZATION_SUGGESTIONS.get(pattern_type, []),
                    )
                )
        except re.error:
            continue

    return patterns


def _analyze_transaction_logs(
    config: ServerConfig,
    auth_manager: AuthManager,
    widget_id: str,
    page_id: Optional[str],
    min_response_time_ms: int,
    timeframe: str,
) -> Dict[str, Any]:
    """Analyze transaction logs for slow requests."""
    result: Dict[str, Any] = {
        "count": 0,
        "avg_response_time": None,
        "max_response_time": None,
        "transactions": [],
    }

    url_filter = f"{page_id}|{widget_id}" if page_id else widget_id

    log_result = get_transaction_logs(
        config,
        auth_manager,
        GetTransactionLogsParams(
            url_contains=url_filter.split("|")[0],
            min_response_time_ms=min_response_time_ms,
            timeframe=timeframe,
            limit=20,
            max_text_length=500,
        ),
    )

    if not log_result.get("success"):
        return result

    transactions = log_result.get("results", [])
    if not transactions:
        return result

    response_times = []
    for tx in transactions:
        rt = tx.get("response_time")
        if rt is not None:
            try:
                response_times.append(float(rt))
            except (ValueError, TypeError):
                continue

    if response_times:
        result["count"] = len(response_times)
        result["avg_response_time"] = sum(response_times) / len(response_times)
        result["max_response_time"] = max(response_times)
        result["transactions"] = [
            {
                "url": tx.get("url"),
                "response_time": tx.get("response_time"),
                "response_status": tx.get("response_status"),
                "created_on": tx.get("sys_created_on"),
                "created_by": tx.get("sys_created_by"),
            }
            for tx in transactions[:10]
        ]

    return result


def _fetch_widget_bundle(
    config: ServerConfig,
    auth_manager: AuthManager,
    widget_id: str,
) -> Dict[str, Any]:
    """Fetch widget code and metadata."""
    query = f"sys_id={widget_id}^ORid={widget_id}^ORname={widget_id}"

    response = sn_query(
        config,
        auth_manager,
        GenericQueryParams(
            table="sp_widget",
            query=query,
            fields="sys_id,name,id,script,client_script",
            limit=1,
            display_value=False,
        ),
    )

    if not response.get("success") or not response.get("results"):
        return {}

    return response["results"][0]


def _fetch_angular_providers(
    config: ServerConfig,
    auth_manager: AuthManager,
    widget_sys_id: str,
) -> List[Dict[str, Any]]:
    """Fetch Angular providers linked to widget."""
    m2m_response = sn_query(
        config,
        auth_manager,
        GenericQueryParams(
            table="m2m_sp_widget_angular_provider",
            query=f"sp_widget={widget_sys_id}",
            fields="sp_angular_provider",
            limit=50,
            display_value=False,
        ),
    )

    if not m2m_response.get("success"):
        return []

    provider_refs = []
    for m2m in m2m_response.get("results", []):
        prov = m2m.get("sp_angular_provider", {})
        if isinstance(prov, dict):
            prov_id = prov.get("value")
        else:
            prov_id = prov
        if prov_id:
            provider_refs.append(str(prov_id))

    if not provider_refs:
        return []

    prov_response = sn_query(
        config,
        auth_manager,
        GenericQueryParams(
            table="sp_angular_provider",
            query=f"sys_idIN{','.join(provider_refs)}",
            fields="sys_id,name,script",
            limit=50,
            display_value=False,
        ),
    )

    return prov_response.get("results", []) if prov_response.get("success") else []


@register_tool(
    "analyze_widget_performance",
    params=AnalyzeWidgetPerformanceParams,
    description="Analyze a widget's code patterns, transaction logs, and data provider usage. Returns performance findings.",
    serialization="raw_dict",
    return_type=dict,
)
def analyze_widget_performance(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: AnalyzeWidgetPerformanceParams,
) -> Dict[str, Any]:
    """
    Analyze widget performance and detect anti-patterns.

    Automates performance analysis by:
    - Fetching transaction logs for slow requests
    - Retrieving widget code and dependencies
    - Detecting common performance anti-patterns
    - Generating structured recommendations
    """
    report = PerformanceReport(
        widget_id=params.widget_id,
        page_id=params.page_id,
        analysis_depth=params.analysis_depth,
    )

    sources_analyzed: List[str] = []
    all_patterns: List[PatternMatch] = []

    tx_analysis = _analyze_transaction_logs(
        config,
        auth_manager,
        params.widget_id,
        params.page_id,
        params.min_response_time_ms,
        params.timeframe,
    )

    report.slow_transactions_count = tx_analysis["count"]
    report.avg_response_time_ms = tx_analysis["avg_response_time"]
    report.max_response_time_ms = tx_analysis["max_response_time"]
    report.slow_transactions = tx_analysis["transactions"]

    widget = _fetch_widget_bundle(config, auth_manager, params.widget_id)
    if not widget:
        return {
            "success": False,
            "error": f"Widget '{params.widget_id}' not found",
            "report": report.model_dump(),
        }

    widget_sys_id = widget.get("sys_id", "")
    widget_name = widget.get("name") or widget.get("id") or params.widget_id
    report.widget_name = widget_name

    server_script = str(widget.get("script") or "")[: params.max_script_length]
    if server_script:
        patterns = _detect_patterns(server_script, f"widget/{widget_name}/script")
        all_patterns.extend(patterns)
        sources_analyzed.append(f"sp_widget/{widget_name}/script")

    client_script = str(widget.get("client_script") or "")[: params.max_script_length]
    if client_script:
        patterns = _detect_patterns(client_script, f"widget/{widget_name}/client_script")
        all_patterns.extend(patterns)
        sources_analyzed.append(f"sp_widget/{widget_name}/client_script")

    if params.include_angular_providers and params.analysis_depth in ("standard", "deep"):
        providers = _fetch_angular_providers(config, auth_manager, widget_sys_id)
        for prov in providers[:10]:
            prov_name = prov.get("name") or prov.get("sys_id") or "unknown"
            prov_script = str(prov.get("script") or "")[: params.max_script_length]
            if prov_script:
                patterns = _detect_patterns(prov_script, f"provider/{prov_name}")
                all_patterns.extend(patterns)
                sources_analyzed.append(f"sp_angular_provider/{prov_name}")

    if params.include_script_includes and params.analysis_depth == "deep":
        refs = _extract_script_references(server_script)
        for ref_name in list(refs)[:5]:
            si_result = get_metadata_source(
                config,
                auth_manager,
                type(
                    "SIParams",
                    (),
                    {
                        "source_type": "script_include",
                        "source_id": ref_name,
                        "max_field_length": 4000,
                    },
                )(),
            )
            if si_result and si_result.get("script"):
                si_script = str(si_result["script"])[: params.max_script_length]
                patterns = _detect_patterns(si_script, f"script_include/{ref_name}")
                all_patterns.extend(patterns)
                sources_analyzed.append(f"sys_script_include/{ref_name}")

    pattern_counts: Dict[str, int] = {}
    for p in all_patterns:
        pattern_counts[p.pattern_type] = pattern_counts.get(p.pattern_type, 0) + 1

    report.patterns_found = all_patterns
    report.pattern_summary = pattern_counts
    report.sources_analyzed = sources_analyzed

    recommendations = []

    if report.slow_transactions_count > 5:
        recommendations.append(
            f"Found {report.slow_transactions_count} slow transactions (>{params.min_response_time_ms}ms). "
            f"Average: {report.avg_response_time_ms:.0f}ms, Max: {report.max_response_time_ms:.0f}ms"
        )

    critical_patterns = [p for p in all_patterns if p.severity == "critical"]
    high_patterns = [p for p in all_patterns if p.severity == "high"]

    if critical_patterns:
        recommendations.append(
            f"CRITICAL: {len(critical_patterns)} critical performance issues detected. "
            "These must be addressed immediately."
        )
        report.auto_fix_available = True

    if high_patterns:
        recommendations.append(
            f"HIGH: {len(high_patterns)} high-severity issues detected. "
            "Review and optimize these patterns."
        )

    for pattern_type, count in sorted(pattern_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            suggestions = OPTIMIZATION_SUGGESTIONS.get(pattern_type, [])
            if suggestions:
                recommendations.append(f"[{pattern_type}] {suggestions[0]}")

    if not recommendations:
        recommendations.append("No significant performance issues detected.")

    report.recommendations = recommendations

    return {
        "success": True,
        "report": report.model_dump(),
        "summary": {
            "widget": widget_name,
            "slow_transactions": report.slow_transactions_count,
            "avg_response_time_ms": report.avg_response_time_ms,
            "patterns_found": len(all_patterns),
            "critical_issues": len(critical_patterns),
            "high_issues": len(high_patterns),
            "sources_analyzed": len(sources_analyzed),
        },
        "quick_actions": (
            [
                "Review critical patterns in server script",
                "Add setLimit() to GlideRecord queries",
                "Consider batching server.update() calls",
                "Implement debouncing for client-side watchers",
            ]
            if all_patterns
            else ["No immediate actions required"]
        ),
    }
