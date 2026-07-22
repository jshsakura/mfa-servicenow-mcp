"""Tests for utils/sync_anchor.py — the live-anchored replacement for the frozen
_baseline/ 3-way. Priority: the hash comparison MUST stay valid across pure
line-ending / trailing-newline noise (else every CRLF instance reads as 'edited')."""

from pathlib import Path

from servicenow_mcp.tools.sync_tools import _normalize_for_compare
from servicenow_mcp.utils.sync_anchor import (
    BLANK_REMOTE_KEPT,
    CONFLICT_MIRRORED,
    KEPT_LOCAL,
    LEGACY_KEPT,
    REFRESHED,
    UNCHANGED,
    WRITTEN,
    field_sha,
    is_mirror_artifact,
    mirror_path_for,
    normalize_for_hash,
    reconcile_field,
)


class TestHashComparisonValidity:
    """The anchor is only trustworthy if identical logical content always hashes
    the same regardless of EOL style or a trailing newline."""

    def test_crlf_and_lf_hash_identically(self):
        assert field_sha("a\r\nb\r\nc") == field_sha("a\nb\nc")

    def test_bare_cr_hashes_identically(self):
        assert field_sha("a\rb\rc") == field_sha("a\nb\nc")

    def test_trailing_newline_ignored(self):
        assert field_sha("a\nb\n") == field_sha("a\nb")

    def test_real_one_char_change_differs(self):
        assert field_sha("var x = 1;") != field_sha("var x = 2;")

    def test_none_and_empty_are_stable(self):
        assert field_sha("") == field_sha(None)  # type: ignore[arg-type]

    def test_one_basis_matches_sync_tools_compare(self):
        """normalize_for_hash MUST equal sync_tools._normalize_for_compare so the
        sha decision and the rendered diff can never disagree."""
        for sample in ("a\r\nb", "x\ry\n", "line\n", "no-newline", ""):
            assert normalize_for_hash(sample) == _normalize_for_compare(sample)


class TestMirrorHelpers:
    def test_mirror_path_before_extension(self):
        assert mirror_path_for(Path("a/script.js")).name == "script.remote.js"

    def test_mirror_path_no_extension(self):
        assert mirror_path_for(Path("a/README")).name == "README.remote"

    def test_is_mirror_artifact(self):
        assert is_mirror_artifact(Path("a/script.remote.js"))
        assert not is_mirror_artifact(Path("a/script.js"))


class TestReconcileField:
    def test_no_local_file_writes_server_body(self, tmp_path):
        f = tmp_path / "script.js"
        outcome, sha = reconcile_field(f, "var x = 1;\n", "")
        assert outcome == WRITTEN
        assert f.read_text() == "var x = 1;\n"
        assert sha == field_sha("var x = 1;")

    def test_local_equals_remote_reseeds_anchor(self, tmp_path):
        f = tmp_path / "script.js"
        f.write_text("var x = 1;\n")
        outcome, sha = reconcile_field(f, "var x = 1;", "")  # legacy, but equal
        assert outcome == UNCHANGED
        assert sha == field_sha("var x = 1;")

    def test_crlf_only_delta_is_not_a_conflict(self, tmp_path):
        """The critical one: local LF vs remote CRLF of the same script must be
        UNCHANGED, never a spurious conflict/mirror."""
        f = tmp_path / "script.js"
        f.write_text("a\nb\nc")
        outcome, _ = reconcile_field(f, "a\r\nb\r\nc", field_sha("a\nb\nc"))
        assert outcome == UNCHANGED
        assert not mirror_path_for(f).exists()

    def test_clean_working_copy_refreshes_when_server_moved(self, tmp_path):
        f = tmp_path / "script.js"
        f.write_text("old\n")
        anchor = field_sha("old")
        outcome, sha = reconcile_field(f, "new server\n", anchor)
        assert outcome == REFRESHED
        assert f.read_text() == "new server\n"
        assert sha == field_sha("new server")

    def test_local_edits_server_unmoved_keeps_local(self, tmp_path):
        f = tmp_path / "script.js"
        f.write_text("my edit\n")
        anchor = field_sha("original")
        # remote still equals the anchor -> server did not move
        outcome, sha = reconcile_field(f, "original", anchor)
        assert outcome == KEPT_LOCAL
        assert f.read_text() == "my edit\n"
        assert sha == anchor
        assert not mirror_path_for(f).exists()

    def test_true_conflict_keeps_local_and_mirrors_live(self, tmp_path):
        f = tmp_path / "script.js"
        f.write_text("my edit\n")
        anchor = field_sha("original")
        outcome, sha = reconcile_field(f, "their server change\n", anchor)
        assert outcome == CONFLICT_MIRRORED
        assert f.read_text() == "my edit\n"  # working copy protected
        mirror = mirror_path_for(f)
        assert mirror.exists()
        assert mirror.read_text() == "their server change\n"  # always-fresh live
        assert sha == anchor  # anchor stays until resolved

    def test_legacy_no_anchor_keeps_local_by_default(self, tmp_path):
        f = tmp_path / "script.js"
        f.write_text("local\n")
        outcome, sha = reconcile_field(f, "different server\n", "")
        assert outcome == LEGACY_KEPT
        assert f.read_text() == "local\n"
        assert sha == ""

    def test_legacy_overwrite_refreshes(self, tmp_path):
        f = tmp_path / "script.js"
        f.write_text("local\n")
        outcome, sha = reconcile_field(f, "server\n", "", legacy_overwrite=True)
        assert outcome == REFRESHED
        assert f.read_text() == "server\n"
        assert sha == field_sha("server")

    def test_blank_remote_unknown_leaves_local(self, tmp_path):
        f = tmp_path / "script.js"
        f.write_text("local\n")
        outcome, sha = reconcile_field(f, "   ", field_sha("local"), blank_remote_is_unknown=True)
        assert outcome == BLANK_REMOTE_KEPT
        assert f.read_text() == "local\n"

    def test_resolved_conflict_clears_mirror(self, tmp_path):
        f = tmp_path / "script.js"
        f.write_text("merged\n")
        mirror = mirror_path_for(f)
        mirror.write_text("stale server\n")
        # local now equals the live server -> mirror is stale, must be cleared
        outcome, _ = reconcile_field(f, "merged", field_sha("something old"))
        assert outcome == UNCHANGED
        assert not mirror.exists()
