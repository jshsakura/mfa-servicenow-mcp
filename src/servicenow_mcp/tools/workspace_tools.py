"""Internal workspace-state helpers (NOT a registered tool).

Deliberately tool-less: automation the LLM must remember to invoke is not
automation. Workspace state surfaces at the flow points that already run —
sn_health carries an offline summary of unfinished local work (edits /
unresolved '.remote' conflicts) on the session's natural first call, and the
push/diff gates re-check the live remote at upload time. Per-tree drill-down
is diff_local_component(path=<tree>, verdict=True).

Everything here is pure disk reads: no network, no ServiceNow ACL dependency.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

from ..utils.baseline import read_baseline_for, remote_sidecar_path_for
from .sync_tools import (
    _all_supported_tables,
    _component_field_files,
    _find_table_dirs,
    _normalize_for_compare,
    _read_map_json,
)

logger = logging.getLogger(__name__)


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
