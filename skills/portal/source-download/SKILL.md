---
name: source-download
version: 1.0.0
description: Export portal widget, provider, and script include sources to local files for offline review or version control
author: jshsakura
tags: [portal, export, download, source, backup]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - download_portal_sources
complexity: beginner
estimated_time: 2-5 minutes
---

# Source Download

## Overview

Export Service Portal sources (widgets, Angular providers, script includes) to a local file structure. Useful for offline code review, git version control, or migration preparation.

**When to use:**
- "Download all widgets in this scope"
- "Export this portal's source code"
- "Back up portal sources before a release"
- "Set up local development for these widgets"

## Prerequisites

- **Roles:** Read access to `sp_widget`, `sp_angular_provider`, `sys_script_include`
- **MCP Package:** `standard` or higher

## Procedure

### Basic: Export Specific Widgets

```
Tool: download_portal_sources
Parameters:
  widget_ids: ["widget-id-1", "widget-id-2"]
  include_linked_angular_providers: true
  include_linked_script_includes: true
```

### Full Scope Export

```
Tool: download_portal_sources
Parameters:
  scope: "x_company_app"
  max_widgets: 100
  include_widget_template: true
  include_widget_server_script: true
  include_widget_client_script: true
  include_widget_link_script: true
  include_widget_css: true
  include_linked_angular_providers: true
  include_linked_script_includes: true
```

### Custom Output Directory

```
Tool: download_portal_sources
Parameters:
  scope: "x_company_app"
  output_dir: "~/servicenow-exports/my-portal"
```

## Output Structure

```
<output_dir>/
  _settings.json              ← instance name, URL, g_ck token
  <scope>/
    sp_widget/
      _map.json               ← widget ID → sys_id mapping
      <widget-id>/
        _widget.json           ← full metadata + save payload
        template.html
        script.js              ← server script
        client_script.js
        link.js
        css.scss
        option_schema.json
        demo_data.json
        _test_urls.txt         ← preview/config URLs
    sp_angular_provider/
      _map.json
      <provider-name>.script.js
    sys_script_include/
      _map.json
      <si-name>.script.js
```

## Tips

- Default exports only the widgets you specify — use `scope` for bulk export
- Linked providers and script includes are opt-in to keep exports small
- The `_widget.json` file contains the full ServiceNow save payload — compatible with SN Utils import format
- `_test_urls.txt` has direct links to preview the widget in ServiceNow
