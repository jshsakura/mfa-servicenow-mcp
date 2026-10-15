"""The server driven through the real mcp SDK, not by calling _*_impl directly.

Every other server test calls the implementation methods, so the wiring in
between (handler registration, the result shapes the SDK expects, and what the
1.x decorators used to do implicitly) is only exercised here. Both protocol
eras are covered: a handshake-era client and a 2026-07-28 client reach the
same handlers through different SDK paths.
"""

from __future__ import annotations

import json
import threading

import anyio
import mcp.types as types
import pytest
from mcp import Client
from mcp.client._memory import InMemoryTransport

from servicenow_mcp.server import ServiceNowMCP
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig
from servicenow_mcp.utils.progress import emit_progress

MODES = ["legacy", "2026-07-28"]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("MCP_TOOL_PACKAGE", "standard")
    monkeypatch.delenv("TOOL_PACKAGE_CONFIG_PATH", raising=False)
    return ServiceNowMCP(
        ServerConfig(
            instance_url="https://test.service-now.com",
            auth=AuthConfig(
                type=AuthType.BASIC,
                basic=BasicAuthConfig(username="alice", password="p"),
            ),
        )
    )


def _run(server, mode, body):
    # Through JSON-RPC framing, as stdio and HTTP deliver it. `Client(server)`
    # alone dispatches a 2026-07-28 call directly with no `_meta` progress
    # token, a path no real transport takes.
    async def main():
        async with Client(InMemoryTransport(server.mcp_server), mode=mode) as client:
            return await body(client)

    return anyio.run(main)


@pytest.mark.parametrize("mode", MODES)
def test_list_tools_reaches_the_client(server, mode):
    async def body(client):
        return await client.list_tools()

    names = {tool.name for tool in _run(server, mode, body).tools}
    assert "sn_query" in names
    assert "list_tool_packages" in names


@pytest.mark.parametrize("mode", MODES)
def test_call_tool_returns_content_as_a_result(server, mode):
    async def body(client):
        return await client.call_tool("list_tool_packages", {})

    result = _run(server, mode, body)
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["current_package"] == "standard"


@pytest.mark.parametrize("mode", MODES)
def test_a_raised_tool_error_is_an_error_result_not_a_protocol_error(server, mode):
    # 1.x's call_tool decorator turned exceptions into is_error results; the
    # model reads the message. 2.x would otherwise send a JSON-RPC error.
    async def body(client):
        return await client.call_tool("no_such_tool", {})

    result = _run(server, mode, body)
    assert result.is_error is True
    assert "no_such_tool" in result.content[0].text


@pytest.mark.parametrize("mode", MODES)
def test_arguments_are_validated_against_the_listed_schema(server, mode):
    async def body(client):
        return await client.call_tool("sn_query", {"table": 123})

    result = _run(server, mode, body)
    assert result.is_error is True
    assert result.content[0].text.startswith("Input validation error:")


@pytest.mark.parametrize("mode", MODES)
def test_skill_resource_reads_through_the_sdk(server, mode):
    # Under mcp 1.x this raised AttributeError inside the SDK's read_resource
    # wrapper for every URI; only direct _read_resource_impl calls worked.
    uri = server._skill_entries[0][0]

    async def body(client):
        listed = await client.list_resources()
        templates = await client.list_resource_templates()
        read = await client.read_resource(uri)
        return listed, templates, read

    listed, templates, read = _run(server, mode, body)
    assert uri in {str(r.uri) for r in listed.resources}
    assert templates.resource_templates[0].uri_template == "skill://{category}/{name}"
    assert read.contents[0].text
    assert read.contents[0].mime_type == "text/markdown"


@pytest.mark.parametrize("mode", MODES)
def test_progress_reaches_a_subscribed_client(server, mode, monkeypatch):
    def impl(cfg, am, params):
        emit_progress(1, 2, "downloading: portal")
        emit_progress(2, 2, "downloading: schema")
        return {"success": True}

    async def call_tool_impl(name, arguments):
        result = await server._invoke_impl("download_app_sources", impl, None, None, None)
        return [types.TextContent(type="text", text=json.dumps(result))]

    monkeypatch.setattr(server, "_call_tool_impl", call_tool_impl)
    seen = []

    async def on_progress(progress, total, message):
        seen.append((progress, total, message))

    async def body(client):
        return await client.call_tool("list_tool_packages", {}, progress_callback=on_progress)

    result = _run(server, mode, body)
    assert result.is_error is False
    assert [m for _, _, m in seen] == ["downloading: portal", "downloading: schema"]


@pytest.mark.parametrize("mode", MODES)
def test_ordinary_tools_still_run_on_the_event_loop_thread(server, mode, monkeypatch):
    # Browser auth (Playwright) must run on the thread that created the loop.
    # The SDK dispatching a handler on another thread would break MFA login
    # while every mocked test stayed green.
    ran_on = []

    def impl(cfg, am, params):
        ran_on.append(threading.get_ident())
        return {"ok": 1}

    async def call_tool_impl(name, arguments):
        loop_thread.append(threading.get_ident())
        result = await server._invoke_impl("sn_query", impl, None, None, None)
        return [types.TextContent(type="text", text=json.dumps(result))]

    loop_thread: list = []
    monkeypatch.setattr(server, "_call_tool_impl", call_tool_impl)

    async def body(client):
        return await client.call_tool("list_tool_packages", {})

    result = _run(server, mode, body)
    assert result.is_error is False
    assert ran_on == loop_thread == [threading.get_ident()]


def test_server_info_reports_this_package_not_the_sdk(server):
    from servicenow_mcp.version import get_version

    assert server.mcp_server.version == get_version()
