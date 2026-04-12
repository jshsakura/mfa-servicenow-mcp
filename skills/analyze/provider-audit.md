---
name: provider-audit
description: Audit Angular providers — implicit globals, orphans, over-connected services
context_cost: medium
safety_level: none
delegatable: true
required_input: scope
output: report
tools:
  - detect_angular_implicit_globals
  - get_provider_dependency_map
  - search_portal_regex_matches
triggers:
  - "프로바이더 감사"
  - "프로바이더 정리"
  - "고아 프로바이더"
  - "선언 안 된 변수"
  - "audit providers"
  - "find unused providers"
  - "undeclared variables"
---

# Instructions

You are auditing Angular providers for quality issues.

## Pipeline

1. CALL detect_angular_implicit_globals
   - scope = INPUT
   - max_providers = 50
   - max_matches = 50
   → LABEL as "globals"

2. CALL get_provider_dependency_map
   - scope = INPUT
   → FOR EACH provider:
     - 0 widgets = ORPHANED (safe to delete)
     - 1 widget = PRIVATE (consider inlining)
     - 5+ widgets = SHARED (high blast radius)
     - 10+ widgets = CRITICAL (do not modify without regression test)

3. CALL search_portal_regex_matches
   - regex = "\\$rootScope|\\$window\\.location|document\\."
   - source_types = ["angular_provider"]
   - scope = INPUT
   - max_matches = 50
   → LABEL as "anti_patterns"

4. RETURN report:
   - Implicit globals: list with provider name, variable, line
   - Orphaned providers: list (deletion candidates)
   - Anti-patterns: list with location and fix suggestion
   - Risk summary: orphaned count, shared count, critical count

## ON ERROR

- 0 findings → clean codebase or wrong scope
- Too many findings → narrow with specific provider names

## DELEGATE hint

Delegatable. Return summary only.
