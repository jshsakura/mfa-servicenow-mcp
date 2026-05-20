---
name: widget-patching
description: Safely modify widget code — MANDATORY preview → confirm → apply pipeline
context_cost: medium
safety_level: staged
delegatable: false
required_input: widget_id + what to change
output: diff
tools:
  - get_portal_component_code
  - preview_portal_component_update
  - manage_portal_component
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

ServiceNow versions every record server-side, so no local snapshot is needed — recovery is done through the platform's version history if required.

## Pipeline

### GATE RULES

- GATE 1: Preview MUST be shown to user before apply
- GATE 2: User MUST confirm before apply
- VIOLATION: If any gate is skipped, STOP and explain why you cannot proceed

### Simple Change (one field, clear instruction)

1. CALL route_portal_component_edit
   - table = "sp_widget"
   - sys_id = INPUT
   - instruction = USER_REQUEST
   - fields = [DETECTED_FIELD]
   → This internally runs analyze → preview → waits for confirm

### Complex Change (multi-field or needs review)

### Read Current Code

CALL get_portal_component_code
  - table = "sp_widget"
  - sys_id = INPUT
  - fields = [RELEVANT_FIELDS]

### Generate Fix

Based on user request and current code, generate the modified code.

### GATE 1: Preview

CALL preview_portal_component_update
  - table = "sp_widget"
  - sys_id = INPUT
  - update_fields = {FIELD: NEW_CONTENT}
→ SHOW diff to user. ASK "Apply this change?"

### GATE 2: Apply

ONLY after user confirms:
CALL manage_portal_component
  - action = "update_code"
  - table = "sp_widget"
  - sys_id = INPUT
  - update_data = {FIELD: NEW_CONTENT}
  - confirm = "approve"

## ON ERROR

- "Unsupported field" → allowed: script, client_script, template, css, link
- Preview shows no diff → content already matches, no change needed

## DELEGATE hint

DO NOT delegate. This requires user interaction at GATE 1 and GATE 2.
