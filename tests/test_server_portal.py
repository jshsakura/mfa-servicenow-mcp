import asyncio
from unittest.mock import MagicMock

import pytest

import servicenow_mcp.server as server_module
from servicenow_mcp.server import ServiceNowMCP


def _build_server(monkeypatch: pytest.MonkeyPatch, tmp_path) -> ServiceNowMCP:
    config_path = tmp_path / "tool_packages.yaml"
    config_path.write_text(
        "\n".join(
            [
                "portal_developer:",
                "  - get_widget_bundle",
                "  - update_portal_component",
            ]
        )
    )

    monkeypatch.setenv("TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("MCP_TOOL_PACKAGE", "portal_developer")
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


def test_server_loads_portal_tools(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)
    tools = asyncio.run(server._list_tools_impl())
    names = {tool.name for tool in tools}

    assert "get_widget_bundle" in names
    assert "update_portal_component" in names


def test_server_blocks_update_without_confirmation(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    # Try updating without confirm='approve'
    with pytest.raises(ValueError, match="confirm='approve'"):
        asyncio.run(
            server._call_tool_impl(
                "update_portal_component",
                {"table": "sp_widget", "sys_id": "123", "update_data": {"css": "body {}"}},
            )
        )


def test_server_allows_update_with_confirmation(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    # Mock the tool implementation to avoid real network call
    def mock_impl(_config, _auth, _params):
        return {"message": "Success"}

    server.tool_definitions["update_portal_component"] = (
        mock_impl,
        MagicMock(),
        dict,
        "description",
        "raw_dict",
    )

    # Try updating WITH confirm='approve'
    result = asyncio.run(
        server._call_tool_impl(
            "update_portal_component",
            {
                "table": "sp_widget",
                "sys_id": "123",
                "update_data": {"css": "body {}"},
                "confirm": "approve",
            },
        )
    )

    assert result[0].text == '{\n  "message": "Success"\n}'
