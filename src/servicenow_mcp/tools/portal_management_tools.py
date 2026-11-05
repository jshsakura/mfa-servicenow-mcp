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
from .sn_api import GenericQueryParams, rows_of, sn_query

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
    for w in rows_of(resp):
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
        description="sys_id or url_suffix; provided = single portal detail, omitted = list all.",
    )
    limit: int = Field(default=20, description="Maximum portals to return in list mode (max 50)")
    offset: int = Field(default=0, description="Pagination offset for list mode")
    query: Optional[str] = Field(
        default=None, description="Filter by title (LIKE match) in list mode"
    )
    count_only: bool = Field(default=False, description="Return count only (list mode)")


# A theme's SCSS variables are the design knobs, so they are returned — up to
# this size. A larger body is withheld with its size and the call that fetches it.
_CSS_VARIABLES_INLINE_CHARS = 4000
_INCLUDE_LIMIT = 100


def _inline_or_withheld(text: Any, get_all: str) -> Any:
    body = str(text or "")
    if len(body) <= _CSS_VARIABLES_INLINE_CHARS:
        return body
    return {
        "withheld": True,
        "chars": len(body),
        "lines": len(body.splitlines()),
        "get_all": get_all,
    }


def _css_variables_body(text: Any, scope: str) -> Any:
    return _inline_or_withheld(
        text, f"download_server_sources(scope='{scope or 'global'}', families=['theme'])"
    )


def _theme_includes(
    config: ServerConfig, auth_manager: AuthManager, table: str, theme_id: str, fields: str
) -> Dict[str, Any]:
    resp = _query(
        config,
        auth_manager,
        table,
        f"sp_theme={theme_id}",
        fields,
        limit=_INCLUDE_LIMIT,
        orderby="order",
    )
    if not resp.get("success"):
        return {"checked": False, "because": resp.get("message", "query failed"), "rows": []}
    rows = rows_of(resp)
    total = resp.get("total_count")
    return {
        "checked": True,
        "complete": total is None or int(total) <= len(rows),
        "total": total,
        "rows": rows,
    }


def _theme_chain(config: ServerConfig, auth_manager: AuthManager, theme_id: str) -> Dict[str, Any]:
    """sp_theme → header/footer, SCSS variables, CSS/JS includes, matching NX theme."""
    resp = _query(
        config,
        auth_manager,
        "sp_theme",
        f"sys_id={theme_id}",
        "sys_id,name,header,header.name,footer,footer.name,navbar_fixed,footer_fixed,"
        "turn_off_scss_compilation,matching_now_experience_theme,"
        "matching_now_experience_theme.name,css_variables,sys_scope.scope",
        limit=1,
    )
    rows = rows_of(resp)
    if not rows:
        from .portal_tools import _lookup_miss

        return {"sys_id": theme_id, **_lookup_miss(resp, f"Theme not read: {theme_id}")}
    t = rows[0]
    scope = str(t.get("sys_scope.scope") or "")
    css = _theme_includes(
        config,
        auth_manager,
        "m2m_sp_theme_css_include",
        theme_id,
        "order,sp_css_include,sp_css_include.name,sp_css_include.source,"
        "sp_css_include.url,sp_css_include.sp_css,sp_css_include.sp_css.name",
    )
    js = _theme_includes(
        config,
        auth_manager,
        "m2m_sp_theme_js_include",
        theme_id,
        "order,sp_js_include,sp_js_include.display_name,sp_js_include.source,"
        "sp_js_include.url,sp_js_include.sys_ui_script,sp_js_include.sys_ui_script.name",
    )
    css["rows"] = [
        {
            "order": r.get("order"),
            "include": r.get("sp_css_include.name"),
            "include_sys_id": r.get("sp_css_include"),
            "source": r.get("sp_css_include.source"),
            "url": r.get("sp_css_include.url") or None,
            "sp_css": r.get("sp_css_include.sp_css.name") or None,
            "sp_css_sys_id": r.get("sp_css_include.sp_css") or None,
        }
        for r in css["rows"]
    ]
    js["rows"] = [
        {
            "order": r.get("order"),
            "include": r.get("sp_js_include.display_name"),
            "include_sys_id": r.get("sp_js_include"),
            "source": r.get("sp_js_include.source"),
            "url": r.get("sp_js_include.url") or None,
            "ui_script": r.get("sp_js_include.sys_ui_script.name") or None,
        }
        for r in js["rows"]
    ]
    return {
        "sys_id": t.get("sys_id"),
        "name": t.get("name"),
        "scope": scope,
        "header": (
            {"name": t.get("header.name"), "sys_id": t.get("header")} if t.get("header") else None
        ),
        "footer": (
            {"name": t.get("footer.name"), "sys_id": t.get("footer")} if t.get("footer") else None
        ),
        "navbar_fixed": t.get("navbar_fixed") == "true",
        "footer_fixed": t.get("footer_fixed") == "true",
        "scss_compilation_off": t.get("turn_off_scss_compilation") == "true",
        "next_experience_theme": (
            {
                "name": t.get("matching_now_experience_theme.name"),
                "sys_id": t.get("matching_now_experience_theme"),
            }
            if t.get("matching_now_experience_theme")
            else None
        ),
        "css_variables": _css_variables_body(t.get("css_variables"), scope),
        "css_includes": css,
        "js_includes": js,
    }


@register_tool(
    name="get_portal",
    params=GetPortalParams,
    description=(
        "List portals, or one portal's config and full theme: SCSS variables, header/footer, "
        "CSS/JS includes, Next Experience theme."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def get_portal(
    config: ServerConfig, auth_manager: AuthManager, params: GetPortalParams
) -> Dict[str, Any]:
    """Get or list Service Portal instances."""
    # Detail mode. Field names are the dictionary's (measured live): `default`,
    # `sc_catalog`, `dark_theme`, `css_variables` — not default_/catalog/css, which
    # the Table API drops without an error.
    if params.portal_id:
        fields = (
            "sys_id,title,url_suffix,default,homepage.id,login_page.id,notfound_page.id,"
            "sc_catalog.title,kb_knowledge_base.title,theme,theme.name,dark_theme,"
            "dark_theme.name,css_variables,sys_scope.scope"
        )
        query = f"sys_id={params.portal_id}^ORurl_suffix={params.portal_id}"
        response = _query(config, auth_manager, PORTAL_TABLE, query, fields, limit=1)
        if not rows_of(response):
            from .portal_tools import _lookup_miss

            return _lookup_miss(response, f"Portal not found: {params.portal_id}", wrap=True)
        r = rows_of(response)[0]
        scope = str(r.get("sys_scope.scope") or "")
        theme_id = str(r.get("theme") or "")
        return {
            "success": True,
            "portal": {
                "sys_id": r.get("sys_id"),
                "title": r.get("title"),
                "url_suffix": r.get("url_suffix"),
                "is_default": r.get("default") == "true",
                "homepage": r.get("homepage.id"),
                "login_page": r.get("login_page.id"),
                "notfound_page": r.get("notfound_page.id"),
                "catalog": r.get("sc_catalog.title"),
                "kb_knowledge_base": r.get("kb_knowledge_base.title"),
                "scope": scope,
                # The portal's own SCSS variables (sp_portal), separate from the theme's.
                "css_variables": _css_variables_body(r.get("css_variables"), scope),
                "dark_theme": (
                    {"name": r.get("dark_theme.name"), "sys_id": r.get("dark_theme")}
                    if r.get("dark_theme")
                    else None
                ),
            },
            "theme": _theme_chain(config, auth_manager, theme_id) if theme_id else None,
        }

    # List mode — search both title and url_suffix so callers can find
    # portals by suffix (e.g. "sp") without a separate detail call.
    query = f"titleLIKE{params.query}^ORurl_suffixLIKE{params.query}" if params.query else ""
    if params.count_only:
        from .sn_api import count_response

        return count_response(config, auth_manager, PORTAL_TABLE, query, what="portals")

    fields = "sys_id,title,url_suffix,homepage.id,theme,theme.name,default"
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
            "homepage": r.get("homepage.id"),
            "theme": r.get("theme.name"),
            "theme_sys_id": r.get("theme"),
            "is_default": r.get("default") == "true",
        }
        for r in rows_of(response)
    ]
    return {"success": True, "portals": portals, "total": response.get("total_count")}


# ---------------------------------------------------------------------------
# Portal Pages (sp_page)
# ---------------------------------------------------------------------------


class GetPageParams(BaseModel):
    """Parameters for listing pages or getting a single page."""

    page_id: Optional[str] = Field(
        default=None,
        description="sys_id or URL path (id). Set → page detail+layout; omit → list pages.",
    )
    include_layout: bool = Field(
        default=True,
        description="Include container/row/column/widget layout tree (detail mode only)",
    )
    limit: int = Field(default=20, description="Maximum pages to return in list mode (max 100)")
    offset: int = Field(default=0, description="Pagination offset for list mode")
    query: Optional[str] = Field(
        default=None, description="Filter by title (LIKE match) in list mode"
    )


@register_tool(
    name="get_page",
    params=GetPageParams,
    description="Get or list portal pages by URL path, title, or sys_id. Returns layout tree with widget placements.",
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
        if not response.get("success") or not rows_of(response):
            return {"success": False, "message": f"Page not found: {params.page_id}"}
        r = rows_of(response)[0]
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
        for r in rows_of(response)
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
        # Dictionary names (measured live): the CSS class is container_class_name,
        # class_name is the parent class. There is no css_class column on any of
        # the three layout tables — selecting it returned blanks, silently.
        "sys_id,order,background_color,container_class_name,class_name,width",
        limit=50,
        orderby="order",
    )
    containers = rows_of(container_resp)
    if not containers:
        return []

    container_ids = [str(c.get("sys_id") or "") for c in containers if c.get("sys_id")]
    row_resp = _query(
        config,
        auth_manager,
        ROW_TABLE,
        f"sp_containerIN{','.join(container_ids)}",
        "sys_id,sp_container,order,class_name",
        limit=max(50, len(container_ids) * 10),
        orderby="order",
    )
    rows = rows_of(row_resp)

    row_ids = [str(row.get("sys_id") or "") for row in rows if row.get("sys_id")]
    col_resp = (
        _query(
            config,
            auth_manager,
            COLUMN_TABLE,
            f"sp_rowIN{','.join(row_ids)}",
            "sys_id,sp_row,order,size,class_name",
            limit=max(20, len(row_ids) * 10),
            orderby="order",
        )
        if row_ids
        else {"results": []}
    )
    columns = rows_of(col_resp)

    column_ids = [str(col.get("sys_id") or "") for col in columns if col.get("sys_id")]
    inst_resp = (
        _query(
            config,
            auth_manager,
            INSTANCE_TABLE,
            f"sp_columnIN{','.join(column_ids)}",
            "sys_id,sp_column,sp_widget,order,widget_parameters,css,class_name,color",
            limit=max(20, len(column_ids) * 20),
            orderby="order",
        )
        if column_ids
        else {"results": []}
    )
    instances = rows_of(inst_resp)

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
        # Instance-level styling: bootstrap class/color and the instance's own CSS.
        for key in ("class_name", "color"):
            if inst.get(key):
                widget_entry[key] = inst.get(key)
        if inst.get("css"):
            widget_entry["css"] = _inline_or_withheld(
                inst.get("css"), f"get_widget_instance(instance_id='{inst.get('sys_id')}')"
            )
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
                "css_class": col.get("class_name"),
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
                "css_class": row.get("class_name"),
                "columns": columns_by_row.get(str(row.get("sys_id") or ""), []),
            }
        )

    layout = []
    for c in containers:
        container_id = str(c.get("sys_id") or "")
        container: Dict[str, Any] = {
            "sys_id": c.get("sys_id"),
            "order": c.get("order"),
            "css_class": c.get("container_class_name"),
            "parent_class": c.get("class_name"),
            "width": c.get("width"),
            "background_color": c.get("background_color"),
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
        description="sys_id of the widget instance. Set → detail; omit → list instances.",
    )
    page_id: Optional[str] = Field(default=None, description="Filter by page sys_id (list mode)")
    widget_id: Optional[str] = Field(
        default=None, description="Filter by widget sys_id — find all placements (list mode)"
    )
    limit: int = Field(default=20, description="Maximum instances to return in list mode (max 100)")
    offset: int = Field(default=0, description="Pagination offset for list mode")


@register_tool(
    name="get_widget_instance",
    params=GetWidgetInstanceParams,
    description="Get widget instance placement on a page. Returns column, order, and config. Filter by page or widget.",
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
        if not response.get("success") or not rows_of(response):
            return {"success": False, "message": f"Widget instance not found: {params.instance_id}"}
        r = rows_of(response)[0]
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

    results = rows_of(response)
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
