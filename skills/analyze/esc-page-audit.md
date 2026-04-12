---
name: esc-page-audit
description: Map the Employee Service Center portal — pages, widgets, OOB vs custom, customization points
context_cost: high
safety_level: none
delegatable: true
required_input: none (auto-detects ESC portal)
output: report
tools:
  - list_portals
  - get_portal
  - list_pages
  - list_widget_instances
  - get_widget_bundle
triggers:
  - "ESC 구조"
  - "ESC 감사"
  - "Employee Service Center"
  - "ESC 페이지"
  - "audit ESC"
  - "ESC portal structure"
---

# Instructions

You are mapping the Employee Service Center portal structure.

## Pipeline

1. CALL list_portals(limit=20)
   → FIND portal where url_suffix contains "esc" or name contains "Employee"
   → IF not found: REPORT "ESC not activated. Check plugin com.sn_hr_service_portal."

2. CALL list_pages(portal_id=ESC_SYS_ID, limit=100)

3. FOR EACH key page (esc_landing_page, esc_catalog, esc_knowledge, esc_requests, esc_cases):
   CALL list_widget_instances(page_id=PAGE_SYS_ID, limit=50)

4. FOR EACH widget instance, CALL get_widget_bundle(widget_id=WIDGET_SYS_ID)
   → CHECK sys_scope:
     - "global" or "sn_hr_*" = OOB
     - "x_*" = Custom

5. RETURN report:
   | Page | Widget Count | Custom | OOB |
   FOR EACH page, list widgets with custom/OOB classification
   Total customization points identified

## ON ERROR

- Portal not found → ESC plugin not activated
- ACL errors → need admin or sn_hr_sp.admin role
- 0 pages → wrong portal selected

## DELEGATE hint

ALWAYS delegate. This produces large output. Return summary table only.
