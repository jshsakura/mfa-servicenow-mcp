---
name: page-management
description: Manage portal pages and widget instances — list, inspect, place, configure
context_cost: low
safety_level: confirm
delegatable: false
required_input: page_id or portal_id
output: data
tools:
  - list_portals
  - get_portal
  - list_pages
  - get_page
  - list_widget_instances
  - get_widget_instance
  - create_widget_instance
  - update_widget_instance
triggers:
  - "페이지 목록"
  - "위젯 배치"
  - "위젯 인스턴스 옵션"
  - "페이지 레이아웃"
  - "page layout"
  - "add widget to page"
  - "list pages"
  - "widget instance options"
---

# Instructions

You are managing portal page layouts and widget instances.

## Pipeline

IF "페이지 목록" or "list pages":
  1. CALL list_portals(limit=10)
  2. CALL list_pages(portal_id=SELECTED, limit=50)
  → RETURN page list with IDs

IF "레이아웃 확인" or "page layout":
  1. CALL get_page(page_id=INPUT)
  2. CALL list_widget_instances(page_id=INPUT, limit=50)
  → RETURN: page info + widget instances with positions

IF "위젯 배치" or "add widget":
  1. CALL create_widget_instance
     - page = PAGE_SYS_ID
     - widget = WIDGET_SYS_ID
     - column = 1
     - order = 100
     - confirm = "approve"
  → RETURN: created instance ID

IF "옵션 변경" or "update options":
  1. CALL get_widget_instance(instance_id=INPUT)
  → SHOW current options
  2. CALL update_widget_instance
     - instance_id = INPUT
     - widget_parameters = {KEY: VALUE}
     - confirm = "approve"

## ON ERROR

- "Widget not found" → verify widget sys_id with get_widget_bundle
- "Page not found" → verify with list_pages
- Empty instances → normal for new pages

## DELEGATE hint

DO NOT delegate. Write operations need user confirmation.
