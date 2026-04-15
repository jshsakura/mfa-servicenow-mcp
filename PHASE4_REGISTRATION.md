# Phase 4: Tool Registration & Package Configuration

## Goal
Phase 1-3에서 만든 모든 도구를 시스템에 등록하고 패키지에 할당한다.

## Prerequisites
- Phase 1 완료 (portal_crud_tools.py에 create_widget ~ create_ui_page)
- Phase 2 완료 (sync_tools.py 확장)
- Phase 3 완료 (portal_crud_tools.py에 create_page ~ scaffold_page 추가)

---

## File 1: `src/servicenow_mcp/tools/__init__.py`

### 추가할 import (기존 import 블록에)

기존 portal_tools import 뒤에 추가:

```python
from servicenow_mcp.tools.portal_crud_tools import (
    create_angular_provider,
    create_column,
    create_container,
    create_css_theme,
    create_header_footer,
    create_ng_template,
    create_page,
    create_row,
    create_ui_page,
    create_widget,
    scaffold_page,
    update_page,
)
```

### 추가할 __all__ 항목

기존 `__all__` 리스트의 portal 도구 섹션 뒤에:

```python
    # Portal CRUD tools (Phase 1-3)
    "create_widget",
    "create_angular_provider",
    "create_header_footer",
    "create_css_theme",
    "create_ng_template",
    "create_ui_page",
    "create_page",
    "update_page",
    "create_container",
    "create_row",
    "create_column",
    "scaffold_page",
```

---

## File 2: `src/servicenow_mcp/config/tool_packages.yaml`

### portal_developer 패키지에 추가

기존 `portal_developer` 섹션의 portal writes 부분에 추가:

```yaml
  # + Portal CRUD (Phase 1: Component Create)
  - create_widget
  - create_angular_provider
  - create_header_footer
  - create_css_theme
  - create_ng_template
  - create_ui_page
  # + Portal CRUD (Phase 3: Page/Layout)
  - create_page
  - update_page
  - create_container
  - create_row
  - create_column
  - scaffold_page
```

위치: `update_widget_instance` 다음, `create_script_include` 이전에 삽입.

### platform_developer 패키지에 추가

`platform_developer`에도 동일하게 추가 (portal_developer와 같은 도구 세트):

```yaml
  # + Portal CRUD
  - create_widget
  - create_angular_provider
  - create_header_footer
  - create_css_theme
  - create_ng_template
  - create_ui_page
  - create_page
  - update_page
  - create_container
  - create_row
  - create_column
  - scaffold_page
```

### full 패키지에 추가

`full` 패키지에도 동일하게 추가:

```yaml
  # + Portal CRUD
  - create_widget
  - create_angular_provider
  - create_header_footer
  - create_css_theme
  - create_ng_template
  - create_ui_page
  - create_page
  - update_page
  - create_container
  - create_row
  - create_column
  - scaffold_page
```

### service_desk 패키지: 추가하지 않음

service_desk는 read-only + incident writes만 포함. Portal CRUD 불필요.

---

## File 3: Verify `register_tool` decorator compatibility

모든 새 도구가 `@register_tool` 데코레이터를 올바르게 사용하는지 확인:

```python
# 확인할 패턴:
@register_tool(
    name="tool_name",           # 고유한 이름 (tool_packages.yaml과 일치해야 함)
    params=ParamModelClass,      # Pydantic BaseModel
    description="...",           # 도구 설명
    serialization="raw_dict",    # Dict 반환시 "raw_dict"
    return_type=dict,            # 반환 타입
)
```

### 전체 도구 이름 목록 (12개):

| # | Tool Name | Table | Phase |
|---|-----------|-------|-------|
| 1 | `create_widget` | sp_widget | 1 |
| 2 | `create_angular_provider` | sp_angular_provider | 1 |
| 3 | `create_header_footer` | sp_header_footer | 1 |
| 4 | `create_css_theme` | sp_css | 1 |
| 5 | `create_ng_template` | sp_ng_template | 1 |
| 6 | `create_ui_page` | sys_ui_page | 1 |
| 7 | `create_page` | sp_page | 3 |
| 8 | `update_page` | sp_page | 3 |
| 9 | `create_container` | sp_container | 3 |
| 10 | `create_row` | sp_row | 3 |
| 11 | `create_column` | sp_column | 3 |
| 12 | `scaffold_page` | sp_page + layout | 3 |

---

## Verification Steps

### Step 1: Import Test

```bash
cd /home/ubuntu/app/jupyterLab/notebooks/mfa-servicenow-mcp
python -c "from servicenow_mcp.tools.portal_crud_tools import create_widget, scaffold_page; print('OK')"
```

### Step 2: Tool Registration Test

```bash
python -c "
from servicenow_mcp.utils.registry import get_registered_tools
tools = get_registered_tools()
expected = [
    'create_widget', 'create_angular_provider', 'create_header_footer',
    'create_css_theme', 'create_ng_template', 'create_ui_page',
    'create_page', 'update_page', 'create_container', 'create_row',
    'create_column', 'scaffold_page',
]
for name in expected:
    assert name in tools, f'Missing tool: {name}'
print(f'All {len(expected)} tools registered OK')
"
```

### Step 3: Package Loading Test

```bash
python -c "
import yaml
from pathlib import Path
pkg_path = Path('src/servicenow_mcp/config/tool_packages.yaml')
with open(pkg_path) as f:
    packages = yaml.safe_load(f)
for pkg_name in ['portal_developer', 'platform_developer', 'full']:
    tools = packages[pkg_name]
    assert 'create_widget' in tools, f'{pkg_name} missing create_widget'
    assert 'scaffold_page' in tools, f'{pkg_name} missing scaffold_page'
    print(f'{pkg_name}: OK ({len(tools)} tools)')
"
```

### Step 4: PORTAL_COMPONENT_EDITABLE_FIELDS Test

```bash
python -c "
from servicenow_mcp.tools.portal_tools import PORTAL_COMPONENT_EDITABLE_FIELDS
expected_tables = ['sp_widget', 'sp_angular_provider', 'sys_script_include',
                   'sp_header_footer', 'sp_css', 'sp_ng_template', 'sys_ui_page']
for table in expected_tables:
    assert table in PORTAL_COMPONENT_EDITABLE_FIELDS, f'Missing table: {table}'
print(f'All {len(expected_tables)} tables in PORTAL_COMPONENT_EDITABLE_FIELDS')
"
```

### Step 5: Sync Tables Test

```bash
python -c "
from servicenow_mcp.tools.sync_tools import SUPPORTED_TABLES, TABLE_FILE_FIELD_MAP
expected = ['sp_widget', 'sp_angular_provider', 'sys_script_include',
            'sp_header_footer', 'sp_css', 'sp_ng_template', 'sys_ui_page']
for table in expected:
    assert table in SUPPORTED_TABLES, f'Missing from SUPPORTED_TABLES: {table}'
    assert table in TABLE_FILE_FIELD_MAP, f'Missing from TABLE_FILE_FIELD_MAP: {table}'
print(f'All {len(expected)} tables in sync config')
"
```

### Step 6: Full Test Suite

```bash
cd /home/ubuntu/app/jupyterLab/notebooks/mfa-servicenow-mcp
pytest -x -q
```

---

## Summary: All Modified/Created Files

| File | Action | Phase |
|------|--------|-------|
| `src/servicenow_mcp/tools/portal_crud_tools.py` | **NEW** | 1, 3 |
| `src/servicenow_mcp/tools/portal_tools.py` | MODIFY (2 changes) | 1 |
| `src/servicenow_mcp/tools/sync_tools.py` | MODIFY (4 changes) | 2 |
| `src/servicenow_mcp/tools/__init__.py` | MODIFY (add imports + __all__) | 4 |
| `src/servicenow_mcp/config/tool_packages.yaml` | MODIFY (3 packages) | 4 |

## End-to-End Workflow After All Phases

```
1. create_css_theme → CSS 테마 생성
2. create_header_footer → 헤더/푸터 생성
3. create_widget × N → 위젯들 생성
4. create_angular_provider → 공유 프로바이더 생성
5. scaffold_page → 페이지 + 레이아웃 + 위젯 배치 한번에
   OR
5a. create_page → 페이지 생성
5b. create_container → 컨테이너 생성
5c. create_row × N → 행 생성
5d. create_column × N → 열 생성
5e. create_widget_instance × N → 위젯 배치
6. download_app_sources → 로컬에 전체 다운로드
7. (로컬 편집기에서 수정)
8. diff_local_component → 변경사항 확인
9. update_remote_from_local → ServiceNow에 push
```
