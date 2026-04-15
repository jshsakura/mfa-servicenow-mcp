"""Tests for server.py — initialization, tool registration, serialization edge cases."""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.server import (
    CONFIRM_FIELD,
    CONFIRM_VALUE,
    ServiceNowMCP,
    _compact_json,
    _get_tool_schema,
    serialize_tool_output,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


# ---------------------------------------------------------------------------
# serialize_tool_output
# ---------------------------------------------------------------------------


class TestSerializeToolOutput:
    def test_dict_input(self):
        result = serialize_tool_output({"key": "value", "n": 1}, "test")
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_string_compact_json_passthrough(self):
        compact = '{"a":1}'
        assert serialize_tool_output(compact, "test") == compact

    def test_string_with_whitespace_recompacted(self):
        spaced = '{ "a" : 1 }'
        result = serialize_tool_output(spaced, "test")
        assert " : " not in result

    def test_string_with_newlines_recompacted(self):
        nl = '{\n"a": 1\n}'
        result = serialize_tool_output(nl, "test")
        assert "\n" not in result

    def test_non_json_string_passthrough(self):
        plain = "hello world"
        assert serialize_tool_output(plain, "test") == plain

    def test_model_dump_json(self):
        obj = MagicMock()
        obj.model_dump_json.return_value = '{"x":1}'
        del obj.model_dump  # remove model_dump so hasattr check for model_dump_json fires first
        result = serialize_tool_output(obj, "test")
        assert result == '{"x":1}'

    def test_model_dump_json_type_error_fallback(self):
        obj = MagicMock()
        obj.model_dump_json.side_effect = TypeError("no")
        obj.model_dump.return_value = {"x": 1}
        result = serialize_tool_output(obj, "test")
        parsed = json.loads(result)
        assert parsed["x"] == 1

    def test_model_dump_fallback(self):
        obj = MagicMock(spec=[])
        obj.model_dump = MagicMock(return_value={"y": 2})
        # no model_dump_json attribute
        result = serialize_tool_output(obj, "test")
        parsed = json.loads(result)
        assert parsed["y"] == 2

    def test_fallback_to_str(self):
        result = serialize_tool_output(12345, "test")
        assert result == "12345"

    def test_serialization_exception(self):
        obj = MagicMock()
        obj.model_dump_json.side_effect = TypeError("fail")
        obj.model_dump.side_effect = Exception("double fail")
        result = serialize_tool_output(obj, "test")
        parsed = json.loads(result)
        assert "error" in parsed

    def test_recompact_invalid_json_string(self):
        # Looks like JSON (starts with {) but has whitespace and is invalid for re-parse
        bad = "{ invalid json : }"
        result = serialize_tool_output(bad, "test")
        assert result == bad  # falls back to returning as-is


# ---------------------------------------------------------------------------
# _compact_json
# ---------------------------------------------------------------------------


class TestCompactJson:
    def test_produces_compact_output(self):
        result = _compact_json({"a": 1, "b": [2, 3]})
        assert "\n" not in result


# ---------------------------------------------------------------------------
# _get_tool_schema caching
# ---------------------------------------------------------------------------


class TestGetToolSchema:
    def test_caches_schema(self):
        from pydantic import BaseModel, Field

        class TestParams(BaseModel):
            x: int = Field(default=1)

        schema1 = _get_tool_schema(TestParams)
        schema2 = _get_tool_schema(TestParams)
        assert schema1 is schema2  # same object = cached


# ---------------------------------------------------------------------------
# ServiceNowMCP static methods
# ---------------------------------------------------------------------------


class TestServiceNowMCPStatic:
    def test_is_blocked_mutating_tool(self):
        assert ServiceNowMCP._is_blocked_mutating_tool("create_incident") is True
        assert ServiceNowMCP._is_blocked_mutating_tool("delete_record") is True
        assert ServiceNowMCP._is_blocked_mutating_tool("sn_batch") is True
        assert ServiceNowMCP._is_blocked_mutating_tool("sn_query") is False

    def test_tool_requires_confirmation(self):
        assert ServiceNowMCP._tool_requires_confirmation("update_record") is True
        assert ServiceNowMCP._tool_requires_confirmation("sn_nl") is True
        assert ServiceNowMCP._tool_requires_confirmation("sn_query") is False

    def test_inject_confirmation_schema(self):
        schema = {
            "properties": {"table": {"type": "string"}},
            "required": ["table"],
        }
        result = ServiceNowMCP._inject_confirmation_schema(schema)
        assert CONFIRM_FIELD in result["properties"]
        assert CONFIRM_FIELD in result["required"]
        # Original not mutated
        assert CONFIRM_FIELD not in schema["properties"]


# ---------------------------------------------------------------------------
# ServiceNowMCP initialization
# ---------------------------------------------------------------------------


class TestServiceNowMCPInit:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_init_with_dict_config(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        config_dict = {
            "instance_url": "https://test.service-now.com",
            "auth": {
                "type": "basic",
                "basic": {"username": "admin", "password": "password"},
            },
        }
        server = ServiceNowMCP(config_dict)
        assert server.config.instance_url == "https://test.service-now.com"

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_init_with_server_config(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        assert server.config is config

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_start_returns_mcp_server(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        result = server.start()
        assert result is server.mcp_server

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_list_tool_packages_impl(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        result = server._list_tool_packages_impl()
        assert "current_package" in result
        assert "available_packages" in result


# ---------------------------------------------------------------------------
# Async handlers
# ---------------------------------------------------------------------------


class TestAsyncHandlers:
    def _run(self, coro):
        """Run an async coroutine synchronously using anyio."""
        import anyio

        result = [None]

        async def _wrapper():
            result[0] = await coro

        anyio.from_thread.run_sync(lambda: None)
        import asyncio

        asyncio.run(_wrapper())
        return result[0]

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_list_tools_caches(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        async def _check():
            tools1 = await server._list_tools_impl()
            tools2 = await server._list_tools_impl()
            assert len(tools1) == len(tools2)

        asyncio.run(_check())

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_call_unknown_tool_raises(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        async def _check():
            with pytest.raises(ValueError, match="Unknown tool"):
                await server._call_tool_impl("nonexistent_tool", {})

        asyncio.run(_check())

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_list_resource_templates_empty_skills(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        async def _check():
            templates = await server._list_resource_templates_impl()
            assert templates == []

        asyncio.run(_check())

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_read_resource_not_found(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        async def _check():
            with pytest.raises(ValueError, match="Resource not found"):
                await server._read_resource_impl("skill://nonexistent/resource")

        asyncio.run(_check())

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch(
        "servicenow_mcp.server.load_skills",
        return_value=[
            ("skill://cat/test", "test", "desc", "cat", ["tool1"], "# Content"),
        ],
    )
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_list_resources(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        async def _check():
            resources = await server._list_resources_impl()
            assert len(resources) == 1

        asyncio.run(_check())

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch(
        "servicenow_mcp.server.load_skills",
        return_value=[
            ("skill://cat/test", "test", "desc", "cat", ["tool1"], "# Content"),
        ],
    )
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_read_resource_found(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        async def _check():
            result = await server._read_resource_impl("skill://cat/test")
            assert len(result) == 1
            assert result[0].text == "# Content"

        asyncio.run(_check())

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch(
        "servicenow_mcp.server.load_skills",
        return_value=[
            ("skill://cat/test", "test", "desc", "cat", ["tool1"], "# Content"),
        ],
    )
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_list_resource_templates_with_skills(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        async def _check():
            templates = await server._list_resource_templates_impl()
            assert len(templates) == 1

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# _load_yaml_config / _load_package_config edge cases
# ---------------------------------------------------------------------------


class TestLoadConfig:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_load_yaml_config_missing_file(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        server._load_yaml_config("/nonexistent/path.yaml")
        assert server.package_definitions == {}

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    @patch.dict("os.environ", {"MCP_TOOL_PACKAGE": "nonexistent_pkg"})
    def test_determine_enabled_tools_unknown_package(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        # Should fallback to 'none'
        assert server.current_package_name == "none"
        assert server.enabled_tool_names == []


# ---------------------------------------------------------------------------
# _augment_tool_description
# ---------------------------------------------------------------------------


class TestAugmentDescription:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch(
        "servicenow_mcp.server.build_tool_to_skills_map",
        return_value={
            "create_incident": ["skill://manage/create-incident"],
        },
    )
    def test_mutating_tool_gets_confirm_notice(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        desc = server._augment_tool_description("create_incident", "Create an incident")
        assert "confirm" in desc.lower()
        assert "skill://manage/create-incident" in desc

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch(
        "servicenow_mcp.server.build_tool_to_skills_map",
        return_value={
            "sn_query": ["skill://a/1", "skill://a/2", "skill://a/3"],
        },
    )
    def test_generic_tool_no_skill_hint(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        desc = server._augment_tool_description("sn_query", "Query table")
        # 3+ skills means no hint appended
        assert "skill://" not in desc


# ---------------------------------------------------------------------------
# _call_tool_impl paths
# ---------------------------------------------------------------------------


class TestCallToolImpl:
    def _make_server(self, tool_defs=None, enabled=None, package="standard", pkg_defs=None):
        """Helper to create server with mocked internals."""
        with (
            patch("servicenow_mcp.server.AuthManager"),
            patch("servicenow_mcp.server.get_tool_definitions") as gtd,
            patch("servicenow_mcp.server.load_skills", return_value=[]),
            patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={}),
        ):
            gtd.return_value = tool_defs or {}
            config = _make_config()
            server = ServiceNowMCP(config)
            if tool_defs:
                server.tool_definitions = tool_defs
            if enabled is not None:
                server.enabled_tool_names = enabled
            if pkg_defs is not None:
                server.package_definitions = pkg_defs
            server.current_package_name = package
            return server

    def test_call_list_tool_packages(self):
        import asyncio

        server = self._make_server(package="standard")

        async def _check():
            result = await server._call_tool_impl("list_tool_packages", {})
            assert len(result) == 1
            assert "current_package" in result[0].text

        asyncio.run(_check())

    def test_call_list_tool_packages_none_package(self):
        import asyncio

        server = self._make_server(package="none")

        async def _check():
            with pytest.raises(ValueError, match="not available"):
                await server._call_tool_impl("list_tool_packages", {})

        asyncio.run(_check())

    def test_call_disabled_tool_available_in_other_package(self):
        import asyncio

        from pydantic import BaseModel

        class FakeParams(BaseModel):
            x: int = 1

        def fake_impl(config, auth, params):
            return {"ok": True}

        server = self._make_server(
            tool_defs={"my_tool": (fake_impl, FakeParams, dict, "desc", "raw_dict")},
            enabled=[],
            package="standard",
            pkg_defs={"full": ["my_tool"], "standard": []},
        )

        async def _check():
            with pytest.raises(ValueError, match="not available in the current package"):
                await server._call_tool_impl("my_tool", {})

        asyncio.run(_check())

    def test_call_disabled_tool_not_in_any_package(self):
        import asyncio

        from pydantic import BaseModel

        class FakeParams(BaseModel):
            x: int = 1

        def fake_impl(config, auth, params):
            return {"ok": True}

        server = self._make_server(
            tool_defs={"my_tool": (fake_impl, FakeParams, dict, "desc", "raw_dict")},
            enabled=[],
            package="standard",
            pkg_defs={"standard": []},
        )

        async def _check():
            with pytest.raises(ValueError, match="not included in any"):
                await server._call_tool_impl("my_tool", {})

        asyncio.run(_check())

    def test_call_mutating_tool_without_confirmation(self):
        import asyncio

        from pydantic import BaseModel

        class FakeParams(BaseModel):
            x: int = 1

        def fake_impl(config, auth, params):
            return {"ok": True}

        server = self._make_server(
            tool_defs={"create_item": (fake_impl, FakeParams, dict, "desc", "raw_dict")},
            enabled=["create_item"],
        )

        async def _check():
            with pytest.raises(ValueError, match="modify or delete"):
                await server._call_tool_impl("create_item", {"x": 1})

        asyncio.run(_check())

    def test_call_mutating_tool_with_confirmation(self):
        import asyncio

        from pydantic import BaseModel

        class FakeParams(BaseModel):
            x: int = 1

        def fake_impl(config, auth, params):
            return {"result": "created"}

        server = self._make_server(
            tool_defs={"create_item": (fake_impl, FakeParams, dict, "desc", "raw_dict")},
            enabled=["create_item"],
        )

        async def _check():
            result = await server._call_tool_impl(
                "create_item", {"x": 1, CONFIRM_FIELD: CONFIRM_VALUE}
            )
            assert len(result) == 1
            assert "created" in result[0].text

        asyncio.run(_check())

    def test_call_tool_execution_error(self):
        import asyncio

        from pydantic import BaseModel

        class FakeParams(BaseModel):
            x: int = 1

        def fake_impl(config, auth, params):
            raise RuntimeError("something broke")

        server = self._make_server(
            tool_defs={"my_tool": (fake_impl, FakeParams, dict, "desc", "raw_dict")},
            enabled=["my_tool"],
        )

        async def _check():
            result = await server._call_tool_impl("my_tool", {"x": 1})
            assert "something broke" in result[0].text

        asyncio.run(_check())

    def test_call_tool_auth_error(self):
        import asyncio

        from pydantic import BaseModel

        class FakeParams(BaseModel):
            x: int = 1

        def fake_impl(config, auth, params):
            raise RuntimeError("browser session expired")

        server = self._make_server(
            tool_defs={"my_tool": (fake_impl, FakeParams, dict, "desc", "raw_dict")},
            enabled=["my_tool"],
        )

        async def _check():
            result = await server._call_tool_impl("my_tool", {"x": 1})
            assert "auth_session_expired" in result[0].text

        asyncio.run(_check())

    def test_call_tool_invalid_arguments(self):
        import asyncio

        from pydantic import BaseModel, Field

        class StrictParams(BaseModel):
            required_field: str = Field(...)

        def fake_impl(config, auth, params):
            return {"ok": True}

        server = self._make_server(
            tool_defs={"my_tool": (fake_impl, StrictParams, dict, "desc", "raw_dict")},
            enabled=["my_tool"],
        )

        async def _check():
            with pytest.raises(ValueError, match="Invalid arguments"):
                await server._call_tool_impl("my_tool", {})

        asyncio.run(_check())

    def test_call_tool_success(self):
        import asyncio

        from pydantic import BaseModel

        class FakeParams(BaseModel):
            x: int = 1

        def fake_impl(config, auth, params):
            return {"result": "success"}

        server = self._make_server(
            tool_defs={"my_tool": (fake_impl, FakeParams, dict, "desc", "raw_dict")},
            enabled=["my_tool"],
        )

        async def _check():
            result = await server._call_tool_impl("my_tool", {"x": 1})
            assert len(result) == 1
            assert "success" in result[0].text

        asyncio.run(_check())

    def test_call_sn_nl_with_execute_requires_confirmation(self):
        import asyncio

        from pydantic import BaseModel

        class FakeNLParams(BaseModel):
            text: str = "test"
            execute: bool = False

        def fake_impl(config, auth, params):
            return {"ok": True}

        server = self._make_server(
            tool_defs={"sn_nl": (fake_impl, FakeNLParams, dict, "desc", "raw_dict")},
            enabled=["sn_nl"],
        )

        async def _check():
            with pytest.raises(ValueError, match="modify or delete"):
                await server._call_tool_impl("sn_nl", {"text": "test", "execute": True})

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# _list_tools_impl with actual tool definitions
# ---------------------------------------------------------------------------


class TestListToolsWithDefinitions:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_list_tools_with_enabled_tools(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        from pydantic import BaseModel

        class FakeParams(BaseModel):
            x: int = 1

        mock_gtd.return_value = {
            "my_tool": (lambda c, a, p: None, FakeParams, dict, "A tool", "raw_dict"),
        }
        config = _make_config()
        server = ServiceNowMCP(config)
        server.enabled_tool_names = ["my_tool"]
        server.current_package_name = "standard"
        server._tool_list_cache = None

        async def _check():
            tools = await server._list_tools_impl()
            names = [t.name for t in tools]
            assert "list_tool_packages" in names
            assert "my_tool" in names

        asyncio.run(_check())

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_list_tools_schema_error(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import asyncio

        broken = MagicMock()
        broken.model_json_schema.side_effect = Exception("schema fail")

        mock_gtd.return_value = {
            "broken_tool": (lambda c, a, p: None, broken, dict, "Broken", "raw_dict"),
        }
        config = _make_config()
        server = ServiceNowMCP(config)
        server.enabled_tool_names = ["broken_tool"]
        server.current_package_name = "standard"
        server._tool_list_cache = None

        from servicenow_mcp.server import _TOOL_SCHEMA_CACHE

        _TOOL_SCHEMA_CACHE.pop(broken, None)

        async def _check():
            tools = await server._list_tools_impl()
            names = [t.name for t in tools]
            assert "broken_tool" not in names

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# _load_yaml_config edge cases
# ---------------------------------------------------------------------------


class TestLoadYamlConfigEdgeCases:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_invalid_yaml_format(self, mock_btsm, mock_ls, mock_gtd, mock_am, tmp_path):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("- item1\n- item2\n")
        server._load_yaml_config(str(yaml_file))
        assert server.package_definitions == {}

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_valid_yaml(self, mock_btsm, mock_ls, mock_gtd, mock_am, tmp_path):
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        yaml_file = tmp_path / "good.yaml"
        yaml_file.write_text("standard:\n  - sn_query\n  - sn_health\n")
        server._load_yaml_config(str(yaml_file))
        assert "standard" in server.package_definitions

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    @patch.dict("os.environ", {"TOOL_PACKAGE_CONFIG_PATH": "/tmp/test_config_srv.yaml"})
    def test_load_package_config_from_env(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        import os

        mock_gtd.return_value = {}
        config_path = "/tmp/test_config_srv.yaml"
        with open(config_path, "w") as f:
            f.write("standard:\n  - sn_query\n")
        try:
            config = _make_config()
            server = ServiceNowMCP(config)
            assert "standard" in server.package_definitions
        finally:
            os.unlink(config_path)

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    @patch(
        "servicenow_mcp.server._load_packaged_package_definitions",
        side_effect=Exception("not found"),
    )
    def test_load_package_config_fallback(self, mock_lpd, mock_btsm, mock_ls, mock_gtd, mock_am):
        mock_gtd.return_value = {}
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("TOOL_PACKAGE_CONFIG_PATH", None)
            config = _make_config()
            ServiceNowMCP(config)
