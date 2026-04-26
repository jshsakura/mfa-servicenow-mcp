"""Domain service layer for ServiceNow MCP tools.

Service modules contain reusable API logic decoupled from MCP tool registration
and Pydantic Params binding. Each ``manage_X`` dispatcher and any surviving
read/list wrappers in ``servicenow_mcp.tools.<domain>`` call into the matching
``servicenow_mcp.services.<domain>`` module.

Phase 4.0 of the consolidation plan extracts services from the legacy wrapper
functions; subsequent phases (4.5, 4.7) move further read/list logic in here.
"""
