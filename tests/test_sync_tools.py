"""Tests for local source synchronization tools (sync_tools.py)."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.sync_tools import (
    DiffLocalComponentParams,
    PushLocalComponentParams,
    _batch_fetch_updated_on,
    _find_manifest_json,
    _find_settings_json,
    _find_table_dirs,
    _is_download_root,
    _read_map_json,
    _read_sync_meta,
    _resolve_local_path,
    _resolve_origin_url,
    _resolve_target_by_name,
    _reverse_lookup_map,
    _reverse_lookup_name,
    _scan_download_root,
    _validate_instance_url,
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

    # Business Rule (folder table: script + condition)
    br_dir = scope / "sys_script" / "MyRule"
    br_dir.mkdir(parents=True)
    (br_dir / "script.js").write_text("(function(){ gs.info('x'); })();", encoding="utf-8")
    (br_dir / "condition.js").write_text("current.state.changesTo('3')", encoding="utf-8")
    (scope / "sys_script" / "_map.json").write_text(
        json.dumps({"MyRule": "br-1"}), encoding="utf-8"
    )
    (scope / "sys_script" / "_sync_meta.json").write_text(
        json.dumps(
            {
                "MyRule": {
                    "sys_id": "br-1",
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

    def test_resolve_business_rule_file(self, download_root):
        # A BR is a folder table — condition.js maps to the condition field so the
        # behaviour (not just the script body) round-trips through sync push.
        path = download_root / "global" / "sys_script" / "MyRule" / "condition.js"
        resolved = _resolve_local_path(path)
        assert resolved.table == "sys_script"
        assert resolved.sys_id == "br-1"
        assert resolved.name == "MyRule"
        assert resolved.fields == {"condition": path}

    def test_resolve_business_rule_directory(self, download_root):
        path = download_root / "global" / "sys_script" / "MyRule"
        resolved = _resolve_local_path(path)
        assert resolved.table == "sys_script"
        assert resolved.sys_id == "br-1"
        assert set(resolved.fields) == {"script", "condition"}

    def test_resolve_scripted_rest_operation_file(self, download_root):
        # sys_ws_operation/<name>/operation_script.js — the Scripted REST resource
        # file-based workflow now resolves (was 'Cannot resolve').
        op_dir = download_root / "global" / "sys_ws_operation" / "get"
        op_dir.mkdir(parents=True)
        (op_dir / "_metadata.json").write_text(
            json.dumps({"sys_id": "op-exact", "name": "get"}), encoding="utf-8"
        )
        (op_dir / "operation_script.js").write_text("(function(){})();", encoding="utf-8")
        resolved = _resolve_local_path(op_dir / "operation_script.js")
        assert resolved.table == "sys_ws_operation"
        assert "operation_script" in resolved.fields

    def test_metadata_sys_id_wins_over_colliding_map(self, download_root):
        # operation names aren't globally unique; the per-folder _metadata.json
        # sys_id must win over a name-keyed _map.json (collision-proof).
        op_dir = download_root / "global" / "sys_ws_operation" / "get"
        op_dir.mkdir(parents=True)
        (op_dir / "_metadata.json").write_text(
            json.dumps({"sys_id": "op-exact", "name": "get"}), encoding="utf-8"
        )
        (op_dir / "operation_script.js").write_text("x", encoding="utf-8")
        (download_root / "global" / "sys_ws_operation" / "_map.json").write_text(
            json.dumps({"get": "op-WRONG-from-other-webservice"}), encoding="utf-8"
        )
        resolved = _resolve_local_path(op_dir / "operation_script.js")
        assert resolved.sys_id == "op-exact"  # _metadata wins, not the colliding _map

    def test_qualified_folder_resolves_bare_remote_name_and_qualifier(self, download_root):
        # A qualified folder ('updateSOSAP.end') keeps folder identity for local
        # lookups but exposes the record's own name + parent qualifier for
        # cross-instance target resolution.
        op_dir = download_root / "global" / "sys_ws_operation" / "updateSOSAP.end"
        op_dir.mkdir(parents=True)
        (op_dir / "_metadata.json").write_text(
            json.dumps(
                {
                    "sys_id": "op-real",
                    "name": "end",
                    "web_service_definition.name": "updateSOSAP",
                }
            ),
            encoding="utf-8",
        )
        (op_dir / "operation_script.js").write_text("x", encoding="utf-8")
        resolved = _resolve_local_path(op_dir / "operation_script.js")
        assert resolved.name == "updateSOSAP.end"  # local folder key (sync_meta/_map)
        assert resolved.remote_name == "end"  # ServiceNow identity
        assert resolved.qualifier == ("web_service_definition.name", "updateSOSAP")

    def test_resolve_target_by_name_appends_qualifier_clause(self, mock_config, mock_auth):
        # Without the parent qualifier, name=end is ambiguous on the target; the
        # qualifier scopes it to the right web service.
        captured = {}

        def _fake_query(config, auth, params):
            captured["query"] = params.query
            return {"results": [{"sys_id": "target-end", "name": "end"}]}

        with patch("servicenow_mcp.tools.sync_tools.sn_query", side_effect=_fake_query):
            matches = _resolve_target_by_name(
                mock_config,
                mock_auth,
                "sys_ws_operation",
                "end",
                ("web_service_definition.name", "updateSOSAP"),
            )
        assert captured["query"] == "name=end^web_service_definition.name=updateSOSAP"
        assert matches == [{"sys_id": "target-end", "name": "end"}]

    def test_widget_json_sys_id_wins_over_colliding_map(self, download_root):
        # Portal/bulk download writes _widget.json (NOT _metadata.json) with a
        # top-level sys_id. Push must use that exact sys_id, not fall back to the
        # name-keyed _map.json — otherwise the collision-proof path silently does
        # not apply to the most common widget case (download_app_sources).
        w_dir = download_root / "global" / "sp_widget" / "cool-widget"
        w_dir.mkdir(parents=True)
        (w_dir / "_widget.json").write_text(
            json.dumps({"sys_id": "wid-exact", "name": "Cool Widget"}), encoding="utf-8"
        )
        (w_dir / "script.js").write_text("x", encoding="utf-8")
        (download_root / "global" / "sp_widget" / "_map.json").write_text(
            json.dumps({"cool-widget": "wid-WRONG-from-map"}), encoding="utf-8"
        )
        resolved = _resolve_local_path(w_dir / "script.js")
        assert resolved.sys_id == "wid-exact"  # _widget.json wins, not the _map

    def test_resolve_unknown_file_raises(self, tmp_path):
        (tmp_path / "random.txt").write_text("hello")
        with pytest.raises(ValueError, match="Cannot resolve"):
            _resolve_local_path(tmp_path / "random.txt")

    def test_resolve_unknown_widget_file_raises(self, download_root):
        unknown = download_root / "global" / "sp_widget" / "my-widget" / "unknown.txt"
        unknown.write_text("test")
        with pytest.raises(ValueError, match="doesn't recognize"):
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

    def test_resolve_bare_table_directory_raises(self, download_root):
        # Passing the TABLE dir (not a record dir) is still unresolvable: its
        # parent ("global") is not a known table.
        path = download_root / "global" / "sp_angular_provider"
        with pytest.raises(ValueError, match="File-based push doesn't cover"):
            _resolve_local_path(path)

    def test_resolve_provider_folder_layout_file(self, download_root):
        # Download writes providers as a folder per record: <name>/script.js.
        # Push must resolve that layout directly (no record-lookup fallback).
        rec_dir = download_root / "global" / "sp_angular_provider" / "myService"
        rec_dir.mkdir(parents=True)
        (rec_dir / "script.js").write_text("angular.module('x');", encoding="utf-8")

        resolved = _resolve_local_path(rec_dir / "script.js")
        assert resolved.table == "sp_angular_provider"
        assert resolved.sys_id == "prov-1"
        assert "script" in resolved.fields

    def test_resolve_provider_folder_layout_dir(self, download_root):
        # The whole record folder resolves too, collecting every source field.
        rec_dir = download_root / "global" / "sp_angular_provider" / "myService"
        rec_dir.mkdir(parents=True)
        (rec_dir / "script.js").write_text("angular.module('x');", encoding="utf-8")
        (rec_dir / "client_script.js").write_text("function(){}", encoding="utf-8")

        resolved = _resolve_local_path(rec_dir)
        assert resolved.table == "sp_angular_provider"
        assert resolved.sys_id == "prov-1"
        assert resolved.fields.keys() == {"script", "client_script"}

    def test_resolve_provider_flat_layout_still_supported(self, download_root):
        # Back-compat: the historical flat "<name>.script.js" layout still works.
        path = download_root / "global" / "sp_angular_provider" / "myService.script.js"
        resolved = _resolve_local_path(path)
        assert resolved.table == "sp_angular_provider"
        assert resolved.sys_id == "prov-1"
        assert "script" in resolved.fields

    def test_resolve_widget_directory_safe_name_fallback(self, download_root):
        # Widget id with special chars: _map.json key = "My Widget [v2]",
        # but folder on disk = _safe_name("My Widget [v2]") = "My_Widget_v2"
        widget_dir = download_root / "global" / "sp_widget" / "My_Widget_v2"
        widget_dir.mkdir(parents=True)
        (widget_dir / "script.js").write_text("var x = 1;", encoding="utf-8")
        map_path = download_root / "global" / "sp_widget" / "_map.json"
        existing = json.loads(map_path.read_text(encoding="utf-8"))
        existing["My Widget [v2]"] = "wid-2"
        map_path.write_text(json.dumps(existing), encoding="utf-8")

        resolved = _resolve_local_path(widget_dir)
        assert resolved.sys_id == "wid-2"
        assert resolved.table == "sp_widget"

    def test_resolve_widget_file_safe_name_fallback(self, download_root):
        # Same as above but resolving a specific file inside the folder
        widget_dir = download_root / "global" / "sp_widget" / "My_Widget_v2"
        widget_dir.mkdir(parents=True)
        (widget_dir / "template.html").write_text("<div/>", encoding="utf-8")
        map_path = download_root / "global" / "sp_widget" / "_map.json"
        existing = json.loads(map_path.read_text(encoding="utf-8"))
        existing["My Widget [v2]"] = "wid-2"
        map_path.write_text(json.dumps(existing), encoding="utf-8")

        resolved = _resolve_local_path(widget_dir / "template.html")
        assert resolved.sys_id == "wid-2"
        assert resolved.table == "sp_widget"
        assert "template" in resolved.fields


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
    def test_diff_crlf_only_delta_is_unchanged_not_phantom(
        self, mock_fetch, mock_sn_query, mock_config, mock_auth, download_root
    ):
        # Local reads as LF (read_text normalizes), remote stores CRLF — identical
        # text. Before the fix this reported status "modified" with an EMPTY diff
        # (the phantom). It must now be "unchanged".
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        path.write_text("var x = 1;\nvar y = 2;\n", encoding="utf-8")
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 1;\r\nvar y = 2;\r\n",  # remote CRLF, same content
            "sys_updated_on": "2025-01-10 10:00:00",
        }

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
            "sys_updated_by": "carol",
        }

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(path))
        )

        assert result["conflict_warning"] is not None
        assert "2025-01-15" in result["conflict_warning"]
        # Surfaces who last changed the remote — the actionable signal.
        assert "carol" in result["conflict_warning"]
        assert result["remote_updated_by"] == "carol"

    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on_multi")
    def test_diff_directory_mode_scan(self, mock_batch, mock_config, mock_auth, download_root):
        # Scan mode fuses ALL tables' timestamp reads into ONE multi call
        # (issue #68 item 1) — pin that it is called exactly once.
        mock_batch.return_value = {
            "sp_widget": {"wid-1": {"on": "2025-01-10 10:00:00", "by": "alice"}},
            "sp_angular_provider": {"prov-1": {"on": "2025-01-10 10:00:00", "by": "alice"}},
            "sys_script_include": {"si-1": {"on": "2025-01-10 10:00:00", "by": "alice"}},
        }

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(download_root))
        )

        assert result["mode"] == "scan"
        assert result["summary"]["total"] >= 3
        assert "components" in result
        mock_batch.assert_called_once()  # whole scan = one fused fetch

    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on_multi")
    def test_diff_directory_mode_detects_remote_newer(
        self, mock_batch, mock_config, mock_auth, download_root
    ):
        mock_batch.return_value = {
            "sp_widget": {"wid-1": {"on": "2025-01-20 12:00:00", "by": "bob"}},  # newer
            "sp_angular_provider": {"prov-1": {"on": "2025-01-10 10:00:00", "by": "alice"}},
            "sys_script_include": {"si-1": {"on": "2025-01-10 10:00:00", "by": "alice"}},
        }

        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(download_root))
        )

        comps = {c["name"]: c for c in result["components"]}
        # File mtime is newer than downloaded_at (2025-01-10), so if remote is also
        # newer, status is "conflict" (both sides changed). If only remote changed
        # and local files are untouched, it would be "remote_newer".
        assert comps["my-widget"]["status"] in ("remote_newer", "conflict")
        # The drifted component surfaces who last changed the remote.
        assert comps["my-widget"]["remote_updated_by"] == "bob"

    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_diff_directory_mode_detects_local_modified(
        self, mock_batch, mock_config, mock_auth, download_root
    ):
        mock_batch.return_value = {
            "wid-1": {"on": "2025-01-10 10:00:00", "by": "alice"},
            "prov-1": {"on": "2025-01-10 10:00:00", "by": "alice"},
            "si-1": {"on": "2025-01-10 10:00:00", "by": "alice"},
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
        # Leads with the actionable retry (issue #65/P2-1).
        assert "instance=<alias>" in result["error"]

    # --- compare_to: local-vs-local (dev-vs-test), no network ---
    def test_compare_to_roots_summary(self, mock_config, mock_auth, download_root, tmp_path):
        # A 2nd download root with one widget field changed. Root-vs-root returns
        # per-component status only (bodies stay on disk) and hits NO network.
        import shutil

        right = tmp_path / "right_root"
        shutil.copytree(download_root, right)
        (right / "global" / "sp_widget" / "my-widget" / "script.js").write_text(
            "var x = 999;", encoding="utf-8"
        )

        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(download_root), compare_to=str(right)),
        )

        assert result["mode"] == "compare_local_roots"
        comps = {(c["table"], c["name"]): c for c in result["components"]}
        widget = comps[("sp_widget", "my-widget")]
        assert widget["status"] == "different"
        assert "script" in widget["changed_fields"]
        # summary only — field names, no diff bodies
        assert set(widget.keys()) == {"table", "name", "status", "changed_fields"}
        assert comps[("sys_script_include", "MyUtil")]["status"] == "identical"

    def test_compare_to_roots_only_in_one_side(
        self, mock_config, mock_auth, download_root, tmp_path
    ):
        import shutil

        right = tmp_path / "right_root"
        shutil.copytree(download_root, right)
        # Add a widget only present on the right.
        extra = right / "global" / "sp_widget" / "right-only"
        extra.mkdir(parents=True)
        (extra / "script.js").write_text("var only = 1;", encoding="utf-8")
        (right / "global" / "sp_widget" / "_map.json").write_text(
            json.dumps({"my-widget": "wid-1", "right-only": "wid-2"}), encoding="utf-8"
        )

        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(download_root), compare_to=str(right)),
        )

        comps = {(c["table"], c["name"]): c for c in result["components"]}
        assert comps[("sp_widget", "right-only")]["status"] == "only_in_right"

    def test_compare_to_component_returns_bodies(
        self, mock_config, mock_auth, download_root, tmp_path
    ):
        import shutil

        right = tmp_path / "right_root"
        shutil.copytree(download_root, right)
        (right / "global" / "sp_widget" / "my-widget" / "script.js").write_text(
            "var x = 999;", encoding="utf-8"
        )

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(path), compare_to=str(right)),
        )

        assert result["mode"] == "compare_local_component"
        # single-file path -> only the script field, with full diff body
        assert {d["field"] for d in result["diffs"]} == {"script"}
        script_diff = result["diffs"][0]
        assert script_diff["status"] == "modified"
        assert "diff" in script_diff

    def test_compare_to_missing_path_errors(self, mock_config, mock_auth, download_root):
        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(download_root), compare_to="/no/such/root"),
        )
        assert "error" in result

    def test_compare_to_file_not_dir_errors_cleanly(
        self, mock_config, mock_auth, download_root, tmp_path
    ):
        # compare_to pointing at a regular file must return a clean error dict,
        # not raise a raw NotADirectoryError from iterdir().
        a_file = tmp_path / "afile.txt"
        a_file.write_text("x", encoding="utf-8")
        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(download_root), compare_to=str(a_file)),
        )
        assert "error" in result
        assert "must be a download root" in result["error"]


# ---------------------------------------------------------------------------
# update_remote_from_local tests
# ---------------------------------------------------------------------------
class TestUpdateRemoteFromLocal:
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_success(
        self,
        mock_fetch,
        mock_update,
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
            # Second call: post-write re-read for landing verification + sync_meta
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",  # matches local → landing confirmed
                "sys_updated_on": "2025-01-10 11:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["message"] == "Update successful"
        assert result["local_sync"]["fields_pushed"] == ["script"]
        assert "snapshot" not in result["local_sync"]
        assert result["success"] is True
        mock_update.assert_called_once()

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_silent_non_landing_reported_not_success(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # THE trust bug: the Table API returns no error, but the post-write re-read
        # shows the field did NOT persist (sp_* silent drop). A 200 + bumped
        # mod_count is NOT proof of landing — the tool must report success:False
        # and must NOT poison _sync_meta (which would hide the non-landing forever).
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",  # differs from local "var x = 1;" → something to push
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            # post-write re-read: the write was accepted but the field STILL reads
            # the old value → it silently did not land.
            {
                "sys_id": "wid-1",
                "script": "var x = 0;",  # unchanged → NOT landed
                "sys_updated_on": "2025-01-10 11:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["success"] is False
        assert result["landed"] is False
        assert result["error"] == "WRITE_NOT_LANDED"
        assert result["fields_not_landed"] == ["script"]
        assert result["target_instance"] == "https://test.service-now.com"
        mock_write_meta.assert_not_called()  # baseline NOT poisoned

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_success_echoes_target_instance_and_landed(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # A confirmed push echoes WHERE it landed (multi-instance safety) and that
        # the content was verified present.
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {"sys_id": "wid-1", "script": "var x = 1;", "sys_updated_on": "2025-01-10 11:00:00"},
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert result["success"] is True
        assert result["landed"] is True
        assert result["target_instance"] == "https://test.service-now.com"

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_reads_remote_untruncated_full_true(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # INVARIANT: push must read the remote body via full=True (raw untruncated
        # GET), exactly like diff_local_component. The default sn_query path clips
        # any field >50k chars (truncate_results) — a CONTEXT-budget safeguard that
        # has no business inside an internal Python comparison. If it leaks in, a
        # >50KB widget client_script comes back capped and compares against the FULL
        # local copy as a bogus "~100% replacement" conflict / false WRITE_NOT_LANDED.
        # Both reads (pre-push gate AND post-push landing verify) must be untruncated.
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {"sys_id": "wid-1", "script": "var x = 1;", "sys_updated_on": "2025-01-10 11:00:00"},
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        update_remote_from_local(mock_config, mock_auth, PushLocalComponentParams(path=str(path)))

        assert mock_fetch.call_count >= 2
        for call in mock_fetch.call_args_list:
            assert call.kwargs.get("full") is True, (
                "push must fetch the remote with full=True — a truncated sn_query "
                "read corrupts the local-vs-remote comparison for >50KB fields"
            )

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_conflict_includes_risk_naming_other_user(
        self, mock_fetch, mock_config, mock_auth, download_root
    ):
        # Remote drifted AND the last editor is someone else → blocked, with a
        # graduated risk score that NAMES them so the overwrite is never silent.
        mock_fetch.return_value = {
            "sys_id": "si-1",
            "name": "MyUtil",
            "script": "// remote rewrote this\n// many\n// new\n// lines\nvar a = 1;\n",
            "sys_updated_on": "2025-01-12 10:00:00",
            "sys_updated_by": "alice",
            "sys_scope": "global",
        }
        path = download_root / "global" / "sys_script_include" / "MyUtil.script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert result["error"] == "CONFLICT_OTHER_USER"
        assert result["risk"]["other_user"] is True
        assert result["risk"]["level"] in ("high", "critical")
        assert "alice" in result["risk"]["message"]
        # P1-1: the rejection carries the line-level diff of what would be
        # overwritten, so the caller can decide without a second round-trip.
        modified = [d for d in result["diffs"] if d.get("status") == "modified"]
        assert modified, "CONFLICT must include the line diff of the pending push"
        assert "script" in {d["field"] for d in modified}
        assert "@@" in modified[0]["diff"] or "+" in modified[0]["diff"]

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_force_overwrite_still_reports_risk(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # force=true overwrites, but the risk it overrode stays visible in the
        # success result — accident-prevention even on a deliberate overwrite.
        mock_fetch.side_effect = [
            {
                "sys_id": "si-1",
                "name": "MyUtil",
                "script": "// remote changed\nvar a = 1;\n",
                "sys_updated_on": "2025-01-12 10:00:00",
                "sys_updated_by": "alice",
                "sys_scope": "global",
            },
            {
                "sys_id": "si-1",
                "script": "var gr = new GlideRecord('task');",  # landed = local
                "sys_updated_on": "2025-01-12 11:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "si-1"}

        path = download_root / "global" / "sys_script_include" / "MyUtil.script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path), force=True)
        )
        assert result["success"] is True
        assert result["risk"]["other_user"] is True

    @patch("servicenow_mcp.tools.sync_tools._resolve_current_user")
    @patch("servicenow_mcp.tools.sync_tools._push_actor_username")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_live_resolved_self_is_not_flagged_as_other_user(
        self, mock_fetch, mock_actor, mock_live, mock_config, mock_auth, download_root
    ):
        # SSO/browser: no configured username, but the live session says we ARE
        # 'alice'. alice's own later edit must NOT be flagged as a coworker's —
        # this is the "another user committed your update set" bug, fixed.
        mock_actor.return_value = ""  # nothing configured
        mock_live.return_value = "alice"  # server: you are alice
        mock_fetch.return_value = {
            "sys_id": "si-1",
            "name": "MyUtil",
            "script": "// my own later edit\nvar a = 1;\n",
            "sys_updated_on": "2025-01-12 10:00:00",
            "sys_updated_by": "alice",
            "sys_scope": "global",
        }
        path = download_root / "global" / "sys_script_include" / "MyUtil.script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert result["risk"]["identity"] == "confirmed"
        assert result["risk"]["other_user"] is False
        assert result["error"] != "CONFLICT_OTHER_USER"

    @patch("servicenow_mcp.tools.sync_tools._resolve_current_user")
    @patch("servicenow_mcp.tools.sync_tools._push_actor_username")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_unconfirmed_identity_hedges_not_accuses(
        self, mock_fetch, mock_actor, mock_live, mock_config, mock_auth, download_root
    ):
        # Identity truly unresolvable (config empty AND live lookup failed) →
        # block on drift, but NEVER assert "bob overwrote you". Hedge instead.
        mock_actor.return_value = ""
        mock_live.return_value = ""
        mock_fetch.return_value = {
            "sys_id": "si-1",
            "name": "MyUtil",
            "script": "// changed\nvar a = 1;\n",
            "sys_updated_on": "2025-01-12 10:00:00",
            "sys_updated_by": "bob",
            "sys_scope": "global",
        }
        path = download_root / "global" / "sys_script_include" / "MyUtil.script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert result["error"] == "CONFLICT"  # NOT CONFLICT_OTHER_USER
        assert result["risk"]["identity"] == "unconfirmed"
        assert result["risk"]["other_user"] is False
        assert "confirm" in result["risk"]["message"].lower()

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_flags_ownership_changed_since_download(
        self, mock_fetch, mock_config, mock_auth, download_root
    ):
        # Free signal: the download baseline said 'alice' owned it; remote now
        # says 'bob' → ownership changed under me. Surfaced from data already on
        # hand (local baseline + the one fetch), no extra API call.
        si_meta = download_root / "global" / "sys_script_include" / "_sync_meta.json"
        si_meta.write_text(
            json.dumps(
                {
                    "MyUtil": {
                        "sys_id": "si-1",
                        "sys_updated_on": "2025-01-10 10:00:00",
                        "sys_updated_by": "alice",
                        "downloaded_at": "2025-01-10T10:05:00+00:00",
                    }
                }
            ),
            encoding="utf-8",
        )
        mock_fetch.return_value = {
            "sys_id": "si-1",
            "name": "MyUtil",
            "script": "// changed remotely\nvar a = 1;\n",
            "sys_updated_on": "2025-01-12 10:00:00",
            "sys_updated_by": "bob",
            "sys_created_by": "alice",
            "sys_scope": "global",
        }
        path = download_root / "global" / "sys_script_include" / "MyUtil.script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert result["risk"]["attribution"] == "ownership_changed"
        assert result["risk"]["ownership_changed"] is True
        assert "alice" in result["risk"]["message"] and "bob" in result["risk"]["message"]

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diff_surfaces_attribution_before_push(
        self, mock_fetch, mock_config, mock_auth, download_root
    ):
        # The handoff must be visible at REVIEW time (diff), before any push.
        si_meta = download_root / "global" / "sys_script_include" / "_sync_meta.json"
        si_meta.write_text(
            json.dumps(
                {
                    "MyUtil": {
                        "sys_id": "si-1",
                        "sys_updated_on": "2025-01-10 10:00:00",
                        "sys_updated_by": "alice",
                        "downloaded_at": "2025-01-10T10:05:00+00:00",
                    }
                }
            ),
            encoding="utf-8",
        )
        mock_fetch.return_value = {
            "sys_id": "si-1",
            "name": "MyUtil",
            "script": "var gr = new GlideRecord('task');",
            "sys_updated_on": "2025-01-12 10:00:00",
            "sys_updated_by": "bob",
            "sys_created_by": "alice",
        }
        path = download_root / "global" / "sys_script_include" / "MyUtil.script.js"
        result = diff_local_component(
            mock_config, mock_auth, DiffLocalComponentParams(path=str(path))
        )
        assert result["attribution"]["attribution"] == "ownership_changed"

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_protected_record_is_not_pre_blocked(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # sys_policy='read' must NOT pre-block the push on our own guess — the
        # record is protected against the API but may still be editable in this
        # scope (it's UI-editable). The write goes through to the writer; the SERVER
        # decides. (Earlier this hard-blocked, falsely calling an editable record
        # uneditable.)
        mock_fetch.side_effect = [
            {
                "sys_id": "si-1",
                "name": "MyUtil",
                "script": "// changed\nvar a = 1;\n",
                "sys_updated_on": "2025-01-10 10:00:00",
                "sys_policy": "read",
                "sys_scope": "global",
            },
            {"sys_id": "si-1", "sys_updated_on": "2025-01-10 11:00:00"},
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "si-1"}
        path = download_root / "global" / "sys_script_include" / "MyUtil.script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert result.get("error") != "PROTECTED_RECORD"
        mock_update.assert_called_once()  # write reached the server, not pre-refused

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_crlf_only_delta_is_no_change(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # Local (LF) vs remote (CRLF) with identical text must NOT push — pushing
        # pure line-ending noise can spuriously trip ACL/conflict paths.
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        path.write_text("var x = 1;\nvar y = 2;\n", encoding="utf-8")
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 1;\r\nvar y = 2;\r\n",
            "sys_updated_on": "2025-01-10 10:00:00",
        }

        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert "No changes to push" in result["message"]
        mock_update.assert_not_called()

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_403_sp_table_hint_mentions_service_portal(
        self,
        mock_fetch,
        mock_update,
        mock_write_meta,
        mock_sn_query,
        mock_config,
        mock_auth,
        download_root,
    ):
        # sp_* tables carry protections beyond role/ACL; the 403 hint must call
        # that out so the user doesn't chase update-set/role red herrings.
        mock_fetch.side_effect = [
            {
                "sys_id": "prov-1",
                "name": "myService",
                "script": "angular.module('x').factory('myService',function(){ /* old */ });",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {"sys_scope": {"value": "scope-1", "display_value": "x_app_bpm"}},
        ]
        mock_update.return_value = {
            "error": "ACL Exception Update Failed due to security constraints",
            "status": 403,
        }
        mock_sn_query.return_value = {"results": []}

        path = download_root / "global" / "sp_angular_provider" / "myService.script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["success"] is False
        assert result["status"] == 403
        assert "Service Portal" in result["hint"]
        assert "SP Designer" in result["hint"]
        mock_write_meta.assert_not_called()

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_business_rule_condition(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # Editing only condition.js pushes the BR condition field — the gap that
        # forced manual reapply because sys_script wasn't a sync-supported table.
        mock_fetch.side_effect = [
            {
                "sys_id": "br-1",
                "name": "MyRule",
                "condition": "current.state.changesTo('4')",  # differs from local
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {
                "sys_id": "br-1",
                "condition": "current.state.changesTo('3')",  # landed = local
                "sys_updated_on": "2025-01-10 11:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "br-1"}

        path = download_root / "global" / "sys_script" / "MyRule" / "condition.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["success"] is True
        assert result["local_sync"]["fields_pushed"] == ["condition"]
        pushed_params = mock_update.call_args.args[2]
        assert pushed_params.table == "sys_script"
        assert "condition" in pushed_params.update_data

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_403_acl_does_not_poison_sync_meta(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # ServiceNow rejects (e.g. update set held by another user). The wrapper
        # must NOT mark sync_meta as updated, and must return actionable guidance.
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 0;",  # differs from local -> there is something to push
            "sys_updated_on": "2025-01-10 10:00:00",
        }
        mock_update.return_value = {
            "error": 'Update failed: {"error":{"detail":"ACL Exception Update Failed '
            'due to security constraints"}}',
            "status": 403,
        }
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["success"] is False
        assert result["status"] == 403
        assert result["sync_meta_updated"] is False
        assert "update set" in result["hint"].lower()
        mock_write_meta.assert_not_called()  # local sync state NOT poisoned

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_403_surfaces_active_update_set_owner(
        self,
        mock_fetch,
        mock_update,
        mock_write_meta,
        mock_sn_query,
        mock_config,
        mock_auth,
        download_root,
    ):
        # On 403, the tool internally resolves who holds the scope's in-progress
        # update set so the caller sees the likely culprit without a manual lookup.
        mock_fetch.side_effect = [
            # conflict-comparison fetch (before push)
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            # scope fetch on the 403 path
            {"sys_scope": {"value": "scope-1", "display_value": "x_app_bpm"}},
        ]
        mock_update.return_value = {
            "error": "Update failed: ACL Exception Update Failed due to security constraints",
            "status": 403,
        }
        mock_sn_query.side_effect = [
            # 1) _active_update_sets — in-progress sets in the component's scope
            {
                "results": [
                    {
                        "name": "KH refactor",
                        "sys_created_by": "jane.doe",
                        "sys_updated_by": "jane.doe",
                        "sys_updated_on": "2026-05-27 09:00:00",
                    }
                ]
            },
            # 2) _record_update_set_hold — no open set holds THIS record
            {"results": []},
        ]
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["success"] is False
        assert result["active_update_sets"][0]["name"] == "KH refactor"
        assert result["active_update_sets"][0]["updated_by"] == "jane.doe"
        # in-progress update sets queried for the component's scope (FIRST sn_query call)
        assert "scope-1" in mock_sn_query.call_args_list[0].args[2].query
        # the record-level hold lookup queries sys_update_xml for THIS record
        assert mock_sn_query.call_args_list[1].args[2].table == "sys_update_xml"
        mock_write_meta.assert_not_called()

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_403_surfaces_cross_user_update_set_hold(
        self,
        mock_fetch,
        mock_update,
        mock_write_meta,
        mock_sn_query,
        mock_config,
        mock_auth,
        download_root,
    ):
        # 403 where THIS record is held in ANOTHER user's UNCOMMITTED update set.
        # The tool must name the holder + set and say it is NOT the caller's own
        # update set/scope — the exact misdiagnosis this change fixes.
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",
                "sys_updated_on": "2025-01-10 10:00:00",  # == baseline, no drift
            },
            {"sys_scope": {"value": "scope-1", "display_value": "x_app_bpm"}},
        ]
        mock_update.return_value = {
            "error": "ACL Exception Update Failed due to security constraints",
            "status": 403,
        }
        mock_sn_query.side_effect = [
            {"results": []},  # _active_update_sets (scope-wide)
            {
                "results": [
                    {
                        "update_set.name": "GwangSung Choi",
                        "update_set.state": "in progress",
                        "sys_updated_by": "gwang.choi",
                    }
                ]
            },  # _record_update_set_hold — held by another user, open
        ]
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["success"] is False
        assert result["record_hold"]["held_by"] == "gwang.choi"
        assert result["record_hold"]["update_set"] == "GwangSung Choi"
        hint = result["hint"].lower()
        # The hold is surfaced as CONTEXT, never asserted as the 403's cause — an
        # open update set does not lock a record against a Table-API write.
        assert "gwang.choi" in hint
        assert "not a confirmed cause" in hint
        assert "does not by itself lock" in hint
        mock_write_meta.assert_not_called()

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_403_no_hold_when_update_set_committed(
        self,
        mock_fetch,
        mock_update,
        mock_write_meta,
        mock_sn_query,
        mock_config,
        mock_auth,
        download_root,
    ):
        # The holding set is COMMITTED -> released -> not a live hold. The hint
        # must NOT blame another user and must point at ACL/SP protection instead.
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 0;",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {"sys_scope": {"value": "scope-1", "display_value": "x_app_bpm"}},
        ]
        mock_update.return_value = {
            "error": "ACL Exception Update Failed due to security constraints",
            "status": 403,
        }
        mock_sn_query.side_effect = [
            {"results": []},  # _active_update_sets
            {
                "results": [
                    {
                        "update_set.name": "GwangSung Choi",
                        "update_set.state": "complete",  # committed -> released
                        "sys_updated_by": "gwang.choi",
                    }
                ]
            },
        ]
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["success"] is False
        assert "record_hold" not in result
        # No live hold → the hint must NOT name/ blame another user, and must point
        # at the real likely cause (Service Portal protection) instead.
        hint = result["hint"].lower()
        assert "gwang.choi" not in hint
        assert "service portal" in hint

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_conflict_live_note_released(
        self, mock_fetch, mock_sn_query, mock_config, mock_auth, download_root
    ):
        # Remote moved since download (drift), but NO ONE holds it now -> frame it
        # as a clean fast-forward, not a stale download-baseline "someone holds it".
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 99;",
            "sys_updated_on": "2025-01-15 12:00:00",  # newer than 2025-01-10 baseline
        }
        mock_sn_query.return_value = {"results": []}  # no live hold
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["error"] in ("CONFLICT", "CONFLICT_OTHER_USER")
        assert result["record_hold"] is None
        msg = result["message"].lower()
        assert "fast-forward" in msg
        assert "force=true" in msg

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_conflict_live_note_held(
        self, mock_fetch, mock_sn_query, mock_config, mock_auth, download_root
    ):
        # Drift AND the record is still actively held by another user -> warn loudly.
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 99;",
            "sys_updated_on": "2025-01-15 12:00:00",
        }
        mock_sn_query.return_value = {
            "results": [
                {
                    "update_set.name": "GwangSung Choi",
                    "update_set.state": "in progress",
                    "sys_updated_by": "gwang.choi",
                }
            ]
        }
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )

        assert result["record_hold"]["held_by"] == "gwang.choi"
        assert "still held by" in result["message"].lower()

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
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_force_overrides_conflict(
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
                "script": "var x = 99;",
                "sys_updated_on": "2025-01-15 12:00:00",  # newer
            },
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",  # landed = local
                "sys_updated_on": "2025-01-15 13:00:00",
            },
        ]
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
    def test_push_widget_directory(
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
                "template": "<div>old</div>",
                "script": "var x = 0;",
                "client_script": "function go(){}",
                "css": ".a{}",
                "sys_updated_on": "2025-01-10 10:00:00",
            },
            {
                "sys_id": "wid-1",
                "template": "<div>hello</div>",  # landed = local
                "script": "var x = 1;",  # landed = local
                "sys_updated_on": "2025-01-10 11:00:00",
            },
        ]
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
            # m2m_sp_widget_dependency: no CSS/JS dependency edges
            [],
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
                {
                    "sys_id": "wid-1",
                    "sys_updated_on": "2025-01-10 10:00:00",
                    "sys_updated_by": "alice",
                },
                {
                    "sys_id": "wid-2",
                    "sys_updated_on": "2025-01-11 11:00:00",
                    "sys_updated_by": "bob",
                },
            ]
        }
        result = _batch_fetch_updated_on(mock_config, mock_auth, "sp_widget", ["wid-1", "wid-2"])
        assert result == {
            "wid-1": {"on": "2025-01-10 10:00:00", "by": "alice"},
            "wid-2": {"on": "2025-01-11 11:00:00", "by": "bob"},
        }
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
        mock_batch.return_value = {"si-1": {"on": "2025-01-10 10:00:00", "by": "alice"}}
        result = _scan_download_root(mock_config, mock_auth, root)
        assert result["mode"] == "scan"
        assert result["summary"]["total"] == 0

    @patch("servicenow_mcp.tools.sync_tools._batch_fetch_updated_on")
    def test_scan_download_root_finds_provider_folder_layout(
        self, mock_batch, mock_config, mock_auth, tmp_path
    ):
        """A provider downloaded as a folder (<name>/script.js) used to be
        skipped by the scope scan because it only looked for the flat layout."""
        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "t", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        scope = root / "global"
        scope.mkdir()
        prov_dir = scope / "sp_angular_provider"
        prov_dir.mkdir()
        (prov_dir / "_map.json").write_text(json.dumps({"myService": "prov-1"}), encoding="utf-8")
        rec = prov_dir / "myService"
        rec.mkdir()
        (rec / "script.js").write_text("angular.module('x');", encoding="utf-8")
        mock_batch.return_value = {"prov-1": {"on": "2025-01-10 10:00:00", "by": "alice"}}

        result = _scan_download_root(mock_config, mock_auth, root)

        names = {c["name"] for c in result["components"]}
        assert "myService" in names

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
        mock_batch.return_value = {"si-1": {"on": "2025-01-10 10:00:00", "by": "alice"}}
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
        mock_batch.return_value = {"si-1": {"on": "2025-01-10 10:00:00", "by": "alice"}}
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
        # Leads with the actionable retry (issue #65/P2-1).
        assert "instance=<alias>" in result["error"]

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

    # --- Lines 723-724: update_remote_from_local - push failure ---
    @patch(
        "servicenow_mcp.tools.sync_tools.update_portal_component",
        side_effect=RuntimeError("network error"),
    )
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_update_failure(
        self,
        mock_fetch,
        mock_update,
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
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        assert "error" in result
        assert "Push failed" in result["error"]

    # --- Lines 743-744: update_remote_from_local - sync meta update failure ---
    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta", side_effect=OSError("write err"))
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_sync_meta_failure(
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
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",  # landed = local
                "sys_updated_on": "2025-01-10 11:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}
        path = download_root / "global" / "sp_widget" / "my-widget" / "script.js"
        result = update_remote_from_local(
            mock_config, mock_auth, PushLocalComponentParams(path=str(path))
        )
        # Should still succeed despite sync meta update failure
        assert result["message"] == "Update successful"


# ---------------------------------------------------------------------------
# Origin provenance: app-source downloads (manifest-only) must be cross-instance
# checked too. The hard block is sound here — origin URL is recorded at download,
# so comparing it to the push target is provenance, not a sys_id heuristic.
# ---------------------------------------------------------------------------


class TestOriginProvenance:
    def _cfg(self, url):
        return ServerConfig(
            instance_url=url,
            auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
        )

    def test_resolve_origin_prefers_settings(self, tmp_path):
        (tmp_path / "_settings.json").write_text(
            json.dumps({"url": "https://portal.service-now.com"}), encoding="utf-8"
        )
        (tmp_path / "_manifest.json").write_text(
            json.dumps({"instance": "https://app.service-now.com"}), encoding="utf-8"
        )
        assert _resolve_origin_url(tmp_path) == "https://portal.service-now.com"

    def test_resolve_origin_falls_back_to_manifest(self, tmp_path):
        # download_app_sources writes only _manifest.json (no _settings.json).
        (tmp_path / "_manifest.json").write_text(
            json.dumps({"instance": "https://app.service-now.com"}), encoding="utf-8"
        )
        assert _find_settings_json(tmp_path) == {}
        assert _resolve_origin_url(tmp_path) == "https://app.service-now.com"

    def test_resolve_origin_empty_without_provenance(self, tmp_path):
        assert _resolve_origin_url(tmp_path) == ""

    def test_find_manifest_walks_up(self, tmp_path):
        (tmp_path / "_manifest.json").write_text(
            json.dumps({"instance": "https://app.service-now.com"}), encoding="utf-8"
        )
        nested = tmp_path / "global" / "sys_script_include"
        nested.mkdir(parents=True)
        assert _find_manifest_json(nested).get("instance") == "https://app.service-now.com"

    def test_manifest_only_blocks_cross_instance_push(self, tmp_path):
        """The previously-silent gap: app-source tree (manifest, no settings)
        downloaded from prod, then resolved while connected to dev → must block."""
        root = tmp_path / "out"
        root.mkdir()
        (root / "_manifest.json").write_text(
            json.dumps({"instance": "https://prod.service-now.com"}), encoding="utf-8"
        )
        si = root / "global" / "sys_script_include"
        si.mkdir(parents=True)
        (si / "MyUtil.script.js").write_text("var x = 1;", encoding="utf-8")
        (si / "_map.json").write_text(json.dumps({"MyUtil": "si-1"}), encoding="utf-8")

        resolved = _resolve_local_path(si / "MyUtil.script.js")
        assert resolved.instance_url == "https://prod.service-now.com"

        with pytest.raises(ValueError, match="Retry this call with instance=<alias>"):
            _validate_instance_url(resolved, self._cfg("https://dev.service-now.com"))

    def test_manifest_only_same_instance_passes(self, tmp_path):
        root = tmp_path / "out"
        root.mkdir()
        (root / "_manifest.json").write_text(
            json.dumps({"instance": "https://dev.service-now.com"}), encoding="utf-8"
        )
        si = root / "global" / "sys_script_include"
        si.mkdir(parents=True)
        (si / "MyUtil.script.js").write_text("var x = 1;", encoding="utf-8")
        (si / "_map.json").write_text(json.dumps({"MyUtil": "si-1"}), encoding="utf-8")

        resolved = _resolve_local_path(si / "MyUtil.script.js")
        # Same instance → validation passes (no raise).
        _validate_instance_url(resolved, self._cfg("https://dev.service-now.com"))

    def test_no_provenance_resolves_empty_origin(self, tmp_path):
        """No _settings.json and no _manifest.json → origin unknown ("") so the
        push fails open with a warning rather than a hard block."""
        si = tmp_path / "global" / "sys_script_include"
        si.mkdir(parents=True)
        (si / "MyUtil.script.js").write_text("var x = 1;", encoding="utf-8")
        (si / "_map.json").write_text(json.dumps({"MyUtil": "si-1"}), encoding="utf-8")

        resolved = _resolve_local_path(si / "MyUtil.script.js")
        assert resolved.instance_url == ""
        # Unknown origin never blocks.
        _validate_instance_url(resolved, self._cfg("https://dev.service-now.com"))

    def test_directory_scan_blocks_manifest_only_mismatch(self, tmp_path):
        """diff_local_component directory-mode also honors manifest provenance:
        a prod-origin app-source dir scanned while connected to dev → error,
        before any remote fetch."""
        root = tmp_path / "out"
        root.mkdir()
        (root / "_manifest.json").write_text(
            json.dumps({"instance": "https://prod.service-now.com"}), encoding="utf-8"
        )
        result = _scan_download_root(self._cfg("https://dev.service-now.com"), MagicMock(), root)
        # Leads with the actionable retry (issue #65/P2-1), names the origin.
        assert result.get("error", "").startswith("Retry this diff with instance=<alias>")
        assert "prod.service-now.com" in result["error"]


# ---------------------------------------------------------------------------
# Hardened baseline-drift conflict gate — cross-user overwrite protection.
# Baseline for "my-widget" in download_root is 2025-01-10 10:00:00; me = admin.
# ---------------------------------------------------------------------------
class TestPushConflictGate:
    def _widget_path(self, download_root):
        return download_root / "global" / "sp_widget" / "my-widget" / "script.js"

    def _remote(self, *, updated_by, updated_on="2025-01-12 09:00:00", script="var x = 0;"):
        return {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": script,  # differs from local "var x = 1;"
            "sys_updated_on": updated_on,  # newer than baseline → drift
            "sys_updated_by": updated_by,
        }

    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_cross_user_drift_blocks_without_confirm(
        self, mock_fetch, mock_update, mock_config, mock_auth, download_root
    ):
        mock_fetch.return_value = self._remote(updated_by="coworker@corp.com")
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(self._widget_path(download_root))),
        )
        assert result["error"] == "CONFLICT_OTHER_USER"
        assert "coworker@corp.com" in result["message"]
        assert result["remote_updated_by"] == "coworker@corp.com"
        mock_update.assert_not_called()

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_force_overrides_cross_user(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # Verification gate, not a hard block: once you've seen who/when (the
        # un-forced call surfaces it), force=true overrides a coworker's edit too.
        mock_fetch.side_effect = [
            self._remote(updated_by="coworker@corp.com"),
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",  # landed = local
                "sys_updated_on": "2025-01-12 10:00:00",
            },  # post-update meta
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(self._widget_path(download_root)), force=True),
        )
        assert result.get("success") is True
        mock_update.assert_called_once()

    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_self_drift_uses_force_gate_not_cross_user(
        self, mock_fetch, mock_update, mock_config, mock_auth, download_root
    ):
        # Remote edited by ME (admin) after download → lighter CONFLICT, force-able.
        mock_fetch.return_value = self._remote(updated_by="admin")
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(self._widget_path(download_root))),
        )
        assert result["error"] == "CONFLICT"  # not CONFLICT_OTHER_USER
        mock_update.assert_not_called()

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_self_drift_force_proceeds(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        mock_fetch.side_effect = [
            self._remote(updated_by="admin"),
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",  # landed = local
                "sys_updated_on": "2025-01-12 10:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(self._widget_path(download_root)), force=True),
        )
        assert result.get("success") is True
        mock_update.assert_called_once()


# ---------------------------------------------------------------------------
# Cross-instance deploy — push dev-origin local source to a different (test)
# instance, re-resolving the target record BY NAME (no re-download, sys_id-safe).
# Origin is forced to dev; mock_config targets test.
# ---------------------------------------------------------------------------
class TestCrossInstanceDeploy:
    def _widget_path(self, root):
        return root / "global" / "sp_widget" / "my-widget" / "script.js"

    def _set_origin_dev(self, root):
        (root / "_settings.json").write_text(
            json.dumps({"name": "dev", "url": "https://dev.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )

    def test_blocked_without_optin_informs_not_walls(self, mock_config, mock_auth, download_root):
        self._set_origin_dev(download_root)
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(self._widget_path(download_root))),
        )
        assert result["error"] == "CROSS_INSTANCE"
        assert result["origin_instance"] == "https://dev.service-now.com"
        assert result["target_instance"] == "https://test.service-now.com"
        assert "cross_instance_deploy=true" in result["message"]

    @patch("servicenow_mcp.tools.sync_tools._resolve_target_by_name")
    def test_target_not_found(self, mock_resolve, mock_config, mock_auth, download_root):
        self._set_origin_dev(download_root)
        mock_resolve.return_value = []
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(
                path=str(self._widget_path(download_root)), cross_instance_deploy=True
            ),
        )
        assert result["error"] == "TARGET_NOT_FOUND"

    @patch("servicenow_mcp.tools.sync_tools._resolve_target_by_name")
    def test_target_ambiguous(self, mock_resolve, mock_config, mock_auth, download_root):
        self._set_origin_dev(download_root)
        mock_resolve.return_value = [
            {"sys_id": "a", "name": "my-widget"},
            {"sys_id": "b", "name": "my-widget"},
        ]
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(
                path=str(self._widget_path(download_root)), cross_instance_deploy=True
            ),
        )
        assert result["error"] == "TARGET_AMBIGUOUS"
        assert len(result["candidates"]) == 2

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    @patch("servicenow_mcp.tools.sync_tools._resolve_target_by_name")
    def test_deploys_to_target_own_sys_id(
        self,
        mock_resolve,
        mock_fetch,
        mock_update,
        mock_write_meta,
        mock_config,
        mock_auth,
        download_root,
    ):
        self._set_origin_dev(download_root)
        # Target (test) has its OWN sys_id for "my-widget", different from dev's wid-1.
        mock_resolve.return_value = [{"sys_id": "TEST-wid-99", "name": "my-widget"}]
        mock_fetch.side_effect = [
            {
                "sys_id": "TEST-wid-99",
                "name": "my-widget",
                "script": "var x = 0;",  # differs from local "var x = 1;"
                "sys_updated_on": "2025-01-12 09:00:00",  # newer than dev baseline — but
                "sys_updated_by": "whoever",  # drift gate is skipped for cross-instance
            },
            {
                "sys_id": "TEST-wid-99",
                "script": "var x = 1;",  # landed = local on the target instance
                "sys_updated_on": "2025-01-12 10:00:00",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "TEST-wid-99"}
        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(
                path=str(self._widget_path(download_root)), cross_instance_deploy=True
            ),
        )
        assert result.get("success") is True
        mock_update.assert_called_once()
        pushed = mock_update.call_args.args[2]
        assert pushed.sys_id == "TEST-wid-99"  # target's own sys_id, not dev's wid-1


class TestDerivedDiffPushCoverage:
    """Batch 3: downloadable single-script tables are diffable/pushable by path,
    derived from SOURCE_CONFIG (no hand-authored second list)."""

    def test_ui_action_folder_resolves_for_push(self, download_root):
        # A downloaded sys_ui_action (single 'script' field) must resolve to its
        # component identity — previously rejected as 'File-based push doesn't cover'.
        op_dir = download_root / "global" / "sys_ui_action" / "My UI Action"
        op_dir.mkdir(parents=True)
        (op_dir / "_metadata.json").write_text(
            json.dumps({"sys_id": "uia-1", "name": "My UI Action"}), encoding="utf-8"
        )
        (op_dir / "script.js").write_text("gs.addInfoMessage('x');", encoding="utf-8")
        resolved = _resolve_local_path(op_dir / "script.js")
        assert resolved.table == "sys_ui_action"
        assert resolved.sys_id == "uia-1"
        assert "script" in resolved.fields

    def test_derived_map_excludes_update_xml(self):
        from servicenow_mcp.tools.sync_tools import _folder_layout_field_map

        assert _folder_layout_field_map("sys_update_xml") is None

    def test_hand_authored_tables_take_precedence(self):
        from servicenow_mcp.tools.sync_tools import _folder_layout_field_map

        # sys_script is folder-based with a condition file — the hand map wins
        # over a naive derived {script.js: script}.
        m = _folder_layout_field_map("sys_script")
        assert m.get("condition.js") == "condition"

    def test_all_downloadable_source_tables_are_supported(self):
        # The push/diff surface must equal the downloadable-with-source set minus
        # the deliberate excludes — no silent gap.
        from servicenow_mcp.tools.source_tools import SOURCE_CONFIG
        from servicenow_mcp.tools.sync_tools import _DIFF_PUSH_EXCLUDE_TABLES, _all_supported_tables

        downloadable = {cfg["table"] for cfg in SOURCE_CONFIG.values() if cfg.get("source_fields")}
        expected = downloadable - _DIFF_PUSH_EXCLUDE_TABLES
        assert expected <= set(_all_supported_tables())

    def test_derived_filenames_are_canonical(self):
        # Every derived filename must match the canonical field_filename the
        # downloader writes, or push can't find the file on disk.
        from servicenow_mcp.tools.sync_tools import _derived_folder_field_maps
        from servicenow_mcp.utils.source_layout import field_filename

        for table, file_map in _derived_folder_field_maps().items():
            for filename, field in file_map.items():
                assert filename == field_filename(field), (table, filename, field)


# ---------------------------------------------------------------------------
# sp_header_footer ↔ sp_widget field parity (v1.19.1)
# ---------------------------------------------------------------------------
# Headers/footers share sp_widget's five code fields. The old template+css-only
# maps made server script/client_script/link invisible to download/diff/push,
# forcing raw by-sys_id field writes. Pin parity in all three gates.


def test_header_footer_sync_map_is_widget_parity() -> None:
    from servicenow_mcp.tools.sync_tools import TABLE_FILE_FIELD_MAP, WIDGET_FILE_FIELD_MAP

    assert TABLE_FILE_FIELD_MAP["sp_header_footer"] == WIDGET_FILE_FIELD_MAP


def test_header_footer_editable_fields_are_widget_parity() -> None:
    from servicenow_mcp.tools.portal_tools import PORTAL_COMPONENT_EDITABLE_FIELDS

    assert (
        PORTAL_COMPONENT_EDITABLE_FIELDS["sp_header_footer"]
        == PORTAL_COMPONENT_EDITABLE_FIELDS["sp_widget"]
    )


def test_header_footer_download_fetches_all_code_fields() -> None:
    from servicenow_mcp.tools.source_tools import SOURCE_CONFIG

    assert set(SOURCE_CONFIG["sp_header_footer"]["source_fields"]) == {
        "template",
        "script",
        "client_script",
        "link",
        "css",
    }


class TestQualifiedFolderResolution:
    """Qualified types nest as <table>/<qualifier>/<name>/, so the pusher must read
    the table from _metadata.json instead of counting directories."""

    @staticmethod
    def _write_record(record_dir, table, sys_id, name, **extra):
        record_dir.mkdir(parents=True)
        (record_dir / "script.js").write_text("gs.info('x');", encoding="utf-8")
        (record_dir / "_metadata.json").write_text(
            json.dumps({"table": table, "sys_id": sys_id, "name": name, **extra}),
            encoding="utf-8",
        )

    def test_nested_record_dir_resolves_table_and_relative_name(self, tmp_path):
        rec = tmp_path / "x_app" / "sys_script" / "x_app_request" / "MyRule"
        self._write_record(rec, "sys_script", "br-1", "MyRule", collection="x_app_request")

        resolved = _resolve_local_path(rec)

        assert resolved.table == "sys_script"
        assert resolved.sys_id == "br-1"
        # name doubles as the _map.json / _sync_meta.json key -> POSIX relpath.
        assert resolved.name == "x_app_request/MyRule"
        assert resolved.remote_name == "MyRule"
        assert resolved.qualifier == ("collection", "x_app_request")
        assert set(resolved.fields) == {"script"}

    def test_nested_field_file_resolves_same_identity(self, tmp_path):
        rec = tmp_path / "x_app" / "sys_script" / "x_app_request" / "MyRule"
        self._write_record(rec, "sys_script", "br-1", "MyRule", collection="x_app_request")

        resolved = _resolve_local_path(rec / "script.js")

        assert (resolved.table, resolved.sys_id) == ("sys_script", "br-1")
        assert resolved.name == "x_app_request/MyRule"
        assert set(resolved.fields) == {"script"}

    def test_qualifier_that_shadows_a_real_table_does_not_hijack_the_push(self, tmp_path):
        # A business rule ON sys_script_include nests under a directory named for a
        # REAL source table. Parent-name resolution would push it as a script
        # include — wrong table, wrong record. Metadata must win.
        rec = tmp_path / "x_app" / "sys_script" / "sys_script_include" / "GuardRule"
        self._write_record(rec, "sys_script", "br-9", "GuardRule", collection="sys_script_include")

        for target in (rec, rec / "script.js"):
            resolved = _resolve_local_path(target)
            assert resolved.table == "sys_script", target
            assert resolved.sys_id == "br-9", target

    def test_shadowed_table_field_does_not_misroute_a_client_script(self, tmp_path):
        # client_script's qualifier field is literally named 'table' and holds the
        # table it RUNS ON, so _metadata.json['table'] is 'incident', not
        # 'sys_script_client'. Resolving on it would push the script as an
        # incident record. 'source_table' is the un-shadowable key.
        rec = tmp_path / "x_app" / "sys_script_client" / "incident" / "SetDefaultState"
        rec.mkdir(parents=True)
        (rec / "script.js").write_text("function onLoad() {}", encoding="utf-8")
        (rec / "_metadata.json").write_text(
            json.dumps(
                {
                    "source_type": "client_script",
                    "table": "incident",  # the shadowing summary field
                    "source_table": "sys_script_client",
                    "sys_id": "cs-1",
                    "name": "SetDefaultState",
                }
            ),
            encoding="utf-8",
        )

        for target in (rec, rec / "script.js"):
            resolved = _resolve_local_path(target)
            assert resolved.table == "sys_script_client", target
            assert resolved.sys_id == "cs-1", target
            assert resolved.name == "incident/SetDefaultState", target

    def test_legacy_flat_record_without_metadata_still_resolves(self, tmp_path):
        # Trees downloaded before nesting have no _metadata.json; the historical
        # parent-name heuristic must keep working for them.
        table_dir = tmp_path / "x_app" / "sys_script"
        rec = table_dir / "OldRule"
        rec.mkdir(parents=True)
        (rec / "script.js").write_text("gs.info('x');", encoding="utf-8")
        (table_dir / "_map.json").write_text(json.dumps({"OldRule": "br-2"}), encoding="utf-8")

        resolved = _resolve_local_path(rec)

        assert (resolved.table, resolved.sys_id, resolved.name) == (
            "sys_script",
            "br-2",
            "OldRule",
        )


class TestContentFirstDriftGate:
    """The gate answers "did the SERVER BODY move since my baseline?" by hashing
    content against the pristine _baseline/ snapshot — NOT by comparing
    sys_updated_on.

    The bug this pins: a stamp also bumps for your own push, a re-save, or an edit
    to an unrelated field on the record. Gating on the stamp turned the ordinary
    edit -> push -> edit-again loop (same file, same session) into a fake
    "someone changed this on the server, pushing is risky" every single time. The
    timestamp survives only as the fallback for legacy trees with no baseline —
    never as a silent pass.
    """

    @staticmethod
    def _seed_baseline(widget_dir, **field_bodies):
        """Record what the server had at the last download/push."""
        from servicenow_mcp.utils.baseline import write_baseline_for

        for filename, body in field_bodies.items():
            write_baseline_for(widget_dir / filename, body)

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_timestamp_bump_with_identical_body_is_not_a_conflict(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        widget_dir = download_root / "global" / "sp_widget" / "my-widget"
        # The server body still equals my baseline; only the stamp advanced (my own
        # earlier push). Local carries my new edit and must push through cleanly.
        self._seed_baseline(widget_dir, **{"script.js": "var x = 1;"})
        (widget_dir / "script.js").write_text("var x = 2;", encoding="utf-8")
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 1;",
                "sys_updated_on": "2025-01-15 12:00:00",  # newer than _sync_meta
                "sys_updated_by": "admin",
                "sys_created_by": "admin",
                "sys_scope": "global",
            },
            # Post-write landing verification re-read: the body I pushed is there.
            {
                "sys_id": "wid-1",
                "script": "var x = 2;",
                "sys_updated_on": "2025-01-15 13:00:00",
                "sys_updated_by": "admin",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(widget_dir / "script.js")),
        )

        assert "error" not in result
        assert result["risk"]["level"] == "none"
        mock_update.assert_called_once()

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_real_body_change_still_blocks_even_when_stamp_looks_old(
        self, mock_fetch, mock_config, mock_auth, download_root
    ):
        widget_dir = download_root / "global" / "sp_widget" / "my-widget"
        self._seed_baseline(widget_dir, **{"script.js": "var x = 1;"})
        (widget_dir / "script.js").write_text("var x = 2;", encoding="utf-8")
        # Stamp is NOT newer than the download watermark, but the body diverged
        # from the baseline: the server really moved. Content wins over the clock.
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 999; // someone else",
            "sys_updated_on": "2025-01-10 10:00:00",
            "sys_updated_by": "bob",
            "sys_created_by": "admin",
            "sys_scope": "global",
        }

        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(widget_dir / "script.js")),
        )

        assert result["error"] in ("CONFLICT", "CONFLICT_OTHER_USER")
        assert result["server_changed_fields"] == ["script"]
        assert result["drift_verified_by"] == "content"

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_legacy_tree_without_baseline_falls_back_to_timestamp(
        self, mock_fetch, mock_config, mock_auth, download_root
    ):
        # No _baseline/ (downloaded before baselines existed) → we cannot verify
        # content, so the stamp must still block. Never a silent pass.
        widget_dir = download_root / "global" / "sp_widget" / "my-widget"
        (widget_dir / "script.js").write_text("var x = 2;", encoding="utf-8")
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 99;",
            "sys_updated_on": "2025-01-15 12:00:00",
            "sys_updated_by": "bob",
            "sys_created_by": "admin",
            "sys_scope": "global",
        }

        result = update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(widget_dir / "script.js")),
        )

        assert result["error"] in ("CONFLICT", "CONFLICT_OTHER_USER")
        assert result["drift_verified_by"] == "timestamp"

    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_diff_reports_stale_watermark_instead_of_phantom_conflict(
        self, mock_fetch, mock_config, mock_auth, download_root
    ):
        widget_dir = download_root / "global" / "sp_widget" / "my-widget"
        self._seed_baseline(widget_dir, **{"script.js": "var x = 1;"})
        mock_fetch.return_value = {
            "sys_id": "wid-1",
            "name": "my-widget",
            "script": "var x = 1;",
            "sys_updated_on": "2025-01-15 12:00:00",
            "sys_updated_by": "admin",
            "sys_created_by": "admin",
        }

        result = diff_local_component(
            mock_config,
            mock_auth,
            DiffLocalComponentParams(path=str(widget_dir / "script.js")),
        )

        assert result["conflict_warning"] is None
        assert "no server-side source change" in result["stale_watermark"]

    @patch("servicenow_mcp.tools.sync_tools._write_sync_meta")
    @patch("servicenow_mcp.tools.sync_tools.update_portal_component")
    @patch("servicenow_mcp.tools.sync_tools._fetch_portal_component_record")
    def test_push_records_editor_so_next_diff_has_a_real_baseline_owner(
        self, mock_fetch, mock_update, mock_write_meta, mock_config, mock_auth, download_root
    ):
        # Dropping sys_updated_by here is what made a settled push re-litigate
        # itself: the next diff compared the current editor (me) against a
        # baseline owner still holding the ORIGINAL author's name.
        widget_dir = download_root / "global" / "sp_widget" / "my-widget"
        (widget_dir / "script.js").write_text("var x = 2;", encoding="utf-8")
        mock_fetch.side_effect = [
            {
                "sys_id": "wid-1",
                "name": "my-widget",
                "script": "var x = 1;",
                "sys_updated_on": "2025-01-10 10:00:00",
                "sys_updated_by": "admin",
                "sys_created_by": "admin",
                "sys_scope": "global",
            },
            # Landing verification re-read: the pushed body persisted, and the
            # editor rides along on the SAME fetch (no extra call) to become the
            # baseline owner.
            {
                "sys_id": "wid-1",
                "script": "var x = 2;",
                "sys_updated_on": "2025-01-16 09:00:00",
                "sys_updated_by": "admin",
            },
        ]
        mock_update.return_value = {"message": "Update successful", "sys_id": "wid-1"}

        update_remote_from_local(
            mock_config,
            mock_auth,
            PushLocalComponentParams(path=str(widget_dir / "script.js")),
        )

        written = mock_write_meta.call_args[0][1]
        assert written["my-widget"]["sys_updated_by"] == "admin"
        assert written["my-widget"]["sys_updated_on"] == "2025-01-16 09:00:00"
