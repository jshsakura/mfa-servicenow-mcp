---
name: schema-discovery
description: Find tables and inspect field definitions
context_cost: low
safety_level: none
delegatable: true
required_input: keyword or table name
output: data
tools:
  - sn_discover
  - sn_schema
  - sn_query
  - sn_aggregate
triggers:
  - "테이블 찾기"
  - "필드 뭐 있어"
  - "스키마"
  - "find table"
  - "show fields"
  - "what tables exist"
---

# Instructions

You are exploring the ServiceNow data model.

## Pipeline

IF "테이블 찾기" or "find table":
  CALL sn_discover(keyword=INPUT, limit=20)
  → RETURN matching tables with names, labels, parent class

IF "필드 확인" or "show fields":
  CALL sn_schema(table=INPUT, limit=500)
  → RETURN field list: name, label, type, mandatory, reference target

IF "샘플 데이터" or "sample":
  CALL sn_query(table=INPUT, fields="sys_id,name,...", limit=5, display_value=true)

IF "레코드 수" or "count":
  CALL sn_aggregate(table=INPUT, aggregate="COUNT", query=INPUT_QUERY, group_by=INPUT_GROUP)

## Portal Tables Quick Reference

| Table | Purpose |
|-------|---------|
| sp_portal | Portal definitions |
| sp_page | Portal pages |
| sp_widget | Widget source code |
| sp_instance | Widget instances on pages |
| sp_angular_provider | Angular providers |
| m2m_sp_widget_angular_provider | Widget↔Provider links |
| sp_css | Portal CSS themes |

## ON ERROR

- 0 results → try broader keyword
- ACL error → table may be restricted

## DELEGATE hint

Delegatable for bulk schema exploration.
