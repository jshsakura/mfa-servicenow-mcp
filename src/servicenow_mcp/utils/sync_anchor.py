"""Live-anchored source sync: normalized content hashing + always-fresh mirror.

Replaces the frozen ``_baseline/`` 3-way snapshot. The authority for "did the
server move" is the live ``sys_mod_count`` (see
``sync_tools._assess_server_drift``); this module owns the LOCAL side:

- a per-field content SHA recorded in ``_sync_meta`` at each sync, so "do I have
  unpushed edits?" is answered offline (``local sha != stored sha``). This is the
  hash comparison the whole model rests on — and therefore hashed on ONE
  normalized basis so pure line-ending / trailing-newline noise can never read as
  an edit;
- the two-copy reconcile on (re)download: a protected working file (never
  clobbered when it carries local edits) plus an always-fresh ``.remote`` mirror
  of the current server body written next to it when the two genuinely diverge.

The frozen baseline was a local *guess* about the server, trusted as authority
even when stale. A SHA anchor is a fact about the last-known-good sync that
advances on every download/push, and the mirror always reflects the *current*
server — a stale copy has no reason to exist.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Tuple

from servicenow_mcp.utils.atomic_io import atomic_write_text
from servicenow_mcp.utils.source_layout import normalize_source_eol

MIRROR_MARKER = ".remote"


def normalize_for_hash(text: str) -> str:
    """The ONE comparison basis: EOL- and trailing-newline-insensitive.

    ``splitlines()`` collapses ``\\r\\n``, ``\\r`` and ``\\n`` and drops a trailing
    newline — identical to ``sync_tools._normalize_for_compare`` — so a content
    hash and a rendered diff can never disagree (the phantom "modified but empty
    diff" bug). Any content (local file, live remote body, or the value behind a
    stored anchor) MUST pass through here before it is hashed or compared.
    """
    return "\n".join((text or "").splitlines())


def field_sha(text: str) -> str:
    """SHA-256 of the normalized content — the offline edit/equality anchor.

    Hashing the normalized view (never raw bytes) is what keeps the comparison
    valid: the same logical script stored CRLF on one instance and LF on another
    yields the SAME sha, so pure line-ending noise is never a false "edited".
    """
    return hashlib.sha256(normalize_for_hash(text).encode("utf-8")).hexdigest()


def mirror_path_for(file_path: Path) -> Path:
    """Server-mirror sidecar path: ``script.js`` -> ``script.remote.js``.

    The marker sits before the extension so editors keep syntax highlighting.
    """
    if file_path.suffix:
        return file_path.with_name(f"{file_path.stem}{MIRROR_MARKER}{file_path.suffix}")
    return file_path.with_name(f"{file_path.name}{MIRROR_MARKER}")


def is_mirror_artifact(path: Path) -> bool:
    """True for ``.remote`` server-mirror sidecars.

    Tree scanners must skip these or they double-count bodies; push/diff must
    reject them — a mirror is the SERVER's copy, never pushed as the component.
    """
    return path.stem.endswith(MIRROR_MARKER)


def cleanup_mirror(file_path: Path) -> None:
    """Remove a resolved server-mirror sidecar once local and server reconcile."""
    mirror = mirror_path_for(file_path)
    try:
        if mirror.exists():
            mirror.unlink()
    except OSError:
        pass


# reconcile_field outcomes
WRITTEN = "written"  # no local file existed -> wrote the server body
UNCHANGED = "unchanged"  # local already equals the live server body
REFRESHED = "refreshed"  # local was clean (== last sync) -> updated to live
KEPT_LOCAL = "kept_local"  # local carries edits, server unmoved -> kept as-is
CONFLICT_MIRRORED = "conflict_mirrored"  # local edits AND server moved -> mirror written
LEGACY_KEPT = "legacy_kept"  # no anchor, caller policy = preserve local
BLANK_REMOTE_KEPT = "blank_remote_kept"  # remote body blank/unknown -> untouched

# Outcomes after which the local file provably equals the current remote body, so
# the caller may record the returned sha + bump the mod_count watermark.
IN_SYNC_OUTCOMES = frozenset({WRITTEN, UNCHANGED, REFRESHED})


def _write_local(file_path: Path, content: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(file_path, normalize_source_eol(content))


def reconcile_field(
    file_path: Path,
    remote_content: str,
    stored_sha: str,
    *,
    legacy_overwrite: bool = False,
    blank_remote_is_unknown: bool = False,
) -> Tuple[str, str]:
    """Two-copy reconcile of one field on (re)download. Never clobbers local edits.

    Returns ``(outcome, sha)`` where ``sha`` is the value the caller should record
    in ``_sync_meta`` as the new anchor. It is the live-remote sha only for
    IN_SYNC outcomes (local provably equals the server); otherwise it is the
    unchanged ``stored_sha``, so a caller may always write it back safely.

    ``stored_sha``: the field's sha recorded at the last sync ("" = legacy tree
    with no anchor). ``legacy_overwrite``: for legacy trees only, whether an
    incremental refresh may overwrite the local copy we cannot prove is unedited.
    ``blank_remote_is_unknown``: some bulk queries return empty bodies spuriously;
    when set, a blank remote leaves the local file (and anchor) untouched.
    """
    remote = remote_content if isinstance(remote_content, str) else ""
    remote_sha = field_sha(remote)

    if not file_path.exists():
        _write_local(file_path, remote)
        cleanup_mirror(file_path)
        return WRITTEN, remote_sha

    if blank_remote_is_unknown and not remote.strip():
        return BLANK_REMOTE_KEPT, stored_sha

    try:
        local = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return LEGACY_KEPT, stored_sha

    local_sha = field_sha(local)

    # Already equal to the live server (EOL-insensitive) — re-seed the anchor so a
    # legacy tree becomes anchored, and clear any resolved mirror.
    if local_sha == remote_sha:
        cleanup_mirror(file_path)
        return UNCHANGED, remote_sha

    # No anchor: we cannot PROVE whether the local copy carries edits.
    if not stored_sha:
        if legacy_overwrite:
            _write_local(file_path, remote)
            cleanup_mirror(file_path)
            return REFRESHED, remote_sha
        return LEGACY_KEPT, stored_sha

    have_local_edits = local_sha != stored_sha
    if not have_local_edits:
        # Working copy is provably clean (== last sync) but differs from live ->
        # the server moved. Refresh the working copy to the current server body.
        _write_local(file_path, remote)
        cleanup_mirror(file_path)
        return REFRESHED, remote_sha

    server_moved = remote_sha != stored_sha
    if not server_moved:
        # My edits, server unchanged since my sync — keep my copy, no mirror needed.
        return KEPT_LOCAL, stored_sha

    # True conflict: my edits AND the server moved. Keep the working file and write
    # an always-fresh mirror of the CURRENT server body next to it for manual merge.
    atomic_write_text(mirror_path_for(file_path), normalize_source_eol(remote))
    return CONFLICT_MIRRORED, stored_sha
