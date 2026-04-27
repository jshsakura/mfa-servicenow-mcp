"""Tests for per-package action allowlists.

Covers the YAML dict-form parser, schema enum narrowing, dispatch reject gate,
and end-to-end behavior across packages (incident readable in standard with
``action=get`` only; service_desk lifts the restriction).
"""

from __future__ import annotations

import os

import pytest

from servicenow_mcp.server import (
    ServiceNowMCP,
    _flatten_package_entries,
    _narrow_action_enum,
    _parse_package_entry,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _server_with_package(pkg: str) -> ServiceNowMCP:
    """Spin up a ServiceNowMCP for a specific package, restoring env after."""
    prev_pkg = os.environ.get("MCP_TOOL_PACKAGE")
    prev_path = os.environ.get("TOOL_PACKAGE_CONFIG_PATH")
    os.environ["MCP_TOOL_PACKAGE"] = pkg
    os.environ.pop("TOOL_PACKAGE_CONFIG_PATH", None)
    try:
        return ServiceNowMCP(_make_config())
    finally:
        if prev_pkg is None:
            os.environ.pop("MCP_TOOL_PACKAGE", None)
        else:
            os.environ["MCP_TOOL_PACKAGE"] = prev_pkg
        if prev_path is not None:
            os.environ["TOOL_PACKAGE_CONFIG_PATH"] = prev_path


# ---------------------------------------------------------------------------
# YAML entry parser
# ---------------------------------------------------------------------------


class TestParseEntry:
    def test_plain_string(self):
        assert _parse_package_entry("foo") == ("foo", None)

    def test_dict_with_actions(self):
        name, allowed = _parse_package_entry({"foo": {"actions": ["a", "b"]}})
        assert name == "foo"
        assert allowed == frozenset({"a", "b"})

    def test_dict_with_empty_actions_means_no_restriction(self):
        # Empty list is treated as "no restriction" — matches caller intent
        # (someone clearing the list to open the tool back up).
        assert _parse_package_entry({"foo": {"actions": []}}) == ("foo", None)

    def test_dict_without_actions_key(self):
        assert _parse_package_entry({"foo": {}}) == ("foo", None)

    @pytest.mark.parametrize(
        "bad",
        [
            42,
            None,
            ["foo"],
            {"foo": "bar"},  # nested value not a dict
            {"foo": {"actions": "get"}},  # actions not a list
            {"foo": {"actions": ["get", 1]}},  # mixed types
            {"foo": {"actions": ["get"]}, "bar": {"actions": []}},  # multi-key
        ],
    )
    def test_malformed_returns_none(self, bad):
        assert _parse_package_entry(bad) is None


class TestFlatten:
    def test_mixed_entries(self):
        entries = ["a", {"b": {"actions": ["get"]}}, "c"]
        names, actions = _flatten_package_entries(entries)
        assert names == ["a", "b", "c"]
        assert actions == {"a": None, "b": frozenset({"get"}), "c": None}

    def test_duplicate_last_wins(self):
        # Same tool listed twice — second entry's restriction wins, name list
        # stays unique.
        entries = [{"foo": {"actions": ["get"]}}, "foo"]
        names, actions = _flatten_package_entries(entries)
        assert names == ["foo"]
        assert actions == {"foo": None}

    def test_skip_malformed(self):
        names, actions = _flatten_package_entries(["a", 42, "b"])
        assert names == ["a", "b"]


# ---------------------------------------------------------------------------
# Schema enum narrowing
# ---------------------------------------------------------------------------


class TestNarrowActionEnum:
    def _schema(self):
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "create", "update"]},
                "sys_id": {"type": "string"},
            },
            "required": ["action"],
        }

    def test_narrows_enum(self):
        narrowed = _narrow_action_enum(self._schema(), frozenset({"get"}))
        assert narrowed["properties"]["action"]["enum"] == ["get"]

    def test_preserves_original_order(self):
        narrowed = _narrow_action_enum(self._schema(), frozenset({"update", "get"}))
        # Preserves enum order from the source — narrowed enum is still in
        # original order, not allowlist order.
        assert narrowed["properties"]["action"]["enum"] == ["get", "update"]

    def test_does_not_mutate_source(self):
        src = self._schema()
        snapshot = src["properties"]["action"]["enum"][:]
        _narrow_action_enum(src, frozenset({"get"}))
        assert src["properties"]["action"]["enum"] == snapshot

    def test_no_op_when_all_allowed(self):
        src = self._schema()
        out = _narrow_action_enum(src, frozenset({"get", "create", "update"}))
        # Returns same ref when nothing changes — quick check
        assert out is src

    def test_no_action_property(self):
        src = {"type": "object", "properties": {"foo": {"type": "string"}}}
        assert _narrow_action_enum(src, frozenset({"get"})) is src


# ---------------------------------------------------------------------------
# Server integration — load packages and dispatch
# ---------------------------------------------------------------------------


class TestServerPackageLoading:
    def test_standard_package_restricts_manage_workflow_to_reads(self):
        s = _server_with_package("standard")
        assert s._active_action_allowlists["manage_workflow"] == frozenset(
            {"list", "get", "list_versions", "get_activities"}
        )

    def test_standard_package_restricts_manage_script_include_to_reads(self):
        s = _server_with_package("standard")
        assert s._active_action_allowlists["manage_script_include"] == frozenset({"list", "get"})

    def test_platform_developer_lifts_workflow_restriction(self):
        # platform_developer extends standard then re-lists manage_workflow as
        # a plain string. The plain entry must override the parent's allowlist
        # so write actions become visible.
        s = _server_with_package("platform_developer")
        assert s._active_action_allowlists.get("manage_workflow") is None

    def test_platform_developer_keeps_catalog_restriction(self):
        # platform_developer doesn't re-list manage_catalog → standard's
        # restriction carries through.
        s = _server_with_package("platform_developer")
        assert s._active_action_allowlists.get("manage_catalog") == frozenset(
            {"list_items", "get_item", "list_categories", "list_item_variables"}
        )

    def test_full_package_has_no_restrictions(self):
        s = _server_with_package("full")
        restricted = {k: v for k, v in s._active_action_allowlists.items() if v is not None}
        assert restricted == {}

    def test_tool_counts_unchanged_by_allowlist(self):
        # Allowlists narrow visible actions but don't add or remove tools.
        # These counts must match the headline numbers in TOOL_INVENTORY.md.
        expected = {"core": 15, "standard": 45, "service_desk": 46, "full": 66}
        for pkg, count in expected.items():
            s = _server_with_package(pkg)
            assert (
                len(s.enabled_tool_names) == count
            ), f"{pkg}: {len(s.enabled_tool_names)} != {count}"


class TestSchemaEmittedToLlm:
    def test_standard_emits_narrowed_action_enum_for_manage_workflow(self):
        s = _server_with_package("standard")
        import asyncio

        tools = asyncio.run(s._list_tools_impl())
        workflow = next(t for t in tools if t.name == "manage_workflow")
        action_enum = workflow.inputSchema["properties"]["action"]["enum"]
        # Only the read actions should reach the LLM.
        assert set(action_enum) == {"list", "get", "list_versions", "get_activities"}

    def test_full_emits_full_action_enum(self):
        s = _server_with_package("full")
        import asyncio

        tools = asyncio.run(s._list_tools_impl())
        workflow = next(t for t in tools if t.name == "manage_workflow")
        # Full surface — write actions visible.
        action_enum = workflow.inputSchema["properties"]["action"]["enum"]
        assert "list" in action_enum
        # Workflow has writes (e.g. create/update/publish/etc.) — full must
        # expose more than just the four reads.
        assert len(action_enum) > 4


class TestDispatchRejectGate:
    def test_disallowed_action_raises(self):
        # In standard, manage_workflow is restricted to reads. Calling
        # action='create' must be rejected before any tool execution.
        s = _server_with_package("standard")
        import asyncio

        with pytest.raises(ValueError, match="not available"):
            asyncio.run(
                s._call_tool_impl(
                    "manage_workflow",
                    {"action": "create", "name": "x"},
                )
            )

    def test_allowed_action_passes_gate(self):
        # An allowlisted action must reach the dispatch path. We don't care
        # whether the underlying tool call succeeds — only that the gate
        # doesn't reject it.
        s = _server_with_package("standard")
        import asyncio

        impl_def = s.tool_definitions["manage_workflow"]

        def fake_impl(config, auth, params):
            return {"success": True, "result": []}

        s.tool_definitions["manage_workflow"] = (
            fake_impl,
            impl_def[1],
            impl_def[2],
            impl_def[3],
            impl_def[4],
        )
        try:
            # 'list' is allowlisted in standard.
            result = asyncio.run(s._call_tool_impl("manage_workflow", {"action": "list"}))
            assert result, "expected non-empty TextContent list"
        finally:
            s.tool_definitions["manage_workflow"] = impl_def

    def test_unrestricted_tool_dispatch_unaffected(self):
        s = _server_with_package("standard")
        assert "sn_query" in s.enabled_tool_names
        assert s._active_action_allowlists.get("sn_query") is None
