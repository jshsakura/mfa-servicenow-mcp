---
name: dependency-analysis
version: 1.0.0
description: Map dependencies between tables, widgets, providers, and script includes to understand impact before changes
author: jshsakura
tags: [development, dependency, impact-analysis, refactoring]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - extract_table_dependencies
    - extract_widget_table_dependencies
    - get_provider_dependency_map
    - search_server_code
    - search_portal_regex_matches
complexity: intermediate
estimated_time: 5-10 minutes
---

# Dependency Analysis

## Overview

Map the dependency graph between ServiceNow artifacts — which widgets depend on which tables, which script includes reference which records, and which providers are shared across widgets. Essential before refactoring or deprecating anything.

**When to use:**
- "What would break if I change this table?"
- "Which widgets use this script include?"
- "Map all dependencies of this widget"
- "Is it safe to delete this provider?"

## Prerequisites

- **Roles:** Read access to script and portal tables
- **MCP Package:** `standard` or higher

## Procedure

### Table Dependencies (Server Scripts)

Find which tables a script references via GlideRecord.

```
Tool: extract_table_dependencies
Parameters:
  sys_id: "<script sys_id>"
  table: "sys_script_include"
```

### Widget Table Dependencies

Find which tables a widget's server script queries.

```
Tool: extract_widget_table_dependencies
Parameters:
  widget_id: "<widget sys_id or id>"
```

### Provider-Widget Map

See which providers are linked to which widgets.

```
Tool: get_provider_dependency_map
Parameters:
  scope: "x_company_app"
```

Result shows:
- Each provider with a list of widgets that use it
- Orphaned providers (linked to 0 widgets)
- Hot providers (linked to many widgets — high blast radius)

### Reverse Search: Who Uses This?

Find all code that references a specific name.

```
Tool: search_server_code
Parameters:
  query: "MyHelperUtil"
  tables: ["sys_script", "sys_script_include", "sys_client_script"]
```

For portal code:
```
Tool: search_portal_regex_matches
Parameters:
  regex: "MyHelperUtil"
  source_types: ["widget", "angular_provider"]
  include_widget_fields: ["script", "client_script"]
```

## Output: Dependency Matrix

| Artifact | Depends On | Depended By |
|----------|-----------|-------------|
| Widget A | Table: incident, Provider: myHelper | Page: home |
| Provider: myHelper | - | Widget A, Widget B |
| SI: MyUtil | Table: sys_user | Widget A (server script) |

## Tips

- Always run dependency analysis before deleting or renaming anything
- Providers linked to 0 widgets are safe to delete
- Providers linked to 5+ widgets need extra care — changes affect many pages
- Combine `extract_table_dependencies` + `search_server_code` for complete picture
