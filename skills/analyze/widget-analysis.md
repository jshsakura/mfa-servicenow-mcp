---
name: widget-analysis
description: Analyze a widget's source, providers, routes, and performance in one pass
context_cost: medium
safety_level: none
delegatable: true
required_input: widget_id (sys_id, id, or name)
output: summary
tools:
  - get_widget_bundle
  - trace_portal_route_targets
  - analyze_widget_performance
triggers:
  - "위젯 분석"
  - "위젯 뭐하는 거야"
  - "의존성 보여줘"
  - "analyze widget"
  - "what does this widget do"
---

# Instructions

You are analyzing a Service Portal widget. Produce a complete dependency summary.

## Pipeline

1. CALL get_widget_bundle
   - widget_id = INPUT
   - include_providers = true
   - include_script = true
   - include_client_script = true
   - include_template = true
   - include_css = true

2. FROM result, EXTRACT:
   - Server script: what tables it queries (GlideRecord), what data it sets
   - Client script: what events it handles, what providers it injects
   - Template: what data bindings ({{c.data.*}}) and directives (ng-if, ng-repeat)
   - Providers: list names and their purpose

3. CALL trace_portal_route_targets
   - widget_ids = [INPUT]
   - include_linked_angular_providers = true
   - output_mode = "compact"

4. CALL analyze_widget_performance
   - widget_id = INPUT

5. RETURN summary:
   - Purpose (one sentence)
   - Server: tables queried, data properties set
   - Client: injected services, event handlers
   - Template: key UI sections
   - Providers: name → purpose
   - Routes: outbound navigation targets
   - Performance: flags (if any)

## ON ERROR

- "Widget not found" → CALL sn_query(table="sp_widget", query="nameLIKE{INPUT}", fields="sys_id,name,id", limit=5) → ASK user to pick
- Empty providers → normal for simple widgets, skip provider section
- 0 route targets → widget has no navigation, skip routes section

## DELEGATE hint

IF user asked about a single widget → run in main context.
IF user asked about multiple widgets or "all widgets in scope" → DELEGATE each to sub-agent, collect summaries.
