---
name: widget-analysis
version: 1.0.0
description: Analyze a portal widget's full dependency tree — source code, Angular providers, script includes, and route targets
author: jshsakura
tags: [portal, widget, analysis, dependency, provider]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - get_widget_bundle
    - get_portal_component_code
    - trace_portal_route_targets
    - search_portal_regex_matches
    - analyze_widget_performance
    - sn_query
  complexity: beginner
  estimated_time: 3-5 minutes
---

# Widget Analysis

## Overview

Analyze a Service Portal widget's complete structure — source code, linked Angular providers, referenced script includes, and route targets. Produces an actionable dependency map.

**When to use:**
- "What does this widget do?"
- "Show me all dependencies of this widget"
- "Which providers does this widget use?"
- "What routes does this widget link to?"

## Prerequisites

- **Roles:** Read access to `sp_widget`, `sp_angular_provider`, `sys_script_include`
- **MCP Package:** `standard` or higher

## Procedure

### Step 1: Get Widget Bundle

Fetch the widget source code and linked providers in one call.

```
Tool: get_widget_bundle
Parameters:
  widget_id: "<widget sys_id or id>"
  include_providers: true
  include_script: true
  include_client_script: true
  include_template: true
  include_css: true
```

Review the result:
- `widget.script` — server-side controller
- `widget.client_script` — client-side AngularJS controller
- `widget.template` — HTML template
- `providers` — linked Angular providers with their scripts

### Step 2: Trace Route Targets

Find which pages/widgets this widget navigates to.

```
Tool: trace_portal_route_targets
Parameters:
  widget_ids: ["<widget sys_id>"]
  include_linked_angular_providers: true
  output_mode: "compact"
```

This reveals:
- `$location.path()` calls → target page IDs
- `spUtil.get()` / `$http` calls → API endpoints
- Provider-level routing logic

### Step 3: Check for Pattern Issues

Scan the widget for common problems.

```
Tool: search_portal_regex_matches
Parameters:
  regex: "\\$rootScope|\\$window\\.location|document\\."
  widget_ids: ["<widget sys_id>"]
  source_types: ["widget", "angular_provider"]
  include_widget_fields: ["script", "client_script", "template"]
```

Common anti-patterns to look for:
- `$rootScope` usage (global state pollution)
- Direct DOM access (`document.getElementById`)
- `$window.location` instead of `$location`

### Step 4: Performance Check (Optional)

```
Tool: analyze_widget_performance
Parameters:
  widget_id: "<widget sys_id>"
```

Review:
- Script size and complexity indicators
- Number of linked providers
- Potential N+1 query patterns in server script

## Output

After completing all steps, you'll have:
1. Full source code of the widget (all 5 fields)
2. All linked Angular provider scripts
3. Route target map (where this widget navigates)
4. Anti-pattern findings (if any)
5. Performance indicators

## Tips

- Start with `get_widget_bundle` — it gives you 80% of the picture in one call
- Only use `trace_portal_route_targets` if the widget has navigation logic
- For large widgets with many providers, add `max_matches: 50` to avoid oversized responses
