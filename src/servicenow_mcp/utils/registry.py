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
