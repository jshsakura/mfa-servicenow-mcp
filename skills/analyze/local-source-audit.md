---
name: local-source-audit
description: Analyze downloaded app sources locally — cross-references, dead code, execution order, HTML report
context_cost: low
safety_level: none
delegatable: true
required_input: source_root (path to downloaded sources)
output: report
tools:
  - audit_local_sources
triggers:
  - "로컬 검수"
  - "소스 분석"
  - "크로스 레퍼런스"
  - "데드 코드"
  - "검수 리포트"
  - "audit local sources"
  - "source review"
  - "dead code check"
  - "cross reference"
---

# Instructions

You are analyzing downloaded ServiceNow app sources on the local filesystem.
No API calls are made — everything is read from local files.

## Prerequisites

Sources must be downloaded first via:
- download_app_sources (full app)
- download_portal_sources + individual download tools (selective)

## Pipeline

1. CALL audit_local_sources
   - source_root = INPUT_PATH (e.g. temp/<instance>/<scope>)

2. FROM result, EXTRACT:
   - report_path → HTML report file location
   - summary.orphan_count → dead code count
   - summary.schema_issue_count → schema validation issues
   - summary.cross_reference_count → total reference links

3. RETURN:
   - HTML report path (user can open in browser)
   - Key findings summary:
     - Orphan sources (unreferenced Script Includes, unused Widgets)
     - Schema issues (tables referenced but not in schema)
     - Execution order conflicts (overlapping BR order numbers)
     - Cross-reference density

## Generated Files

```
<source_root>/
  _audit_report.html       ← Self-contained HTML report
  _source_index.json       ← Flat index of all sources
  _cross_references.json   ← Outgoing + incoming reference graph
  _orphans.json            ← Dead code candidates
  _execution_order.json    ← Per-table BR/CS/ACL execution map
  _schema_issues.json      ← Table validation problems (if any)
```

## How LLM Should Use the Results

1. Start with _audit_report.html for visual overview
2. Read _orphans.json to find dead code candidates
3. For specific investigation, use _cross_references.json to trace dependencies
4. When reviewing a specific source, read the actual .js file from the source directory
5. Cross-check field usage against _schema/ directory

## ON ERROR

- "No source records found" → wrong source_root path or sources not downloaded yet
- Empty orphans → all sources are referenced (good sign)
- Schema issues → run download_table_schema to fetch missing schemas

## DELEGATE hint

Delegatable. Pure local I/O, fast execution, no API needed.
