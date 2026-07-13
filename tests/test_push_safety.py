"""Tests for assess_push_risk — graduated push risk scoring (v1.16 SAFE pillar).

The existing push gate is binary (block on drift / allow on force). This adds a
DETERMINISTIC risk score (no LLM, no network) combining three signals the user
cares about for accident-prevention when pushing local edits:
  - the last remote editor is NOT me (someone else's work at stake)
  - the change MAGNITUDE (a 5-line tweak vs an 80% rewrite)
  - whether the remote drifted from my download baseline at all

It returns a level + a human-readable message so a forced overwrite still SHOWS
"you are about to overwrite alice's 80% rewrite", never silently.
"""

from servicenow_mcp.tools.push_safety import assess_push_risk, describe_attribution


class TestDescribeAttribution:
    """Free corroboration from data already on hand: the download baseline owner
    (_sync_meta, local), the current editor, and the creator (same fetch). No
    extra API, no LLM — just don't trust one field."""

    def test_ownership_changed_since_download(self):
        # I downloaded when 'a' owned it; now 'b' does → someone took it over.
        a = describe_attribution(baseline_by="a", current_by="b", created_by="a")
        assert a["attribution"] == "ownership_changed"
        assert a["ownership_changed"] is True
        assert "a" in a["note"] and "b" in a["note"]

    def test_shared_when_creator_differs_from_editor(self):
        a = describe_attribution(baseline_by="b", current_by="b", created_by="a")
        assert a["attribution"] == "shared"

    def test_consistent_when_all_align(self):
        a = describe_attribution(baseline_by="a", current_by="a", created_by="a")
        assert a["attribution"] == "consistent"
        assert a["ownership_changed"] is False

    def test_missing_baseline_does_not_falsely_flag(self):
        # No baseline owner recorded (older download) → cannot claim a change.
        a = describe_attribution(baseline_by="", current_by="b", created_by="")
        assert a["ownership_changed"] is False


class TestAssessPushRisk:
    def test_no_drift_small_change_is_none_or_low(self):
        r = assess_push_risk(
            me="me",
            remote_updated_by="me",
            drifted=False,
            changed_lines=3,
            total_lines=400,
        )
        assert r["level"] in ("none", "low")
        assert r["other_user"] is False

    def test_other_user_large_change_is_critical(self):
        r = assess_push_risk(
            me="me",
            remote_updated_by="alice",
            drifted=True,
            changed_lines=320,
            total_lines=400,
        )
        assert r["level"] == "critical"
        assert r["other_user"] is True
        # The human message names the editor and conveys magnitude.
        assert "alice" in r["message"]

    def test_other_user_small_change_is_high_not_critical(self):
        r = assess_push_risk(
            me="me",
            remote_updated_by="alice",
            drifted=True,
            changed_lines=4,
            total_lines=400,
        )
        assert r["level"] == "high"
        assert r["other_user"] is True

    def test_my_own_drift_large_change_is_medium_or_high(self):
        # I am the last editor (my own later edit) but it's a big rewrite.
        r = assess_push_risk(
            me="me",
            remote_updated_by="me",
            drifted=True,
            changed_lines=300,
            total_lines=400,
        )
        assert r["level"] in ("medium", "high")
        assert r["other_user"] is False

    def test_unconfirmed_identity_does_not_falsely_accuse(self):
        # The bug we are killing: when the current user is UNCONFIRMED, the old
        # code claimed "someone else edited this" — falsely flagging your OWN
        # update set as a coworker's. Now it must hedge, never assert other_user.
        r = assess_push_risk(
            me="",
            remote_updated_by="bob",
            drifted=True,
            changed_lines=10,
            total_lines=100,
            me_confirmed=False,
        )
        assert r["other_user"] is False
        assert r["identity"] == "unconfirmed"
        assert r["other_user_unconfirmed"] is True
        msg = r["message"].lower()
        assert "confirm" in msg  # hedged: "could not confirm this isn't you"
        assert "bob" in r["message"]
        # Still blocks-worthy on drift, just not a false accusation.
        assert r["level"] in ("medium", "high")

    def test_confirmed_other_user_is_asserted(self):
        # When we KNOW who we are and the editor differs, assert it plainly.
        r = assess_push_risk(
            me="me",
            remote_updated_by="alice",
            drifted=True,
            changed_lines=10,
            total_lines=100,
            me_confirmed=True,
        )
        assert r["other_user"] is True
        assert r["identity"] == "confirmed"

    def test_confirmed_me_equals_editor_is_not_other(self):
        # My own later edit (confirmed me == editor) is not a cross-user risk.
        r = assess_push_risk(
            me="alice",
            remote_updated_by="alice",
            drifted=True,
            changed_lines=5,
            total_lines=400,
            me_confirmed=True,
        )
        assert r["other_user"] is False
        assert r["identity"] == "confirmed"

    def test_change_ratio_guards_zero_total(self):
        # No divide-by-zero when remote has zero countable lines.
        r = assess_push_risk(
            me="me",
            remote_updated_by="me",
            drifted=False,
            changed_lines=0,
            total_lines=0,
        )
        assert r["level"] == "none"

    def test_ownership_change_escalates_and_is_named(self):
        # Recorded owner changed since download → strong signal, surfaced in the
        # message regardless of whether the editor matches 'me'.
        r = assess_push_risk(
            me="alice",
            remote_updated_by="bob",
            drifted=True,
            changed_lines=10,
            total_lines=100,
            me_confirmed=True,
            baseline_by="alice",
            created_by="alice",
        )
        assert r["attribution"] == "ownership_changed"
        assert r["level"] in ("high", "critical")
        assert "alice" in r["message"] and "bob" in r["message"]

    def test_attribution_defaults_consistent_without_extra_signals(self):
        # Back-compat: callers that don't pass baseline/creator still work.
        r = assess_push_risk(
            me="me",
            remote_updated_by="me",
            drifted=False,
            changed_lines=1,
            total_lines=100,
        )
        assert r["attribution"] == "consistent"

    def test_message_and_factors_always_present(self):
        r = assess_push_risk(
            me="me",
            remote_updated_by="alice",
            drifted=True,
            changed_lines=50,
            total_lines=100,
        )
        assert isinstance(r["message"], str) and r["message"]
        assert isinstance(r["factors"], list) and r["factors"]


class TestOwnEditIsNotAnAlarm:
    """The regression this class exists for: you edit a widget, push it, edit it
    again in the SAME session — and the tool warned that 'someone' had changed the
    record and the push was risky. That 'someone' was you. Being the last editor
    must never, by itself, produce a warning; only an UNSEEN server-side change can.
    """

    def test_my_own_edit_is_not_an_ownership_handoff(self):
        # Downloaded when 'admin' was the last editor; I have since edited it.
        # Old behaviour: "Ownership changed ... verify before trusting it".
        a = describe_attribution(baseline_by="admin", current_by="me", created_by="admin", me="me")
        assert a["ownership_changed"] is False
        assert a["self_edit"] is True
        assert a["attribution"] == "self"

    def test_editing_someone_elses_record_is_not_shared_noise(self):
        # Created by 'admin', last changed by me — the normal state of every record
        # I maintain. It must not surface as a 'shared record' flag.
        a = describe_attribution(baseline_by="me", current_by="me", created_by="admin", me="me")
        assert a["shared"] is False
        assert a["attribution"] == "self"

    def test_unconfirmed_identity_cannot_claim_self(self):
        # Never mute the alarm on an unverified 'that was probably me'.
        a = describe_attribution(
            baseline_by="admin", current_by="me", created_by="admin", me="me", me_confirmed=False
        )
        assert a["self_edit"] is False
        assert a["ownership_changed"] is True

    def test_real_handoff_still_flags_when_editor_is_not_me(self):
        a = describe_attribution(baseline_by="admin", current_by="bob", created_by="admin", me="me")
        assert a["ownership_changed"] is True
        assert a["attribution"] == "ownership_changed"

    def test_no_drift_large_own_edit_is_not_a_warning(self):
        # An 80% rewrite I just wrote, with the server untouched since my baseline.
        # There is nothing unseen to destroy — magnitude is not risk.
        r = assess_push_risk(
            me="me",
            remote_updated_by="me",
            drifted=False,
            changed_lines=320,
            total_lines=400,
            baseline_by="admin",
            created_by="admin",
        )
        assert r["level"] == "none"
        assert r["self_edit"] is True
        assert r["ownership_changed"] is False
        assert "safe to push" in r["message"].lower()

    def test_self_drift_names_me_and_does_not_accuse(self):
        # The server DID move and the mover was me (e.g. I edited it in the UI after
        # downloading). Still a real lost-update risk — but it must say so as mine.
        r = assess_push_risk(
            me="me",
            remote_updated_by="me",
            drifted=True,
            changed_lines=5,
            total_lines=400,
            baseline_by="admin",
            created_by="admin",
        )
        assert r["other_user"] is False
        assert r["self_edit"] is True
        assert r["level"] == "low"
        assert "your own" in r["message"].lower()
