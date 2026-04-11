---
name: code-detection
version: 1.0.0
description: Detect missing branch values in widget code — find where conditional logic handles some cases but not all required ones
author: jshsakura
tags: [portal, detection, branch, missing-code, audit]
platforms: [claude-code, claude-desktop, any]
tools:
  mcp:
    - detect_missing_profit_company_codes
    - search_portal_regex_matches
    - get_portal_component_code
complexity: intermediate
estimated_time: 5-10 minutes
---

# Code Detection

## Overview

Detect missing conditional branch values in widget and provider scripts. When code branches on a field (e.g., company code, category, status), this skill finds where some required values are handled but others are missing.

**When to use:**
- "Check if all company codes are handled in these widgets"
- "Find widgets missing a branch for the new status value"
- "Audit code completeness for field X"

## Prerequisites

- **Roles:** Read access to `sp_widget`, `sp_angular_provider`
- **MCP Package:** `standard` or higher

## Procedure

### Step 1: Run Missing Code Detection

```
Tool: detect_missing_profit_company_codes
Parameters:
  required_codes: ["2400", "5K00", "2J00"]
  target_field_patterns:
    - "profit_company_code"
    - "c.data.profit_company_code"
    - "data.profit_company_code"
  scope: "x_company_app"
  include_widget_client_script: true
  include_widget_server_script: true
  include_angular_providers: true
  max_widgets: 25
  output_mode: "compact"
```

The detector finds:
- `==` / `===` comparisons against the target field
- `switch/case` blocks on the target field
- `[].includes()` array checks
- Reports which required values are present and which are missing

### Step 2: Review Findings

Each finding includes:
- **location**: `widget/WidgetName/client_script`
- **line**: line number in source
- **snippet**: code context around the detection
- **found_codes**: values already handled (e.g., `["2400", "5K00"]`)
- **missing_codes**: values not handled (e.g., `["2J00"]`)
- **confidence**: `high` (direct comparison), `medium` (switch/includes), `low` (field mentioned but unclear)

Focus on `high` and `medium` confidence findings first.

### Step 3: Verify with Full Source

For each finding, read the full source to confirm.

```
Tool: get_portal_component_code
Parameters:
  table: "sp_widget"
  sys_id: "<widget sys_id from finding>"
  fields: ["client_script"]
```

Check if the missing code is handled elsewhere (e.g., in a `default` case or a separate function).

### Step 4: Generalize for Any Field

The tool works for any field, not just profit_company_code. Customize:

```
Tool: detect_missing_profit_company_codes
Parameters:
  required_codes: ["active", "inactive", "pending", "closed"]
  target_field_patterns:
    - "record.state"
    - "c.data.state"
    - "data.state"
  widget_prefix: "my-app"
```

## Limitations

- Static analysis only — cannot track dynamic values (variables, config lookups)
- Does not follow function calls across files
- `low` confidence findings may be false positives
- Always verify findings with `get_portal_component_code` before patching

## Tips

- Use `widget_prefix` or `widget_ids` to narrow the scan — avoid scanning the entire instance
- Set `output_mode: "minimal"` for large scans to reduce response size
- Combine with the `widget-patching` skill to fix findings after detection
