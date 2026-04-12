---
name: esc-catalog-flow
description: Trace ESC catalog request flow — browse widget → item detail → variables → fulfillment
context_cost: high
safety_level: none
delegatable: true
required_input: catalog_item_id (optional, traces full flow if omitted)
output: report
tools:
  - get_portal
  - get_page
  - get_widget_instance
  - get_widget_bundle
  - trace_portal_route_targets
  - list_catalog_items
  - get_catalog_item
  - list_catalog_item_variables
  - sn_query
triggers:
  - "ESC 카탈로그 흐름"
  - "카탈로그 요청 추적"
  - "ESC 서비스 요청"
  - "trace ESC catalog"
  - "how does catalog work in ESC"
  - "catalog request flow"
---

# Instructions

You are tracing how a catalog request flows through ESC portal widgets.

## The Flow

```
User → esc_catalog page → selects item → esc_cat_item page → fills variables → submits → sc_req_item → approval → fulfillment
```

## Pipeline

1. CALL get_portal(limit=20)
   → FIND ESC portal (url_suffix contains "esc")
   → IF not found: REPORT "ESC not activated"

2. CALL get_page(portal_id=ESC_SYS_ID, limit=100)
   → FIND: esc_catalog, esc_cat_item pages

3. CALL get_widget_instance(page_id=CATALOG_PAGE_SYS_ID, limit=20)
   → IDENTIFY catalog browse widget

4. CALL get_widget_bundle(widget_id=BROWSE_WIDGET, include_providers=true)
   → READ how items are loaded and displayed

5. CALL trace_portal_route_targets(widget_ids=[BROWSE_WIDGET], include_linked_angular_providers=true, output_mode="compact")
   → FIND navigation from browse → item detail

6. IF specific catalog item given:
   CALL get_catalog_item(item_id=INPUT)
   → CHECK: workflow, delivery_plan, flow fields
   CALL list_catalog_item_variables(item_id=INPUT, limit=50)
   → LIST variables with types and mandatory flags

7. CALL sn_query(table="sc_req_item", query="cat_item=ITEM_SYS_ID^ORDERBYDESCsys_created_on", fields="number,state,stage", limit=5, display_value=true)
   → CHECK recent request status

8. RETURN flow summary:
   - Browse page → widget name
   - Detail page → widget name
   - Variables: count (mandatory count)
   - Fulfillment: workflow/flow/delivery_plan name
   - Recent requests: last 5 statuses

## ON ERROR

- ESC not found → check com.sn_hr_service_portal plugin
- No catalog pages → ESC may use standard sp catalog pages
- No workflow on item → check "flow" field (Flow Designer)

## DELEGATE hint

ALWAYS delegate. High context cost from multiple API calls. Return flow summary only.
