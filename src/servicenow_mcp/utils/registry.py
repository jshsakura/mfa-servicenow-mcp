"""Decorator-based tool registration system.

Each tool function is decorated with @register_tool(...) which automatically
adds it to a global registry. tool_utils.py then auto-discovers all tool
modules and returns the populated registry — no manual import lists needed.
"""

import ast
import importlib
import logging
import os
import pkgutil
from typing import Any, Callable, Dict, Tuple, Type

logger = logging.getLogger(__name__)

# Global registry: tool_name -> (impl_func, ParamsModel, ReturnType, description, serialization)
_TOOL_REGISTRY: Dict[str, Tuple[Callable, Type[Any], Type, str, str]] = {}
_TOOLS_DISCOVERED = False

# Lazy: tool_name -> module_name (built via AST scan, no module import required).
_TOOL_MODULE_INDEX: Dict[str, str] | None = None


def register_tool(
    name: str,
    *,
    params: Type[Any],
    description: str,
    serialization: str = "raw_dict",
    return_type: Type = dict,
) -> Callable:
    """Decorator that registers a tool function in the global registry.

    Usage::

        @register_tool(
            "create_incident",
            params=CreateIncidentParams,
            description="Create a new incident in ServiceNow",
            serialization="str",
        )
        def create_incident(config, auth_manager, params):
            ...
    """

    def decorator(func: Callable) -> Callable:
        if name in _TOOL_REGISTRY:
            logger.warning(f"Tool '{name}' registered more than once — overwriting.")
        _TOOL_REGISTRY[name] = (func, params, return_type, description, serialization)
        return func

    return decorator


def discover_tools() -> Dict[str, Tuple[Callable, Type[Any], Type, str, str]]:
    """Import all modules under servicenow_mcp.tools to trigger @register_tool decorators.

    Returns the populated registry dict.
    """
    global _TOOLS_DISCOVERED

    if _TOOLS_DISCOVERED:
        return dict(_TOOL_REGISTRY)

    import servicenow_mcp.tools as tools_pkg

    for _importer, module_name, _is_pkg in pkgutil.iter_modules(tools_pkg.__path__):
        full_name = f"servicenow_mcp.tools.{module_name}"
        try:
            importlib.import_module(full_name)
        except Exception:
            logger.warning(f"Failed to import tool module: {full_name}", exc_info=True)

    _TOOLS_DISCOVERED = True
    return dict(_TOOL_REGISTRY)


def _extract_register_tool_name(dec: ast.Call) -> str | None:
    """Return the tool name from a @register_tool(...) decorator Call, or None.

    Handles both positional (``@register_tool("name", ...)``) and keyword
    (``@register_tool(name="name", ...)``) forms.
    """
    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
        return dec.args[0].value
    for kw in dec.keywords:
        if (
            kw.arg == "name"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    return None


def _build_tool_module_index() -> Dict[str, str]:
    """Scan tool source files via AST for @register_tool decorators.

    Builds a {tool_name: module_name} map without importing any tool module.
    AST (not regex) is used for correctness: regex would match decorator-like
    strings inside comments, docstrings, and string literals — producing
    phantom entries that collide with real tools.

    Returns {} when tool sources aren't on disk (e.g. zipped wheel) — callers
    should fall back to full discovery.
    """
    import servicenow_mcp.tools as tools_pkg

    idx: Dict[str, str] = {}
    if not tools_pkg.__path__:
        return idx
    pkg_path = tools_pkg.__path__[0]
    try:
        entries = sorted(os.listdir(pkg_path))
    except OSError:
        return idx
    for fname in entries:
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        mod_name = fname[:-3]
        full_path = os.path.join(pkg_path, fname)
        try:
            with open(full_path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=full_path)
        except (OSError, SyntaxError):
            logger.warning(f"AST parse failed for {full_path}", exc_info=True)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                fn = dec.func
                fn_id = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if fn_id != "register_tool":
                    continue
                tool_name = _extract_register_tool_name(dec)
                if tool_name is None:
                    continue
                if tool_name in idx and idx[tool_name] != mod_name:
                    logger.warning(
                        f"Tool '{tool_name}' registered in both "
                        f"'{idx[tool_name]}' and '{mod_name}' — using {mod_name}."
                    )
                idx[tool_name] = mod_name
    return idx


def _load_static_tool_module_index() -> Dict[str, str]:
    """Load the pre-generated tool→module map from tools/_module_index.py.

    This file is committed to the repo and regenerated via the
    ``regenerate_tool_module_index`` utility (tests verify it stays in sync).
    Returns {} when the file is missing — callers fall back to live AST scan.
    """
    try:
        from servicenow_mcp.tools import _module_index
    except ImportError:
        return {}
    data = getattr(_module_index, "TOOL_MODULE_INDEX", None)
    if isinstance(data, dict):
        return dict(data)
    return {}


def _get_tool_module_index() -> Dict[str, str]:
    """Return the cached tool→module map.

    Fast path: load a pre-generated static map (no AST cost).
    Fallback: AST-scan source files once (correctness; ~225ms). The result is
    memoized for the process lifetime either way.
    """
    global _TOOL_MODULE_INDEX
    if _TOOL_MODULE_INDEX is None:
        idx = _load_static_tool_module_index()
        _TOOL_MODULE_INDEX = idx if idx else _build_tool_module_index()
    return _TOOL_MODULE_INDEX


def discover_tools_lazy(
    *,
    enabled_names: set[str] | None = None,
) -> Dict[str, Tuple[Callable, Type[Any], Type, str, str]]:
    """Import only the tool modules that provide the requested tools.

    Uses an AST-built ``tool_name → module_name`` index to resolve the minimum
    set of modules up-front, then imports them in one pass. This gives real
    startup savings even when ``enabled_names`` spans the alphabet (previously
    pkgutil.iter_modules forced imports up to the last-needed module).

    Falls back to full ``discover_tools()`` when ``enabled_names`` is None or
    the AST index is empty (e.g. source files unavailable in a zipped wheel).
    """
    if enabled_names is None:
        return discover_tools()

    idx = _get_tool_module_index()
    if not idx:
        return discover_tools()

    # Resolve the minimal module set. Unknown tools (not in any .py source)
    # fall through silently — the server-layer handles reporting them.
    needed_modules = {idx[name] for name in enabled_names if name in idx}
    for mod_name in sorted(needed_modules):
        full_name = f"servicenow_mcp.tools.{mod_name}"
        try:
            importlib.import_module(full_name)
        except Exception:
            logger.warning(f"Failed to import tool module: {full_name}", exc_info=True)
            continue

    return {k: v for k, v in _TOOL_REGISTRY.items() if k in enabled_names}
