"""Decorator-based tool registration system.

Each tool function is decorated with @register_tool(...) which automatically
adds it to a global registry. tool_utils.py then auto-discovers all tool
modules and returns the populated registry — no manual import lists needed.
"""

import importlib
import logging
import pkgutil
from typing import Any, Callable, Dict, Tuple, Type

logger = logging.getLogger(__name__)

# Global registry: tool_name -> (impl_func, ParamsModel, ReturnType, description, serialization)
_TOOL_REGISTRY: Dict[str, Tuple[Callable, Type[Any], Type, str, str]] = {}


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
    import servicenow_mcp.tools as tools_pkg

    for _importer, module_name, _is_pkg in pkgutil.iter_modules(tools_pkg.__path__):
        full_name = f"servicenow_mcp.tools.{module_name}"
        try:
            importlib.import_module(full_name)
        except Exception:
            logger.warning(f"Failed to import tool module: {full_name}", exc_info=True)

    return dict(_TOOL_REGISTRY)


def discover_tools_lazy(
    *,
    enabled_names: set[str] | None = None,
) -> Dict[str, Tuple[Callable, Type[Any], Type, str, str]]:
    """Import tool modules on-demand, loading only those that provide requested tools.

    Strategy:
    1. Import each module one at a time.
    2. After each import, check which NEW tools appeared in the registry.
    3. Stop early once all ``enabled_names`` are found.
    4. Skip modules entirely once we have everything we need.

    Falls back to full ``discover_tools()`` when ``enabled_names`` is None.
    """
    if enabled_names is None:
        return discover_tools()

    import servicenow_mcp.tools as tools_pkg

    remaining = set(enabled_names)
    for _importer, module_name, _is_pkg in pkgutil.iter_modules(tools_pkg.__path__):
        if not remaining:
            break
        full_name = f"servicenow_mcp.tools.{module_name}"
        try:
            importlib.import_module(full_name)
        except Exception:
            logger.warning(f"Failed to import tool module: {full_name}", exc_info=True)
            continue
        # Remove any tools that are now in the registry
        remaining -= set(_TOOL_REGISTRY.keys())

    # Return only the requested tools
    return {k: v for k, v in _TOOL_REGISTRY.items() if k in enabled_names}
