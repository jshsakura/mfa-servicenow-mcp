---
name: schema-discovery
version: 1.0.0
description: Explore ServiceNow tables and fields — find tables by keyword, inspect schemas, and understand data models
author: jshsakura
tags: [admin, schema, table, discovery, data-model]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - sn_discover
    - sn_schema
    - sn_query
    - sn_aggregate
complexity: beginner
estimated_time: 2-5 minutes
---

# Schema Discovery

## Overview

Explore the ServiceNow data model — find tables by name or keyword, inspect field definitions, and understand table relationships.

**When to use:**
- "What tables are related to incidents?"
- "Show me the fields on the change_request table"
- "Find the table for service catalog items"
- "What's the field type for this column?"

## Prerequisites

- **Roles:** Any authenticated user (read-only)
- **MCP Package:** `standard` or higher

## Procedure

### Step 1: Find Tables

```
Tool: sn_discover
Parameters:
  keyword: "incident"
  limit: 20
```

Returns matching table names, labels, parent classes, and scopes.

### Step 2: Inspect Table Schema

```
Tool: sn_schema
Parameters:
  table: "incident"
  limit: 500
```

Returns all fields with:
- Field name and label
- Data type (string, reference, integer, etc.)
- Max length
- Mandatory flag
- Reference target table (for reference fields)

### Step 3: Sample Data

```
Tool: sn_query
Parameters:
  table: "incident"
  fields: "sys_id,number,short_description,state,priority"
  limit: 5
  display_value: true
```

### Step 4: Count Records

```
Tool: sn_aggregate
Parameters:
  table: "incident"
  aggregate: "COUNT"
  query: "active=true"
  group_by: "priority"
```

## Common Table Reference

| What | Table Name |
|------|-----------|
| Incidents | `incident` |
| Changes | `change_request` |
| Problems | `problem` |
| Users | `sys_user` |
| Groups | `sys_user_group` |
| Catalog Items | `sc_cat_item` |
| Knowledge Articles | `kb_knowledge` |
| Portal Widgets | `sp_widget` |
| Script Includes | `sys_script_include` |
| Business Rules | `sys_script` |
| Update Sets | `sys_update_set` |

## Tips

- `sn_discover` searches both table name and label — use simple keywords
- `sn_schema` with `display_value: true` shows human-readable type names
- Reference fields link to other tables — check the `reference` column in schema output
- Use `sn_aggregate` with `group_by` to understand data distribution before querying
