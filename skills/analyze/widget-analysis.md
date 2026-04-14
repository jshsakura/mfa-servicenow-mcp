---
name: widget-analysis
description: Analyze a widget's source, providers, routes, and performance — quick or deep mode
context_cost: medium
safety_level: none
delegatable: true
required_input: widget_id (sys_id, id, or name)
output: summary
tools:
  - get_widget_bundle
  - resolve_widget_chain
  - download_portal_sources
  - trace_portal_route_targets
  - analyze_widget_performance
  - diff_local_component
triggers:
  - "위젯 분석"
  - "위젯 뭐하는 거야"
  - "의존성 보여줘"
  - "analyze widget"
  - "what does this widget do"
  - "deep analysis"
  - "소스 분석"
---

# Instructions

You are analyzing a Service Portal widget. Choose the right depth based on the user's request.

## Mode Selection

| Signal | Mode | Approach |
|--------|------|----------|
| "뭐하는 위젯이야", simple question | **Quick** | In-memory, resolve_widget_chain depth=2 |
| "로직 분석", "왜 안돼", cross-component debug | **Deep** | Download to local, Read files, full trace |
| Multiple widgets, page-level analysis | **Deep** | Download scope, Read locally |

## Pipeline

Choose one of the two pipelines below based on the request scope and debugging depth.

### Quick Analysis Pipeline

Use when: single widget, overview needed, no cross-component debugging.

1. CALL resolve_widget_chain
   - widget_id = INPUT
   - depth = 2 (widget + providers)
   - include_fields = ["script", "client_script", "template"]

2. FROM result, EXTRACT:
   - Server script: tables queried (GlideRecord), data properties set
   - Client script: events, injected providers ($scope, spUtil, etc.)
   - Template: data bindings ({{c.data.*}}), directives (ng-if, ng-repeat)
   - Providers: name → what each does

3. CALL trace_portal_route_targets
   - widget_ids = [INPUT]

4. RETURN summary: purpose, data flow, routes, provider roles

### Deep Analysis Pipeline

Use when: cross-component logic, debugging, "왜 안 돼", multi-widget analysis.

1. CALL download_portal_sources
   - widget_ids = [INPUT] (or scope for multi-widget)
   - include_linked_angular_providers = true
   - include_linked_script_includes = true
   → Files saved to ./temp/{instance}/

2. READ local files to trace the full chain:
   - Widget server script → find GlideRecord calls, data.xxx assignments
   - Widget client script → find $scope.$on, c.server.get(), spUtil calls
   - Each provider script → find $http calls, shared state, service methods
   - Each script include → find GlideRecord, GlideAjax handler methods
   - Widget template → find ng-click, ng-repeat, data binding patterns

3. CALL analyze_widget_performance
   - widget_id = INPUT

4. RETURN deep report:
   - Data flow: which script sets data.X → which template reads c.data.X
   - Provider chain: widget injects Provider A → Provider A calls SI B
   - GlideRecord usage: which tables, which queries, read vs write
   - Client events: what triggers server calls, what updates UI
   - Performance flags (if any)
   - Cross-component issues found

## Freshness Check

If files already exist in ./temp/:
1. CALL diff_local_component(path=./temp/{instance}/)
2. If changes detected → re-download
3. If no changes → use cached files

## ON ERROR

- "Widget not found" → CALL sn_query(table="sp_widget", query="nameLIKE{INPUT}", fields="sys_id,name,id", limit=5) → ASK user to pick
- Empty providers → normal for simple widgets, skip provider section
- Download fails → fall back to Quick mode with resolve_widget_chain

## DELEGATE hint

IF user asked about a single widget → run in main context.
IF user asked about multiple widgets or "all widgets in scope" → DELEGATE each to sub-agent, collect summaries.
