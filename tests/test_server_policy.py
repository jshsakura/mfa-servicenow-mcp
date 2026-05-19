import asyncio
import json

import mcp.types as types
import pytest
from pydantic import BaseModel

import servicenow_mcp.server as server_module
from servicenow_mcp.server import ServiceNowMCP


class EmptyParams(BaseModel):
    pass


def _build_server(monkeypatch: pytest.MonkeyPatch, tmp_path) -> ServiceNowMCP:
    config_path = tmp_path / "tool_packages.yaml"
    config_path.write_text(
        "\n".join(
            [
                "none: []",
                "approval_query_only:",
                "  - approve_change",
                "  - manage_incident",
                "  - sn_nl",
            ]
        )
    )

    monkeypatch.setenv("TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("MCP_TOOL_PACKAGE", "approval_query_only")
    # Also patch the global constant in server_module
    monkeypatch.setattr(server_module, "TOOL_PACKAGE_CONFIG_PATH", str(config_path))

    return ServiceNowMCP(
        {
            "instance_url": "https://example.service-now.com",
            "auth": {
                "type": "basic",
                "basic": {
                    "username": "admin",
                    "password": "password",
                },
            },
        }
    )


def test_list_tools_shows_enabled_mutating_tools(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    tools = asyncio.run(server._list_tools_impl())
    names = {tool.name for tool in tools}

    assert "manage_incident" in names
    assert "approve_change" in names


def test_list_tools_injects_confirm_field_for_mutating_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    tools = {tool.name: tool for tool in asyncio.run(server._list_tools_impl())}

    manage_incident_schema = tools["manage_incident"].inputSchema
    confirm_schema = manage_incident_schema["properties"]["confirm"]

    assert confirm_schema["enum"] == ["approve"]
    assert confirm_schema["description"] == "Pass 'approve' for writes."
    assert "confirm" in manage_incident_schema["required"]
    assert "confirm='approve'" in (tools["manage_incident"].description or "")


def test_list_tools_injects_confirm_field_for_sn_nl(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    tools = {tool.name: tool for tool in asyncio.run(server._list_tools_impl())}

    sn_nl_schema = tools["sn_nl"].inputSchema
    assert sn_nl_schema["properties"]["confirm"]["enum"] == ["approve"]
    assert "confirm='approve'" in (tools["sn_nl"].description or "")


def test_call_tool_blocks_mutating_tool_without_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    called = {"value": False}

    def should_not_run(_config, _auth_manager, _params):
        called["value"] = True
        return {"ok": True}

    server.tool_definitions["manage_incident"] = (
        should_not_run,
        EmptyParams,
        dict,
        "blocked",
        "raw_dict",
    )
    if "manage_incident" not in server.enabled_tool_names:
        server.enabled_tool_names.append("manage_incident")

    # Should raise error because confirm='approve' is missing
    with pytest.raises(ValueError, match="confirm='approve'"):
        asyncio.run(server._call_tool_impl("manage_incident", {}))

    assert called["value"] is False


def test_call_tool_allows_mutating_tool_with_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    called = {"value": False}

    def should_run(_config, _auth_manager, _params):
        called["value"] = True
        return {"ok": True}

    server.tool_definitions["manage_incident"] = (
        should_run,
        EmptyParams,
        dict,
        "allowed-with-confirmation",
        "raw_dict",
    )
    if "manage_incident" not in server.enabled_tool_names:
        server.enabled_tool_names.append("manage_incident")

    # Should work with confirm='approve'
    asyncio.run(
        server._call_tool_impl(
            "manage_incident",
            {
                "confirm": "approve",
            },
        )
    )

    assert called["value"] is True


def test_call_tool_blocks_sn_nl_execute_true_without_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="confirm='approve'"):
        asyncio.run(server._call_tool_impl("sn_nl", {"text": "create incident", "execute": True}))


def test_call_tool_allows_sn_nl_execute_true_with_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    called = {"value": False}

    def should_run(_config, _auth_manager, _params):
        called["value"] = True
        return {"ok": True}

    # Add dummy sn_nl implementation for testing
    server.tool_definitions["sn_nl"] = (
        should_run,
        EmptyParams,
        dict,
        "sn_nl_with_exec",
        "raw_dict",
    )

    asyncio.run(
        server._call_tool_impl(
            "sn_nl", {"text": "create incident", "execute": True, "confirm": "approve"}
        )
    )
    assert called["value"] is True


def test_call_tool_allows_sn_nl_execute_false_without_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    called = {"value": False}

    def should_run(_config, _auth_manager, _params):
        called["value"] = True
        return {"ok": True}

    server.tool_definitions["sn_nl"] = (
        should_run,
        EmptyParams,
        dict,
        "sn_nl_read_only",
        "raw_dict",
    )

    asyncio.run(server._call_tool_impl("sn_nl", {"text": "list incidents", "execute": False}))

    assert called["value"] is True


def test_call_tool_blocks_approve_tool_without_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="confirm='approve'"):
        asyncio.run(server._call_tool_impl("approve_change", {"change_id": "CHG0010001"}))


def test_list_tools_caches_generated_schemas(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)
    schema_calls = {"count": 0}

    class CountingParams(BaseModel):
        @classmethod
        def model_json_schema(cls, *args, **kwargs):
            schema_calls["count"] += 1
            return {"type": "object", "properties": {}}

    server.current_package_name = "approval_query_only"
    server.enabled_tool_names = ["counted_tool"]
    server.tool_definitions = {
        "counted_tool": (
            lambda _config, _auth_manager, _params: {},
            CountingParams,
            dict,
            "counted",
            "raw_dict",
        )
    }
    server._tool_list_cache = None

    first = asyncio.run(server._list_tools_impl())
    second = asyncio.run(server._list_tools_impl())

    assert any(isinstance(tool, types.Tool) and tool.name == "counted_tool" for tool in first)
    assert any(isinstance(tool, types.Tool) and tool.name == "counted_tool" for tool in second)
    assert schema_calls["count"] == 1


def _build_multi_server(monkeypatch: pytest.MonkeyPatch, tmp_path) -> ServiceNowMCP:
    config_path = tmp_path / "tool_packages.yaml"
    config_path.write_text(
        "\n".join(
            [
                "none: []",
                "standard:",
                "  - sn_query",
                "platform_developer:",
                "  - sn_query",
                "  - update_foo",
            ]
        )
    )
    monkeypatch.setenv("TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SERVICENOW_ACTIVE_INSTANCE", "dev")
    monkeypatch.setenv(
        "SERVICENOW_INSTANCE_CONFIG",
        json.dumps(
            {
                "dev": {
                    "url": "https://dev.service-now.com",
                    "role": "development",
                    "tool_package": "platform_developer",
                    "allow_writes": True,
                },
                "test": {
                    "url": "https://test.service-now.com",
                    "role": "test",
                    "tool_package": "standard",
                    "allow_writes": False,
                },
            }
        ),
    )
    monkeypatch.setattr(server_module, "TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    return ServiceNowMCP(
        {
            "instance_url": "https://dev.service-now.com",
            "auth": {
                "type": "basic",
                "basic": {"username": "admin", "password": "password"},
            },
        }
    )


def test_multi_instance_helpers_are_listed(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_multi_server(monkeypatch, tmp_path)

    tools = asyncio.run(server._list_tools_impl())
    names = {tool.name for tool in tools}

    assert "list_instances" in names
    assert "compare_instances" in names
    assert server.current_package_name == "platform_developer"


def test_list_instances_reports_active_and_hosts(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_multi_server(monkeypatch, tmp_path)

    response = asyncio.run(server._call_tool_impl("list_instances", {}))
    payload = json.loads(response[0].text)

    assert payload["active_instance"] == "dev"
    assert payload["ordinary_tools_route_to"] == "dev"
    assert {item["alias"] for item in payload["instances"]} == {"dev", "test"}
    assert any(item["host"] == "test.service-now.com" for item in payload["instances"])


def test_active_instance_allow_writes_blocks_mutating_tool(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_multi_server(monkeypatch, tmp_path)
    server.active_instance_meta["allow_writes"] = False
    server.tool_definitions["update_foo"] = (
        lambda _config, _auth_manager, _params: {"ok": True},
        EmptyParams,
        dict,
        "test write",
        "raw_dict",
    )
    if "update_foo" not in server.enabled_tool_names:
        server.enabled_tool_names.append("update_foo")

    with pytest.raises(ValueError, match="does not allow write operations"):
        asyncio.run(server._call_tool_impl("update_foo", {"confirm": "approve"}))


def test_compare_instances_reports_changed_and_missing(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_multi_server(monkeypatch, tmp_path)

    def fake_query_page(config, _auth_manager, **_kwargs):
        if "dev" in config.instance_url:
            return (
                [
                    {"api_name": "x_app.A", "script": "return 1;  \n"},
                    {"api_name": "x_app.OnlyDev", "script": "dev"},
                ],
                2,
            )
        return (
            [
                {"api_name": "x_app.A", "script": "return 2;"},
                {"api_name": "x_app.OnlyTest", "script": "test"},
            ],
            2,
        )

    monkeypatch.setattr("servicenow_mcp.tools.sn_api.sn_query_page", fake_query_page)

    result = server._compare_instances_impl(
        {
            "source": "dev",
            "target": "test",
            "table": "sys_script_include",
            "key_field": "api_name",
            "fields": "api_name,script",
        }
    )

    assert result["changed_count"] == 1
    assert result["only_in_source"] == ["x_app.OnlyDev"]
    assert result["only_in_target"] == ["x_app.OnlyTest"]
    assert result["changed"][0]["key"] == "x_app.A"
