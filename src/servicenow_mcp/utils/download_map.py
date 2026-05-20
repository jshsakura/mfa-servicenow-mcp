"""Helpers for download `_map.json` / `_sync_meta.json` files.

Targeted downloads (e.g. `download_portal_sources` with `widget_ids=[...]`)
must NOT overwrite the full map; otherwise entries from prior full-scope
downloads disappear and downstream tools (`update_remote_from_local`,
`diff_local_component`, etc.) report `Component '...' not found in _map.json`.

Policy: every download merges into the existing map file. Full-scope downloads
naturally produce the same end state as before (every entry rewritten),
targeted downloads add/update only the touched entries and preserve the rest.

Each merge logs a single INFO line so future investigations can see at a glance
how the map evolved across runs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Set

logger = logging.getLogger(__name__)


def max_sync_updated_on(sync_meta_path: Path) -> str:
    """Return the newest sys_updated_on recorded in a _sync_meta.json file.

    Used as the incremental-download watermark. Server-side timestamps avoid
    client clock skew. Returns "" when the file is missing/empty so callers
    fall back to a full download.
    """
    existing = _read_existing_map(sync_meta_path)
    stamps = [
        str(entry.get("sys_updated_on") or "")
        for entry in existing.values()
        if isinstance(entry, dict) and entry.get("sys_updated_on")
    ]
    return max(stamps) if stamps else ""


def map_sys_ids(map_path: Path) -> Set[str]:
    """sys_ids recorded locally in a _map.json file (its values)."""
    existing = _read_existing_map(map_path)
    return {str(v) for v in existing.values() if v}


def _read_existing_map(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("download_map: failed to read %s: %s — treating as empty", path, exc)
        return {}
    if not text.strip():
        return {}
    try:
        existing = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("download_map: %s is not valid JSON (%s) — overwriting", path, exc)
        return {}
    if not isinstance(existing, dict):
        logger.warning(
            "download_map: %s top-level is %s, expected object — overwriting",
            path,
            type(existing).__name__,
        )
        return {}
    return existing


def merge_map_file(
    path: Path,
    new_entries: Dict[str, Any],
    *,
    writer: Callable[[Path, Any], None],
    label: str,
) -> Dict[str, Any]:
    """Merge `new_entries` into the JSON object at `path` and persist via `writer`.

    Returns the merged dict (so callers can inspect/return it). Emits one INFO
    log line summarizing existing/new/added/updated/preserved counts.

    `writer` is the caller's existing JSON writer (e.g. `_write_json_file` for
    portal_tools or `_dl_write_json` for source_tools) so the file format the
    project already uses (compact vs. indented) is preserved.
    """
    existing = _read_existing_map(path)
    new_keys = set(new_entries.keys())
    existing_keys = set(existing.keys())

    added = len(new_keys - existing_keys)
    updated = sum(1 for k in (new_keys & existing_keys) if existing.get(k) != new_entries.get(k))
    preserved = len(existing_keys - new_keys)

    merged: Dict[str, Any] = dict(existing)
    merged.update(new_entries)

    writer(path, merged)

    logger.info(
        "Merged %s map: path=%s existing=%d new=%d added=%d updated=%d preserved=%d total=%d",
        label,
        path,
        len(existing),
        len(new_entries),
        added,
        updated,
        preserved,
        len(merged),
    )
    return merged
