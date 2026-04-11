---
name: developer-activity
version: 1.0.0
description: Track developer activity — recent changes, uncommitted work, daily summary, and repo status across ServiceNow artifacts
author: jshsakura
tags: [admin, developer, activity, tracking, changes]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - get_developer_changes
    - get_developer_daily_summary
    - get_uncommitted_changes
    - get_repo_change_report
    - get_repo_recent_commits
    - get_repo_working_tree_status
complexity: beginner
estimated_time: 2-5 minutes
---

# Developer Activity

## Overview

Track what developers have been working on — recent configuration changes, uncommitted work in update sets, daily summaries, and repository status.

**When to use:**
- "What did I change today?"
- "Show uncommitted changes in this scope"
- "Who modified this script include last?"
- "Give me a daily development summary"

## Prerequisites

- **Roles:** Read access to `sys_update_xml`, `sys_update_set`
- **MCP Package:** `standard` or higher (read); `portal_developer` for detailed tracking

## Procedure

### Recent Changes by Developer

```
Tool: get_developer_changes
Parameters:
  username: "admin"
  days: 7
  limit: 50
```

### Daily Summary

```
Tool: get_developer_daily_summary
Parameters:
  username: "admin"
  date: "2026-04-11"
```

### Uncommitted Changes

```
Tool: get_uncommitted_changes
Parameters:
  scope: "x_company_app"
```

### Repository Status

```
Tool: get_repo_working_tree_status
Parameters: {}
```

```
Tool: get_repo_recent_commits
Parameters:
  limit: 10
```

```
Tool: get_repo_change_report
Parameters:
  days: 7
```

## Tips

- Use `get_developer_daily_summary` for standup reports
- `get_uncommitted_changes` is useful before committing update sets — make sure nothing is missed
- Combine with `changeset-workflow` skill: check uncommitted changes → create changeset → commit
