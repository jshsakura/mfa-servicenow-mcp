"""
Service Portal management tools for the ServiceNow MCP server.

Covers portal instances (sp_portal), pages (sp_page), and widget instances (sp_instance).
These complement the widget-centric tools in portal_tools.py by providing
structural visibility into portal composition.
"""

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .sn_api import GenericQueryParams, invalidate_query_cache, sn_query

logger = logging.getLogger(__name__)

# Table constants
PORTAL_TABLE = "sp_portal"
PAGE_TABLE = "sp_page"
INSTANCE_TABLE = "sp_instance"
CONTAINER_TABLE = "sp_container"
ROW_TABLE = "sp_row"
COLUMN_TABLE = "sp_column"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _order_key(record: Dict[str, Any]) -> tuple[int, str]:
    raw_order = record.get("order")
    try:
        order = int(str(raw_order))
    except (TypeError, ValueError):
        order = 0
    return order, str(record.get("sys_id") or "")


def _resolve_widget_names(
    config: ServerConfig,
    auth_manager: AuthManager,
    widget_sys_ids: List[str],
) -> Dict[str, Dict[str, str]]:
    """Bulk-resolve sp_widget sys_ids to {id, name} in a single query."""
    ids = [sid for sid in widget_sys_ids if sid]
    if not ids:
        return {}
    resp = _query(
        config,
        auth_manager,
        "sp_widget",
        f"sys_idIN{','.join(ids)}",
        "sys_id,id,name",
        limit=max(20, len(ids)),
    )
    result: Dict[str, Dict[str, str]] = {}
    for w in resp.get("results", []):
        wid = str(w.get("sys_id") or "")
        if wid:
            result[wid] = {"id": w.get("id", ""), "name": w.get("name", "")}
    return result


def _query(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int = 20,
    offset: int = 0,
    *,
    display_value: bool = False,
    orderby: Optional[str] = None,
) -> Dict[str, Any]:
    """Thin wrapper around sn_query to reduce boilerplate."""
    params = GenericQueryParams(
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=offset,
        orderby=orderby,
        display_value=display_value,
    )
    return sn_query(config, auth_manager, params)


# ---------------------------------------------------------------------------
# Portal Instance (sp_portal)
# ---------------------------------------------------------------------------


class GetPortalParams(BaseModel):
    """Parameters for listing portals or getting a single portal."""

    portal_id: Optional[str] = Field(
        default=None,
        description="sys_id or url_suffix. If provided, returns single portal detail. Otherwise lists all portals.",
    )
    limit: int = Field(default=20, description="Maximum portals to return in list mode (max 50)")
    offset: int = Field(default=0, description="Pagination offset for list mode")
    query: Optional[str] = Field(default=None, description="Filter by title (LIKE match) in list mode")
    count_only: bool = Field(default=False, description="Return count only (list mode)")


@register_tool(
    name="get_portal",
    params=GetPortalParams,
    description=(
        "Look up a Service Portal by name, URL suffix (e.g. 'sp', 'csm'), or sys_id. "
        "Returns portal config including homepage, theme, and linked pages with display names. "
        "Omit portal_id to list all portals."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def get_portal(
    config: ServerConfig, auth_manager: AuthManager, params: GetPortalParams
) -> Dict[str, Any]:
    """Get or list Service Portal instances."""
    # Detail mode
    if params.portal_id:
        fields = (
            "sys_id,title,url_suffix,homepage,theme,css,default_,"
            "logo,quick_start_config,kb_knowledge_base,"
            "catalog,sc_catalog,login_page,notfound_page,sys_scope"
        )
        query = f"sys_id={params.portal_id}^ORurl_suffix={params.portal_id}"
        # Use display_value to resolve reference fields (homepage, login_page, etc.)
        response = _query(
            config, auth_manager, PORTAL_TABLE, query, fields, limit=1, display_value=True
        )
        if not response.get("success") or not response.get("results"):
            return {"success": False, "message": f"Portal not found: {params.portal_id}"}
        r = response["results"][0]
        return {
            "success": True,
            "portal": {
                "sys_id": r.get("sys_id"),
                "title": r.get("title"),
                "url_suffix": r.get("url_suffix"),
                "homepage": r.get("homepage"),
                "theme": r.get("theme"),
                "is_default": r.get("default_") == "true",
                "css": r.get("css"),
                "kb_knowledge_base": r.get("kb_knowledge_base"),
                "catalog": r.get("catalog") or r.get("sc_catalog"),
                "login_page": r.get("login_page"),
                "notfound_page": r.get("notfound_page"),
                "scope": r.get("sys_scope"),
            },
        }

    # List mode — search both title and url_suffix so callers can find
    # portals by suffix (e.g. "sp") without a separate detail call.
    query = f"titleLIKE{params.query}^ORurl_suffixLIKE{params.query}" if params.query else ""
    if params.count_only:
        from .sn_api import sn_count

        count = sn_count(config, auth_manager, PORTAL_TABLE, query)
        return {"success": True, "count": count}

    fields = "sys_id,title,url_suffix,homepage,theme,css,default_,logo,sp_rectangle"
    response = _query(
        config,
        auth_manager,
        PORTAL_TABLE,
        query,
        fields,
        limit=min(params.limit, 50),
        offset=params.offset,
    )
    if not response.get("success"):
        return {"success": False, "message": response.get("message", "Query failed"), "portals": []}

    portals = [
        {
            "sys_id": r.get("sys_id"),
            "title": r.get("title"),
            "url_suffix": r.get("url_suffix"),
            "homepage": r.get("homepage"),
            "theme": r.get("theme"),
            "is_default": r.get("default_") == "true",
        }
        for r in response.get("results", [])
    ]
    return {"success": True, "portals": portals, "total": response.get("total_count")}


# ---------------------------------------------------------------------------
# Portal Pages (sp_page)
# ---------------------------------------------------------------------------


class GetPageParams(BaseModel):
    """Parameters for listing pages or getting a single page."""

    page_id: Optional[str] = Field(
        default=None,
        description="sys_id or URL path (id). If provided, returns single page detail with layout. Otherwise lists pages.",
    )
    include_layout: bool = Field(
        default=True, description="Include container/row/column/widget layout tree (detail mode only)"
    )
    limit: int = Field(default=20, description="Maximum pages to return in list mode (max 100)")
    offset: int = Field(default=0, description="Pagination offset for list mode")
    query: Optional[str] = Field(default=None, description="Filter by title (LIKE match) in list mode")


@register_tool(
    name="get_page",
    params=GetPageParams,
    description=(
        "Look up a Service Portal page by URL path (e.g. 'index', 'form'), title, or sys_id. "
        "Returns page properties and full layout tree with widget names/IDs resolved — "
        "no extra calls needed. Omit page_id to search/list pages."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def get_page(
    config: ServerConfig, auth_manager: AuthManager, params: GetPageParams
) -> Dict[str, Any]:
    """Get or list Service Portal pages."""
    # Detail mode
    if params.page_id:
        fields = "sys_id,id,title,internal,public,draft,css,sys_scope"
        query = f"sys_id={params.page_id}^ORid={params.page_id}"
        response = _query(config, auth_manager, PAGE_TABLE, query, fields, limit=1)
        if not response.get("success") or not response.get("results"):
            return {"success": False, "message": f"Page not found: {params.page_id}"}
        r = response["results"][0]
        page: Dict[str, Any] = {
            "sys_id": r.get("sys_id"),
            "id": r.get("id"),
            "title": r.get("title"),
            "internal": r.get("internal") == "true",
            "public": r.get("public") == "true",
            "draft": r.get("draft") == "true",
            "css": r.get("css"),
            "scope": r.get("sys_scope"),
        }
        if params.include_layout:
            page["layout"] = _get_page_layout(config, auth_manager, r["sys_id"])
        return {"success": True, "page": page}

    # List mode — search both title and id (URL path) so callers can find
    # pages like "index" without knowing the sys_id upfront.
    query_parts = []
    if params.query:
        query_parts.append(f"titleLIKE{params.query}^ORidLIKE{params.query}")
    response = _query(
        config,
        auth_manager,
        PAGE_TABLE,
        "^".join(query_parts) if query_parts else "",
        "sys_id,id,title,internal,public,draft,sys_scope",
        limit=min(params.limit, 100),
        offset=params.offset,
    )
    if not response.get("success"):
        return {"success": False, "message": response.get("message", "Query failed"), "pages": []}

    pages = [
        {
            "sys_id": r.get("sys_id"),
            "id": r.get("id"),
            "title": r.get("title"),
            "internal": r.get("internal") == "true",
            "public": r.get("public") == "true",
            "draft": r.get("draft") == "true",
            "scope": r.get("sys_scope"),
        }
        for r in response.get("results", [])
    ]
    return {"success": True, "pages": pages, "total": response.get("total_count")}


def _get_page_layout(
    config: ServerConfig, auth_manager: AuthManager, page_sys_id: str
) -> List[Dict[str, Any]]:
    """Build the container -> row -> column -> widget instance hierarchy for a page."""
    container_resp = _query(
        config,
        auth_manager,
        CONTAINER_TABLE,
        f"sp_page={page_sys_id}",
        "sys_id,order,background_color,css_class",
        limit=50,
        orderby="order",
    )
    containers = container_resp.get("results", [])
    if not containers:
        return []

    container_ids = [str(c.get("sys_id") or "") for c in containers if c.get("sys_id")]
    row_resp = _query(
        config,
        auth_manager,
        ROW_TABLE,
        f"sp_containerIN{','.join(container_ids)}",
        "sys_id,sp_container,order,css_class",
        limit=max(50, len(container_ids) * 10),
        orderby="order",
    )
    rows = row_resp.get("results", [])

    row_ids = [str(row.get("sys_id") or "") for row in rows if row.get("sys_id")]
    col_resp = (
        _query(
            config,
            auth_manager,
            COLUMN_TABLE,
            f"sp_rowIN{','.join(row_ids)}",
            "sys_id,sp_row,order,size,css_class",
            limit=max(20, len(row_ids) * 10),
            orderby="order",
        )
        if row_ids
        else {"results": []}
    )
    columns = col_resp.get("results", [])

    column_ids = [str(col.get("sys_id") or "") for col in columns if col.get("sys_id")]
    inst_resp = (
        _query(
            config,
            auth_manager,
            INSTANCE_TABLE,
            f"sp_columnIN{','.join(column_ids)}",
            "sys_id,sp_column,sp_widget,order,widget_parameters,css",
            limit=max(20, len(column_ids) * 20),
            orderby="order",
        )
        if column_ids
        else {"results": []}
    )
    instances = inst_resp.get("results", [])

    # Bulk-resolve widget names/IDs so callers don't need extra round-trips.
    widget_ref_ids = list(
        {str(inst.get("sp_widget") or "") for inst in instances if inst.get("sp_widget")}
    )
    widget_meta = _resolve_widget_names(config, auth_manager, widget_ref_ids)

    containers = sorted(containers, key=_order_key)
    rows = sorted(rows, key=_order_key)
    columns = sorted(columns, key=_order_key)
    instances = sorted(instances, key=_order_key)

    widgets_by_column: Dict[str, List[Dict[str, Any]]] = {}
    for inst in instances:
        column_id = str(inst.get("sp_column") or "")
        if not column_id:
            continue
        widget_ref = str(inst.get("sp_widget") or "")
        meta = widget_meta.get(widget_ref, {})
        widget_entry: Dict[str, Any] = {
            "sys_id": inst.get("sys_id"),
            "widget": widget_ref,
            "widget_id": meta.get("id", ""),
            "widget_name": meta.get("name", ""),
            "order": inst.get("order"),
        }
        # Include widget_parameters when present (avoids extra get_widget_instance calls)
        params_val = inst.get("widget_parameters")
        if params_val:
            widget_entry["widget_parameters"] = params_val
        widgets_by_column.setdefault(column_id, []).append(widget_entry)

    columns_by_row: Dict[str, List[Dict[str, Any]]] = {}
    for col in columns:
        row_id = str(col.get("sp_row") or "")
        if not row_id:
            continue
        columns_by_row.setdefault(row_id, []).append(
            {
                "sys_id": col.get("sys_id"),
                "order": col.get("order"),
                "size": col.get("size"),
                "css_class": col.get("css_class"),
                "widgets": widgets_by_column.get(str(col.get("sys_id") or ""), []),
            }
        )

    rows_by_container: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        container_id = str(row.get("sp_container") or "")
        if not container_id:
            continue
        rows_by_container.setdefault(container_id, []).append(
            {
                "sys_id": row.get("sys_id"),
                "order": row.get("order"),
                "css_class": row.get("css_class"),
                "columns": columns_by_row.get(str(row.get("sys_id") or ""), []),
            }
        )

    layout = []
    for c in containers:
        container_id = str(c.get("sys_id") or "")
        container: Dict[str, Any] = {
            "sys_id": c.get("sys_id"),
            "order": c.get("order"),
            "css_class": c.get("css_class"),
            "rows": rows_by_container.get(container_id, []),
        }
        layout.append(container)

    return layout


# ---------------------------------------------------------------------------
# Widget Instances (sp_instance)
# ---------------------------------------------------------------------------


class GetWidgetInstanceParams(BaseModel):
    """Parameters for getting a widget instance or listing instances."""

    instance_id: Optional[str] = Field(
        default=None,
        description="sys_id of the widget instance. If provided, returns detail. Otherwise lists instances.",
    )
    page_id: Optional[str] = Field(default=None, description="Filter by page sys_id (list mode)")
    widget_id: Optional[str] = Field(
        default=None, description="Filter by widget sys_id — find all placements (list mode)"
    )
    limit: int = Field(default=20, description="Maximum instances to return in list mode (max 100)")
    offset: int = Field(default=0, description="Pagination offset for list mode")


class CreateWidgetInstanceParams(BaseModel):
    """Parameters for placing a widget on a page column."""

    sp_widget: str = Field(..., description="sys_id of the widget to place")
    sp_column: str = Field(..., description="sys_id of the target column")
    order: int = Field(default=0, description="Display order within the column")
    widget_parameters: Optional[str] = Field(
        default=None, description="JSON string of widget instance options"
    )
    css: Optional[str] = Field(default=None, description="Instance-level CSS overrides")


class UpdateWidgetInstanceParams(BaseModel):
    """Parameters for updating a widget instance."""

    instance_id: str = Field(..., description="sys_id of the widget instance")
    order: Optional[int] = Field(default=None, description="Display order within the column")
    sp_column: Optional[str] = Field(default=None, description="Move to a different column (sys_id)")
    widget_parameters: Optional[str] = Field(
        default=None, description="JSON string of widget instance options"
    )
    css: Optional[str] = Field(default=None, description="Instance-level CSS overrides")


@register_tool(
    name="get_widget_instance",
    params=GetWidgetInstanceParams,
    description=(
        "Get widget placement details — where a widget sits on a page and its config. "
        "Returns widget name/ID, column, order, and parameters. "
        "Filter by page or widget to find all placements."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def get_widget_instance(
    config: ServerConfig, auth_manager: AuthManager, params: GetWidgetInstanceParams
) -> Dict[str, Any]:
    """Get or list widget instances with resolved widget names."""
    # Detail mode
    if params.instance_id:
        fields = "sys_id,sp_widget,sp_column,order,widget_parameters,css,sys_scope"
        response = _query(
            config,
            auth_manager,
            INSTANCE_TABLE,
            f"sys_id={params.instance_id}",
            fields,
            limit=1,
        )
        if not response.get("success") or not response.get("results"):
            return {"success": False, "message": f"Widget instance not found: {params.instance_id}"}
        r = response["results"][0]
        # Resolve widget name in one extra query
        widget_meta = _resolve_widget_names(config, auth_manager, [str(r.get("sp_widget") or "")])
        meta = widget_meta.get(str(r.get("sp_widget") or ""), {})
        return {
            "success": True,
            "instance": {
                "sys_id": r.get("sys_id"),
                "widget": r.get("sp_widget"),
                "widget_id": meta.get("id", ""),
                "widget_name": meta.get("name", ""),
                "column": r.get("sp_column"),
                "order": r.get("order"),
                "widget_parameters": r.get("widget_parameters"),
                "css": r.get("css"),
                "scope": r.get("sys_scope"),
            },
        }

    # List mode
    query_parts = []
    if params.widget_id:
        query_parts.append(f"sp_widget={params.widget_id}")
    if params.page_id:
        query_parts.append(f"sp_column.sp_row.sp_container.sp_page={params.page_id}")

    response = _query(
        config,
        auth_manager,
        INSTANCE_TABLE,
        "^".join(query_parts) if query_parts else "",
        "sys_id,sp_widget,sp_column,order,css",
        limit=min(params.limit, 100),
        offset=params.offset,
    )
    if not response.get("success"):
        return {
            "success": False,
            "message": response.get("message", "Query failed"),
            "instances": [],
        }

    results = response.get("results", [])
    # Bulk-resolve widget names
    widget_refs = list({str(r.get("sp_widget") or "") for r in results if r.get("sp_widget")})
    widget_meta = _resolve_widget_names(config, auth_manager, widget_refs)

    instances = []
    for r in results:
        ref = str(r.get("sp_widget") or "")
        meta = widget_meta.get(ref, {})
        instances.append(
            {
                "sys_id": r.get("sys_id"),
                "widget": ref,
                "widget_id": meta.get("id", ""),
                "widget_name": meta.get("name", ""),
                "column": r.get("sp_column"),
                "order": r.get("order"),
            }
        )
    return {"success": True, "instances": instances, "total": response.get("total_count")}


@register_tool(
    name="create_widget_instance",
    params=CreateWidgetInstanceParams,
    description="Place a widget on a portal page column. Specify widget, target column, display order, and optional config parameters.",
    serialization="raw_dict",
    return_type=dict,
)
def create_widget_instance(
    config: ServerConfig, auth_manager: AuthManager, params: CreateWidgetInstanceParams
) -> Dict[str, Any]:
    """Create a widget instance (place a widget on a column)."""
    url = f"{config.instance_url}/api/now/table/{INSTANCE_TABLE}"

    body: Dict[str, Any] = {
        "sp_widget": params.sp_widget,
        "sp_column": params.sp_column,
        "order": str(params.order),
    }
    if params.widget_parameters:
        body["widget_parameters"] = params.widget_parameters
    if params.css:
        body["css"] = params.css

    headers = auth_manager.get_headers()

    try:
        response = auth_manager.make_request(
            "POST",
            url,
            json=body,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "result" not in data:
            return {"success": False, "message": "Failed to create widget instance"}

        result = data["result"]
        invalidate_query_cache(table=INSTANCE_TABLE)
        return {
            "success": True,
            "message": "Created widget instance",
            "instance_id": result.get("sys_id"),
            "widget": result.get("sp_widget"),
            "column": result.get("sp_column"),
        }
    except Exception as e:
        logger.error(f"Error creating widget instance: {e}")
        return {"success": False, "message": f"Error creating widget instance: {str(e)}"}


@register_tool(
    name="update_widget_instance",
    params=UpdateWidgetInstanceParams,
    description="Move, reorder, or update options/CSS of an existing widget instance on a page.",
    serialization="raw_dict",
    return_type=dict,
)
def update_widget_instance(
    config: ServerConfig, auth_manager: AuthManager, params: UpdateWidgetInstanceParams
) -> Dict[str, Any]:
    """Update a widget instance."""
    url = f"{config.instance_url}/api/now/table/{INSTANCE_TABLE}/{params.instance_id}"

    body: Dict[str, Any] = {}
    if params.order is not None:
        body["order"] = str(params.order)
    if params.sp_column is not None:
        body["sp_column"] = params.sp_column
    if params.widget_parameters is not None:
        body["widget_parameters"] = params.widget_parameters
    if params.css is not None:
        body["css"] = params.css

    if not body:
        return {"success": True, "message": "No changes to update"}

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

        if "result" not in data:
            return {"success": False, "message": "Failed to update widget instance"}

        result = data["result"]
        invalidate_query_cache(table=INSTANCE_TABLE)
        return {
            "success": True,
            "message": f"Updated widget instance {params.instance_id}",
            "instance_id": result.get("sys_id"),
        }
    except Exception as e:
        logger.error(f"Error updating widget instance: {e}")
        return {"success": False, "message": f"Error updating widget instance: {str(e)}"}
