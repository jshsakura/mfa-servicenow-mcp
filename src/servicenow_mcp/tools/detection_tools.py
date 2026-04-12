"""
Specialized code-pattern detection tools for ServiceNow portal sources.

Unlike generic regex search (search_portal_regex_matches), these detectors
understand *business-rule structure*: they look for a specific field being
branched on, collect the set of literal values used in those branches, and
compare against a required set to surface omissions.

Design principles (inherited from portal_dev_tools):
- Minimize API calls: count first, fetch only what's needed
- Strip fields we don't scan (template, css) to save bandwidth
- Clamp limits to prevent runaway queries
- Return compact, actionable output for LLM consumption
"""

import logging
import re
from concurrent.futures import as_completed
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .sn_api import _page_executor
from .sn_api import sn_count as _sn_count_shared
from .sn_api import sn_query_all as _sn_query_all_shared

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIDGET_TABLE = "sp_widget"
ANGULAR_PROVIDER_TABLE = "sp_angular_provider"
ANGULAR_PROVIDER_M2M_TABLE = "m2m_sp_widget_angular_provider"

MAX_DETECT_WIDGETS = 100
MAX_DETECT_MATCHES = 200
DEFAULT_SNIPPET_LENGTH = 220

# ---------------------------------------------------------------------------
# Detection regex patterns for profit_company_code (or any target field)
# ---------------------------------------------------------------------------

# These patterns capture the *value* being compared against a target field.
# They are built dynamically from the user-supplied field patterns.


def _build_field_alternation(field_patterns: List[str]) -> str:
    """Build a regex alternation for the target field names.

    Example: ["profit_company_code", "c.data.profit_company_code"]
    -> r"(?:profit_company_code|c\\.data\\.profit_company_code)"
    """
    escaped = [re.escape(fp) for fp in field_patterns]
    return "(?:" + "|".join(escaped) + ")"


def _build_detection_regexes(field_alt: str) -> List[re.Pattern[str]]:
    """Return compiled regexes that capture literal code values near the target field.

    Each regex should have at least one capture group that yields the code value.
    """
    patterns = [
        # == / === / != / !== comparison:  field == 'CODE'  or  'CODE' == field
        re.compile(
            rf"""(?:"""
            rf"""{field_alt}\s*[!=]==?\s*['"]([^'"]+)['"]"""
            rf"""|"""
            rf"""['"]([^'"]+)['"]\s*[!=]==?\s*{field_alt}"""
            rf""")""",
            re.MULTILINE,
        ),
        # switch(field) ... case 'CODE':
        # We first confirm a switch on the field, then collect case literals
        # (handled specially in _extract_switch_codes)
        # Array.includes / indexOf:
        #   ['2400','5K00'].includes(field)
        #   [field].indexOf('CODE')  — rare but possible
        #   field == '2400' || field == '5K00'  — caught by first pattern
        re.compile(
            rf"""\[\s*(?:['"][^'"]*['"]\s*,\s*)*['"]([^'"]+)['"]\s*(?:,\s*['"][^'"]*['"]\s*)*\]\s*\.\s*includes\s*\(\s*{field_alt}\s*\)""",
            re.MULTILINE,
        ),
        # indexOf with field:  arr.indexOf(field)  — less common, skip
        # Ternary shorthand:  field == 'CODE' ? ... — caught by first pattern
    ]
    return patterns


# Regex to find switch(field) blocks and extract case literals
def _build_switch_regex(field_alt: str) -> re.Pattern[str]:
    return re.compile(
        rf"""switch\s*\(\s*{field_alt}\s*\)""",
        re.MULTILINE,
    )


CASE_LITERAL_RE = re.compile(r"""case\s+['"]([^'"]+)['"]""")


def _extract_includes_array_codes(source: str, field_alt_pattern: str) -> Set[str]:
    """Extract all codes from array.includes(field) patterns.

    Handles: ['2400', '5K00', '2J00'].includes(profit_company_code)
    Returns all string literals inside the array brackets.
    """
    codes: Set[str] = set()
    pattern = re.compile(
        rf"""\[([^\]]*)\]\s*\.\s*includes\s*\(\s*{field_alt_pattern}\s*\)""",
        re.MULTILINE,
    )
    for m in pattern.finditer(source):
        array_content = m.group(1)
        for lit in re.findall(r"""['"]([^'"]+)['"]""", array_content):
            codes.add(lit)
    return codes


def _extract_switch_codes(source: str, switch_regex: re.Pattern[str]) -> Set[str]:
    """Find switch(field) blocks and extract case 'CODE' literals."""
    codes: Set[str] = set()
    for m in switch_regex.finditer(source):
        # Scan forward from the switch statement to collect case literals
        # We look within a reasonable window (2000 chars) after the switch
        start = m.end()
        window = source[start : start + 2000]
        for case_match in CASE_LITERAL_RE.finditer(window):
            codes.add(case_match.group(1))
        # Stop if we hit another switch or function boundary
    return codes


def _extract_comparison_codes(source: str, detection_regexes: List[re.Pattern[str]]) -> Set[str]:
    """Extract all literal code values from == / === / != comparisons."""
    codes: Set[str] = set()
    for regex in detection_regexes:
        for m in regex.finditer(source):
            # Multiple capture groups — take whichever matched
            for g in m.groups():
                if g:
                    codes.add(g)
    return codes


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------


def _assess_confidence(
    found_codes: Set[str],
    missing_codes: Set[str],
    required_codes: Set[str],
    has_direct_comparison: bool,
) -> str:
    """Assess confidence level of a missing-code finding.

    high:   direct == comparison on the field with some required codes present, others missing
    medium: array includes / switch with some present, others missing
    low:    field name mentioned but branching context is weak
    """
    if not missing_codes:
        return "none"
    overlap = found_codes & required_codes
    if not overlap:
        return "low"
    if has_direct_comparison and len(overlap) >= 1:
        return "high"
    if len(overlap) >= 1:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Snippet extraction helpers (lightweight versions from portal_tools)
# ---------------------------------------------------------------------------


def _to_one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _line_col(source: str, index: int) -> Tuple[int, int]:
    line = source.count("\n", 0, index) + 1
    line_start = source.rfind("\n", 0, index)
    col = index + 1 if line_start == -1 else index - line_start
    return line, col


def _snippet_around(source: str, start: int, end: int, max_length: int) -> str:
    left = max(0, start - 90)
    right = min(len(source), end + 90)
    return _to_one_line(source[left:right])[:max_length]


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def _escape_query(value: str) -> str:
    return str(value).replace("^", "^^").replace("=", r"\=").replace("@", r"\@")


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
    return _sn_query_all_shared(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        page_size=page_size,
        max_records=max_records,
    )


def _sn_count(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
) -> int:
    return _sn_count_shared(config, auth_manager, table=table, query=query)


def _as_ref_sys_id(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        inner = value.get("value")
        if isinstance(inner, str) and inner:
            return inner
    if isinstance(value, str) and value:
        return value
    return None


# ---------------------------------------------------------------------------
# Core scan logic
# ---------------------------------------------------------------------------


def _scan_source_for_missing_codes(
    source: str,
    field_patterns: List[str],
    required_codes: Set[str],
    detection_regexes: List[re.Pattern[str]],
    switch_regex: re.Pattern[str],
    field_alt_pattern: str,
    snippet_length: int,
) -> Optional[Dict[str, Any]]:
    """Scan a single source string for missing profit_company_code branches.

    Returns a finding dict if missing codes are detected, else None.
    """
    if not source:
        return None

    # Quick check: does the source mention the target field at all?
    field_mentioned = False
    first_field_pos = -1
    for fp in field_patterns:
        pos = source.find(fp)
        if pos >= 0:
            field_mentioned = True
            if first_field_pos < 0 or pos < first_field_pos:
                first_field_pos = pos
            break
    if not field_mentioned:
        return None

    # Collect all codes found via various patterns
    comparison_codes = _extract_comparison_codes(source, detection_regexes)
    switch_codes = _extract_switch_codes(source, switch_regex)
    includes_codes = _extract_includes_array_codes(source, field_alt_pattern)

    all_found = comparison_codes | switch_codes | includes_codes

    # Filter to only codes that overlap with the required set
    # (ignore unrelated literals that happen to appear)
    found_required = all_found & required_codes
    missing = required_codes - all_found

    if not found_required:
        # The field is mentioned but none of the required codes appear
        # This might be a dynamic reference — low confidence
        return None

    if not missing:
        # All required codes present — no finding
        return None

    # Build snippet around the first field mention
    line, col = _line_col(source, first_field_pos)
    snippet = _snippet_around(
        source,
        first_field_pos,
        first_field_pos + len(field_patterns[0]),
        snippet_length,
    )

    has_direct = bool(comparison_codes & required_codes)
    confidence = _assess_confidence(found_required, missing, required_codes, has_direct)

    return {
        "line": line,
        "column": col,
        "snippet": snippet,
        "found_codes": sorted(found_required),
        "missing_codes": sorted(missing),
        "detection_methods": sorted(
            {
                *(["comparison"] if comparison_codes & required_codes else []),
                *(["switch"] if switch_codes & required_codes else []),
                *(["includes"] if includes_codes & required_codes else []),
            }
        ),
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Pydantic params
# ---------------------------------------------------------------------------


class DetectMissingCodesParams(BaseModel):
    """Parameters for the missing-code detector."""

    scope: Optional[str] = Field(
        default=None,
        description="App scope filter (sys_scope). Example: x_company_bpm",
    )
    widget_prefix: Optional[str] = Field(
        default=None,
        description="Widget id/name prefix to filter. Example: hopes (matches nameLIKEhopes^ORidLIKEhopes)",
    )
    widget_ids: Optional[List[str]] = Field(
        default=None,
        description="Explicit widget sys_id/id/name list. Overrides widget_prefix when provided.",
    )
    required_codes: List[str] = Field(
       default= ...,
        description='Code values that MUST all appear together in branch logic. Example: ["2400", "5K00", "2J00"]',
    )
    target_field_patterns: List[str] = Field(
        default=["profit_company_code", "c.data.profit_company_code", "data.profit_company_code"],
        description="Field name patterns to look for in source code. All variations that reference the same field.",
    )
    include_widget_client_script: bool = Field(
        default=True,
        description="Scan widget client_script field",
    )
    include_widget_server_script: bool = Field(
        default=True,
        description="Scan widget server script field",
    )
    include_angular_providers: bool = Field(
        default=False,
        description="Expand scan to Angular providers linked to matched widgets (adds M2M queries)",
    )
    max_widgets: int = Field(
        default=25,
        description=f"Maximum widgets to scan (clamped to {MAX_DETECT_WIDGETS})",
    )
    max_matches: int = Field(
        default=50,
        description=f"Maximum findings to return (clamped to {MAX_DETECT_MATCHES})",
    )
    page_size: int = Field(default=50, description="Pagination size for API queries (10..100)")
    snippet_length: int = Field(
        default=DEFAULT_SNIPPET_LENGTH,
        description="Maximum snippet length per finding",
    )
    output_mode: str = Field(
        default="compact",
        description="Output detail level: minimal | compact | full",
    )


# ---------------------------------------------------------------------------
# Output shaping
# ---------------------------------------------------------------------------


def _shape_finding(
    source_type: str,
    source_sys_id: str,
    source_name: str,
    field_name: str,
    detail: Dict[str, Any],
    output_mode: str,
) -> Dict[str, Any]:
    """Shape a single finding for output."""
    if output_mode == "minimal":
        return {
            "location": f"{source_type}/{source_name}/{field_name}",
            "line": detail["line"],
            "found_codes": detail["found_codes"],
            "missing_codes": detail["missing_codes"],
            "confidence": detail["confidence"],
        }
    if output_mode == "compact":
        return {
            "location": f"{source_type}/{source_name}/{field_name}",
            "sys_id": source_sys_id,
            "line": detail["line"],
            "snippet": detail["snippet"],
            "found_codes": detail["found_codes"],
            "missing_codes": detail["missing_codes"],
            "detection_methods": detail["detection_methods"],
            "confidence": detail["confidence"],
        }
    # full
    return {
        "source_type": source_type,
        "source_sys_id": source_sys_id,
        "source_name": source_name,
        "field": field_name,
        "line": detail["line"],
        "column": detail["column"],
        "snippet": detail["snippet"],
        "found_codes": detail["found_codes"],
        "missing_codes": detail["missing_codes"],
        "detection_methods": detail["detection_methods"],
        "confidence": detail["confidence"],
    }


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


@register_tool(
    "detect_missing_profit_company_codes",
    params=DetectMissingCodesParams,
    description=(
        "Detect missing profit_company_code branch values in portal widget and provider scripts. "
        "Scans for conditional patterns (==, switch, includes) and reports where some required codes "
        "are present but others are missing. Designed for code-set completeness audits."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def detect_missing_profit_company_codes(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DetectMissingCodesParams,
) -> Dict[str, Any]:
    # Validate output_mode
    output_mode = params.output_mode.strip().lower()
    if output_mode not in {"minimal", "compact", "full"}:
        return {
            "success": False,
            "message": "output_mode must be one of: minimal, compact, full",
            "findings": [],
        }

    # Validate required_codes
    required_codes = {c.strip() for c in params.required_codes if c.strip()}
    if len(required_codes) < 2:
        return {
            "success": False,
            "message": "required_codes must contain at least 2 distinct values to detect omissions.",
            "findings": [],
        }

    # Clamp limits
    max_widgets = max(1, min(params.max_widgets, MAX_DETECT_WIDGETS))
    max_matches = max(1, min(params.max_matches, MAX_DETECT_MATCHES))
    page_size = max(10, min(params.page_size, 100))
    snippet_length = max(80, min(params.snippet_length, 500))

    # Build detection regexes from target field patterns
    field_patterns = [fp.strip() for fp in params.target_field_patterns if fp.strip()]
    if not field_patterns:
        return {
            "success": False,
            "message": "target_field_patterns must contain at least one field pattern.",
            "findings": [],
        }
    field_alt = _build_field_alternation(field_patterns)
    detection_regexes = _build_detection_regexes(field_alt)
    switch_regex = _build_switch_regex(field_alt)

    # -----------------------------------------------------------------------
    # Phase 1: Build widget query
    # -----------------------------------------------------------------------
    query_parts: List[str] = []
    if params.scope:
        query_parts.append(f"sys_scope={_escape_query(params.scope)}")

    if params.widget_ids:
        id_tokens = [
            _escape_query(v) for v in params.widget_ids if isinstance(v, str) and v.strip()
        ]
        if id_tokens:
            query_parts.append(
                "("
                + "^OR".join(
                    [f"sys_id={t}" for t in id_tokens]
                    + [f"id={t}" for t in id_tokens]
                    + [f"name={t}" for t in id_tokens]
                )
                + ")"
            )
    elif params.widget_prefix:
        prefix = _escape_query(params.widget_prefix.strip())
        query_parts.append(f"(nameLIKE{prefix}^ORidLIKE{prefix})")

    widget_query = "^".join(query_parts) if query_parts else ""

    # Phase 1.5: Count first to pre-report cost
    widget_count = _sn_count(config, auth_manager, WIDGET_TABLE, widget_query)

    warnings: List[str] = []
    if widget_count == 0:
        return {
            "success": True,
            "message": "No widgets matched the filter criteria.",
            "scan_summary": {
                "widgets_matched": 0,
                "widgets_scanned": 0,
                "findings_count": 0,
            },
            "findings": [],
            "warnings": [],
        }
    if widget_count > max_widgets:
        warnings.append(
            f"Found {widget_count} widgets but max_widgets={max_widgets}. "
            f"Only the first {max_widgets} will be scanned. Use widget_prefix or widget_ids to narrow."
        )
    if not params.widget_prefix and not params.widget_ids:
        warnings.append(
            "No widget_prefix or widget_ids specified. Consider narrowing the scan target."
        )

    # -----------------------------------------------------------------------
    # Phase 2: Fetch widget sources (only script fields we need)
    # -----------------------------------------------------------------------
    fetch_fields = ["sys_id", "name", "id", "sys_scope"]
    if params.include_widget_client_script:
        fetch_fields.append("client_script")
    if params.include_widget_server_script:
        fetch_fields.append("script")

    widget_rows = _sn_query_all(
        config,
        auth_manager,
        table=WIDGET_TABLE,
        query=widget_query,
        fields=",".join(fetch_fields),
        page_size=page_size,
        max_records=max_widgets,
    )

    # -----------------------------------------------------------------------
    # Phase 3: Scan each widget's script fields
    # -----------------------------------------------------------------------
    findings: List[Dict[str, Any]] = []
    widget_ids_for_m2m: List[str] = []

    for widget in widget_rows:
        if len(findings) >= max_matches:
            break
        w_sys_id = str(widget.get("sys_id") or "")
        w_name = str(widget.get("name") or widget.get("id") or w_sys_id)
        if w_sys_id:
            widget_ids_for_m2m.append(w_sys_id)

        scan_fields: List[Tuple[str, str]] = []
        if params.include_widget_client_script:
            scan_fields.append(("client_script", str(widget.get("client_script") or "")))
        if params.include_widget_server_script:
            scan_fields.append(("script", str(widget.get("script") or "")))

        for field_name, source in scan_fields:
            if len(findings) >= max_matches:
                break
            detail = _scan_source_for_missing_codes(
                source=source,
                field_patterns=field_patterns,
                required_codes=required_codes,
                detection_regexes=detection_regexes,
                switch_regex=switch_regex,
                field_alt_pattern=field_alt,
                snippet_length=snippet_length,
            )
            if detail:
                findings.append(
                    _shape_finding(
                        source_type="widget",
                        source_sys_id=w_sys_id,
                        source_name=w_name,
                        field_name=field_name,
                        detail=detail,
                        output_mode=output_mode,
                    )
                )

    # -----------------------------------------------------------------------
    # Phase 4 (optional): Scan linked Angular providers
    # -----------------------------------------------------------------------
    providers_scanned = 0
    if params.include_angular_providers and widget_ids_for_m2m and len(findings) < max_matches:
        # Lookup provider sys_ids via M2M (parallel chunks)
        provider_ids: Set[str] = set()
        chunk_size = 100
        chunks = [
            widget_ids_for_m2m[i : i + chunk_size]
            for i in range(0, len(widget_ids_for_m2m), chunk_size)
        ]

        def _fetch_m2m(chunk: List[str]) -> List[Dict[str, Any]]:
            return _sn_query_all(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_M2M_TABLE,
                query=f"sp_widgetIN{','.join(_escape_query(v) for v in chunk)}",
                fields="sp_angular_provider",
                page_size=page_size,
                max_records=1000,
            )

        if len(chunks) == 1:
            m2m_rows = _fetch_m2m(chunks[0])
        else:
            m2m_rows = []
            futures = {_page_executor.submit(_fetch_m2m, c): c for c in chunks}
            for future in as_completed(futures):
                try:
                    m2m_rows.extend(future.result())
                except Exception:
                    logger.warning("Parallel M2M chunk query failed")
        for row in m2m_rows:
            pid = _as_ref_sys_id(row.get("sp_angular_provider"))
            if pid:
                provider_ids.add(pid)

        if provider_ids:
            provider_query = f"sys_idIN{','.join(sorted(provider_ids))}"
            if params.scope:
                provider_query += f"^sys_scope={_escape_query(params.scope)}"
            provider_rows = _sn_query_all(
                config,
                auth_manager,
                table=ANGULAR_PROVIDER_TABLE,
                query=provider_query,
                fields="sys_id,name,script",
                page_size=page_size,
                max_records=200,
            )
            providers_scanned = len(provider_rows)
            for prov in provider_rows:
                if len(findings) >= max_matches:
                    break
                p_script = str(prov.get("script") or "")
                p_sys_id = str(prov.get("sys_id") or "")
                p_name = str(prov.get("name") or p_sys_id)
                detail = _scan_source_for_missing_codes(
                    source=p_script,
                    field_patterns=field_patterns,
                    required_codes=required_codes,
                    detection_regexes=detection_regexes,
                    switch_regex=switch_regex,
                    field_alt_pattern=field_alt,
                    snippet_length=snippet_length,
                )
                if detail:
                    findings.append(
                        _shape_finding(
                            source_type="angular_provider",
                            source_sys_id=p_sys_id,
                            source_name=p_name,
                            field_name="script",
                            detail=detail,
                            output_mode=output_mode,
                        )
                    )

    # -----------------------------------------------------------------------
    # Result
    # -----------------------------------------------------------------------
    trimmed = findings[:max_matches]

    return {
        "success": True,
        "filters": {
            "scope": params.scope,
            "widget_prefix": params.widget_prefix,
            "widget_ids": params.widget_ids,
            "required_codes": sorted(required_codes),
            "target_field_patterns": field_patterns,
            "include_widget_client_script": params.include_widget_client_script,
            "include_widget_server_script": params.include_widget_server_script,
            "include_angular_providers": params.include_angular_providers,
            "output_mode": output_mode,
        },
        "scan_summary": {
            "widgets_matched": widget_count,
            "widgets_scanned": len(widget_rows),
            "providers_scanned": providers_scanned,
            "findings_count": len(trimmed),
            "max_widgets": max_widgets,
            "max_matches": max_matches,
        },
        "findings": trimmed,
        "warnings": warnings,
        "safety_notice": (
            "Findings are static-analysis heuristics based on string-literal pattern matching. "
            "Dynamic values (variables, config lookups) are not tracked. "
            "Verify each finding with get_portal_component_code before patching."
        ),
    }
