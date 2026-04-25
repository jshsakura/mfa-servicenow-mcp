# ServiceNow MCP - Tool Inventory

This page is the web summary of the current tool surface.

- Registered tools: **165**
- Default package `standard`: **54** read-only tools
- Broadest packaged developer surface `full`: **124** tools
- Registered but unpackaged tools: **41**
- Canonical full row-by-row inventory source in the repo: `docs/TOOL_INVENTORY.md`

## Package Summary

| Package | Tools | Description |
|---------|------:|-------------|
| `none` | 0 | Disabled |
| `core` | 22 | Minimal read-only essentials |
| `standard` | 54 | Read-only safe mode **(default)** |
| `service_desk` | 59 | standard + incident/change operational writes |
| `portal_developer` | 86 | standard + portal/source/changeset/local-sync development |
| `platform_developer` | 99 | standard + workflow/flow/script/ITSM writes |
| `full` | 124 | Broadest packaged surface with bundled `manage_*` workflows |

## Flow Designer Surface

The consolidated Flow Designer surface is intentionally limited to 5 tools:

| Tool | R/W | Purpose |
|------|-----|---------|
| `list_flow_designers` | R | List flows and subflows |
| `get_flow_designer_detail` | R | Inspect structure, triggers, execution summary, pill tracing, and subflow tree |
| `get_flow_designer_executions` | R | List executions or fetch one execution detail |
| `compare_flows` | R | Compare two flows structurally |
| `update_flow_designer` | W | Update name, description, or active state |

Specialized Flow Designer reads removed from the public surface should now be handled through `sn_query` where appropriate.

## Maintenance Note

To reduce drift, this website page stays compact. When you need the full category-by-category matrix with package membership, use the auto-generated repository inventory in `docs/TOOL_INVENTORY.md`.
