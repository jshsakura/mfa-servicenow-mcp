# ServiceNow MCP - Tool Inventory

This page is the web summary of the current tool surface.

- Registered tools: **151**
- Default package `standard`: **36** read-only tools
- Broadest developer package `full`: **101** tools
- Canonical full row-by-row inventory source in the repo: `docs/TOOL_INVENTORY.md`

## Package Summary

| Package | Tools | Description |
|---------|------:|-------------|
| `none` | 0 | Disabled |
| `standard` | 36 | Read-only safe mode **(default)** |
| `service_desk` | 46 | standard + incident/change writes |
| `portal_developer` | 84 | standard + portal/source/changeset development |
| `platform_developer` | 77 | standard + workflow/flow/script/ITSM writes |
| `agile` | 51 | standard + Epic/Story/Scrum/Project PPM |
| `admin` | 61 | standard + user/knowledge/catalog management |
| `full` | 101 | Combined developer package (excludes Agile PPM and Admin) |

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

To reduce drift, this website page stays compact. When you need the full category-by-category matrix with package membership, use the canonical repository inventory in `docs/TOOL_INVENTORY.md`.
