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
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from servicenow_mcp.utils.atomic_io import atomic_write_text
from servicenow_mcp.utils.source_layout import field_filename, normalize_source_eol

MIRROR_MARKER = ".remote"
LEGACY_BASELINE_DIRNAME = "_baseline"
STASH_DIRNAME = "_stash"

# What a (re)download does with a file that carries YOUR edits. The tool never
# picks for you: KEEP is the default, and the other two are the user's answer to
# the question the tool asks whenever it held an edit back.
LOCAL_EDITS_KEEP = "keep"  # leave the edit in place (mirror on a real conflict)
LOCAL_EDITS_CLEAN = "clean"  # take the server body; the edit is dropped
LOCAL_EDITS_STASH = "stash"  # take the server body; the edit is set aside first
LOCAL_EDITS_MODES = (LOCAL_EDITS_KEEP, LOCAL_EDITS_CLEAN, LOCAL_EDITS_STASH)

# One component's _sync_meta entry: the scalar stamps (sys_id, sys_updated_on,
# sys_updated_by, sys_mod_count, downloaded_at) AND the nested per-field sha map
# under "field_shas". The value type is a genuine union, so it is Any by
# construction — typing it as str made every field_shas read a type error at the
# call sites that produce and consume the anchor.
SyncMetaEntry = Dict[str, Any]
# name -> entry, as stored in a table dir's _sync_meta.json.
SyncMeta = Dict[str, SyncMetaEntry]


def sweep_legacy_baseline(component_dir: Path) -> None:
    """Remove a leftover ``_baseline/`` snapshot dir from a pre-anchor download.

    Downloads now anchor on a content sha in _sync_meta, so the old frozen
    snapshot dir is dead weight — sweep it on (re)download so trees self-tidy as
    they migrate, instead of leaving orphaned artifacts behind forever.
    """
    legacy = component_dir / LEGACY_BASELINE_DIRNAME
    if legacy.is_dir():
        shutil.rmtree(legacy, ignore_errors=True)


def anchor_matches_disk(record_dir: Path, entry: Dict[str, Any]) -> bool:
    """Do the files on disk still equal what this _sync_meta entry CLAIMS?

    An anchor is a claim about local state, not proof of it. It may only be
    allowed to suppress a download when it still describes the bytes actually
    sitting in ``record_dir`` — otherwise "the server matches my anchor" says
    nothing about the copy you would be left reading. Unverifiable in any way
    (folder gone, a recorded field's file missing, no recorded shas at all)
    returns False: fetch it and reconcile against real content, because
    over-fetching is recoverable and skipping a needed record is not.

    Cheap by construction — local reads only, no network.
    """
    if not record_dir.is_dir():
        return False
    shas = entry.get("field_shas") or {}
    if not shas:
        return False
    for field_name, stored in shas.items():
        if not stored:
            continue
        fpath = record_dir / field_filename(field_name)
        if not fpath.is_file():
            return False
        try:
            if field_sha(fpath.read_text(encoding="utf-8")) != stored:
                return False
        except (OSError, UnicodeDecodeError):
            return False
    return True


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


# How many superseded bodies per field an anchor remembers. A promotion target
# is usually one or two revisions behind its origin; twenty is generous for that
# and still a few kilobytes of hex.
SHA_HISTORY_CAP = 20


def advance_sha_history(
    previous: Dict[str, Any], new_shas: Dict[str, str], sys_id: str = ""
) -> Dict[str, list]:
    """Fold the anchor being replaced into the per-field history, newest first.

    Every sha that ever sat in ``field_shas`` was recorded only when the local
    copy provably equalled the server body, so the history is a list of bodies
    the origin has actually held. That is what lets a promotion prove the target
    is merely behind instead of asking a human to compare 67 KB by eye: a push
    or a re-download replaces the anchor with the NEWER body, and without this
    the older version — the one the target still holds — is gone.

    A different ``sys_id`` under the same name is a different record (deleted and
    re-created); its bodies say nothing about this one, so nothing carries over.
    """
    prior_id = str(previous.get("sys_id") or "")
    if sys_id and prior_id and prior_id != sys_id:
        return {}
    history: Dict[str, list] = {
        f: [h for h in v if isinstance(h, str) and h]
        for f, v in (previous.get("field_sha_history") or {}).items()
        if isinstance(v, list)
    }
    for field_name, old_sha in (previous.get("field_shas") or {}).items():
        if not isinstance(old_sha, str) or not old_sha or old_sha == new_shas.get(field_name):
            continue
        chain = [old_sha] + [h for h in history.get(field_name, []) if h != old_sha]
        history[field_name] = chain[:SHA_HISTORY_CAP]
    return history


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


# refresh_mirror outcomes
MIRROR_ABSENT = "absent"  # no sidecar on disk
MIRROR_CURRENT = "current"  # sidecar already equals the live server body
MIRROR_REFRESHED = "refreshed"  # sidecar had gone stale -> rewritten from live


def refresh_mirror(file_path: Path, remote_content: str) -> str:
    """Bring an existing ``.remote`` sidecar up to the CURRENT server body.

    The mirror is written at reconcile time and then frozen, while the tools that
    point at it say "the server's CURRENT body is in the sidecar". The server can
    move again five minutes later: you then merge a body nobody has, and the push
    gate rejects the result — the merge was wasted and the message was a lie. A
    stale copy of the server has no reason to exist (see this module's header);
    that only holds if something actually keeps it fresh.

    Call this from any surface that HAS the live body in hand. Rewriting costs
    nothing safety-wise: a mirror is the SERVER's copy, never your work, so
    replacing it can only ever discard a version of theirs you had not merged yet
    — and the fresh one is the version you actually need to merge.

    Callers WITHOUT a live body must not claim the sidecar is current. There is
    deliberately no offline "assume it's fine" path here.
    """
    mirror = mirror_path_for(file_path)
    if not mirror.exists():
        return MIRROR_ABSENT
    remote = remote_content if isinstance(remote_content, str) else ""
    try:
        if field_sha(mirror.read_text(encoding="utf-8")) == field_sha(remote):
            return MIRROR_CURRENT
    except (OSError, UnicodeDecodeError):
        pass  # unreadable => rewrite it rather than trust it
    atomic_write_text(mirror, normalize_source_eol(remote))
    return MIRROR_REFRESHED


# reconcile_field outcomes
WRITTEN = "written"  # no local file existed -> wrote the server body
UNCHANGED = "unchanged"  # local already equals the live server body
REFRESHED = "refreshed"  # local was clean (== last sync) -> updated to live
KEPT_LOCAL = "kept_local"  # local carries edits, server unmoved -> kept as-is
CONFLICT_MIRRORED = "conflict_mirrored"  # local edits AND server moved -> mirror written
LEGACY_KEPT = "legacy_kept"  # no anchor, caller policy = preserve local
BLANK_REMOTE_KEPT = "blank_remote_kept"  # remote body blank/unknown -> untouched

DISCARDED = "discarded"  # local edits dropped on request -> server body written
STASHED = "stashed"  # local edits set aside on request -> server body written

# Outcomes after which the local file provably equals the current remote body, so
# the caller may record the returned sha + bump the mod_count watermark.
IN_SYNC_OUTCOMES = frozenset({WRITTEN, UNCHANGED, REFRESHED, DISCARDED, STASHED})
# Outcomes where an edit of yours was held back — the ones that need a decision.
HELD_OUTCOMES = frozenset({KEPT_LOCAL, CONFLICT_MIRRORED, LEGACY_KEPT})


def stash_path_for(file_path: Path) -> Path:
    """Where a set-aside edit goes: ``<parent>/_stash/<scope>/<table>/<name>/<file>``.

    Outside the scope root on purpose: every tree scanner walks the scope root,
    and a stashed body inside it would be read as a component. One slot per file
    — a later stash of the same file replaces the earlier one, so stashes never
    pile up. Plain files, no git assumed.
    """
    record_dir = file_path.parent
    scope_root = record_dir.parent.parent
    return (
        scope_root.parent
        / STASH_DIRNAME
        / scope_root.name
        / record_dir.parent.name
        / record_dir.name
        / file_path.name
    )


def _take_remote(file_path: Path, remote: str, mode: str) -> str:
    """Replace a held local file with the server body, per the user's answer."""
    outcome = DISCARDED
    if mode == LOCAL_EDITS_STASH:
        stash = stash_path_for(file_path)
        stash.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(file_path, stash)
        outcome = STASHED
    _write_local(file_path, remote)
    cleanup_mirror(file_path)
    return outcome


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
    known_shas: Iterable[str] = (),
    on_local_edits: str = LOCAL_EDITS_KEEP,
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
    ``known_shas``: older bodies the server has held for this field (the anchor's
    ``field_sha_history``). A local copy equal to one of them is a copy that fell
    behind, not an edit: nothing in it is yours, so it fast-forwards like a clean
    file. Without this, a file whose anchor had moved past it (an anchor recorded
    from a payload the file never received) read as "your edit" forever and could
    only be cleared by deleting the folder.
    ``on_local_edits``: the user's answer for a file that carries edits — KEEP
    (default), CLEAN or STASH. Never applied to a blank remote under
    ``blank_remote_is_unknown``: a spurious blank is not a server body to take.
    """
    outcome, sha = _reconcile(
        file_path,
        remote_content,
        stored_sha,
        legacy_overwrite=legacy_overwrite,
        blank_remote_is_unknown=blank_remote_is_unknown,
        known_shas=known_shas,
    )
    if outcome in HELD_OUTCOMES and on_local_edits in (LOCAL_EDITS_CLEAN, LOCAL_EDITS_STASH):
        remote = remote_content if isinstance(remote_content, str) else ""
        try:
            return _take_remote(file_path, remote, on_local_edits), field_sha(remote)
        except OSError:
            return outcome, sha  # could not set it aside -> leave the edit alone
    return outcome, sha


def _reconcile(
    file_path: Path,
    remote_content: str,
    stored_sha: str,
    *,
    legacy_overwrite: bool,
    blank_remote_is_unknown: bool,
    known_shas: Iterable[str],
) -> Tuple[str, str]:
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

    # A body the server held before is not an edit — it is a copy that fell behind.
    # Proven from the record's own history, so it holds even with no current anchor.
    if local_sha in {h for h in known_shas if isinstance(h, str) and h}:
        _write_local(file_path, remote)
        cleanup_mirror(file_path)
        return REFRESHED, remote_sha

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


def rerun_call(tool: str, args: Dict[str, Any], instance_alias: str = "") -> str:
    """The caller's own call again, with ``{mode}`` where the answer goes.

    Built from the arguments the caller actually passed: a rerun that dropped
    ``output_dir`` or ``instance`` would land on a DIFFERENT tree (the default
    path, the active instance) — and with an explicit ``output_dir`` it would
    write another instance's bodies into this one. ``instance`` is stripped by the
    router before the tool runs, so it is passed back in explicitly.
    """
    parts = [f"{k}={v!r}" for k, v in args.items() if k != "on_local_edits"]
    if instance_alias:
        parts.append(f"instance={instance_alias!r}")
    parts.append("on_local_edits='{mode}'")
    return f"{tool}({', '.join(parts)})"


def local_edits_decision(held: list, rerun_call: str) -> Dict[str, Any]:
    """The question a download/refresh asks when it held edits back.

    Held edits used to be reported and then left to pile up, and the only way to
    clear them was deleting the folder and downloading again. Which way to go is
    the user's call, so it is asked — with each answer as a ready call.
    ``rerun_call`` is the same call with ``{mode}`` where the answer goes.
    """
    return {
        "question": (
            f"{len(held)} file(s) carry your local edits and were left as they are. "
            "Keep working on them, or take the server copy?"
        ),
        "files": list(held),
        "options": {
            LOCAL_EDITS_KEEP: "Leave them; push with update_remote_from_local when ready.",
            LOCAL_EDITS_CLEAN: (
                "Take the server copy, dropping the edits: "
                + rerun_call.replace("{mode}", LOCAL_EDITS_CLEAN)
            ),
            LOCAL_EDITS_STASH: (
                f"Take the server copy, edits copied to {STASH_DIRNAME}/ first "
                "(one slot per file, beside the scope folder): "
                + rerun_call.replace("{mode}", LOCAL_EDITS_STASH)
            ),
        },
    }
