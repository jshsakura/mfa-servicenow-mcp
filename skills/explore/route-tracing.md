---
name: route-tracing
description: Trace portal navigation paths and find dead links
context_cost: medium
safety_level: none
delegatable: true
required_input: widget_id or scope
output: data
tools:
  - trace_portal_route_targets
  - search_portal_regex_matches
  - list_pages
triggers:
  - "어디로 이동"
  - "데드 링크"
  - "네비게이션 맵"
  - "라우트 추적"
  - "where does this go"
  - "find dead links"
  - "trace navigation"
---

# Instructions

You are tracing navigation paths across portal widgets.

## Pipeline

IF specific widget:
  1. CALL trace_portal_route_targets
     - widget_ids = [INPUT]
     - include_linked_angular_providers = true
     - output_mode = "compact"
  → RETURN: route targets with source evidence

IF find dead links:
  1. CALL trace_portal_route_targets(scope=INPUT, max_widgets=50, output_mode="minimal")
  2. CALL search_portal_regex_matches(regex="\\?id=[a-zA-Z_-]+", scope=INPUT, source_types=["widget","angular_provider"], include_widget_fields=["template","client_script"])
  3. CALL list_pages(portal_id=PORTAL_SYS_ID, limit=100)
  4. COMPARE: targets vs actual pages
     → any target not in page list = DEAD LINK
  → RETURN: dead links with source location

IF map entire portal:
  1. CALL trace_portal_route_targets(scope=INPUT, max_widgets=50, output_mode="minimal")
  → RETURN: full route target map

## ON ERROR

- 0 targets → widget has no navigation (normal for display-only)
- All look dead → wrong portal selected, verify with list_portals

## DELEGATE hint

Delegatable for broad scans. Return summary only.
