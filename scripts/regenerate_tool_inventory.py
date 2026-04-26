"""Regenerate docs/TOOL_INVENTORY.md from the live tool registry and package YAML.

Run this whenever tools or package membership change. A CI test fails if the
committed inventory drifts from the registry/package config, so you won't
forget — but the error message points here.

Usage: python3 scripts/regenerate_tool_inventory.py
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from servicenow_mcp.server import MANAGE_READ_ACTIONS, MUTATING_TOOL_NAMES, MUTATING_TOOL_PREFIXES
from servicenow_mcp.utils.tool_utils import get_tool_definitions

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "tool_packages.yaml"
DOC_PATH = ROOT / "docs" / "TOOL_INVENTORY.md"

PACKAGE_DESCRIPTIONS = {
    "none": "Disabled profile for intentionally turning tools off.",
    "core": "Minimal read-only essentials for quick health/schema/table work.",
    "standard": "Default read-only package across incidents, changes, portal, logs, and source analysis.",
    "service_desk": "standard plus incident and change write workflows for operational support.",
    "portal_developer": "standard plus portal, changeset, script include, and local-sync delivery workflows.",
    "platform_developer": "standard plus workflow, Flow Designer, UI policy, incident/change, and script writes.",
    "full": "Broadest packaged surface: all manage_* workflows plus advanced operations.",
}

READ_ONLY_OVERRIDES = {
    "resolve_page_dependencies",
    "resolve_widget_chain",
}

WRITE_ONLY_OVERRIDES = {
    "scaffold_page",
}

MODULE_TITLES = {
    "catalog_tools": "Catalog Tools",
    "change_tools": "Change Tools",
    "changeset_tools": "Changeset Tools",
    "core_tools": "Core API",
    "detect_tools": "Detection",
    "flow_designer_tools": "Flow Designer",
    "incident_tools": "Incident Management",
    "local_sync_tools": "Local Sync",
    "log_tools": "Logs",
    "perf_tools": "Performance",
    "portal_analysis_tools": "Portal Analysis",
    "portal_crud_tools": "Portal CRUD",
    "portal_tools": "Portal Management",
    "repo_tools": "Repository",
    "script_include_tools": "Script Include",
    "source_tools": "Source Analysis",
    "ui_policy_tools": "UI Policy",
    "user_group_tools": "User & Group",
    "workflow_tools": "Workflow",
}


def _load_packages() -> dict[str, list[str]]:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected dict package config, got {type(raw)}")

    resolved: dict[str, list[str]] = {}

    def resolve(name: str) -> list[str]:
        if name in resolved:
            return resolved[name]

        value = raw.get(name, [])
        if isinstance(value, list):
            resolved[name] = list(value)
            return resolved[name]

        base = resolve(value["_extends"]) if "_extends" in value else []
        merged = list(base)
        for tool in value.get("_tools", []):
            if tool not in merged:
                merged.append(tool)
        resolved[name] = merged
        return merged

    for key in raw:
        resolve(str(key))
    return resolved


def _is_write_tool(tool_name: str) -> bool:
    if tool_name in READ_ONLY_OVERRIDES:
        return False
    if tool_name in WRITE_ONLY_OVERRIDES:
        return True
    if tool_name in MANAGE_READ_ACTIONS:
        return True
    if tool_name in MUTATING_TOOL_NAMES:
        return True
    return tool_name.startswith(MUTATING_TOOL_PREFIXES)


def _rw_label(tool_name: str) -> str:
    if tool_name in MANAGE_READ_ACTIONS:
        return "R/W"
    return "W" if _is_write_tool(tool_name) else "R"


def _module_title(module_name: str) -> str:
    if module_name in MODULE_TITLES:
        return MODULE_TITLES[module_name]
    return module_name.replace("_", " ").title()


def _truncate(text: str, max_len: int = 120) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def build_inventory_markdown() -> str:
    tool_definitions = get_tool_definitions()
    packages = _load_packages()

    package_membership: dict[str, list[str]] = defaultdict(list)
    for package_name, tools in packages.items():
        for tool_name in tools:
            package_membership[tool_name].append(package_name)

    registered_tool_names = sorted(tool_definitions)
    unpackaged = [name for name in registered_tool_names if not package_membership.get(name)]

    grouped_rows: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for tool_name in registered_tool_names:
        _impl, _params_model, _return_type, description, _serialization = tool_definitions[
            tool_name
        ]
        module_name = _impl.__module__.rsplit(".", 1)[-1]
        grouped_rows[module_name].append(
            (
                tool_name,
                _rw_label(tool_name),
                _truncate(description),
                ", ".join(package_membership.get(tool_name, ["—"])),
            )
        )

    lines = [
        "# ServiceNow MCP - Tool Inventory",
        "",
        "AUTO-GENERATED by `scripts/regenerate_tool_inventory.py`. Do not edit by hand.",
        "",
        f"Registered tools in the live registry: **{len(registered_tool_names)}**",
        f"Packaged tool count in `full`: **{len(packages['full'])}**",
        f"Registered but currently unpackaged tools: **{len(unpackaged)}**",
        "",
        "`list_tool_packages` is injected at runtime into every enabled package except `none`.",
        "It is documented below, but package counts in this file reflect the YAML-defined tool surface.",
        "",
        "## Package Summary",
        "",
        "| Package | Tools | Description |",
        "|---------|------:|-------------|",
    ]

    for package_name in [
        "none",
        "core",
        "standard",
        "service_desk",
        "portal_developer",
        "platform_developer",
        "full",
    ]:
        lines.append(
            f"| `{package_name}` | {len(packages[package_name])} | {PACKAGE_DESCRIPTIONS[package_name]} |"
        )

    lines.extend(
        [
            "",
            "## Runtime-Injected Helpers",
            "",
            "| Tool | R/W | Description | Packages |",
            "|------|-----|-------------|----------|",
            "| `list_tool_packages` | R | Lists the available tool packages and the currently active one. | `core`, `standard`, `service_desk`, `portal_developer`, `platform_developer`, `full` |",
            "",
            "## Registered but Unpackaged Tools",
            "",
            "These tools are registered in code but intentionally excluded from the packaged YAML surfaces. They remain reachable for custom builds, tests, or future packaging decisions.",
            "",
        ]
    )

    if unpackaged:
        lines.append(", ".join(f"`{name}`" for name in unpackaged))
    else:
        lines.append("None.")

    lines.extend(["", "## Tools by Module", ""])

    for module_name in sorted(grouped_rows, key=lambda name: (_module_title(name), name)):
        rows = sorted(grouped_rows[module_name])
        lines.extend(
            [
                f"### {_module_title(module_name)} ({len(rows)})",
                "",
                "| Tool | R/W | Description | Packages |",
                "|------|-----|-------------|----------|",
            ]
        )
        for tool_name, rw, description, package_list in rows:
            lines.append(f"| `{tool_name}` | {rw} | {description} | {package_list} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    content = build_inventory_markdown()
    DOC_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote inventory → {DOC_PATH}")


if __name__ == "__main__":
    main()
