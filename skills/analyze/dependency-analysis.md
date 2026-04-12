---
name: dependency-analysis
description: Map what depends on what — safe to delete? what breaks if I change this?
context_cost: medium
safety_level: none
delegatable: true
required_input: sys_id and table (or widget_id, or name to search)
output: data
tools:
  - extract_table_dependencies
  - extract_widget_table_dependencies
  - get_provider_dependency_map
  - search_server_code
  - search_portal_regex_matches
triggers:
  - "지워도 돼"
  - "의존성 확인"
  - "뭐가 깨질까"
  - "누가 이거 쓰는지"
  - "is it safe to delete"
  - "what depends on this"
  - "check dependencies"
---

# Instructions

You are checking dependencies before a destructive or risky change.

## Pipeline

IF input is a script (sys_script, sys_script_include):
  1. CALL extract_table_dependencies(sys_id=INPUT, table=INPUT_TABLE)
     → lists tables referenced by GlideRecord

IF input is a widget:
  1. CALL extract_widget_table_dependencies(widget_id=INPUT)
     → lists tables the widget's server script queries

IF input is a provider or "who uses X":
  1. CALL get_provider_dependency_map(scope=INPUT_SCOPE)
     → shows widget↔provider relationships

2. REVERSE SEARCH — find all references to this artifact:
   CALL search_server_code(query=INPUT_NAME, tables=["sys_script","sys_script_include","sys_client_script"])
   CALL search_portal_regex_matches(regex=INPUT_NAME, source_types=["widget","angular_provider"], include_widget_fields=["script","client_script"])

3. RETURN:
   - Forward dependencies: what INPUT uses
   - Reverse dependencies: what uses INPUT
   - Safe to delete: YES if reverse count = 0, NO otherwise
   - Blast radius: number of artifacts affected

## ON ERROR

- 0 dependencies → either truly unused or wrong sys_id. Verify with reverse search.

## DELEGATE hint

Delegatable for bulk analysis (e.g., "check all script includes in scope").
