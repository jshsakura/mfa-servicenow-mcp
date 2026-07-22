"""Integration tests for the live-anchored sync model (utils/sync_anchor.py).

The frozen _baseline/ 3-way is gone; drift/diff/verdict/push decide from the live
sys_mod_count + per-field content-sha anchor in _sync_meta. reconcile_field's
two-copy behavior is unit-tested in test_sync_anchor.py; here we pin the sync_tools
integrations:
- diff_local_component separates YOUR edits from the SERVER's changes via the anchor.
- a .remote server-mirror sidecar is rejected as a push target.
- a successful push records the new anchor and clears a resolved mirror.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.sync_tools import (
    DiffLocalComponentParams,
    PushLocalComponentParams,
    _read_sync_meta,
    _resolve_local_path,
    _write_sync_meta,
    diff_local_component,
    update_remote_from_local,
)
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.sync_anchor import field_sha, mirror_path_for


def _seed_anchor(script_path, body):
    """Record the last-known-good per-field content-sha anchor in _sync_meta — the
    new drift/edit anchor that replaces the frozen _baseline/ snapshot for the
    sync_tools integration tests."""
    table_dir = script_path.parent.parent
    name = script_path.parent.name
    field = script_path.stem
    meta = _read_sync_meta(table_dir)
    entry = dict(meta.get(name, {"sys_id": "wid-1", "sys_updated_on": "2025-01-10 10:00:00"}))
    shas = dict(entry.get("field_shas", {}))
    shas[field] = field_sha(body)
    entry["field_shas"] = shas
    meta[name] = entry
    _write_sync_meta(table_dir, meta)


# ---------------------------------------------------------------------------
# Artifact recognition (scanner skip / push rejection)
# ---------------------------------------------------------------------------
class TestArtifacts:
    def test_resolve_local_path_rejects_mirror_sidecar(self, tmp_path):
        sidecar = tmp_path / "sp_widget" / "w" / "script.remote.js"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="mirror sidecar"):
            _resolve_local_path(sidecar)


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
        _seed_anchor(script, "var x = 0;")
        sidecar = mirror_path_for(script)
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
        # The push recorded the pushed body as the new anchor and cleared the mirror.
        assert not sidecar.exists()
        anchor = _read_sync_meta(script.parent.parent)["my-widget"]["field_shas"]["script"]
        assert anchor == field_sha("var x = 1;")


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
        _seed_anchor(script, "var x = 0;")  # local "var x = 1;" = YOUR edit
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
        _seed_anchor(script, "var x = 0;")
        sidecar = mirror_path_for(script)
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
def _verdict_chunk_make_request(rows):
    """make_request side_effect for the verdict scan's per-chunk fallback.

    The Batch API POST is forced to fail (500) so the scan falls back to the
    per-chunk direct GET, which now reads RAW/untruncated (a >50k body must not
    be clipped by sn_query's truncate_results). The GET returns the given rows.
    """

    def _side(method, url, **kwargs):
        resp = MagicMock()
        if method == "GET":
            resp.status_code = 200
            resp.json.return_value = {"result": list(rows)}
        else:  # Batch API POST → force per-chunk fallback
            resp.status_code = 500
            resp.text = "batch disabled in test"
        return resp

    return _side


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
        _seed_anchor(script, "var x = 0;")  # local edit vs unmoved server
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
        _seed_anchor(script, "var x = 1;")
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
        _seed_anchor(script, "var x = 1;")  # clean local
        mock_auth.make_request.side_effect = _verdict_chunk_make_request(
            [self._remote("var x = 2; // server moved", mod_count="9")]
        )

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
        mock_auth.make_request.side_effect = _verdict_chunk_make_request(
            [self._remote("var x = 1;")]
        )
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
        mock_auth.make_request.side_effect = _verdict_chunk_make_request(
            [self._remote("var x = 1;")]
        )
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
        mock_auth.make_request.side_effect = _verdict_chunk_make_request([])
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
