# Phase 3: Page & Layout CRUD + Scaffold

## Goal
신규 포탈 페이지 생성, 레이아웃(Container/Row/Column) 구성, 위젯 배치까지
한번에 처리할 수 있는 도구 세트를 만든다.

## Prerequisites
- Phase 1 완료 (portal_crud_tools.py 존재, _create_record 헬퍼 사용 가능)
- Phase 2 완료 (SUPPORTED_TABLES 확장됨)

## ServiceNow Page Layout 데이터 모델

```
sp_page (페이지)
  └── sp_container (컨테이너) - order, width, css_class, background_color
       └── sp_row (행) - order, css_class
            └── sp_column (열) - order, size(Bootstrap 1-12), css_class
                 └── sp_instance (위젯 인스턴스) - sp_widget, order, widget_parameters, css
```

테이블 상수 (portal_management_tools.py에서 이미 정의됨):
```python
PAGE_TABLE = "sp_page"
CONTAINER_TABLE = "sp_container"
ROW_TABLE = "sp_row"
COLUMN_TABLE = "sp_column"
INSTANCE_TABLE = "sp_instance"
```

---

## Add to: `src/servicenow_mcp/tools/portal_crud_tools.py`

Phase 1에서 생성한 파일에 이어서 추가합니다.

### Tool 7: create_page

```python
class CreatePageParams(BaseModel):
    """Parameters for creating a new Service Portal page."""
    id: str = Field(
        ...,
        description="Page URL path (e.g. 'my_landing_page'). Must be unique within the portal.",
    )
    title: str = Field(..., description="Page title displayed in browser tab and breadcrumbs")
    description: Optional[str] = Field(default=None, description="Page description")
    css: Optional[str] = Field(default=None, description="Page-level custom CSS")
    internal: bool = Field(default=False, description="Mark as internal (hidden from navigation)")
    public: bool = Field(default=False, description="Allow unauthenticated access")
    draft: bool = Field(default=False, description="Mark as draft (not published)")
    category: Optional[str] = Field(
        default=None, description="Category sys_id (sp_category)"
    )
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")


@register_tool(
    name="create_page",
    params=CreatePageParams,
    description="Create a new Service Portal page. Returns sys_id for subsequent layout creation.",
    serialization="raw_dict",
    return_type=dict,
)
def create_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreatePageParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "id": params.id,
        "title": params.title,
    }
    if params.description:
        body["description"] = params.description
    if params.css:
        body["css"] = params.css
    if params.internal:
        body["internal"] = "true"
    if params.public:
        body["public"] = "true"
    if params.draft:
        body["draft"] = "true"
    if params.category:
        body["category"] = params.category
    if params.scope:
        body["sys_scope"] = params.scope

    result = _create_record(config, auth_manager, "sp_page", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created page: {record.get('title')} (/{record.get('id')})",
        "sys_id": record.get("sys_id"),
        "id": record.get("id"),
        "title": record.get("title"),
        "hint": "Use create_container to add layout containers to this page.",
    }
```

### Tool 8: update_page

```python
class UpdatePageParams(BaseModel):
    sys_id: str = Field(..., description="Page sys_id")
    title: Optional[str] = Field(default=None, description="New title")
    description: Optional[str] = Field(default=None, description="New description")
    css: Optional[str] = Field(default=None, description="New page-level CSS")
    internal: Optional[bool] = Field(default=None, description="Toggle internal flag")
    public: Optional[bool] = Field(default=None, description="Toggle public access")
    draft: Optional[bool] = Field(default=None, description="Toggle draft status")


@register_tool(
    name="update_page",
    params=UpdatePageParams,
    description="Update a Service Portal page's title, description, CSS, or visibility flags.",
    serialization="raw_dict",
    return_type=dict,
)
def update_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: UpdatePageParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if params.title is not None:
        body["title"] = params.title
    if params.description is not None:
        body["description"] = params.description
    if params.css is not None:
        body["css"] = params.css
    if params.internal is not None:
        body["internal"] = str(params.internal).lower()
    if params.public is not None:
        body["public"] = str(params.public).lower()
    if params.draft is not None:
        body["draft"] = str(params.draft).lower()

    if not body:
        return {"success": False, "message": "No fields to update"}

    url = f"{config.instance_url}/api/now/table/sp_page/{params.sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request(
            "PATCH", url, json=body, headers=headers, timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        invalidate_query_cache(table="sp_page")
        record = data.get("result", {})
        return {
            "success": True,
            "message": f"Updated page: {record.get('title')}",
            "sys_id": params.sys_id,
        }
    except Exception as e:
        return {"success": False, "message": f"Error updating page: {e}"}
```

### Tool 9: create_container

```python
class CreateContainerParams(BaseModel):
    sp_page: str = Field(..., description="Page sys_id to add container to")
    order: int = Field(default=100, description="Display order (lower = higher on page)")
    width: Optional[str] = Field(
        default=None,
        description="Container width. Options: 'container' (fixed), 'container-fluid' (full-width). Default: container.",
    )
    css_class: Optional[str] = Field(default=None, description="Additional CSS classes")
    background_color: Optional[str] = Field(
        default=None, description="Background color (hex or CSS color name)"
    )


@register_tool(
    name="create_container",
    params=CreateContainerParams,
    description="Add a layout container to a portal page. Containers hold rows.",
    serialization="raw_dict",
    return_type=dict,
)
def create_container(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateContainerParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "sp_page": params.sp_page,
        "order": str(params.order),
    }
    if params.width:
        body["width"] = params.width
    if params.css_class:
        body["css_class"] = params.css_class
    if params.background_color:
        body["background_color"] = params.background_color

    result = _create_record(config, auth_manager, "sp_container", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": "Created container",
        "sys_id": record.get("sys_id"),
        "page": params.sp_page,
        "order": params.order,
        "hint": "Use create_row to add rows to this container.",
    }
```

### Tool 10: create_row

```python
class CreateRowParams(BaseModel):
    sp_container: str = Field(..., description="Container sys_id to add row to")
    order: int = Field(default=100, description="Display order within the container")
    css_class: Optional[str] = Field(default=None, description="Additional CSS classes (e.g. 'row-eq-height')")


@register_tool(
    name="create_row",
    params=CreateRowParams,
    description="Add a row to a layout container. Rows hold columns.",
    serialization="raw_dict",
    return_type=dict,
)
def create_row(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateRowParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "sp_container": params.sp_container,
        "order": str(params.order),
    }
    if params.css_class:
        body["css_class"] = params.css_class

    result = _create_record(config, auth_manager, "sp_row", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": "Created row",
        "sys_id": record.get("sys_id"),
        "container": params.sp_container,
        "hint": "Use create_column to add columns to this row.",
    }
```

### Tool 11: create_column

```python
class CreateColumnParams(BaseModel):
    sp_row: str = Field(..., description="Row sys_id to add column to")
    order: int = Field(default=100, description="Display order within the row (left to right)")
    size: int = Field(
        default=12,
        description="Bootstrap grid column size (1-12). Total of all columns in a row should be 12.",
    )
    css_class: Optional[str] = Field(default=None, description="Additional CSS classes")


@register_tool(
    name="create_column",
    params=CreateColumnParams,
    description="Add a column to a row. Columns use Bootstrap grid (size 1-12). Widgets are placed in columns.",
    serialization="raw_dict",
    return_type=dict,
)
def create_column(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateColumnParams,
) -> Dict[str, Any]:
    if params.size < 1 or params.size > 12:
        return {"success": False, "message": "Column size must be between 1 and 12"}

    body: Dict[str, Any] = {
        "sp_row": params.sp_row,
        "order": str(params.order),
        "size": str(params.size),
    }
    if params.css_class:
        body["css_class"] = params.css_class

    result = _create_record(config, auth_manager, "sp_column", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created column (size={params.size})",
        "sys_id": record.get("sys_id"),
        "row": params.sp_row,
        "size": params.size,
        "hint": "Use create_widget_instance to place widgets in this column.",
    }
```

### Tool 12: scaffold_page — 페이지 일괄 생성

```python
class ScaffoldRowDef(BaseModel):
    """Row definition within scaffold layout."""
    columns: List[int] = Field(
        ...,
        description="List of Bootstrap column sizes. Must sum to 12. e.g. [6, 6] or [4, 4, 4] or [12]",
    )
    widgets: Optional[List[Optional[str]]] = Field(
        default=None,
        description="Widget sys_ids to place in each column. Use null for empty columns. Length must match columns.",
    )
    widget_params: Optional[List[Optional[str]]] = Field(
        default=None,
        description="JSON widget_parameters for each column's widget. Length must match columns.",
    )
    css_class: Optional[str] = Field(default=None, description="Row CSS class")


class ScaffoldPageParams(BaseModel):
    """Parameters for scaffolding a complete page with layout and widgets."""
    portal_id: Optional[str] = Field(
        default=None,
        description="Portal sys_id. Optional — page will be created regardless, but useful for validation.",
    )
    page_id: str = Field(..., description="Page URL path (e.g. 'landing_v2')")
    title: str = Field(..., description="Page title")
    description: Optional[str] = Field(default=None, description="Page description")
    css: Optional[str] = Field(default=None, description="Page-level CSS")
    public: bool = Field(default=False, description="Allow unauthenticated access")
    container_width: str = Field(
        default="container",
        description="Container width: 'container' (fixed) or 'container-fluid' (full-width)",
    )
    rows: List[ScaffoldRowDef] = Field(
        ...,
        description="List of row definitions. Each row has column sizes and optional widget placements.",
    )
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")


@register_tool(
    name="scaffold_page",
    params=ScaffoldPageParams,
    description="Create a complete portal page with layout (container/rows/columns) and widget placements in one call.",
    serialization="raw_dict",
    return_type=dict,
)
def scaffold_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ScaffoldPageParams,
) -> Dict[str, Any]:
    """Create page → container → rows → columns → widget instances in sequence."""
    created: Dict[str, Any] = {"page": None, "container": None, "rows": [], "columns": [], "instances": []}
    errors: List[str] = []

    # Validate row definitions
    for i, row in enumerate(params.rows):
        col_sum = sum(row.columns)
        if col_sum != 12:
            return {
                "success": False,
                "message": f"Row {i}: column sizes sum to {col_sum}, must be 12. Columns: {row.columns}",
            }
        if row.widgets and len(row.widgets) != len(row.columns):
            return {
                "success": False,
                "message": f"Row {i}: widgets list length ({len(row.widgets)}) must match columns ({len(row.columns)})",
            }
        if row.widget_params and len(row.widget_params) != len(row.columns):
            return {
                "success": False,
                "message": f"Row {i}: widget_params length ({len(row.widget_params)}) must match columns ({len(row.columns)})",
            }

    # 1. Create page
    page_body: Dict[str, Any] = {"id": params.page_id, "title": params.title}
    if params.description:
        page_body["description"] = params.description
    if params.css:
        page_body["css"] = params.css
    if params.public:
        page_body["public"] = "true"
    if params.scope:
        page_body["sys_scope"] = params.scope

    page_result = _create_record(config, auth_manager, "sp_page", page_body)
    if not page_result["success"]:
        return {"success": False, "message": f"Failed to create page: {page_result['message']}", "created": created}
    page_sys_id = page_result["result"].get("sys_id")
    created["page"] = {"sys_id": page_sys_id, "id": params.page_id, "title": params.title}

    # 2. Create container
    container_body = {
        "sp_page": page_sys_id,
        "order": "100",
        "width": params.container_width,
    }
    container_result = _create_record(config, auth_manager, "sp_container", container_body)
    if not container_result["success"]:
        errors.append(f"Container creation failed: {container_result['message']}")
        return {"success": False, "message": "Failed after page creation", "created": created, "errors": errors}
    container_sys_id = container_result["result"].get("sys_id")
    created["container"] = {"sys_id": container_sys_id}

    # 3. Create rows, columns, and widget instances
    for row_idx, row_def in enumerate(params.rows):
        row_order = (row_idx + 1) * 100
        row_body = {
            "sp_container": container_sys_id,
            "order": str(row_order),
        }
        if row_def.css_class:
            row_body["css_class"] = row_def.css_class

        row_result = _create_record(config, auth_manager, "sp_row", row_body)
        if not row_result["success"]:
            errors.append(f"Row {row_idx} creation failed: {row_result['message']}")
            continue
        row_sys_id = row_result["result"].get("sys_id")
        created["rows"].append({"sys_id": row_sys_id, "order": row_order})

        for col_idx, col_size in enumerate(row_def.columns):
            col_order = (col_idx + 1) * 100
            col_body = {
                "sp_row": row_sys_id,
                "order": str(col_order),
                "size": str(col_size),
            }
            col_result = _create_record(config, auth_manager, "sp_column", col_body)
            if not col_result["success"]:
                errors.append(f"Row {row_idx}, Col {col_idx} creation failed: {col_result['message']}")
                continue
            col_sys_id = col_result["result"].get("sys_id")
            created["columns"].append({"sys_id": col_sys_id, "row": row_sys_id, "size": col_size})

            # Place widget if specified
            widget_id = (row_def.widgets[col_idx] if row_def.widgets and col_idx < len(row_def.widgets) else None)
            if widget_id:
                inst_body: Dict[str, Any] = {
                    "sp_widget": widget_id,
                    "sp_column": col_sys_id,
                    "order": "0",
                }
                widget_param = (
                    row_def.widget_params[col_idx]
                    if row_def.widget_params and col_idx < len(row_def.widget_params)
                    else None
                )
                if widget_param:
                    inst_body["widget_parameters"] = widget_param

                inst_result = _create_record(config, auth_manager, "sp_instance", inst_body)
                if not inst_result["success"]:
                    errors.append(f"Widget instance at row {row_idx}, col {col_idx} failed: {inst_result['message']}")
                else:
                    created["instances"].append({
                        "sys_id": inst_result["result"].get("sys_id"),
                        "widget": widget_id,
                        "column": col_sys_id,
                    })

    return {
        "success": len(errors) == 0,
        "message": f"Page scaffolded: /{params.page_id}" + (f" with {len(errors)} errors" if errors else ""),
        "created": created,
        "errors": errors if errors else None,
        "summary": {
            "page": params.page_id,
            "containers": 1,
            "rows": len(created["rows"]),
            "columns": len(created["columns"]),
            "widget_instances": len(created["instances"]),
        },
    }
```

---

## scaffold_page 사용 예시

### 예시 1: 2-column 랜딩 페이지
```json
{
  "page_id": "landing_v2",
  "title": "Landing Page V2",
  "container_width": "container-fluid",
  "rows": [
    {
      "columns": [12],
      "widgets": ["hero_banner_widget_sys_id"],
      "css_class": "hero-section"
    },
    {
      "columns": [6, 6],
      "widgets": ["feature_list_sys_id", "contact_form_sys_id"]
    },
    {
      "columns": [4, 4, 4],
      "widgets": ["card_widget_1", "card_widget_2", "card_widget_3"]
    },
    {
      "columns": [12],
      "widgets": ["footer_content_sys_id"]
    }
  ]
}
```

### 예시 2: ESC 포탈 페이지 (sidebar + main)
```json
{
  "page_id": "esc_my_requests",
  "title": "My Requests",
  "public": false,
  "rows": [
    {
      "columns": [3, 9],
      "widgets": ["sidebar_nav_sys_id", "request_list_sys_id"]
    }
  ]
}
```

---

## Existing Tool Reference: create_widget_instance

이미 `portal_management_tools.py`에 구현되어 있으므로 Phase 3에서 새로 만들 필요 없음:
- Tool name: `create_widget_instance`
- Params: `sp_widget`, `sp_column`, `order`, `widget_parameters`, `css`
- Package: `portal_developer`, `full`

scaffold_page는 이 도구를 직접 호출하지 않고 `_create_record`를 사용합니다
(같은 Table API POST이므로 동일한 결과).

---

## Validation Checklist

- [ ] create_page: id 필수, title 필수, sys_id 반환
- [ ] update_page: PATCH 동작 확인
- [ ] create_container: sp_page 참조 정상
- [ ] create_row: sp_container 참조 정상
- [ ] create_column: sp_row 참조 정상, size 1-12 검증
- [ ] scaffold_page: 전체 플로우 (page → container → row → column → instance)
- [ ] scaffold_page: 칼럼 합계 12 검증
- [ ] scaffold_page: 부분 실패시 이미 생성된 것들의 sys_id 반환 (rollback 정보)
- [ ] scaffold_page: widgets 없는 row도 정상 생성 (빈 칼럼)
