import asyncio

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
                "  - get_incident_by_number",
                "  - approve_change",
                "  - create_incident",
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

    assert "create_incident" in names
    assert "get_incident_by_number" in names
    assert "approve_change" in names


def test_list_tools_injects_confirm_field_for_mutating_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    tools = {tool.name: tool for tool in asyncio.run(server._list_tools_impl())}

    create_incident_schema = tools["create_incident"].inputSchema
    confirm_schema = create_incident_schema["properties"]["confirm"]

    assert confirm_schema["enum"] == ["approve"]
    assert confirm_schema["description"] == "Pass 'approve' for writes."
    assert "confirm" in create_incident_schema["required"]
    assert "confirm='approve'" in (tools["create_incident"].description or "")


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

    server.tool_definitions["create_incident"] = (
        should_not_run,
        EmptyParams,
        dict,
        "blocked",
        "raw_dict",
    )
    if "create_incident" not in server.enabled_tool_names:
        server.enabled_tool_names.append("create_incident")

    # Should raise error because confirm='approve' is missing
    with pytest.raises(ValueError, match="confirm='approve'"):
        asyncio.run(server._call_tool_impl("create_incident", {}))

    assert called["value"] is False


def test_call_tool_allows_mutating_tool_with_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    server = _build_server(monkeypatch, tmp_path)

    called = {"value": False}

    def should_run(_config, _auth_manager, _params):
        called["value"] = True
        return {"ok": True}

    server.tool_definitions["create_incident"] = (
        should_run,
        EmptyParams,
        dict,
        "allowed-with-confirmation",
        "raw_dict",
    )
    if "create_incident" not in server.enabled_tool_names:
        server.enabled_tool_names.append("create_incident")

    # Should work with confirm='approve'
    asyncio.run(
        server._call_tool_impl(
            "create_incident",
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
