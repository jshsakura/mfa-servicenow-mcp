---
name: health-check
version: 1.0.0
description: Verify ServiceNow instance connectivity, authentication status, and basic API health
author: jshsakura
tags: [admin, health, connectivity, auth, diagnostic]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - sn_health
    - sn_query
    - sn_aggregate
complexity: beginner
estimated_time: 1-2 minutes
---

# Health Check

## Overview

Verify that the MCP server can reach your ServiceNow instance, authentication is working, and the API responds correctly. First thing to run when setting up or troubleshooting.

**When to use:**
- "Is the connection working?"
- "Check ServiceNow status"
- "Why aren't my tools returning data?"
- First-time setup verification

## Prerequisites

- **Roles:** Any authenticated user
- **MCP Package:** `standard` or higher

## Procedure

### Step 1: API Connectivity

```
Tool: sn_health
Parameters:
  timeout: 15
```

**Interpreting results:**
| `ok` | `status_code` | Meaning |
|------|--------------|---------|
| `true` | 200 | Fully connected and authenticated |
| `true` | 403 | Browser session valid but probe path blocked by ACL (normal for browser auth) |
| `false` | 401/302 | Authentication failed — session expired or credentials wrong |
| `false` | - | Network error — check instance URL |

For browser auth: if `ok: true` with status 403, that's expected. The browser session is authenticated but the default probe path may not be accessible.

### Step 2: Data Access Test

Verify you can actually read data:

```
Tool: sn_query
Parameters:
  table: "sys_user"
  query: "user_name=admin"
  fields: "sys_id,user_name,name"
  limit: 1
```

If this returns results, read access is confirmed.

### Step 3: Quick Instance Stats

```
Tool: sn_aggregate
Parameters:
  table: "incident"
  aggregate: "COUNT"
  query: "active=true"
```

This confirms the instance has data and aggregation APIs work.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Connection timeout | Wrong instance URL | Check `--instance-url` starts with `https://` |
| 401 Unauthorized | Expired credentials | Re-run with `--auth-type browser` to re-authenticate |
| 403 on everything | Missing roles | Ask admin to grant `itil` or appropriate role |
| Browser won't open | Chromium not installed | Run `uvx playwright install chromium` |
| Empty results | ACL restrictions | Query a table you have access to (e.g., `sys_user`) |
