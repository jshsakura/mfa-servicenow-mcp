---
name: portal-diagnosis
version: 1.0.0
description: Diagnose a Service Portal's health — widget inventory, anti-patterns, implicit globals, unused providers, and performance issues
author: jshsakura
tags: [portal, diagnosis, health, performance, anti-pattern]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - list_portals
    - list_pages
    - list_widget_instances
    - get_widget_bundle
    - search_portal_regex_matches
    - detect_angular_implicit_globals
    - analyze_widget_performance
    - get_provider_dependency_map
complexity: intermediate
estimated_time: 10-20 minutes
---

# Portal Diagnosis

## Overview

Run a comprehensive health check on a Service Portal — inventory all pages and widgets, detect anti-patterns, find implicit globals, identify unused providers, and surface performance issues.

**When to use:**
- "Is this portal healthy?"
- "Find all problems in our portal"
- "Which widgets have code quality issues?"
- "Are there unused Angular providers?"

## Prerequisites

- **Roles:** Read access to portal tables (`sp_portal`, `sp_page`, `sp_widget`, `sp_angular_provider`)
- **MCP Package:** `standard` or higher

## Procedure

### Step 1: Inventory the Portal

```
Tool: list_portals
Parameters:
  limit: 10
```

Pick the target portal and note its `sys_id`.

```
Tool: list_pages
Parameters:
  portal_id: "<portal sys_id>"
  limit: 50
```

```
Tool: list_widget_instances
Parameters:
  page_id: "<page sys_id>"
  limit: 50
```

Build a map: Portal → Pages → Widget Instances.

### Step 2: Anti-Pattern Scan

Scan all widgets in scope for common issues.

```
Tool: search_portal_regex_matches
Parameters:
  regex: "\\$rootScope\\.|document\\.getElementById|\\$window\\.location|innerHTML|eval\\("
  scope: "<app scope if applicable>"
  source_types: ["widget", "angular_provider"]
  include_widget_fields: ["script", "client_script", "template"]
  max_widgets: 50
  max_matches: 100
```

Each finding includes source location, line number, and snippet.

**Critical anti-patterns:**
| Pattern | Risk | Fix |
|---------|------|-----|
| `$rootScope` | Global state pollution | Use service or `c.data` |
| `document.getElementById` | Bypasses Angular digest | Use `angular.element` |
| `$window.location` | Full page reload | Use `$location.path()` |
| `innerHTML` | XSS vulnerability | Use `ng-bind-html` with `$sce` |
| `eval(` | Code injection | Refactor to avoid |

### Step 3: Implicit Globals Detection

Find undeclared variables in Angular providers.

```
Tool: detect_angular_implicit_globals
Parameters:
  scope: "<app scope>"
  max_providers: 50
  max_matches: 50
```

Implicit globals cause silent bugs and are hard to debug.

### Step 4: Provider Dependency Map

Check for orphaned or over-connected providers.

```
Tool: get_provider_dependency_map
Parameters:
  scope: "<app scope>"
```

Look for:
- Providers linked to 0 widgets (orphaned — candidate for cleanup)
- Providers linked to 10+ widgets (shared — high blast radius for changes)

### Step 5: Performance Spot-Check

Pick the heaviest widgets from Step 1 and check them individually.

```
Tool: analyze_widget_performance
Parameters:
  widget_id: "<widget sys_id>"
```

## Output Summary

After all steps, compile a diagnosis report:

| Area | Status | Details |
|------|--------|---------|
| Pages | Count | Total pages in portal |
| Widgets | Count | Total widget instances |
| Anti-patterns | Count | Findings from regex scan |
| Implicit globals | Count | Undeclared variables |
| Orphaned providers | Count | Providers linked to 0 widgets |
| Performance flags | Count | Widgets with size/complexity warnings |

## Tips

- Start with Step 2 (anti-pattern scan) if you want quick results
- For large portals (50+ pages), narrow the scope with `widget_prefix` or `scope`
- Run this diagnosis before major portal releases
- Export findings as a checklist for the development team
