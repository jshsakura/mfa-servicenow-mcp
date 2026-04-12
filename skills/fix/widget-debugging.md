---
name: widget-debugging
description: Systematically debug a broken widget — logs, source, data flow, dependencies
context_cost: high
safety_level: none
delegatable: true
required_input: widget_id + symptom description
output: diagnosis
tools:
  - get_widget_bundle
  - get_portal_component_code
  - get_system_logs
  - get_transaction_logs
  - search_portal_regex_matches
  - analyze_widget_performance
  - sn_query
triggers:
  - "위젯이 안 돼"
  - "에러 나는데"
  - "디버깅해줘"
  - "왜 안 보이지"
  - "widget is broken"
  - "debug this widget"
  - "widget not loading"
  - "widget shows wrong data"
---

# Instructions

You are debugging a broken Service Portal widget. Follow the symptom-based path.

## Pipeline

IF user has an error message:
  1. CALL get_system_logs(query="messageLIKE{ERROR_TEXT}", limit=20, minutes_ago=30)
  2. CALL get_widget_bundle(widget_id=INPUT, include_providers=true)
  3. MATCH error to source code location
  → RETURN: root cause + file + line

IF widget loads but wrong data:
  1. CALL get_portal_component_code(table="sp_widget", sys_id=INPUT, fields=["script"])
  2. EXTRACT GlideRecord queries from server script
  3. CALL sn_query with same table/query/fields to verify data exists
  4. COMPARE: does server script set data.X correctly? does template read {{c.data.X}}?
  → RETURN: data flow mismatch location

IF widget doesn't load at all:
  1. CALL get_system_logs(query="messageLIKE{WIDGET_NAME}", limit=20, minutes_ago=30)
  2. CALL get_transaction_logs(query="urlLIKEsp^status>=400", limit=20, minutes_ago=30)
  3. CALL get_widget_bundle(widget_id=INPUT, include_providers=true)
  4. CHECK: are all injected providers linked? any syntax errors?
  → RETURN: failure point (ACL / provider missing / syntax error)

IF widget is slow:
  1. CALL analyze_widget_performance(widget_id=INPUT)
  2. CALL get_portal_component_code(table="sp_widget", sys_id=INPUT, fields=["script"])
  3. COUNT GlideRecord calls. IF inside loop → N+1 pattern
  4. CHECK script size. IF > 50KB → too large
  → RETURN: performance bottleneck

## Common Root Causes

| Symptom | Cause | Verification |
|---------|-------|-------------|
| "Cannot read property of undefined" | data.X not set in server script | check server script sets all data props |
| Widget blank, no errors | ACL blocking GlideRecord | system logs show "security" |
| Widget slow (5s+) | N+1 queries in server script | count GlideRecord inside loops |
| "Provider not found" | Angular provider not linked to widget | check M2M relationship |

## ON ERROR

- No logs found → increase minutes_ago to 60, or widget name might differ from ID
- ACL on logs → need admin role for system/transaction logs

## DELEGATE hint

Delegate the log search and source read to sub-agent. Return diagnosis summary only.
