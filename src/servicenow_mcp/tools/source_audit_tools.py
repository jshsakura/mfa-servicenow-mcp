"""
Local source audit tool — analyzes downloaded app sources WITHOUT any API calls.
Generates cross-references, dead code detection, execution order maps,
and a self-contained HTML audit report.
"""

import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns for cross-reference extraction
# ---------------------------------------------------------------------------

GLIDE_CONSTRUCTOR_RE = re.compile(
    r"\bnew\s+(?:global\.)?(GlideRecord|GlideRecordSecure|GlideAggregate)\s*\(\s*[\"']([a-z][a-z0-9_]{1,79})[\"']\s*\)",
    re.IGNORECASE,
)
SCRIPT_INCLUDE_CALL_RE = re.compile(r"\bnew\s+(?:global\.)?([A-Z][A-Za-z0-9_]*)\s*\(")
WIDGET_EMBED_RE = re.compile(r"""<sp-widget\s+id=["']([^"']+)["']""", re.IGNORECASE)
PROVIDER_INJECT_RE = re.compile(r"""\$inject\s*=\s*\[([^\]]+)\]""")
GR_SET_TABLE_RE = re.compile(r"""\.\s*setTableName\s*\(\s*["']([a-z][a-z0-9_]{1,79})["']\s*\)""")
ANGULAR_DEPENDENCY_RE = re.compile(
    r"""(?:factory|service|directive|filter|provider)\s*\(\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
GS_INCLUDE_RE = re.compile(r"""\bgs\.include\s*\(\s*["']([^"']+)["']\s*\)""")

IGNORED_CLASSES = {
    "GlideRecord",
    "GlideRecordSecure",
    "GlideAggregate",
    "GlideDateTime",
    "GlideDuration",
    "GlideElement",
    "GlideAjax",
    "GlideSession",
    "GlideSysAttachment",
    "GlideFilter",
    "GlidePluginManager",
    "GlideEncrypter",
    "GlideUpdateManager",
    "GlideStringUtil",
    "Object",
    "Array",
    "Date",
    "RegExp",
    "Error",
    "Promise",
    "Map",
    "Set",
    "JSON",
    "Math",
    "Number",
    "String",
    "Boolean",
    "Function",
    "XMLDocument",
    "XMLHttpRequest",
}


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _scan_source_index(scope_root: Path) -> List[Dict[str, Any]]:
    """Build a flat index of all source records under scope_root.

    Recognizes two metadata formats:
    - _metadata.json (from _download_source_types): has source_type, table, sys_id
    - _widget.json (from download_portal_sources): has tableName, sys_id, name
    Also picks up flat provider/SI files from portal download (no metadata dir).
    """
    entries: List[Dict[str, Any]] = []
    seen_dirs: set[str] = set()

    # --- Pass 1: _metadata.json directories (from _download_source_types) ---
    for meta_file in sorted(scope_root.rglob("_metadata.json")):
        meta = _read_json(meta_file)
        if not meta or not isinstance(meta, dict):
            continue
        record_dir = meta_file.parent
        seen_dirs.add(str(record_dir))
        source_files = [
            f.name for f in record_dir.iterdir() if f.is_file() and not f.name.startswith("_")
        ]
        total_lines = _count_lines_in_dir(record_dir)
        entries.append(
            {
                "source_type": meta.get("source_type", ""),
                "table": meta.get("table", ""),
                "sys_id": meta.get("sys_id", ""),
                "name": meta.get("name", record_dir.name),
                "path": str(record_dir.relative_to(scope_root)),
                "files": source_files,
                "lines": total_lines,
                "active": meta.get("active", "true"),
                "collection": meta.get("collection", ""),
                "when": meta.get("when", ""),
                "order": meta.get("order", ""),
            }
        )

    # --- Pass 2: _widget.json directories (from download_portal_sources) ---
    for widget_file in sorted(scope_root.rglob("_widget.json")):
        record_dir = widget_file.parent
        if str(record_dir) in seen_dirs:
            continue
        seen_dirs.add(str(record_dir))
        wdata = _read_json(widget_file)
        if not wdata or not isinstance(wdata, dict):
            continue
        source_files = [
            f.name for f in record_dir.iterdir() if f.is_file() and not f.name.startswith("_")
        ]
        total_lines = _count_lines_in_dir(record_dir)
        entries.append(
            {
                "source_type": "widget",
                "table": wdata.get("tableName", "sp_widget"),
                "sys_id": wdata.get("sys_id", ""),
                "name": wdata.get("name", record_dir.name),
                "path": str(record_dir.relative_to(scope_root)),
                "files": source_files,
                "lines": total_lines,
                "active": "true",
                "collection": "",
                "when": "",
                "order": "",
            }
        )

    # --- Pass 3: flat files from portal download (sp_angular_provider/*.script.js) ---
    for table_dir in sorted(scope_root.iterdir()):
        if not table_dir.is_dir() or table_dir.name.startswith("_"):
            continue
        # Map directory names to source types
        dir_type_map = {
            "sp_angular_provider": "angular_provider",
            "sys_script_include": "script_include",
        }
        source_type = dir_type_map.get(table_dir.name)
        if not source_type:
            continue
        map_file = table_dir / "_map.json"
        name_map = _read_json(map_file) if map_file.exists() else {}
        if not isinstance(name_map, dict):
            name_map = {}
        for src_file in sorted(table_dir.iterdir()):
            if not src_file.is_file() or src_file.name.startswith("_"):
                continue
            # Flat file: e.g. quotationService.script.js
            file_name = src_file.stem.split(".")[0]  # strip .script etc.
            if str(src_file.parent / file_name) in seen_dirs:
                continue  # already indexed from _metadata.json dir
            # Check it's not inside a subdirectory (those are handled above)
            if src_file.parent != table_dir:
                continue
            try:
                lines = src_file.read_text(encoding="utf-8").count("\n") + 1
            except Exception:
                lines = 0
            entries.append(
                {
                    "source_type": source_type,
                    "table": table_dir.name,
                    "sys_id": name_map.get(file_name, ""),
                    "name": file_name,
                    "path": str(src_file.relative_to(scope_root)),
                    "files": [src_file.name],
                    "lines": lines,
                    "active": "true",
                    "collection": "",
                    "when": "",
                    "order": "",
                }
            )

    return entries


def _count_lines_in_dir(record_dir: Path) -> int:
    """Count total lines in non-metadata source files."""
    total = 0
    for sf in record_dir.iterdir():
        if sf.is_file() and not sf.name.startswith("_"):
            try:
                total += sf.read_text(encoding="utf-8").count("\n") + 1
            except Exception:
                pass
    return total


def _extract_references_from_script(script: str) -> Dict[str, Set[str]]:
    """Extract all reference types from a script."""
    refs: Dict[str, Set[str]] = {
        "tables": set(),
        "script_includes": set(),
        "widgets": set(),
        "providers": set(),
    }

    for _, table in GLIDE_CONSTRUCTOR_RE.findall(script):
        refs["tables"].add(table)
    for table in GR_SET_TABLE_RE.findall(script):
        refs["tables"].add(table)

    for cls in SCRIPT_INCLUDE_CALL_RE.findall(script):
        if cls not in IGNORED_CLASSES:
            refs["script_includes"].add(cls)
    for cls in GS_INCLUDE_RE.findall(script):
        refs["script_includes"].add(cls)

    for widget_id in WIDGET_EMBED_RE.findall(script):
        refs["widgets"].add(widget_id)

    for dep in ANGULAR_DEPENDENCY_RE.findall(script):
        refs["providers"].add(dep)

    # $inject array: api.$inject = ['dep1', 'dep2', 'myService']
    for inject_match in PROVIDER_INJECT_RE.findall(script):
        for dep in re.findall(r"""["']([^"'$][^"']*)["']""", inject_match):
            refs["providers"].add(dep)

    return refs


def _build_cross_references(
    scope_root: Path,
    source_index: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Scan all source files and build a cross-reference graph."""
    # source_name -> what it references (outgoing)
    outgoing: Dict[str, Dict[str, List[str]]] = {}
    # target_name -> who references it (incoming)
    incoming: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    # All known source names for orphan detection
    known_names: Set[str] = set()
    known_si_names: Set[str] = set()

    known_provider_names: Set[str] = set()
    for entry in source_index:
        name = entry["name"]
        known_names.add(name)
        if entry["source_type"] == "script_include":
            known_si_names.add(name)
        elif entry["source_type"] == "angular_provider":
            known_provider_names.add(name)

    for entry in source_index:
        name = entry["name"]
        record_path = scope_root / entry["path"]
        all_refs: Dict[str, Set[str]] = {
            "tables": set(),
            "script_includes": set(),
            "widgets": set(),
            "providers": set(),
        }

        # Handle both directory (has sub-files) and flat file structures
        source_files: List[Path] = []
        if record_path.is_dir():
            source_files = [
                sf for sf in record_path.iterdir() if sf.is_file() and not sf.name.startswith("_")
            ]
        elif record_path.is_file():
            source_files = [record_path]

        for sf in source_files:
            if sf.is_file() and not sf.name.startswith("_"):
                script = _read_text(sf)
                if script:
                    refs = _extract_references_from_script(script)
                    for key in all_refs:
                        all_refs[key].update(refs[key])
                    # Name-match: if any known provider/SI name appears in the
                    # script text, it's a reference (catches Angular DI injection,
                    # function parameters, and any other usage pattern).
                    for pname in known_provider_names:
                        if pname != name and pname in script:
                            all_refs["providers"].add(pname)
                    for si_name in known_si_names:
                        if si_name != name and si_name in script:
                            all_refs["script_includes"].add(si_name)

        outgoing[name] = {k: sorted(v) for k, v in all_refs.items() if v}

        # Record incoming references
        source_info = {"name": name, "type": entry["source_type"]}
        for si_name in all_refs["script_includes"]:
            incoming[si_name].append(source_info)
        for widget_id in all_refs["widgets"]:
            incoming[widget_id].append(source_info)
        for provider in all_refs["providers"]:
            incoming[provider].append(source_info)
        for table in all_refs["tables"]:
            incoming[f"table:{table}"].append(source_info)

    return {
        "outgoing": outgoing,
        "incoming": dict(incoming),
        "known_names": sorted(known_names),
        "known_si_names": sorted(known_si_names),
    }


def _detect_orphans(
    source_index: List[Dict[str, Any]],
    cross_refs: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Find sources that nobody references."""
    incoming = cross_refs["incoming"]
    orphans: List[Dict[str, Any]] = []

    for entry in source_index:
        name = entry["name"]
        source_type = entry["source_type"]
        # Only check types where orphans matter
        if source_type not in ("script_include", "widget", "angular_provider"):
            continue
        if name not in incoming and entry.get("active", "true") != "false":
            orphans.append(
                {
                    "name": name,
                    "source_type": source_type,
                    "sys_id": entry["sys_id"],
                    "lines": entry["lines"],
                    "path": entry["path"],
                }
            )

    return orphans


def _extract_external_refs(cross_refs: Dict[str, Any]) -> Dict[str, List[str]]:
    """Find references to components NOT in this scope (global/external).

    Returns dict with keys: script_includes, providers, tables — each a
    sorted list of names that are referenced but not present locally.
    """
    known = set(cross_refs.get("known_names", []))
    ext_si: set[str] = set()
    ext_providers: set[str] = set()
    ext_tables: set[str] = set()

    for refs in cross_refs.get("outgoing", {}).values():
        for si in refs.get("script_includes", []):
            if si not in known:
                ext_si.add(si)
        for prov in refs.get("providers", []):
            if prov not in known:
                ext_providers.add(prov)
        for table in refs.get("tables", []):
            ext_tables.add(table)

    return {
        "script_includes": sorted(ext_si),
        "providers": sorted(ext_providers),
        "tables": sorted(ext_tables),
    }


def _build_execution_order(source_index: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Group BRs and Client Scripts by target table with execution order."""
    table_map: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
        lambda: {"business_rules": [], "client_scripts": [], "ui_actions": [], "acls": []}
    )

    for entry in source_index:
        st = entry["source_type"]
        collection = entry.get("collection", "")
        table_field = entry.get("table", collection) if st != "business_rule" else collection

        if not table_field:
            continue

        item = {
            "name": entry["name"],
            "sys_id": entry["sys_id"],
            "active": entry.get("active", "true"),
            "when": entry.get("when", ""),
            "order": entry.get("order", ""),
        }

        if st == "business_rule":
            table_map[table_field]["business_rules"].append(item)
        elif st in ("client_script", "catalog_client_script"):
            table_map[table_field]["client_scripts"].append(item)
        elif st == "ui_action":
            table_map[table_field]["ui_actions"].append(item)
        elif st == "acl":
            table_map[table_field]["acls"].append(item)

    # Sort by order field
    result: Dict[str, Any] = {}
    for table, groups in sorted(table_map.items()):
        for key in groups:
            groups[key].sort(key=lambda x: (x.get("when", ""), x.get("order", "0")))
        # Only include tables with at least one entry
        if any(groups[k] for k in groups):
            result[table] = groups

    return result


def _validate_schema_references(
    scope_root: Path,
    cross_refs: Dict[str, Any],
) -> List[Dict[str, str]]:
    """Check if referenced table fields exist in downloaded schemas."""
    schema_dir = scope_root / "_schema"
    if not schema_dir.is_dir():
        return []

    issues: List[Dict[str, str]] = []
    # Load all schemas
    schemas: Dict[str, Set[str]] = {}
    for schema_file in schema_dir.glob("*.json"):
        if schema_file.name.startswith("_"):
            continue
        data = _read_json(schema_file)
        if data and "fields" in data:
            table_name = data.get("table", schema_file.stem)
            schemas[table_name] = {f["field"] for f in data["fields"] if f.get("field")}

    # Check if referenced tables exist in schemas
    incoming = cross_refs.get("incoming", {})
    for key, refs in incoming.items():
        if key.startswith("table:"):
            table = key[6:]
            if (
                table not in schemas
                and not table.startswith("sys_")
                and not table.startswith("cmdb_")
            ):
                issues.append(
                    {
                        "type": "unknown_table",
                        "table": table,
                        "referenced_by": ", ".join(r["name"] for r in refs[:5]),
                        "ref_count": str(len(refs)),
                    }
                )

    return issues


# ---------------------------------------------------------------------------
# HTML Report Generator
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Source Audit Report — {scope}</title>
<style>
:root {{
  --bg: #0f172a; --surface: #1e293b; --surface2: #334155;
  --border: #475569; --text: #e2e8f0; --text2: #94a3b8;
  --accent: #38bdf8; --accent2: #818cf8; --green: #4ade80;
  --red: #f87171; --yellow: #fbbf24; --orange: #fb923c;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Segoe UI', -apple-system, sans-serif;
  background: var(--bg); color: var(--text);
  line-height: 1.6; padding: 2rem;
}}
.container {{ max-width: 1400px; margin: 0 auto; }}
h1 {{
  font-size: 1.8rem; font-weight: 700;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  margin-bottom: 0.5rem;
}}
.subtitle {{ color: var(--text2); font-size: 0.9rem; margin-bottom: 2rem; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
.card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 1.2rem;
}}
.card .label {{ font-size: 0.75rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.05em; }}
.card .value {{ font-size: 1.8rem; font-weight: 700; color: var(--accent); margin-top: 0.25rem; }}
.card .detail {{ font-size: 0.8rem; color: var(--text2); margin-top: 0.25rem; }}
.section {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; margin-bottom: 1.5rem; overflow: hidden;
}}
.section-header {{
  padding: 1rem 1.5rem; border-bottom: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center; cursor: pointer;
}}
.section-header h2 {{ font-size: 1.1rem; font-weight: 600; }}
.section-header .badge {{
  background: var(--surface2); color: var(--accent);
  padding: 0.2rem 0.8rem; border-radius: 99px; font-size: 0.8rem; font-weight: 600;
}}
.section-body {{ padding: 1.5rem; }}
.section-body.collapsed {{ display: none; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ text-align: left; color: var(--text2); font-weight: 500; padding: 0.6rem 0.8rem; border-bottom: 1px solid var(--border); }}
td {{ padding: 0.6rem 0.8rem; border-bottom: 1px solid var(--surface2); }}
tr:hover td {{ background: var(--surface2); }}
.tag {{
  display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px;
  font-size: 0.75rem; font-weight: 500; margin-right: 0.3rem; margin-bottom: 0.2rem;
}}
.tag-si {{ background: #1e3a5f; color: #93c5fd; }}
.tag-br {{ background: #3b1f1f; color: #fca5a5; }}
.tag-widget {{ background: #1a3a2a; color: #86efac; }}
.tag-table {{ background: #3d2f10; color: #fde68a; }}
.tag-acl {{ background: #2d1f3d; color: #c4b5fd; }}
.tag-orphan {{ background: #4a1515; color: var(--red); }}
.tag-issue {{ background: #4a3515; color: var(--yellow); }}
.ref-list {{ display: flex; flex-wrap: wrap; gap: 0.3rem; }}
.status-ok {{ color: var(--green); }}
.status-warn {{ color: var(--yellow); }}
.status-error {{ color: var(--red); }}
.exec-group {{ margin-bottom: 1rem; }}
.exec-group h3 {{ font-size: 0.95rem; color: var(--accent); margin-bottom: 0.5rem; }}
.exec-when {{ font-size: 0.75rem; color: var(--text2); margin-left: 0.5rem; }}
.footer {{ text-align: center; color: var(--text2); font-size: 0.8rem; margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid var(--border); }}
</style>
</head>
<body>
<div class="container">
  <h1>Source Audit Report</h1>
  <div class="subtitle">{scope} &mdash; {instance} &mdash; {timestamp}</div>

  <!-- Summary Cards -->
  <div class="grid">
    {summary_cards}
  </div>

  <!-- Source Type Breakdown -->
  <div class="section">
    <div class="section-header" onclick="toggle(this)">
      <h2>Source Type Breakdown</h2>
      <span class="badge">{total_sources} records</span>
    </div>
    <div class="section-body">
      <table>
        <tr><th>Type</th><th>Table</th><th>Count</th><th>Total Lines</th></tr>
        {type_breakdown_rows}
      </table>
    </div>
  </div>

  <!-- Orphans / Dead Code -->
  <div class="section">
    <div class="section-header" onclick="toggle(this)">
      <h2>Orphan / Dead Code Detection</h2>
      <span class="badge {orphan_badge_class}">{orphan_count} found</span>
    </div>
    <div class="section-body{orphan_collapsed}">
      {orphan_content}
    </div>
  </div>

  <!-- Schema Issues -->
  <div class="section">
    <div class="section-header" onclick="toggle(this)">
      <h2>Schema Validation Issues</h2>
      <span class="badge {schema_badge_class}">{schema_issue_count} issues</span>
    </div>
    <div class="section-body{schema_collapsed}">
      {schema_content}
    </div>
  </div>

  <!-- Execution Order -->
  <div class="section">
    <div class="section-header" onclick="toggle(this)">
      <h2>Execution Order Map</h2>
      <span class="badge">{exec_table_count} tables</span>
    </div>
    <div class="section-body collapsed">
      {execution_order_content}
    </div>
  </div>

  <!-- Cross References -->
  <div class="section">
    <div class="section-header" onclick="toggle(this)">
      <h2>Cross-Reference Graph</h2>
      <span class="badge">{xref_count} connections</span>
    </div>
    <div class="section-body collapsed">
      {xref_content}
    </div>
  </div>

  <!-- Source Index -->
  <div class="section">
    <div class="section-header" onclick="toggle(this)">
      <h2>Source Index</h2>
      <span class="badge">{total_sources} entries</span>
    </div>
    <div class="section-body collapsed">
      <table>
        <tr><th>Name</th><th>Type</th><th>Lines</th><th>Active</th><th>Files</th></tr>
        {source_index_rows}
      </table>
    </div>
  </div>

  <div class="footer">
    Generated by ServiceNow MCP &mdash; audit_app_sources &mdash; {timestamp}
  </div>
</div>
<script>
function toggle(header) {{
  const body = header.nextElementSibling;
  body.classList.toggle('collapsed');
}}
</script>
</body>
</html>"""


def _tag(cls: str, text: str) -> str:
    return f'<span class="tag {cls}">{text}</span>'


def _generate_html_report(
    scope: str,
    instance: str,
    source_index: List[Dict[str, Any]],
    cross_refs: Dict[str, Any],
    orphans: List[Dict[str, Any]],
    execution_order: Dict[str, Any],
    schema_issues: List[Dict[str, str]],
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # --- Summary cards ---
    type_counts = Counter(e["source_type"] for e in source_index)
    total_lines = sum(e["lines"] for e in source_index)
    total_refs = sum(len(v) for v in cross_refs.get("outgoing", {}).values())

    cards = [
        ("Total Sources", str(len(source_index)), f"{len(type_counts)} types"),
        ("Total Lines", f"{total_lines:,}", "across all files"),
        ("Cross-References", str(total_refs), "outgoing links"),
        ("Orphans", str(len(orphans)), "potentially dead" if orphans else "all referenced"),
        (
            "Schema Issues",
            str(len(schema_issues)),
            "tables to verify" if schema_issues else "clean",
        ),
        ("Exec Tables", str(len(execution_order)), "with BR/CS/ACL"),
    ]
    summary_cards = "\n".join(
        f'<div class="card"><div class="label">{label}</div>'
        f'<div class="value">{value}</div><div class="detail">{detail}</div></div>'
        for label, value, detail in cards
    )

    # --- Type breakdown ---
    type_lines: Dict[str, int] = defaultdict(int)
    type_tables: Dict[str, str] = {}
    for e in source_index:
        type_lines[e["source_type"]] += e["lines"]
        type_tables[e["source_type"]] = e["table"]
    type_breakdown_rows = "\n".join(
        f'<tr><td>{st}</td><td><code>{type_tables.get(st, "")}</code></td>'
        f"<td>{type_counts[st]}</td><td>{type_lines[st]:,}</td></tr>"
        for st in sorted(type_counts, key=lambda x: -type_counts[x])
    )

    # --- Orphans ---
    if orphans:
        orphan_rows = "\n".join(
            f'<tr><td>{_tag("tag-orphan", o["source_type"])}{o["name"]}</td>'
            f'<td>{o["lines"]} lines</td><td><code>{o["path"]}</code></td></tr>'
            for o in sorted(orphans, key=lambda x: -x["lines"])
        )
        orphan_content = (
            f"<table><tr><th>Name</th><th>Size</th><th>Path</th></tr>{orphan_rows}</table>"
        )
        orphan_badge_class = "status-warn" if len(orphans) < 10 else "status-error"
        orphan_collapsed = ""
    else:
        orphan_content = '<p class="status-ok">No orphans detected. All sources are referenced.</p>'
        orphan_badge_class = "status-ok"
        orphan_collapsed = " collapsed"

    # --- Schema issues ---
    if schema_issues:
        schema_rows = "\n".join(
            f'<tr><td>{_tag("tag-issue", i["type"])}<code>{i["table"]}</code></td>'
            f'<td>{i["referenced_by"]}</td><td>{i["ref_count"]}</td></tr>'
            for i in schema_issues
        )
        schema_content = f"<table><tr><th>Table</th><th>Referenced By</th><th>Ref Count</th></tr>{schema_rows}</table>"
        schema_badge_class = "status-warn"
        schema_collapsed = ""
    else:
        schema_content = '<p class="status-ok">All referenced tables have matching schemas.</p>'
        schema_badge_class = "status-ok"
        schema_collapsed = " collapsed"

    # --- Execution order ---
    exec_parts: List[str] = []
    for table, groups in sorted(execution_order.items()):
        parts = [f'<div class="exec-group"><h3>{table}</h3>']
        for group_key, label in [
            ("business_rules", "Business Rules"),
            ("client_scripts", "Client Scripts"),
            ("ui_actions", "UI Actions"),
            ("acls", "ACLs"),
        ]:
            items = groups.get(group_key, [])
            if items:
                rows = "\n".join(
                    f'<tr><td>{item["name"]}</td>'
                    f'<td>{item.get("when", "")}</td>'
                    f'<td>{item.get("order", "")}</td>'
                    f'<td>{"active" if item.get("active", "true") == "true" else _tag("tag-orphan", "inactive")}</td></tr>'
                    for item in items
                )
                parts.append(
                    f'<h4 style="color:var(--text2);font-size:0.85rem;margin:0.5rem 0 0.3rem">{label}</h4>'
                    f"<table><tr><th>Name</th><th>When</th><th>Order</th><th>Status</th></tr>{rows}</table>"
                )
        parts.append("</div>")
        exec_parts.append("\n".join(parts))
    execution_order_content = (
        "\n".join(exec_parts)
        if exec_parts
        else '<p class="status-ok">No execution order entries found.</p>'
    )

    # --- Cross-references ---
    outgoing = cross_refs.get("outgoing", {})
    xref_total = sum(sum(len(v) for v in refs.values()) for refs in outgoing.values())
    xref_rows: List[str] = []
    for source_name in sorted(outgoing, key=lambda n: -sum(len(v) for v in outgoing[n].values())):
        refs = outgoing[source_name]
        ref_tags: List[str] = []
        for si in refs.get("script_includes", []):
            ref_tags.append(_tag("tag-si", si))
        for w in refs.get("widgets", []):
            ref_tags.append(_tag("tag-widget", w))
        for t in refs.get("tables", []):
            ref_tags.append(_tag("tag-table", t))
        for p in refs.get("providers", []):
            ref_tags.append(_tag("tag-acl", p))
        if ref_tags:
            xref_rows.append(
                f"<tr><td><strong>{source_name}</strong></td>"
                f'<td><div class="ref-list">{"".join(ref_tags)}</div></td></tr>'
            )
    xref_content = (
        f'<table><tr><th>Source</th><th>References</th></tr>{"".join(xref_rows)}</table>'
        if xref_rows
        else '<p class="status-ok">No cross-references found.</p>'
    )

    # --- Source index ---
    source_index_rows = "\n".join(
        f'<tr><td>{e["name"]}</td>'
        f'<td>{_tag("tag-si" if e["source_type"] == "script_include" else "tag-br", e["source_type"])}</td>'
        f'<td>{e["lines"]}</td>'
        f'<td>{"active" if e.get("active", "true") == "true" else _tag("tag-orphan", "inactive")}</td>'
        f'<td>{", ".join(e["files"])}</td></tr>'
        for e in sorted(source_index, key=lambda x: (-x["lines"], x["name"]))
    )

    return _HTML_TEMPLATE.format(
        scope=scope,
        instance=instance,
        timestamp=timestamp,
        summary_cards=summary_cards,
        total_sources=len(source_index),
        type_breakdown_rows=type_breakdown_rows,
        orphan_count=len(orphans),
        orphan_badge_class=orphan_badge_class,
        orphan_collapsed=orphan_collapsed,
        orphan_content=orphan_content,
        schema_issue_count=len(schema_issues),
        schema_badge_class=schema_badge_class,
        schema_collapsed=schema_collapsed,
        schema_content=schema_content,
        exec_table_count=len(execution_order),
        execution_order_content=execution_order_content,
        xref_count=xref_total,
        xref_content=xref_content,
        source_index_rows=source_index_rows,
    )


# ---------------------------------------------------------------------------
# Domain knowledge generation — single MD file
# ---------------------------------------------------------------------------


def _generate_domain_knowledge(
    scope_root: Path,
    scope: str,
    source_index: List[Dict[str, Any]],
    cross_refs: Dict[str, Any],
    orphans: List[Dict[str, Any]],
    execution_order: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate a single _domain_knowledge.md from audit analysis.

    This file is self-contained and can be:
    - Included in CLAUDE.md for always-on context
    - Read by LLM on-demand via file read
    - Exposed as MCP resource
    - Handed to a junior developer as-is
    """
    type_counts = Counter(e["source_type"] for e in source_index)
    total_lines = sum(e["lines"] for e in source_index)
    outgoing = cross_refs.get("outgoing", {})
    incoming = cross_refs.get("incoming", {})
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    sections: List[str] = []

    # --- Header ---
    sections.append(f"# Domain Knowledge: {scope}\n")
    sections.append(f"> Auto-generated by audit_local_sources at {timestamp}")
    sections.append(
        f"> {len(source_index)} sources, {total_lines:,} lines, "
        f"{len(execution_order)} tables with server logic\n"
    )

    # --- App Structure Overview ---
    sections.append("## App Structure\n")
    sections.append("| Type | Count | Lines |")
    sections.append("|------|-------|-------|")
    type_lines: Dict[str, int] = defaultdict(int)
    for e in source_index:
        type_lines[e["source_type"]] += e["lines"]
    for st in sorted(type_counts, key=lambda x: -type_counts[x]):
        sections.append(f"| {st} | {type_counts[st]} | {type_lines[st]:,} |")
    sections.append("")

    # --- Table Profiles ---
    if execution_order:
        sections.append("## Table Profiles\n")
        for table_name in sorted(execution_order):
            groups = execution_order[table_name]
            brs = groups.get("business_rules", [])
            css_list = groups.get("client_scripts", [])
            uas = groups.get("ui_actions", [])
            acls = groups.get("acls", [])

            parts = []
            if brs:
                br_desc = ", ".join(
                    f"{br['name']}({br.get('when', '?')}/{br.get('order', '?')})" for br in brs
                )
                parts.append(f"BR: {br_desc}")
            if css_list:
                parts.append(f"CS: {', '.join(cs['name'] for cs in css_list)}")
            if uas:
                parts.append(f"UA: {', '.join(ua['name'] for ua in uas)}")
            if acls:
                parts.append(f"ACL: {len(acls)}")

            # Who references this table
            table_key = f"table:{table_name}"
            refs = incoming.get(table_key, [])
            if refs:
                parts.append(f"Used by: {', '.join(r['name'] for r in refs[:5])}")

            sections.append(f"### {table_name}\n")
            for p in parts:
                sections.append(f"- {p}")
            sections.append("")

    # --- Script Include Dependency Map ---
    si_entries = [e for e in source_index if e["source_type"] == "script_include"]
    connected_sis = [e for e in si_entries if outgoing.get(e["name"]) or incoming.get(e["name"])]
    if connected_sis:
        sections.append("## Script Include Dependencies\n")
        for e in sorted(connected_sis, key=lambda x: -x["lines"]):
            name = e["name"]
            out = outgoing.get(name, {})
            inc = incoming.get(name, [])
            calls = out.get("script_includes", [])
            tables = out.get("tables", [])
            callers = [r["name"] for r in inc]

            desc_parts = [f"{e['lines']}L"]
            if tables:
                desc_parts.append(f"tables: {', '.join(tables)}")
            if calls:
                desc_parts.append(f"calls: {', '.join(calls)}")
            if callers:
                desc_parts.append(f"called by: {', '.join(callers[:5])}")

            sections.append(f"- **{name}** — {' | '.join(desc_parts)}")
        sections.append("")

    # --- Warnings ---
    warnings_added = False
    if orphans:
        if not warnings_added:
            sections.append("## Warnings\n")
            warnings_added = True
        sections.append("### Dead Code Candidates\n")
        for o in sorted(orphans, key=lambda x: -x["lines"]):
            sections.append(
                f"- **{o['name']}** ({o['source_type']}, {o['lines']} lines) — not referenced by any source"
            )
        sections.append("")

    complex_sources = [e for e in source_index if e["lines"] > 200]
    if complex_sources:
        if not warnings_added:
            sections.append("## Warnings\n")
            warnings_added = True
        sections.append("### High Complexity (>200 lines)\n")
        for e in sorted(complex_sources, key=lambda x: -x["lines"]):
            sections.append(f"- **{e['name']}** ({e['source_type']}, {e['lines']} lines)")
        sections.append("")

    # --- Hub Scripts (called by 3+ sources) ---
    hubs = [
        (name, refs)
        for name, refs in incoming.items()
        if not name.startswith("table:") and len(refs) >= 3
    ]
    if hubs:
        sections.append("## Hub Scripts (3+ callers)\n")
        for name, refs in sorted(hubs, key=lambda x: -len(x[1])):
            callers = [r["name"] for r in refs]
            sections.append(f"- **{name}** — {len(refs)} callers: {', '.join(callers[:8])}")
        sections.append("")

    # --- Write file ---
    content = "\n".join(sections)
    output_path = scope_root / "_domain_knowledge.md"
    output_path.write_text(content, encoding="utf-8")

    return {
        "path": str(output_path),
        "sections": {
            "tables": len(execution_order),
            "scripts": len(connected_sis),
            "orphans": len(orphans),
            "hubs": len(hubs),
            "complex": len(complex_sources),
        },
        "size_chars": len(content),
    }


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------


class AuditAppSourcesParams(BaseModel):
    source_root: str = Field(
        ...,
        description=(
            "Path to the downloaded source directory (e.g. temp/<instance>/<scope>). "
            "This is the output_root returned by download_app_sources."
        ),
    )
    output_file: Optional[str] = Field(
        default=None,
        description="Path for the HTML report. Defaults to <source_root>/_audit_report.html",
    )


@register_tool(
    "audit_local_sources",
    params=AuditAppSourcesParams,
    description=(
        "Analyze downloaded app sources locally (NO API calls). "
        "Generates cross-reference graph, orphan/dead code detection, "
        "execution order map, schema validation, and a self-contained HTML report. "
        "Returns only a summary to the conversation context."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def audit_local_sources(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: AuditAppSourcesParams,
) -> Dict[str, Any]:
    started = time.perf_counter()
    scope_root = Path(params.source_root).expanduser().resolve()

    if not scope_root.is_dir():
        return {"success": False, "message": f"source_root not found: {params.source_root}"}

    # Read manifest for scope/instance info
    manifest = _read_json(scope_root / "_manifest.json") or {}
    scope = manifest.get("scope", scope_root.name)
    instance = manifest.get("instance", "unknown")

    # 1. Build source index
    source_index = _scan_source_index(scope_root)
    if not source_index:
        return {"success": False, "message": "No source records found in source_root."}

    # 2. Build cross-references
    cross_refs = _build_cross_references(scope_root, source_index)

    # 3. Detect orphans
    orphans = _detect_orphans(source_index, cross_refs)

    # 4. Build execution order
    execution_order = _build_execution_order(source_index)

    # 5. Validate schema references
    schema_issues = _validate_schema_references(scope_root, cross_refs)

    # 6. Generate domain knowledge units
    domain_stats = _generate_domain_knowledge(
        scope_root,
        scope,
        source_index,
        cross_refs,
        orphans,
        execution_order,
    )

    # 8. Write JSON data files
    def _dl_write(p: Path, d: Any) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

    _dl_write(scope_root / "_source_index.json", source_index)
    _dl_write(
        scope_root / "_cross_references.json",
        {
            "outgoing": cross_refs["outgoing"],
            "incoming": cross_refs["incoming"],
        },
    )
    _dl_write(scope_root / "_orphans.json", orphans)
    _dl_write(scope_root / "_execution_order.json", execution_order)
    if schema_issues:
        _dl_write(scope_root / "_schema_issues.json", schema_issues)

    # 8. Generate HTML report
    html = _generate_html_report(
        scope=scope,
        instance=instance,
        source_index=source_index,
        cross_refs=cross_refs,
        orphans=orphans,
        execution_order=execution_order,
        schema_issues=schema_issues,
    )
    report_path = (
        Path(params.output_file) if params.output_file else scope_root / "_audit_report.html"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html, encoding="utf-8")

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return {
        "success": True,
        "scope": scope,
        "report_path": str(report_path),
        "duration_ms": elapsed_ms,
        "summary": {
            "total_sources": len(source_index),
            "total_lines": sum(e["lines"] for e in source_index),
            "type_counts": dict(Counter(e["source_type"] for e in source_index)),
            "cross_reference_count": sum(
                sum(len(v) for v in refs.values())
                for refs in cross_refs.get("outgoing", {}).values()
            ),
            "orphan_count": len(orphans),
            "orphan_names": [o["name"] for o in orphans[:20]],
            "external_references": _extract_external_refs(cross_refs),
            "schema_issue_count": len(schema_issues),
            "execution_order_tables": len(execution_order),
            "domain_knowledge": domain_stats.get("size_chars", 0),
        },
        "domain_knowledge": domain_stats,
        "generated_files": [
            str(scope_root / "_source_index.json"),
            str(scope_root / "_cross_references.json"),
            str(scope_root / "_orphans.json"),
            str(scope_root / "_execution_order.json"),
            domain_stats.get("path", ""),
            str(report_path),
        ],
        "safety_notice": (
            "Pure local analysis — zero API calls. "
            "HTML report and JSON data files written to disk. "
            "Only this summary is returned to the conversation context."
        ),
    }
