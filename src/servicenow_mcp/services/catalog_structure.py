"""Collect a catalog, category or item's structure as update names for export_record_xml.

Read-only. Moving a catalog by XML means exporting every record under it —
categories, items, link rows, variable sets, variables, choices, UI policies
and their actions, client scripts — and a hand-gathered list is how one gets
left behind. This walks the structure from the server and returns the
``<table>_<sys_id>`` names ``export_record_xml(names=...)`` takes.

Facts measured on a live instance that shape the walk:

- An item's catalogs live in ``sc_cat_item_catalog``. The ``sc_catalogs``
  list column on the item can be EMPTY while the link row exists, so the
  link table is read, never the column.
- An item can sit in a category of ANOTHER catalog; a whole-catalog move must
  not drag that link along (it would point at a category the move does not
  carry), so such links are reported, not exported.
- The update name is keyed by the record's CLASS, not the table read:
  a record producer is ``sc_cat_item_producer_<id>``.
- A record nobody ever customized (untouched baseline) has NO
  ``sys_update_version`` row, so it cannot be exported by update XML at all.
  Every name is checked against the version table before it is offered.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import SYS_ID_IN_CHUNK, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

_PAGE = 500
_MAX_PAGES = 20  # 10 000 rows per query before a table is called truncated
_MAX_CATEGORY_DEPTH = 10
# never-versioned records listed by name; the rest are counted per table
# (a baseline catalog is hundreds of them, and bulk never enters context)
_NO_VERSION_LISTED = 30

# Import order: a parent before what points at it.
_TABLE_ORDER = (
    "sc_catalog",
    "sc_category",
    "sc_cat_item",  # every item class sorts here (see _order_key)
    "item_option_new_set",
    "io_set_item",
    "item_option_new",
    "question_choice",
    "catalog_ui_policy",
    "catalog_ui_policy_action",
    "catalog_script_client",
    "sc_cat_item_category",
    "sc_cat_item_catalog",
    "sc_cat_item_user_criteria_mtom",
    "sc_cat_item_user_criteria_no_mtom",
    "sc_category_user_criteria_mtom",
    "sc_category_user_criteria_no_mtom",
)

_ITEM_UC_LINKS = ("sc_cat_item_user_criteria_mtom", "sc_cat_item_user_criteria_no_mtom")
_CATEGORY_UC_LINKS = ("sc_category_user_criteria_mtom", "sc_category_user_criteria_no_mtom")

NOT_COLLECTED = (
    "Not walked: order guide rules, catalog data lookups, delivery plans, images/"
    "attachments, and the flows/workflows the items run (listed under referenced; "
    "flows ship through their own export)."
)


class _Reader:
    """Raising, fully paged reads. A failed table is recorded, never read as empty."""

    def __init__(self, config: ServerConfig, auth_manager: AuthManager) -> None:
        self.config = config
        self.auth_manager = auth_manager
        self.unread: List[Dict[str, str]] = []
        self.truncated: List[str] = []

    def rows(self, table: str, query: str, fields: str) -> Optional[List[Dict[str, Any]]]:
        out: List[Dict[str, Any]] = []
        try:
            for page in range(_MAX_PAGES):
                rows, _ = sn_query_page(
                    self.config,
                    self.auth_manager,
                    table=table,
                    query=query,
                    fields=fields,
                    limit=_PAGE,
                    offset=page * _PAGE,
                    display_value=False,
                    no_count=True,
                    fail_silently=False,
                )
                out.extend(rows)
                if len(rows) < _PAGE:
                    return out
            self.truncated.append(table)
            return out
        except Exception as e:  # noqa: BLE001 - recorded, surfaces as incomplete
            self.unread.append({"table": table, "because": str(e) or type(e).__name__})
            return None

    def by_ids(
        self, table: str, column: str, ids: Iterable[str], fields: str
    ) -> Optional[List[Dict[str, Any]]]:
        """``column IN ids`` per chunk, de-duplicated by sys_id. One IN per query:
        no OR chain, so an unknown column can never drop the whole filter."""
        id_list = sorted({i for i in ids if i})
        seen: Dict[str, Dict[str, Any]] = {}
        for start in range(0, len(id_list), SYS_ID_IN_CHUNK):
            chunk = id_list[start : start + SYS_ID_IN_CHUNK]
            rows = self.rows(table, f"{column}IN{','.join(chunk)}", fields)
            if rows is None:
                return None
            for r in rows:
                seen.setdefault(_v(r.get("sys_id")), r)
        return list(seen.values())


def _v(x: Any) -> str:
    if isinstance(x, dict):
        x = x.get("value")
    return str(x or "")


def _order_key(table: str, item_tables: Set[str]) -> int:
    if table in item_tables:
        return _TABLE_ORDER.index("sc_cat_item")
    return _TABLE_ORDER.index(table) if table in _TABLE_ORDER else len(_TABLE_ORDER)


def collect_structure(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    catalog_id: Optional[str] = None,
    category_id: Optional[str] = None,
    item_id: Optional[str] = None,
) -> Dict[str, Any]:
    roots = [r for r in (catalog_id, category_id, item_id) if r]
    if len(roots) != 1:
        return {
            "success": False,
            "message": "collect_structure takes exactly one of catalog_id, category_id, item_id.",
        }
    rd = _Reader(config, auth_manager)
    # table -> {sys_id: label}; insertion order kept within a table
    owned: Dict[str, Dict[str, str]] = {}
    referenced: Dict[Tuple[str, str], Dict[str, str]] = {}
    outside_links: List[Dict[str, str]] = []

    def own(table: str, sys_id: str, label: str = "") -> None:
        if sys_id:
            owned.setdefault(table, {}).setdefault(sys_id, label)

    def refer(table: str, sys_id: str, why: str) -> None:
        if sys_id and sys_id not in owned.get(table, {}):
            referenced.setdefault((table, sys_id), {"table": table, "sys_id": sys_id, "why": why})

    # ---- root -------------------------------------------------------------
    categories: Dict[str, Dict[str, Any]] = {}  # sys_id -> {title, parent, depth}
    linked_catalogs: Set[str] = set()  # catalogs whose item links are carried
    item_ids: Set[str] = set()
    root: Dict[str, str]

    if catalog_id:
        rows = rd.rows("sc_catalog", f"sys_id={catalog_id}", "sys_id,title")
        if rows is None:
            return _unreadable_root(rd, "sc_catalog", catalog_id)
        if not rows:
            return _not_found("sc_catalog", catalog_id)
        root = {"table": "sc_catalog", "sys_id": catalog_id, "label": _v(rows[0].get("title"))}
        own("sc_catalog", catalog_id, root["label"])
        linked_catalogs.add(catalog_id)
        cats = rd.rows("sc_category", f"sc_catalog={catalog_id}", "sys_id,title,parent")
        for r in cats or []:
            categories[_v(r.get("sys_id"))] = {
                "title": _v(r.get("title")),
                "parent": _v(r.get("parent")),
            }
        for r in rd.rows("sc_cat_item_catalog", f"sc_catalog={catalog_id}", "sc_cat_item") or []:
            item_ids.add(_v(r.get("sc_cat_item")))
    elif category_id:
        rows = rd.rows("sc_category", f"sys_id={category_id}", "sys_id,title,parent,sc_catalog")
        if rows is None:
            return _unreadable_root(rd, "sc_category", category_id)
        if not rows:
            return _not_found("sc_category", category_id)
        r0 = rows[0]
        root = {"table": "sc_category", "sys_id": category_id, "label": _v(r0.get("title"))}
        categories[category_id] = {"title": root["label"], "parent": ""}
        cat_of = _v(r0.get("sc_catalog"))
        if cat_of:
            linked_catalogs.add(cat_of)
            refer("sc_catalog", cat_of, "the category's catalog; item links to it are carried")
        if _v(r0.get("parent")):
            refer("sc_category", _v(r0.get("parent")), "parent of the root category")
        frontier = [category_id]
        for _depth in range(_MAX_CATEGORY_DEPTH):
            kids = rd.by_ids("sc_category", "parent", frontier, "sys_id,title,parent")
            fresh = [r for r in kids or [] if _v(r.get("sys_id")) not in categories]
            if not fresh:
                break
            for r in fresh:
                categories[_v(r.get("sys_id"))] = {
                    "title": _v(r.get("title")),
                    "parent": _v(r.get("parent")),
                }
            frontier = [_v(r.get("sys_id")) for r in fresh]
        else:
            rd.truncated.append("sc_category (depth)")
    else:
        assert item_id is not None
        root = {"table": "sc_cat_item", "sys_id": item_id, "label": ""}
        item_ids.add(item_id)

    # Categories parent-first, so an import never meets a child before its parent.
    def depth(cid: str) -> int:
        d, seen = 0, set()
        while categories.get(cid, {}).get("parent") in categories and cid not in seen:
            seen.add(cid)
            cid = categories[cid]["parent"]
            d += 1
        return d

    for cid in sorted(categories, key=depth):
        own("sc_category", cid, categories[cid]["title"])

    if categories:
        for r in rd.by_ids("sc_cat_item_category", "sc_category", categories, "sc_cat_item") or []:
            item_ids.add(_v(r.get("sc_cat_item")))
        # The item's own category column, in case a link row was never written.
        for r in rd.by_ids("sc_cat_item", "category", categories, "sys_id") or []:
            item_ids.add(_v(r.get("sys_id")))
    item_ids.discard("")

    # ---- items ------------------------------------------------------------
    item_tables: Set[str] = set()
    items = rd.by_ids(
        "sc_cat_item",
        "sys_id",
        item_ids,
        "sys_id,name,sys_class_name,flow_designer_flow,workflow",
    )
    found_items: Set[str] = set()
    for r in items or []:
        sid = _v(r.get("sys_id"))
        cls = _v(r.get("sys_class_name")) or "sc_cat_item"
        item_tables.add(cls)
        found_items.add(sid)
        own(cls, sid, _v(r.get("name")))
        if item_id and sid == item_id:
            root["table"], root["label"] = cls, _v(r.get("name"))
        if _v(r.get("flow_designer_flow")):
            refer("sys_hub_flow", _v(r.get("flow_designer_flow")), f"flow of item {sid}")
        if _v(r.get("workflow")):
            refer("wf_workflow", _v(r.get("workflow")), f"workflow of item {sid}")
    if item_id and items is not None and item_id not in found_items:
        return _not_found("sc_cat_item", item_id)

    # ---- links: carried when the far end moves too (or the root is one item) --
    whole_item = bool(item_id)
    for r in (
        rd.by_ids(
            "sc_cat_item_category", "sc_cat_item", found_items, "sys_id,sc_cat_item,sc_category"
        )
        or []
    ):
        far = _v(r.get("sc_category"))
        if far in categories or whole_item:
            own("sc_cat_item_category", _v(r.get("sys_id")))
            refer("sc_category", far, "a category the item is placed in")
        else:
            outside_links.append(
                {
                    "table": "sc_cat_item_category",
                    "sys_id": _v(r.get("sys_id")),
                    "item": _v(r.get("sc_cat_item")),
                    "sc_category": far,
                }
            )
    for r in (
        rd.by_ids(
            "sc_cat_item_catalog", "sc_cat_item", found_items, "sys_id,sc_cat_item,sc_catalog"
        )
        or []
    ):
        far = _v(r.get("sc_catalog"))
        if far in linked_catalogs or whole_item:
            own("sc_cat_item_catalog", _v(r.get("sys_id")))
            refer("sc_catalog", far, "a catalog the item is listed in")
        else:
            outside_links.append(
                {
                    "table": "sc_cat_item_catalog",
                    "sys_id": _v(r.get("sys_id")),
                    "item": _v(r.get("sc_cat_item")),
                    "sc_catalog": far,
                }
            )
    for link in _ITEM_UC_LINKS:
        for r in rd.by_ids(link, "sc_cat_item", found_items, "sys_id,user_criteria") or []:
            own(link, _v(r.get("sys_id")))
            refer("user_criteria", _v(r.get("user_criteria")), f"named by {link}")
    for link in _CATEGORY_UC_LINKS:
        for r in rd.by_ids(link, "sc_category", categories, "sys_id,user_criteria") or []:
            own(link, _v(r.get("sys_id")))
            refer("user_criteria", _v(r.get("user_criteria")), f"named by {link}")

    # ---- variable sets, variables, choices ---------------------------------
    set_ids: Set[str] = set()
    for r in rd.by_ids("io_set_item", "sc_cat_item", found_items, "sys_id,variable_set") or []:
        own("io_set_item", _v(r.get("sys_id")))
        set_ids.add(_v(r.get("variable_set")))
    set_ids.discard("")
    for r in rd.by_ids("item_option_new_set", "sys_id", set_ids, "sys_id,title") or []:
        own("item_option_new_set", _v(r.get("sys_id")), _v(r.get("title")))

    def item_or_set(table: str, item_col: str, fields: str) -> List[Dict[str, Any]]:
        got: Dict[str, Dict[str, Any]] = {}
        for col, ids in ((item_col, found_items), ("variable_set", set_ids)):
            for r in rd.by_ids(table, col, ids, fields) or []:
                got.setdefault(_v(r.get("sys_id")), r)
        return list(got.values())

    var_ids: List[str] = []
    for r in item_or_set("item_option_new", "cat_item", "sys_id,name"):
        own("item_option_new", _v(r.get("sys_id")), _v(r.get("name")))
        var_ids.append(_v(r.get("sys_id")))
    for r in rd.by_ids("question_choice", "question", var_ids, "sys_id") or []:
        own("question_choice", _v(r.get("sys_id")))

    # ---- behaviour: UI policies (+ actions), client scripts -----------------
    pol_ids: List[str] = []
    for r in item_or_set("catalog_ui_policy", "catalog_item", "sys_id,short_description"):
        own("catalog_ui_policy", _v(r.get("sys_id")), _v(r.get("short_description")))
        pol_ids.append(_v(r.get("sys_id")))
    for r in rd.by_ids("catalog_ui_policy_action", "ui_policy", pol_ids, "sys_id") or []:
        own("catalog_ui_policy_action", _v(r.get("sys_id")))
    for r in item_or_set("catalog_script_client", "cat_item", "sys_id,name"):
        own("catalog_script_client", _v(r.get("sys_id")), _v(r.get("name")))

    return _result(rd, root, owned, item_tables, referenced, outside_links)


def _result(
    rd: _Reader,
    root: Dict[str, str],
    owned: Dict[str, Dict[str, str]],
    item_tables: Set[str],
    referenced: Dict[Tuple[str, str], Dict[str, str]],
    outside_links: List[Dict[str, str]],
) -> Dict[str, Any]:
    tables = sorted(owned, key=lambda t: _order_key(t, item_tables))
    ordered = [(t, sid, owned[t][sid]) for t in tables for sid in owned[t]]
    names_all = [f"{t}_{sid}" for t, sid, _ in ordered]

    # Decided BEFORE the version check: a failed version read is its own limit
    # (versions_checked), not a missing piece of the structure.
    complete = not rd.unread and not rd.truncated
    structure_unread = list(rd.unread)

    # Which of them can an update XML carry at all?
    have: Set[str] = set()
    versions_checked = True
    for start in range(0, len(names_all), SYS_ID_IN_CHUNK):
        chunk = names_all[start : start + SYS_ID_IN_CHUNK]
        rows = rd.rows("sys_update_version", f"state=current^nameIN{','.join(chunk)}", "name")
        if rows is None:
            versions_checked = False
            break
        have.update(_v(r.get("name")) for r in rows)

    counts: Dict[str, Dict[str, int]] = {}
    no_version: List[Dict[str, str]] = []
    for t, sid, label in ordered:
        c = counts.setdefault(t, {"records": 0})
        c["records"] += 1
        if versions_checked and f"{t}_{sid}" not in have:
            c["no_version"] = c.get("no_version", 0) + 1
            entry = {"name": f"{t}_{sid}"}
            if label:
                entry["label"] = label
            no_version.append(entry)

    names = [n for n in names_all if not versions_checked or n in have]
    out: Dict[str, Any] = {
        "success": True,
        "root": root,
        "complete": complete,
        "tables": counts,
        "record_count": len(names_all),
        "names": names,
        "versions_checked": versions_checked,
        "not_collected": NOT_COLLECTED,
    }
    if structure_unread:
        out["unread"] = structure_unread
    if not versions_checked:
        out["versions_unread"] = rd.unread[len(structure_unread) :]
    if rd.truncated:
        out["truncated"] = sorted(set(rd.truncated))
    if no_version:
        out["no_version"] = no_version[:_NO_VERSION_LISTED]
        if len(no_version) > _NO_VERSION_LISTED:
            out["no_version_more"] = len(no_version) - _NO_VERSION_LISTED
            out["no_version_note"] = (
                f"First {_NO_VERSION_LISTED} of {len(no_version)} listed; tables.*.no_version "
                "counts them all. Narrow the root (category_id / item_id) to list the rest."
            )
    if referenced:
        out["referenced"] = list(referenced.values())
    if outside_links:
        out["outside_links"] = outside_links
        out["outside_links_note"] = (
            "Links from these items to categories/catalogs this walk does not carry. "
            "Not in names: imported alone they would point at records the target may not have."
        )

    if not complete:
        out["next"] = (
            "INCOMPLETE: a read failed or hit its cap (see unread/truncated), so names is "
            "missing records. Do not build the deploy XML from it; fix the read and re-run."
        )
    elif not versions_checked:
        out["next"] = (
            "The version check failed, so it is unknown which names an update XML can "
            "carry. export_record_xml(names=names) still reports any it could not find."
        )
    elif not names:
        out["next"] = (
            "Nothing here can travel by update XML: no record has an update version "
            "(none was ever customized). An untouched baseline record usually exists on "
            "the target already; check it there rather than exporting."
        )
    else:
        out["next"] = (
            "export_record_xml(names=names), then verify_deployment_xml(mode='preflight') "
            "against this (source) instance before import."
        )
        if no_version:
            out["next"] += (
                f" {len(no_version)} record(s) have NO update version (never customized) and "
                "cannot travel by update XML: check they exist on the target, or recreate them."
            )
        if referenced:
            out["next"] += (
                " referenced records are NOT in names: confirm they exist on the target "
                "(same sys_id) before import."
            )
    return out


def _not_found(table: str, sys_id: str) -> Dict[str, Any]:
    return {"success": False, "message": f"No {table} record {sys_id} (or not readable)."}


def _unreadable_root(rd: _Reader, table: str, sys_id: str) -> Dict[str, Any]:
    because = rd.unread[-1]["because"] if rd.unread else "read failed"
    return {
        "success": False,
        "message": f"Could not read {table} {sys_id}: {because}. Nothing was collected.",
    }
