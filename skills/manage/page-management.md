---
name: page-management
description: Manage portal pages and widget instances — create, list, inspect, place, configure, scaffold
context_cost: low
safety_level: confirm
delegatable: false
required_input: page_id or portal_id
output: data
tools:
  - get_portal
  - get_page
  - get_widget_instance
  - create_widget_instance
  - update_widget_instance
  - create_page
  - update_page
  - create_container
  - create_row
  - create_column
  - scaffold_page
triggers:
  - "페이지 목록"
  - "위젯 배치"
  - "위젯 인스턴스 옵션"
  - "페이지 레이아웃"
  - "페이지 생성"
  - "페이지 만들기"
  - "page layout"
  - "add widget to page"
  - "list pages"
  - "create page"
  - "scaffold page"
  - "widget instance options"
---

# Instructions

You are managing portal page layouts and widget instances.

## Pipeline

IF "페이지 목록" or "list pages":
  1. CALL get_portal(limit=10)
  2. CALL get_page(portal_id=SELECTED, limit=50)
  → RETURN page list with IDs

IF "레이아웃 확인" or "page layout":
  1. CALL get_page(page_id=INPUT)
  2. CALL get_widget_instance(page_id=INPUT, limit=50)
  → RETURN: page info + widget instances with positions

IF "페이지 생성" or "create page":
  1. CONFIRM scope sys_id with user (REQUIRED — never default to Global)
  2. CALL create_page
     - id = URL_PATH
     - title = TITLE
     - scope = SCOPE_SYS_ID
  → RETURN: created page sys_id
  3. Suggest: "Use scaffold_page for page + layout + widget placement in one call"

IF "페이지 일괄 생성" or "scaffold page":
  1. CONFIRM scope sys_id with user (REQUIRED)
  2. CONFIRM row/column layout (e.g. [6,6], [4,4,4], [12])
  3. CALL scaffold_page
     - page_id = URL_PATH
     - title = TITLE
     - scope = SCOPE_SYS_ID
     - rows = [{columns: [COL_SIZES], widgets: [WIDGET_IDS]}]
  → RETURN: created inventory (page, container, rows, columns, instances)

IF "레이아웃 추가" or "add layout":
  1. CALL create_container(sp_page=PAGE_SYS_ID)
  2. CALL create_row(sp_container=CONTAINER_SYS_ID)
  3. CALL create_column(sp_row=ROW_SYS_ID, size=BOOTSTRAP_SIZE)
  → RETURN: column sys_id ready for widget placement

IF "위젯 배치" or "add widget":
  1. CALL create_widget_instance
     - sp_widget = WIDGET_SYS_ID
     - sp_column = COLUMN_SYS_ID
     - order = 100
  → RETURN: created instance ID

IF "옵션 변경" or "update options":
  1. CALL get_widget_instance(instance_id=INPUT)
  → SHOW current options
  2. CALL update_widget_instance
     - instance_id = INPUT
     - widget_parameters = {KEY: VALUE}

## Safety Rules

- NEVER create components without explicit scope — ask user if scope is missing
- scaffold_page returns created record IDs; if partial failure occurs, report cleanup_hint
- Column sizes in a row MUST sum to 12
- Duplicate page id or widget name will be rejected automatically

## ON ERROR

- "Widget not found" → verify widget sys_id with get_widget_bundle
- "Page not found" → verify with get_page
- "already exists" → component with same name/id exists; ask user to use update instead
- Empty instances → normal for new pages
- scaffold partial failure → report created dict for manual cleanup

## DELEGATE hint

DO NOT delegate. Write operations need user confirmation.
