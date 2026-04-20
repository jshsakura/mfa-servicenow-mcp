"""
Portal CRUD tools for the ServiceNow MCP server.
Create widgets, angular providers, header/footer, CSS themes,
ng templates, UI pages, pages, and layout components.

Safety features:
- scope is REQUIRED for all component creation (prevents accidental Global scope)
- Duplicate name/id check before creation
- scaffold_page returns full created-record inventory for manual cleanup on partial failure
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety helpers
# ---------------------------------------------------------------------------
def _check_duplicate(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    field: str,
    value: str,
    scope: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Check if a record with the same identifier already exists.

    Returns the existing record dict if found, None otherwise.
    """
    query = f"{field}={value}"
    if scope:
        query += f"^sys_scope={scope}"
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=f"sys_id,{field},sys_scope",
            limit=1,
            offset=0,
            display_value=True,
        )
        return rows[0] if rows else None
    except Exception:
        return None


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
            "POST",
            url,
            json=body,
            headers=headers,
            timeout=timeout,
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


# ===========================================================================
# Phase 1: Component Create Tools (6)
# ===========================================================================

# --- Tool 1: create_widget -------------------------------------------------


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
    scope: str = Field(
        ...,
        description="REQUIRED. sys_scope sys_id — the application scope this widget belongs to.",
    )


@register_tool(
    name="create_widget",
    params=CreateWidgetParams,
    description="Create a new Service Portal widget with template, scripts, and CSS. Scope is required.",
    serialization="raw_dict",
    return_type=dict,
)
def create_widget(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateWidgetParams,
) -> Dict[str, Any]:
    # Duplicate check by name
    existing = _check_duplicate(
        config, auth_manager, "sp_widget", "name", params.name, params.scope
    )
    if existing:
        return {
            "success": False,
            "message": f"Widget with name '{params.name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
            "existing_scope": existing.get("sys_scope"),
        }
    # Also check by id if provided
    if params.id:
        existing_id = _check_duplicate(config, auth_manager, "sp_widget", "id", params.id)
        if existing_id:
            return {
                "success": False,
                "message": f"Widget with id '{params.id}' already exists.",
                "existing_sys_id": existing_id.get("sys_id"),
                "existing_scope": existing_id.get("sys_scope"),
            }

    body: Dict[str, Any] = {"name": params.name, "sys_scope": params.scope}
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


# --- Tool 2: create_angular_provider ----------------------------------------


class CreateAngularProviderParams(BaseModel):
    name: str = Field(..., description="Provider name (e.g. 'myService')")
    script: str = Field(..., description="AngularJS provider/factory/service script")
    type: str = Field(
        default="factory",
        description="Provider type: factory, service, provider, directive, filter",
    )
    description: Optional[str] = Field(default=None, description="Description")
    scope: str = Field(..., description="REQUIRED. sys_scope sys_id — the application scope.")


@register_tool(
    name="create_angular_provider",
    params=CreateAngularProviderParams,
    description="Create an AngularJS 1.x angular provider (factory/service/directive). Scope is required.",
    serialization="raw_dict",
    return_type=dict,
)
def create_angular_provider(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateAngularProviderParams,
) -> Dict[str, Any]:
    existing = _check_duplicate(
        config, auth_manager, "sp_angular_provider", "name", params.name, params.scope
    )
    if existing:
        return {
            "success": False,
            "message": f"Angular provider '{params.name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {
        "name": params.name,
        "script": params.script,
        "type": params.type,
        "sys_scope": params.scope,
    }
    if params.description:
        body["description"] = params.description

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


# --- Tool 3: create_header_footer -------------------------------------------


class CreateHeaderFooterParams(BaseModel):
    name: str = Field(..., description="Header/footer name")
    template: Optional[str] = Field(default=None, description="HTML template")
    css: Optional[str] = Field(default=None, description="CSS/SCSS styles")
    scope: str = Field(..., description="REQUIRED. sys_scope sys_id — the application scope.")


@register_tool(
    name="create_header_footer",
    params=CreateHeaderFooterParams,
    description="Create a Service Portal header or footer component. Scope is required.",
    serialization="raw_dict",
    return_type=dict,
)
def create_header_footer(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateHeaderFooterParams,
) -> Dict[str, Any]:
    existing = _check_duplicate(
        config, auth_manager, "sp_header_footer", "name", params.name, params.scope
    )
    if existing:
        return {
            "success": False,
            "message": f"Header/footer '{params.name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": params.name, "sys_scope": params.scope}
    if params.template is not None:
        body["template"] = params.template
    if params.css is not None:
        body["css"] = params.css

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


# --- Tool 4: create_css_theme -----------------------------------------------


class CreateCssThemeParams(BaseModel):
    name: str = Field(..., description="CSS theme name")
    css: Optional[str] = Field(default=None, description="CSS/SCSS content")
    scope: str = Field(..., description="REQUIRED. sys_scope sys_id — the application scope.")


@register_tool(
    name="create_css_theme",
    params=CreateCssThemeParams,
    description="Create a Service Portal CSS theme (sp_css). Scope is required.",
    serialization="raw_dict",
    return_type=dict,
)
def create_css_theme(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateCssThemeParams,
) -> Dict[str, Any]:
    existing = _check_duplicate(config, auth_manager, "sp_css", "name", params.name, params.scope)
    if existing:
        return {
            "success": False,
            "message": f"CSS theme '{params.name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": params.name, "sys_scope": params.scope}
    if params.css is not None:
        body["css"] = params.css

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


# --- Tool 5: create_ng_template ---------------------------------------------


class CreateNgTemplateParams(BaseModel):
    id: str = Field(..., description="Template ID (used in ng-include, e.g. 'my-template.html')")
    template: str = Field(..., description="HTML template content")
    scope: str = Field(..., description="REQUIRED. sys_scope sys_id — the application scope.")


@register_tool(
    name="create_ng_template",
    params=CreateNgTemplateParams,
    description="Create an AngularJS ng-template (sp_ng_template) for use in ng-include. Scope is required.",
    serialization="raw_dict",
    return_type=dict,
)
def create_ng_template(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateNgTemplateParams,
) -> Dict[str, Any]:
    existing = _check_duplicate(
        config, auth_manager, "sp_ng_template", "id", params.id, params.scope
    )
    if existing:
        return {
            "success": False,
            "message": f"ng-template with id '{params.id}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {
        "id": params.id,
        "template": params.template,
        "sys_scope": params.scope,
    }

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


# --- Tool 6: create_ui_page -------------------------------------------------


class CreateUiPageParams(BaseModel):
    name: str = Field(..., description="UI Page name (URL path)")
    html: Optional[str] = Field(default=None, description="Jelly/HTML content")
    client_script: Optional[str] = Field(default=None, description="Client-side JavaScript")
    processing_script: Optional[str] = Field(
        default=None, description="Server-side processing script"
    )
    description: Optional[str] = Field(default=None, description="Page description")
    category: Optional[str] = Field(default=None, description="Category (e.g. 'general')")
    scope: str = Field(..., description="REQUIRED. sys_scope sys_id — the application scope.")


@register_tool(
    name="create_ui_page",
    params=CreateUiPageParams,
    description="Create a UI Page (sys_ui_page) with HTML, client script, and processing script. Scope is required.",
    serialization="raw_dict",
    return_type=dict,
)
def create_ui_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateUiPageParams,
) -> Dict[str, Any]:
    existing = _check_duplicate(
        config, auth_manager, "sys_ui_page", "name", params.name, params.scope
    )
    if existing:
        return {
            "success": False,
            "message": f"UI page '{params.name}' already exists in this scope.",
            "existing_sys_id": existing.get("sys_id"),
        }

    body: Dict[str, Any] = {"name": params.name, "sys_scope": params.scope}
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


# ===========================================================================
# Phase 3: Page & Layout CRUD Tools (6)
# ===========================================================================

# --- Tool 7: create_page ----------------------------------------------------


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
    category: Optional[str] = Field(default=None, description="Category sys_id (sp_category)")
    scope: str = Field(..., description="REQUIRED. sys_scope sys_id — the application scope.")


@register_tool(
    name="create_page",
    params=CreatePageParams,
    description="Create a new Service Portal page. Scope is required. Returns sys_id for subsequent layout creation.",
    serialization="raw_dict",
    return_type=dict,
)
def create_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreatePageParams,
) -> Dict[str, Any]:
    # sp_page.id is globally unique (URL path), check without scope filter
    existing = _check_duplicate(config, auth_manager, "sp_page", "id", params.id)
    if existing:
        return {
            "success": False,
            "message": f"Page with id '{params.id}' already exists.",
            "existing_sys_id": existing.get("sys_id"),
            "existing_scope": existing.get("sys_scope"),
        }

    body: Dict[str, Any] = {
        "id": params.id,
        "title": params.title,
        "sys_scope": params.scope,
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


# --- Tool 8: update_page ----------------------------------------------------


class UpdatePageParams(BaseModel):
    sys_id: str = Field(..., description="Page sys_id")
    title: Optional[str] = Field(default=None, description="New title")
    description: Optional[str] = Field(default=None, description="New description")
    css: Optional[str] = Field(default=None, description="New page-level CSS")
    internal: Optional[bool] = Field(default=None, description="Toggle internal flag")
    public: Optional[bool] = Field(default=None, description="Toggle public access")
    draft: Optional[bool] = Field(default=None, description="Toggle draft status")
    dry_run: bool = Field(
        default=False,
        description="Preview field-level changes without executing.",
    )


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

    if params.dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sp_page",
            sys_id=params.sys_id,
            proposed=body,
            identifier_fields=["title", "id", "public"],
        )

    url = f"{config.instance_url}/api/now/table/sp_page/{params.sys_id}"
    headers = auth_manager.get_headers()
    try:
        response = auth_manager.make_request(
            "PATCH",
            url,
            json=body,
            headers=headers,
            timeout=30,
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


# --- Tool 9: create_container -----------------------------------------------


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


# --- Tool 10: create_row ----------------------------------------------------


class CreateRowParams(BaseModel):
    sp_container: str = Field(..., description="Container sys_id to add row to")
    order: int = Field(default=100, description="Display order within the container")
    css_class: Optional[str] = Field(
        default=None, description="Additional CSS classes (e.g. 'row-eq-height')"
    )


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


# --- Tool 11: create_column -------------------------------------------------


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


# --- Tool 12: scaffold_page -------------------------------------------------


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
    scope: str = Field(
        ..., description="REQUIRED. sys_scope sys_id — the application scope for the page."
    )


@register_tool(
    name="scaffold_page",
    params=ScaffoldPageParams,
    description="Create a complete portal page with layout (container/rows/columns) and widget placements in one call. Scope is required.",
    serialization="raw_dict",
    return_type=dict,
)
def scaffold_page(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ScaffoldPageParams,
) -> Dict[str, Any]:
    """Create page -> container -> rows -> columns -> widget instances in sequence."""
    created: Dict[str, Any] = {
        "page": None,
        "container": None,
        "rows": [],
        "columns": [],
        "instances": [],
    }
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
                "message": (
                    f"Row {i}: widgets list length ({len(row.widgets)}) "
                    f"must match columns ({len(row.columns)})"
                ),
            }
        if row.widget_params and len(row.widget_params) != len(row.columns):
            return {
                "success": False,
                "message": (
                    f"Row {i}: widget_params length ({len(row.widget_params)}) "
                    f"must match columns ({len(row.columns)})"
                ),
            }

    # Duplicate check: page id is globally unique
    existing_page = _check_duplicate(config, auth_manager, "sp_page", "id", params.page_id)
    if existing_page:
        return {
            "success": False,
            "message": f"Page with id '{params.page_id}' already exists.",
            "existing_sys_id": existing_page.get("sys_id"),
            "existing_scope": existing_page.get("sys_scope"),
        }

    # 1. Create page
    page_body: Dict[str, Any] = {
        "id": params.page_id,
        "title": params.title,
        "sys_scope": params.scope,
    }
    if params.description:
        page_body["description"] = params.description
    if params.css:
        page_body["css"] = params.css
    if params.public:
        page_body["public"] = "true"

    page_result = _create_record(config, auth_manager, "sp_page", page_body)
    if not page_result["success"]:
        return {
            "success": False,
            "message": f"Failed to create page: {page_result['message']}",
            "created": created,
        }
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
        return {
            "success": False,
            "message": "Failed after page creation",
            "created": created,
            "errors": errors,
            "cleanup_hint": "Page was created but layout failed. Delete the page or retry layout manually.",
        }
    container_sys_id = container_result["result"].get("sys_id")
    created["container"] = {"sys_id": container_sys_id}

    # 3. Create rows, columns, and widget instances
    for row_idx, row_def in enumerate(params.rows):
        row_order = (row_idx + 1) * 100
        row_body: Dict[str, Any] = {
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
                errors.append(
                    f"Row {row_idx}, Col {col_idx} creation failed: {col_result['message']}"
                )
                continue
            col_sys_id = col_result["result"].get("sys_id")
            created["columns"].append({"sys_id": col_sys_id, "row": row_sys_id, "size": col_size})

            # Place widget if specified
            widget_id = (
                row_def.widgets[col_idx]
                if row_def.widgets and col_idx < len(row_def.widgets)
                else None
            )
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
                    errors.append(
                        f"Widget instance at row {row_idx}, col {col_idx} failed: "
                        f"{inst_result['message']}"
                    )
                else:
                    created["instances"].append(
                        {
                            "sys_id": inst_result["result"].get("sys_id"),
                            "widget": widget_id,
                            "column": col_sys_id,
                        }
                    )

    success = len(errors) == 0
    result: Dict[str, Any] = {
        "success": success,
        "message": (
            f"Page scaffolded: /{params.page_id}"
            + (f" with {len(errors)} errors" if errors else "")
        ),
        "created": created,
        "summary": {
            "page": params.page_id,
            "containers": 1,
            "rows": len(created["rows"]),
            "columns": len(created["columns"]),
            "widget_instances": len(created["instances"]),
        },
    }
    if errors:
        result["errors"] = errors
        result["cleanup_hint"] = (
            "Some layout components failed to create. Use the 'created' dict "
            "to identify orphaned records for manual cleanup or retry."
        )
    return result
