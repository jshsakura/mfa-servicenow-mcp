"""Tests for individual download tools and the download_app_sources orchestrator.

Covers:
- _download_source_types (core loop)
- download_script_includes
- download_server_scripts
- download_ui_components
- download_api_sources
- download_security_sources
- download_admin_scripts
- download_table_schema
- download_app_sources (orchestrator)
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.source_tools import (
    DownloadAdminScriptsParams,
    DownloadAPISourcesParams,
    DownloadAppSourcesParams,
    DownloadScriptIncludesParams,
    DownloadSecuritySourcesParams,
    DownloadServerScriptsParams,
    DownloadTableSchemaParams,
    DownloadUIComponentsParams,
    _download_source_types,
    _resolve_scope_root,
    _safe_filename,
    download_admin_scripts,
    download_api_sources,
    download_app_sources,
    download_script_includes,
    download_security_sources,
    download_server_scripts,
    download_table_schema,
    download_ui_components,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def auth() -> MagicMock:
    return MagicMock()


def _si_records():
    return [
        {
            "sys_id": "si-1",
            "name": "CommitHelper",
            "api_name": "x_app.CommitHelper",
            "description": "Helps with commits",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-01 12:00:00",
            "sys_updated_by": "admin",
            "script": "var CommitHelper = Class.create();\nCommitHelper.prototype = {\n  validate: function() { return true; }\n};",
        },
        {
            "sys_id": "si-2",
            "name": "ApprovalUtil",
            "api_name": "x_app.ApprovalUtil",
            "description": "Approval utilities",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-02 10:00:00",
            "sys_updated_by": "dev1",
            "script": "var ApprovalUtil = Class.create();\nApprovalUtil.prototype = {\n  approve: function(gr) {\n    var task = new GlideRecord('task');\n    task.query();\n  }\n};",
        },
    ]


def _br_records():
    return [
        {
            "sys_id": "br-1",
            "name": "Validate Before Insert",
            "collection": "x_app_request",
            "when": "before",
            "active": "true",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-01 14:00:00",
            "sys_updated_by": "admin",
            "script": "(function executeRule(current, previous) {\n  if (!current.short_description) {\n    gs.addErrorMessage('Required');\n  }\n})(current, previous);",
        },
    ]


def _ui_action_records():
    return [
        {
            "sys_id": "ua-1",
            "name": "Approve Request",
            "table": "x_app_request",
            "action_name": "approve",
            "active": "true",
            "client": "false",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-01 15:00:00",
            "sys_updated_by": "admin",
            "script": "current.state = 'approved';\ncurrent.update();",
        },
    ]


def _rest_records():
    return [
        {
            "sys_id": "rest-1",
            "name": "Get Request Status",
            "http_method": "GET",
            "active": "true",
            "web_service_definition": "RequestAPI",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-01 16:00:00",
            "sys_updated_by": "admin",
            "operation_script": "(function process(request, response) {\n  var gr = new GlideRecord('x_app_request');\n  response.setBody({status: 'ok'});\n})(request, response);",
        },
    ]


def _acl_records():
    return [
        {
            "sys_id": "acl-1",
            "name": "x_app_request.read",
            "type": "record",
            "operation": "read",
            "active": "true",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-01 17:00:00",
            "sys_updated_by": "admin",
            "script": "answer = gs.hasRole('x_app.user');",
        },
    ]


def _fix_script_records():
    return [
        {
            "sys_id": "fix-1",
            "name": "Migrate Legacy Data",
            "description": "One-time migration",
            "active": "false",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-01 18:00:00",
            "sys_updated_by": "admin",
            "script": "var gr = new GlideRecord('x_app_legacy');\ngr.query();\nwhile (gr.next()) { gr.deleteRecord(); }",
        },
    ]


# Source fields per source type — must be stripped from sn_query_all mocks
# and returned by sn_query_page mocks in the 2-pass download model.
_SOURCE_FIELDS = {
    "script",
    "operation_script",
    "html",
    "client_script",
    "processing_script",
}


def _strip_source(records):
    """Return records with source fields removed (Pass 1 metadata only)."""
    return [{k: v for k, v in r.items() if k not in _SOURCE_FIELDS} for r in records]


def _page_side_effect_for(full_records):
    """Build a sn_query_page side_effect that returns source fields by sys_id."""

    def _side_effect(*args, **kwargs):
        query = kwargs.get("query", "")
        for r in full_records:
            if r["sys_id"] in query:
                src = {k: v for k, v in r.items() if k in _SOURCE_FIELDS and v}
                return ([src], None) if src else ([], None)
        return ([], None)

    return _side_effect


def _dict_records():
    return [
        {
            "name": "x_app_request",
            "element": "short_description",
            "column_label": "Short description",
            "internal_type": "string",
            "max_length": "160",
            "mandatory": "true",
            "reference": "",
        },
        {
            "name": "x_app_request",
            "element": "state",
            "column_label": "State",
            "internal_type": "string",
            "max_length": "40",
            "mandatory": "false",
            "reference": "",
        },
        {
            "name": "x_app_request",
            "element": "assigned_to",
            "column_label": "Assigned to",
            "internal_type": "reference",
            "max_length": "32",
            "mandatory": "false",
            "reference": "sys_user",
        },
        {
            "name": "task",
            "element": "number",
            "column_label": "Number",
            "internal_type": "string",
            "max_length": "40",
            "mandatory": "true",
            "reference": "",
        },
    ]


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------


class TestSafeFilename:
    def test_normal_name(self):
        assert _safe_filename("CommitHelper") == "CommitHelper"

    def test_special_characters(self):
        assert _safe_filename("My Script / Include") == "My_Script_Include"

    def test_dots_and_dashes(self):
        assert _safe_filename("x_app.CommitHelper") == "x_app.CommitHelper"

    def test_empty_string(self):
        assert _safe_filename("") == "unnamed"

    def test_only_special_chars(self):
        assert _safe_filename("///") == "unnamed"

    def test_leading_trailing_dots(self):
        assert _safe_filename(".hidden.") == "hidden"


class TestResolveScopeRoot:
    def test_custom_output_dir(self, config, tmp_path):
        root, scope_root = _resolve_scope_root(config, "x_app", str(tmp_path))
        assert root == tmp_path
        assert scope_root == tmp_path / "x_app"
        assert scope_root.is_dir()

    def test_default_output_dir(self, config):
        root, scope_root = _resolve_scope_root(config, "x_app", None)
        assert "test" in str(root)  # instance name extracted from URL
        assert scope_root.name == "x_app"


# ---------------------------------------------------------------------------
# Core download loop tests
# ---------------------------------------------------------------------------


class TestDownloadSourceTypes:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_and_writes_files(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        # Pass 1: sn_query_all returns metadata only (no script)
        meta_records = [{k: v for k, v in r.items() if k != "script"} for r in _si_records()]
        mock_query_all.return_value = meta_records

        # Pass 2: sn_query_page returns source per record
        def _page_side_effect(*args, **kwargs):
            query = kwargs.get("query", "")
            for r in _si_records():
                if r["sys_id"] in query:
                    return [{"script": r["script"]}], None
            return [], None

        mock_query_page.side_effect = _page_side_effect
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert result["total_files"] == 2
        assert result["type_results"]["script_include"]["count"] == 2

        # Verify files written (identifier_field for SI is api_name)
        si_dir = scope_root / "sys_script_include"
        assert (si_dir / "x_app.CommitHelper" / "_metadata.json").exists()
        assert (si_dir / "x_app.CommitHelper" / "script.js").exists()
        assert (si_dir / "x_app.ApprovalUtil" / "script.js").exists()
        assert (si_dir / "_map.json").exists()
        assert (si_dir / "_sync_meta.json").exists()

        # Verify metadata content
        meta = json.loads((si_dir / "x_app.CommitHelper" / "_metadata.json").read_text())
        assert meta["sys_id"] == "si-1"
        assert meta["source_type"] == "script_include"
        assert meta["table"] == "sys_script_include"

        # Verify script content is NOT truncated
        script = (si_dir / "x_app.CommitHelper" / "script.js").read_text()
        assert "CommitHelper" in script
        assert "validate" in script

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_map_and_sync_meta_content(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.return_value = _strip_source(_si_records())
        mock_query_page.side_effect = _page_side_effect_for(_si_records())
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

        si_dir = scope_root / "sys_script_include"
        name_map = json.loads((si_dir / "_map.json").read_text())
        assert name_map["x_app.CommitHelper"] == "si-1"
        assert name_map["x_app.ApprovalUtil"] == "si-2"

        sync_meta = json.loads((si_dir / "_sync_meta.json").read_text())
        assert sync_meta["x_app.CommitHelper"]["sys_id"] == "si-1"
        assert "downloaded_at" in sync_meta["x_app.CommitHelper"]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_empty_results(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = []
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert result["total_files"] == 0
        assert result["type_results"]["script_include"]["count"] == 0

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_api_error_captured_as_warning(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.side_effect = Exception("Connection timeout")
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert result["type_results"]["script_include"]["count"] == 0
        assert any("fetch failed" in w for w in result["warnings"])
        assert len(result["warnings"]) == 1
        assert "Connection timeout" in result["warnings"][0]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_unknown_source_type_warning(self, mock_query_all, config, auth, tmp_path):
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["nonexistent_type"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert len(result["warnings"]) == 1
        assert "Unknown source type" in result["warnings"][0]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_only_active_filter(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_br_records())
        mock_query_page.return_value = ([], None)
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["business_rule"],
            scope_root=scope_root,
            root=tmp_path,
            only_active=True,
        )

        call_kwargs = mock_query_all.call_args[1]
        assert "active=true" in call_kwargs["query"]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_extra_query_for_acl(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_acl_records())
        mock_query_page.return_value = ([], None)
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["acl"],
            scope_root=scope_root,
            root=tmp_path,
            extra_query={"acl": "scriptISNOTEMPTY"},
        )

        call_kwargs = mock_query_all.call_args[1]
        assert "scriptISNOTEMPTY" in call_kwargs["query"]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_multiple_source_types(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.side_effect = [_strip_source(_br_records()), [], []]
        mock_query_page.return_value = ([], None)
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["business_rule", "client_script", "catalog_client_script"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert result["type_results"]["business_rule"]["count"] == 1
        assert result["type_results"]["client_script"]["count"] == 0
        assert mock_query_all.call_count == 3

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_empty_script_fields_not_written(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        meta_records = [
            {
                "sys_id": "si-empty",
                "name": "EmptySI",
                "api_name": "x_app.EmptySI",
                "description": "",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-01",
                "sys_updated_by": "admin",
            }
        ]
        mock_query_all.return_value = meta_records
        # Pass 2 returns empty script
        mock_query_page.return_value = ([{"script": ""}], None)
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert result["total_files"] == 0  # no script file written
        si_dir = scope_root / "sys_script_include" / "x_app.EmptySI"
        assert (si_dir / "_metadata.json").exists()  # metadata always written
        assert not (si_dir / "script.js").exists()  # empty script not written

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_manifest_entries_contain_path(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.return_value = _strip_source(_si_records()[:1])
        mock_query_page.return_value = ([], None)
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert len(result["manifest_entries"]) == 1
        entry = result["manifest_entries"][0]
        assert entry["source_type"] == "script_include"
        assert entry["sys_id"] == "si-1"
        assert entry["name"] == "x_app.CommitHelper"
        assert "x_app/sys_script_include/x_app.CommitHelper" in entry["path"]


# ---------------------------------------------------------------------------
# Individual download tool tests
# ---------------------------------------------------------------------------


class TestDownloadScriptIncludes:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_happy_path(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_si_records())
        mock_query_page.side_effect = _page_side_effect_for(_si_records())
        result = download_script_includes(
            config,
            auth,
            DownloadScriptIncludesParams(
                scope="x_app",
                output_dir=str(tmp_path),
            ),
        )

        assert result["success"] is True
        assert result["tool"] == "download_script_includes"
        assert result["total_records"] == 2
        assert result["total_files"] == 2

        call_kwargs = mock_query_all.call_args[1]
        assert call_kwargs["table"] == "sys_script_include"
        assert "sys_scope.scope=x_app" in call_kwargs["query"]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_empty_scope(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = []
        result = download_script_includes(
            config,
            auth,
            DownloadScriptIncludesParams(
                scope="x_empty",
                output_dir=str(tmp_path),
            ),
        )
        assert result["success"] is True
        assert result["total_records"] == 0


class TestDownloadServerScripts:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_br_and_client_scripts(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.side_effect = [_strip_source(_br_records()), [], []]
        mock_query_page.side_effect = _page_side_effect_for(_br_records())
        result = download_server_scripts(
            config,
            auth,
            DownloadServerScriptsParams(
                scope="x_app",
                output_dir=str(tmp_path),
            ),
        )

        assert result["success"] is True
        assert result["source_types"]["business_rule"]["count"] == 1
        assert mock_query_all.call_count == 3

        # Verify BR query uses sys_script table
        first_call = mock_query_all.call_args_list[0]
        assert first_call[1]["table"] == "sys_script"


class TestDownloadUIComponents:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_all_ui_types(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.side_effect = [_strip_source(_ui_action_records()), [], [], []]
        mock_query_page.side_effect = _page_side_effect_for(_ui_action_records())
        result = download_ui_components(
            config,
            auth,
            DownloadUIComponentsParams(
                scope="x_app",
                output_dir=str(tmp_path),
            ),
        )

        assert result["success"] is True
        assert result["source_types"]["ui_action"]["count"] == 1
        assert mock_query_all.call_count == 4  # 4 UI types

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_ui_page_multi_field_export(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        ui_page_full = [
            {
                "sys_id": "up-1",
                "name": "custom_page",
                "description": "A custom page",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-01",
                "sys_updated_by": "admin",
                "html": "<html><body>hello</body></html>",
                "client_script": "alert('hi');",
                "processing_script": "gs.log('processed');",
            }
        ]
        mock_query_all.side_effect = [[], [], _strip_source(ui_page_full), []]
        mock_query_page.side_effect = _page_side_effect_for(ui_page_full)
        download_ui_components(
            config,
            auth,
            DownloadUIComponentsParams(
                scope="x_app",
                output_dir=str(tmp_path),
            ),
        )

        page_dir = tmp_path / "x_app" / "sys_ui_page" / "custom_page"
        assert (page_dir / "html.html").exists()
        assert (page_dir / "client_script.client.js").exists()
        assert (page_dir / "processing_script.server.js").exists()


class TestDownloadAPISources:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_rest_and_processor(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.side_effect = [_strip_source(_rest_records()), []]
        mock_query_page.side_effect = _page_side_effect_for(_rest_records())
        result = download_api_sources(
            config,
            auth,
            DownloadAPISourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
            ),
        )

        assert result["success"] is True
        assert result["source_types"]["scripted_rest"]["count"] == 1

        rest_dir = tmp_path / "x_app" / "sys_ws_operation" / "Get_Request_Status"
        assert (rest_dir / "operation_script.js").exists()
        script = (rest_dir / "operation_script.js").read_text()
        assert "x_app_request" in script


class TestDownloadSecuritySources:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_acl_script_only_filter(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_acl_records())
        mock_query_page.return_value = ([], None)
        result = download_security_sources(
            config,
            auth,
            DownloadSecuritySourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                acl_script_only=True,
            ),
        )

        assert result["success"] is True
        call_kwargs = mock_query_all.call_args[1]
        assert "scriptISNOTEMPTY" in call_kwargs["query"]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_acl_all_no_filter(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_acl_records())
        mock_query_page.return_value = ([], None)
        download_security_sources(
            config,
            auth,
            DownloadSecuritySourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                acl_script_only=False,
            ),
        )

        call_kwargs = mock_query_all.call_args[1]
        assert "scriptISNOTEMPTY" not in call_kwargs["query"]


class TestDownloadAdminScripts:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_all_admin_types(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.side_effect = [_strip_source(_fix_script_records()), [], [], [], []]
        mock_query_page.side_effect = _page_side_effect_for(_fix_script_records())
        result = download_admin_scripts(
            config,
            auth,
            DownloadAdminScriptsParams(
                scope="x_app",
                output_dir=str(tmp_path),
            ),
        )

        assert result["success"] is True
        assert result["source_types"]["fix_script"]["count"] == 1
        assert mock_query_all.call_count == 5  # 5 admin types


# ---------------------------------------------------------------------------
# download_table_schema tests
# ---------------------------------------------------------------------------


class TestDownloadTableSchema:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_explicit_tables(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _dict_records()
        result = download_table_schema(
            config,
            auth,
            DownloadTableSchemaParams(
                tables=["x_app_request", "task"],
                output_dir=str(tmp_path / "_schema"),
            ),
        )

        assert result["success"] is True
        assert result["tables_requested"] == 2
        assert result["tables_fetched"] == 2

        schema_dir = tmp_path / "_schema"
        assert (schema_dir / "x_app_request.json").exists()
        assert (schema_dir / "task.json").exists()
        assert (schema_dir / "_index.json").exists()

        schema = json.loads((schema_dir / "x_app_request.json").read_text())
        assert schema["field_count"] == 3
        field_names = [f["field"] for f in schema["fields"]]
        assert "short_description" in field_names
        assert "state" in field_names
        assert "assigned_to" in field_names

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_auto_scan_from_source_root(self, mock_query_all, config, auth, tmp_path):
        # Create a fake source directory with a script referencing a table
        si_dir = tmp_path / "sys_script_include" / "TestSI"
        si_dir.mkdir(parents=True)
        (si_dir / "script.js").write_text(
            "var gr = new GlideRecord('x_app_request');\ngr.query();",
            encoding="utf-8",
        )
        (si_dir / "_metadata.json").write_text(
            json.dumps(
                {"source_type": "script_include", "table": "sys_script_include", "sys_id": "x"}
            ),
            encoding="utf-8",
        )

        mock_query_all.return_value = _dict_records()[:2]

        result = download_table_schema(
            config,
            auth,
            DownloadTableSchemaParams(
                source_root=str(tmp_path),
            ),
        )

        assert result["success"] is True
        assert result["tables_fetched"] >= 1

    def test_missing_source_root(self, config, auth):
        result = download_table_schema(
            config,
            auth,
            DownloadTableSchemaParams(
                source_root="/nonexistent/path",
            ),
        )
        assert result["success"] is False
        assert "not found" in result["message"]

    def test_no_input_error(self, config, auth):
        result = download_table_schema(config, auth, DownloadTableSchemaParams())
        assert result["success"] is False
        assert "Either tables or source_root" in result["message"]

    def test_empty_tables_list(self, config, auth, tmp_path):
        """Empty list is falsy → falls through to source_root check → error."""
        result = download_table_schema(
            config,
            auth,
            DownloadTableSchemaParams(
                tables=[],
            ),
        )
        # Empty list is falsy in Python, so params.tables check fails
        # → falls to source_root check → neither provided → error
        assert result["success"] is False

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_schema_fetch_error_captured(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.side_effect = Exception("API limit exceeded")
        result = download_table_schema(
            config,
            auth,
            DownloadTableSchemaParams(
                tables=["x_app_request"],
                output_dir=str(tmp_path / "_schema"),
            ),
        )
        assert result["success"] is True  # partial success
        assert len(result.get("warnings", [])) > 0

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_index_file_content(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _dict_records()
        download_table_schema(
            config,
            auth,
            DownloadTableSchemaParams(
                tables=["x_app_request"],
                output_dir=str(tmp_path / "_schema"),
            ),
        )

        index = json.loads((tmp_path / "_schema" / "_index.json").read_text())
        assert "downloaded_at" in index
        assert index["total_tables"] >= 1
        assert index["total_fields"] >= 1

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_auto_scan_reads_collection_from_metadata(self, mock_query_all, config, auth, tmp_path):
        br_dir = tmp_path / "sys_script" / "TestBR"
        br_dir.mkdir(parents=True)
        (br_dir / "script.js").write_text("// no GlideRecord", encoding="utf-8")
        (br_dir / "_metadata.json").write_text(
            json.dumps(
                {
                    "source_type": "business_rule",
                    "table": "sys_script",
                    "sys_id": "x",
                    "collection": "custom_table",
                }
            ),
            encoding="utf-8",
        )

        mock_query_all.return_value = [
            {
                "name": "custom_table",
                "element": "field1",
                "column_label": "Field 1",
                "internal_type": "string",
                "max_length": "40",
                "mandatory": "false",
                "reference": "",
            },
        ]

        result = download_table_schema(
            config,
            auth,
            DownloadTableSchemaParams(
                source_root=str(tmp_path),
            ),
        )

        assert result["tables_fetched"] >= 1
        # Verify custom_table was included in the query
        call_kwargs = mock_query_all.call_args[1]
        assert "custom_table" in call_kwargs["query"]


# ---------------------------------------------------------------------------
# Orchestrator tests
# ---------------------------------------------------------------------------


class TestDownloadAppSources:
    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_orchestrator_calls_all_groups(
        self, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        # Each group call returns empty
        mock_query_all.return_value = []
        mock_scan.return_value = set()
        mock_schema.return_value = ({}, [])

        result = download_app_sources(
            config,
            auth,
            DownloadAppSourcesParams(
                scope="x_app",
                include_widget_sources=False,
                include_schema=True,
                output_dir=str(tmp_path),
            ),
        )

        assert result["success"] is True
        # Should call sn_query_all for 7 groups (each with multiple types)
        assert mock_query_all.call_count >= 7

    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_orchestrator_writes_manifest(
        self, mock_query_page, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        mock_query_all.side_effect = [_strip_source(_si_records())] + [[] for _ in range(20)]
        mock_query_page.side_effect = _page_side_effect_for(_si_records())
        mock_scan.return_value = {"x_app_request"}
        mock_schema.return_value = ({"x_app_request": 3}, [])

        download_app_sources(
            config,
            auth,
            DownloadAppSourcesParams(
                scope="x_app",
                include_widget_sources=False,
                include_schema=True,
                output_dir=str(tmp_path),
            ),
        )

        manifest_path = tmp_path / "x_app" / "_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["scope"] == "x_app"
        assert manifest["total_records"] >= 2

    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_orchestrator_schema_included(
        self, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        mock_query_all.return_value = []
        mock_scan.return_value = {"task", "x_app_request"}
        mock_schema.return_value = ({"task": 5, "x_app_request": 3}, [])

        result = download_app_sources(
            config,
            auth,
            DownloadAppSourcesParams(
                scope="x_app",
                include_widget_sources=False,
                include_schema=True,
                output_dir=str(tmp_path),
            ),
        )

        assert result["schema_summary"]["tables_fetched"] == 2
        mock_schema.assert_called_once()

    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_orchestrator_skip_schema(
        self, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        mock_query_all.return_value = []

        result = download_app_sources(
            config,
            auth,
            DownloadAppSourcesParams(
                scope="x_app",
                include_widget_sources=False,
                include_schema=False,
                output_dir=str(tmp_path),
            ),
        )

        mock_scan.assert_not_called()
        mock_schema.assert_not_called()
        assert "schema_summary" not in result

    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_orchestrator_acl_script_only(
        self, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        mock_query_all.return_value = []
        mock_scan.return_value = set()
        mock_schema.return_value = ({}, [])

        download_app_sources(
            config,
            auth,
            DownloadAppSourcesParams(
                scope="x_app",
                include_widget_sources=False,
                include_schema=False,
                acl_script_only=True,
                output_dir=str(tmp_path),
            ),
        )

        # Find the call that queries ACL table
        for call in mock_query_all.call_args_list:
            if call[1].get("table") == "sys_security_acl":
                assert "scriptISNOTEMPTY" in call[1]["query"]
                break

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_orchestrator_portal_fallback_on_import_error(
        self, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.return_value = []

        with patch(
            "servicenow_mcp.tools.source_tools.download_app_sources.__module__",
            "servicenow_mcp.tools.source_tools",
        ):
            result = download_app_sources(
                config,
                auth,
                DownloadAppSourcesParams(
                    scope="x_app",
                    include_widget_sources=False,
                    include_schema=False,
                    output_dir=str(tmp_path),
                ),
            )

        assert result["success"] is True

    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_orchestrator_includes_portal_assets(
        self, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        """Verify sp_header_footer, sp_css, ng_template are included."""
        mock_query_all.return_value = []
        mock_scan.return_value = set()
        mock_schema.return_value = ({}, [])

        download_app_sources(
            config,
            auth,
            DownloadAppSourcesParams(
                scope="x_app",
                include_widget_sources=False,
                include_schema=False,
                output_dir=str(tmp_path),
            ),
        )

        queried_tables = [c[1]["table"] for c in mock_query_all.call_args_list]
        assert "sp_header_footer" in queried_tables
        assert "sp_css" in queried_tables
        assert "sp_ng_template" in queried_tables


# ---------------------------------------------------------------------------
# File extension mapping tests
# ---------------------------------------------------------------------------


class TestFieldExtensions:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_business_rule_script_extension(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.return_value = _strip_source(_br_records())
        mock_query_page.side_effect = _page_side_effect_for(_br_records())
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["business_rule"],
            scope_root=scope_root,
            root=tmp_path,
        )

        br_dir = scope_root / "sys_script" / "Validate_Before_Insert"
        assert (br_dir / "script.js").exists()

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_rest_operation_script_extension(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.return_value = _strip_source(_rest_records())
        mock_query_page.side_effect = _page_side_effect_for(_rest_records())
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["scripted_rest"],
            scope_root=scope_root,
            root=tmp_path,
        )

        rest_dir = scope_root / "sys_ws_operation" / "Get_Request_Status"
        assert (rest_dir / "operation_script.js").exists()

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_acl_script_extension(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_acl_records())
        mock_query_page.side_effect = _page_side_effect_for(_acl_records())
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["acl"],
            scope_root=scope_root,
            root=tmp_path,
        )

        acl_dir = scope_root / "sys_security_acl" / "x_app_request.read"
        assert (acl_dir / "script.js").exists()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_duplicate_names_safe_filename(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        """Two records with same name should not crash (last one wins)."""
        full_records = [
            {**_si_records()[0], "sys_id": "si-dup-1"},
            {**_si_records()[0], "sys_id": "si-dup-2"},
        ]
        mock_query_all.return_value = _strip_source(full_records)
        mock_query_page.side_effect = _page_side_effect_for(full_records)
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )
        # Should not crash, last write wins
        assert result["type_results"]["script_include"]["count"] == 2

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_max_records_clamped(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = []
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
            max_per_type=99999,
        )

        call_kwargs = mock_query_all.call_args[1]
        assert call_kwargs["max_records"] == 50000  # MAX_DOWNLOAD_PER_TYPE

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_page_size_clamped(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = []
        scope_root = tmp_path / "x_app"
        scope_root.mkdir()

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
            page_size=999,
        )

        call_kwargs = mock_query_all.call_args[1]
        # script_include has source_fields → clamped to min(100, 10) = 10
        assert call_kwargs["page_size"] == 10
