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
  - download_sources
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
| **Full / all / entire source** | "전체 받아", "full source", no specific type | **`download_app_sources`** (orchestrator) — the ONLY full-source tool |
| Portal only | "위젯만", "포탈 소스" | download_portal_sources |
| Specific family | "BR만", "SI만", "ACL만" | download_sources(families=[...]) |

> For "full/all source", use `download_app_sources` — NOT `download_portal_sources` (portal widgets/providers only) and NOT `download_sources` (specific families only). Those are partial.

## Pipeline

### Full App Download

> `scope` is REQUIRED — it's the app to dump (an instance has many apps; there is no "everything" scope). If the user said "전체/full source" but named no app, ASK which app (or x_ namespace) first. Do NOT fall back to download_portal_sources just because it needs no scope.

CALL download_app_sources
  - scope = INPUT_SCOPE   # required; ask the user if unknown
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

#### Re-syncing an already-downloaded scope (incremental)

If the scope was downloaded before (a `_manifest.json` / `_sync_meta.json` exists),
do NOT re-download everything. Pass `incremental=true` so only records changed since
the last sync (`sys_updated_on` watermark) are fetched — like `git pull`. Much faster
and avoids timeouts on large apps. Add `reconcile_deletions=true` to also get a warning
list (`deletion_candidates`) of records deleted on the instance (never auto-deleted).

```
CALL download_app_sources(scope=INPUT_SCOPE, incremental=true)            # changed only
CALL download_app_sources(scope=INPUT_SCOPE, incremental=true, reconcile_deletions=true)
```

Both `download_app_sources` and `download_portal_sources` support these flags. Run a full
(non-incremental) download periodically to stay fully in sync.

### Targeted Family Download

One tool, pick families (combine in a single call):

| Input | families= |
|-------|-----------|
| "SI" / "스크립트 인클루드" | `script_includes` |
| "BR" / "비즈니스 룰" / server scripts | `server_scripts` |
| "UI" / "UI 액션" | `ui` |
| "REST" / "API" | `api` |
| "ACL" / "보안" | `security` (acl_script_only=true by default) |
| "Fix" / "스케줄" / "관리" | `admin` |

```
CALL download_sources(scope=INPUT_SCOPE, families=["script_includes"])
CALL download_sources(scope=INPUT_SCOPE, families=["server_scripts", "ui"])   # combine
```

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
  sys_script_include/  ← download_sources(families=["script_includes"])
  sys_script/          ← download_sources(families=["server_scripts"]) (BR)
  sys_script_client/   ← download_sources(families=["server_scripts"])
  sys_ui_action/       ← download_sources(families=["ui"])
  sys_ws_operation/    ← download_sources(families=["api"])
  sys_security_acl/    ← download_sources(families=["security"])
  sys_script_fix/      ← download_sources(families=["admin"])
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
