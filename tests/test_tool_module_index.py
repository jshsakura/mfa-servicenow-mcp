"""Ensure the committed static tool→module index matches the live AST scan.

If this test fails, someone added/removed/moved a tool without regenerating
the index. Run:

    python scripts/regenerate_tool_module_index.py
"""

from servicenow_mcp.tools import _module_index
from servicenow_mcp.utils.registry import _build_tool_module_index


def test_static_index_matches_ast_scan():
    live = _build_tool_module_index()
    static = _module_index.TOOL_MODULE_INDEX
    assert live == static, (
        "tools/_module_index.py is stale. Regenerate with "
        "`python scripts/regenerate_tool_module_index.py`.\n"
        f"Missing from static: {sorted(set(live) - set(static))}\n"
        f"Stale in static:     {sorted(set(static) - set(live))}"
    )


def test_static_index_non_empty():
    assert _module_index.TOOL_MODULE_INDEX, "Static index is empty — never regenerated?"


def test_every_mapped_module_exists():
    """Defensive: every module referenced by the index must be importable."""
    import importlib

    for _tool_name, mod_name in _module_index.TOOL_MODULE_INDEX.items():
        full = f"servicenow_mcp.tools.{mod_name}"
        importlib.import_module(full)  # raises if module missing
