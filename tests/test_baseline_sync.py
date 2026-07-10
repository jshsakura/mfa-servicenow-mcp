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
# _baseline/ directories keep themselves out of the user's git status
# ---------------------------------------------------------------------------
class TestBaselineDirSelfIgnores:
    def test_write_baseline_creates_self_ignoring_gitignore(self, field_file):
        write_baseline_for(field_file, ORIGINAL)
        gitignore = field_file.parent / "_baseline" / ".gitignore"
        assert gitignore.exists()
        # '*' ignores every snapshot AND the .gitignore itself -> nothing shows.
        assert gitignore.read_text().splitlines()[-1] == "*"

    def test_gitignore_lives_inside_baseline_dir_and_is_an_artifact(self, field_file):
        write_baseline_for(field_file, ORIGINAL)
        gitignore = field_file.parent / "_baseline" / ".gitignore"
        # Being under _baseline/, scanners skip it exactly like snapshots.
        assert is_baseline_artifact(gitignore)

    def test_existing_gitignore_is_not_clobbered(self, field_file):
        write_baseline_for(field_file, ORIGINAL)
        gitignore = field_file.parent / "_baseline" / ".gitignore"
        gitignore.write_text("custom\n", encoding="utf-8")
        write_baseline_for(field_file, REMOTE_EDIT)
        assert gitignore.read_text() == "custom\n"


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
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",  # landed = local
                "sys_updated_on": "2025-01-10 11:00:00",
            },
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

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diff_always_echoes_remote_state(self, mock_fetch, mock_config, mock_auth, widget_root):
        # An all-'unchanged' diff must still show the server's last-edit info,
        # so "no local/remote delta" is never read as "the server never moved".
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"
        mock_fetch.return_value = {**self._remote("var x = 1;"), "sys_mod_count": "165"}

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(script))
        )
        assert result["remote"]["updated_on"] == "2025-01-12 10:00:00"
        assert result["remote"]["updated_by"] == "alice"
        assert result["remote"]["mod_count"] == "165"


# ---------------------------------------------------------------------------
# Verdict mode: token-lean status-only verification (no diff bodies)
# ---------------------------------------------------------------------------
class TestVerdictMode:
    def _remote(self, script, mod_count="7"):
        return {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": script,
            "sys_updated_on": "2025-01-12 10:00:00",
            "sys_updated_by": "alice",
            "sys_created_by": "alice",
            "sys_mod_count": mod_count,
        }

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_component_verdict_local_ahead_has_no_bodies(
        self, mock_fetch, mock_config, mock_auth, widget_root
    ):
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"
        write_baseline_for(script, "var x = 0;")  # local edit vs unmoved server
        mock_fetch.return_value = self._remote("var x = 0;")

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(script), verdict=True)
        )
        assert result["mode"] == "verdict"
        assert result["verdict"] == "local_ahead"
        assert result["fields"]["script"]["state"] == "local_ahead"
        assert result["fields"]["script"]["changed_lines"] > 0
        assert result["remote"]["mod_count"] == "7"
        assert "diffs" not in result  # never diff bodies in verdict mode

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_component_verdict_identical(self, mock_fetch, mock_config, mock_auth, widget_root):
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"
        write_baseline_for(script, "var x = 1;")
        mock_fetch.return_value = self._remote("var x = 1;")

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(script), verdict=True)
        )
        assert result["verdict"] == "identical"
        assert "fields" not in result
        # P5: even 'identical' carries the server's last-edit evidence.
        assert result["remote"]["updated_by"] == "alice"

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_directory_verdict_scan_remote_ahead(
        self, mock_query, mock_config, mock_auth, widget_root
    ):
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"
        write_baseline_for(script, "var x = 1;")  # clean local
        mock_query.return_value = {
            "results": [self._remote("var x = 2; // server moved", mod_count="9")]
        }

        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(widget_root / "global"), verdict=True),
        )
        assert result["mode"] == "verdict"
        assert result["components_checked"] == 1
        assert result["in_sync"] == 0
        row = result["needs_attention"][0]
        assert row["verdict"] == "remote_ahead"
        assert row["fields"]["script"]["state"] == "remote_ahead"
        assert row["remote"]["mod_count"] == "9"

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_directory_verdict_scan_all_in_sync(
        self, mock_query, mock_config, mock_auth, widget_root
    ):
        mock_query.return_value = {"results": [self._remote("var x = 1;")]}
        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(widget_root / "global"), verdict=True),
        )
        assert result["components_checked"] == 1
        assert result["in_sync"] == 1
        assert result["needs_attention"] == []

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_table_dir_path_scans_directly(self, mock_query, mock_config, mock_auth, widget_root):
        mock_query.return_value = {"results": [self._remote("var x = 1;")]}
        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(widget_root / "global" / "sp_widget"), verdict=True),
        )
        assert result["components_checked"] == 1
        assert result["in_sync"] == 1

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_directory_verdict_flags_missing_remote(
        self, mock_query, mock_config, mock_auth, widget_root
    ):
        mock_query.return_value = {"results": []}
        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(widget_root / "global"), verdict=True),
        )
        assert result["needs_attention"][0]["verdict"] == "missing_remote"

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_directory_verdict_skips_other_instance_trees(
        self, mock_query, mock_config, mock_auth, widget_root
    ):
        (widget_root / "_settings.json").write_text(
            json.dumps({"name": "dev", "url": "https://dev.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(widget_root / "global"), verdict=True),
        )
        assert result["components_checked"] == 0
        assert result["skipped_other_instance"][0]["origin"] == "https://dev.service-now.com"
        assert "compare_instances" in result["skipped_hint"]
        mock_query.assert_not_called()


# ---------------------------------------------------------------------------
# Force-CAS: force=true approves overwriting exactly the version the caller
# reviewed. No local backup (ServiceNow's sys_update_version history covers
# recovery) — the guarantee is that an UNSEEN edit can never be force-crushed.
# ---------------------------------------------------------------------------
class TestForceCAS:
    def _drifted_remote(self, updated_on="2025-01-12 10:00:00"):
        return {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 0; // someone else's edit",
            "sys_updated_on": updated_on,
            "sys_updated_by": "alice",
            "sys_created_by": "alice",
            "sys_scope": "global",
        }

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_conflict_hint_names_cas_param_with_exact_version(
        self, mock_fetch, mock_config, mock_auth, widget_root
    ):
        mock_fetch.return_value = self._drifted_remote()
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"

        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(script))
        )
        assert result["error"] in ("CONFLICT", "CONFLICT_OTHER_USER")
        assert "confirm_overwrite_updated_on='2025-01-12 10:00:00'" in result["message"]

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_force_with_matching_confirm_pushes(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, widget_root
    ):
        mock_fetch.side_effect = [
            self._drifted_remote(),
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",  # landed = local
                "sys_updated_on": "2025-01-12 11:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"

        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(
                path=str(script),
                force=True,
                confirm_overwrite_updated_on="2025-01-12 10:00:00",
            ),
        )
        assert result["success"] is True
        mock_update.assert_called_once()

    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_force_with_stale_confirm_reblocks(
        self, mock_fetch, mock_update, mock_config, mock_auth, widget_root
    ):
        # The server moved AGAIN after the review the caller approved.
        mock_fetch.return_value = self._drifted_remote(updated_on="2025-01-12 12:34:56")
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"

        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(
                path=str(script),
                force=True,
                confirm_overwrite_updated_on="2025-01-12 10:00:00",
            ),
        )
        assert result["error"] == "FORCE_CONFIRM_STALE"
        assert "2025-01-12 12:34:56" in result["message"]
        assert result["diffs"], "stale-confirm block must carry the fresh diff"
        mock_update.assert_not_called()

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_force_without_confirm_still_works(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, widget_root
    ):
        # Back-compat escape hatch: bare force=true keeps working.
        mock_fetch.side_effect = [
            self._drifted_remote(),
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",  # landed = local
                "sys_updated_on": "2025-01-12 11:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}
        script = widget_root / "global" / "sp_widget" / "my-widget" / "script.js"

        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(script), force=True)
        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Registry binding regression: a helper inserted between @register_tool and its
# function once hijacked the registration (v1.18.28) — pin name == callable.
# ---------------------------------------------------------------------------
class TestRegistryBinding:
    def test_every_registered_tool_binds_its_own_function(self):
        from servicenow_mcp.utils.registry import discover_tools

        mismatches = {
            name: func.__name__
            for name, (func, *_rest) in discover_tools().items()
            if func.__name__ != name
        }
        assert mismatches == {}
