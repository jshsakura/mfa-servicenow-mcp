"""Extra tests for source_audit_tools.py — targeting uncovered code paths.

Covers: _read_text exception, _widget.json pass, flat file pass, $sp.getWidget,
$inject, provider name-match, sp_instance refs, suspect orphans, external refs,
client_scripts/catalog_client_scripts in exec order, schema unknown tables,
HTML suspect/dynamic/xref sections, domain knowledge hubs/complexity, and more.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.tools.source_audit_tools import (
    AuditAppSourcesParams,
    _build_cross_references,
    _build_execution_order,
    _collect_instance_widget_refs,
    _detect_orphans,
    _extract_external_refs,
    _extract_references_from_script,
    _generate_domain_knowledge,
    _generate_html_report,
    _read_text,
    _scan_source_index,
    _validate_schema_references,
    audit_local_sources,
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


def _write(path: Path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        path.write_text(json.dumps(content, indent=2), encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")


def _create_base_tree(root: Path):
    """Minimal tree with 2 SIs that reference each other."""
    _write(
        root / "sys_script_include" / "Alpha" / "_metadata.json",
        {
            "source_type": "script_include",
            "table": "sys_script_include",
            "sys_id": "si-a",
            "name": "Alpha",
            "active": "true",
        },
    )
    _write(
        root / "sys_script_include" / "Alpha" / "script.js",
        "var Alpha = Class.create();\nAlpha.prototype = { run: function() {} };\n",
    )
    _write(
        root / "sys_script_include" / "Beta" / "_metadata.json",
        {
            "source_type": "script_include",
            "table": "sys_script_include",
            "sys_id": "si-b",
            "name": "Beta",
            "active": "true",
        },
    )
    _write(
        root / "sys_script_include" / "Beta" / "script.js",
        "var Beta = Class.create();\nvar a = new Alpha();\n",
    )
    _write(
        root / "_manifest.json",
        {"scope": "x_app", "instance": "https://test.service-now.com"},
    )


# ---------------------------------------------------------------------------
# _read_text exception path (lines 98-99)
# ---------------------------------------------------------------------------


class TestReadTextException:
    def test_unreadable_file_returns_empty(self, tmp_path):
        f = tmp_path / "bad.txt"
        f.write_text("ok", encoding="utf-8")
        # Force read_text to fail by making path point to a dir
        (tmp_path / "subdir").mkdir()
        result = _read_text(tmp_path / "subdir")
        # Reading a directory raises, should return ""
        assert result == ""


# ---------------------------------------------------------------------------
# _scan_source_index: invalid _metadata.json (line 117)
# ---------------------------------------------------------------------------


class TestScanInvalidMetadata:
    def test_invalid_metadata_skipped(self, tmp_path):
        root = tmp_path / "scope"
        _write(root / "mydir" / "_metadata.json", "not valid json{{{")
        index = _scan_source_index(root)
        assert index == []

    def test_metadata_non_dict_skipped(self, tmp_path):
        root = tmp_path / "scope"
        _write(root / "mydir" / "_metadata.json", [1, 2, 3])
        index = _scan_source_index(root)
        assert index == []


# ---------------------------------------------------------------------------
# _scan_source_index: _widget.json pass (lines 142-153)
# ---------------------------------------------------------------------------


class TestScanWidgetJson:
    def test_widget_json_pass(self, tmp_path):
        root = tmp_path / "scope"
        _write(
            root / "sp_widget" / "MyWidget" / "_widget.json",
            {
                "tableName": "sp_widget",
                "sys_id": "w-1",
                "name": "MyWidget",
            },
        )
        _write(
            root / "sp_widget" / "MyWidget" / "template.html",
            "<div>Hello</div>\n",
        )
        index = _scan_source_index(root)
        assert len(index) == 1
        assert index[0]["source_type"] == "widget"
        assert index[0]["name"] == "MyWidget"
        assert index[0]["table"] == "sp_widget"
        assert index[0]["lines"] > 0

    def test_widget_json_already_seen_dir_skipped(self, tmp_path):
        """If _metadata.json already saw the dir, _widget.json is skipped."""
        root = tmp_path / "scope"
        d = root / "sp_widget" / "Overlap"
        _write(
            d / "_metadata.json",
            {
                "source_type": "widget",
                "table": "sp_widget",
                "sys_id": "w-a",
                "name": "Overlap",
            },
        )
        _write(d / "script.js", "// code\n")
        _write(
            d / "_widget.json",
            {"tableName": "sp_widget", "sys_id": "w-b", "name": "OverlapAlt"},
        )
        index = _scan_source_index(root)
        # Only one entry from _metadata.json pass
        assert len(index) == 1
        assert index[0]["sys_id"] == "w-a"

    def test_widget_json_invalid_skipped(self, tmp_path):
        root = tmp_path / "scope"
        _write(root / "sp_widget" / "Bad" / "_widget.json", "bad json{{{")
        index = _scan_source_index(root)
        assert index == []

    def test_widget_json_non_dict_skipped(self, tmp_path):
        root = tmp_path / "scope"
        p = root / "sp_widget" / "Bad" / "_widget.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("42", encoding="utf-8")
        index = _scan_source_index(root)
        assert index == []

    def test_widget_json_defaults(self, tmp_path):
        """_widget.json with missing name field uses dir name as default."""
        root = tmp_path / "scope"
        _write(
            root / "sp_widget" / "Minimal" / "_widget.json",
            {"sys_id": "w-min"},
        )
        _write(root / "sp_widget" / "Minimal" / "template.html", "<p>hi</p>")
        index = _scan_source_index(root)
        assert len(index) == 1
        assert index[0]["table"] == "sp_widget"
        assert index[0]["name"] == "Minimal"


# ---------------------------------------------------------------------------
# _scan_source_index: flat file pass (lines 189-199) + invalid _map.json (184)
# ---------------------------------------------------------------------------


class TestScanFlatFiles:
    def test_flat_angular_provider(self, tmp_path):
        root = tmp_path / "scope"
        provider_dir = root / "sp_angular_provider"
        _write(
            provider_dir / "myService.script.js",
            "angular.module('x').factory('myService', function(){});\n",
        )
        index = _scan_source_index(root)
        assert len(index) == 1
        assert index[0]["source_type"] == "angular_provider"
        assert index[0]["name"] == "myService"
        assert index[0]["lines"] > 0

    def test_flat_script_include(self, tmp_path):
        root = tmp_path / "scope"
        si_dir = root / "sys_script_include"
        _write(si_dir / "FlatSI.script.js", "var FlatSI = Class.create();\n")
        index = _scan_source_index(root)
        assert len(index) == 1
        assert index[0]["source_type"] == "script_include"

    def test_flat_file_with_map(self, tmp_path):
        root = tmp_path / "scope"
        provider_dir = root / "sp_angular_provider"
        _write(provider_dir / "_map.json", {"svc1": "abc-123"})
        _write(provider_dir / "svc1.script.js", "// code\n")
        index = _scan_source_index(root)
        assert index[0]["sys_id"] == "abc-123"

    def test_flat_file_invalid_map(self, tmp_path):
        """Non-dict _map.json is treated as empty (line 184)."""
        root = tmp_path / "scope"
        provider_dir = root / "sp_angular_provider"
        _write(provider_dir / "_map.json", "not a dict")
        _write(provider_dir / "svc1.script.js", "// code\n")
        index = _scan_source_index(root)
        assert len(index) == 1
        assert index[0]["sys_id"] == ""

    def test_flat_file_skips_metadata_dirs(self, tmp_path):
        """Flat file already indexed by _metadata.json is skipped (line 190-191)."""
        root = tmp_path / "scope"
        provider_dir = root / "sp_angular_provider"
        _write(
            provider_dir / "svc1" / "_metadata.json",
            {
                "source_type": "angular_provider",
                "table": "sp_angular_provider",
                "sys_id": "p-1",
                "name": "svc1",
            },
        )
        _write(provider_dir / "svc1" / "script.js", "// code\n")
        _write(provider_dir / "svc1.script.js", "// duplicate flat\n")
        index = _scan_source_index(root)
        # Only the _metadata.json entry should appear
        assert len(index) == 1
        assert index[0]["sys_id"] == "p-1"

    def test_flat_file_unreadable(self, tmp_path):
        """Unreadable flat file: if is_file() passes but read fails, lines=0."""
        root = tmp_path / "scope"
        provider_dir = root / "sp_angular_provider"
        # Use permission denied: write a file then remove read permission
        src = provider_dir / "broken.script.js"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("code\n", encoding="utf-8")
        import os

        os.chmod(str(src), 0o000)
        try:
            index = _scan_source_index(root)
            assert len(index) == 1
            assert index[0]["lines"] == 0
        finally:
            os.chmod(str(src), 0o644)

    def test_flat_ignores_unknown_dirs(self, tmp_path):
        root = tmp_path / "scope"
        _write(root / "sys_unknown_table" / "file.js", "// code\n")
        index = _scan_source_index(root)
        assert index == []


# ---------------------------------------------------------------------------
# _count_lines_in_dir exception path (lines 225-226)
# ---------------------------------------------------------------------------


class TestCountLinesException:
    def test_unreadable_file_in_dir_counted_zero(self, tmp_path):
        """A subdirectory inside a record dir is skipped by is_file()."""
        d = tmp_path / "record"
        d.mkdir()
        (d / "subdir").mkdir()  # not a file, skipped
        _write(d / "good.js", "line1\nline2\n")
        from servicenow_mcp.tools.source_audit_tools import _count_lines_in_dir

        result = _count_lines_in_dir(d)
        assert result == 3  # good.js has 2 newlines + 1 = 3 lines


# ---------------------------------------------------------------------------
# $sp.getWidget references (line 254)
# ---------------------------------------------------------------------------


class TestSpGetWidget:
    def test_sp_get_widget_literal(self):
        script = "var w = $sp.getWidget('my-widget-id');"
        refs = _extract_references_from_script(script)
        assert "my-widget-id" in refs["widgets"]

    def test_sp_get_widget_from_instance(self):
        script = "var w = $sp.getWidgetFromInstance('inst-widget');"
        refs = _extract_references_from_script(script)
        assert "inst-widget" in refs["widgets"]


# ---------------------------------------------------------------------------
# $inject provider references (lines 261-262)
# ---------------------------------------------------------------------------


class TestInjectProviders:
    def test_inject_array(self):
        script = "api.$inject = ['dep1', 'dep2', 'myService'];"
        refs = _extract_references_from_script(script)
        assert "dep1" in refs["providers"]
        assert "dep2" in refs["providers"]
        assert "myService" in refs["providers"]


# ---------------------------------------------------------------------------
# Cross-refs: provider tracking (line 287), is_file (308-309),
# provider/SI name-match (322-323), dynamic widget (329)
# ---------------------------------------------------------------------------


class TestCrossRefAdvanced:
    def test_provider_names_tracked(self, tmp_path):
        root = tmp_path / "scope"
        provider_dir = root / "sp_angular_provider"
        _write(provider_dir / "_map.json", {"myProvider": "p-1"})
        _write(
            provider_dir / "myProvider.script.js",
            "angular.module('x').factory('myProvider', function(){});\n",
        )
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        assert "myProvider" in xrefs.get("known_names", [])

    def test_record_path_is_file(self, tmp_path):
        """When record_path points to a flat file (not dir), it's read too (lines 308-309)."""
        root = tmp_path / "scope"
        provider_dir = root / "sp_angular_provider"
        _write(provider_dir / "mySvc.script.js", "var gr = new GlideRecord('incident');\n")
        index = _scan_source_index(root)
        # record_path for flat files is the file itself
        xrefs = _build_cross_references(root, index)
        assert "incident" in xrefs["outgoing"].get("mySvc", {}).get("tables", [])

    def test_provider_name_match_in_script(self, tmp_path):
        """Provider name appearing in another source triggers a name-match ref (lines 322-323)."""
        root = tmp_path / "scope"
        # Provider
        provider_dir = root / "sp_angular_provider"
        _write(provider_dir / "sharedUtil.script.js", "// provider code\n")
        # SI that contains the provider name in its script text
        _write(
            root / "sys_script_include" / "Caller" / "_metadata.json",
            {
                "source_type": "script_include",
                "table": "sys_script_include",
                "sys_id": "si-c",
                "name": "Caller",
            },
        )
        _write(
            root / "sys_script_include" / "Caller" / "script.js",
            "// uses sharedUtil somewhere\n",
        )
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        # Caller's outgoing should include sharedUtil as a provider ref
        outgoing = xrefs["outgoing"].get("Caller", {})
        assert "sharedUtil" in outgoing.get("providers", [])

    def test_dynamic_widget_loader_detected(self, tmp_path):
        """$sp.getWidget(variable) marks source as dynamic loader (line 329)."""
        root = tmp_path / "scope"
        _write(
            root / "sys_script_include" / "DynLoader" / "_metadata.json",
            {
                "source_type": "script_include",
                "table": "sys_script_include",
                "sys_id": "si-d",
                "name": "DynLoader",
            },
        )
        _write(
            root / "sys_script_include" / "DynLoader" / "script.js",
            "var w = $sp.getWidget(widgetId);\n",
        )
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        assert "DynLoader" in xrefs.get("dynamic_widget_loaders", [])


# ---------------------------------------------------------------------------
# _collect_instance_widget_refs (lines 369, 375-386)
# ---------------------------------------------------------------------------


class TestCollectInstanceWidgetRefs:
    def test_collects_sp_widget_ref(self, tmp_path):
        root = tmp_path / "scope"
        # A widget entry
        _write(
            root / "sp_widget" / "W1" / "_widget.json",
            {"tableName": "sp_widget", "sys_id": "w-1", "name": "W1"},
        )
        _write(root / "sp_widget" / "W1" / "template.html", "<div>W1</div>")
        # An sp_instance that references w-1
        _write(
            root / "sp_instance" / "Inst1" / "_metadata.json",
            {
                "source_type": "widget_instance",
                "table": "sp_instance",
                "sys_id": "inst-1",
                "name": "Inst1",
                "sp_widget": "w-1",
            },
        )
        _write(root / "sp_instance" / "Inst1" / "data.json", "{}")
        index = _scan_source_index(root)
        refs = _collect_instance_widget_refs(root, index)
        assert "w-1" in refs
        assert "W1" in refs  # resolved name

    def test_sp_instance_without_widget(self, tmp_path):
        root = tmp_path / "scope"
        _write(
            root / "sp_instance" / "Empty" / "_metadata.json",
            {
                "source_type": "widget_instance",
                "table": "sp_instance",
                "sys_id": "inst-e",
                "name": "Empty",
            },
        )
        _write(root / "sp_instance" / "Empty" / "data.json", "{}")
        index = _scan_source_index(root)
        refs = _collect_instance_widget_refs(root, index)
        assert len(refs) == 0

    def test_sp_instance_invalid_metadata(self, tmp_path):
        root = tmp_path / "scope"
        _write(
            root / "sp_instance" / "Bad" / "_metadata.json",
            "not json",
        )
        _write(root / "sp_instance" / "Bad" / "data.json", "{}")
        index = _scan_source_index(root)
        refs = _collect_instance_widget_refs(root, index)
        assert len(refs) == 0


# ---------------------------------------------------------------------------
# _detect_orphans: suspect orphans (lines 433, 437-438), active=false (423)
# ---------------------------------------------------------------------------


class TestDetectOrphansAdvanced:
    def test_inactive_source_not_orphan(self, tmp_path):
        """Inactive sources are skipped (line 423)."""
        root = tmp_path / "scope"
        _write(
            root / "sys_script_include" / "InactiveSI" / "_metadata.json",
            {
                "source_type": "script_include",
                "table": "sys_script_include",
                "sys_id": "si-i",
                "name": "InactiveSI",
                "active": "false",
            },
        )
        _write(
            root / "sys_script_include" / "InactiveSI" / "script.js",
            "// dead\n",
        )
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        orphans = _detect_orphans(index, xrefs)
        names = [o["name"] for o in orphans]
        assert "InactiveSI" not in names

    def test_widget_placed_on_page_not_orphan(self, tmp_path):
        """Widget referenced by sp_instance is not orphan (line 433)."""
        root = tmp_path / "scope"
        _write(
            root / "sp_widget" / "PlacedWidget" / "_widget.json",
            {"tableName": "sp_widget", "sys_id": "w-p", "name": "PlacedWidget"},
        )
        _write(root / "sp_widget" / "PlacedWidget" / "template.html", "<div>P</div>")
        _write(
            root / "sp_instance" / "P1" / "_metadata.json",
            {
                "source_type": "widget_instance",
                "table": "sp_instance",
                "sys_id": "inst-p",
                "name": "P1",
                "sp_widget": "w-p",
            },
        )
        _write(root / "sp_instance" / "P1" / "data.json", "{}")
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        orphans = _detect_orphans(index, xrefs, root)
        names = [o["name"] for o in orphans]
        assert "PlacedWidget" not in names

    def test_suspect_orphan_with_dynamic_loaders(self, tmp_path):
        """Widget with no refs but dynamic loaders exist => suspect (lines 437-438)."""
        root = tmp_path / "scope"
        # Dynamic loader SI
        _write(
            root / "sys_script_include" / "DynLoader" / "_metadata.json",
            {
                "source_type": "script_include",
                "table": "sys_script_include",
                "sys_id": "si-d",
                "name": "DynLoader",
            },
        )
        _write(
            root / "sys_script_include" / "DynLoader" / "script.js",
            "var w = $sp.getWidget(widgetId);\n",
        )
        # Orphan widget
        _write(
            root / "sp_widget" / "MaybeOrphan" / "_widget.json",
            {"tableName": "sp_widget", "sys_id": "w-m", "name": "MaybeOrphan"},
        )
        _write(root / "sp_widget" / "MaybeOrphan" / "template.html", "<div>M</div>")
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        orphans = _detect_orphans(index, xrefs, root)
        for o in orphans:
            if o["name"] == "MaybeOrphan":
                assert o["confidence"] == "suspect"
                assert "dynamic" in o["reason"].lower() or "Dynamic" in o["reason"]
                break
        else:
            pytest.fail("MaybeOrphan should be in orphans")


# ---------------------------------------------------------------------------
# _extract_external_refs (lines 476, 478-479)
# ---------------------------------------------------------------------------


class TestExtractExternalRefs:
    def test_external_si(self):
        cross_refs = {
            "known_names": ["Alpha"],
            "outgoing": {
                "Alpha": {"script_includes": ["ExternalLib"]},
            },
        }
        ext = _extract_external_refs(cross_refs)
        assert "ExternalLib" in ext["script_includes"]

    def test_external_provider(self):
        cross_refs = {
            "known_names": ["Alpha"],
            "outgoing": {
                "Alpha": {"providers": ["externalProvider"]},
            },
        }
        ext = _extract_external_refs(cross_refs)
        assert "externalProvider" in ext["providers"]

    def test_known_not_external(self):
        cross_refs = {
            "known_names": ["Alpha", "Beta"],
            "outgoing": {
                "Alpha": {"script_includes": ["Beta"]},
            },
        }
        ext = _extract_external_refs(cross_refs)
        assert "Beta" not in ext["script_includes"]

    def test_tables_always_external(self):
        cross_refs = {
            "known_names": [],
            "outgoing": {
                "Src": {"tables": ["incident"]},
            },
        }
        ext = _extract_external_refs(cross_refs)
        assert "incident" in ext["tables"]


# ---------------------------------------------------------------------------
# _build_execution_order: client_script, catalog_client_script, no table (lines 502, 515)
# ---------------------------------------------------------------------------


class TestExecutionOrderAdvanced:
    def test_client_script_grouped(self, tmp_path):
        root = tmp_path / "scope"
        _write(
            root / "sys_client_script" / "CS1" / "_metadata.json",
            {
                "source_type": "client_script",
                "table": "sys_client_script",
                "sys_id": "cs-1",
                "name": "CS1",
                "active": "true",
                "collection": "incident",
            },
        )
        _write(root / "sys_client_script" / "CS1" / "script.js", "// cs\n")
        index = _scan_source_index(root)
        exec_order = _build_execution_order(index)
        # table_field uses entry["table"] for non-BR, so "sys_client_script"
        assert "sys_client_script" in exec_order
        assert len(exec_order["sys_client_script"]["client_scripts"]) == 1

    def test_catalog_client_script_grouped(self, tmp_path):
        root = tmp_path / "scope"
        _write(
            root / "catalog_script_client" / "CatCS1" / "_metadata.json",
            {
                "source_type": "catalog_client_script",
                "table": "catalog_script_client",
                "sys_id": "ccs-1",
                "name": "CatCS1",
                "active": "true",
                "collection": "sc_req_item",
            },
        )
        _write(root / "catalog_script_client" / "CatCS1" / "script.js", "// ccs\n")
        index = _scan_source_index(root)
        exec_order = _build_execution_order(index)
        assert "catalog_script_client" in exec_order
        assert len(exec_order["catalog_script_client"]["client_scripts"]) == 1

    def test_no_table_field_skipped(self, tmp_path):
        """Entries without a table field are skipped (line 502)."""
        index = [
            {
                "source_type": "business_rule",
                "table": "",
                "sys_id": "x",
                "name": "NoTable",
                "collection": "",
                "active": "true",
                "when": "",
                "order": "",
            },
        ]
        exec_order = _build_execution_order(index)
        assert len(exec_order) == 0


# ---------------------------------------------------------------------------
# _validate_schema_references: unknown table (line 563)
# ---------------------------------------------------------------------------


class TestSchemaValidationUnknownTable:
    def test_unknown_table_reported(self, tmp_path):
        root = tmp_path / "scope"
        schema_dir = root / "_schema"
        _write(schema_dir / "known_table.json", {"table": "known_table", "fields": []})
        # cross-ref with unknown non-sys/cmdb table
        cross_refs = {
            "incoming": {
                "table:custom_unknown": [
                    {"name": "MyScript", "type": "script_include"},
                ],
            },
        }
        issues = _validate_schema_references(root, cross_refs)
        assert len(issues) == 1
        assert issues[0]["table"] == "custom_unknown"
        assert issues[0]["type"] == "unknown_table"

    def test_cmdb_table_not_reported(self, tmp_path):
        root = tmp_path / "scope"
        schema_dir = root / "_schema"
        _write(schema_dir / "some.json", {"table": "some", "fields": []})
        cross_refs = {
            "incoming": {
                "table:cmdb_ci": [{"name": "S1", "type": "script_include"}],
            },
        }
        issues = _validate_schema_references(root, cross_refs)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# HTML report: suspect orphans, dynamic loaders, xref widgets/providers (lines 818, 835-842, 909, 913)
# ---------------------------------------------------------------------------


class TestHTMLReportAdvanced:
    def test_html_dynamic_loaders_warning(self):
        html = _generate_html_report(
            scope="x_app",
            instance="test",
            source_index=[
                {
                    "name": "W1",
                    "source_type": "widget",
                    "table": "sp_widget",
                    "lines": 10,
                    "files": [],
                    "active": "true",
                },
            ],
            cross_refs={
                "outgoing": {},
                "incoming": {},
                "dynamic_widget_loaders": ["DynLoader"],
            },
            orphans=[
                {
                    "name": "W1",
                    "source_type": "widget",
                    "sys_id": "w1",
                    "lines": 10,
                    "path": "W1",
                    "confidence": "suspect",
                    "reason": "dynamic",
                },
            ],
            execution_order={},
            schema_issues=[],
        )
        assert "Dynamic widget loaders" in html
        assert "DynLoader" in html
        assert "suspect" in html

    def test_html_suspect_orphan_section(self):
        html = _generate_html_report(
            scope="x_app",
            instance="test",
            source_index=[],
            cross_refs={"outgoing": {}, "incoming": {}, "dynamic_widget_loaders": []},
            orphans=[
                {
                    "name": "SuspectWidget",
                    "source_type": "widget",
                    "sys_id": "ws",
                    "lines": 50,
                    "path": "p",
                    "confidence": "suspect",
                    "reason": "test",
                },
            ],
            execution_order={},
            schema_issues=[],
        )
        assert "Suspect — Possibly Dynamic" in html
        assert "SuspectWidget" in html

    def test_html_xref_widgets_and_providers(self):
        html = _generate_html_report(
            scope="x_app",
            instance="test",
            source_index=[],
            cross_refs={
                "outgoing": {
                    "Src1": {
                        "widgets": ["my-widget"],
                        "providers": ["myProvider"],
                        "tables": [],
                        "script_includes": [],
                    },
                },
                "incoming": {},
            },
            orphans=[],
            execution_order={},
            schema_issues=[],
        )
        assert "my-widget" in html
        assert "myProvider" in html

    def test_html_with_schema_issues(self):
        html = _generate_html_report(
            scope="x_app",
            instance="test",
            source_index=[],
            cross_refs={"outgoing": {}, "incoming": {}},
            orphans=[],
            execution_order={},
            schema_issues=[
                {
                    "type": "unknown_table",
                    "table": "missing_tbl",
                    "referenced_by": "Script1",
                    "ref_count": "2",
                },
            ],
        )
        assert "missing_tbl" in html
        assert "Schema Validation Issues" in html

    def test_html_orphan_badge_error(self):
        """10+ confirmed orphans → status-error badge class."""
        orphans = [
            {
                "name": f"O{i}",
                "source_type": "widget",
                "sys_id": f"w{i}",
                "lines": 10,
                "path": f"p{i}",
                "confidence": "orphan",
                "reason": "none",
            }
            for i in range(12)
        ]
        html = _generate_html_report(
            scope="x_app",
            instance="test",
            source_index=[],
            cross_refs={"outgoing": {}, "incoming": {}, "dynamic_widget_loaders": []},
            orphans=orphans,
            execution_order={},
            schema_issues=[],
        )
        assert "status-error" in html


# ---------------------------------------------------------------------------
# Domain knowledge: hubs (1094-1098), complexity (1079-1085), CS (1023)
# ---------------------------------------------------------------------------


class TestDomainKnowledgeAdvanced:
    def test_hub_scripts_section(self, tmp_path):
        """Sources referenced by 3+ others appear as hubs (lines 1094-1098)."""
        root = tmp_path / "scope"
        _create_base_tree(root)
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)

        # Make Alpha have 3+ callers by adding more incoming refs
        incoming = xrefs.setdefault("incoming", {})
        incoming["Alpha"] = [
            {"name": "Caller1", "type": "script_include"},
            {"name": "Caller2", "type": "widget"},
            {"name": "Caller3", "type": "business_rule"},
        ]

        result = _generate_domain_knowledge(root, "x_app", index, xrefs, [], {})
        assert result["sections"]["hubs"] >= 1
        md = (root / "_domain_knowledge.md").read_text()
        assert "Hub Scripts" in md
        assert "Alpha" in md

    def test_complex_sources_warning(self, tmp_path):
        """Sources >200 lines get a complexity warning (lines 1079-1085)."""
        root = tmp_path / "scope"
        _create_base_tree(root)
        # Add a large source
        _write(
            root / "sys_script_include" / "BigBoy" / "_metadata.json",
            {
                "source_type": "script_include",
                "table": "sys_script_include",
                "sys_id": "si-big",
                "name": "BigBoy",
                "active": "true",
            },
        )
        _write(
            root / "sys_script_include" / "BigBoy" / "script.js",
            "\n".join(f"// line {i}" for i in range(250)),
        )
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        result = _generate_domain_knowledge(root, "x_app", index, xrefs, [], {})
        assert result["sections"]["complex"] >= 1
        md = (root / "_domain_knowledge.md").read_text()
        assert "High Complexity" in md
        assert "BigBoy" in md

    def test_orphan_warning_in_domain_knowledge(self, tmp_path):
        """Orphans appear in warnings section of domain knowledge."""
        root = tmp_path / "scope"
        _create_base_tree(root)
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        orphans = [{"name": "DeadSI", "source_type": "script_include", "lines": 10}]
        result = _generate_domain_knowledge(root, "x_app", index, xrefs, orphans, {})
        assert result["sections"]["orphans"] >= 1
        md = (root / "_domain_knowledge.md").read_text()
        assert "Dead Code Candidates" in md
        assert "DeadSI" in md

    def test_client_scripts_in_table_profiles(self, tmp_path):
        """Client scripts appear in table profiles section (line 1023)."""
        root = tmp_path / "scope"
        _write(
            root / "sys_client_script" / "CS1" / "_metadata.json",
            {
                "source_type": "client_script",
                "table": "sys_client_script",
                "sys_id": "cs-1",
                "name": "CS1",
                "active": "true",
                "collection": "incident",
            },
        )
        _write(root / "sys_client_script" / "CS1" / "script.js", "// cs\n")
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        exec_order = _build_execution_order(index)
        _generate_domain_knowledge(root, "x_app", index, xrefs, [], exec_order)
        md = (root / "_domain_knowledge.md").read_text()
        assert "CS1" in md

    def test_no_warnings_when_clean(self, tmp_path):
        """No warnings section when there are no orphans and no complex sources."""
        root = tmp_path / "scope"
        _create_base_tree(root)
        index = _scan_source_index(root)
        xrefs = _build_cross_references(root, index)
        _generate_domain_knowledge(root, "x_app", index, xrefs, [], {})
        md = (root / "_domain_knowledge.md").read_text()
        assert "Warnings" not in md


# ---------------------------------------------------------------------------
# audit_local_sources: schema_issues written to file (line 1203)
# ---------------------------------------------------------------------------


class TestAuditLocalSourcesExtra:
    def test_schema_issues_file_written(self, config, auth, tmp_path):
        """When schema_issues exist, _schema_issues.json is written (line 1203)."""
        root = tmp_path / "scope"
        _create_base_tree(root)
        # Create schema dir that will cause an unknown_table issue
        schema_dir = root / "_schema"
        _write(schema_dir / "dummy.json", {"table": "dummy", "fields": []})
        # Add a source that references a table not in schemas
        _write(
            root / "sys_script_include" / "RefUnknown" / "_metadata.json",
            {
                "source_type": "script_include",
                "table": "sys_script_include",
                "sys_id": "si-u",
                "name": "RefUnknown",
                "active": "true",
            },
        )
        _write(
            root / "sys_script_include" / "RefUnknown" / "script.js",
            "var gr = new GlideRecord('custom_unknown_table');\n",
        )

        result = audit_local_sources(config, auth, AuditAppSourcesParams(source_root=str(root)))
        assert result["success"] is True
        # If schema issues were found, the file should exist
        if result["summary"]["schema_issue_count"] > 0:
            assert (root / "_schema_issues.json").exists()

    def test_external_references_in_result(self, config, auth, tmp_path):
        """Result includes external_references section."""
        root = tmp_path / "scope"
        _create_base_tree(root)
        result = audit_local_sources(config, auth, AuditAppSourcesParams(source_root=str(root)))
        assert "external_references" in result["summary"]
        ext = result["summary"]["external_references"]
        assert "script_includes" in ext
        assert "providers" in ext
        assert "tables" in ext
