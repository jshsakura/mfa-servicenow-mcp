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
from .sn_api import GenericQueryParams, sn_query

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


def _query(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """Thin wrapper around sn_query to reduce boilerplate."""
    params = GenericQueryParams(
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=offset,
        display_value=True,
    )
    return sn_query(config, auth_manager, params)


# ---------------------------------------------------------------------------
# Portal Instance (sp_portal)
# ---------------------------------------------------------------------------


class ListPortalsParams(BaseModel):
    """Parameters for listing portal instances."""

    limit: int = Field(20, description="Maximum portals to return (max 50)")
    offset: int = Field(0, description="Pagination offset")
    query: Optional[str] = Field(None, description="Filter by title (LIKE match)")
    count_only: bool = Field(
        False,
        description="Return count only without fetching records. Uses lightweight Aggregate API.",
    )


class GetPortalParams(BaseModel):
    """Parameters for getting a portal instance."""

    portal_id: str = Field(..., description="sys_id or url_suffix of the portal")


@register_tool(
    name="list_portals",
    params=ListPortalsParams,
    description="List portals with title, URL suffix, theme, and homepage references. Filterable by title.",
    serialization="raw_dict",
    return_type=dict,
)
def list_portals(
    config: ServerConfig, auth_manager: AuthManager, params: ListPortalsParams
) -> Dict[str, Any]:
    """List Service Portal instances."""
    query = ""
    if params.query:
        query = f"titleLIKE{params.query}"

    if params.count_only:
        from .sn_api import sn_count

        count = sn_count(config, auth_manager, "sp_portal", query)
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

    portals = []
    for r in response.get("results", []):
        portals.append(
            {
                "sys_id": r.get("sys_id"),
                "title": r.get("title"),
                "url_suffix": r.get("url_suffix"),
                "homepage": r.get("homepage"),
                "theme": r.get("theme"),
                "is_default": r.get("default_") == "true",
            }
        )

    return {
        "success": True,
        "message": f"Found {len(portals)} portal(s)",
        "portals": portals,
        "total": response.get("total_count"),
    }


@register_tool(
    name="get_portal",
    params=GetPortalParams,
    description="Get a single portal by sys_id or URL suffix. Returns full config including theme, KB, catalog, and login page.",
    serialization="raw_dict",
    return_type=dict,
)
def get_portal(
    config: ServerConfig, auth_manager: AuthManager, params: GetPortalParams
) -> Dict[str, Any]:
    """Get a Service Portal instance by sys_id or url_suffix."""
    fields = (
        "sys_id,title,url_suffix,homepage,theme,css,default_,"
        "logo,quick_start_config,kb_knowledge_base,"
        "catalog,sc_catalog,login_page,notfound_page,sys_scope"
    )
    query = f"sys_id={params.portal_id}^ORurl_suffix={params.portal_id}"

    response = _query(config, auth_manager, PORTAL_TABLE, query, fields, limit=1)

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


# ---------------------------------------------------------------------------
# Portal Pages (sp_page)
# ---------------------------------------------------------------------------


class ListPagesParams(BaseModel):
    """Parameters for listing portal pages."""

    limit: int = Field(20, description="Maximum pages to return (max 100)")
    offset: int = Field(0, description="Pagination offset")
    query: Optional[str] = Field(None, description="Filter by title (LIKE match)")
    portal_id: Optional[str] = Field(
        None, description="Filter pages belonging to a specific portal (sys_id)"
    )


class GetPageParams(BaseModel):
    """Parameters for getting a portal page with layout structure."""

    page_id: str = Field(..., description="sys_id or id (URL path) of the page")
    include_layout: bool = Field(
        True, description="Include container/row/column/widget instance hierarchy"
    )


@register_tool(
    name="list_pages",
    params=ListPagesParams,
    description="List portal pages with title, URL path, and visibility flags. Filterable by title or portal.",
    serialization="raw_dict",
    return_type=dict,
)
def list_pages(
    config: ServerConfig, auth_manager: AuthManager, params: ListPagesParams
) -> Dict[str, Any]:
    """List Service Portal pages."""
    fields = "sys_id,id,title,internal,public,draft,sys_scope"
    query_parts = []
    if params.query:
        query_parts.append(f"titleLIKE{params.query}")

    response = _query(
        config,
        auth_manager,
        PAGE_TABLE,
        "^".join(query_parts) if query_parts else "",
        fields,
        limit=min(params.limit, 100),
        offset=params.offset,
    )

    if not response.get("success"):
        return {"success": False, "message": response.get("message", "Query failed"), "pages": []}

    pages = []
    for r in response.get("results", []):
        pages.append(
            {
                "sys_id": r.get("sys_id"),
                "id": r.get("id"),
                "title": r.get("title"),
                "internal": r.get("internal") == "true",
                "public": r.get("public") == "true",
                "draft": r.get("draft") == "true",
                "scope": r.get("sys_scope"),
            }
        )

    return {
        "success": True,
        "message": f"Found {len(pages)} page(s)",
        "pages": pages,
        "total": response.get("total_count"),
    }


@register_tool(
    name="get_page",
    params=GetPageParams,
    description="Get a page by sys_id or URL path. Optionally includes full container/row/column/widget layout tree.",
    serialization="raw_dict",
    return_type=dict,
)
def get_page(
    config: ServerConfig, auth_manager: AuthManager, params: GetPageParams
) -> Dict[str, Any]:
    """Get a portal page with optional layout structure."""
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


def _get_page_layout(
    config: ServerConfig, auth_manager: AuthManager, page_sys_id: str
) -> List[Dict[str, Any]]:
    """Build the container -> row -> column -> widget instance hierarchy for a page."""
    # 1. Get containers
    container_resp = _query(
        config,
        auth_manager,
        CONTAINER_TABLE,
        f"sp_page={page_sys_id}",
        "sys_id,order,background_color,css_class",
        limit=50,
    )
    containers = container_resp.get("results", [])

    layout = []
    for c in containers:
        container: Dict[str, Any] = {
            "sys_id": c.get("sys_id"),
            "order": c.get("order"),
            "css_class": c.get("css_class"),
            "rows": [],
        }

        # 2. Get rows in container
        row_resp = _query(
            config,
            auth_manager,
            ROW_TABLE,
            f"sp_container={c['sys_id']}",
            "sys_id,order,css_class",
            limit=50,
        )
        for row in row_resp.get("results", []):
            row_data: Dict[str, Any] = {
                "sys_id": row.get("sys_id"),
                "order": row.get("order"),
                "css_class": row.get("css_class"),
                "columns": [],
            }

            # 3. Get columns in row
            col_resp = _query(
                config,
                auth_manager,
                COLUMN_TABLE,
                f"sp_row={row['sys_id']}",
                "sys_id,order,size,css_class",
                limit=20,
            )
            for col in col_resp.get("results", []):
                col_data: Dict[str, Any] = {
                    "sys_id": col.get("sys_id"),
                    "order": col.get("order"),
                    "size": col.get("size"),
                    "css_class": col.get("css_class"),
                    "widgets": [],
                }

                # 4. Get widget instances in column
                inst_resp = _query(
                    config,
                    auth_manager,
                    INSTANCE_TABLE,
                    f"sp_column={col['sys_id']}",
                    "sys_id,sp_widget,order,widget_parameters,css",
                    limit=20,
                )
                for inst in inst_resp.get("results", []):
                    col_data["widgets"].append(
                        {
                            "sys_id": inst.get("sys_id"),
                            "widget": inst.get("sp_widget"),
                            "order": inst.get("order"),
                        }
                    )

                row_data["columns"].append(col_data)
            container["rows"].append(row_data)
        layout.append(container)

    return layout


# ---------------------------------------------------------------------------
# Widget Instances (sp_instance)
# ---------------------------------------------------------------------------


class ListWidgetInstancesParams(BaseModel):
    """Parameters for listing widget instances."""

    page_id: Optional[str] = Field(None, description="Filter by page sys_id")
    widget_id: Optional[str] = Field(
        None, description="Filter by widget sys_id (find all placements of a widget)"
    )
    limit: int = Field(20, description="Maximum instances to return (max 100)")
    offset: int = Field(0, description="Pagination offset")


class GetWidgetInstanceParams(BaseModel):
    """Parameters for getting a widget instance."""

    instance_id: str = Field(..., description="sys_id of the widget instance")


class CreateWidgetInstanceParams(BaseModel):
    """Parameters for placing a widget on a page column."""

    sp_widget: str = Field(..., description="sys_id of the widget to place")
    sp_column: str = Field(..., description="sys_id of the target column")
    order: int = Field(0, description="Display order within the column")
    widget_parameters: Optional[str] = Field(
        None, description="JSON string of widget instance options"
    )
    css: Optional[str] = Field(None, description="Instance-level CSS overrides")


class UpdateWidgetInstanceParams(BaseModel):
    """Parameters for updating a widget instance."""

    instance_id: str = Field(..., description="sys_id of the widget instance")
    order: Optional[int] = Field(None, description="Display order within the column")
    sp_column: Optional[str] = Field(None, description="Move to a different column (sys_id)")
    widget_parameters: Optional[str] = Field(
        None, description="JSON string of widget instance options"
    )
    css: Optional[str] = Field(None, description="Instance-level CSS overrides")


@register_tool(
    name="list_widget_instances",
    params=ListWidgetInstancesParams,
    description="List widget placements on pages with column and order info. Filter by page or widget sys_id.",
    serialization="raw_dict",
    return_type=dict,
)
def list_widget_instances(
    config: ServerConfig, auth_manager: AuthManager, params: ListWidgetInstancesParams
) -> Dict[str, Any]:
    """List widget instances with placement info."""
    fields = "sys_id,sp_widget,sp_column,order,css"
    query_parts = []
    if params.widget_id:
        query_parts.append(f"sp_widget={params.widget_id}")
    if params.page_id:
        # Join through column -> row -> container -> page
        query_parts.append(f"sp_column.sp_row.sp_container.sp_page={params.page_id}")

    response = _query(
        config,
        auth_manager,
        INSTANCE_TABLE,
        "^".join(query_parts) if query_parts else "",
        fields,
        limit=min(params.limit, 100),
        offset=params.offset,
    )

    if not response.get("success"):
        return {
            "success": False,
            "message": response.get("message", "Query failed"),
            "instances": [],
        }

    instances = []
    for r in response.get("results", []):
        instances.append(
            {
                "sys_id": r.get("sys_id"),
                "widget": r.get("sp_widget"),
                "column": r.get("sp_column"),
                "order": r.get("order"),
            }
        )

    return {
        "success": True,
        "message": f"Found {len(instances)} widget instance(s)",
        "instances": instances,
        "total": response.get("total_count"),
    }


@register_tool(
    name="get_widget_instance",
    params=GetWidgetInstanceParams,
    description="Get a single widget instance with its placement, parameters, and CSS overrides.",
    serialization="raw_dict",
    return_type=dict,
)
def get_widget_instance(
    config: ServerConfig, auth_manager: AuthManager, params: GetWidgetInstanceParams
) -> Dict[str, Any]:
    """Get a single widget instance with full details."""
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
    return {
        "success": True,
        "instance": {
            "sys_id": r.get("sys_id"),
            "widget": r.get("sp_widget"),
            "column": r.get("sp_column"),
            "order": r.get("order"),
            "widget_parameters": r.get("widget_parameters"),
            "css": r.get("css"),
            "scope": r.get("sys_scope"),
        },
    }


@register_tool(
    name="create_widget_instance",
    params=CreateWidgetInstanceParams,
    description="Place a widget on a page column. Specify widget sys_id, target column, order, and optional parameters.",
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
        return {
            "success": True,
            "message": f"Updated widget instance {params.instance_id}",
            "instance_id": result.get("sys_id"),
        }
    except Exception as e:
        logger.error(f"Error updating widget instance: {e}")
        return {"success": False, "message": f"Error updating widget instance: {str(e)}"}
