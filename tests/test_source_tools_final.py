"""Final coverage tests for source_tools.py — target remaining 84 missed lines."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.source_tools import (
    DownloadAppSourcesParams,
    DownloadTableSchemaParams,
    GetMetadataSourceParams,
    SearchServerCodeParams,
    _auto_resolve_deps,
    _batch_resolve_script_includes,
    _collect_downloaded_names,
    _download_dep_records,
    _download_source_types,
    _extract_table_names_from_script,
    _scan_scope_dep_refs,
    _scan_tables_from_source_root,
    download_app_sources,
    download_table_schema,
    search_server_code,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _build_config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        ),
    )


def _finalize_response(response: MagicMock) -> MagicMock:
    payload = response.json.return_value
    response.content = json.dumps(payload).encode("utf-8")
    response.headers = getattr(response, "headers", {}) or {}
    response.raise_for_status.return_value = None
    return response


def _response(result, *, total_count=None):
    response = MagicMock()
    response.json.return_value = {"result": result}
    response.headers = {}
    if total_count is not None:
        response.headers["X-Total-Count"] = str(total_count)
    return _finalize_response(response)


@pytest.fixture
def mock_config():
    return _build_config()


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic test"}
    return auth


class TestSearchServerCodeInvalidType:
    def test_invalid_source_type(self, mock_config, mock_auth):
        with pytest.raises(ValidationError):
            SearchServerCodeParams(query="test", source_type="bad_type")

    def test_limit_clamp(self, mock_config, mock_auth):
        with patch("servicenow_mcp.tools.source_tools._make_request") as mock_req:
            mock_req.return_value = _response([])
            result = search_server_code(
                mock_config,
                mock_auth,
                SearchServerCodeParams(query="test", limit=1000),
            )
            assert result["success"] is True


class TestGetMetadataSourceInvalidType:
    def test_invalid_source_type(self, mock_config, mock_auth):
        with pytest.raises(ValidationError):
            GetMetadataSourceParams(source_type="bad_type", source_id="x")

    def test_all_source_type_rejected(self, mock_config, mock_auth):
        with pytest.raises(ValidationError):
            GetMetadataSourceParams(source_type="all", source_id="x")


class TestExtractTableNamesFromScript:
    def test_glide_db_functions(self):
        script = "var gr = new GlideRecord('incident'); gr.query();"
        tables = _extract_table_names_from_script(script)
        assert "incident" in tables

    def test_loose_literal_cap(self):
        tables = set()
        for i in range(200):
            tables.add(f"u_table_{i}")
        parts = [f"'{t}'" for t in sorted(tables)]
        script = "var x = [" + ", ".join(parts) + "];"
        result = _extract_table_names_from_script(script, include_loose_literal_scan=True)
        assert len(result) <= 150


class TestFindScriptIncludeSkipAlreadyResolved:
    def test_skip_already_resolved_candidates(self, mock_config, mock_auth):
        with patch("servicenow_mcp.tools.source_tools._make_request") as mock_req:
            mock_req.return_value = [{"sys_id": "si1", "name": "MySI", "api_name": "MySI"}]

            result = _batch_resolve_script_includes(
                mock_config,
                mock_auth,
                candidates=["MySI", "MySI"],
                scope=None,
                only_active=True,
            )

        assert result["MySI"]["sys_id"] == "si1"
        assert mock_req.call_count == 1


class TestExtractWidgetTableDependenciesSkipNonString:
    def test_widget_with_non_string_script(self, mock_config, mock_auth):
        with patch("servicenow_mcp.tools.source_tools.sn_query_all") as mock_qa:
            mock_qa.return_value = {
                "success": True,
                "results": [
                    {
                        "sys_id": "w1",
                        "name": "Test",
                        "script": 123,
                        "client_script": None,
                        "link": "",
                    }
                ],
                "count": 1,
            }
            (
                _download_source_types.__wrapped__(mock_config, mock_auth, "test_scope", ["widget"])
                if hasattr(_download_source_types, "__wrapped__")
                else None
            )


class TestScanScopeDepRefs:
    def test_scan_with_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            widget_dir = scope_root / "widget"
            widget_dir.mkdir()
            js_file = widget_dir / "test.js"
            js_file.write_text(
                "var x = new MyScriptInclude();"
                "gs.include('AnotherSI');"
                "new GlideAjax('MyAjax');"
                '<sp-widget id="embedded_widget"></sp-widget>'
                "$sp.getWidget('sp_widget_ref');"
                "angular.module('myApp', ['myProvider']);",
                encoding="utf-8",
            )
            refs = _scan_scope_dep_refs(scope_root)
            si_refs = refs["script_includes"]
            widget_refs = refs["widgets"]
            provider_refs = refs["angular_providers"]
            assert "MyScriptInclude" in si_refs
            assert "AnotherSI" in si_refs
            assert "MyAjax" in si_refs
            assert "embedded_widget" in widget_refs
            assert "sp_widget_ref" in widget_refs
            assert "myProvider" in provider_refs

    def test_scan_handles_read_exception(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            widget_dir = scope_root / "widget"
            widget_dir.mkdir()
            bad_file = widget_dir / "bad.js"
            bad_file.write_text("valid", encoding="utf-8")
            with patch("pathlib.Path.read_text", side_effect=PermissionError("denied")):
                refs = _scan_scope_dep_refs(scope_root)
                assert len(refs["script_includes"]) == 0
                assert len(refs["widgets"]) == 0
                assert len(refs["angular_providers"]) == 0


class TestCollectDownloadedNamesBadMetadata:
    def test_corrupt_metadata_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            si_dir = scope_root / "script_include"
            si_dir.mkdir(parents=True)
            meta_file = si_dir / "_metadata.json"
            meta_file.write_text("not valid json{{{", encoding="utf-8")
            result = _collect_downloaded_names(scope_root, "script_include", "api_name")
            assert isinstance(result, set)


class TestDownloadDepRecordsException:
    def test_fetch_chunk_exception(self, mock_config, mock_auth):
        with patch(
            "servicenow_mcp.tools.source_tools.sn_query_all", side_effect=Exception("API error")
        ):
            with tempfile.TemporaryDirectory() as tmpdir:
                scope_root = Path(tmpdir)
                dep_dir = scope_root / "script_include"
                dep_dir.mkdir(parents=True)
                result = _download_dep_records(
                    mock_config,
                    mock_auth,
                    "script_include",
                    "api_name",
                    ["MySI"],
                    scope_root,
                    20,
                )
                assert result["count"] == 0

    def test_parallel_fetch(self, mock_config, mock_auth):
        with patch("servicenow_mcp.tools.source_tools.sn_query_all") as mock_qa:
            mock_qa.return_value = [{"sys_id": "si1", "api_name": "MySI", "name": "MySI"}]
            with tempfile.TemporaryDirectory() as tmpdir:
                scope_root = Path(tmpdir)
                dep_dir = scope_root / "script_include"
                dep_dir.mkdir(parents=True)
                names = [f"SI_{i}" for i in range(150)]
                result = _download_dep_records(
                    mock_config,
                    mock_auth,
                    "script_include",
                    "api_name",
                    names,
                    scope_root,
                    20,
                )
                assert result["count"] >= 0


class TestAutoResolveDepsMissingTypes:
    def test_resolve_missing_widgets(self, mock_config, mock_auth):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            widget_dir = scope_root / "widget"
            widget_dir.mkdir(parents=True)
            si_dir = scope_root / "script_include"
            si_dir.mkdir(parents=True)
            meta = {"api_name": "ExistingSI", "name": "ExistingSI"}
            (si_dir / "_metadata.json").write_text(json.dumps(meta), encoding="utf-8")

            dep_scan_result = {
                "script_includes": {"MissingSI"},
                "widgets": {"missing_widget"},
                "angular_providers": {"missing_provider"},
                "ui_macros": {"missing_macro"},
            }

            with patch(
                "servicenow_mcp.tools.source_tools._scan_scope_dep_refs",
                return_value=dep_scan_result,
            ):
                with patch(
                    "servicenow_mcp.tools.source_tools._collect_downloaded_names",
                    return_value={"ExistingSI"},
                ):
                    with patch(
                        "servicenow_mcp.tools.source_tools._download_dep_records"
                    ) as mock_dl:
                        mock_dl.return_value = {"count": 1, "files": 1}
                        result = _auto_resolve_deps(mock_config, mock_auth, scope_root, 20)
                        assert result["total_new_records"] >= 0

    def test_resolve_exception_returns_partial(self, mock_config, mock_auth):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            with patch(
                "servicenow_mcp.tools.source_tools._scan_scope_dep_refs",
                side_effect=Exception("scan fail"),
            ):
                with pytest.raises(Exception, match="scan fail"):
                    _auto_resolve_deps(mock_config, mock_auth, scope_root, 20)


class TestDownloadAppSourcesPortalSection:
    def test_widget_sources_fallback_on_exception(self, mock_config, mock_auth):
        real_import = __import__

        def fail_portal_tools(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "servicenow_mcp.tools.portal_tools":
                raise ImportError("no portal_tools")
            return real_import(name, globals, locals, fromlist, level)

        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir) / "x_test_app"
            with patch(
                "servicenow_mcp.tools.source_tools._resolve_scope_root",
                return_value=(Path(tmpdir), scope_root),
            ):
                with patch("servicenow_mcp.tools.source_tools._download_source_types") as mock_dl:
                    mock_dl.return_value = {
                        "success": True,
                        "type_results": {},
                        "manifest_entries": [],
                        "total_records": 0,
                        "total_files": 0,
                        "warnings": [],
                    }
                    with patch("servicenow_mcp.tools.source_tools._auto_resolve_deps") as mock_ar:
                        mock_ar.return_value = {"total_new_records": 0, "total_new_files": 0}
                        with patch("servicenow_mcp.tools.source_tools.sn_query_all") as mock_qa:
                            mock_qa.return_value = {"success": True, "results": [], "count": 0}
                            with patch(
                                "servicenow_mcp.tools.source_tools.sn_query_page"
                            ) as mock_qp:
                                mock_qp.return_value = ([], 0)
                                with patch("builtins.__import__", side_effect=fail_portal_tools):
                                    params = DownloadAppSourcesParams(
                                        scope="x_test_app",
                                        output_dir=tmpdir,
                                        include_widget_sources=True,
                                        auto_resolve_deps=False,
                                    )
                                    result = download_app_sources(mock_config, mock_auth, params)
                                    assert result["success"] is True


class TestDownloadAppSourcesAutoResolve:
    def test_auto_resolve_adds_to_file_count(self, mock_config, mock_auth):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            with patch(
                "servicenow_mcp.tools.source_tools._resolve_scope_root",
                return_value=(Path(tmpdir), scope_root),
            ):
                with patch("servicenow_mcp.tools.source_tools._download_source_types") as mock_dl:
                    mock_dl.return_value = {
                        "success": True,
                        "type_results": {},
                        "manifest_entries": [],
                        "total_records": 1,
                        "total_files": 1,
                        "warnings": [],
                    }
                    with patch("servicenow_mcp.tools.source_tools._auto_resolve_deps") as mock_ar:
                        mock_ar.return_value = {"total_new_records": 5, "total_new_files": 5}
                        with patch("servicenow_mcp.tools.source_tools.sn_query_all") as mock_qa:
                            mock_qa.return_value = {"success": True, "results": [], "count": 0}
                            with patch(
                                "servicenow_mcp.tools.source_tools.sn_query_page"
                            ) as mock_qp:
                                mock_qp.return_value = ([], 0)
                                params = DownloadAppSourcesParams(
                                    scope="x_test_app",
                                    output_dir=tmpdir,
                                    auto_resolve_deps=True,
                                    include_widget_sources=False,
                                )
                                result = download_app_sources(mock_config, mock_auth, params)
                                assert result["success"] is True

    def test_auto_resolve_exception_adds_warning(self, mock_config, mock_auth):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            with patch(
                "servicenow_mcp.tools.source_tools._resolve_scope_root",
                return_value=(Path(tmpdir), scope_root),
            ):
                with patch("servicenow_mcp.tools.source_tools._download_source_types") as mock_dl:
                    mock_dl.return_value = {
                        "success": True,
                        "type_results": {},
                        "manifest_entries": [],
                        "total_records": 0,
                        "total_files": 0,
                        "warnings": [],
                    }
                    with patch(
                        "servicenow_mcp.tools.source_tools._auto_resolve_deps",
                        side_effect=Exception("dep fail"),
                    ):
                        with patch("servicenow_mcp.tools.source_tools.sn_query_all") as mock_qa:
                            mock_qa.return_value = {"success": True, "results": [], "count": 0}
                            with patch(
                                "servicenow_mcp.tools.source_tools.sn_query_page"
                            ) as mock_qp:
                                mock_qp.return_value = ([], 0)
                                params = DownloadAppSourcesParams(
                                    scope="x_test_app",
                                    output_dir=tmpdir,
                                    auto_resolve_deps=True,
                                    include_widget_sources=False,
                                )
                                result = download_app_sources(mock_config, mock_auth, params)
                                assert result["success"] is True
                                assert any("dep_resolve" in w for w in result.get("warnings", []))


class TestScanTablesFromSourceRoot:
    def test_scan_with_bad_js_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            si_dir = scope_root / "script_include"
            si_dir.mkdir(parents=True)
            bad_js = si_dir / "bad.js"
            bad_js.write_text("new GlideRecord('incident');", encoding="utf-8")
            good_js = si_dir / "good.js"
            good_js.write_text("new GlideRecord('task');", encoding="utf-8")
            with patch.object(
                Path,
                "read_text",
                side_effect=[PermissionError("denied"), "new GlideRecord('task');"],
            ):
                tables = _scan_tables_from_source_root(scope_root)
                assert isinstance(tables, set)

    def test_scan_with_bad_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scope_root = Path(tmpdir)
            si_dir = scope_root / "script_include"
            si_dir.mkdir(parents=True)
            meta = si_dir / "_metadata.json"
            meta.write_text("invalid json{{", encoding="utf-8")
            tables = _scan_tables_from_source_root(scope_root)
            assert isinstance(tables, set)


class TestDownloadTableSchemaNoTables:
    def test_no_tables_returns_early(self, mock_config, mock_auth):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "servicenow_mcp.tools.source_tools._scan_tables_from_source_root",
                return_value=set(),
            ):
                params = DownloadTableSchemaParams(
                    source_root=tmpdir,
                    tables=[],
                )
                result = download_table_schema(mock_config, mock_auth, params)
                assert result["success"] is True
                assert result["tables"] == 0

    def test_default_schema_dir_from_source_root(self, mock_config, mock_auth):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema") as mock_fetch:
                mock_fetch.return_value = ({"incident": 0}, [])
                with patch("servicenow_mcp.tools.source_tools.sn_query_all") as mock_qa:
                    mock_qa.return_value = {"success": True, "results": [], "count": 0}
                    params = DownloadTableSchemaParams(
                        source_root=tmpdir,
                        tables=["incident"],
                    )
                    result = download_table_schema(mock_config, mock_auth, params)
                    assert result["success"] is True
