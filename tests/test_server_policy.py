import asyncio

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
                "  - list_incidents",
                "  - approve_change",
                "  - create_incident",
                "  - sn_nl",
            ]
        )
    )

    monkeypatch.setenv("TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("MCP_TOOL_PACKAGE", "approval_query_only")
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
    assert "list_incidents" in names
    assert "approve_change" in names


def test_call_tool_blocks_create_tool_before_execution(monkeypatch: pytest.MonkeyPatch, tmp_path):
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

    with pytest.raises(ValueError, match="requires explicit approval"):
        asyncio.run(server._call_tool_impl("create_incident", {}))

    assert called["value"] is False


def test_call_tool_allows_create_tool_with_explicit_approval(
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
        "allowed-with-approval",
        "raw_dict",
    )
    if "create_incident" not in server.enabled_tool_names:
        server.enabled_tool_names.append("create_incident")

    asyncio.run(
        server._call_tool_impl(
            "create_incident",
            {
                "_approved": True,
                "_approval_by": "test-user",
                "_approval_reason": "approved-by-user-request",
            },
        )
    )

    assert called["value"] is True


def test_call_tool_blocks_when_approval_by_missing(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="_approval_by"):
        asyncio.run(
            server._call_tool_impl(
                "create_incident",
                {
                    "_approved": True,
                    "_approval_reason": "approved-by-user-request",
                },
            )
        )


def test_call_tool_blocks_when_approval_reason_missing(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="_approval_reason"):
        asyncio.run(
            server._call_tool_impl(
                "create_incident",
                {
                    "_approved": True,
                    "_approval_by": "test-user",
                },
            )
        )


def test_call_tool_blocks_sn_nl_execute_true(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="requires explicit approval"):
        asyncio.run(server._call_tool_impl("sn_nl", {"text": "create incident", "execute": True}))


def test_call_tool_blocks_sn_nl_execute_without_metadata(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="_approval_by"):
        asyncio.run(
            server._call_tool_impl(
                "sn_nl", {"text": "create incident", "execute": True, "_approved": True}
            )
        )


def test_call_tool_blocks_approve_tool(monkeypatch: pytest.MonkeyPatch, tmp_path):
    server = _build_server(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="requires explicit approval"):
        asyncio.run(server._call_tool_impl("approve_change", {"change_id": "CHG0010001"}))
