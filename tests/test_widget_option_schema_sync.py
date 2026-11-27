"""Widget option DEFINITIONS (sp_widget.option_schema) and preview data round-trip.

The downloader always wrote option_schema.json / demo_data.json, but re-serialized
them and recorded no anchor, while diff/push skipped the files and update_code
refused the fields: an edited default_value could be downloaded and never sent,
and the next download overwrote it. These pin the round trip — and the line
between a widget's option definitions and one placement's option VALUES
(sp_instance.widget_parameters), which is a different record and a different tool.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    DownloadPortalSourcesParams,
    _validate_portal_component_update_data,
    download_portal_sources,
)
from servicenow_mcp.tools.sync_tools import (
    _build_update_data_and_magnitude,
    _compute_field_diffs,
    _field_state,
    _invalid_json_fields,
    _resolve_local_path,
)
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.source_layout import json_bodies_equal
from servicenow_mcp.utils.sync_anchor import (
    LEGACY_KEPT,
    REFRESHED,
    field_sha,
    reconcile_field,
)

WIDGET_SYS_ID = "aaaa1111bbbb2222cccc3333dddd4444"
# As the server stores it: pretty-printed, as the widget editor saves it.
SERVER_SCHEMA = (
    '[\n  {\n    "name": "title",\n    "type": "string",\n'
    '    "label": "Title",\n    "default_value": ""\n  }\n]'
)
EDITED_SCHEMA = SERVER_SCHEMA.replace('"default_value": ""', '"default_value": "Hello"')


@pytest.fixture
def config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def auth_manager():
    manager = MagicMock()
    manager.get_headers.return_value = {"Authorization": "Basic Zm9vOmJhcg=="}
    return manager


def _widget_row(option_schema: str = SERVER_SCHEMA, mod_count: str = "3") -> dict:
    return {
        "sys_id": WIDGET_SYS_ID,
        "name": "Sample Widget",
        "id": "sample_widget",
        "sys_scope": "x_myapp",
        "template": "<div></div>",
        "script": "",
        "client_script": "",
        "link": "",
        "css": "",
        "option_schema": option_schema,
        "demo_data": '{"data": {}}',
        "sys_updated_on": "2026-01-01 00:00:00",
        "sys_updated_by": "alice",
        "sys_mod_count": mod_count,
    }


def _download(config, auth_manager, tmp_path: Path, row: dict) -> dict:
    with (
        patch(
            "servicenow_mcp.tools.portal_tools.sn_query_all",
            side_effect=lambda *a, **k: [row] if k.get("table") == "sp_widget" else [],
        ),
        patch("servicenow_mcp.tools.portal_tools.sn_query_page", return_value=([], None)),
    ):
        return download_portal_sources(
            config,
            auth_manager,
            DownloadPortalSourcesParams(
                output_dir=str(tmp_path / "x_myapp"),
                scope="x_myapp",
                include_linked_script_includes=False,
                include_linked_angular_providers=False,
            ),
        )


def _widget_dir(tmp_path: Path) -> Path:
    return tmp_path / "x_myapp" / "sp_widget" / "sample_widget"


def _sync_entry(tmp_path: Path) -> dict:
    meta = json.loads((tmp_path / "x_myapp" / "sp_widget" / "_sync_meta.json").read_text())
    return meta["sample_widget"]


# --- download --------------------------------------------------------------


def test_download_writes_server_text_verbatim_and_anchors_it(config, auth_manager, tmp_path):
    result = _download(config, auth_manager, tmp_path, _widget_row())

    assert result["success"] is True
    on_disk = (_widget_dir(tmp_path) / "option_schema.json").read_text(encoding="utf-8")
    assert on_disk == SERVER_SCHEMA  # not re-serialized
    shas = _sync_entry(tmp_path)["field_shas"]
    assert shas["option_schema"] == field_sha(SERVER_SCHEMA)
    assert shas["demo_data"] == field_sha('{"data": {}}')


def test_untouched_legacy_file_is_replaced_by_server_text(config, auth_manager, tmp_path):
    # What the old writer left behind: compact re-serialization, no anchor.
    legacy = json_fast.dumps(json.loads(SERVER_SCHEMA))
    path = _widget_dir(tmp_path) / "option_schema.json"
    path.parent.mkdir(parents=True)
    path.write_text(legacy, encoding="utf-8")

    result = _download(config, auth_manager, tmp_path, _widget_row())

    assert path.read_text(encoding="utf-8") == SERVER_SCHEMA
    assert _sync_entry(tmp_path)["field_shas"]["option_schema"] == field_sha(SERVER_SCHEMA)
    # The server did not change; the message must not say it did.
    assert any("same value, the server did not change" in w for w in result["warnings"])
    assert not any("server had updated" in w for w in result["warnings"])


def test_edited_legacy_file_is_kept_and_the_record_watermark_does_not_advance(
    config, auth_manager, tmp_path
):
    # Old tree: anchored at mod_count 3, option_schema.json never anchored; the
    # user edited a default. The server has since moved to 5.
    scope = tmp_path / "x_myapp" / "sp_widget"
    path = scope / "sample_widget" / "option_schema.json"
    path.parent.mkdir(parents=True)
    edited_legacy = json_fast.dumps(json.loads(EDITED_SCHEMA))
    path.write_text(edited_legacy, encoding="utf-8")
    (scope / "_sync_meta.json").write_text(
        json.dumps(
            {
                "sample_widget": {
                    "sys_id": WIDGET_SYS_ID,
                    "sys_updated_on": "2025-12-01 00:00:00",
                    "sys_updated_by": "alice",
                    "sys_mod_count": "3",
                    "field_shas": {},
                }
            }
        )
    )

    result = _download(config, auth_manager, tmp_path, _widget_row(mod_count="5"))

    assert path.read_text(encoding="utf-8") == edited_legacy  # the edit survives
    assert "option_schema" not in _sync_entry(tmp_path).get("field_shas", {})
    # Prior watermark kept: a push of this file still faces the drift gate.
    assert _sync_entry(tmp_path)["sys_mod_count"] == "3"
    assert str(path) in json.dumps(result)
    # Not claimed to be "your edit", nor the server "unchanged" — neither was read.
    kept = [w for w in result["warnings"] if "no recorded anchor" in w]
    assert kept and "NOT determined" in kept[0]
    assert not any("server copy unchanged" in w for w in result["warnings"])
    assert "differ from the server" in result["local_edits_decision"]["question"]


# --- diff / push -----------------------------------------------------------


def _local_widget(tmp_path: Path, option_schema: str) -> Path:
    folder = tmp_path / "x_myapp" / "sp_widget" / "sample_widget"
    folder.mkdir(parents=True)
    (folder.parent / "_map.json").write_text(json.dumps({"sample_widget": WIDGET_SYS_ID}))
    (folder / "_widget.json").write_text(
        json.dumps({"sys_id": WIDGET_SYS_ID, "tableName": "sp_widget"})
    )
    (folder / "script.js").write_text("", encoding="utf-8")
    (folder / "option_schema.json").write_text(option_schema, encoding="utf-8")
    return folder


def test_option_schema_file_resolves_as_a_pushable_field(tmp_path):
    folder = _local_widget(tmp_path, EDITED_SCHEMA)

    by_folder = _resolve_local_path(folder)
    by_file = _resolve_local_path(folder / "option_schema.json")

    assert by_folder.fields["option_schema"] == folder / "option_schema.json"
    assert set(by_file.fields) == {"option_schema"}


def test_an_edited_default_is_pushed(tmp_path):
    resolved = _resolve_local_path(_local_widget(tmp_path, EDITED_SCHEMA))

    update_data, changed, _total = _build_update_data_and_magnitude(
        resolved, {"script": "", "option_schema": SERVER_SCHEMA}
    )

    assert update_data == {"option_schema": EDITED_SCHEMA}
    assert changed > 0


def test_a_reformat_alone_is_neither_pushed_nor_reported(tmp_path):
    compact = json_fast.dumps(json.loads(SERVER_SCHEMA))
    resolved = _resolve_local_path(_local_widget(tmp_path, compact))
    remote = {"script": "", "option_schema": SERVER_SCHEMA}

    update_data, _changed, _total = _build_update_data_and_magnitude(resolved, remote)
    diffs = _compute_field_diffs(resolved, remote, 3)

    assert update_data == {}
    assert {d["field"]: d["status"] for d in diffs}["option_schema"] == "unchanged"
    assert _field_state(compact, None, SERVER_SCHEMA, as_json=True) == "in_sync"
    # A non-JSON field never gets value equality.
    assert _field_state(compact, None, SERVER_SCHEMA) == "changed_no_anchor"


def test_push_refuses_option_schema_that_is_not_an_array(tmp_path):
    resolved = _resolve_local_path(_local_widget(tmp_path, '{"name": "title"}'))

    assert "array" in _invalid_json_fields(resolved)["option_schema"]


def test_push_refuses_option_schema_that_does_not_parse(tmp_path):
    resolved = _resolve_local_path(_local_widget(tmp_path, '[{"name": "title",]'))

    assert "option_schema" in _invalid_json_fields(resolved)


# --- update_code -------------------------------------------------------------


@pytest.mark.parametrize("table", ["sp_widget", "sp_header_footer"])
def test_update_code_accepts_option_schema_and_demo_data(table):
    data = {"option_schema": EDITED_SCHEMA, "demo_data": '{"data": {}}'}

    assert _validate_portal_component_update_data(table, data) == data


def test_update_code_accepts_clearing_option_schema():
    assert _validate_portal_component_update_data("sp_widget", {"option_schema": ""}) == {
        "option_schema": ""
    }


@pytest.mark.parametrize(
    "value, needle",
    [('[{"name": "title",]', "not valid JSON"), ('{"name": "title"}', "JSON array")],
)
def test_update_code_refuses_a_broken_option_schema(value, needle):
    with pytest.raises(ValueError, match=needle):
        _validate_portal_component_update_data("sp_widget", {"option_schema": value})


def test_update_code_points_instance_values_at_the_layout_tool():
    with pytest.raises(ValueError) as exc:
        _validate_portal_component_update_data("sp_widget", {"widget_parameters": "{}"})

    message = str(exc.value)
    assert "sp_instance" in message
    assert "manage_portal_layout(action='move_widget'" in message


# --- comparison primitives -----------------------------------------------------


def test_json_equality_does_not_merge_types():
    assert json_bodies_equal('{"a": 1, "b": [1]}', '{"b":[1],"a":1}')
    assert not json_bodies_equal('{"a": true}', '{"a": 1}')
    assert not json_bodies_equal('{"a": 1}', '{"a": 1.0}')
    assert not json_bodies_equal("", "[]")
    assert not json_bodies_equal("not json", "not json")


def test_reconcile_fast_forwards_a_json_file_equal_by_value(tmp_path):
    path = tmp_path / "option_schema.json"
    path.write_text(json_fast.dumps(json.loads(SERVER_SCHEMA)), encoding="utf-8")

    outcome, sha = reconcile_field(path, SERVER_SCHEMA, "")

    assert outcome == REFRESHED
    assert sha == field_sha(SERVER_SCHEMA)
    assert path.read_text(encoding="utf-8") == SERVER_SCHEMA


def test_reconcile_keeps_a_json_file_that_differs_by_value(tmp_path):
    path = tmp_path / "option_schema.json"
    path.write_text(EDITED_SCHEMA, encoding="utf-8")

    outcome, _sha = reconcile_field(path, SERVER_SCHEMA, "")

    assert outcome == LEGACY_KEPT
    assert path.read_text(encoding="utf-8") == EDITED_SCHEMA
