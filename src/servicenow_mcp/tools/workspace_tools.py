"""Workspace situational awareness for ServiceNow MCP.

One call answers, at session start or before risky work:
  - WHO am I / WHERE am I connected (live identity, optional)
  - WHAT is in flight locally (your edits, unresolved conflict sidecars,
    trees still without baseline protection) — pure disk reads, no network
  - WHETHER each downloaded tree needs a refresh: local sync watermark vs the
    server's newest sys_updated_on (one tiny count query per table, no bodies)

The point is PROACTIVE awareness: every historical incident (wrong instance,
stale source pushed, deploy moved local files, someone else's update set) was
a situational-awareness failure that surfaced only at push time.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.baseline import read_baseline_for, remote_sidecar_path_for
from ..utils.config import ServerConfig
from ..utils.download_map import max_sync_updated_on
from ..utils.registry import register_tool
from .sn_api import resolve_live_username, sn_query_page
from .sync_tools import (
    _all_supported_tables,
    _component_field_files,
    _find_table_dirs,
    _normalize_for_compare,
    _read_map_json,
    _resolve_origin_url,
)

logger = logging.getLogger(__name__)

_MAX_LISTED = 20  # cap per detail list — the brief must stay a brief


class WorkspaceBriefParams(BaseModel):
    """Parameters for the workspace situational brief."""

    root: Optional[str] = Field(
        default=None,
        description="Download root to scan (default ./temp). A scope root also works.",
    )
    include_remote: bool = Field(
        default=True,
        description="Live checks: identity + per-tree refresh need. False = offline only.",
    )
    max_trees: int = Field(
        default=20,
        description="Max downloaded trees to scan (safety cap).",
    )


def _looks_like_tree(path: Path) -> bool:
    """True when *path* is a scope root: has a manifest or any table dir."""
    if (path / "_manifest.json").exists():
        return True
    return any((path / table / "_map.json").exists() for table in _all_supported_tables())


def _discover_trees(root: Path, max_trees: int) -> List[Path]:
    """Scope roots under *root* (root itself, root/<scope>, root/<inst>/<scope>)."""
    if _looks_like_tree(root):
        return [root]
    trees: List[Path] = []
    try:
        level1 = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return []
    for child in level1:
        if _looks_like_tree(child):
            trees.append(child)
            continue
        try:
            level2 = sorted(p for p in child.iterdir() if p.is_dir())
        except OSError:
            continue
        trees.extend(p for p in level2 if _looks_like_tree(p))
    return trees[:max_trees]


def _scan_tree_local(tree: Path) -> Dict[str, Any]:
    """Offline state of one tree: your edits, conflict sidecars, baseline coverage."""
    dirty: List[str] = []
    sidecars: List[str] = []
    components = 0
    with_baseline = 0
    for table_name in sorted(_all_supported_tables()):
        for table_dir in _find_table_dirs(tree, table_name):
            for name in sorted(_read_map_json(table_dir)):
                fields = _component_field_files(table_dir, name, table_name)
                if not fields:
                    continue
                components += 1
                component_has_baseline = False
                for _field, fpath in sorted(fields.items()):
                    sidecar = remote_sidecar_path_for(fpath)
                    if sidecar.exists():
                        sidecars.append(f"{table_name}/{name} ({sidecar.name})")
                    baseline = read_baseline_for(fpath)
                    if baseline is None:
                        continue
                    component_has_baseline = True
                    try:
                        local = fpath.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    if _normalize_for_compare(local) != _normalize_for_compare(baseline):
                        dirty.append(f"{table_name}/{name}:{fpath.name}")
                if component_has_baseline:
                    with_baseline += 1
    return {
        "components": components,
        "baseline_protected": with_baseline,
        "your_edits": dirty,
        "unresolved_conflicts": sidecars,
    }


def _check_tree_refresh(
    config: ServerConfig, auth_manager: AuthManager, tree: Path, scope: str
) -> Dict[str, Any]:
    """Local watermark vs the server's newest sys_updated_on, per table.

    One count query per table (fields=sys_updated_on, limit=1) — no bodies ever
    travel, so the check costs near-zero tokens and trivial network.
    """
    changed_total = 0
    newest_remote = ""
    unknown_tables: List[str] = []
    for table_name in sorted(_all_supported_tables()):
        for table_dir in _find_table_dirs(tree, table_name):
            watermark = max_sync_updated_on(table_dir / "_sync_meta.json")
            if not watermark:
                unknown_tables.append(table_name)
                continue
            try:
                rows, total = sn_query_page(
                    config,
                    auth_manager,
                    table=table_name,
                    query=(
                        f"sys_scope.scope={scope}^sys_updated_on>{watermark}"
                        f"^ORDERBYDESCsys_updated_on"
                    ),
                    fields="sys_updated_on",
                    limit=1,
                    offset=0,
                    display_value=False,
                )
            except Exception as exc:  # noqa: BLE001 — one denied table must not kill the brief
                logger.warning("workspace_brief: refresh check failed for %s: %s", table_name, exc)
                unknown_tables.append(table_name)
                continue
            count = total if total is not None else len(rows)
            if count:
                changed_total += int(count)
                ts = str(rows[0].get("sys_updated_on") or "") if rows else ""
                newest_remote = max(newest_remote, ts)
    refresh: Dict[str, Any] = {"needed": changed_total > 0, "changed_records": changed_total}
    if newest_remote:
        refresh["newest_remote"] = newest_remote
    if changed_total:
        refresh["how"] = f"download_app_sources(scope='{scope}', incremental=True)"
    if unknown_tables:
        refresh["unchecked_tables"] = unknown_tables[:_MAX_LISTED]
    return refresh


def _tree_scope(tree: Path) -> str:
    """Scope namespace for a tree — manifest first, folder name fallback."""
    manifest = tree / "_manifest.json"
    if manifest.exists():
        try:
            scope = str(json.loads(manifest.read_text(encoding="utf-8")).get("scope") or "")
            if scope:
                return scope
        except (OSError, ValueError):
            pass
    return tree.name


@register_tool(
    "workspace_brief",
    params=WorkspaceBriefParams,
    description="Session brief: who/where, your local edits & conflicts, and which trees need a refresh.",
    serialization="raw_dict",
    return_type=dict,
)
def workspace_brief(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: WorkspaceBriefParams,
) -> Dict[str, Any]:
    root = Path(params.root).expanduser().resolve() if params.root else Path.cwd() / "temp"
    active_url = config.instance_url.rstrip("/")

    identity: Dict[str, Any] = {
        "instance": config.instance_url,
        "auth_type": str(getattr(config.auth.type, "value", config.auth.type)),
    }
    if params.include_remote:
        identity["user"] = resolve_live_username(config, auth_manager) or "(unresolved)"

    trees_out: List[Dict[str, Any]] = []
    next_steps: List[str] = []
    if not root.exists():
        return {
            "identity": identity,
            "root": str(root),
            "trees": [],
            "note": "No download root found — nothing downloaded yet.",
        }

    for tree in _discover_trees(root, max(1, min(params.max_trees, 100))):
        local = _scan_tree_local(tree)
        entry: Dict[str, Any] = {"root": str(tree), "scope": _tree_scope(tree)}
        entry["components"] = local["components"]
        seeded = local["baseline_protected"]
        entry["baseline_protected"] = f"{seeded}/{local['components']}"
        if local["your_edits"]:
            entry["your_edits"] = local["your_edits"][:_MAX_LISTED]
        if local["unresolved_conflicts"]:
            entry["unresolved_conflicts"] = local["unresolved_conflicts"][:_MAX_LISTED]

        origin = _resolve_origin_url(tree).rstrip("/")
        if origin and origin != active_url:
            entry["other_instance"] = origin
            entry["note"] = (
                "Downloaded from a different instance — route calls for this tree with "
                "instance=<alias> (see list_instances)."
            )
        elif params.include_remote:
            entry["refresh"] = _check_tree_refresh(config, auth_manager, tree, entry["scope"])

        trees_out.append(entry)

        # Actionable next steps, most urgent first.
        if local["unresolved_conflicts"]:
            next_steps.append(
                f"{entry['scope']}: merge {len(local['unresolved_conflicts'])} '.remote' conflict "
                f"sidecar(s) into the main file(s), then push (sidecars auto-clear)."
            )
        if entry.get("refresh", {}).get("needed"):
            next_steps.append(
                f"{entry['scope']}: {entry['refresh']['changed_records']} record(s) changed on the "
                f"server — {entry['refresh']['how']}"
            )
        if local["components"] and seeded == 0:
            next_steps.append(
                f"{entry['scope']}: no baseline snapshots yet — one re-download seeds 3-way "
                f"protection (local edits become distinguishable from server changes)."
            )
        if local["your_edits"]:
            next_steps.append(
                f"{entry['scope']}: {len(local['your_edits'])} file(s) carry your unpushed edits — "
                f"verify with diff_local_component(path=..., verdict=True) before continuing."
            )

    result: Dict[str, Any] = {
        "identity": identity,
        "root": str(root),
        "trees": trees_out,
    }
    if next_steps:
        result["next_steps"] = next_steps
    if not trees_out:
        result["note"] = "No downloaded trees under this root."
    return result
