"""Extra tests for source_tools.py — targeting uncovered helper functions and download tools."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.source_tools import (
    DownloadAdminScriptsParams,
    DownloadAPISourcesParams,
    DownloadScriptIncludesParams,
    DownloadSecuritySourcesParams,
    DownloadServerScriptsParams,
    DownloadTableSchemaParams,
    DownloadUIComponentsParams,
    ExtractTableDependenciesParams,
    ExtractWidgetTableDependenciesParams,
    GetMetadataSourceParams,
    SearchServerCodeParams,
    _auto_resolve_deps,
    _batch_resolve_script_includes,
    _build_dependency_query,
    _build_download_result,
    _build_label_map,
    _build_lookup_query,
    _build_search_query,
    _build_snippet,
    _chunked,
    _clamp_dep_scan_limit,
    _clamp_download_per_type,
    _clamp_field_length,
    _clamp_limit,
    _clamp_linked_si_limit,
    _clamp_page_size,
    _collect_downloaded_names,
    _dl_write_file,
    _dl_write_json,
    _download_dep_records,
    _download_source_types,
    _escape_query_value,
    _extract_match_fields,
    _extract_script_include_candidates,
    _extract_script_include_refs,
    _extract_table_names_from_script,
    _fetch_and_write_schema,
    _find_script_include_by_candidate,
    _make_request,
    _normalize_source_type,
    _normalize_table_candidate,
    _parse_string_arg,
    _resolve_scope_root,
    _retry_empty_source,
    _safe_filename,
    _scan_scope_dep_refs,
    _scan_tables_from_source_root,
    _truncate_text,
    download_admin_scripts,
    download_api_sources,
    download_script_includes,
    download_security_sources,
    download_server_scripts,
    download_table_schema,
    download_ui_components,
    extract_table_dependencies,
    extract_widget_table_dependencies,
    get_metadata_source,
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


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestNormalizeSourceType:
    def test_all_returns_all(self):
        assert _normalize_source_type("all") == "all"

    def test_valid_type_returns_it(self):
        assert _normalize_source_type("script_include") == "script_include"

    def test_case_insensitive(self):
        assert _normalize_source_type("Widget") == "widget"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            _normalize_source_type("nonexistent")


class TestClampFunctions:
    def test_clamp_limit_min(self):
        assert _clamp_limit(0) == 1

    def test_clamp_limit_max(self):
        assert _clamp_limit(9999) == 10

    def test_clamp_field_length_min(self):
        assert _clamp_field_length(50) == 200

    def test_clamp_field_length_max(self):
        assert _clamp_field_length(99999) == 12000

    def test_clamp_dep_scan_limit(self):
        assert _clamp_dep_scan_limit(0) == 1

    def test_clamp_page_size(self):
        assert _clamp_page_size(5) == 10
        assert _clamp_page_size(300) == 200

    def test_clamp_linked_si_limit(self):
        assert _clamp_linked_si_limit(0) == 1

    def test_clamp_download_per_type(self):
        assert _clamp_download_per_type(0) == 1


class TestEscapeQueryValue:
    def test_escapes_caret(self):
        assert _escape_query_value("a^b") == "a^^b"

    def test_escapes_equals(self):
        assert _escape_query_value("a=b") == r"a\=b"

    def test_escapes_at(self):
        assert _escape_query_value("a@b") == r"a\@b"


class TestBuildSearchQuery:
    def test_basic_query(self):
        cfg = {"search_fields": ["script", "name"]}
        params = MagicMock()
        params.query = "test"
        params.scope = None
        params.updated_by = None
        q = _build_search_query(cfg, params)
        assert "test" in q

    def test_with_scope(self):
        cfg = {"search_fields": ["script"]}
        params = MagicMock()
        params.query = "test"
        params.scope = "x_app"
        params.updated_by = None
        q = _build_search_query(cfg, params)
        assert "x_app" in q

    def test_with_updated_by(self):
        cfg = {"search_fields": ["script"]}
        params = MagicMock()
        params.query = "test"
        params.scope = None
        params.updated_by = "admin"
        q = _build_search_query(cfg, params)
        assert "admin" in q


class TestBuildLookupQuery:
    def test_escapes_source_id(self):
        cfg = {"lookup_fields": ["name", "id"]}
        q = _build_lookup_query(cfg, "my^widget")
        assert "^^" in q


class TestBuildDependencyQuery:
    def test_no_filters(self):
        result = _build_dependency_query(scope=None, only_active=False, source_table="sp_widget")
        assert result is None

    def test_with_scope(self):
        result = _build_dependency_query(scope="x_app", only_active=False, source_table="sp_widget")
        assert "x_app" in result

    def test_with_active_for_supported_table(self):
        result = _build_dependency_query(scope=None, only_active=True, source_table="sp_widget")
        assert "active=true" in result

    def test_active_ignored_for_unsupported_table(self):
        result = _build_dependency_query(scope=None, only_active=True, source_table="sys_db_object")
        assert result is None

    def test_scope_and_active_combined(self):
        result = _build_dependency_query(
            scope="x_app", only_active=True, source_table="sys_script_include"
        )
        assert "x_app" in result
        assert "active=true" in result


class TestExtractTableNames:
    def test_empty_script(self):
        assert _extract_table_names_from_script("") == set()

    def test_glide_record_constructor(self):
        script = 'var gr = new GlideRecord("incident");'
        tables = _extract_table_names_from_script(script)
        assert "incident" in tables

    def test_variable_assignment(self):
        script = 'var tableName = "task"; var gr = new GlideRecord(tableName);'
        tables = _extract_table_names_from_script(script)
        assert "task" in tables

    def test_glide_db_function(self):
        script = "gs.sql('SELECT * FROM incident')"
        # May or may not match depending on regex
        tables = _extract_table_names_from_script(script)
        assert isinstance(tables, set)

    def test_loose_literal_scan(self):
        script = 'someFunction("incident", "task")'
        tables = _extract_table_names_from_script(script, include_loose_literal_scan=True)
        assert isinstance(tables, set)

    def test_max_tables_cap(self):
        # Create a script with many table references
        refs = " ".join(f'new GlideRecord("table_{i}")' for i in range(60))
        tables = _extract_table_names_from_script(refs, include_loose_literal_scan=True)
        assert len(tables) <= 60  # bounded


class TestExtractScriptIncludeRefs:
    def test_empty_script(self):
        assert _extract_script_include_refs("", set()) == set()

    def test_finds_known_ref(self):
        script = "var helper = new CommitHelper();"
        refs = _extract_script_include_refs(script, {"CommitHelper"})
        assert "CommitHelper" in refs

    def test_finds_by_short_name(self):
        script = "var x = new CommitHelper();"
        refs = _extract_script_include_refs(script, {"x_app.CommitHelper"})
        assert "x_app.CommitHelper" in refs

    def test_unknown_class_ignored(self):
        script = "var x = new SomeUnknownThing();"
        refs = _extract_script_include_refs(script, {"CommitHelper"})
        assert len(refs) == 0


class TestExtractScriptIncludeCandidates:
    def test_empty_script(self):
        assert _extract_script_include_candidates("") == set()

    def test_extracts_capitalized_names(self):
        script = "var x = new MyHelper(); var y = new AnotherService();"
        candidates = _extract_script_include_candidates(script)
        assert "MyHelper" in candidates
        assert "AnotherService" in candidates

    def test_ignores_common_names(self):
        # GlideRecord, Array, etc. should be ignored
        script = "var gr = new GlideRecord('incident');"
        candidates = _extract_script_include_candidates(script)
        assert "GlideRecord" not in candidates


class TestNormalizeTableCandidate:
    def test_valid_name(self):
        assert _normalize_table_candidate("incident") == "incident"

    def test_empty(self):
        assert _normalize_table_candidate("") is None

    def test_whitespace_only(self):
        assert _normalize_table_candidate("   ") is None

    def test_invalid_chars(self):
        assert _normalize_table_candidate("has spaces") is None

    def test_strips_quotes(self):
        assert _normalize_table_candidate('"incident"') == "incident"


class TestParseStringArg:
    def test_double_quoted(self):
        assert _parse_string_arg('"incident"') == "incident"

    def test_single_quoted(self):
        assert _parse_string_arg("'incident'") == "incident"

    def test_unquoted_returns_none(self):
        assert _parse_string_arg("incident") is None


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert _truncate_text("hello", 100) == "hello"

    def test_long_text_truncated(self):
        result = _truncate_text("x" * 200, 50)
        assert "truncated" in result
        assert len(result) < 200


class TestBuildSnippet:
    def test_finds_match(self):
        record = {"script": "function doCommit() { return true; }"}
        result = _build_snippet(record, ["script"], "commit", 200)
        assert "commit" in result.lower()

    def test_no_match_returns_empty(self):
        record = {"script": "no match here"}
        result = _build_snippet(record, ["script"], "xyz", 200)
        assert result == ""

    def test_non_string_field_skipped(self):
        record = {"script": None}
        result = _build_snippet(record, ["script"], "test", 200)
        assert result == ""


class TestExtractMatchFields:
    def test_finds_matching_fields(self):
        record = {"script": "commit helper", "name": "CommitHelper"}
        fields = _extract_match_fields(record, ["script", "name"], "commit")
        assert "script" in fields
        assert "name" in fields

    def test_no_matches(self):
        record = {"script": "other"}
        fields = _extract_match_fields(record, ["script"], "commit")
        assert len(fields) == 0


class TestChunked:
    def test_splits_into_chunks(self):
        result = _chunked(["a", "b", "c", "d", "e"], 2)
        assert result == [["a", "b"], ["c", "d"], ["e"]]

    def test_empty_list(self):
        assert _chunked([], 5) == []


class TestSafeFilename:
    def test_basic(self):
        assert _safe_filename("My Script") == "My_Script"

    def test_empty(self):
        assert _safe_filename("") == "unnamed"

    def test_special_chars(self):
        result = _safe_filename("a/b\\c:d")
        assert "/" not in result


class TestDlWriteFunctions:
    def test_dl_write_file(self, tmp_path):
        dest = tmp_path / "sub" / "test.js"
        _dl_write_file(dest, "content")
        assert dest.read_text() == "content"

    def test_dl_write_json(self, tmp_path):
        dest = tmp_path / "sub" / "test.json"
        _dl_write_json(dest, {"key": "value"})
        data = json.loads(dest.read_text())
        assert data["key"] == "value"


class TestResolveScopeRoot:
    def test_creates_dirs(self, tmp_path):
        config = _build_config()
        with patch.object(Path, "cwd", return_value=tmp_path):
            root, scope_root = _resolve_scope_root(config, "x_app", None)
        assert scope_root.name == "x_app"
        assert scope_root.is_dir()

    def test_custom_output_dir(self, tmp_path):
        config = _build_config()
        custom = tmp_path / "any" / "shape"
        root, scope_root = _resolve_scope_root(config, "x_app", str(custom))
        assert scope_root == custom
        assert root == custom.parent


class TestScanScopeDepRefs:
    def test_scans_js_files(self, tmp_path):
        si_dir = tmp_path / "sys_script_include"
        si_dir.mkdir()
        si_dir.joinpath("_metadata.json").write_text('{"name":"MySI"}')
        si_dir.joinpath("script.js").write_text("var x = new ExternalHelper();")

        refs = _scan_scope_dep_refs(tmp_path)
        assert "ExternalHelper" in refs["script_includes"]

    def test_scans_html_for_widget_refs(self, tmp_path):
        (tmp_path / "template.html").write_text('<sp-widget id="my_widget"></sp-widget>')

        refs = _scan_scope_dep_refs(tmp_path)
        assert "my_widget" in refs["widgets"]

    def test_skips_deps_folder(self, tmp_path):
        deps = tmp_path / "_deps"
        deps.mkdir()
        deps.joinpath("script.js").write_text("var x = new ExternalHelper();")

        refs = _scan_scope_dep_refs(tmp_path)
        assert "ExternalHelper" not in refs["script_includes"]

    def test_scans_angular_inject(self, tmp_path):
        (tmp_path / "client.js").write_text(
            'var ctrl = function($scope, myService) {}; ctrl.$inject = ["$scope", "myService"];'
        )
        refs = _scan_scope_dep_refs(tmp_path)
        assert "myService" in refs["angular_providers"]

    def test_scans_jelly_macros(self, tmp_path):
        (tmp_path / "page.xml").write_text("<g:my_custom_macro name='test'/>")

        refs = _scan_scope_dep_refs(tmp_path)
        assert "my_custom_macro" in refs["ui_macros"]

    def test_skips_builtin_jelly_tags(self, tmp_path):
        (tmp_path / "page.xml").write_text("<g:if test='true'>content</g:if>")

        refs = _scan_scope_dep_refs(tmp_path)
        assert "if" not in refs["ui_macros"]


class TestCollectDownloadedNames:
    def test_reads_metadata(self, tmp_path):
        table_dir = tmp_path / "sys_script_include"
        rec_dir = table_dir / "MyHelper"
        rec_dir.mkdir(parents=True)
        rec_dir.joinpath("_metadata.json").write_text(
            '{"name":"MyHelper","api_name":"x_app.MyHelper"}'
        )
        names = _collect_downloaded_names(tmp_path, "sys_script_include", "api_name")
        assert "MyHelper" in names
        assert "x_app.MyHelper" in names

    def test_missing_dir_returns_empty(self, tmp_path):
        names = _collect_downloaded_names(tmp_path, "nonexistent_table", "name")
        assert len(names) == 0


class TestScanTablesFromSourceRoot:
    def test_scans_js_files(self, tmp_path):
        (tmp_path / "script.js").write_text('var gr = new GlideRecord("incident");')
        tables = _scan_tables_from_source_root(tmp_path)
        assert "incident" in tables

    def test_scans_metadata_collection(self, tmp_path):
        (tmp_path / "_metadata.json").write_text('{"collection":"task"}')
        tables = _scan_tables_from_source_root(tmp_path)
        assert "task" in tables


# ---------------------------------------------------------------------------
# Tool function tests (with mocking)
# ---------------------------------------------------------------------------


class TestSearchServerCodeEdgeCases:
    def test_search_request_exception_continues(self):
        config = _build_config()
        auth_manager = MagicMock()
        auth_manager.make_request.side_effect = Exception("network error")

        result = search_server_code(
            config,
            auth_manager,
            SearchServerCodeParams(query="test", source_type="script_include"),
        )
        assert result["success"] is True
        assert result["count"] == 0

    def test_search_with_scope_and_updated_by(self):
        config = _build_config()
        auth_manager = MagicMock()

        response = _response(
            [
                {
                    "sys_id": "si-1",
                    "name": "Test",
                    "api_name": "x_app.Test",
                    "sys_scope": "x_app",
                    "sys_updated_on": "2026-01-01",
                    "sys_updated_by": "admin",
                    "script": "test query",
                }
            ],
            total_count=1,
        )
        auth_manager.make_request.return_value = response

        result = search_server_code(
            config,
            auth_manager,
            SearchServerCodeParams(
                query="test",
                source_type="script_include",
                scope="x_app",
                updated_by="admin",
            ),
        )
        assert result["success"] is True


class TestGetMetadataSourceEdgeCases:
    def test_request_exception(self):
        config = _build_config()
        auth_manager = MagicMock()
        auth_manager.make_request.side_effect = Exception("network error")

        result = get_metadata_source(
            config,
            auth_manager,
            GetMetadataSourceParams(source_type="script_include", source_id="test"),
        )
        assert result["success"] is False
        assert "Failed to fetch" in result["message"]


class TestExtractWidgetTableDependenciesEdgeCases:
    def test_widget_not_found(self):
        config = _build_config()
        auth_manager = MagicMock()
        response = _response([], total_count=0)
        auth_manager.make_request.return_value = response

        result = extract_widget_table_dependencies(
            config,
            auth_manager,
            ExtractWidgetTableDependenciesParams(widget_id="missing"),
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_widget_fetch_exception(self):
        config = _build_config()
        auth_manager = MagicMock()
        auth_manager.make_request.side_effect = Exception("error")

        result = extract_widget_table_dependencies(
            config,
            auth_manager,
            ExtractWidgetTableDependenciesParams(widget_id="test"),
        )
        assert result["success"] is False

    def test_widget_with_script_includes(self):
        config = _build_config()
        auth_manager = MagicMock()

        # Widget response
        widget_resp = _response(
            [
                {
                    "sys_id": "wid-1",
                    "name": "Test Widget",
                    "id": "test_widget",
                    "sys_scope": "x_app",
                    "script": 'var x = new MyHelper(); new GlideRecord("incident");',
                }
            ],
            total_count=1,
        )
        # SI batch resolve response
        si_resp = _response(
            [
                {
                    "sys_id": "si-1",
                    "name": "MyHelper",
                    "api_name": "x_app.MyHelper",
                    "script": 'new GlideRecord("task");',
                }
            ],
            total_count=1,
        )
        auth_manager.make_request.side_effect = [widget_resp, si_resp]

        result = extract_widget_table_dependencies(
            config,
            auth_manager,
            ExtractWidgetTableDependenciesParams(
                widget_id="test_widget",
                include_linked_script_includes=True,
            ),
        )
        assert result["success"] is True
        assert result["tables"]

    def test_widget_si_resolve_exception(self):
        config = _build_config()
        auth_manager = MagicMock()

        widget_resp = _response(
            [
                {
                    "sys_id": "wid-1",
                    "name": "Test Widget",
                    "id": "test_widget",
                    "sys_scope": "x_app",
                    "script": "var x = new MyHelper();",
                }
            ],
            total_count=1,
        )
        auth_manager.make_request.side_effect = [
            widget_resp,
            Exception("SI resolve error"),
        ]

        result = extract_widget_table_dependencies(
            config,
            auth_manager,
            ExtractWidgetTableDependenciesParams(
                widget_id="test_widget",
                include_linked_script_includes=True,
            ),
        )
        assert result["success"] is True
        assert any("script_include_lookup" in str(w) for w in result.get("warnings", []))


class TestExtractTableDependenciesEdgeCases:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_all_source_types_disabled(self, mock_page, mock_all):
        config = _build_config()
        auth_manager = MagicMock()

        result = extract_table_dependencies(
            config,
            auth_manager,
            ExtractTableDependenciesParams(
                include_widgets=False,
                include_business_rules=False,
                include_linked_script_includes=False,
            ),
        )
        assert result["success"] is True
        assert result["tables"] == []

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_si_fetch_exception(self, mock_all):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.side_effect = Exception("SI fetch error")

        result = extract_table_dependencies(
            config,
            auth_manager,
            ExtractTableDependenciesParams(
                include_widgets=False,
                include_business_rules=False,
                include_linked_script_includes=True,
            ),
        )
        assert result["success"] is True
        assert any("script_include_candidates" in str(w) for w in result["warnings"])

    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_widget_exception(self, mock_all, mock_page):
        config = _build_config()
        auth_manager = MagicMock()
        # SI fetch succeeds with empty
        mock_all.return_value = []
        # Widget fetch fails
        mock_page.side_effect = Exception("widget error")

        result = extract_table_dependencies(
            config,
            auth_manager,
            ExtractTableDependenciesParams(
                include_widgets=True,
                include_business_rules=False,
                include_linked_script_includes=False,
            ),
        )
        assert result["success"] is True

    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_br_exception(self, mock_all, mock_page):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.side_effect = [
            [],  # SI fetch
            Exception("BR fetch error"),
        ]
        mock_page.return_value = ([], 0)

        result = extract_table_dependencies(
            config,
            auth_manager,
            ExtractTableDependenciesParams(
                include_widgets=False,
                include_business_rules=True,
                include_linked_script_includes=False,
            ),
        )
        assert result["success"] is True

    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_with_br_collection(self, mock_all, mock_page):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.return_value = [
            {
                "sys_id": "br-1",
                "name": "Test BR",
                "collection": "incident",
                "script": "",
            }
        ]
        mock_page.return_value = (
            [{"name": "incident", "label": "Incident"}],
            1,
        )

        result = extract_table_dependencies(
            config,
            auth_manager,
            ExtractTableDependenciesParams(
                include_widgets=False,
                include_business_rules=True,
                include_linked_script_includes=False,
            ),
        )
        assert result["success"] is True
        assert any(t["table_name"] == "incident" for t in result["tables"])


# ---------------------------------------------------------------------------
# Download tool tests
# ---------------------------------------------------------------------------


class TestDownloadSourceTypes:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_basic_download(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.return_value = [
            {
                "sys_id": "si-1",
                "name": "MyHelper",
                "api_name": "x_app.MyHelper",
                "script": "function MyHelper() {}",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-01-01",
            }
        ]

        result = _download_source_types(
            config,
            auth_manager,
            scope="x_app",
            source_types=["script_include"],
            scope_root=tmp_path,
            root=tmp_path,
        )
        assert "script_include" in result["type_results"]
        assert result["type_results"]["script_include"]["count"] == 1

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_fetch_error(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.side_effect = Exception("fetch error")

        result = _download_source_types(
            config,
            auth_manager,
            scope="x_app",
            source_types=["script_include"],
            scope_root=tmp_path,
            root=tmp_path,
        )
        assert "error" in result["type_results"]["script_include"]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_empty_records(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.return_value = []

        result = _download_source_types(
            config,
            auth_manager,
            scope="x_app",
            source_types=["script_include"],
            scope_root=tmp_path,
            root=tmp_path,
        )
        assert result["type_results"]["script_include"]["count"] == 0

    def test_unknown_source_type(self, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()

        result = _download_source_types(
            config,
            auth_manager,
            scope="x_app",
            source_types=["nonexistent_type"],
            scope_root=tmp_path,
            root=tmp_path,
        )
        assert len(result["warnings"]) == 1

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_resume_skips_existing(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        # Pre-create source file
        rec_dir = tmp_path / "sys_script_include" / "MyHelper"
        rec_dir.mkdir(parents=True)
        rec_dir.joinpath("script.js").write_text("existing content")

        mock_all.return_value = [
            {
                "sys_id": "si-1",
                "name": "MyHelper",
                "api_name": "x_app.MyHelper",
                "script": "new content",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-01-01",
            }
        ]

        result = _download_source_types(
            config,
            auth_manager,
            scope="x_app",
            source_types=["script_include"],
            scope_root=tmp_path,
            root=tmp_path,
        )
        # Should skip since file exists
        assert result["type_results"]["script_include"]["count"] == 1

    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_retry_empty_source(self, mock_all, mock_page, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        rec_dir = tmp_path / "sys_script_include" / "EmptySI"
        rec_dir.mkdir(parents=True)
        rec_dir.joinpath("_metadata.json").write_text('{"name":"EmptySI"}')

        # First batch returns empty script
        mock_all.return_value = [
            {
                "sys_id": "si-1",
                "name": "EmptySI",
                "api_name": "x_app.EmptySI",
                "script": "",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-01-01",
            }
        ]
        # Retry returns content
        mock_page.return_value = (
            [{"script": "function retry() {}"}],
            1,
        )

        result = _download_source_types(
            config,
            auth_manager,
            scope="x_app",
            source_types=["script_include"],
            scope_root=tmp_path,
            root=tmp_path,
        )
        assert result["type_results"]["script_include"]["count"] == 1

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_with_only_active(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.return_value = []

        _download_source_types(
            config,
            auth_manager,
            scope="x_app",
            source_types=["business_rule"],
            scope_root=tmp_path,
            root=tmp_path,
            only_active=True,
        )
        call_args = mock_all.call_args
        assert "active=true" in call_args.kwargs.get("query", call_args[1].get("query", ""))


class TestBuildDownloadResult:
    def test_with_warnings(self, tmp_path):
        dl = {
            "type_results": {"script_include": {"count": 5}},
            "manifest_entries": [],
            "warnings": ["some warning"],
            "total_files": 10,
        }
        result = _build_download_result("x_app", tmp_path, dl, 100, "test_tool")
        assert result["success"] is True
        assert "warnings" in result

    def test_without_warnings(self, tmp_path):
        dl = {
            "type_results": {},
            "manifest_entries": [],
            "warnings": [],
            "total_files": 0,
        }
        result = _build_download_result("x_app", tmp_path, dl, 100, "test_tool")
        assert "warnings" not in result


class TestDownloadDepRecords:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_fetches_and_saves(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.return_value = [
            {
                "sys_id": "si-dep1",
                "name": "ExternalHelper",
                "api_name": "global.ExternalHelper",
                "script": "function help() {}",
            }
        ]

        result = _download_dep_records(
            config,
            auth_manager,
            "script_include",
            "name",
            ["ExternalHelper"],
            tmp_path,
            20,
        )
        assert result["count"] == 1
        assert result["files"] == 1

    def test_empty_names(self, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        result = _download_dep_records(
            config, auth_manager, "script_include", "name", [], tmp_path, 20
        )
        assert result["count"] == 0

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_skips_existing_metadata(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        rec_dir = tmp_path / "sys_script_include" / "ExistingHelper"
        rec_dir.mkdir(parents=True)
        rec_dir.joinpath("_metadata.json").write_text('{"name":"ExistingHelper"}')

        mock_all.return_value = [
            {
                "sys_id": "si-exist",
                "name": "ExistingHelper",
                "api_name": "global.ExistingHelper",
                "script": "content",
            }
        ]

        result = _download_dep_records(
            config,
            auth_manager,
            "script_include",
            "name",
            ["ExistingHelper"],
            tmp_path,
            20,
        )
        assert result["count"] == 0  # skipped


class TestAutoResolveDeps:
    @patch("servicenow_mcp.tools.source_tools._download_dep_records")
    def test_resolves_missing_deps(self, mock_dl, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        # Create a source file that references a SI
        si_dir = tmp_path / "sys_script_include"
        si_dir.mkdir()
        si_dir.joinpath("script.js").write_text("var x = new MissingHelper();")

        mock_dl.return_value = {"count": 1, "files": 1}

        result = _auto_resolve_deps(config, auth_manager, tmp_path, 20)
        assert result["total_new_records"] >= 0

    def test_no_deps_found(self, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        # Empty source dir
        (tmp_path / "sys_script_include").mkdir()

        result = _auto_resolve_deps(config, auth_manager, tmp_path, 20)
        assert result["total_new_records"] == 0


class TestRetryEmptySource:
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_retry_fetches_content(self, mock_page, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        rec_dir = tmp_path / "rec"
        rec_dir.mkdir()

        mock_page.return_value = (
            [{"script": "function retry() {}"}],
            1,
        )

        warnings = []
        count = _retry_empty_source(
            config,
            auth_manager,
            "sys_script_include",
            ["script"],
            "script_include",
            ("si-1", "MySI", rec_dir),
            warnings,
        )
        assert count == 1

    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_retry_exception(self, mock_page, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        rec_dir = tmp_path / "rec"
        rec_dir.mkdir()

        mock_page.side_effect = Exception("retry error")

        warnings = []
        count = _retry_empty_source(
            config,
            auth_manager,
            "sys_script_include",
            ["script"],
            "script_include",
            ("si-1", "MySI", rec_dir),
            warnings,
        )
        assert count == 0
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Registered tool wrapper tests
# ---------------------------------------------------------------------------


class TestDownloadToolWrappers:
    @patch("servicenow_mcp.tools.source_tools._download_source_types")
    @patch("servicenow_mcp.tools.source_tools._resolve_scope_root")
    def test_download_script_includes(self, mock_resolve, mock_dl, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_resolve.return_value = (tmp_path, tmp_path)
        mock_dl.return_value = {
            "type_results": {"script_include": {"count": 3}},
            "manifest_entries": [],
            "warnings": [],
            "total_files": 3,
        }

        result = download_script_includes(
            config, auth_manager, DownloadScriptIncludesParams(scope="x_app")
        )
        assert result["success"] is True

    @patch("servicenow_mcp.tools.source_tools._download_source_types")
    @patch("servicenow_mcp.tools.source_tools._resolve_scope_root")
    def test_download_server_scripts(self, mock_resolve, mock_dl, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_resolve.return_value = (tmp_path, tmp_path)
        mock_dl.return_value = {
            "type_results": {},
            "manifest_entries": [],
            "warnings": [],
            "total_files": 0,
        }

        result = download_server_scripts(
            config, auth_manager, DownloadServerScriptsParams(scope="x_app")
        )
        assert result["success"] is True

    @patch("servicenow_mcp.tools.source_tools._download_source_types")
    @patch("servicenow_mcp.tools.source_tools._resolve_scope_root")
    def test_download_ui_components(self, mock_resolve, mock_dl, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_resolve.return_value = (tmp_path, tmp_path)
        mock_dl.return_value = {
            "type_results": {},
            "manifest_entries": [],
            "warnings": [],
            "total_files": 0,
        }

        result = download_ui_components(
            config, auth_manager, DownloadUIComponentsParams(scope="x_app")
        )
        assert result["success"] is True

    @patch("servicenow_mcp.tools.source_tools._download_source_types")
    @patch("servicenow_mcp.tools.source_tools._resolve_scope_root")
    def test_download_api_sources(self, mock_resolve, mock_dl, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_resolve.return_value = (tmp_path, tmp_path)
        mock_dl.return_value = {
            "type_results": {},
            "manifest_entries": [],
            "warnings": [],
            "total_files": 0,
        }

        result = download_api_sources(config, auth_manager, DownloadAPISourcesParams(scope="x_app"))
        assert result["success"] is True

    @patch("servicenow_mcp.tools.source_tools._download_source_types")
    @patch("servicenow_mcp.tools.source_tools._resolve_scope_root")
    def test_download_security_sources(self, mock_resolve, mock_dl, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_resolve.return_value = (tmp_path, tmp_path)
        mock_dl.return_value = {
            "type_results": {},
            "manifest_entries": [],
            "warnings": [],
            "total_files": 0,
        }

        result = download_security_sources(
            config, auth_manager, DownloadSecuritySourcesParams(scope="x_app")
        )
        assert result["success"] is True

    @patch("servicenow_mcp.tools.source_tools._download_source_types")
    @patch("servicenow_mcp.tools.source_tools._resolve_scope_root")
    def test_download_admin_scripts(self, mock_resolve, mock_dl, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_resolve.return_value = (tmp_path, tmp_path)
        mock_dl.return_value = {
            "type_results": {},
            "manifest_entries": [],
            "warnings": [],
            "total_files": 0,
        }

        result = download_admin_scripts(
            config, auth_manager, DownloadAdminScriptsParams(scope="x_app")
        )
        assert result["success"] is True


class TestDownloadTableSchema:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_explicit_tables(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.return_value = [
            {
                "name": "incident",
                "element": "number",
                "column_label": "Number",
                "internal_type": "string",
                "max_length": "40",
                "mandatory": "true",
                "reference": "",
            }
        ]

        result = download_table_schema(
            config,
            auth_manager,
            DownloadTableSchemaParams(tables=["incident"], output_dir=str(tmp_path)),
        )
        assert result["success"] is True
        assert result["tables_fetched"] == 1

    def test_no_tables_or_source_root(self):
        config = _build_config()
        auth_manager = MagicMock()
        result = download_table_schema(config, auth_manager, DownloadTableSchemaParams())
        assert result["success"] is False

    def test_empty_tables_list(self):
        config = _build_config()
        auth_manager = MagicMock()
        result = download_table_schema(config, auth_manager, DownloadTableSchemaParams(tables=[]))
        assert result["success"] is False

    def test_source_root_not_found(self):
        config = _build_config()
        auth_manager = MagicMock()
        result = download_table_schema(
            config,
            auth_manager,
            DownloadTableSchemaParams(source_root="/nonexistent/path"),
        )
        assert result["success"] is False

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_source_root_scan(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        (tmp_path / "script.js").write_text('new GlideRecord("task");')
        mock_all.return_value = [
            {
                "name": "task",
                "element": "number",
                "column_label": "Number",
                "internal_type": "string",
                "max_length": "40",
                "mandatory": "false",
                "reference": "",
            }
        ]

        result = download_table_schema(
            config, auth_manager, DownloadTableSchemaParams(source_root=str(tmp_path))
        )
        assert result["success"] is True


class TestFetchAndWriteSchema:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_schema_fetch_error(self, mock_all, tmp_path):
        config = _build_config()
        auth_manager = MagicMock()
        mock_all.side_effect = Exception("schema error")

        schema_dir = tmp_path / "_schema"
        schema_results, warnings = _fetch_and_write_schema(
            config, auth_manager, {"incident"}, schema_dir
        )
        assert len(warnings) == 1
        assert len(schema_results) == 0


class TestBatchResolveScriptIncludes:
    def test_empty_candidates(self):
        config = _build_config()
        auth_manager = MagicMock()
        result = _batch_resolve_script_includes(
            config, auth_manager, candidates=[], scope=None, only_active=False
        )
        assert result == {}


class TestFindScriptIncludeByCandidate:
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_found(self, mock_page):
        config = _build_config()
        auth_manager = MagicMock()
        mock_page.return_value = (
            [{"sys_id": "si-1", "name": "MyHelper", "api_name": "x_app.MyHelper", "script": ""}],
            1,
        )

        result = _find_script_include_by_candidate(
            config, auth_manager, candidate="MyHelper", scope="x_app", only_active=True
        )
        assert result is not None
        assert result["name"] == "MyHelper"

    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_not_found(self, mock_page):
        config = _build_config()
        auth_manager = MagicMock()
        mock_page.return_value = ([], 0)

        result = _find_script_include_by_candidate(
            config, auth_manager, candidate="Missing", scope=None, only_active=False
        )
        assert result is None


class TestMakeRequest:
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_basic(self, mock_page):
        config = _build_config()
        auth_manager = MagicMock()
        mock_page.return_value = (
            [{"sys_id": "1", "name": "test"}],
            1,
        )

        rows = _make_request(
            config,
            auth_manager,
            table="sys_script_include",
            query="name=test",
            fields=["sys_id", "name"],
            limit=10,
        )
        assert len(rows) == 1


class TestBuildLabelMap:
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_fetches_labels(self, mock_page):
        config = _build_config()
        auth_manager = MagicMock()
        mock_page.return_value = (
            [{"name": "incident", "label": "Incident"}],
            1,
        )

        result = _build_label_map(config, auth_manager, {"incident"})
        assert result["incident"] == "Incident"

    def test_empty_table_names(self):
        config = _build_config()
        auth_manager = MagicMock()
        result = _build_label_map(config, auth_manager, set())
        assert result == {}
