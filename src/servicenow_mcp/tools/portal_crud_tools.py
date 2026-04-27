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
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import portal_component as _comp_svc
from servicenow_mcp.services import portal_layout as _layout_svc
from servicenow_mcp.tools.portal_tools import UpdatePortalComponentParams, update_portal_component
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
# Phase 1: scaffold_page
# ===========================================================================


# --- scaffold_page -------------------------------------------------


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


# ---------------------------------------------------------------------------
# manage_portal_layout — page + container/row/column + widget instance ops
# ---------------------------------------------------------------------------

_PAGE_UPDATE_FIELDS = ("title", "description", "css", "internal", "public", "draft")


class ManagePortalLayoutParams(BaseModel):
    """Manage Service Portal layout — pages, containers, rows, columns, widget instances.

    Required per action:
      create_page:    page_id, title, scope
      update_page:    sys_id, at least one field
      add_container:  sp_page
      add_row:        sp_container
      add_column:     sp_row
      place_widget:   sp_widget, sp_column
      move_widget:    instance_id (and at least one of sp_column/order/widget_parameters/css)
    """

    action: Literal[
        "create_page",
        "update_page",
        "add_container",
        "add_row",
        "add_column",
        "place_widget",
        "move_widget",
    ] = Field(...)

    # Page identity
    page_id: Optional[str] = Field(default=None, description="URL path (create_page)")
    title: Optional[str] = Field(default=None)
    sys_id: Optional[str] = Field(default=None, description="page sys_id (update_page)")
    description: Optional[str] = Field(default=None)
    css: Optional[str] = Field(default=None)
    internal: Optional[bool] = Field(default=None)
    public: Optional[bool] = Field(default=None)
    draft: Optional[bool] = Field(default=None)
    category: Optional[str] = Field(default=None)
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id (create_page)")

    # Layout container/row/column
    sp_page: Optional[str] = Field(default=None)
    sp_container: Optional[str] = Field(default=None)
    sp_row: Optional[str] = Field(default=None)
    order: Optional[int] = Field(default=None)
    width: Optional[str] = Field(default=None)
    css_class: Optional[str] = Field(default=None)
    background_color: Optional[str] = Field(default=None)
    size: Optional[int] = Field(default=None, description="Bootstrap col size 1-12")

    # Widget instance
    sp_widget: Optional[str] = Field(default=None)
    sp_column: Optional[str] = Field(default=None)
    instance_id: Optional[str] = Field(default=None)
    widget_parameters: Optional[str] = Field(default=None, description="JSON string")
    instance_css: Optional[str] = Field(default=None, description="Instance-level CSS")

    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManagePortalLayoutParams":
        a = self.action
        if a == "create_page":
            for f in ("page_id", "title", "scope"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='create_page'")
        elif a == "update_page":
            if not self.sys_id:
                raise ValueError("sys_id is required for action='update_page'")
            if not any(getattr(self, f) is not None for f in _PAGE_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update_page'")
        elif a == "add_container":
            if not self.sp_page:
                raise ValueError("sp_page is required for action='add_container'")
        elif a == "add_row":
            if not self.sp_container:
                raise ValueError("sp_container is required for action='add_row'")
        elif a == "add_column":
            if not self.sp_row:
                raise ValueError("sp_row is required for action='add_column'")
        elif a == "place_widget":
            if not self.sp_widget:
                raise ValueError("sp_widget is required for action='place_widget'")
            if not self.sp_column:
                raise ValueError("sp_column is required for action='place_widget'")
        elif a == "move_widget":
            if not self.instance_id:
                raise ValueError("instance_id is required for action='move_widget'")
        return self


@register_tool(
    name="manage_portal_layout",
    params=ManagePortalLayoutParams,
    description="Portal layout: page CRUD + container/row/column + widget instance placement.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_portal_layout(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManagePortalLayoutParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "create_page":
        kw: Dict[str, Any] = {
            "page_id": params.page_id,
            "title": params.title,
            "scope": params.scope,
        }
        for f in ("description", "css", "internal", "public", "draft", "category"):
            v = getattr(params, f)
            if v is not None:
                kw[f] = v
        return _layout_svc.create_page(config, auth_manager, **kw)
    if a == "update_page":
        kw = {"sys_id": params.sys_id, "dry_run": params.dry_run}
        for f in _PAGE_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kw[f] = v
        return _layout_svc.update_page(config, auth_manager, **kw)
    if a == "add_container":
        kw = {"sp_page": params.sp_page}
        if params.order is not None:
            kw["order"] = params.order
        for f in ("width", "css_class", "background_color"):
            v = getattr(params, f)
            if v is not None:
                kw[f] = v
        return _layout_svc.create_container(config, auth_manager, **kw)
    if a == "add_row":
        kw = {"sp_container": params.sp_container}
        if params.order is not None:
            kw["order"] = params.order
        if params.css_class is not None:
            kw["css_class"] = params.css_class
        return _layout_svc.create_row(config, auth_manager, **kw)
    if a == "add_column":
        kw = {"sp_row": params.sp_row}
        if params.order is not None:
            kw["order"] = params.order
        if params.size is not None:
            kw["size"] = params.size
        if params.css_class is not None:
            kw["css_class"] = params.css_class
        return _layout_svc.create_column(config, auth_manager, **kw)
    if a == "place_widget":
        kw = {"sp_widget": params.sp_widget, "sp_column": params.sp_column}
        if params.order is not None:
            kw["order"] = params.order
        if params.widget_parameters is not None:
            kw["widget_parameters"] = params.widget_parameters
        if params.instance_css is not None:
            kw["css"] = params.instance_css
        return _layout_svc.place_widget(config, auth_manager, **kw)
    # move_widget
    kw = {"instance_id": params.instance_id}
    for src, dst in (
        ("sp_column", "sp_column"),
        ("order", "order"),
        ("widget_parameters", "widget_parameters"),
        ("instance_css", "css"),
    ):
        v = getattr(params, src)
        if v is not None:
            kw[dst] = v
    return _layout_svc.move_widget(config, auth_manager, **kw)


# ---------------------------------------------------------------------------
# manage_portal_component — widget/provider/header_footer/theme/ng_template/
# ui_page/update_code
# ---------------------------------------------------------------------------


class ManagePortalComponentParams(BaseModel):
    """Manage Service Portal components.

    Required per action:
      create_widget:        name, scope
      create_provider:      name, script, scope
      create_header_footer: name, scope
      create_theme:         name, scope
      create_ng_template:   template_id, template, scope
      create_ui_page:       name, scope
      update_code:          table, sys_id, update_data
    """

    action: Literal[
        "create_widget",
        "create_provider",
        "create_header_footer",
        "create_theme",
        "create_ng_template",
        "create_ui_page",
        "update_code",
    ] = Field(...)

    # Common fields
    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    scope: Optional[str] = Field(default=None, description="sys_scope sys_id")

    # widget
    widget_id: Optional[str] = Field(
        default=None, description="Widget technical id (auto if omitted)"
    )
    template: Optional[str] = Field(default=None)
    css: Optional[str] = Field(default=None)
    script: Optional[str] = Field(default=None)
    client_script: Optional[str] = Field(default=None)
    link: Optional[str] = Field(default=None)
    internal: bool = Field(default=False)
    data_table: Optional[str] = Field(default=None)

    # provider
    provider_type: Optional[str] = Field(
        default=None, description="factory|service|provider|directive|filter"
    )

    # ng_template
    template_id: Optional[str] = Field(default=None, description="ng-include id")

    # ui_page
    html: Optional[str] = Field(default=None)
    processing_script: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)

    # update_code
    table: Optional[str] = Field(default=None)
    sys_id: Optional[str] = Field(default=None)
    update_data: Optional[Dict[str, str]] = Field(default=None)

    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManagePortalComponentParams":
        a = self.action
        if a in (
            "create_widget",
            "create_header_footer",
            "create_theme",
            "create_ui_page",
        ):
            if not self.name:
                raise ValueError(f"name is required for action='{a}'")
            if not self.scope:
                raise ValueError(f"scope is required for action='{a}'")
        elif a == "create_provider":
            if not self.name:
                raise ValueError("name is required for action='create_provider'")
            if not self.script:
                raise ValueError("script is required for action='create_provider'")
            if not self.scope:
                raise ValueError("scope is required for action='create_provider'")
        elif a == "create_ng_template":
            if not self.template_id:
                raise ValueError("template_id is required for action='create_ng_template'")
            if not self.template:
                raise ValueError("template is required for action='create_ng_template'")
            if not self.scope:
                raise ValueError("scope is required for action='create_ng_template'")
        elif a == "update_code":
            if not self.table:
                raise ValueError("table is required for action='update_code'")
            if not self.sys_id:
                raise ValueError("sys_id is required for action='update_code'")
            if not self.update_data:
                raise ValueError("update_data is required for action='update_code'")
        return self


@register_tool(
    name="manage_portal_component",
    params=ManagePortalComponentParams,
    description="Portal component create (widget/provider/theme/etc.) + update_code.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_portal_component(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManagePortalComponentParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "create_widget":
        kw: Dict[str, Any] = {"name": params.name, "scope": params.scope}
        if params.widget_id is not None:
            kw["widget_id"] = params.widget_id
        for f in (
            "template",
            "css",
            "script",
            "client_script",
            "link",
            "internal",
            "data_table",
            "description",
        ):
            v = getattr(params, f)
            if v is not None:
                kw[f] = v
        return _comp_svc.create_widget(config, auth_manager, **kw)
    if a == "create_provider":
        kw = {
            "name": params.name,
            "script": params.script,
            "scope": params.scope,
        }
        if params.provider_type is not None:
            kw["provider_type"] = params.provider_type
        if params.description is not None:
            kw["description"] = params.description
        return _comp_svc.create_angular_provider(config, auth_manager, **kw)
    if a == "create_header_footer":
        kw = {"name": params.name, "scope": params.scope}
        for f in ("template", "css"):
            v = getattr(params, f)
            if v is not None:
                kw[f] = v
        return _comp_svc.create_header_footer(config, auth_manager, **kw)
    if a == "create_theme":
        kw = {"name": params.name, "scope": params.scope}
        if params.css is not None:
            kw["css"] = params.css
        return _comp_svc.create_css_theme(config, auth_manager, **kw)
    if a == "create_ng_template":
        kw = {
            "template_id": params.template_id,
            "template": params.template,
            "scope": params.scope,
        }
        return _comp_svc.create_ng_template(config, auth_manager, **kw)
    if a == "create_ui_page":
        kw = {"name": params.name, "scope": params.scope}
        for f in ("html", "client_script", "processing_script", "description", "category"):
            v = getattr(params, f)
            if v is not None:
                kw[f] = v
        return _comp_svc.create_ui_page(config, auth_manager, **kw)
    # update_code
    # ManagePortalCrudParams validator guarantees both are present for update_code.
    assert params.table is not None
    assert params.sys_id is not None
    assert params.update_data is not None
    return update_portal_component(
        config,
        auth_manager,
        UpdatePortalComponentParams(
            table=params.table, sys_id=params.sys_id, update_data=params.update_data
        ),
    )
