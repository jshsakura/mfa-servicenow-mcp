import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    AnalyzePortalComponentUpdateParams,
    CreatePortalComponentSnapshotParams,
    DetectAngularImplicitGlobalsParams,
    DownloadPortalSourcesParams,
    GetPortalComponentParams,
    GetWidgetBundleParams,
    PreviewPortalComponentUpdateParams,
    RoutePortalComponentEditParams,
    SearchPortalRegexMatchesParams,
    TracePortalRouteTargetsParams,
    UpdatePortalComponentFromSnapshotParams,
    UpdatePortalComponentParams,
    analyze_portal_component_update,
    create_portal_component_snapshot,
    detect_angular_implicit_globals,
    download_portal_sources,
    get_portal_component_code,
    get_widget_bundle,
    preview_portal_component_update,
    route_portal_component_edit,
    search_portal_regex_matches,
    trace_portal_route_targets,
    update_portal_component,
    update_portal_component_from_snapshot,
)
from servicenow_mcp.utils.config import ServerConfig

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "portal_edit"


def _load_portal_edit_fixture(name: str):
    return json.loads((FIXTURE_ROOT / name).read_text())


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth_manager():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_get_widget_bundle_success(mock_sn_query, mock_config, mock_auth_manager):
    # Mock Widget Data
    mock_sn_query.side_effect = [
        {
            "success": True,
            "results": [
                {
                    "name": "Test Widget",
                    "sys_id": "wid-123",
                    "template": "<div></div>",
                    "id": "test_id",
                }
            ],
        },  # Widget
        {"success": True, "results": [{"sp_angular_provider": {"value": "prov-123"}}]},  # M2M
        {
            "success": True,
            "results": [{"name": "Test Provider", "sys_id": "prov-123", "type": "factory"}],
        },  # Provider
    ]

    params = GetWidgetBundleParams(widget_id="test_id")
    result = get_widget_bundle(mock_config, mock_auth_manager, params)

    assert "widget" in result
    assert result["widget"]["name"] == "Test Widget"
    assert "angular_providers" in result
    assert len(result["angular_providers"]) == 1
    assert result["angular_providers"][0]["name"] == "Test Provider"


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_get_portal_component_code_pagination(mock_sn_query, mock_config, mock_auth_manager):
    # Mock large script with line breaks
    large_script = "\n".join([f"var line{i} = {i};" for i in range(2000)])
    mock_sn_query.return_value = {
        "success": True,
        "results": [{"script": large_script, "sys_id": "sys-1", "name": "Test"}],
    }

    # First page
    params = GetPortalComponentParams(
        table="sp_widget", sys_id="sys-1", fields=["script"], script_max_length=5000
    )
    result = get_portal_component_code(mock_config, mock_auth_manager, params)

    assert len(result["script"]) <= 5000
    assert result["_script_total_length"] == len(large_script)
    assert result["_script_offset"] == 0
    assert result["_script_has_more"] is True
    assert result["_script_next_offset"] > 0
    # Should end at a newline boundary
    assert result["script"].endswith("\n")

    # Second page using next_offset
    params2 = GetPortalComponentParams(
        table="sp_widget",
        sys_id="sys-1",
        fields=["script"],
        script_offset=result["_script_next_offset"],
        script_max_length=5000,
    )
    result2 = get_portal_component_code(mock_config, mock_auth_manager, params2)
    assert result2["_script_offset"] == result["_script_next_offset"]


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_get_widget_bundle_matches_widget_name(mock_sn_query, mock_config, mock_auth_manager):
    mock_sn_query.side_effect = [
        {
            "success": True,
            "results": [
                {
                    "name": "Budget Widget",
                    "sys_id": "wid-123",
                    "template": "<div></div>",
                    "script": "",
                    "client_script": "",
                    "css": "",
                    "id": "budget_widget",
                }
            ],
        },
        {"success": True, "results": []},
    ]

    result = get_widget_bundle(
        mock_config,
        mock_auth_manager,
        GetWidgetBundleParams(widget_id="Budget Widget"),
    )

    assert result["widget"]["name"] == "Budget Widget"
    first_params = mock_sn_query.call_args_list[0].args[2]
    assert "ORname=Budget Widget" in first_params.query


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_get_portal_component_code_minified_fallback(mock_sn_query, mock_config, mock_auth_manager):
    # Minified code — no newlines
    large_script = ";".join([f"var x{i}={i}" for i in range(3000)])
    mock_sn_query.return_value = {
        "success": True,
        "results": [{"script": large_script, "sys_id": "sys-1", "name": "Test"}],
    }

    params = GetPortalComponentParams(
        table="sp_widget", sys_id="sys-1", fields=["script"], script_max_length=5000
    )
    result = get_portal_component_code(mock_config, mock_auth_manager, params)

    assert len(result["script"]) <= 5000
    # Should end at a semicolon boundary
    assert result["script"].endswith(";")


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_analyze_portal_component_update_returns_risk_summary(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {
        "success": True,
        "results": [
            {
                "sys_id": "sys-1",
                "name": "Benefits Widget",
                "client_script": "function run(){return true;}",
            }
        ],
    }

    result = analyze_portal_component_update(
        mock_config,
        mock_auth_manager,
        AnalyzePortalComponentUpdateParams(
            table="sp_widget",
            sys_id="sys-1",
            update_data={"client_script": "function run(){return false;}"},
        ),
    )

    assert result["success"] is True
    assert result["risk_level"] in {"low", "medium", "high"}
    assert result["edit_scope"]["changed_fields"] == ["client_script"]
    assert result["field_analysis"][0]["changed"] is True
    assert "Apply with update_portal_component" in result["recommended_flow"][1]


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_analyze_portal_component_update_matches_fixture_contract(
    mock_sn_query, mock_config, mock_auth_manager
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    update_data = _load_portal_edit_fixture("widget_update_data.json")
    expected = _load_portal_edit_fixture("expected_analyze.json")

    mock_sn_query.return_value = {"success": True, "results": [before_record]}

    result = analyze_portal_component_update(
        mock_config,
        mock_auth_manager,
        AnalyzePortalComponentUpdateParams(
            table="sp_widget",
            sys_id=before_record["sys_id"],
            update_data=update_data,
        ),
    )

    assert result == expected


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_preview_portal_component_update_returns_bounded_diff(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {
        "success": True,
        "results": [
            {
                "sys_id": "sys-1",
                "name": "Benefits Widget",
                "template": "<div>{{data.old}}</div>",
            }
        ],
    }

    result = preview_portal_component_update(
        mock_config,
        mock_auth_manager,
        PreviewPortalComponentUpdateParams(
            table="sp_widget",
            sys_id="sys-1",
            update_data={"template": "<div>{{data.new}}</div>"},
        ),
    )

    assert result["success"] is True
    assert result["preview"][0]["field"] == "template"
    assert result["preview"][0]["changed"] is True
    assert "--- current" in result["preview"][0]["diff_preview"]


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_preview_portal_component_update_matches_fixture_contract(
    mock_sn_query, mock_config, mock_auth_manager
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    update_data = _load_portal_edit_fixture("widget_update_data.json")
    expected = _load_portal_edit_fixture("expected_preview.json")

    mock_sn_query.return_value = {"success": True, "results": [before_record]}

    result = preview_portal_component_update(
        mock_config,
        mock_auth_manager,
        PreviewPortalComponentUpdateParams(
            table="sp_widget",
            sys_id=before_record["sys_id"],
            update_data=update_data,
        ),
    )

    assert result == expected


@patch("servicenow_mcp.tools.portal_tools.sn_query")
@patch("servicenow_mcp.tools.portal_tools.invalidate_query_cache")
def test_update_portal_component_success(
    mock_invalidate_query_cache, mock_sn_query, mock_config, mock_auth_manager
):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_auth_manager.make_request.return_value = mock_response
    mock_sn_query.side_effect = [
        {
            "success": True,
            "results": [{"sys_id": "sys-1", "name": "Test", "client_script": "before"}],
        },
        {
            "success": True,
            "results": [{"sys_id": "sys-1", "name": "Test", "client_script": "function() {}"}],
        },
    ]

    params = UpdatePortalComponentParams(
        table="sp_widget", sys_id="sys-1", update_data={"client_script": "function() {}"}
    )
    result = update_portal_component(mock_config, mock_auth_manager, params)

    assert result["message"] == "Update successful"
    mock_auth_manager.make_request.assert_called_once()
    mock_invalidate_query_cache.assert_called_once_with(table="sp_widget")
    assert result["validation"]["verified_fields"] == ["client_script"]


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_update_portal_component_matches_fixture_contract(
    mock_sn_query, mock_config, mock_auth_manager
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    after_record = _load_portal_edit_fixture("widget_after.json")
    update_data = _load_portal_edit_fixture("widget_update_data.json")
    expected = _load_portal_edit_fixture("expected_apply.json")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_auth_manager.make_request.return_value = mock_response
    mock_sn_query.side_effect = [
        {"success": True, "results": [before_record]},
        {"success": True, "results": [after_record]},
    ]

    result = update_portal_component(
        mock_config,
        mock_auth_manager,
        UpdatePortalComponentParams(
            table="sp_widget",
            sys_id=before_record["sys_id"],
            update_data=update_data,
        ),
    )

    snapshot = result.pop("snapshot")
    assert result == expected
    assert snapshot["fields"] == ["client_script", "template"]
    assert "portal_component_snapshots" in snapshot["path"]
    assert Path(snapshot["path"]).exists()
    mock_auth_manager.make_request.assert_called_once()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_update_portal_component_noop_matches_fixture_contract(
    mock_sn_query, mock_config, mock_auth_manager
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    update_data = _load_portal_edit_fixture("widget_noop_update_data.json")
    expected = _load_portal_edit_fixture("expected_noop_apply.json")

    mock_sn_query.return_value = {"success": True, "results": [before_record]}

    result = update_portal_component(
        mock_config,
        mock_auth_manager,
        UpdatePortalComponentParams(
            table="sp_widget",
            sys_id=before_record["sys_id"],
            update_data=update_data,
        ),
    )

    assert result == expected
    mock_auth_manager.make_request.assert_not_called()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_update_portal_component_mismatch_matches_fixture_contract(
    mock_sn_query, mock_config, mock_auth_manager
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    after_record = _load_portal_edit_fixture("widget_after_mismatch.json")
    update_data = _load_portal_edit_fixture("widget_update_data.json")
    expected = _load_portal_edit_fixture("expected_mismatch_apply.json")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_auth_manager.make_request.return_value = mock_response
    mock_sn_query.side_effect = [
        {"success": True, "results": [before_record]},
        {"success": True, "results": [after_record]},
    ]

    result = update_portal_component(
        mock_config,
        mock_auth_manager,
        UpdatePortalComponentParams(
            table="sp_widget",
            sys_id=before_record["sys_id"],
            update_data=update_data,
        ),
    )

    snapshot = result.pop("snapshot")
    assert result == expected
    assert snapshot["fields"] == ["client_script", "template"]
    assert "portal_component_snapshots" in snapshot["path"]
    assert Path(snapshot["path"]).exists()
    mock_auth_manager.make_request.assert_called_once()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_create_portal_component_snapshot_writes_file(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    mock_sn_query.return_value = {"success": True, "results": [before_record]}

    result = create_portal_component_snapshot(
        mock_config,
        mock_auth_manager,
        CreatePortalComponentSnapshotParams(
            table="sp_widget",
            sys_id=before_record["sys_id"],
            fields=["client_script", "template"],
            output_dir=str(tmp_path),
        ),
    )

    snapshot_path = Path(result["snapshot"]["path"])
    assert result["success"] is True
    assert snapshot_path.exists()

    payload = json.loads(snapshot_path.read_text())
    assert payload["instance_url"] == mock_config.instance_url
    assert payload["component"] == {
        "table": "sp_widget",
        "sys_id": before_record["sys_id"],
        "name": before_record["name"],
    }
    assert payload["fields"] == ["client_script", "template"]
    assert payload["values"] == {
        "client_script": before_record["client_script"],
        "template": before_record["template"],
    }


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_update_portal_component_includes_preupdate_snapshot(
    mock_sn_query, mock_config, mock_auth_manager
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    after_record = _load_portal_edit_fixture("widget_after.json")
    update_data = _load_portal_edit_fixture("widget_update_data.json")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_auth_manager.make_request.return_value = mock_response
    mock_sn_query.side_effect = [
        {"success": True, "results": [before_record]},
        {"success": True, "results": [after_record]},
    ]

    result = update_portal_component(
        mock_config,
        mock_auth_manager,
        UpdatePortalComponentParams(
            table="sp_widget",
            sys_id=before_record["sys_id"],
            update_data=update_data,
        ),
    )

    snapshot_path = Path(result["snapshot"]["path"])
    assert snapshot_path.exists()
    snapshot_payload = json.loads(snapshot_path.read_text())
    assert snapshot_payload["component"]["sys_id"] == before_record["sys_id"]
    assert snapshot_payload["values"] == {
        "client_script": before_record["client_script"],
        "template": before_record["template"],
    }


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_update_portal_component_from_snapshot_restores_values(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    after_record = _load_portal_edit_fixture("widget_after.json")
    snapshot_path = tmp_path / "widget_snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "snapshot_version": 1,
                "created_at": "2026-04-09T00:00:00Z",
                "instance_url": mock_config.instance_url,
                "component": {
                    "table": "sp_widget",
                    "sys_id": before_record["sys_id"],
                    "name": before_record["name"],
                },
                "fields": ["client_script", "template"],
                "values": {
                    "client_script": before_record["client_script"],
                    "template": before_record["template"],
                },
            }
        )
    )

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_auth_manager.make_request.return_value = mock_response
    mock_sn_query.side_effect = [
        {"success": True, "results": [after_record]},
        {"success": True, "results": [before_record]},
    ]

    result = update_portal_component_from_snapshot(
        mock_config,
        mock_auth_manager,
        UpdatePortalComponentFromSnapshotParams(snapshot_path=str(snapshot_path)),
    )

    assert result["message"] == "Update successful"
    assert result["rollback"]["restored_from_snapshot"] == str(snapshot_path.resolve())
    assert result["validation"]["verified_fields"] == ["client_script", "template"]
    mock_auth_manager.make_request.assert_called_once()


def test_update_portal_component_from_snapshot_rejects_instance_mismatch(
    mock_config, mock_auth_manager, tmp_path
):
    before_record = _load_portal_edit_fixture("widget_before.json")
    snapshot_path = tmp_path / "widget_snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "snapshot_version": 1,
                "created_at": "2026-04-09T00:00:00Z",
                "instance_url": "https://other.service-now.com",
                "component": {
                    "table": "sp_widget",
                    "sys_id": before_record["sys_id"],
                    "name": before_record["name"],
                },
                "fields": ["client_script"],
                "values": {"client_script": before_record["client_script"]},
            }
        )
    )

    with pytest.raises(ValueError, match="Snapshot instance_url does not match"):
        update_portal_component_from_snapshot(
            mock_config,
            mock_auth_manager,
            UpdatePortalComponentFromSnapshotParams(snapshot_path=str(snapshot_path)),
        )


def test_route_portal_component_edit_routes_preview_request():
    result = route_portal_component_edit(
        MagicMock(),
        MagicMock(),
        RoutePortalComponentEditParams(
            instruction="preview the widget client script change before applying",
            table="sp_widget",
            sys_id="widget-benefits-1",
            update_data={"client_script": "function next() { return true; }"},
        ),
    )

    assert result["detected_action"] == "preview"
    assert result["suggested_fields"] == ["client_script"]
    assert result["workflow_rule"].startswith("Always follow 3 stages")
    assert [stage["name"] for stage in result["three_stage_flow"]] == [
        "identify",
        "expand_related",
        "deep_apply",
    ]
    assert result["three_stage_flow"][0]["status"] == "completed"
    assert result["three_stage_flow"][1]["tool"]["tool_name"] == "get_portal_component_code"
    assert result["three_stage_flow"][2]["tool"]["tool_name"] == "preview_portal_component_update"
    assert result["tool_plan"] == {
        "tool_name": "preview_portal_component_update",
        "arguments": {
            "table": "sp_widget",
            "sys_id": "widget-benefits-1",
            "update_data": {"client_script": "function next() { return true; }"},
        },
        "confirmation_required": False,
        "missing_requirements": [],
    }
    assert result["recommended_next_call"] == {
        "tool_name": "preview_portal_component_update",
        "arguments": {
            "table": "sp_widget",
            "sys_id": "widget-benefits-1",
            "update_data": {"client_script": "function next() { return true; }"},
        },
    }


def test_route_portal_component_edit_routes_rollback_request():
    result = route_portal_component_edit(
        MagicMock(),
        MagicMock(),
        RoutePortalComponentEditParams(
            instruction="rollback this widget using the saved snapshot",
            snapshot_path="/tmp/widget_snapshot.json",
        ),
    )

    assert result["detected_action"] == "rollback"
    assert (
        result["three_stage_flow"][2]["tool"]["tool_name"]
        == "update_portal_component_from_snapshot"
    )
    assert result["tool_plan"] == {
        "tool_name": "update_portal_component_from_snapshot",
        "arguments": {"snapshot_path": "/tmp/widget_snapshot.json"},
        "confirmation_required": True,
        "missing_requirements": [],
    }
    assert result["recommended_next_call"] == {
        "tool_name": "update_portal_component_from_snapshot",
        "arguments": {
            "snapshot_path": "/tmp/widget_snapshot.json",
            "confirm": "approve",
        },
    }


def test_route_portal_component_edit_reports_missing_apply_inputs():
    result = route_portal_component_edit(
        MagicMock(),
        MagicMock(),
        RoutePortalComponentEditParams(
            instruction="apply this widget template fix",
            table="sp_widget",
        ),
    )

    assert result["detected_action"] == "apply"
    assert result["suggested_fields"] == ["template"]
    assert result["three_stage_flow"][0]["status"] == "required"
    assert result["three_stage_flow"][1]["status"] == "blocked"
    assert result["three_stage_flow"][2]["status"] == "blocked"
    assert result["tool_plan"]["tool_name"] == "update_portal_component"
    assert result["tool_plan"]["confirmation_required"] is True
    assert result["tool_plan"]["missing_requirements"] == ["sys_id", "update_data"]
    assert result["recommended_next_call"] == {
        "tool_name": "update_portal_component",
        "arguments": {
            "table": "sp_widget",
            "sys_id": "<sys_id>",
            "update_data": "<update_data>",
            "confirm": "approve",
        },
    }


def test_update_portal_component_unsupported_field_matches_fixture_contract(
    mock_config, mock_auth_manager
):
    update_data = _load_portal_edit_fixture("unsupported_update_data.json")
    expected = _load_portal_edit_fixture("expected_unsupported_error.json")

    with pytest.raises(ValueError, match=expected["match"]):
        update_portal_component(
            mock_config,
            mock_auth_manager,
            UpdatePortalComponentParams(
                table="sp_widget",
                sys_id="widget-benefits-1",
                update_data=update_data,
            ),
        )


def test_update_portal_component_rejects_unsupported_field(mock_config, mock_auth_manager):
    with pytest.raises(ValueError, match="Unsupported update fields"):
        update_portal_component(
            mock_config,
            mock_auth_manager,
            UpdatePortalComponentParams(
                table="sp_widget",
                sys_id="sys-1",
                update_data={"name": "Renamed widget"},
            ),
        )


def test_portal_search_defaults_are_conservative():
    params = SearchPortalRegexMatchesParams()

    assert params.source_types == ["widget"]
    assert params.include_linked_script_includes is False
    assert params.include_linked_angular_providers is False
    assert params.max_widgets == 25
    assert params.max_matches == 25
    assert params.page_size == 50


def test_portal_download_defaults_are_conservative():
    params = DownloadPortalSourcesParams()

    assert params.include_linked_script_includes is None
    assert params.include_linked_angular_providers is None
    assert params.max_widgets == 25
    assert params.page_size == 50


def test_portal_component_code_default_chunk_is_conservative():
    params = GetPortalComponentParams(table="sp_widget", sys_id="sys-1")

    assert params.script_max_length == 8000


def test_detect_angular_defaults_are_conservative():
    params = DetectAngularImplicitGlobalsParams()

    assert params.max_providers == 25
    assert params.max_matches == 25
    assert params.page_size == 50


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
@patch("servicenow_mcp.tools.portal_tools.sn_query_page")
def test_download_portal_sources_exports_widget_provider_and_script_include(
    mock_sn_query_page, mock_sn_query_all, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query_all.side_effect = [
        [
            {
                "sys_id": "wid-1",
                "name": "Quotation Widget",
                "id": "quotation_widget",
                "sys_scope": "x_bpm",
                "template": "<div>ok</div>",
                "script": "var si = new x_bpm.QuotationUtil();",
                "client_script": "",
                "link": "function link() {}",
                "css": ".a{}",
                "option_schema": '{"type":"object"}',
                "demo_data": '{"demo":true}',
            }
        ],
        [
            {
                "sp_widget": {"value": "wid-1"},
                "sp_angular_provider": {"value": "prov-1"},
            }
        ],
        [
            {
                "sys_id": "prov-1",
                "name": "quotationService",
            }
        ],
        [
            {
                "sys_id": "si-1",
                "name": "QuotationUtil",
                "api_name": "x_bpm.QuotationUtil",
                "script": "var gr = new GlideRecord('task');",
            }
        ],
    ]

    # sn_query_page returns provider script when queried individually
    mock_sn_query_page.return_value = (
        [{"script": "angular.module('x').factory('quotationService', function(){});"}],
        None,
    )

    result = download_portal_sources(
        mock_config,
        mock_auth_manager,
        DownloadPortalSourcesParams(
            output_dir=str(tmp_path / "x_bpm"),
            scope="x_bpm",
            include_linked_script_includes=True,
            include_linked_angular_providers=True,
        ),
    )

    assert result["success"] is True
    assert result["summary"]["widgets"] == 1
    assert result["summary"]["angular_providers"] == 1
    assert result["summary"]["script_includes"] == 1

    scope_root = tmp_path / "x_bpm"
    assert (tmp_path / "_settings.json").exists()
    assert (tmp_path / "scopes.json").exists()
    assert (tmp_path / "_last_error.json").exists()
    assert (scope_root / "sp_widget" / "quotation_widget" / "script.js").exists()
    assert (scope_root / "sp_widget" / "quotation_widget" / "client_script.js").exists()
    assert (scope_root / "sp_widget" / "quotation_widget" / "_widget.json").exists()
    assert (scope_root / "sp_widget" / "quotation_widget" / "_test_urls.txt").exists()
    assert (scope_root / "sp_angular_provider" / "quotationService.script.js").exists()
    assert (scope_root / "sys_script_include" / "QuotationUtil.script.js").exists()
    assert (scope_root / "sp_widget" / "_map.json").exists()
    assert (scope_root / "sp_angular_provider" / "_map.json").exists()
    assert (scope_root / "sys_script_include" / "_map.json").exists()


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_download_portal_sources_batches_targeted_widget_fetches(
    mock_sn_query_all, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query_all.side_effect = [
        [
            {
                "sys_id": "wid-1",
                "name": "Quotation Widget",
                "id": "quotation_widget",
                "sys_scope": "x_bpm",
                "template": "<div>one</div>",
                "script": "",
                "client_script": "",
                "link": "",
                "css": "",
                "option_schema": "",
                "demo_data": "",
            },
            {
                "sys_id": "wid-2",
                "name": "Approval Widget",
                "id": "approval_widget",
                "sys_scope": "x_bpm",
                "template": "<div>two</div>",
                "script": "",
                "client_script": "",
                "link": "",
                "css": "",
                "option_schema": "",
                "demo_data": "",
            },
        ],
        [],
        [],
    ]

    result = download_portal_sources(
        mock_config,
        mock_auth_manager,
        DownloadPortalSourcesParams(
            output_dir=str(tmp_path / "x_bpm"),
            scope="x_bpm",
            widget_ids=["wid-1", "approval_widget"],
        ),
    )

    assert result["success"] is True
    assert result["summary"]["widgets"] == 2
    assert result["summary"]["angular_providers"] == 0
    assert result["summary"]["script_includes"] == 0
    assert mock_sn_query_all.call_count == 2

    first_call = mock_sn_query_all.call_args_list[0]
    first_query = first_call.kwargs["query"]
    assert "sys_id=wid-1" in first_query
    assert "id=approval_widget" in first_query
    assert "name=approval_widget" in first_query
    assert mock_sn_query_all.call_args_list[0].kwargs["max_records"] >= 20

    scope_root = tmp_path / "x_bpm" / "sp_widget"
    assert (scope_root / "quotation_widget" / "_widget.json").exists()
    assert (scope_root / "approval_widget" / "_widget.json").exists()


@patch("servicenow_mcp.tools.portal_tools.sn_query_page")
@patch("servicenow_mcp.tools.portal_tools._fetch_linked_script_include_rows")
@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_download_portal_sources_targeted_widget_mode_auto_includes_linked_components(
    mock_sn_query_all,
    mock_fetch_linked_script_include_rows,
    mock_sn_query_page,
    mock_config,
    mock_auth_manager,
    tmp_path,
):
    mock_sn_query_all.side_effect = [
        [
            {
                "sys_id": "wid-1",
                "name": "Quotation Widget",
                "id": "quotation_widget",
                "sys_scope": "x_bpm",
                "template": "<div>one</div>",
                "script": "var si = new x_bpm.QuotationUtil();",
                "client_script": "",
                "link": "",
                "css": "",
                "option_schema": "",
                "demo_data": "",
            }
        ],
        [
            {
                "sp_widget": {"value": "wid-1"},
                "sp_angular_provider": {"value": "prov-1"},
            }
        ],
        [
            {
                "sys_id": "prov-1",
                "name": "quotationService",
                "type": "factory",
                "sys_scope": "x_bpm",
            }
        ],
    ]
    mock_sn_query_page.return_value = (
        [{"script": "angular.module('x').factory('quotationService', function(){});"}],
        None,
    )
    mock_fetch_linked_script_include_rows.return_value = [
        {
            "sys_id": "si-1",
            "name": "QuotationUtil",
            "api_name": "x_bpm.QuotationUtil",
            "script": "var gr = new GlideRecord('task');",
        }
    ]

    result = download_portal_sources(
        mock_config,
        mock_auth_manager,
        DownloadPortalSourcesParams(
            output_dir=str(tmp_path / "x_bpm"),
            scope="x_bpm",
            widget_ids=["quotation_widget"],
        ),
    )

    assert result["success"] is True
    assert result["summary"]["widgets"] == 1
    assert result["summary"]["angular_providers"] == 1
    assert result["summary"]["script_includes"] == 1
    assert mock_sn_query_all.call_count == 3

    scope_root = tmp_path / "x_bpm"
    assert (scope_root / "sp_angular_provider" / "quotationService.script.js").exists()
    assert (scope_root / "sys_script_include" / "QuotationUtil.script.js").exists()
    mock_fetch_linked_script_include_rows.assert_called_once()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_download_portal_sources_defaults_to_temp_directory(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query.return_value = {"success": True, "results": []}

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = download_portal_sources(
            mock_config,
            mock_auth_manager,
            DownloadPortalSourcesParams(scope="x_bpm"),
        )

    assert result["success"] is True
    workspace = tmp_path / "temp" / "test"
    assert (workspace / "_settings.json").exists()
    assert (workspace / "_last_error.json").exists()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_download_portal_sources_widget_ids_mode_handles_missing_widget(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = download_portal_sources(
        mock_config,
        mock_auth_manager,
        DownloadPortalSourcesParams(
            output_dir=str(tmp_path / "x_bpm"), scope="x_bpm", widget_ids=["missing"]
        ),
    )

    assert result["success"] is True
    assert result["summary"]["widgets"] == 0
    assert (tmp_path / "x_bpm" / "sp_widget" / "_map.json").exists()


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_search_portal_regex_matches_returns_compact_line_matches(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.side_effect = [
        [
            {
                "sys_id": "wid-1",
                "name": "RFQ Entry Widget",
                "id": "rfq_entry_widget",
                "script": "data.url='/ybpm?id=rfqentry'; var util = new RedirectUtil();",
                "template": "",
                "client_script": "",
                "link": "",
                "css": "",
            }
        ],
        [{"sp_angular_provider": {"value": "prov-1"}}],
        [
            {
                "sys_id": "prov-1",
                "name": "redirectProvider",
                "script": "return '/ybpm?id=rfqentry';",
            }
        ],
        [
            {
                "sys_id": "si-1",
                "name": "RedirectUtil",
                "script": "var path = '/ybpm?id=rfqentry';",
            }
        ],
    ]

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            updated_by="admin@example.com",
            regex=r"/ybpm\?id=rfqentry",
            compact_output=True,
            source_types=["widget", "script_include", "angular_provider"],
            include_linked_script_includes=True,
            include_linked_angular_providers=True,
            max_widgets=20,
            max_matches=20,
        ),
    )

    assert result["success"] is True
    assert result["scan_summary"]["widgets_scanned"] == 1
    assert result["scan_summary"]["linked_angular_providers_scanned"] == 1
    assert result["scan_summary"]["linked_script_includes_scanned"] == 1
    assert result["scan_summary"]["match_count"] == 3
    assert any("Linked component expansion is enabled" in warning for warning in result["warnings"])

    locations = [item["location"] for item in result["matches"]]
    assert "sp_widget/RFQ_Entry_Widget/script" in locations
    assert "sp_angular_provider/redirectProvider/script" in locations
    assert "sys_script_include/RedirectUtil/script" in locations
    assert all(isinstance(item["line"], int) and item["line"] >= 1 for item in result["matches"])


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_search_portal_regex_matches_allows_missing_updated_by(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.return_value = []

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(regex=r"/ybpm\?id=rfqentry", max_widgets=5, max_matches=5),
    )

    assert result["success"] is True
    _args, kwargs = mock_sn_query_all.call_args
    query = kwargs.get("query", "")
    assert "sys_updated_by=" not in query
    assert any("No explicit widget/provider target" in warning for warning in result["warnings"])


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_search_portal_regex_matches_warns_and_clamps_broad_requests(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            regex=r"abc",
            max_widgets=999,
            max_matches=999,
            include_linked_script_includes=True,
            include_linked_angular_providers=True,
        ),
    )

    assert result["success"] is True
    assert result["scan_summary"]["max_widgets"] == 100
    assert result["scan_summary"]["max_matches"] == 100
    assert any("reduced to 100" in warning for warning in result["warnings"])
    assert any("not blocked" in warning for warning in result["warnings"])


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_search_portal_regex_matches_targeted_widget_avoids_broad_target_warning(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(regex=r"abc", widget_ids=["wid-1"]),
    )

    assert result["success"] is True
    assert not any(
        "No explicit widget/provider target" in warning for warning in result["warnings"]
    )


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_search_portal_regex_matches_minimal_output_mode(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.return_value = [
        {
            "sys_id": "wid-1",
            "name": "RFQ Entry Widget",
            "id": "rfq_entry_widget",
            "script": "data.url='/ybpm?id=rfqentry';",
            "template": "",
            "client_script": "",
            "link": "",
            "css": "",
        }
    ]

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            regex=r"/ybpm\?id=rfqentry",
            output_mode="minimal",
            include_linked_script_includes=False,
            include_linked_angular_providers=False,
            max_widgets=5,
            max_matches=5,
        ),
    )

    assert result["success"] is True
    assert result["filters"]["output_mode"] == "minimal"
    assert result["scan_summary"]["output_mode"] == "minimal"
    assert len(result["matches"]) == 1
    assert set(result["matches"][0].keys()) == {"location", "line"}
    assert (
        mock_sn_query_all.call_args.kwargs["fields"]
        == "sys_id,name,id,client_script,css,link,script,template"
    )


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_search_portal_regex_matches_auto_mode_treats_plain_text_as_literal(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.return_value = [
        {
            "sys_id": "wid-1",
            "name": "RFQ Entry Widget",
            "id": "rfq_entry_widget",
            "script": "data.url='/ybpm?id=rfqentry';",
            "template": "",
            "client_script": "",
            "link": "",
            "css": "",
        }
    ]

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            regex="/ybpm?id=rfqentry",
            max_widgets=5,
            max_matches=5,
        ),
    )

    assert result["success"] is True
    assert result["filters"]["match_mode"] == "auto"
    assert result["filters"]["effective_match_mode"] == "literal"
    assert result["filters"]["resolved_pattern"] == r"/ybpm\?id=rfqentry"
    assert len(result["matches"]) == 1


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_search_portal_regex_matches_regex_mode_preserves_pattern(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            regex=r"/ybpm\?id=(rfqentry|rfqdetail)",
            match_mode="regex",
            max_widgets=5,
            max_matches=5,
        ),
    )

    assert result["success"] is True
    assert result["filters"]["effective_match_mode"] == "regex"
    assert result["filters"]["resolved_pattern"] == r"/ybpm\?id=(rfqentry|rfqdetail)"


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_search_portal_regex_matches_classifies_employee_center_routes(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.return_value = [
        {
            "sys_id": "wid-1",
            "name": "Benefits Widget",
            "id": "benefits_widget",
            "script": "data.route='/esc?id=benefits'; data.preview='/$sp.do?id=sp-preview&sys_id=abc123';",
            "template": "",
            "client_script": "",
            "link": "",
            "css": "",
        }
    ]

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(max_widgets=5, max_matches=10),
    )

    assert result["success"] is True
    matches = result["matches"]
    esc_match = next(item for item in matches if item["match"] == "/esc?id=benefits")
    preview_match = next(
        item for item in matches if item["match"] == "/$sp.do?id=sp-preview&sys_id=abc123"
    )
    assert esc_match["route_family"] == "employee_center"
    assert esc_match["route_id"] == "benefits"
    assert preview_match["route_family"] == "service_portal"
    assert preview_match["route_id"] == "sp-preview"


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_trace_portal_route_targets_returns_minimal_llm_friendly_rows(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.side_effect = [
        [
            {
                "sys_id": "wid-1",
                "name": "Budget Widget",
                "id": "budget_widget",
                "template": '<button ng-click="branchToBudget()">Budget</button>',
                "script": "",
                "client_script": (
                    "function branchToBudget(){ return '/sp?id=hopesinitplanbudgetmanhour'; }"
                ),
                "link": "",
            }
        ],
        [{"sp_widget": {"value": "wid-1"}, "sp_angular_provider": {"value": "prov-1"}}],
        [
            {
                "sys_id": "prov-1",
                "name": "budgetProvider",
                "script": (
                    "function resolveBudgetRoute(){ return '/sp?id=hopesinitplanbudgetmanhour'; }"
                ),
            }
        ],
    ]

    result = trace_portal_route_targets(
        mock_config,
        mock_auth_manager,
        TracePortalRouteTargetsParams(
            regex=r"hopesinitplanbudgetmanhour",
            widget_ids=["budget_widget"],
            output_mode="minimal",
        ),
    )

    assert result["success"] is True
    assert result["summary"]["widgets_scanned"] == 1
    assert result["summary"]["providers_with_hits"] == 1
    assert result["summary"]["trace_count"] == 1

    trace = result["traces"][0]
    assert trace["widget"]["name"] == "Budget Widget"
    assert trace["service_names"] == ["budgetProvider"]
    assert "branchToBudget()" in trace["button_handlers"]
    assert "branchToBudget" in trace["button_handlers"]
    assert "branchToBudget" in trace["branch_names"]
    assert "resolveBudgetRoute" in trace["branch_names"]
    assert trace["route_targets"][0]["page_id"] == "hopesinitplanbudgetmanhour"
    assert {"location", "line", "match"} <= set(trace["evidence"][0].keys())
    assert result["filters"]["effective_match_mode"] == "literal"
    assert (
        mock_sn_query_all.call_args_list[0].kwargs["fields"]
        == "sys_id,name,id,client_script,link,script,template"
    )
    assert mock_sn_query_all.call_args_list[2].kwargs["fields"] == "sys_id,name,id,script"


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_trace_portal_route_targets_full_mode_includes_provider_details(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.side_effect = [
        [
            {
                "sys_id": "wid-1",
                "name": "Budget Widget",
                "id": "budget_widget",
                "template": "",
                "script": "function openBudget(){ return '/sp?id=hopesinitplanbudgetmanhour'; }",
                "client_script": "",
                "link": "",
            }
        ],
        [{"sp_widget": {"value": "wid-1"}, "sp_angular_provider": {"value": "prov-1"}}],
        [
            {
                "sys_id": "prov-1",
                "name": "budgetProvider",
                "script": "function resolveBudgetRoute(){ return '/sp?id=hopesinitplanbudgetmanhour'; }",
            }
        ],
    ]

    result = trace_portal_route_targets(
        mock_config,
        mock_auth_manager,
        TracePortalRouteTargetsParams(
            regex=r"hopesinitplanbudgetmanhour",
            widget_ids=["budget_widget"],
            output_mode="full",
        ),
    )

    trace = result["traces"][0]
    assert trace["matched_provider_count"] == 1
    assert trace["matched_widget_field_count"] == 1
    assert trace["linked_providers"] == [{"sys_id": "prov-1", "name": "budgetProvider"}]
    assert trace["provider_matches"][0]["provider"] == {
        "sys_id": "prov-1",
        "name": "budgetProvider",
    }
    assert trace["provider_matches"][0]["context_name"] == "resolveBudgetRoute"


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_trace_portal_route_targets_regex_mode_preserves_route_pattern(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = trace_portal_route_targets(
        mock_config,
        mock_auth_manager,
        TracePortalRouteTargetsParams(
            regex=r"hopes(init|legacy)planbudgetmanhour",
            match_mode="regex",
            max_widgets=5,
            max_traces=5,
        ),
    )

    assert result["success"] is True
    assert result["filters"]["effective_match_mode"] == "regex"
    assert result["filters"]["resolved_pattern"] == r"hopes(init|legacy)planbudgetmanhour"


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_detect_angular_implicit_globals_finds_undeclared_assignment(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.return_value = [
        {
            "sys_id": "prov-1",
            "name": "providerOne",
            "script": "function f(){ test = 'x'; }",
        }
    ]

    result = detect_angular_implicit_globals(
        mock_config,
        mock_auth_manager,
        DetectAngularImplicitGlobalsParams(output_mode="full", max_matches=10),
    )

    assert result["success"] is True
    assert result["scan_summary"]["providers_scanned"] == 1
    assert result["scan_summary"]["finding_count"] == 1
    assert any("No explicit widget/provider target" in warning for warning in result["warnings"])
    finding = result["findings"][0]
    assert finding["variable"] == "test"
    assert finding["issue"] == "implicit_global_assignment"


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_detect_angular_implicit_globals_respects_let_const_declarations(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.return_value = [
        {
            "sys_id": "prov-1",
            "name": "providerOne",
            "script": "function f(){ let test = ''; const done = true; test = 'y'; doneLocal = 1; }",
        }
    ]

    result = detect_angular_implicit_globals(
        mock_config,
        mock_auth_manager,
        DetectAngularImplicitGlobalsParams(output_mode="full", max_matches=10),
    )

    assert result["success"] is True
    assert result["scan_summary"]["finding_count"] == 1
    assert result["findings"][0]["variable"] == "doneLocal"


@patch("servicenow_mcp.tools.portal_tools.sn_query_all")
def test_detect_angular_implicit_globals_minimal_mode_shape(
    mock_sn_query_all, mock_config, mock_auth_manager
):
    mock_sn_query_all.return_value = [
        {
            "sys_id": "prov-1",
            "name": "providerOne",
            "script": "test = 'x';",
        }
    ]

    result = detect_angular_implicit_globals(
        mock_config,
        mock_auth_manager,
        DetectAngularImplicitGlobalsParams(output_mode="minimal", max_matches=10),
    )

    assert result["success"] is True
    assert result["filters"]["output_mode"] == "minimal"
    assert set(result["findings"][0].keys()) == {"location", "line"}
    assert mock_sn_query_all.call_args.kwargs["fields"] == "sys_id,name,id,script"


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_download_portal_sources_warns_and_clamps_broad_requests(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query.side_effect = [
        {"success": True, "results": []},
        {"success": True, "results": []},
    ]

    result = download_portal_sources(
        mock_config,
        mock_auth_manager,
        DownloadPortalSourcesParams(
            output_dir=str(tmp_path / "x_bpm"),
            scope="x_bpm",
            max_widgets=999,
            include_linked_script_includes=True,
            include_linked_angular_providers=True,
        ),
    )

    assert result["success"] is True
    assert any("reduced to 500" in warning for warning in result["warnings"])
    assert any("Linked component expansion is enabled" in warning for warning in result["warnings"])


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_update_portal_component_conflict_blocked(mock_sn_query, mock_config, mock_auth_manager):
    """Write is blocked when remote sys_updated_on is newer than base_updated_on."""
    mock_sn_query.return_value = {
        "success": True,
        "results": [
            {
                "sys_id": "sys-1",
                "name": "My Widget",
                "client_script": "old code",
                "sys_updated_on": "2026-04-29 10:00:00",
            }
        ],
    }
    result = update_portal_component(
        mock_config,
        mock_auth_manager,
        UpdatePortalComponentParams(
            table="sp_widget",
            sys_id="sys-1",
            update_data={"client_script": "new code"},
            base_updated_on="2026-04-28 09:00:00",
        ),
    )
    assert result["error"] == "CONFLICT"
    assert result["remote_updated_on"] == "2026-04-29 10:00:00"
    assert result["base_updated_on"] == "2026-04-28 09:00:00"
    mock_auth_manager.make_request.assert_not_called()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
@patch("servicenow_mcp.tools.portal_tools.invalidate_query_cache")
def test_update_portal_component_conflict_force_overrides(
    mock_invalidate_query_cache, mock_sn_query, mock_config, mock_auth_manager
):
    """force=True writes through even when remote is newer."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_auth_manager.make_request.return_value = mock_response
    mock_sn_query.side_effect = [
        {
            "success": True,
            "results": [
                {
                    "sys_id": "sys-1",
                    "name": "My Widget",
                    "client_script": "old code",
                    "sys_updated_on": "2026-04-29 10:00:00",
                }
            ],
        },
        {
            "success": True,
            "results": [{"sys_id": "sys-1", "name": "My Widget", "client_script": "new code"}],
        },
    ]
    result = update_portal_component(
        mock_config,
        mock_auth_manager,
        UpdatePortalComponentParams(
            table="sp_widget",
            sys_id="sys-1",
            update_data={"client_script": "new code"},
            base_updated_on="2026-04-28 09:00:00",
            force=True,
        ),
    )
    assert result.get("error") != "CONFLICT"
    mock_auth_manager.make_request.assert_called_once()
