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
from typing import Any, Dict, List, Optional

from ..utils.sync_anchor import field_sha, mirror_path_for
from .sync_tools import (
    _all_supported_tables,
    _component_field_files,
    _find_table_dirs,
    _read_map_json,
    _read_sync_meta,
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


def _scan_tree_local(tree: Path, component_budget: Optional[int] = None) -> Dict[str, Any]:
    """Offline state of one tree: your edits, conflict mirrors, anchor coverage.

    Uses the per-field content-sha anchor in _sync_meta (``local sha != stored
    sha`` = your unpushed edit) — no network, no frozen snapshot. ``component_budget``
    caps how many components are content-checked (speed guard for advisory surfaces
    like the health snapshot — the push gates re-verify live at upload time, so
    stopping early never hides a conflict where it matters).
    """
    dirty: List[str] = []
    sidecars: List[str] = []
    components = 0
    with_anchor = 0
    for table_name in sorted(_all_supported_tables()):
        for table_dir in _find_table_dirs(tree, table_name):
            sync_meta = _read_sync_meta(table_dir)
            for name in sorted(_read_map_json(table_dir)):
                if component_budget is not None and components >= component_budget:
                    return {
                        "components": components,
                        "anchor_protected": with_anchor,
                        "your_edits": dirty,
                        "unresolved_conflicts": sidecars,
                    }
                fields = _component_field_files(table_dir, name, table_name)
                if not fields:
                    continue
                components += 1
                stored_shas = sync_meta.get(name, {}).get("field_shas", {})
                if stored_shas:
                    with_anchor += 1
                for field_name, fpath in sorted(fields.items()):
                    mirror = mirror_path_for(fpath)
                    if mirror.exists():
                        sidecars.append(f"{table_name}/{name} ({mirror.name})")
                    stored = stored_shas.get(field_name)
                    if not stored:
                        continue
                    try:
                        local = fpath.read_text(encoding="utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    if field_sha(local) != stored:
                        dirty.append(f"{table_name}/{name}:{fpath.name}")
    return {
        "components": components,
        "anchor_protected": with_anchor,
        "your_edits": dirty,
        "unresolved_conflicts": sidecars,
    }
