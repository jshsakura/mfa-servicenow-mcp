import json
from unittest.mock import MagicMock

from servicenow_mcp.tools.source_tools import (
    ExtractTableDependenciesParams,
    ExtractWidgetTableDependenciesParams,
    GetMetadataSourceParams,
    SearchServerCodeParams,
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


def test_search_server_code_clamps_limit_and_returns_snippets():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response(
        [
            {
                "sys_id": "si-1",
                "name": "CommitHelper",
                "api_name": "x_app.CommitHelper",
                "description": "Helper for update set commit validation",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-03-25 12:00:00",
                "sys_updated_by": "admin",
                "script": "function validateCommit() { gs.error('commit failed'); }",
            }
        ],
        total_count=1,
    )
    auth_manager.make_request.return_value = response

    result = search_server_code(
        config,
        auth_manager,
        SearchServerCodeParams(query="commit", source_type="script_include", limit=99),
    )

    assert result["success"] is True
    assert result["limit_applied"] == 10
    assert result["count"] == 1
    assert result["results"][0]["source_type"] == "script_include"
    assert "commit" in result["results"][0]["snippet"].lower()
    assert "script" in result["results"][0]["matched_fields"]

    _, kwargs = auth_manager.make_request.call_args
    assert kwargs["params"]["sysparm_limit"] == 5
    assert kwargs["params"]["sysparm_fields"].startswith("sys_id,name")
    assert "scriptLIKEcommit" in kwargs["params"]["sysparm_query"]


def test_search_server_code_searches_multiple_types():
    config = _build_config()
    auth_manager = MagicMock()

    si_response = _response([], total_count=0)

    widget_response = _response(
        [
            {
                "sys_id": "wid-1",
                "name": "Approval Widget",
                "id": "approval_widget",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-03-25 13:00:00",
                "sys_updated_by": "admin",
                "template": "<div>approval status</div>",
                "script": "",
                "client_script": "c.showApproval = true;",
                "css": "",
            }
        ],
        total_count=1,
    )
    auth_manager.make_request.side_effect = [si_response, widget_response]

    result = search_server_code(
        config,
        auth_manager,
        SearchServerCodeParams(query="approval", source_type="all", limit=2),
    )

    assert result["success"] is True
    assert result["count"] == 1
    assert result["results"][0]["source_type"] == "widget"
    assert result["searched_types"] == ["script_include", "widget"]


def test_get_metadata_source_resolves_widget_by_id_and_truncates_fields():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response(
        [
            {
                "sys_id": "wid-1",
                "name": "Approval Widget",
                "id": "approval_widget",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-03-25 13:00:00",
                "sys_updated_by": "admin",
                "template": "x" * 5000,
                "script": "function server() {}",
                "client_script": "function client() {}",
                "css": ".a {}",
            }
        ],
        total_count=1,
    )
    auth_manager.make_request.return_value = response

    result = get_metadata_source(
        config,
        auth_manager,
        GetMetadataSourceParams(
            source_type="widget",
            source_id="approval_widget",
            max_field_length=300,
        ),
    )

    assert result["success"] is True
    assert result["metadata"]["sys_id"] == "wid-1"
    assert result["metadata"]["identifier"] == "approval_widget"
    assert "template" in result["sources"]
    assert "truncated" in result["sources"]["template"].lower()

    _, kwargs = auth_manager.make_request.call_args
    assert "id=approval_widget" in kwargs["params"]["sysparm_query"]


def test_get_metadata_source_returns_error_when_not_found():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response([], total_count=0)
    auth_manager.make_request.return_value = response

    result = get_metadata_source(
        config,
        auth_manager,
        GetMetadataSourceParams(source_type="script_include", source_id="MissingThing"),
    )

    assert result["success"] is False
    assert "not found" in result["message"].lower()


def test_search_server_code_supports_business_rule():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response(
        [
            {
                "sys_id": "br-1",
                "name": "Validate Commit",
                "collection": "sys_update_set",
                "when": "before",
                "active": "true",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-03-25 14:00:00",
                "sys_updated_by": "admin",
                "script": "if (current.state.changes()) gs.error('commit blocked');",
            }
        ],
        total_count=1,
    )
    auth_manager.make_request.return_value = response

    result = search_server_code(
        config,
        auth_manager,
        SearchServerCodeParams(query="commit", source_type="business_rule", limit=3),
    )

    assert result["success"] is True
    assert result["count"] == 1
    assert result["results"][0]["source_type"] == "business_rule"
    assert result["results"][0]["identifier"] == "Validate Commit"


def test_get_metadata_source_supports_ui_script_by_name():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response(
        [
            {
                "sys_id": "ui-1",
                "name": "Portal Helpers",
                "global": "true",
                "ui_type": "all",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-03-25 14:10:00",
                "sys_updated_by": "admin",
                "script": "function portalHelper(){return true;}",
            }
        ],
        total_count=1,
    )
    auth_manager.make_request.return_value = response

    result = get_metadata_source(
        config,
        auth_manager,
        GetMetadataSourceParams(source_type="ui_script", source_id="Portal Helpers"),
    )

    assert result["success"] is True
    assert result["metadata"]["identifier"] == "Portal Helpers"
    assert "script" in result["sources"]


def test_search_server_code_supports_update_xml():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response(
        [
            {
                "sys_id": "upd-1",
                "name": "sys_script_include_123",
                "target_name": "CommitHelper",
                "type": "Script Include",
                "update_set": "US001",
                "sys_updated_on": "2026-03-25 14:20:00",
                "sys_updated_by": "admin",
                "payload": "<xml>commit helper update</xml>",
            }
        ],
        total_count=1,
    )
    auth_manager.make_request.return_value = response

    result = search_server_code(
        config,
        auth_manager,
        SearchServerCodeParams(query="commit", source_type="update_xml", limit=2),
    )

    assert result["success"] is True
    assert result["count"] == 1
    assert result["results"][0]["source_type"] == "update_xml"
    assert "payload" in result["results"][0]["matched_fields"]


def test_search_server_code_reports_non_source_match_fields():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response(
        [
            {
                "sys_id": "upd-2",
                "name": "sys_script_include_456",
                "target_name": "CommitValidator",
                "type": "Script Include",
                "update_set": "US002",
                "sys_updated_on": "2026-03-25 14:30:00",
                "sys_updated_by": "admin",
                "payload": "<xml>other</xml>",
            }
        ],
        total_count=1,
    )
    auth_manager.make_request.return_value = response

    result = search_server_code(
        config,
        auth_manager,
        SearchServerCodeParams(query="validator", source_type="update_xml"),
    )

    assert result["success"] is True
    assert "target_name" in result["results"][0]["matched_fields"]


def test_get_metadata_source_escapes_lookup_value():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response([], total_count=0)
    auth_manager.make_request.return_value = response

    get_metadata_source(
        config,
        auth_manager,
        GetMetadataSourceParams(source_type="script_include", source_id="Thing^ORname=Other"),
    )

    _, kwargs = auth_manager.make_request.call_args
    assert "Thing^^ORname\\=Other" in kwargs["params"]["sysparm_query"]


def test_extract_table_dependencies_scans_widget_br_and_linked_script_include():
    config = _build_config()
    auth_manager = MagicMock()

    si_response = _response(
        [
            {
                "sys_id": "si-1",
                "name": "BpmOrderUtils",
                "api_name": "x_bpm.BpmOrderUtils",
                "script": "var gr = new GlideRecord('sc_req_item');",
            }
        ],
        total_count=1,
    )

    widget_response = _response(
        [
            {
                "sys_id": "wid-1",
                "name": "BPM Summary",
                "id": "bpm_summary",
                "script": "var gr = new GlideRecord('task'); var util = new BpmOrderUtils();",
            }
        ],
        total_count=1,
    )

    br_response = _response(
        [
            {
                "sys_id": "br-1",
                "name": "BPM BR",
                "collection": "incident",
                "script": "var tableName = 'incident'; var gr = new GlideRecord(tableName);",
            }
        ],
        total_count=1,
    )

    db_object_response = _response(
        [
            {"name": "incident", "label": "Incident"},
            {"name": "sc_req_item", "label": "Requested Item"},
            {"name": "task", "label": "Task"},
        ],
        total_count=3,
    )

    auth_manager.make_request.side_effect = [
        si_response,
        widget_response,
        br_response,
        db_object_response,
    ]

    result = extract_table_dependencies(
        config,
        auth_manager,
        ExtractTableDependenciesParams(scope="x_bpm", max_records_per_source=100, page_size=50),
    )

    assert result["success"] is True
    assert result["scan_summary"]["widgets_scanned"] == 1
    assert result["scan_summary"]["business_rules_scanned"] == 1
    assert result["scan_summary"]["linked_script_includes_scanned"] == 1
    assert result["dependency_summary"]["referenced_script_include_count"] == 1

    table_names = {entry["table_name"] for entry in result["tables"]}
    assert {"task", "incident", "sc_req_item"}.issubset(table_names)

    task_entry = next(entry for entry in result["tables"] if entry["table_name"] == "task")
    assert task_entry["table_label"] == "Task"
    assert "widget" in task_entry["source_type_counts"]

    for entry in result["tables"]:
        assert "script" not in entry


def test_extract_table_dependencies_can_skip_linked_script_includes():
    config = _build_config()
    auth_manager = MagicMock()

    widget_response = _response(
        [
            {
                "sys_id": "wid-1",
                "name": "BPM Summary",
                "id": "bpm_summary",
                "script": "var util = new BpmOrderUtils(); var gr = new GlideRecord('task');",
            }
        ],
        total_count=1,
    )

    br_response = _response([], total_count=0)

    db_object_response = _response([{"name": "task", "label": "Task"}], total_count=1)

    auth_manager.make_request.side_effect = [widget_response, br_response, db_object_response]

    result = extract_table_dependencies(
        config,
        auth_manager,
        ExtractTableDependenciesParams(
            include_linked_script_includes=False,
            max_records_per_source=20,
            page_size=20,
        ),
    )

    assert result["success"] is True
    assert result["scan_summary"]["linked_script_includes_scanned"] == 0
    assert result["dependency_summary"]["referenced_script_include_count"] == 0
    assert [entry["table_name"] for entry in result["tables"]] == ["task"]


def test_extract_table_dependencies_handles_br_collection_without_script_and_settablename_and_api_name_ref():
    config = _build_config()
    auth_manager = MagicMock()

    si_response = _response(
        [
            {
                "sys_id": "si-10",
                "name": "OrderSI",
                "api_name": "x_bpm.OrderSI",
                "script": "var gr = new GlideRecord('sc_request');",
            }
        ],
        total_count=1,
    )

    widget_response = _response(
        [
            {
                "sys_id": "wid-10",
                "name": "Order Widget",
                "id": "order_widget",
                "script": "var gr = new GlideRecord('task'); var gr2 = new GlideRecord(); gr2.setTableName('incident'); var si = new x_bpm.OrderSI();",
            }
        ],
        total_count=1,
    )

    br_response = _response(
        [
            {
                "sys_id": "br-10",
                "name": "BR no script",
                "collection": "problem",
                "script": None,
            }
        ],
        total_count=1,
    )

    db_object_response = _response(
        [
            {"name": "incident", "label": "Incident"},
            {"name": "problem", "label": "Problem"},
            {"name": "sc_request", "label": "Request"},
            {"name": "task", "label": "Task"},
        ],
        total_count=4,
    )

    auth_manager.make_request.side_effect = [
        si_response,
        widget_response,
        br_response,
        db_object_response,
    ]

    result = extract_table_dependencies(
        config,
        auth_manager,
        ExtractTableDependenciesParams(scope="x_bpm", max_records_per_source=100, page_size=50),
    )

    assert result["success"] is True
    table_names = {entry["table_name"] for entry in result["tables"]}
    assert {"task", "incident", "problem", "sc_request"}.issubset(table_names)


def test_extract_widget_table_dependencies_returns_widget_and_linked_si_tables():
    config = _build_config()
    auth_manager = MagicMock()

    widget_response = _response(
        [
            {
                "sys_id": "wid-1",
                "name": "Order Widget",
                "id": "order_widget",
                "sys_scope": "x_bpm",
                "script": "var gr = new GlideRecord('task'); var si = new x_bpm.OrderSI();",
            }
        ],
        total_count=1,
    )

    si_lookup_response = _response(
        [
            {
                "sys_id": "si-1",
                "name": "OrderSI",
                "api_name": "x_bpm.OrderSI",
                "script": "var gr = new GlideRecord('sc_req_item');",
            }
        ],
        total_count=1,
    )

    label_response = _response(
        [
            {"name": "task", "label": "Task"},
            {"name": "sc_req_item", "label": "Requested Item"},
        ],
        total_count=2,
    )

    auth_manager.make_request.side_effect = [widget_response, si_lookup_response, label_response]

    result = extract_widget_table_dependencies(
        config,
        auth_manager,
        ExtractWidgetTableDependenciesParams(widget_id="order_widget", scope="x_bpm"),
    )

    assert result["success"] is True
    assert result["widget"]["identifier"] == "order_widget"
    table_names = {entry["table_name"] for entry in result["tables"]}
    assert {"task", "sc_req_item"}.issubset(table_names)
    assert result["scan_summary"]["linked_script_includes_scanned"] == 1


def test_extract_widget_table_dependencies_returns_not_found_for_missing_widget():
    config = _build_config()
    auth_manager = MagicMock()

    widget_response = _response([], total_count=0)
    auth_manager.make_request.return_value = widget_response

    result = extract_widget_table_dependencies(
        config,
        auth_manager,
        ExtractWidgetTableDependenciesParams(widget_id="missing_widget"),
    )

    assert result["success"] is False
    assert "not found" in result["message"].lower()


def test_get_metadata_source_reuses_shared_query_cache_for_identical_lookup():
    config = _build_config()
    auth_manager = MagicMock()

    response = _response(
        [
            {
                "sys_id": "wid-1",
                "name": "Approval Widget",
                "id": "approval_widget",
                "sys_scope": "x_app",
                "sys_updated_on": "2026-03-25 13:00:00",
                "sys_updated_by": "admin",
                "template": "<div></div>",
                "script": "function server() {}",
                "client_script": "function client() {}",
                "css": ".a {}",
            }
        ],
        total_count=1,
    )
    auth_manager.make_request.return_value = response

    params = GetMetadataSourceParams(source_type="widget", source_id="approval_widget")
    first = get_metadata_source(config, auth_manager, params)
    second = get_metadata_source(config, auth_manager, params)

    assert first["success"] is True
    assert second["success"] is True
    assert first["metadata"] == second["metadata"]
    assert auth_manager.make_request.call_count == 1
