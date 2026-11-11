"""Resolve a portal or a set of pages to the widgets they actually render.

"Download what I need to change this page" used to be three calls the model
stitched by hand: read the layout, pull widget ids out of it, pass them back as
``widget_ids``. Here it is one walk, and the walk is complete or says it is not.

Two traps, both measured on a live Employee Center instance:

- Layouts nest. A column can hold rows (``sp_row.sp_column``) with no
  ``sp_container`` of their own, so one dot-walk
  ``sp_column.sp_row.sp_container.sp_page=X`` counts only the top level and
  silently drops every widget below it. The walk goes level by level until no
  new rows appear.
- A portal's chrome is not on any page. The header and footer come from the
  theme (``sp_theme.header/footer``, class ``sp_header_footer``), the main menu
  from ``sp_portal.sp_rectangle_menu`` (an ``sp_instance_menu``). A page-only
  walk would leave the parts every page shows.

Pages are shared between portals, so "every page of a portal" is not a
relation the platform has. A portal resolves to the pages it NAMES (home,
login, 404, catalog, catalog category, KB home) plus its chrome; other pages
are named with ``page_ids``.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

PORTAL_PAGE_FIELDS = (
    "homepage",
    "login_page",
    "notfound_page",
    "sc_catalog_page",
    "sc_category_page",
    "kb_knowledge_page",
)
PORTAL_THEME_FIELDS = ("theme", "dark_theme")
_MAX_DEPTH = 12
_MAX_ROWS = 5000

QueryFn = Callable[..., List[Dict[str, Any]]]


def _plain(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value") or ""
    return str(value or "").strip()


def _ids(rows: Sequence[Dict[str, Any]], field: str = "sys_id") -> List[str]:
    out: List[str] = []
    for row in rows:
        v = _plain(row.get(field))
        if v and v not in out:
            out.append(v)
    return out


class _Walk:
    def __init__(self, query: QueryFn):
        self._query = query
        self.complete = True
        self.warnings: List[str] = []

    def read(self, table: str, query: str, fields: str) -> List[Dict[str, Any]]:
        try:
            rows = self._query(table=table, query=query, fields=fields, max_records=_MAX_ROWS)
        except Exception as exc:  # noqa: BLE001 - recorded as incomplete, never as empty
            from servicenow_mcp.tools.sn_api import _is_auth_error

            if _is_auth_error(exc):
                raise
            self.complete = False
            self.warnings.append(f"INCOMPLETE — could not read {table} ({query[:80]}): {exc}")
            return []
        if len(rows) >= _MAX_ROWS:
            self.complete = False
            self.warnings.append(
                f"INCOMPLETE — {table} hit the {_MAX_ROWS}-row read cap; widgets past it "
                "may be missing."
            )
        return rows


def resolve_slice(
    query: QueryFn,
    *,
    portal: Optional[str] = None,
    page_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Widgets (sys_ids) a portal/page set renders, with what was and was not proven."""
    walk = _Walk(query)
    widget_ids: List[str] = []
    widget_source: Dict[str, str] = {}

    def add_widget(sys_id: str, where: str) -> None:
        if sys_id and sys_id not in widget_ids:
            widget_ids.append(sys_id)
            widget_source[sys_id] = where

    page_sys_ids: List[str] = []
    portal_info: Optional[Dict[str, Any]] = None
    themes: List[Dict[str, Any]] = []
    unresolved: List[str] = []

    if portal:
        rows = walk.read(
            "sp_portal",
            f"sys_id={portal}^ORurl_suffix={portal}",
            "sys_id,title,url_suffix,sp_rectangle_menu,"
            + ",".join(PORTAL_PAGE_FIELDS + PORTAL_THEME_FIELDS),
        )
        if not rows:
            unresolved.append(f"portal:{portal}")
        else:
            row = rows[0]
            portal_info = {
                "sys_id": _plain(row.get("sys_id")),
                "url_suffix": _plain(row.get("url_suffix")),
                "title": _plain(row.get("title")),
            }
            for f in PORTAL_PAGE_FIELDS:
                pid = _plain(row.get(f))
                if pid and pid not in page_sys_ids:
                    page_sys_ids.append(pid)
            theme_ids = [_plain(row.get(f)) for f in PORTAL_THEME_FIELDS if _plain(row.get(f))]
            if theme_ids:
                for t in walk.read(
                    "sp_theme",
                    f"sys_idIN{','.join(theme_ids)}",
                    "sys_id,name,header,footer,sys_scope.scope",
                ):
                    themes.append(
                        {
                            "sys_id": _plain(t.get("sys_id")),
                            "name": _plain(t.get("name")),
                            "scope": _plain(t.get("sys_scope.scope")),
                        }
                    )
                    add_widget(_plain(t.get("header")), "theme header")
                    add_widget(_plain(t.get("footer")), "theme footer")
            menu = _plain(row.get("sp_rectangle_menu"))
            if menu:
                for m in walk.read("sp_instance_menu", f"sys_id={menu}", "sys_id,sp_widget"):
                    add_widget(_plain(m.get("sp_widget")), "main menu")

    requested_pages = [p.strip() for p in (page_ids or []) if p and p.strip()]
    if requested_pages:
        joined = ",".join(requested_pages)
        found = walk.read("sp_page", f"sys_idIN{joined}^ORidIN{joined}", "sys_id,id")
        matched = set()
        for r in found:
            sid, pid = _plain(r.get("sys_id")), _plain(r.get("id"))
            matched.update({sid, pid})
            if sid and sid not in page_sys_ids:
                page_sys_ids.append(sid)
        unresolved.extend(f"page:{p}" for p in requested_pages if p not in matched)

    pages: List[Dict[str, str]] = []
    if page_sys_ids:
        pages = [
            {"sys_id": _plain(r.get("sys_id")), "id": _plain(r.get("id"))}
            for r in walk.read("sp_page", f"sys_idIN{','.join(page_sys_ids)}", "sys_id,id")
        ]
        page_label = {p["sys_id"]: p["id"] for p in pages}
        containers = walk.read(
            "sp_container", f"sp_pageIN{','.join(page_sys_ids)}", "sys_id,sp_page"
        )
        container_page = {_plain(c.get("sys_id")): _plain(c.get("sp_page")) for c in containers}
        frontier = (
            walk.read("sp_row", f"sp_containerIN{','.join(container_page)}", "sys_id,sp_container")
            if container_page
            else []
        )
        row_page = {
            _plain(r.get("sys_id")): container_page.get(_plain(r.get("sp_container")), "")
            for r in frontier
        }
        seen_rows = set(row_page)
        depth = 0
        while frontier and depth < _MAX_DEPTH:
            depth += 1
            row_ids = _ids(frontier)
            columns = walk.read("sp_column", f"sp_rowIN{','.join(row_ids)}", "sys_id,sp_row")
            column_page = {
                _plain(c.get("sys_id")): row_page.get(_plain(c.get("sp_row")), "") for c in columns
            }
            if not column_page:
                break
            col_list = ",".join(column_page)
            for inst in walk.read("sp_instance", f"sp_columnIN{col_list}", "sp_widget,sp_column"):
                page = page_label.get(column_page.get(_plain(inst.get("sp_column")), ""), "")
                add_widget(_plain(inst.get("sp_widget")), f"page {page}".strip())
            nested = [
                r
                for r in walk.read("sp_row", f"sp_columnIN{col_list}", "sys_id,sp_column")
                if _plain(r.get("sys_id")) not in seen_rows
            ]
            for r in nested:
                rid = _plain(r.get("sys_id"))
                seen_rows.add(rid)
                row_page[rid] = column_page.get(_plain(r.get("sp_column")), "")
            frontier = nested
        if frontier and depth >= _MAX_DEPTH:
            walk.complete = False
            walk.warnings.append(
                f"INCOMPLETE — layout nesting deeper than {_MAX_DEPTH} levels was not walked."
            )

    if unresolved:
        walk.warnings.append("Not found: " + ", ".join(unresolved))

    return {
        "widget_sys_ids": widget_ids,
        "widget_source": widget_source,
        "pages": pages,
        "portal": portal_info,
        "themes": themes,
        "unresolved": unresolved,
        "complete": walk.complete and not unresolved,
        "warnings": walk.warnings,
    }
