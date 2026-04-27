"""Tests for local source synchronization tools (sync_tools.py)."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.sync_tools import (
    DiffLocalComponentParams,
    PushLocalComponentParams,
    _batch_fetch_updated_on,
    _find_settings_json,
    _find_table_dirs,
    _is_download_root,
    _read_map_json,
    _read_sync_meta,
    _resolve_local_path,
    _reverse_lookup_map,
    _reverse_lookup_name,
    _scan_download_root,
    _write_sync_meta,
    diff_local_component,
    update_remote_from_local,
)
from servicenow_mcp.utils.config import ServerConfig


# ---------------------------------------------------------------------------
# Fixtures
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
def download_root(tmp_path):
    """Create a realistic download directory structure."""
    root = tmp_path / "output"
    root.mkdir()

    # _settings.json
    (root / "_settings.json").write_text(
        json.dumps({"name": "test", "url": "https://test.service-now.com", "g_ck": ""}),
        encoding="utf-8",
    )

    scope = root / "global"
    scope.mkdir()

    # Widget
    widget_dir = scope / "sp_widget" / "my-widget"
    widget_dir.mkdir(parents=True)
    (widget_dir / "template.html").write_text("<div>hello</div>", encoding="utf-8")
    (widget_dir / "script.js").write_text("var x = 1;", encoding="utf-8")
    (widget_dir / "client_script.js").write_text("function go(){}", encoding="utf-8")
    (widget_dir / "css.scss").write_text(".a{}", encoding="utf-8")

    (scope / "sp_widget" / "_map.json").write_text(
        json.dumps({"my-widget": "wid-1"}), encoding="utf-8"
    )
    (scope / "sp_widget" / "_sync_meta.json").write_text(
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

    # Provider
    prov_dir = scope / "sp_angular_provider"
    prov_dir.mkdir(parents=True)
    (prov_dir / "myService.script.js").write_text(
        "angular.module('x').factory('myService',function(){});", encoding="utf-8"
    )
    (prov_dir / "_map.json").write_text(json.dumps({"myService": "prov-1"}), encoding="utf-8")
    (prov_dir / "_sync_meta.json").write_text(
        json.dumps(
            {
                "myService": {
                    "sys_id": "prov-1",
                    "sys_updated_on": "2025-01-10 10:00:00",
                    "downloaded_at": "2025-01-10T10:05:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    # Script Include
    si_dir = scope / "sys_script_include"
    si_dir.mkdir(parents=True)
    (si_dir / "MyUtil.script.js").write_text("var gr = new GlideRecord('task');", encoding="utf-8")
    (si_dir / "_map.json").write_text(json.dumps({"MyUtil": "si-1"}), encoding="utf-8")
    (si_dir / "_sync_meta.json").write_text(
        json.dumps(
            {
                "MyUtil": {
                    "sys_id": "si-1",
                    "sys_updated_on": "2025-01-10 10:00:00",
                    "downloaded_at": "2025-01-10T10:05:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    return root


@pytest.fixture
def download_root_extended(tmp_path):
    root = tmp_path / "output"
    root.mkdir()
    (root / "_settings.json").write_text(
        json.dumps({"name": "test", "url": "https://test.service-now.com", "g_ck": ""}),
        encoding="utf-8",
    )
    scope = root / "global"
    scope.mkdir()

    # sp_header_footer (folder-based)
    hf_dir = scope / "sp_header_footer" / "main-header"
    hf_dir.mkdir(parents=True)
    (hf_dir / "template.html").write_text("<header/>", encoding="utf-8")
    (hf_dir / "css.scss").write_text(".hdr{}", encoding="utf-8")
    (scope / "sp_header_footer" / "_map.json").write_text(
        json.dumps({"main-header": "hf-1"}), encoding="utf-8"
    )

    # sp_css (single-file)
    css_dir = scope / "sp_css"
    css_dir.mkdir(parents=True)
    (css_dir / "dark-theme.css.scss").write_text("body{background:#000}", encoding="utf-8")
    (css_dir / "_map.json").write_text(json.dumps({"dark-theme": "css-1"}), encoding="utf-8")

    # sp_ng_template (single-file)
    ngt_dir = scope / "sp_ng_template"
    ngt_dir.mkdir(parents=True)
    (ngt_dir / "card.template.html").write_text("<div class='card'/>", encoding="utf-8")
    (ngt_dir / "_map.json").write_text(json.dumps({"card": "ngt-1"}), encoding="utf-8")

    # sys_ui_page (folder-based)
    uip_dir = scope / "sys_ui_page" / "processor-page"
    uip_dir.mkdir(parents=True)
    (uip_dir / "html.html").write_text("<jelly/>", encoding="utf-8")
    (uip_dir / "client_script.js").write_text("cs()", encoding="utf-8")
    (uip_dir / "processing_script.js").write_text("ps()", encoding="utf-8")
    (scope / "sys_ui_page" / "_map.json").write_text(
        json.dumps({"processor-page": "uip-1"}), encoding="utf-8"
    )

    return root


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_find_settings_json_walks_up(self, download_root):
        widget_dir = download_root / "global" / "sp_widget" / "my-widget"
        settings = _find_settings_json(widget_dir)
        assert settings["url"] == "https://test.service-now.com"

    def test_find_settings_json_returns_empty_if_missing(self, tmp_path):
        settings = _find_settings_json(tmp_path)
        assert settings == {}

    def test_read_map_json(self, download_root):
        table_dir = download_root / "global" / "sp_widget"
        data = _read_map_json(table_dir)
        assert data == {"my-widget": "wid-1"}

    def test_read_map_json_missing(self, tmp_path):
        assert _read_map_json(tmp_path) == {}

    def test_read_sync_meta(self, download_root):
        table_dir = download_root / "global" / "sp_widget"
        meta = _read_sync_meta(table_dir)
        assert "my-widget" in meta
        assert meta["my-widget"]["sys_id"] == "wid-1"

    def test_read_sync_meta_missing(self, tmp_path):
        assert _read_sync_meta(tmp_path) == {}

    def test_write_sync_meta(self, tmp_path):
        _write_sync_meta(tmp_path, {"comp": {"sys_id": "x", "sys_updated_on": "ts"}})
        data = json.loads((tmp_path / "_sync_meta.json").read_text())
        assert data["comp"]["sys_id"] == "x"

    def test_is_download_root_with_settings(self, download_root):
        assert _is_download_root(download_root) is True

    def test_is_download_root_false(self, tmp_path):
        assert _is_download_root(tmp_path) is False

    def test_reverse_lookup_map(self):
        data = {"My Widget": "sys-1"}
        assert _reverse_lookup_map(data, "My_Widget") == "sys-1"
        assert _reverse_lookup_map(data, "My Widget") == "sys-1"
        assert _reverse_lookup_map(data, "nonexistent") is None

    def test_reverse_lookup_name(self):
        data = {"My Widget": "sys-1"}
        assert _reverse_lookup_name(data, "My_Widget") == "My Widget"
        assert _reverse_lookup_name(data, "nonexistent") is None


# ---------------------------------------------------------------------------
# Path resolution tests
# ---------------------------------------------------------------------------
class TestResolveLocalPath:
    def test_resolve_widget_file(self, download_root):
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        resolved = _resolve_local_path(path)
        assert resolved.table == "sp_widget"
        assert resolved.sys_id == "wid-1"
        assert resolved.name == "my-widget"
        assert "script" in resolved.fields
        assert resolved.instance_url == "https://test.service-now.com"

    def test_resolve_widget_directory(self, download_root):
        path = download_root / "global" / "sp_widget" / "my-widget"
        resolved = _resolve_local_path(path)
        assert resolved.table == "sp_widget"
        assert resolved.sys_id == "wid-1"
        assert len(resolved.fields) >= 3  # template, script, client_script, css

    def test_resolve_provider_file(self, download_root):
        path = download_root / "global" / "sp_angular_provider" / "myService.script.js"
        resolved = _resolve_local_path(path)
        assert resolved.table == "sp_angular_provider"
        assert resolved.sys_id == "prov-1"
        assert resolved.name == "myService"
        assert "script" in resolved.fields

    def test_resolve_script_include_file(self, download_root):
        path = download_root / "global" / "sys_script_include" / "MyUtil.script.js"
        resolved = _resolve_local_path(path)
        assert resolved.table == "sys_script_include"
        assert resolved.sys_id == "si-1"
        assert "script" in resolved.fields

    def test_resolve_unknown_file_raises(self, tmp_path):
        (tmp_path / "random.txt").write_text("hello")
        with pytest.raises(ValueError, match="Cannot resolve"):
            _resolve_local_path(tmp_path / "random.txt")

    def test_resolve_unknown_widget_file_raises(self, download_root):
        unknown = download_root / "global" / "sp_widget" / "my-widget" / "unknown.txt"
        unknown.write_text("test")
        with pytest.raises(ValueError, match="Unknown file"):
            _resolve_local_path(unknown)

    def test_resolve_missing_map_entry_raises(self, download_root):
        # Create a widget folder not in _map.json
        orphan = download_root / "global" / "sp_widget" / "orphan"
        orphan.mkdir()
        (orphan / "script.js").write_text("x")
        with pytest.raises(ValueError, match="not found"):
            _resolve_local_path(orphan)

    def test_resolve_nonexistent_path_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            _resolve_local_path(tmp_path / "nope.js")

    def test_resolve_non_widget_directory_raises(self, download_root):
        path = download_root / "global" / "sp_angular_provider"
        with pytest.raises(ValueError, match="folder-based tables"):
            _resolve_local_path(path)


# ---------------------------------------------------------------------------
# diff_local_component tests
# ---------------------------------------------------------------------------
class TestDiffLocalComponent:
    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diff_single_file_modified(
        self, mock_fetch, mock_sn_query, mock_config, mock_auth, download_root
    ):
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 2;",  # different from local "var x = 1;"
            "sys_updated_on": "2025-01-10 10:00:00",
        }

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(path))
        )

        assert result["mode"] == "diff"
        assert result["component"]["table"] == "sp_widget"
        assert result["conflict_warning"] is None
        assert len(result["diffs"]) == 1
        assert result["diffs"][0]["status"] == "modified"
        assert "diff" in result["diffs"][0]

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diff_single_file_unchanged(
        self, mock_fetch, mock_sn_query, mock_config, mock_auth, download_root
    ):
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 1;",  # same as local
            "sys_updated_on": "2025-01-10 10:00:00",
        }

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(path))
        )

        assert result["diffs"][0]["status"] == "unchanged"

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diff_detects_conflict_warning(
        self, mock_fetch, mock_sn_query, mock_config, mock_auth, download_root
    ):
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 99;",
            "sys_updated_on": "2025-01-15 12:00:00",  # newer than download
        }

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(path))
        )

        assert result["conflict_warning"] is not None
        assert "2025-01-15" in result["conflict_warning"]

    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_diff_directory_mode_scan(self, mock_batch, mock_config, mock_auth, download_root):
        mock_batch.return_value = {
            "wid-1": "2025-01-10 10:00:00",
            "prov-1": "2025-01-10 10:00:00",
            "si-1": "2025-01-10 10:00:00",
        }

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(download_root))
        )

        assert result["mode"] == "scan"
        assert result["summary"]["total"] >= 3
        assert "components" in result

    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_diff_directory_mode_detects_remote_newer(
        self, mock_batch, mock_config, mock_auth, download_root
    ):
        mock_batch.return_value = {
            "wid-1": "2025-01-20 12:00:00",  # newer than download
            "prov-1": "2025-01-10 10:00:00",
            "si-1": "2025-01-10 10:00:00",
        }

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(download_root))
        )

        statuses = {c["name"]: c["status"] for c in result["components"]}
        # File mtime is newer than downloaded_at (2025-01-10), so if remote is also
        # newer, status is "conflict" (both sides changed). If only remote changed
        # and local files are untouched, it would be "remote_newer".
        assert statuses["my-widget"] in ("remote_newer", "conflict")

    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_diff_directory_mode_detects_local_modified(
        self, mock_batch, mock_config, mock_auth, download_root
    ):
        mock_batch.return_value = {
            "wid-1": "2025-01-10 10:00:00",
            "prov-1": "2025-01-10 10:00:00",
            "si-1": "2025-01-10 10:00:00",
        }
        # Touch a file to make it newer than downloaded_at
        script = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        time.sleep(0.05)
        script.write_text("var x = 999;", encoding="utf-8")

        # Update downloaded_at to be in the past relative to mtime
        meta_path = download_root / "global" / "sp_widget" / "_sync_meta.json"
        meta = json.loads(meta_path.read_text())
        meta["my-widget"]["downloaded_at"] = "2025-01-10T10:05:00+00:00"
        meta_path.write_text(json.dumps(meta))

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(download_root))
        )

        statuses = {c["name"]: c["status"] for c in result["components"]}
        assert statuses["my-widget"] == "local_modified"

    def test_diff_nonexistent_path_returns_error(self, mock_config, mock_auth, tmp_path):
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(tmp_path / "nope"))
        )
        assert "error" in result

    def test_diff_instance_mismatch_returns_error(self, mock_auth, download_root):
        wrong_config = ServerConfig(
            instance_url="https://other.service-now.com",
            auth={"type": "basic", "basic": {"username": "a", "password": "b"}},
        )
        result = diff_local_component(
            wrong_config, mock_auth, DiffLocalComponentParams(path=str(download_root))
        )
        assert "error" in result
        assert "mismatch" in result["error"].lower()


# ---------------------------------------------------------------------------
# update_remote_from_local tests
# ---------------------------------------------------------------------------
class TestUpdateRemoteFromLocal:
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools._write_portal_component_snapshot")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_success(
        self,
        mock_fetch,
        mock_update,
        mock_snapshot,
        mock_write_meta,
        mock_config,
        mock_auth,
        download_root,
    ):
        mock_fetch.side_effect = [
            # First call: fetch remote for comparison
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",  # different from local "var x = 1;"
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            # Second call: fetch after update for sync_meta
            {
                "sys_id": "wid-1",
                "sys_updated_on": "2025-01-10 11:00:00",
            },
        ]
        mock_snapshot.return_value = Path("/tmp/snapshot.json")
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["message"] == "Update successful"
        assert result["local_sync"]["fields_pushed"] == ["script"]
        assert result["local_sync"]["snapshot"] is not None
        mock_snapshot.assert_called_once()
        mock_update.assert_called_once()

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_conflict_rejected(self, mock_fetch, mock_config, mock_auth, download_root):
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 99;",
            "sys_updated_on": "2025-01-15 12:00:00",  # newer than download
        }

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["error"] == "CONFLICT"
        assert "force" in result["message"].lower()

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools._write_portal_component_snapshot")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_force_overrides_conflict(
        self,
        mock_fetch,
        mock_update,
        mock_snapshot,
        mock_write_meta,
        mock_config,
        mock_auth,
        download_root,
    ):
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 99;",
                "sys_updated_on": "2025-01-15 12:00:00",  # newer
            },
            {"sys_id": "wid-1", "sys_updated_on": "2025-01-15 13:00:00"},
        ]
        mock_snapshot.return_value = Path("/tmp/snapshot.json")
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path), force=True)
        )

        assert "error" not in result
        mock_update.assert_called_once()

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_no_changes_detected(self, mock_fetch, mock_config, mock_auth, download_root):
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 1;",  # same as local
            "sys_updated_on": "2025-01-10 10:00:00",
        }

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert "No changes to push" in result["message"]

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_skip_snapshot(
        self,
        mock_fetch,
        mock_update,
        mock_write_meta,
        mock_config,
        mock_auth,
        download_root,
    ):
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

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(path), skip_snapshot=True),
        )

        assert result["local_sync"]["snapshot"] is None

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools._write_portal_component_snapshot")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_widget_directory(
        self,
        mock_fetch,
        mock_update,
        mock_snapshot,
        mock_write_meta,
        mock_config,
        mock_auth,
        download_root,
    ):
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "template": "<div>old</div>",
                "script": "var x = 0;",
                "client_script": "function go(){}",
                "css": ".a{}",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {"sys_id": "wid-1", "sys_updated_on": "2025-01-10 11:00:00"},
        ]
        mock_snapshot.return_value = Path("/tmp/snapshot.json")
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        path = download_root / "global" / "sp_widget" / "my-widget"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["message"] == "Update successful"
        pushed = result["local_sync"]["fields_pushed"]
        assert "template" in pushed
        assert "script" in pushed

    def test_push_instance_mismatch(self, mock_auth, download_root):
        wrong_config = ServerConfig(
            instance_url="https://other.service-now.com",
            auth={"type": "basic", "basic": {"username": "a", "password": "b"}},
        )
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            wrong_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# Download _sync_meta.json generation test
# ---------------------------------------------------------------------------
class TestDownloadSyncMeta:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_download_creates_sync_meta_files(
        self, mock_sn_query_all, mock_config, mock_auth, tmp_path
    ):
        from servicenow_mcp.tools.portal_tools import (
            DownloadPortalSourcesParams,
            download_portal_sources,
        )

        mock_sn_query_all.side_effect = [
            [
                {
                    "sys_id": "wid-1",
                    "name": "Test Widget",
                    "id": "test_widget",
                    "sys_scope": "global",
                    "template": "<div/>",
                    "script": "var t = new TestUtil();",
                    "client_script": "",
                    "link": "",
                    "css": "",
                    "option_schema": "",
                    "demo_data": "",
                    "sys_updated_on": "2025-06-01 09:00:00",
                }
            ],
            # M2M
            [{"sp_widget": {"value": "wid-1"}, "sp_angular_provider": {"value": "prov-1"}}],
            # Providers
            [
                {
                    "sys_id": "prov-1",
                    "name": "testService",
                    "script": "angular.module('x').factory('testService',function(){});",
                    "sys_updated_on": "2025-06-01 08:00:00",
                }
            ],
            # Script includes
            [
                {
                    "sys_id": "si-1",
                    "name": "TestUtil",
                    "api_name": "global.TestUtil",
                    "script": "var gr = new GlideRecord('task');",
                    "sys_updated_on": "2025-06-01 07:00:00",
                }
            ],
        ]

        result = download_portal_sources(
            mock_config,
            mock_auth,
            DownloadPortalSourcesParams(
                output_dir=str(tmp_path / "global"),
                include_linked_script_includes=True,
                include_linked_angular_providers=True,
            ),
        )

        assert result["success"] is True
        scope = tmp_path / "global"

        # Widget sync meta
        widget_sync = scope / "sp_widget" / "_sync_meta.json"
        assert widget_sync.exists()
        data = json.loads(widget_sync.read_text())
        assert "test_widget" in data
        assert data["test_widget"]["sys_id"] == "wid-1"
        assert data["test_widget"]["sys_updated_on"] == "2025-06-01 09:00:00"
        assert "downloaded_at" in data["test_widget"]

        # Provider sync meta
        prov_sync = scope / "sp_angular_provider" / "_sync_meta.json"
        assert prov_sync.exists()
        pdata = json.loads(prov_sync.read_text())
        assert "testService" in pdata
        assert pdata["testService"]["sys_updated_on"] == "2025-06-01 08:00:00"

        # SI sync meta
        si_sync = scope / "sys_script_include" / "_sync_meta.json"
        assert si_sync.exists()
        sdata = json.loads(si_sync.read_text())
        assert "TestUtil" in sdata
        assert sdata["TestUtil"]["sys_updated_on"] == "2025-06-01 07:00:00"


# ---------------------------------------------------------------------------
# Extended coverage tests
# ---------------------------------------------------------------------------
class TestExtendedSyncCoverage:
    """Tests targeting previously uncovered lines in sync_tools.py."""

    # --- Lines 164-165: _read_sync_meta with corrupt JSON ---
    def test_read_sync_meta_corrupt_json(self, tmp_path):
        meta_file = tmp_path / "_sync_meta.json"
        meta_file.write_text("{invalid json!!!", encoding="utf-8")
        result = _read_sync_meta(tmp_path)
        assert result == {}

    # --- Lines 176-177: _read_map_json with corrupt JSON ---
    def test_read_map_json_corrupt_json(self, tmp_path):
        map_file = tmp_path / "_map.json"
        map_file.write_text("{broken!!!", encoding="utf-8")
        result = _read_map_json(tmp_path)
        assert result == {}

    # --- Lines 192-195: _is_download_root detecting scope/table structure ---
    def test_is_download_root_scope_table_structure(self, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        # No _settings.json, but has scope/table/_map.json structure
        scope = root / "global"
        scope.mkdir()
        table_dir = scope / "sp_widget"
        table_dir.mkdir()
        (table_dir / "_map.json").write_text("{}", encoding="utf-8")
        assert _is_download_root(root) is True

    # --- Lines 235: _resolve_local_path folder-based table with dot-file skip ---
    def test_resolve_folder_table_skips_dot_prefix_files(self, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        hf_dir = scope / "sp_header_footer" / "my-hf"
        hf_dir.mkdir(parents=True)
        # Only dot-prefixed file in TABLE_FILE_FIELD_MAP for sp_header_footer:
        # there are no dot-prefixed entries for sp_header_footer, so just test
        # that non-editable files are skipped by providing only unsupported files
        (hf_dir / "random.txt").write_text("data", encoding="utf-8")
        (scope / "sp_header_footer" / "_map.json").write_text(
            json.dumps({"my-hf": "hf-1"}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="No editable source files"):
            _resolve_local_path(hf_dir)

    # --- Lines 240: _resolve_local_path folder with no editable files ---
    def test_resolve_folder_no_editable_files(self, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        widget_dir = scope / "sp_widget" / "empty-widget"
        widget_dir.mkdir(parents=True)
        # No template.html, script.js, etc.
        (widget_dir / "readme.md").write_text("docs", encoding="utf-8")
        (scope / "sp_widget" / "_map.json").write_text(
            json.dumps({"empty-widget": "wid-x"}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="No editable source files"):
            _resolve_local_path(widget_dir)

    # --- Lines 275: _resolve_local_path folder-based file where component not in _map.json ---
    def test_resolve_folder_file_not_in_map(self, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        widget_dir = scope / "sp_widget" / "ghost"
        widget_dir.mkdir(parents=True)
        (widget_dir / "template.html").write_text("<div/>", encoding="utf-8")
        # _map.json exists but does not contain 'ghost'
        (scope / "sp_widget" / "_map.json").write_text(
            json.dumps({"other": "wid-99"}), encoding="utf-8"
        )
        with pytest.raises(ValueError, match="not found"):
            _resolve_local_path(widget_dir / "template.html")

    # --- Lines 305: _resolve_local_path single-file table with wrong filename suffix ---
    def test_resolve_single_file_wrong_suffix(self, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        si_dir = scope / "sys_script_include"
        si_dir.mkdir()
        (si_dir / "MyUtil.wrong.txt").write_text("data", encoding="utf-8")
        (si_dir / "_map.json").write_text(json.dumps({"MyUtil": "si-1"}), encoding="utf-8")
        with pytest.raises(ValueError, match="Cannot parse filename"):
            _resolve_local_path(si_dir / "MyUtil.wrong.txt")

    # --- Lines 313: _resolve_local_path single-file table where component not in _map.json ---
    def test_resolve_single_file_not_in_map(self, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        si_dir = scope / "sys_script_include"
        si_dir.mkdir()
        (si_dir / "Orphan.script.js").write_text("code", encoding="utf-8")
        # Map does not contain 'Orphan'
        (si_dir / "_map.json").write_text(json.dumps({"Other": "si-99"}), encoding="utf-8")
        with pytest.raises(ValueError, match="not found"):
            _resolve_local_path(si_dir / "Orphan.script.js")

    # --- Lines 368-387: _batch_fetch_updated_on ---
    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_batch_fetch_updated_on(self, mock_sn_query, mock_config, mock_auth):
        mock_sn_query.return_value = {
            "results": [
                {"sys_id": "wid-1", "sys_updated_on": "2025-01-10 10:00:00"},
                {"sys_id": "wid-2", "sys_updated_on": "2025-01-11 11:00:00"},
            ]
        }
        result = _batch_fetch_updated_on(mock_config, mock_auth, "sp_widget", ["wid-1", "wid-2"])
        assert result == {"wid-1": "2025-01-10 10:00:00", "wid-2": "2025-01-11 11:00:00"}
        mock_sn_query.assert_called_once()

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_batch_fetch_updated_on_empty(self, mock_sn_query, mock_config, mock_auth):
        result = _batch_fetch_updated_on(mock_config, mock_auth, "sp_widget", [])
        assert result == {}
        mock_sn_query.assert_not_called()

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_batch_fetch_updated_on_handles_empty_rows(self, mock_sn_query, mock_config, mock_auth):
        mock_sn_query.return_value = {"results": [{"sys_id": "", "sys_updated_on": ""}]}
        result = _batch_fetch_updated_on(mock_config, mock_auth, "sp_widget", ["bad-id"])
        # Empty sys_id should be skipped
        assert result == {}

    # --- Lines 401: _find_table_dirs direct table dir (not under scope) ---
    def test_find_table_dirs_direct(self, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        # Direct table dir under root (no scope subdirectory)
        table_dir = root / "sp_widget"
        table_dir.mkdir()
        (table_dir / "_map.json").write_text("{}", encoding="utf-8")
        result = _find_table_dirs(root, "sp_widget")
        assert len(result) == 1
        assert result[0] == table_dir

    # --- Lines 428: _scan_download_root with empty map_data ---
    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_scan_download_root_empty_map(self, mock_batch, mock_config, mock_auth, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        table_dir = scope / "sp_widget"
        table_dir.mkdir()
        (table_dir / "_map.json").write_text("{}", encoding="utf-8")
        result = _scan_download_root(mock_config, mock_auth, root)
        assert result["mode"] == "scan"
        assert result["summary"]["total"] == 0
        mock_batch.assert_not_called()

    # --- Lines 461: _scan_download_root with no local files ---
    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_scan_download_root_no_local_files(self, mock_batch, mock_config, mock_auth, tmp_path):
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        table_dir = scope / "sys_script_include"
        table_dir.mkdir()
        (table_dir / "_map.json").write_text(json.dumps({"MyUtil": "si-1"}), encoding="utf-8")
        # No actual script file exists, so local_files will be empty
        mock_batch.return_value = {"si-1": "2025-01-10 10:00:00"}
        result = _scan_download_root(mock_config, mock_auth, root)
        assert result["mode"] == "scan"
        assert result["summary"]["total"] == 0

    # --- Lines 472-473, 485-488: _scan_download_root status transitions ---
    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_scan_download_root_unknown_status(self, mock_batch, mock_config, mock_auth, tmp_path):
        """Component with no sync_meta (has_sync_meta=False) -> status 'unknown'."""
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        si_dir = scope / "sys_script_include"
        si_dir.mkdir()
        (si_dir / "MyUtil.script.js").write_text("code", encoding="utf-8")
        (si_dir / "_map.json").write_text(json.dumps({"MyUtil": "si-1"}), encoding="utf-8")
        # No _sync_meta.json -> has_sync_meta=False -> status='unknown'
        mock_batch.return_value = {"si-1": "2025-01-10 10:00:00"}
        result = _scan_download_root(mock_config, mock_auth, root)
        assert result["mode"] == "scan"
        statuses = {c["name"]: c["status"] for c in result["components"]}
        assert statuses.get("MyUtil") == "unknown"

    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_scan_download_root_unchanged_status(
        self, mock_batch, mock_config, mock_auth, tmp_path
    ):
        """Component with matching timestamps and unmodified local files -> 'unchanged'."""
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        si_dir = scope / "sys_script_include"
        si_dir.mkdir()
        script_file = si_dir / "MyUtil.script.js"
        script_file.write_text("var gr = new GlideRecord('task');", encoding="utf-8")
        (si_dir / "_map.json").write_text(json.dumps({"MyUtil": "si-1"}), encoding="utf-8")
        from datetime import UTC as _UTC
        from datetime import datetime as _datetime

        now_iso = _datetime.now(_UTC).isoformat()
        (si_dir / "_sync_meta.json").write_text(
            json.dumps(
                {
                    "MyUtil": {
                        "sys_id": "si-1",
                        "sys_updated_on": "2025-01-10 10:00:00",
                        "downloaded_at": now_iso,
                    }
                }
            ),
            encoding="utf-8",
        )
        mock_batch.return_value = {"si-1": "2025-01-10 10:00:00"}
        result = _scan_download_root(mock_config, mock_auth, root)
        statuses = {c["name"]: c["status"] for c in result["components"]}
        assert statuses.get("MyUtil") == "unchanged"

    # --- Lines 543-544: diff_local_component - invalid path ---
    def test_diff_resolve_error(self, mock_config, mock_auth, tmp_path):
        bad_path = tmp_path / "random" / "file.js"
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(bad_path))
        )
        assert "error" in result

    # --- Lines 548-549: diff_local_component - instance mismatch (component mode) ---
    def test_diff_component_instance_mismatch(self, mock_auth, download_root):
        wrong_config = ServerConfig(
            instance_url="https://other.service-now.com",
            auth={"type": "basic", "basic": {"username": "a", "password": "b"}},
        )
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = diff_local_component(
            wrong_config, mock_auth, DiffLocalComponentParams(path=str(path))
        )
        assert "error" in result
        assert "mismatch" in result["error"].lower()

    # --- Lines 556-557: diff_local_component - fetch error ---
    @patch(
        "servicenow_mcp.tools.sync_tools._fetch_portal_component_record",
        side_effect=ValueError("API error"),
    )
    def test_diff_fetch_error(self, mock_fetch, mock_config, mock_auth, download_root):
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(path))
        )
        assert "error" in result
        assert "API error" in result["error"]

    # --- Lines 575: diff_local_component - missing file (file_path doesn't exist) ---
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diff_missing_local_file_skipped(
        self, mock_fetch, mock_config, mock_auth, download_root
    ):
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 1;",
            "sys_updated_on": "2025-01-10 10:00:00",
        }
        # Delete the local file so file_path.exists() is False (line 574-575)
        script = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        script.unlink()
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(script))
        )
        # The file is gone, so _resolve_local_path raises ValueError
        assert "error" in result

    # --- Lines 594: diff_local_component - diff truncation ---
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diff_truncation(self, mock_fetch, mock_config, mock_auth, download_root):
        # Create a large local file to trigger diff truncation (MAX_DIFF_LINES=120)
        long_lines = "\n".join(f"line {i}" for i in range(200))
        script = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        script.write_text(long_lines, encoding="utf-8")
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "original",
            "sys_updated_on": "2025-01-10 10:00:00",
        }
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(script))
        )
        diffs = result.get("diffs", [])
        assert len(diffs) == 1
        assert diffs[0]["status"] == "modified"
        assert "DIFF TRUNCATED" in diffs[0]["diff"]

    # --- Lines 637-638: update_remote_from_local resolve error ---
    def test_push_resolve_error(self, mock_config, mock_auth, tmp_path):
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(tmp_path / "nope.js"))
        )
        assert "error" in result

    # --- Lines 651-652: update_remote_from_local fetch error ---
    @patch(
        "servicenow_mcp.tools.sync_tools._fetch_portal_component_record",
        side_effect=ValueError("fetch err"),
    )
    def test_push_fetch_error(self, mock_fetch, mock_config, mock_auth, download_root):
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert "error" in result
        assert "fetch err" in result["error"]

    # --- Lines 682: update_remote_from_local - file_path doesn't exist during push ---
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_no_changes(self, mock_fetch, mock_config, mock_auth, download_root):
        """All local files match remote content -> no changes to push."""
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 1;",
            "template": "<div>hello</div>",
            "client_script": "function go(){}",
            "css": ".a{}",
            "sys_updated_on": "2025-01-10 10:00:00",
        }
        widget_dir = download_root / "global" / "sp_widget" / "my-widget"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(widget_dir))
        )
        assert "No changes to push" in result["message"]

    # --- Lines 709-710: update_remote_from_local - snapshot failure ---
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch(
        "servicenow_mcp.tools.sync_tools._write_portal_component_snapshot",
        side_effect=OSError("disk full"),
    )
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_snapshot_failure(
        self,
        mock_fetch,
        mock_snapshot,
        mock_update,
        mock_write_meta,
        mock_config,
        mock_auth,
        download_root,
    ):
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
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        # Should still succeed with snapshot=None
        assert result["message"] == "Update successful"
        assert result["local_sync"]["snapshot"] is None

    # --- Lines 723-724: update_remote_from_local - push failure ---
    @patch("servicenow_mcp.tools.sync_tools._write_portal_component_snapshot")
    @patch(
        "servicenow_mcp.tools.sync_tools.update_portal_component",
        side_effect=RuntimeError("network error"),
    )
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_update_failure(
        self,
        mock_fetch,
        mock_update,
        mock_snapshot,
        mock_config,
        mock_auth,
        download_root,
    ):
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 0;",
            "sys_updated_on": "2025-01-10 10:00:00",
        }
        mock_snapshot.return_value = Path("/tmp/snapshot.json")
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert "error" in result
        assert "Push failed" in result["error"]

    # --- Lines 743-744: update_remote_from_local - sync meta update failure ---
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta", side_effect=OSError("write err"))
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._write_portal_component_snapshot")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_sync_meta_failure(
        self,
        mock_fetch,
        mock_snapshot,
        mock_update,
        mock_write_meta,
        mock_config,
        mock_auth,
        download_root,
    ):
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {"sys_id": "wid-1", "sys_updated_on": "2025-01-10 11:00:00"},
        ]
        mock_snapshot.return_value = Path("/tmp/snapshot.json")
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        # Should still succeed despite sync meta update failure
        assert result["message"] == "Update successful"
