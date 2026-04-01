"""Tool definitions registry for the ServiceNow MCP server.

Tools are auto-discovered via the @register_tool decorator in each tool module.
Adding a new tool only requires:
  1. Decorating the function with @register_tool(...)
  2. Adding the tool name to config/tool_packages.yaml
"""

from typing import Any, Callable, Dict, Tuple, Type

from servicenow_mcp.utils.registry import discover_tools

# Type aliases kept for backward compatibility
ParamsModel = Type[Any]
ToolDefinition = Tuple[
    Callable,  # Implementation function
    ParamsModel,  # Pydantic model for parameters
    Type,  # Return type annotation
    str,  # Description
    str,  # Serialization method
]


def get_tool_definitions() -> Dict[str, ToolDefinition]:
    """Returns all registered ServiceNow tool definitions.

    Tools register themselves via @register_tool when their modules are imported.
    This function triggers that import via discover_tools() and returns the registry.
    """
    return discover_tools()
