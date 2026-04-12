---
name: portal-diagnosis
description: Full health check — anti-patterns, implicit globals, orphaned providers, performance flags
context_cost: high
safety_level: none
delegatable: true
required_input: scope or portal_id
output: report
tools:
  - list_portals
  - list_pages
  - search_portal_regex_matches
  - detect_angular_implicit_globals
  - get_provider_dependency_map
  - analyze_widget_performance
triggers:
  - "포탈 진단"
  - "포탈 건강 확인"
  - "문제 찾아줘"
  - "portal health check"
  - "find portal problems"
---

# Instructions

You are running a comprehensive portal health check. DELEGATE to sub-agent recommended due to high context cost.

## Pipeline

1. CALL list_portals(limit=10)
   - IF scope given → filter by scope
   - IF portal_id given → use directly

2. CALL search_portal_regex_matches
   - regex = "\\$rootScope\\.|document\\.getElementById|\\$window\\.location|innerHTML|eval\\("
   - scope = INPUT
   - source_types = ["widget", "angular_provider"]
   - include_widget_fields = ["script", "client_script", "template"]
   - max_widgets = 50
   - max_matches = 100
   → LABEL result as "anti_patterns"

3. CALL detect_angular_implicit_globals
   - scope = INPUT
   - max_providers = 50
   → LABEL result as "implicit_globals"

4. CALL get_provider_dependency_map
   - scope = INPUT
   → LABEL result as "provider_map"
   → COUNT providers with 0 widgets as "orphaned"
   → COUNT providers with 10+ widgets as "critical"

5. RETURN report:
   | Area | Count | Severity |
   |------|-------|----------|
   | Anti-patterns | {anti_patterns.findings_count} | high if >0 |
   | Implicit globals | {implicit_globals.findings_count} | medium |
   | Orphaned providers | {orphaned} | low |
   | Critical shared providers | {critical} | info |

6. FOR EACH anti-pattern finding, INCLUDE:
   - location, line, snippet, suggested fix

## ON ERROR

- "0 findings everywhere" → either clean portal or wrong scope. CALL list_portals to verify.
- Timeout on large scan → reduce max_widgets to 25

## DELEGATE hint

ALWAYS delegate this skill to sub-agent. Results are large. Return only the summary report to main context.
