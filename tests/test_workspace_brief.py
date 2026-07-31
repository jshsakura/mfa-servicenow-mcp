"""Tests for the automatic workspace surfacing (sn_health integration).

There is deliberately NO workspace tool: automation the LLM must remember to
invoke is not automation. Pinned invariants:
- sn_health carries a `workspace` summary of unfinished local work (unpushed
  edits, unresolved '.remote' conflicts) — pure disk reads, no network.
- Silent when clean, silent when nothing was ever downloaded — zero noise for
  users who never touch local sources.
- A broken/unreadable temp tree can never fail the health check.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.workspace_tools import _discover_trees, _scan_tree_local
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.sync_anchor import field_sha, mirror_path_for


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth():
    return MagicMock()


@pytest.fixture
def workspace(tmp_path):
    """temp/<instance>/<scope> tree with one widget, seeded baseline."""
    tree = tmp_path / "temp" / "test" / "x_app"
    widget_dir = tree / "sp_widget" / "my-widget"
    widget_dir.mkdir(parents=True)
    (tmp_path / "temp" / "test" / "_settings.json").write_text(
        json.dumps({"name": "test", "url": "https://test.service-now.com", "g_ck": ""}),
        encoding="utf-8",
    )
    (tree / "_manifest.json").write_text(
        json.dumps({"scope": "x_app", "instance": "https://test.service-now.com"}),
        encoding="utf-8",
    )
    script = widget_dir / "script.js"
    script.write_text("var x = 1;", encoding="utf-8")
    (tree / "sp_widget" / "_map.json").write_text(
        json.dumps({"my-widget": "wid-1"}), encoding="utf-8"
    )
    (tree / "sp_widget" / "_sync_meta.json").write_text(
        json.dumps(
            {
                "my-widget": {
                    "sys_id": "wid-1",
                    "sys_updated_on": "2025-01-10 10:00:00",
                    "downloaded_at": "2025-01-10T10:05:00+00:00",
                    "field_shas": {"script": field_sha("var x = 1;")},
                }
            }
        ),
        encoding="utf-8",
    )
    return tmp_path / "temp"


class TestTreeScan:
    def test_clean_tree(self, workspace):
        trees = _discover_trees(workspace, 10)
        assert len(trees) == 1
        local = _scan_tree_local(trees[0])
        assert local["components"] == 1
        assert local["anchor_protected"] == 1
        assert local["your_edits"] == []
        assert local["unresolved_conflicts"] == []

    def test_detects_edits_and_sidecars(self, workspace):
        script = workspace / "test" / "x_app" / "sp_widget" / "my-widget" / "script.js"
        script.write_text("var x = 1; // my edit", encoding="utf-8")
        mirror_path_for(script).write_text("var x = 2;", encoding="utf-8")

        local = _scan_tree_local(workspace / "test" / "x_app")
        assert local["your_edits"] == ["sp_widget/my-widget:script.js"]
        assert local["unresolved_conflicts"] == ["sp_widget/my-widget (script.remote.js)"]

    def test_legacy_tree_counts_as_unprotected(self, workspace):
        # A tree with no field-sha anchor (legacy download) cannot attribute edits.
        meta_path = workspace / "test" / "x_app" / "sp_widget" / "_sync_meta.json"
        meta = json.loads(meta_path.read_text())
        meta["my-widget"].pop("field_shas", None)
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        local = _scan_tree_local(workspace / "test" / "x_app")
        assert local["anchor_protected"] == 0
        assert local["your_edits"] == []  # no anchor -> cannot claim edits


class TestHealthIntegration:
    """Unfinished local work must surface NATURALLY on the session's usual
    first call (sn_health) — nobody has to remember a separate tool."""

    def test_snapshot_reports_edits_and_conflicts(self, workspace, monkeypatch):
        from servicenow_mcp.tools.sn_api import _workspace_snapshot

        script = workspace / "test" / "x_app" / "sp_widget" / "my-widget" / "script.js"
        script.write_text("var x = 1; // my edit", encoding="utf-8")
        mirror_path_for(script).write_text("var x = 2;", encoding="utf-8")
        monkeypatch.chdir(workspace.parent)

        snap = _workspace_snapshot()
        assert snap["unpushed_local_edits"] == 1
        assert snap["unresolved_conflicts"] == 1
        assert "diff_local_component" in snap["next"]

    def test_snapshot_silent_when_clean(self, workspace, monkeypatch):
        from servicenow_mcp.tools.sn_api import _workspace_snapshot

        monkeypatch.chdir(workspace.parent)
        assert _workspace_snapshot() == {}

    def test_snapshot_silent_when_no_temp(self, tmp_path, monkeypatch):
        from servicenow_mcp.tools.sn_api import _workspace_snapshot

        monkeypatch.chdir(tmp_path)
        assert _workspace_snapshot() == {}

    def test_snapshot_survives_unreadable_tree(self, workspace, monkeypatch):
        """A permission-denied tree must degrade to silence — the health check
        itself must never fail because ./temp is unreadable."""
        import os

        from servicenow_mcp.tools.sn_api import _workspace_snapshot

        if os.geteuid() == 0:
            pytest.skip("root ignores file permissions")
        tree = workspace / "test" / "x_app"
        monkeypatch.chdir(workspace.parent)
        tree.chmod(0o000)
        try:
            assert _workspace_snapshot() == {}
        finally:
            tree.chmod(0o755)  # restore so pytest tmp cleanup works

    @patch("servicenow_mcp.tools.sn_api._workspace_snapshot")
    @patch("servicenow_mcp.tools.sn_api._authenticated_user")
    @patch("servicenow_mcp.tools.sn_api._auth_identity_fields")
    @patch("servicenow_mcp.tools.sn_api._chromium_health_fields")
    @patch("servicenow_mcp.tools.sn_api._sn_health_impl")
    def test_sn_health_carries_workspace_summary(
        self, mock_impl, mock_chromium, mock_identity, mock_user, mock_snap, mock_config, mock_auth
    ):
        from servicenow_mcp.tools.sn_api import HealthCheckParams, sn_health

        mock_impl.return_value = {"ok": True}
        mock_chromium.return_value = {}
        mock_identity.return_value = {}
        mock_user.return_value = None
        mock_snap.return_value = {"unpushed_local_edits": 2}

        result = sn_health(mock_config, mock_auth, HealthCheckParams())
        assert result["workspace"] == {"unpushed_local_edits": 2}

    def test_workspace_brief_tool_is_not_registered(self):
        """Automation the LLM must remember to invoke is not automation —
        the tool was removed on purpose; the data rides sn_health instead."""
        from servicenow_mcp.utils.registry import discover_tools

        assert "workspace_brief" not in discover_tools()


class TestDownloadRootRegistry:
    """temp/ is not the law: downloads auto-record their real roots so the
    snapshot follows the user's personal layout with zero configuration."""

    def test_record_and_list_roundtrip(self, tmp_path):
        from servicenow_mcp.utils.workspace_roots import known_download_roots, record_download_root

        root = tmp_path / "my" / "custom" / "place"
        root.mkdir(parents=True)
        record_download_root(root)
        assert root.resolve() in known_download_roots()

    def test_nonexistent_roots_are_pruned_on_read(self, tmp_path):
        from servicenow_mcp.utils.workspace_roots import known_download_roots, record_download_root

        gone = tmp_path / "was-here"
        gone.mkdir()
        record_download_root(gone)
        gone.rmdir()
        assert known_download_roots() == []

    def test_snapshot_follows_recorded_custom_root(self, workspace, tmp_path, monkeypatch):
        """A tree downloaded to a custom output_dir (recorded automatically)
        surfaces in the health snapshot even when cwd has no ./temp at all."""
        from servicenow_mcp.tools.sn_api import _workspace_snapshot
        from servicenow_mcp.utils.workspace_roots import record_download_root

        tree = workspace / "test" / "x_app"
        script = tree / "sp_widget" / "my-widget" / "script.js"
        script.write_text("var x = 1; // my edit", encoding="utf-8")
        record_download_root(tree)

        elsewhere = tmp_path / "unrelated-cwd"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        snap = _workspace_snapshot()
        assert snap["unpushed_local_edits"] == 1

    def test_download_resolver_records_root(self, tmp_path, mock_config):
        from servicenow_mcp.tools.source_tools import _resolve_scope_root
        from servicenow_mcp.utils.workspace_roots import known_download_roots

        custom = tmp_path / "elsewhere" / "x_app"
        _resolve_scope_root(mock_config, "x_app", str(custom))
        assert custom.resolve() in known_download_roots()

    def test_budget_stops_hashing_but_never_stops_looking_for_conflicts(self, workspace):
        """The budget bounds the expensive half only.

        Finding your unpushed edits means hashing every file; finding a conflict
        is one exists(). A conflict is a decision somebody still owes, so a speed
        guard must never be the reason one goes unlisted — those edits are still
        there to be found next call, and the push gate re-checks them live anyway.
        """
        script = workspace / "test" / "x_app" / "sp_widget" / "my-widget" / "script.js"
        script.write_text("var x = 1; // my edit", encoding="utf-8")
        mirror_path_for(script).write_text("var x = 2;", encoding="utf-8")

        local = _scan_tree_local(workspace / "test" / "x_app", component_budget=0)

        assert local["hashed"] == 0
        assert local["your_edits"] == []  # not hashed, so not found — acceptable
        assert local["unresolved_conflicts"]  # found anyway — not acceptable to miss
        assert local["conflict_paths"] == [str(script)]


class TestConflictIsAQuestionNotANotice:
    """A conflict is a decision nobody has made yet. Reporting a count and moving
    on is how it stayed unmade until a push reverted somebody."""

    @staticmethod
    def _with_conflict(workspace):
        script = workspace / "test" / "x_app" / "sp_widget" / "my-widget" / "script.js"
        script.write_text("var x = 1; // my edit", encoding="utf-8")
        mirror_path_for(script).write_text("var x = 2;", encoding="utf-8")
        return script

    def test_health_states_the_choices_and_names_the_files(self, workspace, monkeypatch):
        from servicenow_mcp.tools.sn_api import _workspace_snapshot

        self._with_conflict(workspace)
        monkeypatch.chdir(workspace.parent)

        decision = _workspace_snapshot()["decision_required"]
        assert "both" in decision["question"].lower()
        # Every option is a call, not advice.
        assert "update_remote_from_local" in decision["keep_both"]
        assert "update_remote_from_local" in decision["keep_mine"]
        assert decision["take_theirs"]
        # And it names the WORKING file, not the sidecar and not a label the
        # caller would have to reconstruct a path from.
        assert decision["components"]
        assert decision["components"][0].endswith("script.js")
        assert ".remote." not in decision["components"][0]

    def test_no_conflict_asks_nothing(self, workspace, monkeypatch):
        from servicenow_mcp.tools.sn_api import _workspace_snapshot

        script = workspace / "test" / "x_app" / "sp_widget" / "my-widget" / "script.js"
        script.write_text("var x = 1; // my edit", encoding="utf-8")
        monkeypatch.chdir(workspace.parent)

        snap = _workspace_snapshot()
        assert snap["unpushed_local_edits"] == 1  # edits alone are not a question
        assert "decision_required" not in snap

    def test_the_offline_count_does_not_claim_the_sidecar_is_current(self, workspace, monkeypatch):
        """This scan never touches the network, so it must not imply freshness —
        that is established only where the live record is in hand."""
        from servicenow_mcp.tools.sn_api import _workspace_snapshot

        self._with_conflict(workspace)
        monkeypatch.chdir(workspace.parent)

        nxt = _workspace_snapshot()["next"]
        assert "offline" in nxt
        assert "re-verifies" in nxt
