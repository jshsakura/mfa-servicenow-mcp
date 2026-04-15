"""Tests for servicenow_mcp.utils.registry module."""

import logging
from unittest.mock import patch

from pydantic import BaseModel

from servicenow_mcp.utils.registry import (
    _TOOL_REGISTRY,
    discover_tools,
    discover_tools_lazy,
    register_tool,
)


class _DummyParams(BaseModel):
    x: int = 1


def test_register_tool_duplicate_warns(caplog):
    """Registering the same tool name twice logs a warning."""
    name = "__test_duplicate_tool__"
    # Clean up in case of prior test pollution
    _TOOL_REGISTRY.pop(name, None)
    try:

        @register_tool(name, params=_DummyParams, description="first")
        def first_fn():
            pass

        with caplog.at_level(logging.WARNING):

            @register_tool(name, params=_DummyParams, description="second")
            def second_fn():
                pass

        assert any("overwriting" in r.message.lower() for r in caplog.records)
        # Second registration overwrites
        assert _TOOL_REGISTRY[name][3] == "second"
    finally:
        _TOOL_REGISTRY.pop(name, None)


def test_discover_tools_lazy_with_none_delegates():
    """discover_tools_lazy(enabled_names=None) delegates to discover_tools."""
    with patch("servicenow_mcp.utils.registry.discover_tools") as mock_dt:
        mock_dt.return_value = {"tool1": ("fn", None, dict, "desc", "raw_dict")}
        result = discover_tools_lazy(enabled_names=None)
        mock_dt.assert_called_once()
        assert "tool1" in result


def test_discover_tools_lazy_import_error(caplog):
    """discover_tools_lazy handles import errors in tool modules gracefully."""

    # Create a fake module iterator that will fail on import
    fake_modules = [
        (None, "__test_bad_module__", False),
    ]
    with (
        patch("pkgutil.iter_modules", return_value=fake_modules),
        patch("importlib.import_module", side_effect=ImportError("no such module")),
        caplog.at_level(logging.WARNING),
    ):
        discover_tools_lazy(enabled_names={"nonexistent_tool"})
    assert any("Failed to import" in r.message for r in caplog.records)


def test_discover_tools_import_error(caplog):
    """discover_tools handles import errors gracefully."""
    import servicenow_mcp.utils.registry as reg

    # Temporarily reset discovered flag
    orig = reg._TOOLS_DISCOVERED
    reg._TOOLS_DISCOVERED = False
    try:
        fake_modules = [(None, "__test_bad__", False)]
        with (
            patch("pkgutil.iter_modules", return_value=fake_modules),
            patch("importlib.import_module", side_effect=RuntimeError("boom")),
            caplog.at_level(logging.WARNING),
        ):
            discover_tools()
        assert any("Failed to import" in r.message for r in caplog.records)
    finally:
        reg._TOOLS_DISCOVERED = orig
