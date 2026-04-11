---
name: widget-patching
version: 1.0.0
description: Modify portal widget code through a safe snapshot-preview-apply workflow with automatic rollback support
author: jshsakura
tags: [portal, widget, edit, patch, snapshot, rollback]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - get_portal_component_code
    - create_portal_component_snapshot
    - analyze_portal_component_update
    - preview_portal_component_update
    - update_portal_component
    - update_portal_component_from_snapshot
    - route_portal_component_edit
complexity: intermediate
estimated_time: 5-10 minutes
---

# Widget Patching

## Overview

Safely modify a Service Portal widget's code fields (script, client_script, template, css, link) through a controlled workflow: snapshot current state, preview changes, apply, and rollback if needed.

**When to use:**
- "Fix a bug in this widget's server script"
- "Add a condition to the client script"
- "Update the widget template HTML"
- "Rollback the last widget change"

## Prerequisites

- **Roles:** Write access to `sp_widget` (typically `sp_admin` or scoped app developer)
- **MCP Package:** `portal_developer` or higher

## Procedure

### Step 1: Read Current Code

```
Tool: get_portal_component_code
Parameters:
  table: "sp_widget"
  sys_id: "<widget sys_id>"
  fields: ["script", "client_script", "template"]
```

Review the current code to understand what needs to change.

### Step 2: Create Snapshot (Safety Net)

Before any modification, save the current state.

```
Tool: create_portal_component_snapshot
Parameters:
  table: "sp_widget"
  sys_id: "<widget sys_id>"
  fields: ["script", "client_script", "template", "css", "link"]
```

Save the returned `snapshot_path` — you'll need it for rollback.

### Step 3: Preview Changes

See a diff of proposed changes before applying.

```
Tool: preview_portal_component_update
Parameters:
  table: "sp_widget"
  sys_id: "<widget sys_id>"
  update_fields:
    script: "<new server script content>"
```

Review the diff output. If it looks wrong, adjust and preview again.

### Step 4: Apply Changes

```
Tool: update_portal_component
Parameters:
  table: "sp_widget"
  sys_id: "<widget sys_id>"
  update_fields:
    script: "<new server script content>"
  confirm: "approve"
```

### Step 5: Rollback (If Needed)

If the change causes issues, restore from snapshot.

```
Tool: update_portal_component_from_snapshot
Parameters:
  snapshot_path: "<path from Step 2>"
  confirm: "approve"
```

## Alternative: One-Shot Edit via Router

For simple edits, the router handles the entire workflow automatically.

```
Tool: route_portal_component_edit
Parameters:
  table: "sp_widget"
  sys_id: "<widget sys_id>"
  instruction: "Add error handling for empty data.profit_company_code in the server script"
  fields: ["script"]
```

The router detects the intent (analyze/preview/apply/snapshot/rollback) and executes the appropriate steps.

## Tips

- Always create a snapshot before modifying production widgets
- Preview before apply — the diff catches unintended changes
- One field at a time for complex changes — easier to review and rollback
- Use `route_portal_component_edit` for simple, well-defined changes
- Use the manual step-by-step flow for complex multi-field edits
