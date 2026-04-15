# Phase 1: Portal Component Create Tools

## Goal
신규 위젯, Angular Provider, Header/Footer, CSS Theme, NG Template, UI Page를 MCP를 통해 ServiceNow에 생성할 수 있게 한다.

## New File: `src/servicenow_mcp/tools/portal_crud_tools.py`

이 파일에 모든 Create 도구를 구현한다.

### Imports & Setup

```python
"""
Portal CRUD tools for the ServiceNow MCP server.
Create widgets, angular providers, header/footer, CSS themes,
ng templates, UI pages, pages, and layout components.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool
from servicenow_mcp.tools.sn_api import invalidate_query_cache

logger = logging.getLogger(__name__)
```

### Common Response Helper

모든 create 도구가 공유하는 POST 패턴:

```python
def _create_record(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    body: Dict[str, Any],
    timeout: int = 30,
) -> Dict[str, Any]:
    """POST a new record to ServiceNow Table API. Returns result dict."""
    url = f"{config.instance_url}/api/now/table/{table}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request(
            "POST", url, json=body, headers=headers, timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if "result" not in data:
            return {"success": False, "message": f"No result in response for {table}"}
        invalidate_query_cache(table=table)
        return {"success": True, "result": data["result"]}
    except Exception as e:
        logger.error("Error creating record in %s: %s", table, e)
        return {"success": False, "message": f"Error creating record in {table}: {e}"}
```

### Tool 1: create_widget

```python
class CreateWidgetParams(BaseModel):
    """Parameters for creating a new Service Portal widget."""
    name: str = Field(..., description="Display name of the widget")
    id: Optional[str] = Field(
        default=None,
        description="Technical ID (URL-safe, lowercase). Auto-generated from name if omitted.",
    )
    template: Optional[str] = Field(default=None, description="HTML template (AngularJS 1.x)")
    css: Optional[str] = Field(default=None, description="SCSS/CSS styles")
    script: Optional[str] = Field(default=None, description="Server-side script (GlideRecord)")
    client_script: Optional[str] = Field(
        default=None, description="Client-side controller (AngularJS 1.x)"
    )
    link: Optional[str] = Field(default=None, description="AngularJS link function")
    internal: bool = Field(default=False, description="Mark as internal widget")
    data_table: Optional[str] = Field(default=None, description="Default data table")
    description: Optional[str] = Field(default=None, description="Widget description")
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")


@register_tool(
    name="create_widget",
    params=CreateWidgetParams,
    description="Create a new Service Portal widget with template, scripts, and CSS.",
    serialization="raw_dict",
    return_type=dict,
)
def create_widget(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateWidgetParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"name": params.name}
    if params.id:
        body["id"] = params.id
    if params.template is not None:
        body["template"] = params.template
    if params.css is not None:
        body["css"] = params.css
    if params.script is not None:
        body["script"] = params.script
    if params.client_script is not None:
        body["client_script"] = params.client_script
    if params.link is not None:
        body["link"] = params.link
    if params.internal:
        body["internal"] = "true"
    if params.data_table:
        body["data_table"] = params.data_table
    if params.description:
        body["description"] = params.description
    if params.scope:
        body["sys_scope"] = params.scope

    result = _create_record(config, auth_manager, "sp_widget", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created widget: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "id": record.get("id"),
        "name": record.get("name"),
    }
```

### Tool 2: create_angular_provider

```python
class CreateAngularProviderParams(BaseModel):
    name: str = Field(..., description="Provider name (e.g. 'myService')")
    script: str = Field(..., description="AngularJS provider/factory/service script")
    type: str = Field(
        default="factory",
        description="Provider type: factory, service, provider, directive, filter",
    )
    description: Optional[str] = Field(default=None, description="Description")
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")


@register_tool(
    name="create_angular_provider",
    params=CreateAngularProviderParams,
    description="Create an AngularJS 1.x angular provider (factory/service/directive).",
    serialization="raw_dict",
    return_type=dict,
)
def create_angular_provider(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateAngularProviderParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "name": params.name,
        "script": params.script,
        "type": params.type,
    }
    if params.description:
        body["description"] = params.description
    if params.scope:
        body["sys_scope"] = params.scope

    result = _create_record(config, auth_manager, "sp_angular_provider", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created angular provider: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
        "type": record.get("type"),
    }
```

### Tool 3: create_header_footer

```python
class CreateHeaderFooterParams(BaseModel):
    name: str = Field(..., description="Header/footer name")
    template: Optional[str] = Field(default=None, description="HTML template")
    css: Optional[str] = Field(default=None, description="CSS/SCSS styles")
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")


@register_tool(
    name="create_header_footer",
    params=CreateHeaderFooterParams,
    description="Create a Service Portal header or footer component.",
    serialization="raw_dict",
    return_type=dict,
)
def create_header_footer(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateHeaderFooterParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"name": params.name}
    if params.template is not None:
        body["template"] = params.template
    if params.css is not None:
        body["css"] = params.css
    if params.scope:
        body["sys_scope"] = params.scope

    result = _create_record(config, auth_manager, "sp_header_footer", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created header/footer: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }
```

### Tool 4: create_css_theme

```python
class CreateCssThemeParams(BaseModel):
    name: str = Field(..., description="CSS theme name")
    css: Optional[str] = Field(default=None, description="CSS/SCSS content")
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")


@register_tool(
    name="create_css_theme",
    params=CreateCssThemeParams,
    description="Create a Service Portal CSS theme (sp_css).",
    serialization="raw_dict",
    return_type=dict,
)
def create_css_theme(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateCssThemeParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"name": params.name}
    if params.css is not None:
        body["css"] = params.css
    if params.scope:
        body["sys_scope"] = params.scope

    result = _create_record(config, auth_manager, "sp_css", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created CSS theme: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }
```

### Tool 5: create_ng_template

```python
class CreateNgTemplateParams(BaseModel):
    id: str = Field(..., description="Template ID (used in ng-include, e.g. 'my-template.html')")
    template: str = Field(..., description="HTML template content")
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")


@register_tool(
    name="create_ng_template",
    params=CreateNgTemplateParams,
    description="Create an AngularJS ng-template (sp_ng_template) for use in ng-include.",
    serialization="raw_dict",
    return_type=dict,
)
def create_ng_template(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateNgTemplateParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "id": params.id,
        "template": params.template,
    }
    if params.scope:
        body["sys_scope"] = params.scope

    result = _create_record(config, auth_manager, "sp_ng_template", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created ng-template: {record.get('id')}",
        "sys_id": record.get("sys_id"),
        "id": record.get("id"),
    }
```

### Tool 6: create_ui_page

```python
class CreateUiPageParams(BaseModel):
    name: str = Field(..., description="UI Page name (URL path)")
    html: Optional[str] = Field(default=None, description="Jelly/HTML content")
    client_script: Optional[str] = Field(default=None, description="Client-side JavaScript")
    processing_script: Optional[str] = Field(default=None, description="Server-side processing script")
    description: Optional[str] = Field(default=None, description="Page description")
    category: Optional[str] = Field(default=None, description="Category (e.g. 'general')")
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")


@register_tool(
    name="create_ui_page",
    params=CreateUiPageParams,
    description="Create a UI Page (sys_ui_page) with HTML, client script, and processing script.",
    serialization="raw_dict",
    return_type=dict,
)
def create_ui_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateUiPageParams,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"name": params.name}
    if params.html is not None:
        body["html"] = params.html
    if params.client_script is not None:
        body["client_script"] = params.client_script
    if params.processing_script is not None:
        body["processing_script"] = params.processing_script
    if params.description:
        body["description"] = params.description
    if params.category:
        body["category"] = params.category
    if params.scope:
        body["sys_scope"] = params.scope

    result = _create_record(config, auth_manager, "sys_ui_page", body)
    if not result["success"]:
        return result

    record = result["result"]
    return {
        "success": True,
        "message": f"Created UI page: {record.get('name')}",
        "sys_id": record.get("sys_id"),
        "name": record.get("name"),
    }
```

---

## Modify: `src/servicenow_mcp/tools/portal_tools.py`

### Change 1: Extend PORTAL_COMPONENT_EDITABLE_FIELDS (line 664)

**Before:**
```python
PORTAL_COMPONENT_EDITABLE_FIELDS: Dict[str, Set[str]] = {
    "sp_widget": {"template", "script", "client_script", "link", "css"},
    "sp_angular_provider": {"script"},
    "sys_script_include": {"script"},
}
```

**After:**
```python
PORTAL_COMPONENT_EDITABLE_FIELDS: Dict[str, Set[str]] = {
    "sp_widget": {"template", "script", "client_script", "link", "css"},
    "sp_angular_provider": {"script"},
    "sys_script_include": {"script"},
    "sp_header_footer": {"template", "css"},
    "sp_css": {"css"},
    "sp_ng_template": {"template"},
    "sys_ui_page": {"html", "client_script", "processing_script"},
}
```

This single change automatically enables:
- `update_portal_component` for new tables
- `preview_portal_component_update` for new tables
- `analyze_portal_component_update` for new tables
- `create_portal_component_snapshot` for new tables
- `update_portal_component_from_snapshot` for new tables

### Change 2: Upload Size Warning in update_portal_component (line ~2836)

In `update_portal_component()`, after building `effective_update_data` (around line 2811) and before the PATCH request (line 2836), add:

```python
    # Upload size warning
    size_warnings = []
    for field_name, value in effective_update_data.items():
        field_bytes = len(value.encode("utf-8"))
        if field_bytes > 500_000:  # 500KB
            size_warnings.append(
                f"Field '{field_name}' is {field_bytes:,} bytes ({field_bytes // 1024}KB). "
                f"Large payloads may be rejected by proxy/WAF."
            )
```

Then in the return dict (around line 2865), add:

```python
    result_dict = {
        "message": "Update successful",
        ...existing fields...
    }
    if size_warnings:
        result_dict["size_warnings"] = size_warnings
    return result_dict
```

---

## Reference: Existing Patterns to Follow

### @register_tool decorator pattern (from script_include_tools.py:295)
```python
@register_tool(
    name="create_script_include",
    params=CreateScriptIncludeParams,
    description="...",
    serialization="raw_dict",   # Use raw_dict for Dict return types
    return_type=dict,
)
```

### Auth + POST pattern (from portal_management_tools.py:570)
```python
url = f"{config.instance_url}/api/now/table/{TABLE_NAME}"
headers = auth_manager.get_headers()
response = auth_manager.make_request("POST", url, json=body, headers=headers, timeout=30)
response.raise_for_status()
data = response.json()
result = data["result"]
invalidate_query_cache(table=TABLE_NAME)
```

### Import for invalidate_query_cache
```python
from servicenow_mcp.tools.sn_api import invalidate_query_cache
```

---

## Validation Checklist

- [ ] `portal_crud_tools.py` imports compile without errors
- [ ] All 6 create tools have @register_tool decorator
- [ ] All Pydantic param classes have proper Field descriptions
- [ ] `_create_record` helper handles exceptions and returns consistent format
- [ ] `PORTAL_COMPONENT_EDITABLE_FIELDS` has 7 entries (3 existing + 4 new)
- [ ] Size warning logic doesn't block the update, only warns
- [ ] `invalidate_query_cache` called after every successful POST
