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
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Set

from servicenow_mcp.utils.sync_anchor import anchor_matches_disk

logger = logging.getLogger(__name__)


def stale_sys_ids(
    sync_meta_path: Path,
    remote_rows: Iterable[Mapping[str, Any]],
    *,
    record_root: Optional[Path] = None,
    name_to_folder: Optional[Callable[[str], str]] = None,
) -> Set[str]:
    """sys_ids the SERVER says are not reflected on disk — the incremental fetch set.

    Remote-first, per record. ``remote_rows`` is the live ledger (sys_id +
    sys_mod_count + sys_updated_on, no bodies); every id in it is judged against
    THAT record's own anchor in _sync_meta.

    This replaces a single ``sys_updated_on >= max(local anchors)`` query filter,
    which could not see a record it had already skipped: a record whose anchor
    never advanced (conflict, kept local edits, legacy/unanchored tree, deleted
    folder) keeps an OLD stamp, while ANY freshly synced sibling raises the MAX
    above it. The stale record then falls outside the query forever, and the
    download truthfully reports "0 changed" — the illusion that there is nothing
    to fetch. A max-watermark only ever rises, so that state never self-heals.

    Per record, fetch when:
      - no anchor for the id at all (never synced, or an unanchored legacy tree);
      - ``record_root`` is given and the anchor no longer matches the files on
        disk — deleted, edited, or never sha-recorded. The anchor is a claim about
        local state; until it is checked against real bytes it may not veto a
        fetch, or a record whose local copy is not what the anchor says gets
        skipped as "up to date" and you never receive the body you needed;
      - the live ``sys_mod_count`` differs from the anchored one — the server's own
        monotonic counter is the authority (same basis as the diff/push gate);
      - no anchored mod_count (legacy anchor) and the live ``sys_updated_on`` is
        newer, or either stamp is missing so equality cannot be proven.

    Anchors are keyed by the record's local folder name, and carry their sys_id.
    ``name_to_folder`` maps that key to the on-disk folder when a downloader
    sanitizes it (portal widgets); omit when the key IS the folder name.
    """
    anchors = _read_existing_map(sync_meta_path)
    by_sys_id: Dict[str, Mapping[str, Any]] = {}
    for name, entry in anchors.items():
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("sys_id") or "")
        if not sid:
            continue
        # An anchor may only suppress a fetch while it still describes the bytes
        # on disk. It is a local claim, not proof: if the files are gone, changed
        # under it, or were never sha-recorded, "the server matches my anchor"
        # says nothing about the copy you would be left reading — so drop the
        # claim and let the record be fetched and reconciled against real content.
        if record_root is not None:
            folder = name_to_folder(str(name)) if name_to_folder else str(name)
            if not anchor_matches_disk(record_root / folder, entry):
                continue
        by_sys_id[sid] = entry

    stale: Set[str] = set()
    for row in remote_rows:
        sid = str(row.get("sys_id") or "")
        if not sid:
            continue
        anchor = by_sys_id.get(sid)
        if anchor is None:
            stale.add(sid)
            continue
        local_count = str(anchor.get("sys_mod_count") or "")
        remote_count = str(row.get("sys_mod_count") or "")
        if local_count and remote_count:
            if local_count != remote_count:
                stale.add(sid)
            continue
        local_on = str(anchor.get("sys_updated_on") or "")
        remote_on = str(row.get("sys_updated_on") or "")
        if not local_on or not remote_on or remote_on > local_on:
            stale.add(sid)
    return stale


def max_sync_updated_on(sync_meta_path: Path) -> str:
    """Return the newest sys_updated_on recorded in a _sync_meta.json file.

    NOT a fetch gate — see ``stale_sys_ids`` for that; a MAX watermark silently
    excludes any record whose own anchor lagged behind its siblings. Kept for
    reporting the tree's newest known-good sync. Returns "" when the file is
    missing/empty.
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


def read_download_map(path: Path) -> Dict[str, Any]:
    """Parsed contents of a _map.json / _sync_meta.json file (empty if missing).

    Public reader so download tools can inspect the prior on-disk state — e.g.
    to preserve an existing sync watermark instead of overwriting it."""
    return _read_existing_map(path)


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
