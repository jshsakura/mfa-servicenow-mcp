"""Tests for server.py — targeting uncovered lines 77, 145, 148, 160, 179, 348,
355-356, 368-369, 430, 442-444, 484-508, 601, 701, 739-743."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.server import ServiceNowMCP, _compact_schema, _strip_field_filler
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


def _run_async(coro):
    """Run an async coroutine synchronously."""
    result = [None]

    async def _wrapper():
        result[0] = await coro

    asyncio.run(_wrapper())
    return result[0]


# ---------------------------------------------------------------------------
# _compact_schema edge cases (lines 145, 148, 160)
# ---------------------------------------------------------------------------


class TestCompactSchemaExtras:
    def test_drops_empty_required_at_top_level(self):
        """Line 145: empty required arrays at top level should be dropped."""
        schema = {"type": "object", "properties": {}, "required": []}
        result = _compact_schema(schema, _top_level=True)
        assert "required" not in result

    def test_keeps_nonempty_required_at_top_level(self):
        schema = {"type": "object", "properties": {}, "required": ["field"]}
        result = _compact_schema(schema, _top_level=True)
        assert "required" in result

    def test_drops_additional_properties_false(self):
        """Line 148: additionalProperties=false should be dropped."""
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        result = _compact_schema(schema)
        assert "additionalProperties" not in result

    def test_keeps_additional_properties_true(self):
        schema = {"type": "object", "properties": {}, "additionalProperties": True}
        result = _compact_schema(schema)
        assert result["additionalProperties"] is True

    def test_drops_long_string_default(self):
        """Line 160: string defaults longer than 60 chars should be dropped."""
        long_default = "x" * 61
        schema = {
            "type": "object",
            "properties": {"field": {"type": "string", "default": long_default}},
        }
        result = _compact_schema(schema)
        assert "default" not in result["properties"]["field"]

    def test_keeps_short_string_default(self):
        short_default = "x" * 60
        schema = {
            "type": "object",
            "properties": {"field": {"type": "string", "default": short_default}},
        }
        result = _compact_schema(schema)
        assert result["properties"]["field"]["default"] == short_default


# ---------------------------------------------------------------------------
# _strip_field_filler edge case (line 179)
# ---------------------------------------------------------------------------


class TestStripFieldFillerExtras:
    def test_non_dict_schema_returns_as_is(self):
        """Line 179: non-dict field_schema should be returned unchanged."""
        assert _strip_field_filler("some_field", "string_value") == "string_value"
        assert _strip_field_filler("some_field", 42) == 42
        assert _strip_field_filler("some_field", None) is None


# ---------------------------------------------------------------------------
# _load_packaged_package_definitions ValueError (line 77)
# ---------------------------------------------------------------------------


class TestLoadPackagedDefinitions:
    def test_non_dict_config_raises_value_error(self):
        """Line 77: ValueError when yaml returns a list instead of dict."""
        mock_pkg = MagicMock()
        mock_pkg.read_text.return_value = "- item1\n- item2\n"
        mock_files = MagicMock(return_value=MagicMock(joinpath=MagicMock(return_value=mock_pkg)))

        from servicenow_mcp.server import _load_packaged_package_definitions

        _load_packaged_package_definitions.cache_clear()
        with (
            patch("importlib.resources.files", mock_files),
            pytest.raises(ValueError, match="Expected dict"),
        ):
            _load_packaged_package_definitions()


# ---------------------------------------------------------------------------
# _register_tools edge cases (lines 348, 355-356)
# ---------------------------------------------------------------------------


class TestRegisterToolsExtras:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_register_tools_skips_not_enabled(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        """Line 348: tool not in enabled_tool_names is skipped during registration."""
        from pydantic import BaseModel

        class Params(BaseModel):
            x: int = 1

        mock_gtd.return_value = {
            "disabled_tool": (
                lambda c, a, p: None,
                Params,
                dict,
                "desc",
                "raw_dict",
            ),
        }

        # Create a mock server where tool_decorator will track calls
        mock_mcp_server = MagicMock()
        mock_mcp_server.tool.return_value = MagicMock(return_value=lambda f: f)

        config = _make_config()
        server = ServiceNowMCP.__new__(ServiceNowMCP)
        server.config = config
        server.mcp_server = mock_mcp_server
        server.package_definitions = {"standard": ["other_tool"]}
        server.enabled_tool_names = ["other_tool"]
        server.current_package_name = "standard"
        server._tool_list_cache = None
        server._include_skill_hints = False
        server._skill_entries = []
        server._tool_to_skills = {}
        server.tool_definitions = mock_gtd.return_value

        server._register_tools()

        mock_mcp_server.tool.assert_not_called()

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_register_tools_exception_is_caught(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        """Lines 355-356: exception during tool registration is caught gracefully."""
        from pydantic import BaseModel

        class Params(BaseModel):
            x: int = 1

        mock_gtd.return_value = {
            "broken_reg": (
                lambda c, a, p: None,
                Params,
                dict,
                "desc",
                "raw_dict",
            ),
        }

        mock_mcp_server = MagicMock()
        mock_mcp_server.tool.side_effect = Exception("registration failed")

        config = _make_config()
        server = ServiceNowMCP.__new__(ServiceNowMCP)
        server.config = config
        server.mcp_server = mock_mcp_server
        server.package_definitions = {"standard": ["broken_reg"]}
        server.enabled_tool_names = ["broken_reg"]
        server.current_package_name = "standard"
        server._tool_list_cache = None
        server._include_skill_hints = False
        server._skill_entries = []
        server._tool_to_skills = {}
        server.tool_definitions = mock_gtd.return_value

        server._register_tools()

    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_register_resources_exception_is_caught(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        """Lines 368-369: exception during resource registration is caught gracefully."""
        mock_gtd.return_value = {}

        mock_mcp_server = MagicMock()
        mock_mcp_server.resource.side_effect = Exception("resource reg failed")

        config = _make_config()
        server = ServiceNowMCP.__new__(ServiceNowMCP)
        server.config = config
        server.mcp_server = mock_mcp_server
        server.package_definitions = {}
        server.enabled_tool_names = []
        server.current_package_name = "none"
        server._tool_list_cache = None
        server._include_skill_hints = False
        server._skill_entries = []
        server._tool_to_skills = {}
        server.tool_definitions = {}

        server._register_resources()


# ---------------------------------------------------------------------------
# _load_yaml_config extends with None parent (line 430)
# ---------------------------------------------------------------------------


class TestLoadYamlExtendsNone:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_extends_with_none_parent_continues(
        self, mock_btsm, mock_ls, mock_gtd, mock_am, tmp_path
    ):
        """Line 430: _extends key with None value should continue (skip)."""
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        yaml_file = tmp_path / "extends_none.yaml"
        yaml_file.write_text(
            "standard:\n"
            "  - sn_query\n"
            "child_pkg:\n"
            "  _extends: null\n"
            "  _tools:\n"
            "    - sn_health\n"
        )
        server._load_yaml_config(str(yaml_file))
        assert "standard" in server.package_definitions
        assert "child_pkg" in server.package_definitions
        assert isinstance(server.package_definitions["child_pkg"], dict)
        assert "_extends" in server.package_definitions["child_pkg"]


# ---------------------------------------------------------------------------
# _load_yaml_config general exception (lines 442-444)
# ---------------------------------------------------------------------------


class TestLoadYamlGeneralException:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_yaml_read_exception(self, mock_btsm, mock_ls, mock_gtd, mock_am, tmp_path):
        """Lines 442-444: unexpected exception during YAML loading is caught."""
        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)

        yaml_file = tmp_path / "exists.yaml"
        yaml_file.write_text("standard:\n  - sn_query\n")

        with patch("builtins.open", side_effect=PermissionError("no access")):
            server._load_yaml_config(str(yaml_file))

        assert server.package_definitions == {}


# ---------------------------------------------------------------------------
# Multi-package merge (lines 484-508)
# ---------------------------------------------------------------------------


class TestMultiPackageMerge:
    def _make_server_with_packages(self, env_packages, pkg_defs):
        """Create a server with specific package definitions and env var."""
        with (
            patch("servicenow_mcp.server.AuthManager"),
            patch("servicenow_mcp.server.get_tool_definitions") as gtd,
            patch("servicenow_mcp.server.load_skills", return_value=[]),
            patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={}),
            patch.dict("os.environ", {"MCP_TOOL_PACKAGE": env_packages}),
        ):
            gtd.return_value = {}
            config = _make_config()
            server = ServiceNowMCP(config)
            server.package_definitions = pkg_defs
            server._determine_enabled_tools()
            return server

    def test_multi_package_merge(self):
        """Lines 484-508: merging multiple valid packages."""
        server = self._make_server_with_packages(
            "pkg_a,pkg_b",
            {
                "pkg_a": ["tool1", "tool2"],
                "pkg_b": ["tool2", "tool3"],
            },
        )
        assert "pkg_a" in server.current_package_name
        assert "pkg_b" in server.current_package_name
        assert server.enabled_tool_names == ["tool1", "tool2", "tool3"]

    def test_multi_package_all_unknown(self):
        """Lines 497-503: all packages unknown → 'none' with warning."""
        server = self._make_server_with_packages(
            "unknown_a,unknown_b",
            {"standard": ["sn_query"]},
        )
        assert server.current_package_name == "none"
        assert server.enabled_tool_names == []

    def test_multi_package_partial_unknown(self):
        """Lines 489-490: skip unknown package, continue with valid ones."""
        server = self._make_server_with_packages(
            "unknown_pkg,standard",
            {"standard": ["sn_query"]},
        )
        assert server.current_package_name == "standard"
        assert server.enabled_tool_names == ["sn_query"]

    def test_multi_package_deduplication(self):
        """Lines 493-495: duplicate tools across packages are de-duplicated."""
        server = self._make_server_with_packages(
            "pkg_a,pkg_b",
            {
                "pkg_a": ["tool1", "tool2"],
                "pkg_b": ["tool1", "tool3"],
            },
        )
        assert server.enabled_tool_names == ["tool1", "tool2", "tool3"]


# ---------------------------------------------------------------------------
# _list_tools_impl warning (line 601)
# ---------------------------------------------------------------------------


class TestListToolsWarning:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions")
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_warns_no_tools_enabled_non_none_package(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        """Line 601: warning when no tools enabled but package isn't 'none'."""

        mock_gtd.return_value = {}
        config = _make_config()
        server = ServiceNowMCP(config)
        server.enabled_tool_names = []
        server.current_package_name = "standard"
        server._tool_list_cache = None

        async def _check():
            tools = await server._list_tools_impl()
            assert tools[0].name == "list_tool_packages"

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# _call_tool_impl unknown tool in enabled but not in definitions (line 701)
# ---------------------------------------------------------------------------


class TestCallToolUnknownInDefinitions:
    def _make_server(self, enabled, tool_defs, pkg_defs=None):
        with (
            patch("servicenow_mcp.server.AuthManager"),
            patch("servicenow_mcp.server.get_tool_definitions") as gtd,
            patch("servicenow_mcp.server.load_skills", return_value=[]),
            patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={}),
        ):
            gtd.return_value = tool_defs
            config = _make_config()
            server = ServiceNowMCP(config)
            server.enabled_tool_names = enabled
            server.tool_definitions = tool_defs
            server.package_definitions = pkg_defs or {"standard": enabled}
            server.current_package_name = "standard"
            return server

    def test_tool_enabled_but_not_in_definitions(self):
        """Line 701: tool in enabled_tool_names but not in tool_definitions → Unknown."""
        server = self._make_server(
            enabled=["phantom_tool"],
            tool_defs={},
            pkg_defs={"standard": ["phantom_tool"]},
        )

        async def _check():
            with pytest.raises(ValueError, match="Unknown tool"):
                await server._call_tool_impl("phantom_tool", {})

        asyncio.run(_check())


# ---------------------------------------------------------------------------
# _call_tool_impl non-ValidationError exception (lines 739-743)
# ---------------------------------------------------------------------------


class TestCallToolNonValidationException:
    def _make_server(self):
        from pydantic import BaseModel

        class BrokenParams(BaseModel):
            x: int = 1

        class ExplosiveParams(BaseModel):
            x: int = 1

            def __init__(self, **data):
                super().__init__(**data)
                raise TypeError("internal type error")

        def fake_impl(config, auth, params):
            return {"ok": True}

        with (
            patch("servicenow_mcp.server.AuthManager"),
            patch("servicenow_mcp.server.get_tool_definitions") as gtd,
            patch("servicenow_mcp.server.load_skills", return_value=[]),
            patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={}),
        ):
            gtd.return_value = {
                "my_tool": (fake_impl, ExplosiveParams, dict, "desc", "raw_dict"),
            }
            config = _make_config()
            server = ServiceNowMCP(config)
            server.enabled_tool_names = ["my_tool"]
            server.tool_definitions = gtd.return_value
            return server

    def test_non_validation_error_raises_value_error(self):
        """Lines 739-743: non-ValidationError during arg parsing → ValueError."""
        server = self._make_server()

        async def _check():
            with pytest.raises(ValueError, match="Failed to parse arguments"):
                await server._call_tool_impl("my_tool", {"x": 1})

        asyncio.run(_check())
