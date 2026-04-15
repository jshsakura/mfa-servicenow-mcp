# Phase 2: Sync (Diff/Push) Extension for New Tables

## Goal
Phase 1에서 추가한 테이블들(sp_header_footer, sp_css, sp_ng_template, sys_ui_page)에 대해
로컬 파일 수정 후 diff 확인과 push(업로드)를 가능하게 한다.

## Prerequisites
- Phase 1 완료 (PORTAL_COMPONENT_EDITABLE_FIELDS 확장됨)

## Modify: `src/servicenow_mcp/tools/sync_tools.py`

### Change 1: TABLE_FILE_FIELD_MAP 추가 (line ~33, WIDGET_FILE_FIELD_MAP 근처)

기존 `WIDGET_FILE_FIELD_MAP`은 하위 호환을 위해 유지하고, 새 dict를 추가:

```python
# Existing - keep for backward compatibility
WIDGET_FILE_FIELD_MAP: Dict[str, str] = {
    "template.html": "template",
    "script.js": "script",
    "client_script.js": "client_script",
    "link.js": "link",
    "css.scss": "css",
}

# NEW: Per-table file-to-field mappings
# Tables with multiple source fields use folder structure (like sp_widget)
# Tables with single source field use single-file structure (like sp_angular_provider)
TABLE_FILE_FIELD_MAP: Dict[str, Dict[str, str]] = {
    "sp_widget": WIDGET_FILE_FIELD_MAP,
    "sp_angular_provider": {".script.js": "script"},       # single file: <name>.script.js
    "sys_script_include": {".script.js": "script"},         # single file: <name>.script.js
    "sp_header_footer": {                                   # folder: <name>/template.html, css.scss
        "template.html": "template",
        "css.scss": "css",
    },
    "sp_css": {".css.scss": "css"},                         # single file: <name>.css.scss
    "sp_ng_template": {".template.html": "template"},       # single file: <name>.template.html
    "sys_ui_page": {                                        # folder: <name>/html.html, etc.
        "html.html": "html",
        "client_script.js": "client_script",
        "processing_script.js": "processing_script",
    },
}

# Tables that use folder structure (multiple files per record)
FOLDER_TABLES: Set[str] = {"sp_widget", "sp_header_footer", "sys_ui_page"}

# Tables that use single-file structure
SINGLE_FILE_TABLES: Set[str] = {"sp_angular_provider", "sys_script_include", "sp_css", "sp_ng_template"}
```

### Change 2: SUPPORTED_TABLES 확장 (line ~41)

**Before:**
```python
SUPPORTED_TABLES: Set[str] = {"sp_widget", "sp_angular_provider", "sys_script_include"}
```

**After:**
```python
SUPPORTED_TABLES: Set[str] = {
    "sp_widget", "sp_angular_provider", "sys_script_include",
    "sp_header_footer", "sp_css", "sp_ng_template", "sys_ui_page",
}
```

### Change 3: _resolve_local_path() 리팩터링 (line ~166)

기존 하드코딩된 로직을 TABLE_FILE_FIELD_MAP 기반으로 변경.

현재 구조:
```
_resolve_local_path()
  ├── Case 1: path.is_dir() → sp_widget only (hardcoded)
  ├── Case 2: grandparent.name == "sp_widget" → widget file
  └── Case 3: parent.name in ("sp_angular_provider", "sys_script_include") → single file
```

변경 후 구조:
```
_resolve_local_path()
  ├── Case 1: path.is_dir() → any FOLDER_TABLE (sp_widget, sp_header_footer, sys_ui_page)
  ├── Case 2: grandparent.name in FOLDER_TABLES → folder-based file
  └── Case 3: parent.name in SINGLE_FILE_TABLES → single file
```

**전체 교체할 함수:**

```python
def _resolve_local_path(path: Path) -> _ResolvedComponent:
    """Resolve a local file or directory to its ServiceNow component identity.

    Folder-based tables (sp_widget, sp_header_footer, sys_ui_page):
      .../sp_widget/<folder>/script.js          -> (sp_widget, script)
      .../sp_header_footer/<folder>/template.html -> (sp_header_footer, template)
      .../sys_ui_page/<folder>/html.html        -> (sys_ui_page, html)

    Single-file tables (sp_angular_provider, sys_script_include, sp_css, sp_ng_template):
      .../sp_angular_provider/<name>.script.js   -> (sp_angular_provider, script)
      .../sp_css/<name>.css.scss                 -> (sp_css, css)
      .../sp_ng_template/<name>.template.html    -> (sp_ng_template, template)
    """
    path = path.expanduser().resolve()

    # Case 1: Directory → folder-based table
    if path.is_dir():
        table_dir = path.parent
        table_name = table_dir.name
        if table_name not in FOLDER_TABLES:
            raise ValueError(
                f"Directory push is only supported for folder-based tables "
                f"({', '.join(sorted(FOLDER_TABLES))}). Got: {table_name}"
            )
        folder_name = path.name
        map_data = _read_map_json(table_dir)
        sys_id = map_data.get(folder_name)
        if not sys_id:
            raise ValueError(
                f"Component '{folder_name}' not found in {table_dir / '_map.json'}. "
                f"Re-download sources first."
            )
        file_field_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
        fields: Dict[str, Path] = {}
        for filename, field_name in file_field_map.items():
            if filename.startswith("."):
                continue  # skip single-file patterns
            fpath = path / filename
            if fpath.exists():
                fields[field_name] = fpath
        if not fields:
            raise ValueError(f"No editable source files found in {path}")
        scope_root = table_dir.parent
        settings = _find_settings_json(scope_root)
        return _ResolvedComponent(
            table=table_name,
            sys_id=sys_id,
            name=folder_name,
            fields=fields,
            scope_root=scope_root,
            instance_url=settings.get("url", ""),
        )

    # Case 2: File
    if not path.is_file():
        raise ValueError(f"Path does not exist: {path}")

    parent = path.parent
    grandparent = parent.parent

    # Case 2a: File inside a folder-based table directory
    #   e.g. .../sp_widget/<folder>/script.js
    #   e.g. .../sp_header_footer/<folder>/template.html
    if grandparent.name in FOLDER_TABLES:
        table_name = grandparent.name
        folder_name = parent.name
        table_dir = grandparent
        filename = path.name
        file_field_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
        field_name = file_field_map.get(filename)
        if not field_name:
            supported = ", ".join(
                k for k in sorted(file_field_map) if not k.startswith(".")
            )
            raise ValueError(
                f"Unknown file '{filename}' for {table_name}. Supported: {supported}"
            )
        map_data = _read_map_json(table_dir)
        sys_id = map_data.get(folder_name)
        if not sys_id:
            raise ValueError(
                f"Component '{folder_name}' not found in {table_dir / '_map.json'}"
            )
        scope_root = table_dir.parent
        settings = _find_settings_json(scope_root)
        return _ResolvedComponent(
            table=table_name,
            sys_id=sys_id,
            name=folder_name,
            fields={field_name: path},
            scope_root=scope_root,
            instance_url=settings.get("url", ""),
        )

    # Case 2b: Single file in a single-file table directory
    #   e.g. .../sp_angular_provider/<name>.script.js
    #   e.g. .../sp_css/<name>.css.scss
    if parent.name in SINGLE_FILE_TABLES:
        table_name = parent.name
        table_dir = parent
        stem = path.name

        # Find matching suffix pattern in TABLE_FILE_FIELD_MAP
        file_field_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
        matched_field = None
        component_name = None
        for suffix_pattern, field_name in file_field_map.items():
            if suffix_pattern.startswith(".") and stem.endswith(suffix_pattern):
                matched_field = field_name
                component_name = stem[: -len(suffix_pattern)]
                break

        if not matched_field or not component_name:
            raise ValueError(
                f"Cannot parse filename '{stem}' for table {table_name}. "
                f"Expected suffix: {', '.join(file_field_map.keys())}"
            )

        map_data = _read_map_json(table_dir)
        sys_id = _reverse_lookup_map(map_data, component_name)
        if not sys_id:
            raise ValueError(
                f"Component '{component_name}' not found in {table_dir / '_map.json'}"
            )
        original_name = _reverse_lookup_name(map_data, component_name)
        scope_root = table_dir.parent
        settings = _find_settings_json(scope_root)
        return _ResolvedComponent(
            table=table_name,
            sys_id=sys_id,
            name=original_name or component_name,
            fields={matched_field: path},
            scope_root=scope_root,
            instance_url=settings.get("url", ""),
        )

    supported_tables = sorted(FOLDER_TABLES | SINGLE_FILE_TABLES)
    raise ValueError(
        f"Cannot resolve '{path}' to a ServiceNow component. "
        f"Expected path under one of: {', '.join(supported_tables)}"
    )
```

### Change 4: _scan_download_root() 파일 탐색 로직 확장 (line ~362)

현재 `_scan_download_root` 내부의 per-component 파일 탐색 (line ~384):

**Before:**
```python
if table_name == "sp_widget":
    folder = table_dir / _safe_name(name)
    local_files = [
        str(folder / fn) for fn in WIDGET_FILE_FIELD_MAP if (folder / fn).exists()
    ]
else:
    safe = _safe_name(name)
    fpath = table_dir / f"{safe}.script.js"
    local_files = [str(fpath)] if fpath.exists() else []
```

**After:**
```python
if table_name in FOLDER_TABLES:
    folder = table_dir / _safe_name(name)
    file_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
    local_files = [
        str(folder / fn)
        for fn in file_map
        if not fn.startswith(".") and (folder / fn).exists()
    ]
else:
    safe = _safe_name(name)
    file_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
    local_files = []
    for suffix_pattern in file_map:
        if suffix_pattern.startswith("."):
            fpath = table_dir / f"{safe}{suffix_pattern}"
            if fpath.exists():
                local_files.append(str(fpath))
```

---

## Download Flow Integration

`source_tools.py`의 `_download_source_types()` (line ~1557)는 이미 모든 SOURCE_CONFIG 테이블을 지원합니다.
`download_app_sources` 도구로 sp_header_footer, sp_css, sp_ng_template, sys_ui_page를 다운로드하면
`{scope}/{table}/{safe_name}/` 또는 `{scope}/{table}/{safe_name}/` 폴더에 파일이 생깁니다.

**그러나** source_tools.py의 다운로드 디렉토리 구조와 sync_tools.py의 기대 구조가 맞아야 합니다.

### source_tools.py 다운로드 구조 (기존):
```
{scope}/
  {table}/
    {safe_name}/
      _metadata.json
      {source_field}.{ext}     # e.g. template.html, css.scss, script.js
    _map.json                   # {safe_name: sys_id}
    _sync_meta.json             # {safe_name: {sys_id, sys_updated_on, downloaded_at}}
```

이 구조는 folder-based 테이블에 완벽히 맞습니다. single-file 테이블도 폴더 안에 파일이 하나만 있는 구조입니다.

### 주의사항: portal_tools.py의 download_portal_sources vs source_tools.py의 download_app_sources

- `download_portal_sources` (portal_tools.py): sp_widget 전용 다운로드 — 위젯 폴더에 template.html, script.js 등을 직접 생성
- `download_app_sources` (source_tools.py): 범용 다운로드 — `{safe_name}/{source_field}.{ext}` 구조

**sp_header_footer, sp_css 등은 download_app_sources로 다운로드하되, sync_tools.py가 이 구조를 해석할 수 있어야 합니다.**

source_tools.py의 `_FIELD_EXTENSIONS` (다운로드시 파일 확장자):
```python
_FIELD_EXTENSIONS: Dict[str, str] = {
    "script": ".js",
    "client_script": ".js",
    "processing_script": ".js",
    "template": ".html",
    "html": ".html",
    "css": ".scss",
    "xml": ".xml",
    "payload": ".xml",
    "operation_script": ".js",
    "message_html": ".html",
    "message_text": ".txt",
    "link": ".js",
}
```

source_tools.py가 다운로드할 때 `{source_field}{ext}` 형식으로 파일을 생성합니다.
예: `template.html`, `css.scss`, `html.html`, `client_script.js`, `processing_script.js`

이것은 `TABLE_FILE_FIELD_MAP`의 folder-based 테이블 매핑과 일치합니다:
- sp_header_footer: `template.html` → template, `css.scss` → css  ✓
- sys_ui_page: `html.html` → html, `client_script.js` → client_script, `processing_script.js` → processing_script  ✓

**single-file 테이블(sp_css, sp_ng_template)은 source_tools.py가 폴더를 만들지만, sync_tools.py는 단일 파일을 기대합니다.**

이 불일치를 해결하려면, `_resolve_local_path`에 **폴백 로직** 추가:

```python
# In Case 2b, before raising "Cannot resolve" error:
# Fallback: check if path is inside a folder under a supported table
#   e.g. .../sp_css/<folder>/css.scss  (download_app_sources structure)
if parent.parent.name in SUPPORTED_TABLES:
    table_name = parent.parent.name
    table_dir = parent.parent
    folder_name = parent.name
    filename = path.name
    # Try to match as folder-based even for normally single-file tables
    file_field_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
    # Check non-dot patterns (folder files)
    for pattern, field_name in file_field_map.items():
        if not pattern.startswith(".") and filename == pattern:
            map_data = _read_map_json(table_dir)
            sys_id = _reverse_lookup_map(map_data, folder_name)
            if sys_id:
                original_name = _reverse_lookup_name(map_data, folder_name)
                scope_root = table_dir.parent
                settings = _find_settings_json(scope_root)
                return _ResolvedComponent(
                    table=table_name,
                    sys_id=sys_id,
                    name=original_name or folder_name,
                    fields={field_name: path},
                    scope_root=scope_root,
                    instance_url=settings.get("url", ""),
                )
    # Also check dot-suffix patterns for single-file mapping
    for suffix_pattern, field_name in file_field_map.items():
        if suffix_pattern.startswith("."):
            expected_filename = f"{field_name}{_infer_ext(suffix_pattern)}"
            if filename == expected_filename or filename == f"{field_name}{suffix_pattern.lstrip('.')}":
                # ... same resolution logic
```

**더 간단한 접근**: single-file 테이블도 `download_app_sources`가 폴더 구조로 내리니까,
`FOLDER_TABLES`에 전부 포함시키고 단일 파일 패턴은 보조용으로만 유지:

```python
# Revised: ALL tables use folder structure from download_app_sources
FOLDER_TABLES: Set[str] = {
    "sp_widget", "sp_header_footer", "sys_ui_page",
    "sp_css", "sp_ng_template",
    "sp_angular_provider", "sys_script_include",
}

# Single-file patterns are also supported for manual file placement
SINGLE_FILE_SUFFIX: Dict[str, Dict[str, str]] = {
    "sp_angular_provider": {".script.js": "script"},
    "sys_script_include": {".script.js": "script"},
    "sp_css": {".css.scss": "css"},
    "sp_ng_template": {".template.html": "template"},
}
```

그리고 `_resolve_local_path`에서:
1. 먼저 폴더 기반으로 시도 (모든 테이블)
2. 실패하면 single-file suffix로 폴백 (4개 테이블만)

---

## Validation Checklist

- [ ] `SUPPORTED_TABLES`에 7개 테이블 포함
- [ ] `TABLE_FILE_FIELD_MAP`에 7개 테이블 매핑 존재
- [ ] 기존 sp_widget push 동작 유지 (regression test)
- [ ] 기존 sp_angular_provider push 동작 유지
- [ ] 기존 sys_script_include push 동작 유지
- [ ] sp_header_footer 폴더에서 diff_local_component 동작
- [ ] sp_header_footer 폴더에서 update_remote_from_local 동작
- [ ] sp_css 파일에서 diff/push 동작
- [ ] sys_ui_page 폴더에서 diff/push 동작
- [ ] download_app_sources로 받은 구조와 sync가 호환되는지 확인
- [ ] _scan_download_root()가 새 테이블을 스캔하는지 확인
