"""Tool definitions registry for the ServiceNow MCP server.

Tools are auto-discovered via the @register_tool decorator in each tool module.
Adding a new tool only requires:
  1. Decorating the function with @register_tool(...)
  2. Adding the tool name to config/tool_packages.yaml
"""

from typing import Any, Callable, Dict, Tuple, Type

from servicenow_mcp.utils.registry import discover_tools, discover_tools_lazy

# Type aliases kept for backward compatibility
ParamsModel = Type[Any]
ToolDefinition = Tuple[
    Callable,  # Implementation function
    ParamsModel,  # Pydantic model for parameters
    Type,  # Return type annotation
    str,  # Description
    str,  # Serialization method
]


def get_tool_definitions(
    *, enabled_names: set[str] | None = None
) -> Dict[str, ToolDefinition]:
    """Returns registered ServiceNow tool definitions.

    When *enabled_names* is provided, uses lazy discovery to import only the
    modules that provide the requested tools — skipping unused modules for
    faster startup.  Falls back to full discovery when ``enabled_names`` is None.
    """
    if enabled_names is not None:
        return discover_tools_lazy(enabled_names=enabled_names)
    return discover_tools()
