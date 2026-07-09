"""Tests for individual download tools and the download_app_sources orchestrator.

Covers:
- _download_source_types (core loop)
- download_server_sources (consolidated targeted source-family refresh)
- download_table_schema
- download_app_sources (orchestrator)
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.source_tools import (
    DownloadAppSourcesParams,
    DownloadSourcesParams,
    DownloadTableSchemaParams,
    _download_source_types,
    _resolve_scope_root,
    _safe_filename,
    _strip_scope_prefix,
    download_app_sources,
    download_server_sources,
    download_table_schema,
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
            "web_service_definition": "ws-req-1",
            "web_service_definition.name": "RequestAPI",
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


def _query_all_side_effect_for(records_by_table):
    """Build a table-keyed sn_query_all side_effect.

    Source types download in a ThreadPoolExecutor (submit + as_completed), so
    a positional side_effect LIST is consumed in thread-scheduling order — a
    long-standing order-dependent flake (records randomly land on the wrong
    type). Key on the `table` kwarg instead so each type deterministically
    receives its own records; unlisted tables get [].
    """

    def _side_effect(*args, **kwargs):
        return list(records_by_table.get(kwargs.get("table", ""), []))

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
        # output_dir IS the final scope root — nothing appended.
        custom = tmp_path / "any" / "shape"
        root, scope_root = _resolve_scope_root(config, "x_app", str(custom))
        assert scope_root == custom
        assert root == custom.parent
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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        assert (si_dir / "CommitHelper" / "_metadata.json").exists()
        assert (si_dir / "CommitHelper" / "script.js").exists()
        assert (si_dir / "ApprovalUtil" / "script.js").exists()
        assert (si_dir / "_map.json").exists()
        assert (si_dir / "_sync_meta.json").exists()

        # Verify metadata content
        meta = json.loads((si_dir / "CommitHelper" / "_metadata.json").read_text())
        assert meta["sys_id"] == "si-1"
        assert meta["source_type"] == "script_include"
        assert meta["table"] == "sys_script_include"

        # Verify script content is NOT truncated
        script = (si_dir / "CommitHelper" / "script.js").read_text()
        assert "CommitHelper" in script
        assert "validate" in script

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_multiple_types_run_in_parallel_and_merge_deterministically(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        """Source types fan out concurrently; results merge in input order with
        no cross-type leakage. Guards the parallel rewrite of the type loop."""
        by_table = {
            "sys_script_include": _si_records(),
            "sys_script": _br_records(),
        }

        def _all_side_effect(*args, **kwargs):
            return _strip_source(by_table.get(kwargs.get("table"), []))

        all_full = _si_records() + _br_records()

        mock_query_all.side_effect = _all_side_effect
        mock_query_page.side_effect = _page_side_effect_for(all_full)
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include", "business_rule"],
            scope_root=scope_root,
            root=tmp_path,
        )

        # Both types processed, counts correct, no cross-type bleed.
        assert result["type_results"]["script_include"]["count"] == 2
        assert result["type_results"]["business_rule"]["count"] == 1
        assert result["total_files"] == 3

        # Files landed under each type's own table dir.
        assert (scope_root / "sys_script_include" / "CommitHelper" / "script.js").exists()
        assert (
            scope_root / "sys_script" / "x_app_request" / "Validate_Before_Insert" / "script.js"
        ).exists()

        # Merge is deterministic: type_results follows input order.
        assert list(result["type_results"].keys()) == ["script_include", "business_rule"]
        manifest_types = {e["source_type"] for e in result["manifest_entries"]}
        assert manifest_types == {"script_include", "business_rule"}

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_auth_failure_aborts_remaining_types_no_401_bomb(
        self, mock_query_all, config, auth, tmp_path
    ):
        """An auth failure on one type trips the abort flag so the remaining
        types skip instead of each re-firing the same doomed call (401 bomb)."""
        import requests

        call_count = {"n": 0}

        def _fail_auth(*args, **kwargs):
            call_count["n"] += 1
            raise requests.HTTPError(
                "FRESH_SESSION_REJECTED: brand-new browser session (<90s old) "
                "rejected by ServiceNow with 401."
            )

        mock_query_all.side_effect = _fail_auth
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        # Many types queued; only up to the worker cap should actually fire
        # before the abort flag short-circuits the rest.
        many_types = [
            "script_include",
            "business_rule",
            "ui_action",
            "client_script",
            "ui_script",
            "fix_script",
            "scheduled_job",
            "transform_script",
        ]
        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=many_types,
            scope_root=scope_root,
            root=tmp_path,
        )

        # Far fewer API calls than queued types — the bomb was contained.
        assert call_count["n"] < len(many_types)
        # At least one type carries the actionable abort warning.
        assert any("aborted" in w.lower() for w in result["warnings"])
        # Some types were explicitly skipped via the abort flag.
        skipped = [
            t for t, r in result["type_results"].items() if r.get("skipped") == "auth_failure_abort"
        ]
        assert skipped

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_map_and_sync_meta_content(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.return_value = _strip_source(_si_records())
        mock_query_page.side_effect = _page_side_effect_for(_si_records())
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        assert name_map["CommitHelper"] == "si-1"
        assert name_map["ApprovalUtil"] == "si-2"

        sync_meta = json.loads((si_dir / "_sync_meta.json").read_text())
        assert sync_meta["CommitHelper"]["sys_id"] == "si-1"
        assert "downloaded_at" in sync_meta["CommitHelper"]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_empty_results(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = []
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_script": _strip_source(_br_records())}
        )
        mock_query_page.return_value = ([], None)
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert result["total_files"] == 0  # no script file written
        si_dir = scope_root / "sys_script_include" / "EmptySI"
        assert (si_dir / "_metadata.json").exists()  # metadata always written
        assert not (si_dir / "script.js").exists()  # empty script not written

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_manifest_entries_contain_path(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.return_value = _strip_source(_si_records()[:1])
        mock_query_page.return_value = ([], None)
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        assert "x_app/sys_script_include/CommitHelper" in entry["path"]


# ---------------------------------------------------------------------------
# Individual download tool tests
# ---------------------------------------------------------------------------


class TestDownloadSourcesScriptIncludes:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_happy_path(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_si_records())
        mock_query_page.side_effect = _page_side_effect_for(_si_records())
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["script_includes"],
            ),
        )

        assert result["success"] is True
        assert result["tool"] == "download_server_sources"
        assert result["total_records"] == 2
        assert result["total_files"] == 2

        call_kwargs = mock_query_all.call_args[1]
        assert call_kwargs["table"] == "sys_script_include"
        assert "sys_scope.scope=x_app" in call_kwargs["query"]

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_empty_scope(self, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = []
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_empty",
                output_dir=str(tmp_path),
                families=["script_includes"],
            ),
        )
        assert result["success"] is True
        assert result["total_records"] == 0

    def test_unknown_family_rejected(self, config, auth, tmp_path):
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(scope="x_app", output_dir=str(tmp_path), families=["bogus"]),
        )
        assert result["success"] is False
        assert "bogus" in result["message"]

    def test_empty_families_rejected(self, config, auth, tmp_path):
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(scope="x_app", output_dir=str(tmp_path), families=[]),
        )
        assert result["success"] is False


class TestDownloadSourcesServerScripts:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_br_and_client_scripts(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_script": _strip_source(_br_records())}
        )
        mock_query_page.side_effect = _page_side_effect_for(_br_records())
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["server_scripts"],
            ),
        )

        assert result["success"] is True
        assert result["source_types"]["business_rule"]["count"] == 1
        assert mock_query_all.call_count == 3

        # Verify BR query uses sys_script table
        first_call = mock_query_all.call_args_list[0]
        assert first_call[1]["table"] == "sys_script"


class TestDownloadSourcesUIComponents:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_all_ui_types(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_ui_action": _strip_source(_ui_action_records())}
        )
        mock_query_page.side_effect = _page_side_effect_for(_ui_action_records())
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["ui"],
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
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_ui_page": _strip_source(ui_page_full)}
        )
        mock_query_page.side_effect = _page_side_effect_for(ui_page_full)
        download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["ui"],
            ),
        )

        page_dir = tmp_path / "sys_ui_page" / "custom_page"
        assert (page_dir / "html.html").exists()
        # Canonical filenames (source_layout) — same as the uploader expects.
        assert (page_dir / "client_script.js").exists()
        assert (page_dir / "processing_script.js").exists()


class TestDownloadSourcesAPI:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_rest_and_processor(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_ws_operation": _strip_source(_rest_records())}
        )
        mock_query_page.side_effect = _page_side_effect_for(_rest_records())
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["api"],
            ),
        )

        assert result["success"] is True
        assert result["source_types"]["scripted_rest"]["count"] == 1

        # Folder is qualified by the parent web service so same-named operations
        # across web services don't collide.
        rest_dir = tmp_path / "sys_ws_operation" / "RequestAPI" / "Get_Request_Status"
        assert (rest_dir / "operation_script.js").exists()
        script = (rest_dir / "operation_script.js").read_text()
        assert "x_app_request" in script

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_same_named_operations_across_web_services_dont_collide(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        # Two web services each own an operation named 'end' — the exact
        # same-name trap. Each must land in its OWN folder with its OWN sys_id.
        ops = [
            {
                "sys_id": "op-a",
                "name": "end",
                "http_method": "POST",
                "active": "true",
                "web_service_definition": "ws-1",
                "web_service_definition.name": "updateSOSAP",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-01 16:00:00",
                "sys_updated_by": "admin",
                "operation_script": "// updateSOSAP end body\n",
            },
            {
                "sys_id": "op-b",
                "name": "end",
                "http_method": "POST",
                "active": "true",
                "web_service_definition": "ws-2",
                "web_service_definition.name": "otherSvc",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-01 16:00:00",
                "sys_updated_by": "admin",
                "operation_script": "// otherSvc end body\n",
            },
        ]
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_ws_operation": _strip_source(ops)}
        )
        mock_query_page.side_effect = _page_side_effect_for(ops)

        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(scope="x_app", output_dir=str(tmp_path), families=["api"]),
        )

        assert result["success"] is True
        op_root = tmp_path / "sys_ws_operation"
        a_dir = op_root / "updateSOSAP" / "end"
        b_dir = op_root / "otherSvc" / "end"
        # Both bodies present in distinct folders — nothing overwritten.
        assert (a_dir / "operation_script.js").read_text() == "// updateSOSAP end body\n"
        assert (b_dir / "operation_script.js").read_text() == "// otherSvc end body\n"
        # Each folder carries its OWN sys_id (collision-proof push identity).
        assert json.loads((a_dir / "_metadata.json").read_text())["sys_id"] == "op-a"
        assert json.loads((b_dir / "_metadata.json").read_text())["sys_id"] == "op-b"

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_unqualified_name_collision_suffixes_both_and_warns(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        # Net for tables with no folder qualifier: two records mapping to one
        # folder must BOTH land on disk, sys_id-suffixed, and warn. Dropping the
        # loser (the pre-fix behavior) made the tree look complete while silently
        # missing records. Suffixing every member of a duplicate group also keeps
        # the folder a pure function of the record, not of result-set order.
        dups = [
            {
                "sys_id": "fix-a",
                "name": "Dup Script",
                "description": "first",
                "active": "false",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-01 18:00:00",
                "sys_updated_by": "admin",
                "script": "// first\n",
            },
            {
                "sys_id": "fix-b",
                "name": "Dup Script",
                "description": "second",
                "active": "false",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-01 18:00:00",
                "sys_updated_by": "admin",
                "script": "// second\n",
            },
        ]
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_script_fix": _strip_source(dups)}
        )
        mock_query_page.side_effect = _page_side_effect_for(dups)

        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(scope="x_app", output_dir=str(tmp_path), families=["admin"]),
        )

        assert any(
            "not unique" in w and "Dup_Script" in w for w in result.get("warnings", [])
        ), result.get("warnings")
        # Neither record is dropped: each keeps its own body and its own sys_id,
        # and the bare colliding folder is never created.
        assert not (tmp_path / "sys_script_fix" / "Dup_Script").exists()
        for sys_id, body in (("fix-a", "// first\n"), ("fix-b", "// second\n")):
            dup_dir = tmp_path / "sys_script_fix" / f"Dup_Script.{sys_id}"
            assert (dup_dir / "script.js").read_text() == body
            assert json.loads((dup_dir / "_metadata.json").read_text())["sys_id"] == sys_id

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_collision_folders_are_independent_of_record_order(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        # A reordered result set must not flip which record owns which folder,
        # or every download would churn the tree.
        def _dup(sys_id, body):
            return {
                "sys_id": sys_id,
                "name": "Dup Script",
                "active": "false",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-01 18:00:00",
                "sys_updated_by": "admin",
                "script": body,
            }

        seen = []
        for order in (
            [_dup("fix-a", "// a\n"), _dup("fix-b", "// b\n")],
            [_dup("fix-b", "// b\n"), _dup("fix-a", "// a\n")],
        ):
            out = tmp_path / f"run{len(seen)}"
            mock_query_all.side_effect = _query_all_side_effect_for(
                {"sys_script_fix": _strip_source(order)}
            )
            mock_query_page.side_effect = _page_side_effect_for(order)
            download_server_sources(
                config,
                auth,
                DownloadSourcesParams(scope="x_app", output_dir=str(out), families=["admin"]),
            )
            seen.append(sorted(p.name for p in (out / "sys_script_fix").iterdir() if p.is_dir()))

        assert seen[0] == seen[1] == ["Dup_Script.fix-a", "Dup_Script.fix-b"]


class TestDownloadSourcesSecurity:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_acl_script_only_filter(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_acl_records())
        mock_query_page.return_value = ([], None)
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["security"],
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
        download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["security"],
                acl_script_only=False,
            ),
        )

        call_kwargs = mock_query_all.call_args[1]
        assert "scriptISNOTEMPTY" not in call_kwargs["query"]
        assert call_kwargs["page_size"] == 20
        mock_query_page.assert_not_called()


class TestDownloadSourcesAdmin:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_downloads_all_admin_types(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_script_fix": _strip_source(_fix_script_records())}
        )
        mock_query_page.side_effect = _page_side_effect_for(_fix_script_records())
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["admin"],
            ),
        )

        assert result["success"] is True
        assert result["source_types"]["fix_script"]["count"] == 1
        assert mock_query_all.call_count == 5  # 5 admin types

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_multiple_families_one_call(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        # script_includes (1 type) + api (2 types) = 3 source-type queries in one call.
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_script_include": _strip_source(_si_records())}
        )
        mock_query_page.side_effect = _page_side_effect_for(_si_records())
        result = download_server_sources(
            config,
            auth,
            DownloadSourcesParams(
                scope="x_app",
                output_dir=str(tmp_path),
                families=["script_includes", "api"],
            ),
        )
        assert result["success"] is True
        assert mock_query_all.call_count == 3


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
        mock_query_all.side_effect = _query_all_side_effect_for(
            {"sys_script_include": _strip_source(_si_records())}
        )
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

        manifest_path = tmp_path / "_manifest.json"
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

    @patch("servicenow_mcp.tools.source_tools._fetch_and_write_schema")
    @patch("servicenow_mcp.tools.source_tools._scan_tables_from_source_root")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_orchestrator_acl_all_skips_empty_source_retry(
        self, mock_query_page, mock_query_all, mock_scan, mock_schema, config, auth, tmp_path
    ):
        def _query_all(*args, **kwargs):
            if kwargs.get("table") == "sys_security_acl":
                return _strip_source(_acl_records())
            return []

        mock_query_all.side_effect = _query_all
        mock_scan.return_value = set()
        mock_schema.return_value = ({}, [])

        result = download_app_sources(
            config,
            auth,
            DownloadAppSourcesParams(
                scope="x_app",
                include_widget_sources=False,
                include_schema=False,
                acl_script_only=False,
                output_dir=str(tmp_path),
            ),
        )

        assert result["success"] is True
        mock_query_page.assert_not_called()
        for call in mock_query_all.call_args_list:
            if call[1].get("table") == "sys_security_acl":
                assert "scriptISNOTEMPTY" not in call[1]["query"]
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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["business_rule"],
            scope_root=scope_root,
            root=tmp_path,
        )

        br_dir = scope_root / "sys_script" / "x_app_request" / "Validate_Before_Insert"
        assert (br_dir / "script.js").exists()

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_rest_operation_script_extension(
        self, mock_query_page, mock_query_all, config, auth, tmp_path
    ):
        mock_query_all.return_value = _strip_source(_rest_records())
        mock_query_page.side_effect = _page_side_effect_for(_rest_records())
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["scripted_rest"],
            scope_root=scope_root,
            root=tmp_path,
        )

        rest_dir = scope_root / "sys_ws_operation" / "RequestAPI" / "Get_Request_Status"
        assert (rest_dir / "operation_script.js").exists()

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_acl_script_extension(self, mock_query_page, mock_query_all, config, auth, tmp_path):
        mock_query_all.return_value = _strip_source(_acl_records())
        mock_query_page.side_effect = _page_side_effect_for(_acl_records())
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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


# ---------------------------------------------------------------------------
# Re-download must never let a stale local body reach the server NOR destroy
# local edits (3-way via the _baseline snapshot, utils/baseline.py):
#   - clean local + server moved  -> auto-refresh (watermark bumps: honest)
#   - local edits + server moved  -> keep local, save .remote sidecar, and
#     PRESERVE the watermark so a later push still flags the conflict
#   - legacy tree (no _baseline/) -> historical resume-skip + stale warning
# ---------------------------------------------------------------------------


class TestResumeSkipWatermark:
    def _download(self, config, auth, records, scope_root, tmp_path, mqa, mqp):
        mqa.return_value = _strip_source(records)
        mqp.side_effect = _page_side_effect_for(records)
        return _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

    def _redownload_with_remote_change(self, config, auth, scope_root, tmp_path, mqa, mqp):
        recs2 = _si_records()
        recs2[0]["sys_updated_on"] = "2026-05-01 09:00:00"
        recs2[0]["script"] = "var CommitHelper = 'REMOTE_CHANGED';"
        return self._download(config, auth, recs2, scope_root, tmp_path, mqa, mqp)

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_clean_local_auto_refreshes_on_remote_change(self, mqp, mqa, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)
        si_dir = scope_root / "sys_script_include"

        # First download at T0 seeds the baseline snapshot.
        self._download(config, auth, _si_records(), scope_root, tmp_path, mqa, mqp)
        assert (si_dir / "CommitHelper" / "_baseline" / "script.js").exists()

        # Someone edits CommitHelper remotely at T1; local copy was NOT edited.
        result = self._redownload_with_remote_change(config, auth, scope_root, tmp_path, mqa, mqp)

        # Clean local -> auto-refreshed to the server's version; watermark bumps.
        local_script = (si_dir / "CommitHelper" / "script.js").read_text()
        assert "REMOTE_CHANGED" in local_script
        baseline = (si_dir / "CommitHelper" / "_baseline" / "script.js").read_text()
        assert "REMOTE_CHANGED" in baseline
        meta1 = json.loads((si_dir / "_sync_meta.json").read_text())
        assert meta1["CommitHelper"]["sys_updated_on"] == "2026-05-01 09:00:00"
        assert any("auto-refreshed" in w and "CommitHelper" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_local_edits_kept_with_sidecar_and_watermark_preserved(
        self, mqp, mqa, config, auth, tmp_path
    ):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)
        si_dir = scope_root / "sys_script_include"

        self._download(config, auth, _si_records(), scope_root, tmp_path, mqa, mqp)
        # The user edits the local copy...
        local_file = si_dir / "CommitHelper" / "script.js"
        local_file.write_text("var CommitHelper = 'MY_LOCAL_EDIT';", encoding="utf-8")
        # ...and someone ELSE edits the same record remotely.
        result = self._redownload_with_remote_change(config, auth, scope_root, tmp_path, mqa, mqp)

        # Local edits are NEVER overwritten; the server's version lands as a sidecar.
        assert "MY_LOCAL_EDIT" in local_file.read_text()
        sidecar = si_dir / "CommitHelper" / "script.remote.js"
        assert "REMOTE_CHANGED" in sidecar.read_text()
        # Watermark stays at T0 — bumping it would blind the push conflict gate.
        meta1 = json.loads((si_dir / "_sync_meta.json").read_text())
        assert meta1["CommitHelper"]["sys_updated_on"] == "2026-04-01 12:00:00"
        assert any("CONFLICT" in w and "CommitHelper" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_legacy_tree_keeps_local_and_flags_stale(self, mqp, mqa, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)
        si_dir = scope_root / "sys_script_include"

        self._download(config, auth, _si_records(), scope_root, tmp_path, mqa, mqp)
        # Simulate a pre-baseline tree: drop the snapshots.
        import shutil

        shutil.rmtree(si_dir / "CommitHelper" / "_baseline")
        result = self._redownload_with_remote_change(config, auth, scope_root, tmp_path, mqa, mqp)

        # Historical behavior: keep local, preserve watermark, surface the drift.
        local_script = (si_dir / "CommitHelper" / "script.js").read_text()
        assert "REMOTE_CHANGED" not in local_script
        meta1 = json.loads((si_dir / "_sync_meta.json").read_text())
        assert meta1["CommitHelper"]["sys_updated_on"] == "2026-04-01 12:00:00"
        assert any("OLDER than the server" in w and "CommitHelper" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_unchanged_skip_emits_no_stale_warning(self, mqp, mqa, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        self._download(config, auth, _si_records(), scope_root, tmp_path, mqa, mqp)
        # Re-download with identical timestamps → resume-skip, but nothing stale.
        result = self._download(config, auth, _si_records(), scope_root, tmp_path, mqa, mqp)
        assert not any("OLDER than the server" in w for w in result["warnings"])
        assert not any("CONFLICT" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Completeness: hitting the per-type cap must be surfaced (never a silent
# truncation), both as a human warning and a machine-readable `capped` flag.
# ---------------------------------------------------------------------------


class TestDownloadCapWarning:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_cap_hit_is_flagged(self, mqp, mqa, config, auth, tmp_path):
        # Two SI records; cap the download at 2 → fetched == cap → capped.
        recs = _si_records()
        mqa.return_value = _strip_source(recs)
        mqp.side_effect = _page_side_effect_for(recs)
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
            max_per_type=2,
        )
        assert result["type_results"]["script_include"]["capped"] is True
        assert any("INCOMPLETE" in w and "script_include" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_under_cap_is_not_flagged(self, mqp, mqa, config, auth, tmp_path):
        recs = _si_records()  # 2 records
        mqa.return_value = _strip_source(recs)
        mqp.side_effect = _page_side_effect_for(recs)
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
            max_per_type=100,
        )
        assert result["type_results"]["script_include"]["capped"] is False
        assert not any("INCOMPLETE" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Transitive dependency depth is configurable but clamped — deeper when asked,
# never runaway (don't force, but allow looking further).
# ---------------------------------------------------------------------------


class TestDepMaxDepth:
    def test_default_is_two(self):
        import os
        from unittest.mock import patch

        from servicenow_mcp.tools.source_tools import _dep_max_depth

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SERVICENOW_DEP_MAX_DEPTH", None)
            assert _dep_max_depth() == 2

    def test_env_raises_depth(self):
        import os
        from unittest.mock import patch

        from servicenow_mcp.tools.source_tools import _dep_max_depth

        with patch.dict(os.environ, {"SERVICENOW_DEP_MAX_DEPTH": "4"}):
            assert _dep_max_depth() == 4

    def test_clamped_to_cap_and_floor(self):
        import os
        from unittest.mock import patch

        from servicenow_mcp.tools.source_tools import _DEP_MAX_DEPTH_CAP, _dep_max_depth

        with patch.dict(os.environ, {"SERVICENOW_DEP_MAX_DEPTH": "999"}):
            assert _dep_max_depth() == _DEP_MAX_DEPTH_CAP
        with patch.dict(os.environ, {"SERVICENOW_DEP_MAX_DEPTH": "0"}):
            assert _dep_max_depth() == 1

    def test_garbage_falls_back_to_default(self):
        import os
        from unittest.mock import patch

        from servicenow_mcp.tools.source_tools import _dep_max_depth

        with patch.dict(os.environ, {"SERVICENOW_DEP_MAX_DEPTH": "deep!"}):
            assert _dep_max_depth() == 2


# ---------------------------------------------------------------------------
# Resume-skip is PER FIELD, not all-or-nothing. A prior download that wrote some
# source fields but not others must NOT mark the whole record "already
# downloaded" — the missing field files are backfilled from the batch content
# already in hand (no extra API call), while existing files stay untouched.
# Regression guard for the "success but the file isn't there" floundering.
# ---------------------------------------------------------------------------


def _ui_page_records():
    return [
        {
            "sys_id": "uip-1",
            "name": "Request Form",
            "description": "Custom request form",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-01 12:00:00",
            "sys_updated_by": "admin",
            "html": "<g:ui_form>FORM</g:ui_form>",
            "client_script": "function onLoad() { salesGroup(); }",
            "processing_script": "current.update();",
        },
    ]


class TestResumeSkipBackfill:
    def _download(self, config, auth, records, scope_root, tmp_path, mqa, mqp):
        mqa.return_value = _strip_source(records)
        mqp.side_effect = _page_side_effect_for(records)
        return _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["ui_page"],
            scope_root=scope_root,
            root=tmp_path,
        )

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_missing_field_is_backfilled_existing_untouched(self, mqp, mqa, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        # First download writes all three field files.
        self._download(config, auth, _ui_page_records(), scope_root, tmp_path, mqa, mqp)
        rec_dir = next((scope_root / "sys_ui_page").glob("*/client_script.js")).parent
        assert (rec_dir / "html.html").exists()
        assert (rec_dir / "processing_script.js").exists()

        # Simulate a prior PARTIAL download: the client_script file never landed.
        # Mark an existing file so we can prove it is NOT clobbered on backfill.
        (rec_dir / "client_script.js").unlink()
        (rec_dir / "html.html").write_text("<g:ui_form>LOCAL EDIT</g:ui_form>")

        # Re-download (non-incremental) — the old any()-skip would leave
        # client_script.js missing forever; the per-field backfill must restore it.
        result = self._download(config, auth, _ui_page_records(), scope_root, tmp_path, mqa, mqp)

        assert (rec_dir / "client_script.js").exists()
        assert "salesGroup" in (rec_dir / "client_script.js").read_text()
        # Existing local edit preserved (never clobbered).
        assert "LOCAL EDIT" in (rec_dir / "html.html").read_text()
        # Surfaced as both a human warning and a machine-readable disk-truth field.
        assert result["type_results"]["ui_page"]["backfilled"] == 1
        assert any("backfilled" in w and "Request Form" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_complete_record_is_not_backfilled(self, mqp, mqa, config, auth, tmp_path):
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        self._download(config, auth, _ui_page_records(), scope_root, tmp_path, mqa, mqp)
        # Re-download with every field already on disk → nothing backfilled.
        result = self._download(config, auth, _ui_page_records(), scope_root, tmp_path, mqa, mqp)
        assert "backfilled" not in result["type_results"]["ui_page"]
        assert not any("backfilled" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Folder-name consistency (single style, no scope-prefix mix, no bare sys_id)
# ---------------------------------------------------------------------------


class TestStripScopePrefix:
    def test_strips_only_the_resolved_scope(self):
        assert _strip_scope_prefix("x_app.Foo", "x_app") == "Foo"

    def test_bare_name_untouched(self):
        assert _strip_scope_prefix("Foo", "x_app") == "Foo"

    def test_other_scope_not_stripped(self):
        # A different scope's prefix is not the parent dir → keep it to stay unique.
        assert _strip_scope_prefix("global.Foo", "x_app") == "global.Foo"

    def test_scope_without_dot_untouched(self):
        assert _strip_scope_prefix("x_app", "x_app") == "x_app"


class TestSIFolderConsistency:
    """script_include uses api_name; an SI with an empty api_name fell back to
    name, mixing 'x_app.Foo' and 'Foo' folders in one tree. Both must now be bare."""

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_scoped_and_unscoped_si_both_bare(self, mqp, mqa, config, auth, tmp_path):
        records = [
            {
                "sys_id": "si-1",
                "name": "CommitHelper",
                "api_name": "x_app.CommitHelper",  # api_name populated → was prefixed
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-01 12:00:00",
                "sys_updated_by": "admin",
                "script": "var CommitHelper = Class.create();",
            },
            {
                "sys_id": "si-2",
                "name": "LegacyUtil",
                "api_name": "",  # empty api_name → fell back to bare name already
                "sys_scope": "x_app",
                "sys_updated_on": "2026-04-02 10:00:00",
                "sys_updated_by": "dev1",
                "script": "var LegacyUtil = Class.create();",
            },
        ]
        mqa.return_value = [{k: v for k, v in r.items() if k != "script"} for r in records]

        def _page(*a, **k):
            q = k.get("query", "")
            for r in records:
                if r["sys_id"] in q:
                    return [{"script": r["script"]}], None
            return [], None

        mqp.side_effect = _page
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )
        si_dir = scope_root / "sys_script_include"
        # Single consistent style: no scope prefix on either folder.
        assert (si_dir / "CommitHelper" / "script.js").exists()
        assert (si_dir / "LegacyUtil" / "script.js").exists()
        assert not (si_dir / "x_app.CommitHelper").exists()


class TestTransformScriptFolderName:
    """sys_transform_script.name is blank → folder must compose map.name/when/order,
    not collapse to the bare sys_id."""

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_nameless_record_composes_readable_folder(self, mqp, mqa, config, auth, tmp_path):
        records = [
            {
                "sys_id": "ts-1",
                "name": "",
                "map": "map-sysid-1",
                "map.name": "User Import",
                "when": "onBefore",
                "order": 100,
                "sys_updated_on": "2026-04-01 12:00:00",
                "sys_updated_by": "admin",
                "script": "target.name = source.u_name;",
            },
        ]
        mqa.return_value = [{k: v for k, v in r.items() if k != "script"} for r in records]

        def _page(*a, **k):
            q = k.get("query", "")
            return ([{"script": records[0]["script"]}], None) if "ts-1" in q else ([], None)

        mqp.side_effect = _page
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["transform_script"],
            scope_root=scope_root,
            root=tmp_path,
        )
        ts_dir = scope_root / "sys_transform_script"
        assert (ts_dir / "User_Import_onBefore_100" / "script.js").exists()
        # sys_id must NOT be used as the folder when composable fields exist.
        assert not (ts_dir / "ts-1").exists()


# ---------------------------------------------------------------------------
# Scope routing — every record lands under ITS OWN scope tree, always bare
# ---------------------------------------------------------------------------


def test_record_scope_namespace_sources():
    from servicenow_mcp.tools.source_tools import _record_scope_namespace as ns

    # sys_scope.scope is the authoritative source
    assert ns({"sys_scope.scope": "x_app", "api_name": "global.Foo"}, "fb") == "x_app"
    # api_name prefix is the SI fallback when sys_scope.scope is absent
    assert ns({"api_name": "global.Foo"}, "fb") == "global"
    # bare api_name (no dot) → fall back to the download scope, never mis-route
    assert ns({"api_name": "Foo"}, "x_app") == "x_app"
    assert ns({}, "x_app") == "x_app"


class TestDepScopeRouting:
    """A dependency is written under its OWN scope tree (global -> sibling 'global',
    same-scope -> the app), always as a bare name."""

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_global_and_same_scope_deps_routed(self, mqa, config, auth, tmp_path):
        from servicenow_mcp.tools.source_tools import _download_dep_records

        scope_root = tmp_path / "x_app"
        scope_root.mkdir()
        mqa.return_value = [
            {
                "sys_id": "g1",
                "name": "GUtil",
                "api_name": "global.GUtil",
                "sys_scope.scope": "global",
                "script": "var GUtil;",
            },
            {
                "sys_id": "a1",
                "name": "AUtil",
                "api_name": "x_app.AUtil",
                "sys_scope.scope": "x_app",
                "script": "var AUtil;",
            },
        ]
        res = _download_dep_records(
            config, auth, "script_include", "name", ["GUtil", "AUtil"], scope_root, 20
        )
        # global dep -> sibling global tree, bare name
        assert (tmp_path / "global" / "sys_script_include" / "GUtil" / "script.js").exists()
        # same-scope dep -> the app's own tree, bare name
        assert (scope_root / "sys_script_include" / "AUtil" / "script.js").exists()
        # never buried under the app that pulled the global one
        assert not (scope_root / "sys_script_include" / "global.GUtil").exists()
        assert set(res["scope_roots"]) == {str(tmp_path / "global"), str(scope_root)}

    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_metadata_records_scope_namespace(self, mqa, config, auth, tmp_path):
        from servicenow_mcp.tools.source_tools import _download_dep_records

        scope_root = tmp_path / "x_app"
        scope_root.mkdir()
        mqa.return_value = [
            {
                "sys_id": "g1",
                "name": "GUtil",
                "api_name": "global.GUtil",
                "sys_scope.scope": "global",
                "script": "var GUtil;",
            }
        ]
        _download_dep_records(config, auth, "script_include", "name", ["GUtil"], scope_root, 20)
        meta = json.loads(
            (tmp_path / "global" / "sys_script_include" / "GUtil" / "_metadata.json").read_text()
        )
        assert meta["scope_namespace"] == "global"
        assert meta["is_dependency"] is True


def test_dep_scope_roots_reads_manifest(tmp_path):
    from servicenow_mcp.utils.source_layout import dep_scope_roots

    scope_root = tmp_path / "x_app"
    scope_root.mkdir()
    (tmp_path / "global").mkdir()
    # x_other listed but not on disk → excluded; global exists → included
    (scope_root / "_dep_scopes.json").write_text('{"dep_scopes": ["global", "x_other"]}')
    assert dep_scope_roots(scope_root) == [tmp_path / "global"]
    # no manifest → empty
    assert dep_scope_roots(tmp_path / "nope") == []


def test_schema_scan_spans_dep_scope(tmp_path):
    from servicenow_mcp.tools.source_tools import _scan_tables_from_source_root

    scope_root = tmp_path / "x_app"
    app_si = scope_root / "sys_script_include" / "A"
    app_si.mkdir(parents=True)
    (app_si / "script.js").write_text("new GlideRecord('app_tbl');")
    dep_si = tmp_path / "global" / "sys_script_include" / "B"
    dep_si.mkdir(parents=True)
    (dep_si / "script.js").write_text("new GlideRecord('global_tbl');")
    (scope_root / "_dep_scopes.json").write_text('{"dep_scopes": ["global"]}')
    tables = _scan_tables_from_source_root(scope_root)
    assert "app_tbl" in tables
    assert "global_tbl" in tables  # dep scope tree is scanned too


def test_audit_index_spans_dep_scope(tmp_path):
    from servicenow_mcp.tools.source_audit_tools import _scan_source_index

    scope_root = tmp_path / "x_app"
    a = scope_root / "sys_script_include" / "A"
    a.mkdir(parents=True)
    (a / "_metadata.json").write_text(
        '{"source_type":"script_include","table":"sys_script_include","sys_id":"a1","name":"A"}'
    )
    (a / "script.js").write_text("x")
    b = tmp_path / "global" / "sys_script_include" / "B"
    b.mkdir(parents=True)
    (b / "_metadata.json").write_text(
        '{"source_type":"script_include","table":"sys_script_include","sys_id":"b1","name":"B"}'
    )
    (b / "script.js").write_text("y")
    (scope_root / "_dep_scopes.json").write_text('{"dep_scopes": ["global"]}')

    idx = _scan_source_index(scope_root)
    names = {e["name"] for e in idx}
    assert "A" in names and "B" in names  # dep from sibling scope is indexed
    b_path = next(e["path"] for e in idx if e["name"] == "B")
    assert b_path.startswith("global/")  # path relative to instance base


# ---------------------------------------------------------------------------
# EOL canonicalization — CRLF bodies land on disk as LF (clean cross-instance diff)
# ---------------------------------------------------------------------------


def test_normalize_source_eol():
    from servicenow_mcp.utils.source_layout import normalize_source_eol

    assert normalize_source_eol("a\r\nb\r\n") == "a\nb\n"  # CRLF -> LF
    assert normalize_source_eol("a\rb") == "a\nb"  # lone CR -> LF
    assert normalize_source_eol("a\nb") == "a\nb"  # already LF, unchanged


class TestDownloadEolNormalization:
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    def test_crlf_body_written_as_lf(self, mqp, mqa, config, auth, tmp_path):
        record = {
            "sys_id": "si-1",
            "name": "Foo",
            "api_name": "x_app.Foo",
            "sys_scope": "x_app",
            "sys_updated_on": "2026-04-01 12:00:00",
            "sys_updated_by": "admin",
            "script": "line1\r\nline2\r\n",
        }
        mqa.return_value = [{k: v for k, v in record.items() if k != "script"}]

        def _page(*a, **k):
            if "si-1" in k.get("query", ""):
                return [{"script": record["script"]}], None
            return [], None

        mqp.side_effect = _page
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )
        raw = (scope_root / "sys_script_include" / "Foo" / "script.js").read_bytes()
        assert b"\r" not in raw  # no CRLF noise survives to disk
        assert raw == b"line1\nline2\n"


class TestBulkDownloadRetry:
    @patch("servicenow_mcp.tools.sn_api.time.sleep")
    @patch("servicenow_mcp.tools.source_tools.sn_query_page")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_transient_error_is_retried_not_fatal(
        self, mock_query_all, mock_query_page, mock_sleep, config, auth, tmp_path
    ):
        # A single 503 mid-bulk-download must retry and complete, not abort
        # the whole multi-record run (issue #63 batch 2).
        import requests as _requests

        resp = MagicMock()
        resp.status_code = 503
        err = _requests.exceptions.HTTPError(response=resp)
        mock_query_all.side_effect = [err, _strip_source(_si_records())]
        mock_query_page.side_effect = _page_side_effect_for(_si_records())
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

        result = _download_source_types(
            config,
            auth,
            scope="x_app",
            source_types=["script_include"],
            scope_root=scope_root,
            root=tmp_path,
        )

        assert result["type_results"]["script_include"]["count"] == len(_si_records())
        assert not any("fetch failed" in w for w in result.get("warnings", []))
        assert mock_query_all.call_count == 2  # failed once, retried once
        assert mock_sleep.called  # backoff happened

    @patch("servicenow_mcp.tools.sn_api.time.sleep")
    @patch("servicenow_mcp.tools.source_tools.sn_query_all")
    def test_non_retryable_error_still_fails_fast(
        self, mock_query_all, mock_sleep, config, auth, tmp_path
    ):
        # Non-transient errors keep the old fail-fast behavior (no retry storm).
        mock_query_all.side_effect = Exception("ACL denied")
        scope_root = tmp_path / "test" / "x_app"
        scope_root.mkdir(parents=True)

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
        assert mock_query_all.call_count == 1  # no retry


def test_qualified_type_keeps_uniform_depth_when_qualifier_is_blank():
    """A qualified type must never mix depths: a record with an empty qualifier
    (a notification with no target table) still nests, under a reserved segment.
    Otherwise `ls <table>/` shows records and qualifier groups side by side."""
    from servicenow_mcp.tools.source_tools import SOURCE_CONFIG, _record_identifier_and_folder

    cfg = SOURCE_CONFIG["email_notification"]
    _, qualified = _record_identifier_and_folder(
        {"sys_id": "n-1", "name": "Escalated", "collection": "incident"}, cfg, "x_app"
    )
    _, blank = _record_identifier_and_folder(
        {"sys_id": "n-2", "name": "Orphan", "collection": ""}, cfg, "x_app"
    )
    _, nameless = _record_identifier_and_folder({"sys_id": "n-3"}, cfg, "x_app")

    assert qualified == "incident/Escalated"
    assert blank == "_unqualified/Orphan"
    assert nameless == "_unqualified/n-3"
    assert len({p.count("/") for p in (qualified, blank, nameless)}) == 1
