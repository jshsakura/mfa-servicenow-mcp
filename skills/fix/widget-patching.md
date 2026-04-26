---
name: widget-patching
description: Safely modify widget code — MANDATORY snapshot → preview → apply pipeline with rollback
context_cost: medium
safety_level: staged
delegatable: false
required_input: widget_id + what to change
output: diff
tools:
  - get_portal_component_code
  - create_portal_component_snapshot
  - preview_portal_component_update
  - manage_portal_component
  - update_portal_component_from_snapshot
  - route_portal_component_edit
triggers:
  - "위젯 수정"
  - "코드 고쳐"
  - "스크립트 바꿔"
  - "패치해줘"
  - "fix widget"
  - "update widget code"
  - "patch the script"
---

# Instructions

You are modifying a Service Portal widget. This is a STAGED safety pipeline. DO NOT skip gates.

## Pipeline

### GATE RULES

- GATE 1: Snapshot MUST exist before any modification
- GATE 2: Preview MUST be shown to user before apply
- GATE 3: User MUST confirm before apply
- VIOLATION: If any gate is skipped, STOP and explain why you cannot proceed

### Simple Change (one field, clear instruction)

1. CALL route_portal_component_edit
   - table = "sp_widget"
   - sys_id = INPUT
   - instruction = USER_REQUEST
   - fields = [DETECTED_FIELD]
   → This internally runs snapshot → analyze → preview → waits for confirm

### Complex Change (multi-field or needs review)

### GATE 1: Snapshot

CALL create_portal_component_snapshot
  - table = "sp_widget"
  - sys_id = INPUT
  - fields = ["script", "client_script", "template", "css", "link"]
→ SAVE snapshot_path. DO NOT proceed without it.

### Read Current Code

CALL get_portal_component_code
  - table = "sp_widget"
  - sys_id = INPUT
  - fields = [RELEVANT_FIELDS]

### Generate Fix

Based on user request and current code, generate the modified code.

### GATE 2: Preview

CALL preview_portal_component_update
  - table = "sp_widget"
  - sys_id = INPUT
  - update_fields = {FIELD: NEW_CONTENT}
→ SHOW diff to user. ASK "Apply this change?"

### GATE 3: Apply

ONLY after user confirms:
CALL manage_portal_component
  - action = "update_code"
  - table = "sp_widget"
  - sys_id = INPUT
  - update_data = {FIELD: NEW_CONTENT}
  - confirm = "approve"

### Rollback (if user reports issue after apply)

CALL update_portal_component_from_snapshot
  - snapshot_path = SAVED_PATH
  - confirm = "approve"

## ON ERROR

- "Unsupported field" → allowed: script, client_script, template, css, link
- "Snapshot not found" → check ~/.servicenow_mcp/portal_component_snapshots/
- Preview shows no diff → content already matches, no change needed

## DELEGATE hint

DO NOT delegate. This requires user interaction at GATE 2 and GATE 3.
