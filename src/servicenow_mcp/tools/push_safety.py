"""Deterministic push risk scoring (no LLM, no network).

The push gate (`update_remote_from_local`) already knows WHO last touched the
remote, WHETHER it drifted from the download baseline, and WHICH fields changed.
This turns those facts into a graduated risk level + a human-readable warning so
an overwrite — even a forced one — is never silent about what it's about to
clobber. Pure function: same inputs → same output, fully unit-testable. Guards
stay deterministic code, not LLM judgement (see the multi-instance safety model).
"""

from typing import Any, Dict, List

# Fraction-of-lines-changed thresholds.
_LARGE_CHANGE_RATIO = 0.5
_MODERATE_CHANGE_RATIO = 0.15


def describe_attribution(
    *,
    baseline_by: str,
    current_by: str,
    created_by: str,
    me: str = "",
    me_confirmed: bool = True,
) -> Dict[str, Any]:
    """Corroborate WHO owns a record from signals already on hand — no extra API.

    - baseline_by: owner recorded in _sync_meta at YOUR download (local, free).
    - current_by:  the record's current sys_updated_by (already fetched).
    - created_by:  the record's sys_created_by (same fetch, one extra field).
    - me:          the confirmed current actor; "" when identity is unconfirmed.

    sys_updated_by is a CLAIM, not truth (impersonation can spoof it). We never
    trust it alone: if the recorded owner changed since your download, or the
    creator differs from the last editor, that is the signal to surface.

    But the flags must not fire on YOUR OWN edit. When you are the current editor
    (confirmed), "the owner changed since download" and "creator != editor" are
    both just descriptions of what you did — treating them as ownership alarms
    made a normal round-trip (edit -> push -> edit again) read as someone else's
    work at stake. Being the editor is NOT a safety verdict either: it only mutes
    the attribution alarm. Whether the SERVER BODY moved is decided by content
    hashing against the pristine baseline, upstream of this function.
    """
    baseline = (baseline_by or "").strip()
    current = (current_by or "").strip()
    creator = (created_by or "").strip()
    actor = (me or "").strip() if me_confirmed else ""

    self_edit = bool(actor) and bool(current) and current == actor

    # Raw signals, then the self-edit mute. Kept separate so "this WOULD have
    # flagged, but it was you" stays visible as attribution == "self".
    ownership_changed_raw = bool(baseline) and bool(current) and baseline != current
    shared_raw = bool(creator) and bool(current) and creator != current
    ownership_changed = ownership_changed_raw and not self_edit
    shared = shared_raw and not self_edit

    if ownership_changed:
        attribution = "ownership_changed"
        note = (
            f"Ownership changed since your download: recorded owner was '{baseline}', "
            f"now '{current}'. sys_updated_by is only a claim (impersonation can spoof "
            f"it) — verify before trusting it."
        )
    elif shared:
        attribution = "shared"
        note = f"Created by '{creator}', last changed by '{current}' — shared record."
    elif self_edit and (ownership_changed_raw or shared_raw):
        attribution = "self"
        note = f"You ('{current}') are the last editor on the server" + (
            f"; the record was originally created by '{creator}'." if shared_raw else "."
        )
    else:
        attribution = "consistent"
        note = ""

    return {
        "attribution": attribution,
        "ownership_changed": ownership_changed,
        "shared": shared,
        "self_edit": self_edit,
        "note": note,
    }


def _change_ratio(changed_lines: int, total_lines: int) -> float:
    if total_lines <= 0:
        return 0.0
    return min(1.0, max(0, changed_lines) / total_lines)


def assess_push_risk(
    *,
    me: str,
    remote_updated_by: str,
    drifted: bool,
    changed_lines: int,
    total_lines: int,
    me_confirmed: bool = True,
    baseline_by: str = "",
    created_by: str = "",
) -> Dict[str, Any]:
    """Score the risk of pushing a local edit over the current remote.

    Args:
        me: current push actor's username ("" if unresolved).
        remote_updated_by: username that last modified the remote.
        drifted: the SERVER BODY moved since your download/push baseline. The
            caller decides this by CONTENT (remote body vs the pristine baseline),
            not by a sys_updated_on bump — a bump also fires for your own push, a
            re-save, or an edit to an unrelated field on the same record.
        changed_lines: lines this push would change.
        total_lines: total lines in the remote (denominator for magnitude).
        me_confirmed: whether 'me' is a trusted identity (configured or resolved
            live from the session). When False we must NOT claim the editor is
            someone else — that is the false "another user committed your update
            set" bug. We hedge instead.

    Risk here means "what could this push destroy that you have NOT seen". With no
    server-side drift there is nothing unseen to destroy, so the size of YOUR OWN
    deliberate edit is reported as magnitude, never as a warning — a 90% rewrite
    you just wrote is the point of the push, not a hazard.

    Returns {level, score, other_user, other_user_unconfirmed, identity, self_edit,
    change_ratio, factors, message}.
    """
    remote_editor = (remote_updated_by or "").strip()
    confirmed = me_confirmed and bool((me or "").strip())
    identity = "confirmed" if confirmed else "unconfirmed"

    attr = describe_attribution(
        baseline_by=baseline_by,
        current_by=remote_editor,
        created_by=created_by,
        me=me,
        me_confirmed=me_confirmed,
    )
    ownership_changed = attr["ownership_changed"]
    self_edit = attr["self_edit"]

    # other_user is asserted ONLY when we know who we are and it differs.
    other_user = confirmed and bool(remote_editor) and remote_editor != me
    # When identity is unconfirmed, a known editor MIGHT be someone else — flagged
    # for caution, but never stated as fact.
    other_user_unconfirmed = (not confirmed) and bool(remote_editor)

    ratio = _change_ratio(changed_lines, total_lines)
    large = ratio >= _LARGE_CHANGE_RATIO
    moderate = ratio >= _MODERATE_CHANGE_RATIO

    factors: List[str] = []
    if ownership_changed:
        factors.append(f"ownership changed since download: '{baseline_by}' -> '{remote_editor}'")
    if drifted and other_user:
        factors.append(f"server body changed by '{remote_editor}', not you")
    elif drifted and other_user_unconfirmed:
        factors.append(f"server body changed by '{remote_editor}'; current user unconfirmed")
    elif drifted and self_edit:
        factors.append("server body carries your own later edit")
    elif drifted:
        factors.append("server body changed since your download baseline")
    if large:
        factors.append(f"large change (~{round(ratio * 100)}% of lines)")
    elif moderate:
        factors.append(f"moderate change (~{round(ratio * 100)}% of lines)")

    # A known signal that someone ELSE is at stake. self_edit already mutes
    # ownership_changed upstream, so your own edit can never be cross_party.
    cross_party = other_user or ownership_changed

    # No drift = nothing on the server you have not seen = nothing this push can
    # destroy unknowingly. Your own edit's size is magnitude, not risk.
    if not drifted:
        level = "none"
    elif cross_party and large:
        level = "critical"
    elif cross_party or other_user_unconfirmed:
        level = "high"
    elif self_edit:
        # A real lost-update (your local copy is older than your own server-side
        # edit) but self-inflicted and recoverable from version history.
        level = "medium" if large else "low"
    elif large:
        level = "high"
    else:
        level = "medium"

    score = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}[level]

    magnitude = f"~{round(ratio * 100)}% of the lines" if total_lines else "an unknown amount"
    if not drifted:
        scale = f"this edit changes {magnitude}" if total_lines else "no magnitude available"
        message = (
            f"Safe to push: the server body is identical to your baseline — nobody changed it "
            f"since your download/last push, so nothing unseen gets overwritten ({scale})."
        )
    elif ownership_changed and drifted:
        message = (
            f"When you downloaded this, the last editor was '{baseline_by}' — now it's "
            f"'{remote_editor}'. Someone changed it after your download. Your push would "
            f"overwrite {magnitude} of the current version; confirm before overwriting."
        )
    elif other_user and drifted:
        message = (
            f"'{remote_editor}' changed this on the server after your download. Your push "
            f"would overwrite {magnitude} of their version; confirm before overwriting."
        )
    elif other_user_unconfirmed and drifted:
        message = (
            f"'{remote_editor}' changed this after your download. I could not confirm who "
            f"you are logged in as, so I can't tell whether that was you — confirm before "
            f"overwriting ({magnitude})."
        )
    elif self_edit:
        message = (
            f"The server body is YOUR OWN later edit (last changed by '{remote_editor}') — no one "
            f"else's work is at stake. Pushing replaces {magnitude} of that newer server version "
            f"with this local copy; take it if the local copy is the one you want, or re-download "
            f"to keep the server's."
        )
    else:
        message = (
            f"The server body changed after your download. Your push would overwrite "
            f"{magnitude}; review before overwriting."
        )

    return {
        "level": level,
        "score": score,
        "other_user": other_user,
        "other_user_unconfirmed": other_user_unconfirmed,
        "identity": identity,
        "self_edit": self_edit,
        "attribution": attr["attribution"],
        "ownership_changed": ownership_changed,
        "change_ratio": round(ratio, 3),
        "factors": factors,
        "message": message,
    }
