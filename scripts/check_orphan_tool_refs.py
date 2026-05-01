#!/usr/bin/env python
"""CI gate: scan docs/skills/website/README for tool name references that no
longer exist in the live tool registry.

Run before any wrapper deletion ships. Exits non-zero if it finds any orphan
reference. The "live registry" is read from
``servicenow_mcp.tools._module_index.TOOL_MODULE_INDEX``, which is regenerated
by ``scripts/regenerate_tool_module_index.py``, plus ``RUNTIME_INJECTED_TOOLS``
for tools that aren't in the static index but exist at runtime.

Heuristic for "this string is being used as a tool reference":
  * appears inside backticks ``X``
  * OR appears inside bold ``**X**``
  * OR appears at the start of a bulleted list item (``- X`` / ``* X`` /
    ``1. X``)
  * OR appears as a YAML key (``  - X`` or ``X:``)

Free-floating identifiers in prose are intentionally ignored to avoid catching
Python variable names, Pydantic action-enum values, ServiceNow scope names,
etc. — those are usually false positives in markdown.

Token shape further requires:
  * snake_case with at least one underscore
  * starts with a known tool-action verb (create_/update_/get_/list_/manage_/sn_/...)
  * not on ALLOWLIST below

Skipped directories: ``.venv``, ``.ipynb_checkpoints``, ``node_modules``,
``__pycache__``, ``.git``.

False-positive policy: if a real non-tool identifier still trips the gate,
add it to ALLOWLIST below with a one-line comment explaining why.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent

# Verbs / prefixes that signal "this snake_case word is probably a tool name."
TOOL_PREFIXES: tuple[str, ...] = (
    "activate_",
    "add_",
    "analyze_",
    "approve_",
    "audit_",
    "check_",
    "commit_",
    "compare_",
    "create_",
    "deactivate_",
    "delete_",
    "download_",
    "execute_",
    "fetch_",
    "format_",
    "generate_",
    "get_",
    "invalidate_",
    "list_",
    "manage_",
    "move_",
    "preview_",
    "publish_",
    "rebuild_",
    "reject_",
    "remove_",
    "reorder_",
    "resolve_",
    "route_",
    "run_",
    "scaffold_",
    "search_",
    "setup_",
    "sn_",
    "submit_",
    "sync_",
    "trace_",
    "update_",
)

# Tools that aren't in the static module index but exist at runtime
# (registered directly in server.py rather than via @register_tool).
RUNTIME_INJECTED_TOOLS: set[str] = {
    "list_tool_packages",
}

# Identifiers that match the tool-name shape but legitimately appear in docs as
# something other than a registered tool. Keep this list tight — only add when
# you've confirmed the match is a real false positive.
ALLOWLIST: set[str] = {
    # Anti-pattern examples in CONSOLIDATION_PLAN.md / PHASE_4_PLAYBOOK.md
    "manage_record",
    "manage_itsm",
    "manage_workflow_things",
    "sn_create",
    "sn_do",
    "sn_update",
    "sn_transition",
    # Internal Python helpers in tools/sn_api.py — not registered as MCP tools
    # but documented in README as performance internals.
    "sn_batch",
    "sn_query_all",
    # Action enum values inside manage_X tool descriptions (e.g. "create/update/add_file")
    "add_file",
    "add_task",
    "update_code",
    # Placeholder syntax in CLAUDE.md ("Use <list_tool> first to find...")
    "list_tool",
    "list_actions",
    # Script filenames (referenced as commands, not tools)
    "regenerate_tool_module_index",
    "regenerate_tool_inventory",
    "check_orphan_tool_refs",
    "setup_install",
    "setup_skills",
    "setup_installer",
    # Internal helpers / methods that look tool-shaped
    "get_headers",
    "get_auth_headers",
    "get_started",
    "get_tool_definitions",
    "get_tool_schema",
    "list_tools",
    "list_resources",
    "list_resource_templates",
    "read_resource",
    "call_tool",
    "register_tool",
    "create_table",
    "create_app",
    "create_params",
    "update_set",
    "update_fields",
    "update_data",  # manage_portal_component parameter name in skill instructions
    "list_view",
    "run_tests",
    "run_pytest",
    # ServiceNow scope/plugin names (sn_hr_* family of plugin scopes)
    "sn_hr_",
    "sn_hr_sp",
    "sn_hr_service_portal",
}

# Directory names that should never be scanned (third-party / generated).
SKIP_DIRS: set[str] = {
    ".venv",
    ".ipynb_checkpoints",
    "node_modules",
    "__pycache__",
    ".git",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}

# Match references in documentation contexts. Each pattern captures the token
# (group 1) without surrounding markup.
_REF_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"`([a-z][a-z0-9_]*_[a-z0-9_]+)`"),  # backtick: `tool_name`
    re.compile(r"\*\*([a-z][a-z0-9_]*_[a-z0-9_]+)\*\*"),  # bold: **tool_name**
    re.compile(r"^\s*[-*]\s+([a-z][a-z0-9_]*_[a-z0-9_]+)\b", re.MULTILINE),  # bullet: - tool_name
    re.compile(
        r"^\s*\d+\.\s+([a-z][a-z0-9_]*_[a-z0-9_]+)\b", re.MULTILINE
    ),  # numbered: 1. tool_name
    re.compile(r"^\s*-\s+([a-z][a-z0-9_]*_[a-z0-9_]+)\s*$", re.MULTILINE),  # YAML list entry
    re.compile(r"^([a-z][a-z0-9_]*_[a-z0-9_]+):", re.MULTILINE),  # YAML key
)


def load_registry() -> set[str]:
    """Return the set of tool names currently in the live registry."""
    src_path = REPO_ROOT / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    from servicenow_mcp.tools._module_index import TOOL_MODULE_INDEX

    return set(TOOL_MODULE_INDEX.keys()) | RUNTIME_INJECTED_TOOLS


def _looks_like_tool(token: str) -> bool:
    return any(token.startswith(p) for p in TOOL_PREFIXES)


def scan_file(path: Path, registry: set[str]) -> list[tuple[int, str, str]]:
    """Return [(line_no, line, orphan_token)] for orphan refs in this file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []

    findings: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()

    # Build line offset -> line_no map for reporting.
    line_starts = [0]
    for ch in text:
        if ch == "\n":
            line_starts.append(line_starts[-1] + 1)
        else:
            line_starts[-1] += 1
    # Reconstruct simpler: just split.
    lines = text.splitlines()

    def _line_no_for_offset(offset: int) -> int:
        # Walk lines until cumulative length exceeds offset.
        cum = 0
        for i, line in enumerate(lines, start=1):
            cum += len(line) + 1  # +1 for newline
            if cum > offset:
                return i
        return len(lines)

    for pattern in _REF_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(1)
            if token in registry or token in ALLOWLIST:
                continue
            if not _looks_like_tool(token):
                continue
            line_no = _line_no_for_offset(match.start(1))
            key = (line_no, token)
            if key in seen:
                continue
            seen.add(key)
            line = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
            findings.append((line_no, line.rstrip(), token))
    return findings


def collect_files() -> Iterable[Path]:
    targets: list[Path] = []
    for top_level in ("README.md", "README.ko.md", "CLAUDE.md"):
        p = REPO_ROOT / top_level
        if p.is_file():
            targets.append(p)
    for sub in ("skills", "docs", "website"):
        d = REPO_ROOT / sub
        if not d.is_dir():
            continue
        for ext in ("*.md", "*.mdx", "*.yaml", "*.yml"):
            for f in d.rglob(ext):
                if any(part in SKIP_DIRS for part in f.parts):
                    continue
                targets.append(f)
    return targets


def main() -> int:
    registry = load_registry()
    files = list(collect_files())

    orphans: dict[str, list[tuple[Path, int, str]]] = {}
    for f in files:
        for line_no, line, token in scan_file(f, registry):
            orphans.setdefault(token, []).append((f.relative_to(REPO_ROOT), line_no, line))

    if not orphans:
        print(
            f"OK: no orphan tool references found "
            f"({len(registry)} tools in registry, {len(files)} files scanned)."
        )
        return 0

    total_refs = sum(len(v) for v in orphans.values())
    print(f"FAIL: {len(orphans)} unknown tool name(s) referenced in {total_refs} place(s):\n")
    for tok in sorted(orphans):
        hits = orphans[tok]
        print(f"  - {tok}  ({len(hits)} ref{'s' if len(hits) != 1 else ''})")
        for fp, ln, line in hits[:5]:
            snippet = line.strip()
            if len(snippet) > 110:
                snippet = snippet[:107] + "..."
            print(f"      {fp}:{ln}: {snippet}")
        if len(hits) > 5:
            print(f"      ... and {len(hits) - 5} more")
        print()

    print(
        "Action: either restore the missing tool, update the doc to reference "
        "its replacement (e.g. manage_X(action=...)), or add the token to "
        "ALLOWLIST in this script with a justification."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
