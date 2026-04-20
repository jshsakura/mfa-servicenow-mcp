---
name: app-source-download
description: Download all server-side source code for a ServiceNow application scope
context_cost: high
safety_level: none
delegatable: true
required_input: scope
output: files
tools:
  - download_app_sources
  - download_portal_sources
  - download_script_includes
  - download_server_scripts
  - download_ui_components
  - download_api_sources
  - download_security_sources
  - download_admin_scripts
  - download_table_schema
triggers:
  - "앱 소스 다운로드"
  - "전체 소스 받아"
  - "앱 백업"
  - "소스 전체 내보내기"
  - "download app sources"
  - "export all sources"
  - "full app backup"
---

# Instructions

You are downloading all source code for a ServiceNow application scope to local files for offline review.

## Mode Selection

| Mode | When | Tools |
|------|------|-------|
| Full app | "전체 받아", no specific type | download_app_sources (orchestrator) |
| Portal only | "위젯만", "포탈 소스" | download_portal_sources |
| Specific group | "BR만", "SI만", "ACL만" | Individual download tool |

## Pipeline

### Full App Download

CALL download_app_sources
  - scope = INPUT_SCOPE
  - include_widget_sources = true
  - include_schema = true
  - auto_resolve_deps = true  # default; pulls cross-scope SI/widget/provider/ui_macro
  - max_records_per_type = 500

→ RETURN: summary with counts, `dep_summary` (cross-scope deps fetched), and output_root path

#### What auto_resolve_deps does (v1.8.21+)

After the in-scope download, the tool scans every `.js/.html/.xml` file and
fetches any referenced records not already in the bundle. Saved into the
same tree with `is_dependency: true` in `_metadata.json`. Covered types:

| Ref pattern | Resolves to |
|-------------|-------------|
| `new X()`, `gs.include('X')`, `new GlideAjax('X')` | sys_script_include |
| `<sp-widget id="X">`, `$sp.getWidget('X')` | sp_widget |
| `$inject=[...]`, `angular.module(..., [...])` | sp_angular_provider |
| `<g:X>`, `<g2:X>` Jelly (excl. builtins) | sys_ui_macro |

Set `auto_resolve_deps=false` to skip this pass if you only want in-scope records.

### Individual Group Download

IF "SI" or "스크립트 인클루드":
  CALL download_script_includes(scope=INPUT_SCOPE)

IF "BR" or "비즈니스 룰":
  CALL download_server_scripts(scope=INPUT_SCOPE)

IF "UI" or "UI 액션":
  CALL download_ui_components(scope=INPUT_SCOPE)

IF "REST" or "API":
  CALL download_api_sources(scope=INPUT_SCOPE)

IF "ACL" or "보안":
  CALL download_security_sources(scope=INPUT_SCOPE)

IF "Fix" or "스케줄" or "관리":
  CALL download_admin_scripts(scope=INPUT_SCOPE)

IF "스키마" or "테이블 정의":
  CALL download_table_schema(source_root=OUTPUT_ROOT)

### Post-Download

After any download, suggest:
  "audit_local_sources로 검수 리포트를 생성할 수 있습니다."

## Output Structure

```
temp/<instance>/<scope>/
  sp_widget/           ← download_portal_sources
  sp_angular_provider/ ← download_portal_sources
  sys_script_include/  ← download_script_includes
  sys_script/          ← download_server_scripts (BR)
  sys_client_script/   ← download_server_scripts
  sys_ui_action/       ← download_ui_components
  sys_ws_operation/    ← download_api_sources
  sys_security_acl/    ← download_security_sources
  sys_script_fix/      ← download_admin_scripts
  sys_ui_macro/        ← auto_resolve_deps (if any macros referenced)
  _schema/             ← download_table_schema
  _manifest.json       ← unified inventory

  # Cross-scope deps (if auto_resolve_deps=true):
  # records marked `"is_dependency": true` in their _metadata.json.
```

## ON ERROR

- 0 records → wrong scope name or empty scope
- Timeout → reduce max_records_per_type
- Permission → check ServiceNow ACLs for the querying user

## DELEGATE hint

Delegatable. Heavy I/O, minimal context needed. Results go to disk.
