"""Pristine-baseline snapshots for downloaded source files (3-way safety net).

Every local source write records the exact content that came from (or went to)
the server under ``<record_dir>/_baseline/<filename>``. That copy is the common
ancestor for content-aware sync decisions:

    local  != baseline  ->  the local copy carries YOUR edits
    remote != baseline  ->  the server moved since your last download/push

``sync_field_file`` applies the decision matrix to one field file. Trees
downloaded before baselines existed ("legacy", no ``_baseline/``) keep each
caller's historical behavior via ``legacy_overwrite``. Baselines are written
ONLY at moments the local file is known to equal the server content (fresh
download, auto-refresh, backfill, successful push) — never guessed afterwards,
so ``local != baseline`` always means a real divergence.

A true conflict (local edits AND server moved) never overwrites: the local file
is kept and the server's version lands next to it as ``<stem>.remote<ext>`` so
the user can merge by hand. Sidecars and baselines are internal artifacts —
tree scanners and push/diff resolution must skip them (``is_baseline_artifact``).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from servicenow_mcp.utils.atomic_io import atomic_write_text
from servicenow_mcp.utils.source_layout import normalize_source_eol

logger = logging.getLogger(__name__)

BASELINE_DIRNAME = "_baseline"
REMOTE_SIDECAR_MARKER = ".remote"

# sync_field_file outcomes
ACTION_WRITTEN = "written"  # no local file existed; wrote file + baseline
ACTION_UNCHANGED = "unchanged"  # local clean, server unmoved
ACTION_REFRESHED = "refreshed"  # local clean, server moved -> local updated
ACTION_KEPT_DIRTY = "kept_dirty"  # local edits, server unmoved -> kept
ACTION_RESEEDED = "reseeded"  # local edits already equal the server
ACTION_CONFLICT = "conflict"  # local edits AND server moved -> .remote sidecar
ACTION_LEGACY_KEPT = "legacy_kept"  # no baseline; caller policy = preserve
ACTION_LEGACY_OVERWRITTEN = "legacy_overwritten"  # no baseline; caller policy = overwrite
ACTION_BLANK_REMOTE_KEPT = "blank_remote_kept"  # remote body blank/unknown -> untouched

# Outcomes after which the local file provably equals the current remote body,
# so a sync watermark (sys_updated_on) may be bumped without blinding the
# push-time conflict gate.
IN_SYNC_ACTIONS = frozenset(
    {
        ACTION_WRITTEN,
        ACTION_UNCHANGED,
        ACTION_REFRESHED,
        ACTION_RESEEDED,
        ACTION_LEGACY_OVERWRITTEN,
    }
)


def baseline_path_for(file_path: Path) -> Path:
    """Baseline snapshot location for a field file."""
    return file_path.parent / BASELINE_DIRNAME / file_path.name


def remote_sidecar_path_for(file_path: Path) -> Path:
    """Conflict sidecar location: ``script.js`` -> ``script.remote.js``.

    The marker goes before the extension so editors keep syntax highlighting.
    """
    if file_path.suffix:
        return file_path.with_name(f"{file_path.stem}{REMOTE_SIDECAR_MARKER}{file_path.suffix}")
    return file_path.with_name(f"{file_path.name}{REMOTE_SIDECAR_MARKER}")


def is_baseline_artifact(path: Path) -> bool:
    """True for files this module owns: baseline snapshots and .remote sidecars.

    Tree scanners (dep scan, table extraction, audits) must skip these or they
    double-count bodies; push/diff resolution must reject them or a sidecar
    could be pushed as if it were the component itself.
    """
    if BASELINE_DIRNAME in path.parts:
        return True
    return path.stem.endswith(REMOTE_SIDECAR_MARKER)


def read_baseline_for(file_path: Path) -> Optional[str]:
    """Baseline content for a field file, or None when no baseline exists."""
    bpath = baseline_path_for(file_path)
    if not bpath.exists():
        return None
    try:
        return bpath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("baseline: failed to read %s: %s — treating as absent", bpath, exc)
        return None


def _ensure_baseline_dir_ignored(baseline_dir: Path) -> None:
    """Drop a self-ignoring ``.gitignore`` into a ``_baseline/`` directory.

    A single ``*`` ignores every snapshot AND the ``.gitignore`` itself, so a
    download tree that lives inside a git repo never floods ``git status`` with
    baseline artifacts — and no new tracked file appears either. Placement is
    root-agnostic: git honours the rule wherever ``.git`` sits above it.
    """
    gitignore = baseline_dir / ".gitignore"
    if gitignore.exists():
        return
    try:
        atomic_write_text(gitignore, "# ServiceNow MCP baseline snapshots — never commit\n*\n")
    except OSError as exc:
        logger.warning(
            "baseline: failed to write %s: %s — status may show snapshots", gitignore, exc
        )


def write_baseline_for(file_path: Path, content: str) -> None:
    """Record *content* as the new common ancestor for a field file."""
    bpath = baseline_path_for(file_path)
    bpath.parent.mkdir(parents=True, exist_ok=True)
    _ensure_baseline_dir_ignored(bpath.parent)
    atomic_write_text(bpath, normalize_source_eol(content))


def cleanup_remote_sidecar(file_path: Path) -> None:
    """Remove a stale conflict sidecar once local and server are reconciled."""
    spath = remote_sidecar_path_for(file_path)
    try:
        if spath.exists():
            spath.unlink()
    except OSError as exc:
        logger.warning("baseline: failed to remove stale sidecar %s: %s", spath, exc)


def _norm(text: str) -> str:
    """EOL/trailing-newline–insensitive view for change detection.

    Matches the ``splitlines()`` basis diff rendering uses, so classification
    and rendered diffs can never disagree (no phantom modifications).
    """
    return "\n".join(normalize_source_eol(text or "").splitlines())


def _write_local_and_baseline(file_path: Path, content: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    canonical = normalize_source_eol(content)
    atomic_write_text(file_path, canonical)
    write_baseline_for(file_path, canonical)


def sync_field_file(
    file_path: Path,
    remote_content: str,
    *,
    legacy_overwrite: bool,
    blank_remote_is_unknown: bool = False,
) -> str:
    """Reconcile one local field file with the server body already in hand.

    Returns one of the ``ACTION_*`` constants. Never destroys local edits: the
    only overwrite paths are a clean local copy (== baseline) or the caller's
    explicit legacy policy for pre-baseline trees.

    ``blank_remote_is_unknown``: bulk queries on some instances return empty
    source bodies spuriously; when set, a blank remote body is treated as
    "unknown" and the local file (and baseline, and watermark) stay untouched.
    """
    remote = remote_content if isinstance(remote_content, str) else ""

    if not file_path.exists():
        _write_local_and_baseline(file_path, remote)
        cleanup_remote_sidecar(file_path)
        return ACTION_WRITTEN

    if blank_remote_is_unknown and not remote.strip():
        return ACTION_BLANK_REMOTE_KEPT

    try:
        local = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("baseline: failed to read local %s: %s — keeping it", file_path, exc)
        return ACTION_LEGACY_KEPT

    baseline = read_baseline_for(file_path)
    if baseline is None:
        if legacy_overwrite:
            _write_local_and_baseline(file_path, remote)
            return ACTION_LEGACY_OVERWRITTEN
        return ACTION_LEGACY_KEPT

    local_n, baseline_n, remote_n = _norm(local), _norm(baseline), _norm(remote)

    if local_n == baseline_n:
        if remote_n == baseline_n:
            cleanup_remote_sidecar(file_path)
            return ACTION_UNCHANGED
        _write_local_and_baseline(file_path, remote)
        cleanup_remote_sidecar(file_path)
        return ACTION_REFRESHED

    # Local carries edits.
    if remote_n == local_n:
        # The user's edit is already on the server (manual apply / other path):
        # re-seed the ancestor so the copy reads clean from here on.
        write_baseline_for(file_path, local)
        cleanup_remote_sidecar(file_path)
        return ACTION_RESEEDED
    if remote_n == baseline_n:
        return ACTION_KEPT_DIRTY

    # True conflict: keep the local edits, save the server's version alongside.
    sidecar = remote_sidecar_path_for(file_path)
    atomic_write_text(sidecar, normalize_source_eol(remote))
    return ACTION_CONFLICT
