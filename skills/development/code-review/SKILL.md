---
name: code-review
version: 1.0.0
description: Search and review server-side code across ServiceNow artifact tables for patterns, bugs, and security issues
author: jshsakura
tags: [development, code-review, search, security, audit]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - search_server_code
    - get_metadata_source
    - extract_table_dependencies
    - audit_pending_changes
    - sn_query
complexity: intermediate
estimated_time: 5-15 minutes
---

# Code Review

## Overview

Search server-side code across ServiceNow artifact tables (business rules, script includes, client scripts, UI actions, etc.) for patterns, security issues, and dependencies.

**When to use:**
- "Find all code that references this table"
- "Search for eval() usage across all scripts"
- "What does this business rule do?"
- "Audit pending changes for security risks"

## Prerequisites

- **Roles:** Read access to script tables (`sys_script`, `sys_script_include`, `sys_client_script`, etc.)
- **MCP Package:** `standard` or higher

## Procedure

### Step 1: Search for Code Patterns

```
Tool: search_server_code
Parameters:
  query: "eval("
  tables: ["sys_script", "sys_script_include", "sys_client_script", "sys_ui_action"]
  scope: "x_company_app"
  max_results: 50
```

**Common security patterns to search:**
| Pattern | Risk |
|---------|------|
| `eval(` | Code injection |
| `gs.execute` | Arbitrary script execution |
| `GlideRecord` without ACL check | Data exposure |
| `setWorkflow(false)` | Bypasses business rules |
| `current.update()` | Recursive update risk in business rules |

### Step 2: Read Specific Source

When you find a suspicious match, read the full source.

```
Tool: get_metadata_source
Parameters:
  sys_id: "<record sys_id>"
  table: "sys_script_include"
```

### Step 3: Analyze Dependencies

Find what tables and records a script depends on.

```
Tool: extract_table_dependencies
Parameters:
  sys_id: "<script sys_id>"
  table: "sys_script"
```

This reveals GlideRecord table references, making it clear which tables would break if removed.

### Step 4: Audit Pending Changes

Review uncommitted changes for potential issues.

```
Tool: audit_pending_changes
Parameters:
  scope: "x_company_app"
  include_risk_scan: true
```

The audit checks:
- Uncommitted script changes with risk pattern scanning
- Change inventory grouped by artifact type
- Clone detection (duplicate code across scripts)

## Tips

- Start with `search_server_code` for broad pattern discovery
- Use `extract_table_dependencies` before deleting or refactoring scripts
- Run `audit_pending_changes` before committing update sets to catch issues early
- For portal-specific code review, use the `portal-diagnosis` skill instead
