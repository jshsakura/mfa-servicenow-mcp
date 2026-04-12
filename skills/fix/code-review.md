---
name: code-review
description: Search server-side code for security issues, anti-patterns, and bugs
context_cost: medium
safety_level: none
delegatable: true
required_input: scope or search pattern
output: report
tools:
  - search_server_code
  - get_metadata_source
  - extract_table_dependencies
  - audit_pending_changes
triggers:
  - "코드 리뷰"
  - "보안 검사"
  - "eval 찾아줘"
  - "커밋 전 검토"
  - "code review"
  - "security audit"
  - "find eval usage"
  - "review before commit"
---

# Instructions

You are reviewing server-side code for issues.

## Pipeline

IF searching for a pattern:
  1. CALL search_server_code
     - query = INPUT_PATTERN (e.g., "eval(")
     - tables = ["sys_script", "sys_script_include", "sys_client_script", "sys_ui_action"]
     - scope = INPUT_SCOPE
     - max_results = 50
  2. FOR EACH match with high-risk pattern:
     CALL get_metadata_source(sys_id=MATCH_SYS_ID, table=MATCH_TABLE)
     → READ full context around the match
  3. RETURN: findings with location, risk level, fix suggestion

IF pre-commit audit:
  1. CALL audit_pending_changes
     - scope = INPUT_SCOPE
     - include_risk_scan = true
  2. RETURN: change inventory + risk findings

## Security Patterns to Check

| Pattern | Risk | Fix |
|---------|------|-----|
| `eval(` | Critical — code injection | refactor to avoid |
| `gs.execute` | Critical — arbitrary script | use specific API |
| `innerHTML` | High — XSS | use Angular binding |
| `setWorkflow(false)` | High — bypasses business rules | document why |
| `current.update()` | High — recursive in business rules | use workflow instead |

## ON ERROR

- 0 results → clean code or wrong scope
- ACL error → need admin role

## DELEGATE hint

Delegatable. Return findings summary.
