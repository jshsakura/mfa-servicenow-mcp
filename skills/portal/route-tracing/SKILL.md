---
name: route-tracing
version: 1.0.0
description: Trace navigation routes across portal widgets and providers to map page flows and find dead links
author: jshsakura
tags: [portal, route, navigation, dead-link, trace]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - trace_portal_route_targets
    - search_portal_regex_matches
    - list_pages
complexity: beginner
estimated_time: 3-5 minutes
---

# Route Tracing

## Overview

Trace how users navigate through a Service Portal — map `$location.path()` calls, `spUtil.get()` invocations, and hardcoded URL references across widgets and providers. Find dead links pointing to non-existent pages.

**When to use:**
- "Where does clicking this button take the user?"
- "Which pages link to this widget?"
- "Find all dead links in the portal"
- "Map the navigation flow of this portal"

## Prerequisites

- **Roles:** Read access to `sp_widget`, `sp_angular_provider`, `sp_page`
- **MCP Package:** `standard` or higher

## Procedure

### Step 1: Trace Routes from Specific Widgets

```
Tool: trace_portal_route_targets
Parameters:
  widget_ids: ["<widget sys_id or id>"]
  include_linked_angular_providers: true
  output_mode: "compact"
```

The result shows:
- **route_targets**: page IDs found in `$location.path()`, `spUtil.get()`, `href` attributes
- **source**: which widget/provider/field contains the reference
- **evidence**: code snippet with the route call

### Step 2: Scan for Hardcoded URLs

```
Tool: search_portal_regex_matches
Parameters:
  regex: "\\?id=[a-zA-Z_-]+"
  scope: "<app scope>"
  source_types: ["widget", "angular_provider"]
  include_widget_fields: ["template", "client_script", "script"]
  max_widgets: 30
```

This catches `?id=page-name` patterns that `trace_portal_route_targets` might miss (e.g., in HTML `href` attributes).

### Step 3: Cross-Reference with Existing Pages

```
Tool: list_pages
Parameters:
  portal_id: "<portal sys_id>"
  limit: 100
```

Compare the route targets from Steps 1-2 against the actual page list. Any target not in the page list is a dead link.

**Dead link detection:**
```
Route targets found: [page-a, page-b, page-c, legacy-page]
Actual pages:        [page-a, page-b, page-c]
Dead links:          [legacy-page]  ← does not exist
```

### Step 4: Broader Scan (Optional)

To map the entire portal's navigation:

```
Tool: trace_portal_route_targets
Parameters:
  scope: "<app scope>"
  include_linked_angular_providers: true
  max_widgets: 50
  output_mode: "minimal"
```

## Output

| Route Target | Source Widget | Source Field | Evidence | Page Exists |
|-------------|-------------|-------------|----------|-------------|
| `page-a` | my-widget | client_script | `$location.path('/page-a')` | Yes |
| `legacy-page` | old-widget | template | `href="?id=legacy-page"` | **No (dead link)** |

## Tips

- Use `output_mode: "minimal"` for large scans to reduce response size
- Dead links often come from deprecated widgets that reference removed pages
- Hardcoded `?id=` in templates is more fragile than `$location.path()` — flag these for refactoring
