"""
Tools module for the ServiceNow MCP server.

MCP tool registration is handled by @register_tool decorators.
discover_tools_lazy() auto-imports only the modules needed for the active package.
No eager imports here — they defeat lazy discovery and waste startup time.

For direct Python consumption, import from submodules:
    from servicenow_mcp.tools.incident_tools import get_incident_by_number
"""
