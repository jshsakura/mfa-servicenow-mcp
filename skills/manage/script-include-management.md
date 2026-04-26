---
name: script-include-management
description: Script include CRUD + GlideAjax execution
context_cost: low
safety_level: confirm
delegatable: false
required_input: SI name or sys_id
output: data
tools:
  - list_script_includes
  - get_script_include
  - manage_script_include
triggers:
  - "스크립트 인클루드"
  - "SI 보여줘"
  - "GlideAjax 실행"
  - "SI 만들어줘"
  - "script include"
  - "execute GlideAjax"
  - "create script include"
---

# Instructions

You are managing Script Includes.

## Pipeline

IF "목록" or "list":
  CALL list_script_includes(query=INPUT, active=true, limit=20)
  → count only: list_script_includes(query=INPUT, count_only=true)

IF "읽기" or "read source":
  CALL get_script_include(script_include_id=INPUT)
  → accepts name or "sys_id:abc123"

IF "만들기" or "create":
  CALL manage_script_include(action="create", name=INPUT, script=SCRIPT, ...)
    - confirm = "approve"

IF "수정" or "update":
  # 1. Preview field-level diff (no side effects)
  CALL manage_script_include(action="update", script_include_id=INPUT, <fields>, dry_run=True)
  # 2. Show `proposed_changes` + `no_op_fields`, then apply
  CALL manage_script_include(action="update", script_include_id=INPUT, <fields>)
    - confirm = "approve"

IF "실행" or "execute GlideAjax":
  CALL manage_script_include(action="execute", name=INPUT, method=METHOD_NAME, exec_params={...})
    - confirm = "approve"
  → requires client_callable=true

IF "삭제" or "delete":
  CALL manage_script_include(action="delete", script_include_id=INPUT)
    - confirm = "approve"

## ON ERROR

- "not client-callable" → update with client_callable=true first
- "not found" → use list_script_includes to find correct name

## DELEGATE hint

DO NOT delegate write operations. Read operations are delegatable.
