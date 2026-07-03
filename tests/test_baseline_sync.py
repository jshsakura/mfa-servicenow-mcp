"""Tests for the 3-way baseline safety net (utils/baseline.py + integrations).

Invariants pinned here:
- sync_field_file NEVER destroys local edits (only clean copies or the caller's
  explicit legacy policy get overwritten).
- A true conflict keeps the local file and saves the server's body as a
  '<stem>.remote<ext>' sidecar.
- Baseline artifacts are recognized (scanner skip / push rejection).
- A successful push re-seeds the baseline and clears a resolved sidecar.
- diff_local_component separates YOUR edits from the SERVER's changes.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.sync_tools import (
    DiffLocalComponentParams,
    PushLocalComponentParams,
    _resolve_local_path,
    diff_local_component,
    update_remote_from_local,
)
from servicenow_mcp.utils.baseline import (
    ACTION_BLANK_REMOTE_KEPT,
    ACTION_CONFLICT,
    ACTION_KEPT_DIRTY,
    ACTION_LEGACY_KEPT,
    ACTION_LEGACY_OVERWRITTEN,
    ACTION_REFRESHED,
    ACTION_RESEEDED,
    ACTION_UNCHANGED,
    ACTION_WRITTEN,
    IN_SYNC_ACTIONS,
    baseline_path_for,
    is_baseline_artifact,
    read_baseline_for,
    remote_sidecar_path_for,
    sync_field_file,
    write_baseline_for,
)
from servicenow_mcp.utils.config import ServerConfig

ORIGINAL = "var x = 1;"
LOCAL_EDIT = "var x = 1; // my edit"
REMOTE_EDIT = "var x = 2; // their edit"


@pytest.fixture
def field_file(tmp_path):
    return tmp_path / "record" / "script.js"


def _seed(field_file, local, baseline):
    field_file.parent.mkdir(parents=True, exist_ok=True)
    field_file.write_text(local, encoding="utf-8")
    write_baseline_for(field_file, baseline)


# ---------------------------------------------------------------------------
# sync_field_file decision matrix
# ---------------------------------------------------------------------------
class TestSyncFieldFile:
    def test_missing_local_writes_file_and_baseline(self, field_file):
        action = sync_field_file(field_file, ORIGINAL, legacy_overwrite=False)
        assert action == ACTION_WRITTEN
        assert field_file.read_text() == ORIGINAL
        assert read_baseline_for(field_file) == ORIGINAL

    def test_clean_local_remote_unmoved_is_noop(self, field_file):
        _seed(field_file, ORIGINAL, ORIGINAL)
        assert sync_field_file(field_file, ORIGINAL, legacy_overwrite=False) == ACTION_UNCHANGED
        assert field_file.read_text() == ORIGINAL

    def test_clean_local_remote_moved_auto_refreshes(self, field_file):
        _seed(field_file, ORIGINAL, ORIGINAL)
        action = sync_field_file(field_file, REMOTE_EDIT, legacy_overwrite=False)
        assert action == ACTION_REFRESHED
        assert field_file.read_text() == REMOTE_EDIT
        assert read_baseline_for(field_file) == REMOTE_EDIT

    def test_dirty_local_remote_unmoved_is_kept(self, field_file):
        _seed(field_file, LOCAL_EDIT, ORIGINAL)
        assert sync_field_file(field_file, ORIGINAL, legacy_overwrite=False) == ACTION_KEPT_DIRTY
        assert field_file.read_text() == LOCAL_EDIT
        # Baseline stays the common ancestor.
        assert read_baseline_for(field_file) == ORIGINAL

    def test_dirty_local_matching_remote_reseeds_baseline(self, field_file):
        # The user's edit was applied on the server too (manual apply).
        _seed(field_file, LOCAL_EDIT, ORIGINAL)
        assert sync_field_file(field_file, LOCAL_EDIT, legacy_overwrite=False) == ACTION_RESEEDED
        assert read_baseline_for(field_file) == LOCAL_EDIT

    def test_conflict_keeps_local_and_writes_sidecar(self, field_file):
        _seed(field_file, LOCAL_EDIT, ORIGINAL)
        action = sync_field_file(field_file, REMOTE_EDIT, legacy_overwrite=False)
        assert action == ACTION_CONFLICT
        assert field_file.read_text() == LOCAL_EDIT
        sidecar = remote_sidecar_path_for(field_file)
        assert sidecar.name == "script.remote.js"
        assert sidecar.read_text() == REMOTE_EDIT
        # Baseline untouched — still the ancestor for a later merge.
        assert read_baseline_for(field_file) == ORIGINAL

    def test_conflict_even_under_legacy_overwrite_policy(self, field_file):
        # legacy_overwrite only applies to trees WITHOUT a baseline; with one,
        # local edits are protected regardless of caller policy (incremental /
        # portal full overwrite).
        _seed(field_file, LOCAL_EDIT, ORIGINAL)
        assert sync_field_file(field_file, REMOTE_EDIT, legacy_overwrite=True) == ACTION_CONFLICT
        assert field_file.read_text() == LOCAL_EDIT

    def test_legacy_tree_kept_without_overwrite_policy(self, field_file):
        field_file.parent.mkdir(parents=True)
        field_file.write_text(LOCAL_EDIT, encoding="utf-8")
        assert (
            sync_field_file(field_file, REMOTE_EDIT, legacy_overwrite=False) == ACTION_LEGACY_KEPT
        )
        assert field_file.read_text() == LOCAL_EDIT
        assert read_baseline_for(field_file) is None

    def test_legacy_tree_overwritten_seeds_baseline(self, field_file):
        field_file.parent.mkdir(parents=True)
        field_file.write_text(LOCAL_EDIT, encoding="utf-8")
        action = sync_field_file(field_file, REMOTE_EDIT, legacy_overwrite=True)
        assert action == ACTION_LEGACY_OVERWRITTEN
        assert field_file.read_text() == REMOTE_EDIT
        assert read_baseline_for(field_file) == REMOTE_EDIT

    def test_blank_remote_is_unknown_keeps_everything(self, field_file):
        _seed(field_file, LOCAL_EDIT, ORIGINAL)
        action = sync_field_file(
            field_file, "", legacy_overwrite=True, blank_remote_is_unknown=True
        )
        assert action == ACTION_BLANK_REMOTE_KEPT
        assert field_file.read_text() == LOCAL_EDIT
        assert read_baseline_for(field_file) == ORIGINAL

    def test_eol_only_difference_is_not_a_change(self, field_file):
        _seed(field_file, "var a = 1;\nvar b = 2;\n", "var a = 1;\nvar b = 2;\n")
        action = sync_field_file(field_file, "var a = 1;\r\nvar b = 2;\r\n", legacy_overwrite=False)
        assert action == ACTION_UNCHANGED

    def test_refresh_clears_stale_sidecar(self, field_file):
        _seed(field_file, ORIGINAL, ORIGINAL)
        sidecar = remote_sidecar_path_for(field_file)
        sidecar.write_text("old conflict copy", encoding="utf-8")
        assert sync_field_file(field_file, REMOTE_EDIT, legacy_overwrite=False) == ACTION_REFRESHED
        assert not sidecar.exists()

    def test_in_sync_actions_frozenset(self):
        assert ACTION_WRITTEN in IN_SYNC_ACTIONS
        assert ACTION_CONFLICT not in IN_SYNC_ACTIONS
        assert ACTION_KEPT_DIRTY not in IN_SYNC_ACTIONS
        assert ACTION_BLANK_REMOTE_KEPT not in IN_SYNC_ACTIONS


# ---------------------------------------------------------------------------
# Artifact recognition (scanner skip / push rejection)
# ---------------------------------------------------------------------------
class TestArtifacts:
    def test_baseline_dir_is_artifact(self, field_file):
        assert is_baseline_artifact(baseline_path_for(field_file))

    def test_sidecar_is_artifact(self, field_file):
        assert is_baseline_artifact(remote_sidecar_path_for(field_file))

    def test_main_field_file_is_not_artifact(self, field_file):
        assert not is_baseline_artifact(field_file)

    def test_resolve_local_path_rejects_sidecar(self, tmp_path):
        sidecar = tmp_path / "sp_widget" / "w" / "script.remote.js"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="conflict sidecar"):
            _resolve_local_path(sidecar)

    def test_resolve_local_path_rejects_baseline_file(self, tmp_path):
        bfile = tmp_path / "sp_widget" / "w" / "_baseline" / "script.js"
        bfile.parent.mkdir(parents=True)
        bfile.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="baseline"):
            _resolve_local_path(bfile)


# ---------------------------------------------------------------------------
# Push integration: baseline re-seeded, resolved sidecar cleared
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


@pytest.fixture
def widget_root(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    (root / "_settings.json").write_text(
        json.dumps({"name": "test", "url": "https://test.service-now.com", "g_ck": ""}),
        encoding="utf-8",
    )
    widget_dir = root / "global" / "sp_widget" / "my-widget"
    widget_dir.mkdir(parents=True)
    (widget_dir / "script.js").write_text("var x = 1;", encoding="utf-8")
    (root / "global" / "sp_widget" / "_map.json").write_text(
        json.dumps({"my-widget": "wid-1"}), encoding="utf-8"
    )
    (root / "global" / "sp_widget" / "_sync_meta.json").write_text(
        json.dumps(
            {
                "my-widget": {
                    "sys_id": "wid-1",
                    "sys_updated_on": "2025-01-10 10:00:00",
                    "downloaded_at": "2025-01-10T10:05:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    return root


class TestPushRefreshesBaseline:
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_seeds_baseline_and_clears_sidecar(
        self, mock_fetch, mock_update, mock_config, mock_auth, widget_root
    ):
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"
        # Simulate an earlier conflict: baseline at the old ancestor + sidecar.
        write_baseline_for(script, "var x = 0;")
        sidecar = remote_sidecar_path_for(script)
        sidecar.write_text("var x = 9; // theirs", encoding="utf-8")

        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {"sys_id": "wid-1", "sys_updated_on": "2025-01-10 11:00:00"},
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(script))
        )

        assert result["success"] is True
        # The pushed body is the new common ancestor; the conflict is resolved.
        assert read_baseline_for(script) == "var x = 1;"
        assert not sidecar.exists()


# ---------------------------------------------------------------------------
# Diff integration: 3-way separation of YOUR edits vs the SERVER's changes
# ---------------------------------------------------------------------------
class TestDiffThreeWay:
    def _remote(self, script):
        return {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": script,
            "sys_updated_on": "2025-01-12 10:00:00",
            "sys_updated_by": "alice",
            "sys_created_by": "alice",
        }

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_your_edits_separated_from_unmoved_server(
        self, mock_fetch, mock_config, mock_auth, widget_root
    ):
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"
        write_baseline_for(script, "var x = 0;")  # local "var x = 1;" = YOUR edit
        mock_fetch.return_value = self._remote("var x = 0;")  # server == baseline

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(script))
        )
        assert result["three_way"]["your_local_edits"] == ["script"]
        assert "diverged_both_changed" not in result["three_way"]

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diverged_field_lists_conflict_sidecar(
        self, mock_fetch, mock_config, mock_auth, widget_root
    ):
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"
        write_baseline_for(script, "var x = 0;")
        sidecar = remote_sidecar_path_for(script)
        sidecar.write_text("var x = 9; // theirs", encoding="utf-8")
        mock_fetch.return_value = self._remote("var x = 9; // theirs")

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(script))
        )
        assert result["three_way"]["diverged_both_changed"] == ["script"]
        assert result["three_way"]["conflict_sidecars_on_disk"] == ["script.remote.js"]

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_legacy_tree_has_no_three_way_key(
        self, mock_fetch, mock_config, mock_auth, widget_root
    ):
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"
        mock_fetch.return_value = self._remote("var x = 0;")

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(script))
        )
        assert "three_way" not in result
