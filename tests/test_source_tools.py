from unittest.mock import MagicMock

from servicenow_mcp.tools.source_tools import (
    GetMetadataSourceParams,
    SearchServerCodeParams,
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


def test_search_server_code_clamps_limit_and_returns_snippets():
    config = _build_config()
    auth_manager = MagicMock()

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "result": [
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
        ]
    }
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

    si_response = MagicMock()
    si_response.raise_for_status.return_value = None
    si_response.json.return_value = {"result": []}

    widget_response = MagicMock()
    widget_response.raise_for_status.return_value = None
    widget_response.json.return_value = {
        "result": [
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
        ]
    }
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

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "result": [
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
        ]
    }
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

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"result": []}
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

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "result": [
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
        ]
    }
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

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "result": [
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
        ]
    }
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

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "result": [
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
        ]
    }
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

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "result": [
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
        ]
    }
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

    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"result": []}
    auth_manager.make_request.return_value = response

    get_metadata_source(
        config,
        auth_manager,
        GetMetadataSourceParams(source_type="script_include", source_id="Thing^ORname=Other"),
    )

    _, kwargs = auth_manager.make_request.call_args
    assert "Thing^^ORname\\=Other" in kwargs["params"]["sysparm_query"]
