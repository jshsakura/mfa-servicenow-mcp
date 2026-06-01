"""Resumable-download progress for download_app_sources.

The orchestrator runs many sequential stages (portal, source groups, schema,
deps) inside a single MCP call. Large scopes blow past the client's 120s
call timeout, dropping the whole run. This module persists per-stage progress
to disk so a re-invocation skips already-finished stages and converges in
several short calls instead of one long one.

Safety invariants (so nothing is silently missed):
- A stage is recorded ONLY after its work fully returns. A mid-stage timeout
  leaves no record, so the next call re-runs that stage from scratch.
- The saved payload preserves each stage's ``type_results`` (incl. ``capped``
  flags) so the final completeness signal aggregates losslessly across calls.
- Progress is bound to a params fingerprint; changing params invalidates the
  stale progress and starts fresh.
- On full success the progress file is deleted, so a completed run leaves no
  trace and the next call starts clean.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PROGRESS_FILENAME = "_download_progress.json"

# Params that change WHAT gets downloaded. A change in any of these means a
# prior partial run is no longer comparable and must not be resumed.
_FINGERPRINT_FIELDS = (
    "scope",
    "include_widget_sources",
    "include_schema",
    "max_records_per_type",
    "page_size",
    "only_active",
    "acl_script_only",
    "auto_resolve_deps",
    "incremental",
    "reconcile_deletions",
)


def progress_path(scope_root: Path) -> Path:
    return Path(scope_root) / PROGRESS_FILENAME


def params_fingerprint(params: Any) -> str:
    """Stable hash of the download-shaping params.

    Resume only kicks in when this matches the stored fingerprint, so a user
    who re-runs with different options never inherits a mismatched partial.
    """
    payload = {f: getattr(params, f, None) for f in _FINGERPRINT_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def load_progress(scope_root: Path, fingerprint: str) -> Optional[Dict[str, Any]]:
    """Return the saved ``stages`` map when a matching partial run exists.

    Returns None when there is no progress file, it is unreadable, or its
    fingerprint differs (params changed) — in every such case the caller
    starts a fresh full download.
    """
    path = progress_path(scope_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("download progress unreadable (%s); starting fresh: %s", path, exc)
        return None
    if not isinstance(data, dict) or data.get("fingerprint") != fingerprint:
        logger.info("download progress fingerprint mismatch; starting fresh: %s", path)
        return None
    stages = data.get("stages")
    return stages if isinstance(stages, dict) else {}


def save_stage(
    scope_root: Path,
    fingerprint: str,
    stage_key: str,
    payload: Dict[str, Any],
) -> None:
    """Record one finished stage. Read-modify-write; best-effort.

    A failure to persist progress must never fail the download itself — at
    worst the stage re-runs on the next call, which is wasteful but safe.
    """
    path = progress_path(scope_root)
    stages: Dict[str, Any] = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing.get("fingerprint") == fingerprint:
                prior = existing.get("stages")
                if isinstance(prior, dict):
                    stages = prior
        except (OSError, ValueError):
            stages = {}
    stages[stage_key] = payload
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fingerprint": fingerprint, "stages": stages}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("could not persist download progress (%s): %s", path, exc)


def clear_progress(scope_root: Path) -> None:
    """Remove the progress file after a fully successful run."""
    path = progress_path(scope_root)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("could not clear download progress (%s): %s", path, exc)
