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


def get_tool_definitions(
    create_kb_category_tool_impl: Callable = None,
    list_kb_categories_tool_impl: Callable = None,
) -> Dict[str, ToolDefinition]:
    """Returns a dictionary containing definitions for all available ServiceNow tools.

    Tools register themselves via the @register_tool decorator when their
    modules are imported. This function triggers that import via discover_tools()
    and returns the populated registry.

    The create_kb_category_tool_impl / list_kb_categories_tool_impl parameters
    are kept for backward compatibility but are no longer needed — the KB
    category tools now register themselves directly.
    """
    return discover_tools()
