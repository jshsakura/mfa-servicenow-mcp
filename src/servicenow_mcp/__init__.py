"""
ServiceNow MCP Server

A Model Context Protocol (MCP) server implementation for ServiceNow,
focusing on the ITSM module.
"""

from servicenow_mcp.server import ServiceNowMCP
from servicenow_mcp.version import __version__

__all__ = ["ServiceNowMCP"]
