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
    # No description: field name + single-value enum + the tool description's
    # "(confirm='approve')" suffix are self-explanatory (token saving).
    assert "description" not in confirm_schema
    assert "confirm" in manage_incident_schema["required"]
    assert "confirm='approve'" in (tools["manage_incident"].description or "")


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


def test_call_tool_push_confirm_miss_points_to_preview(monkeypatch: pytest.MonkeyPatch, tmp_path):
    # P0-2: a push confirm-miss must hand back the read-only preview step, never a
    # bare dead-end. confirm_publish satisfies G7; the standard confirm is still
    # missing, so the rejection must name diff_local_component — and not run.
    server = _build_server(monkeypatch, tmp_path)

    called = {"value": False}

    def should_not_run(_config, _auth_manager, _params):
        called["value"] = True
        return {"ok": True}

    server.tool_definitions["update_remote_from_local"] = (
        should_not_run,
        EmptyParams,
        dict,
        "blocked",
        "raw_dict",
    )
    if "update_remote_from_local" not in server.enabled_tool_names:
        server.enabled_tool_names.append("update_remote_from_local")

    with pytest.raises(ValueError, match="diff_local_component"):
        asyncio.run(
            server._call_tool_impl("update_remote_from_local", {"confirm_publish": "approve"})
        )

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


def _build_multi_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path, test_allow_writes: bool = False
) -> ServiceNowMCP:
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
    # Tool surface is global now — set it once via MCP_TOOL_PACKAGE.
    monkeypatch.setenv("MCP_TOOL_PACKAGE", "platform_developer")
    monkeypatch.setenv("SERVICENOW_ACTIVE_INSTANCE", "dev")
    monkeypatch.setenv(
        "SERVICENOW_INSTANCE_CONFIG",
        json.dumps(
            {
                "dev": {
                    "url": "https://dev.service-now.com",
                    "role": "development",
                    "allow_writes": True,
                },
                "test": {
                    "url": "https://test.service-now.com",
                    "role": "test",
                    "allow_writes": test_allow_writes,
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
    assert "read_other_instance" in payload
    # Explicit per-instance auth state surfaced (no-network, deterministic).
    for item in payload["instances"]:
        assert item["auth_status"] in {
            "credentials",
            "session_cached",
            "no_session",
            "unknown",
        }


# ---------------------------------------------------------------------------
# instance= routing: read-only calls can target a non-active instance
# ---------------------------------------------------------------------------


def _register_recorder(server, tool_name: str):
    """Register a fake tool that records the config/auth it was dispatched with."""
    seen = {}

    def _impl(config, auth_manager, _params):
        seen["instance_url"] = config.instance_url
        seen["auth_manager"] = auth_manager
        return {"ok": True}

    server.tool_definitions[tool_name] = (_impl, EmptyParams, dict, "desc", "raw_dict")
    if tool_name not in server.enabled_tool_names:
        server.enabled_tool_names.append(tool_name)
    return seen


def test_instance_arg_routes_read_to_named_instance(monkeypatch, tmp_path):
    server = _build_multi_server(monkeypatch, tmp_path)
    seen = _register_recorder(server, "sn_query")

    asyncio.run(server._call_tool_impl("sn_query", {"instance": "test"}))

    assert seen["instance_url"] == "https://test.service-now.com"
    assert seen["auth_manager"] is server.instance_contexts["test"]["auth_manager"]


def test_no_instance_arg_uses_active(monkeypatch, tmp_path):
    server = _build_multi_server(monkeypatch, tmp_path)
    seen = _register_recorder(server, "sn_query")

    asyncio.run(server._call_tool_impl("sn_query", {}))

    assert seen["instance_url"] == "https://dev.service-now.com"
    assert seen["auth_manager"] is server.auth_manager


def test_instance_arg_unknown_alias_rejected(monkeypatch, tmp_path):
    server = _build_multi_server(monkeypatch, tmp_path)
    _register_recorder(server, "sn_query")

    with pytest.raises(ValueError, match="is not configured"):
        asyncio.run(server._call_tool_impl("sn_query", {"instance": "nope"}))


def test_cross_instance_write_without_confirm_instance_rejected(monkeypatch, tmp_path):
    # Active is "dev"; writing with instance="test" but NO confirm_instance is
    # blocked — the strong, target-naming approval is required.
    server = _build_multi_server(monkeypatch, tmp_path, test_allow_writes=True)
    seen = _register_recorder(server, "update_foo")

    with pytest.raises(ValueError, match="confirm_instance"):
        asyncio.run(
            server._call_tool_impl("update_foo", {"instance": "test", "confirm": "approve"})
        )
    assert seen == {}  # never executed


def test_cross_instance_write_to_read_only_target_rejected(monkeypatch, tmp_path):
    # Even with confirm_instance, a read-only (allow_writes=false) target is blocked.
    server = _build_multi_server(monkeypatch, tmp_path, test_allow_writes=False)
    seen = _register_recorder(server, "update_foo")

    with pytest.raises(ValueError, match="read-only"):
        asyncio.run(
            server._call_tool_impl(
                "update_foo",
                {"instance": "test", "confirm_instance": "test", "confirm": "approve"},
            )
        )
    assert seen == {}


def test_cross_instance_write_authorized_routes_to_target(monkeypatch, tmp_path):
    # Active is "dev"; a single write to writable "test" with confirm_instance=test
    # routes to test, then the active instance is restored.
    server = _build_multi_server(monkeypatch, tmp_path, test_allow_writes=True)
    seen = _register_recorder(server, "update_foo")

    result = asyncio.run(
        server._call_tool_impl(
            "update_foo",
            {"instance": "test", "confirm_instance": "test", "confirm": "approve"},
        )
    )
    # Write executed against the TARGET (test), not the active (dev).
    assert seen["auth_manager"] is server.instance_contexts["test"]["auth_manager"]
    assert seen["instance_url"] == "https://test.service-now.com"
    # Echo makes the cross-instance target explicit.
    payload = json.loads(result[0].text)
    assert payload["instance_target"]["alias"] == "test"
    assert payload["instance_target"]["cross_instance"] is True
    # Active instance was restored — NOT left swapped on test.
    assert server.active_instance_alias == "dev"
    assert server.active_instance_meta.get("alias") == "dev"


def test_write_naming_active_instance_is_accepted(monkeypatch, tmp_path):
    # instance="dev" equals the active instance, so the write is NOT a redirect —
    # accept it (no-op) and run against the active config instead of erroring.
    server = _build_multi_server(monkeypatch, tmp_path)
    seen = _register_recorder(server, "update_foo")

    asyncio.run(server._call_tool_impl("update_foo", {"instance": "dev", "confirm": "approve"}))

    assert seen["instance_url"] == "https://dev.service-now.com"
    assert seen["auth_manager"] is server.auth_manager


def test_instance_schema_advertised_on_read_tools_only(monkeypatch, tmp_path):
    server = _build_multi_server(monkeypatch, tmp_path)
    # update_foo is enabled by the package but has no registered definition;
    # register one so it shows up in list_tools for the write-tool assertion.
    _register_recorder(server, "update_foo")

    tools = {t.name: t for t in asyncio.run(server._list_tools_impl())}

    read_props = tools["sn_query"].inputSchema["properties"]
    assert read_props["instance"]["enum"] == ["dev", "test"]

    # Write tool: no instance arg (it only ever runs against the active instance).
    write_props = tools["update_foo"].inputSchema["properties"]
    assert "instance" not in write_props


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

    # Read-only active instance blocks the write, and the message explicitly
    # tells the LLM NOT to edit config/env to bypass (prevents the
    # "edit .mcp.json to flip allow_writes" flailing).
    with pytest.raises(ValueError, match="read-only") as exc_info:
        asyncio.run(server._call_tool_impl("update_foo", {"confirm": "approve"}))
    msg = str(exc_info.value)
    assert "allow_writes" in msg
    assert "Do NOT edit" in msg or "do NOT edit" in msg


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


def _build_browser_default_server(monkeypatch, tmp_path):
    """Active=dev on the global browser default; prod carries its own creds."""
    config_path = tmp_path / "tool_packages.yaml"
    config_path.write_text("none: []\nstandard:\n  - sn_query\n")
    monkeypatch.setenv("TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("MCP_TOOL_PACKAGE", "standard")
    monkeypatch.setenv("SERVICENOW_ACTIVE_INSTANCE", "dev")
    monkeypatch.setenv(
        "SERVICENOW_INSTANCE_CONFIG",
        json.dumps(
            {
                "dev": {"url": "https://dev.service-now.com", "allow_writes": True},
                "test": {"url": "https://test.service-now.com", "allow_writes": True},
                "prod": {
                    "url": "https://prod.service-now.com",
                    "allow_writes": False,
                    "username": "svc_prod",
                    "password": "pw",
                },
            }
        ),
    )
    monkeypatch.setattr(server_module, "TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    return ServiceNowMCP(
        {
            "instance_url": "https://dev.service-now.com",
            "auth": {"type": "browser", "browser": {"headless": True}},
        }
    )


def test_instance_with_creds_opts_out_of_browser_to_basic(monkeypatch, tmp_path):
    from servicenow_mcp.utils.config import AuthType

    server = _build_browser_default_server(monkeypatch, tmp_path)

    # Bare instances keep the global browser (headless) default.
    assert server.instance_contexts["dev"]["config"].auth.type == AuthType.BROWSER
    assert server.instance_contexts["test"]["config"].auth.type == AuthType.BROWSER
    # prod brought its own username+password → basic (no browser), and those
    # exact creds are used, not the global.
    prod_auth = server.instance_contexts["prod"]["config"].auth
    assert prod_auth.type == AuthType.BASIC
    assert prod_auth.basic.username == "svc_prod"
    assert prod_auth.basic.password == "pw"
    # prod's own auth_manager targets prod with those creds.
    assert server.instance_contexts["prod"]["auth_manager"].instance_url == (
        "https://prod.service-now.com"
    )


def test_list_instances_shows_auth_type_and_user_per_profile(monkeypatch, tmp_path):
    server = _build_browser_default_server(monkeypatch, tmp_path)

    out = server._list_instances_impl()
    by_alias = {i["alias"]: i for i in out["instances"]}

    # dev/test: browser SSO, no configured user → labelled 'sso'.
    assert by_alias["dev"]["auth_type"] == "browser"
    assert by_alias["dev"]["user"] == "sso"
    assert by_alias["test"]["auth_type"] == "browser"
    # prod: brought creds → basic, and its exact configured user is shown.
    assert by_alias["prod"]["auth_type"] == "basic"
    assert by_alias["prod"]["user"] == "svc_prod"
    # write permission per profile still surfaced.
    assert by_alias["dev"]["allow_writes"] is True
    assert by_alias["prod"]["allow_writes"] is False
