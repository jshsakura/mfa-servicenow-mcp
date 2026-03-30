"""
ServiceNow MCP Server

A Model Context Protocol (MCP) server implementation for ServiceNow,
focusing on the ITSM module.
"""

__version__ = "1.2.2"

from servicenow_mcp.server import ServiceNowMCP

__all__ = ["ServiceNowMCP"]
