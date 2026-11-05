"""Service catalog (sc_category, sc_cat_item, item_option_new) service layer.

Business logic for create_category / update_category / update_item /
move_items / create_variable / update_variable operations.
``manage_catalog`` in tools/catalog_tools.py is the sole public entry point.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services.choices import resolve_choice
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import (
    SYS_ID_IN_CHUNK,
    count_response,
    invalidate_query_cache,
    sn_query_page,
)
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value

logger = logging.getLogger(__name__)


def create_category(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    title: str,
    description: Optional[str] = None,
    parent: Optional[str] = None,
    icon: Optional[str] = None,
    active: Optional[bool] = None,
    order: Optional[int] = None,
) -> Dict[str, Any]:
    """Create a new service catalog category."""
    url = f"{config.instance_url}/api/now/table/sc_category"
    body: Dict[str, Any] = {"title": title}
    if description is not None:
        body["description"] = description
    if parent is not None:
        body["parent"] = parent
    if icon is not None:
        body["icon"] = icon
    if active is not None:
        body["active"] = str(active).lower()
    if order is not None:
        body["order"] = str(order)

    headers = auth_manager.get_headers()
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("POST", url, headers=headers, json=body)
        response.raise_for_status()
        category = response.json().get("result", {})
        invalidate_query_cache(table="sc_category")
        return {
            "success": True,
            "message": f"Created catalog category: {title}",
            "data": {
                "sys_id": category.get("sys_id", ""),
                "title": category.get("title", ""),
                "description": category.get("description", ""),
                "parent": category.get("parent", ""),
                "icon": category.get("icon", ""),
                "active": category.get("active", ""),
                "order": category.get("order", ""),
            },
        }
    except Exception as e:
        logger.error(f"Error creating catalog category: {e}")
        return {
            "success": False,
            "message": f"Error creating catalog category: {str(e)}",
            "data": None,
        }


def update_category(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    category_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    parent: Optional[str] = None,
    icon: Optional[str] = None,
    active: Optional[bool] = None,
    order: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update an existing service catalog category."""
    body: Dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if description is not None:
        body["description"] = description
    if parent is not None:
        body["parent"] = parent
    if icon is not None:
        body["icon"] = icon
    if active is not None:
        body["active"] = str(active).lower()
    if order is not None:
        body["order"] = str(order)

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sc_category",
            sys_id=category_id,
            proposed=body,
            identifier_fields=["title", "active", "order"],
        )

    url = f"{config.instance_url}/api/now/table/sc_category/{category_id}"
    headers = auth_manager.get_headers()
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("PATCH", url, headers=headers, json=body)
        response.raise_for_status()
        category = response.json().get("result", {})
        invalidate_query_cache(table="sc_category")
        return {
            "success": True,
            "message": f"Updated catalog category: {category_id}",
            "data": {
                "sys_id": category.get("sys_id", ""),
                "title": category.get("title", ""),
                "description": category.get("description", ""),
                "parent": category.get("parent", ""),
                "icon": category.get("icon", ""),
                "active": category.get("active", ""),
                "order": category.get("order", ""),
            },
        }
    except Exception as e:
        logger.error(f"Error updating catalog category: {e}")
        return {
            "success": False,
            "message": f"Error updating catalog category: {str(e)}",
            "data": None,
        }


def update_item(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    item_id: str,
    name: Optional[str] = None,
    short_description: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    price: Optional[str] = None,
    active: Optional[bool] = None,
    order: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update a catalog item by sys_id."""
    body: Dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if short_description is not None:
        body["short_description"] = short_description
    if description is not None:
        body["description"] = description
    if category is not None:
        body["category"] = category
    if price is not None:
        body["price"] = price
    if active is not None:
        body["active"] = str(active).lower()
    if order is not None:
        body["order"] = str(order)

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="sc_cat_item",
            sys_id=item_id,
            proposed=body,
            identifier_fields=["name", "category", "active"],
        )

    url = f"{config.instance_url}/api/now/table/sc_cat_item/{item_id}"
    headers = auth_manager.get_headers()
    headers["Content-Type"] = "application/json"

    try:
        response = auth_manager.make_request("PATCH", url, headers=headers, json=body)
        response.raise_for_status()
        invalidate_query_cache(table="sc_cat_item")
        return {
            "success": True,
            "message": "Catalog item updated successfully",
            "data": response.json()["result"],
        }
    except Exception as e:
        logger.error(f"Error updating catalog item: {e}")
        return {"success": False, "message": f"Error updating catalog item: {str(e)}", "data": None}


def move_items(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    item_ids: List[str],
    target_category_id: str,
) -> Dict[str, Any]:
    """Reassign one or more catalog items to a target category."""
    headers = auth_manager.get_headers()
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"

    success_count = 0
    failed_items: List[Dict[str, Any]] = []

    try:
        for item_id in item_ids:
            item_url = f"{config.instance_url}/api/now/table/sc_cat_item/{item_id}"
            try:
                response = auth_manager.make_request(
                    "PATCH", item_url, headers=headers, json={"category": target_category_id}
                )
                response.raise_for_status()
                success_count += 1
            except Exception as e:
                logger.error(f"Error moving catalog item {item_id}: {e}")
                failed_items.append({"item_id": item_id, "error": str(e)})

        invalidate_query_cache(table="sc_cat_item")

        if success_count == len(item_ids):
            return {
                "success": True,
                "message": f"Successfully moved {success_count} catalog items to category {target_category_id}",
                "data": {"moved_items_count": success_count},
            }
        elif success_count > 0:
            return {
                "success": True,
                "message": f"Partially moved catalog items. {success_count} succeeded, {len(failed_items)} failed.",
                "data": {"moved_items_count": success_count, "failed_items": failed_items},
            }
        else:
            return {
                "success": False,
                "message": "Failed to move any catalog items",
                "data": {"failed_items": failed_items},
            }
    except Exception as e:
        logger.error(f"Error moving catalog items: {e}")
        return {"success": False, "message": f"Error moving catalog items: {str(e)}", "data": None}


def _apply_variable_constraints(
    data: Dict[str, Any],
    *,
    max_length: Any = None,
    min: Any = None,
    max: Any = None,
) -> None:
    """Put length/range constraints where item_option_new actually keeps them.

    None of `max_length`, `min` or `max` is a column on item_option_new —
    filtering on any of them returns all 718 rows, i.e. the condition is dropped.
    Writing them was accepted, ignored, and reported as saved.

    Measured on a live instance:
      * `max_length` lives in the `attributes` string as `max_length=NN`. 14
        variables carry exactly that (`max_length=10`, `=200`, `=255`) on the
        text types — the platform's own convention.
      * `scale_min` / `scale_max` ARE columns, but they are populated on all 718
        rows with the default 0/5: they are the rating-scale range, not a bound
        on text input. They are set only when asked for, and never inferred.
    """
    if max_length:
        existing = str(data.get("attributes") or "")
        clause = f"max_length={max_length}"
        data["attributes"] = f"{existing},{clause}" if existing else clause
    if min is not None:
        data["scale_min"] = min
    if max is not None:
        data["scale_max"] = max


# item_option_new.type is an integer choice (6 = Single Line Text, 8 = Reference,
# ...) declared on its parent table `question`. "string" is not one of them: the
# record was created with a type the form cannot render, and reported success.
def resolve_variable_type(
    config: ServerConfig, auth_manager: AuthManager, requested: str
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Return ``(code, None)`` for a known code or label, else ``(None, refusal)``."""
    return resolve_choice(
        config,
        auth_manager,
        table="question",
        element="type",
        requested=requested,
        unknown_error="UNKNOWN_VARIABLE_TYPE",
        unverified_error="VARIABLE_TYPE_UNVERIFIED",
    )


def create_variable(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    catalog_item_id: str,
    name: str,
    variable_type: str,
    label: str,
    mandatory: bool = False,
    help_text: Optional[str] = None,
    default_value: Optional[str] = None,
    description: Optional[str] = None,
    order: Optional[int] = None,
    reference_table: Optional[str] = None,
    reference_qualifier: Optional[str] = None,
    max_length: Optional[int] = None,
    min: Optional[int] = None,
    max: Optional[int] = None,
) -> Dict[str, Any]:
    """Add a form variable to a catalog item."""
    type_code, refusal = resolve_variable_type(config, auth_manager, variable_type)
    if refusal is not None:
        return refusal
    data: Dict[str, Any] = {
        "cat_item": catalog_item_id,
        "name": name,
        "type": type_code,
        "question_text": label,
        "mandatory": str(mandatory).lower(),
    }
    if help_text:
        data["help_text"] = help_text
    if default_value:
        data["default_value"] = default_value
    if description:
        data["description"] = description
    if order is not None:
        data["order"] = order
    if reference_table:
        data["reference"] = reference_table
    if reference_qualifier:
        data["reference_qual"] = reference_qualifier
    _apply_variable_constraints(data, max_length=max_length, min=min, max=max)

    try:
        response = auth_manager.make_request(
            "POST",
            f"{config.instance_url}/api/now/table/item_option_new",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        result = response.json().get("result", {})
        invalidate_query_cache(table="item_option_new")
        return {
            "success": True,
            "message": "Catalog item variable created successfully",
            "variable_id": result.get("sys_id"),
            "details": result,
        }
    except Exception as e:
        logger.error(f"Failed to create catalog item variable: {e}")
        return {"success": False, "message": f"Failed to create catalog item variable: {str(e)}"}


def update_variable(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    variable_id: str,
    variable_name: Optional[str] = None,
    variable_type: Optional[str] = None,
    reference_table: Optional[str] = None,
    label: Optional[str] = None,
    mandatory: Optional[bool] = None,
    help_text: Optional[str] = None,
    default_value: Optional[str] = None,
    description: Optional[str] = None,
    order: Optional[int] = None,
    reference_qualifier: Optional[str] = None,
    max_length: Optional[int] = None,
    min: Optional[int] = None,
    max: Optional[int] = None,
) -> Dict[str, Any]:
    """Update an existing catalog item variable."""
    data: Dict[str, Any] = {}
    if variable_type is not None:
        type_code, refusal = resolve_variable_type(config, auth_manager, variable_type)
        if refusal is not None:
            return refusal
        data["type"] = type_code
    if variable_name is not None:
        data["name"] = variable_name
    if reference_table is not None:
        data["reference"] = reference_table
    if label is not None:
        data["question_text"] = label
    if mandatory is not None:
        data["mandatory"] = str(mandatory).lower()
    if help_text is not None:
        data["help_text"] = help_text
    if default_value is not None:
        data["default_value"] = default_value
    if description is not None:
        data["description"] = description
    if order is not None:
        data["order"] = order
    if reference_qualifier is not None:
        data["reference_qual"] = reference_qualifier
    _apply_variable_constraints(data, max_length=max_length, min=min, max=max)

    if not data:
        return {"success": False, "message": "No update parameters provided"}

    try:
        response = auth_manager.make_request(
            "PATCH",
            f"{config.instance_url}/api/now/table/item_option_new/{variable_id}",
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()
        result = response.json().get("result", {})
        invalidate_query_cache(table="item_option_new")
        return {
            "success": True,
            "message": "Catalog item variable updated successfully",
            "variable_id": variable_id,
            "details": result,
        }
    except Exception as e:
        logger.error(f"Failed to update catalog item variable: {e}")
        return {"success": False, "message": f"Failed to update catalog item variable: {str(e)}"}


def _page_totals(count: int, server_total: Optional[int], offset: int) -> Dict[str, Any]:
    """`total` is the server's match count, never the size of this page.

    It used to be ``len(page)``: a page of 10 read as "10 in the catalog".
    When the server sends no count, `total` is left out rather than guessed.
    """
    out: Dict[str, Any] = {"count": count}
    if server_total is not None:
        out["total"] = server_total
        if offset + count < server_total:
            out["more"] = f"{server_total - offset - count:,} more; offset={offset + count}"
    else:
        out["total_unknown"] = True
    return out


def list_items(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    active: Optional[bool] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    # See utils/encoded_query.py: a `^` in a caller value stops being a value and
    # becomes query structure, and a condition ServiceNow cannot parse is dropped
    # rather than refused — so the widened query comes back as rows.
    filters = []
    notes = []
    if active:
        filters.append("active=true")
    if category:
        safe_category = safe_value(category)
        filters.append(f"category={safe_category.value}")
        if safe_category.changed:
            notes.append(safe_category.note(field="category"))
    if query:
        safe_q = safe_value(query)
        filters.append(f"short_descriptionLIKE{safe_q.value}^ORnameLIKE{safe_q.value}")
        if safe_q.changed:
            notes.append(safe_q.note(field="query"))
    qs = "^".join(filters)
    if count_only:
        return count_response(config, auth_manager, "sc_cat_item", qs, what="catalog items")
    try:
        records, server_total = sn_query_page(
            config,
            auth_manager,
            table="sc_cat_item",
            query=qs,
            fields="sys_id,name,short_description,category,price,picture,active,order",
            limit=min(limit, 100),
            offset=offset,
            display_value=True,
            fail_silently=False,
        )
        items = [
            {
                "sys_id": r.get("sys_id", ""),
                "name": r.get("name", ""),
                "short_description": r.get("short_description", ""),
                "category": r.get("category", ""),
                "price": r.get("price", ""),
                "active": r.get("active", ""),
                "order": r.get("order", ""),
            }
            for r in records
        ]
        answer: Dict[str, Any] = {
            "success": True,
            "message": f"Retrieved {len(items)} catalog items",
            "items": items,
            **_page_totals(len(items), server_total, offset),
            "limit": limit,
            "offset": offset,
        }
        # Said, not silent: a cleaned filter searched for something other than
        # what the caller typed.
        if notes:
            answer["filter_notes"] = notes
        return answer
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "items": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }


def get_item(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    item_id: str,
    detail: str = "summary",
) -> Dict[str, Any]:
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="sc_cat_item",
            query=f"sys_id={item_id}",
            fields="sys_id,name,short_description,description,category,price,picture,active,order,delivery_time,availability",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if not records:
            return {"success": False, "message": f"Catalog item not found: {item_id}"}
        r = records[0]
        full = detail == "full"
        variables = (
            [] if full else list_item_variables(config, auth_manager, catalog_item_id=item_id)
        )
        out: Dict[str, Any] = {
            "success": True,
            "message": f"Retrieved catalog item: {r.get('name', '')}",
            "data": {
                **{
                    k: r.get(k, "")
                    for k in (
                        "sys_id",
                        "name",
                        "short_description",
                        "description",
                        "category",
                        "price",
                        "active",
                        "order",
                        "delivery_time",
                        "availability",
                    )
                },
                "variables": variables,
            },
        }
        if full:
            out["data"].update(_item_full(config, auth_manager, item_id))
        return out
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}


_FULL_CAP = 500
_VARIABLE_FIELDS = (
    "sys_id,name,question_text,type,mandatory,order,default_value,reference,active,"
    "variable_set,cat_item"
)


def _rv(x: Any) -> Any:
    """Raw value of a display_value='all' cell (or the cell itself)."""
    return x.get("value", "") if isinstance(x, dict) else (x if x is not None else "")


def _dv(x: Any) -> Any:
    """Display value of a display_value='all' cell (or the cell itself)."""
    return x.get("display_value", "") if isinstance(x, dict) else (x if x is not None else "")


def _ref(x: Any) -> Optional[Dict[str, Any]]:
    v = _rv(x)
    return {"sys_id": v, "label": _dv(x)} if v else None


def _chunks(ids: List[str]) -> List[List[str]]:
    return [ids[i : i + SYS_ID_IN_CHUNK] for i in range(0, len(ids), SYS_ID_IN_CHUNK)]


def _read_all(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    queries: List[str],
    fields: str,
    truncated: List[str],
) -> List[Dict[str, Any]]:
    """Run each query (raising on failure), de-duplicated by sys_id."""
    seen: Dict[str, Dict[str, Any]] = {}
    for q in queries:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=q,
            fields=fields,
            limit=_FULL_CAP,
            offset=0,
            display_value="all",
            fail_silently=False,
        )
        if len(rows) >= _FULL_CAP:
            truncated.append(table)
        for r in rows:
            seen.setdefault(_rv(r.get("sys_id")) or str(len(seen)), r)
    return list(seen.values())


def _item_or_set_queries(item_col: str, item_id: str, set_ids: List[str]) -> List[str]:
    """`<col>=item^ORvariable_setIN..` per chunk; the real column goes FIRST."""
    cs = _chunks(set_ids) or [[]]
    return [
        f"{item_col}={item_id}" + (f"^ORvariable_setIN{','.join(c)}" if c else "") + "^ORDERBYorder"
        for c in cs
    ]


def _item_full(config: ServerConfig, auth_manager: AuthManager, item_id: str) -> Dict[str, Any]:
    """detail='full' blocks. A failed read is {checked: False, because}, never []."""
    truncated: List[str] = []
    warnings: List[Dict[str, str]] = []
    out: Dict[str, Any] = {}

    def fail(e: Exception) -> Dict[str, Any]:
        return {"checked": False, "because": str(e) or type(e).__name__}

    # 1 + 2: engine and origin (one record read)
    item: Optional[Dict[str, Any]] = None
    item_err: Optional[Dict[str, Any]] = None
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sc_cat_item",
            query=f"sys_id={item_id}",
            fields=(
                "sys_id,flow_designer_flow,workflow,delivery_plan,sys_scope,sys_package,"
                "sys_policy,sys_class_name"
            ),
            limit=1,
            offset=0,
            display_value="all",
            fail_silently=False,
        )
        item = rows[0] if rows else None
        if item is None:
            item_err = {"checked": False, "because": "item not returned by the engine/origin read"}
    except Exception as e:
        item_err = fail(e)

    if item is None:
        out["engine"] = out["origin"] = item_err
    else:
        engine = {k: _ref(item.get(k)) for k in ("flow_designer_flow", "workflow", "delivery_plan")}
        out["engine"] = engine
        live = [k for k, v in engine.items() if v]
        if len(live) > 1:
            warnings.append(
                {
                    "code": "MULTIPLE_FULFILMENT_ENGINES",
                    "message": (
                        f"{' and '.join(live)} both set; which runs is decided by the "
                        "platform - confirm on a RITM via sys_flow_context / wf_context"
                    ),
                }
            )
        cls = _rv(item.get("sys_class_name"))
        origin: Dict[str, Any] = {
            "sys_scope": _ref(item.get("sys_scope")),
            "sys_package": _ref(item.get("sys_package")),
            "sys_policy": _rv(item.get("sys_policy")),
            "sys_class_name": cls,
        }
        if cls == "sc_cat_item_producer":
            try:
                prow, _ = sn_query_page(
                    config,
                    auth_manager,
                    table="sc_cat_item_producer",
                    query=f"sys_id={item_id}",
                    fields="sys_id,table_name,script",
                    limit=1,
                    offset=0,
                    display_value="all",
                    fail_silently=False,
                )
                if prow:
                    origin["producer"] = {
                        "table_name": _rv(prow[0].get("table_name")),
                        "script_length": len(str(_rv(prow[0].get("script")) or "")),
                    }
                else:
                    origin["producer"] = {"checked": False, "because": "producer row not returned"}
            except Exception as e:
                origin["producer"] = fail(e)
        out["origin"] = origin

    # 3: variable sets
    sets: List[Dict[str, Any]] = []
    sets_ok = True
    try:
        links = _read_all(
            config,
            auth_manager,
            "io_set_item",
            [f"sc_cat_item={item_id}^ORDERBYorder"],
            "sys_id,sc_cat_item,variable_set,order",
            truncated,
        )
        order_of = {_rv(r.get("variable_set")): _rv(r.get("order")) for r in links}
        ids = [i for i in order_of if i]
        set_rows: List[Dict[str, Any]] = []
        for c in _chunks(ids):
            rows, _ = sn_query_page(
                config,
                auth_manager,
                table="item_option_new_set",
                query=f"sys_idIN{','.join(c)}",
                fields="sys_id,title,internal_name,type,order",
                limit=_FULL_CAP,
                offset=0,
                display_value="all",
                fail_silently=False,
            )
            set_rows += rows
        found = {_rv(r.get("sys_id")) for r in set_rows}
        for r in set_rows:
            sid = _rv(r.get("sys_id"))
            sets.append(
                {
                    "sys_id": sid,
                    "title": _rv(r.get("title")),
                    "internal_name": _rv(r.get("internal_name")),
                    "type": _rv(r.get("type")),
                    "order": _rv(r.get("order")),
                    "item_order": order_of.get(sid, ""),
                }
            )
        missing = [i for i in ids if i not in found]
        if missing:
            # a linked set we could not describe still has variables to read
            sets += [{"sys_id": i, "unreadable": True} for i in missing]
        out["variable_sets"] = sets
    except Exception as e:
        sets_ok = False
        out["variable_sets"] = fail(e)
    set_ids = [s["sys_id"] for s in sets]
    set_title = {s["sys_id"]: s.get("title", "") for s in sets}
    blocked = {"checked": False, "because": "variable sets could not be read"}

    # 4: variables
    variables: Optional[List[Dict[str, Any]]] = None
    if not sets_ok:
        out["variables"] = blocked
    else:
        try:
            qs = _item_or_set_queries("cat_item", item_id, set_ids)
            rows = _read_all(
                config, auth_manager, "item_option_new", qs, _VARIABLE_FIELDS, truncated
            )
            variables = []
            absent = set()
            for r in rows:
                absent |= {
                    f
                    for f in (
                        "name question_text type mandatory order default_value reference active"
                    ).split()
                    if f not in r
                }
                vs = _rv(r.get("variable_set"))
                variables.append(
                    {
                        "sys_id": _rv(r.get("sys_id")),
                        "name": _rv(r.get("name")),
                        "question_text": _rv(r.get("question_text")),
                        "type": {"value": _rv(r.get("type")), "label": _dv(r.get("type"))},
                        "mandatory": _rv(r.get("mandatory")),
                        "order": _rv(r.get("order")),
                        "default_value": _rv(r.get("default_value")),
                        "reference": _rv(r.get("reference")),
                        "active": _rv(r.get("active")),
                        "variable_set": vs,
                        **({"variable_set_title": set_title.get(vs, "")} if vs else {}),
                    }
                )
            variables.sort(key=lambda v: (v["variable_set"] != "", str(v["order"]).zfill(8)))
            out["variables"] = variables
            if absent:
                warnings.append(
                    {
                        "code": "VARIABLE_FIELDS_MISSING",
                        "message": "not returned by the server: " + ", ".join(sorted(absent)),
                    }
                )
        except Exception as e:
            out["variables"] = fail(e)

    # 5: choices
    if variables is None:
        out["choices"] = {"checked": False, "because": "variables could not be read"}
    else:
        try:
            # Ask question_choice for every variable: guessing choice types by
            # number or label would silently miss a type that carries choices.
            vname = {v["sys_id"]: v["name"] for v in variables}
            choices: Dict[str, List[Dict[str, Any]]] = {}
            for c in _chunks(list(vname)):
                rows = _read_all(
                    config,
                    auth_manager,
                    "question_choice",
                    [f"questionIN{','.join(c)}^ORDERBYorder"],
                    "sys_id,question,text,value,order,inactive",
                    truncated,
                )
                for r in rows:
                    ch = {
                        "text": _rv(r.get("text")),
                        "value": _rv(r.get("value")),
                        "order": _rv(r.get("order")),
                    }
                    if str(_rv(r.get("inactive"))).lower() == "true":
                        ch["inactive"] = True
                    choices.setdefault(vname.get(_rv(r.get("question")), "?"), []).append(ch)
            out["choices"] = choices
        except Exception as e:
            out["choices"] = fail(e)

    # 6: ui policies + actions
    if not sets_ok:
        out["ui_policies"] = blocked
    else:
        try:
            qs = _item_or_set_queries("catalog_item", item_id, set_ids)
            pols = _read_all(
                config,
                auth_manager,
                "catalog_ui_policy",
                qs,
                "sys_id,short_description,active,order,applies_catalog,applies_req_item,"
                "applies_sc_task,applies_target_record,catalog_conditions,catalog_item,variable_set",
                truncated,
            )
            pids = [_rv(p.get("sys_id")) for p in pols]
            acts: List[Dict[str, Any]] = []
            for c in _chunks(pids):
                acts += _read_all(
                    config,
                    auth_manager,
                    "catalog_ui_policy_action",
                    [f"ui_policyIN{','.join(c)}^ORDERBYorder"],
                    "sys_id,ui_policy,catalog_variable,variable,mandatory,visible,disabled,order",
                    truncated,
                )
            by_policy: Dict[str, List[Dict[str, Any]]] = {}
            for a in acts:
                by_policy.setdefault(_rv(a.get("ui_policy")), []).append(
                    {
                        "catalog_variable": _rv(a.get("catalog_variable")),
                        "variable_label": _dv(a.get("catalog_variable")),
                        "variable": _rv(a.get("variable")),
                        "mandatory": _rv(a.get("mandatory")),
                        "visible": _rv(a.get("visible")),
                        "disabled": _rv(a.get("disabled")),
                        "order": _rv(a.get("order")),
                    }
                )
            out["ui_policies"] = [
                {
                    "sys_id": _rv(p.get("sys_id")),
                    "short_description": _rv(p.get("short_description")),
                    "scope": "variable_set" if _rv(p.get("variable_set")) else "item",
                    **{
                        k: _rv(p.get(k))
                        for k in (
                            "active",
                            "order",
                            "applies_catalog",
                            "applies_req_item",
                            "applies_sc_task",
                            "applies_target_record",
                            "catalog_conditions",
                        )
                    },
                    "actions": by_policy.get(_rv(p.get("sys_id")), []),
                }
                for p in pols
            ]
            # Conditions name variables as IO:<sys_id>; render them by name so the
            # caller never decodes ids by hand. Unknown ids stay as they are.
            names = {v["sys_id"]: v["name"] for v in variables or []}
            for pol in out["ui_policies"]:
                cond = pol.get("catalog_conditions") or ""
                readable = re.sub(
                    r"IO:([0-9a-f]{32})", lambda m: names.get(m.group(1), m.group(0)), cond
                )
                if readable != cond:
                    pol["conditions_readable"] = readable
        except Exception as e:
            out["ui_policies"] = fail(e)

    # 7: client scripts (no bodies)
    if not sets_ok:
        out["client_scripts"] = blocked
    else:
        try:
            qs = _item_or_set_queries("cat_item", item_id, set_ids)
            rows = _read_all(
                config,
                auth_manager,
                "catalog_script_client",
                qs,
                "sys_id,name,type,cat_variable,ui_type,applies_to,applies_catalog,"
                "applies_req_item,applies_sc_task,active,cat_item,variable_set",
                truncated,
            )
            out["client_scripts"] = [
                {
                    "sys_id": _rv(r.get("sys_id")),
                    "name": _rv(r.get("name")),
                    "type": _rv(r.get("type")),
                    "cat_variable": _dv(r.get("cat_variable")),
                    "ui_type": _rv(r.get("ui_type")),
                    "applies_to": _rv(r.get("applies_to")),
                    "applies_catalog": _rv(r.get("applies_catalog")),
                    "applies_req_item": _rv(r.get("applies_req_item")),
                    "applies_sc_task": _rv(r.get("applies_sc_task")),
                    "active": _rv(r.get("active")),
                }
                for r in rows
            ]
            out["client_script_hint"] = (
                "Bodies: download_server_sources(families=['server_scripts']) "
                "(source type catalog_client_script)."
            )
        except Exception as e:
            out["client_scripts"] = fail(e)

    if truncated:
        warnings.append(
            {
                "code": "READ_CAPPED",
                "message": f"{_FULL_CAP}-row cap reached on: {', '.join(sorted(set(truncated)))}",
            }
        )
    if warnings:
        out["warnings"] = warnings
    return out


def list_categories(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    active: Optional[bool] = None,
    query: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
    count_only: bool = False,
) -> Dict[str, Any]:
    filters = []
    notes = []
    if active:
        filters.append("active=true")
    if query:
        safe_q = safe_value(query)
        filters.append(f"titleLIKE{safe_q.value}^ORdescriptionLIKE{safe_q.value}")
        if safe_q.changed:
            notes.append(safe_q.note(field="query"))
    qs = "^".join(filters)
    if count_only:
        return count_response(config, auth_manager, "sc_category", qs, what="catalog categories")
    try:
        records, server_total = sn_query_page(
            config,
            auth_manager,
            table="sc_category",
            query=qs,
            fields="sys_id,title,description,parent,icon,active,order",
            limit=min(limit, 100),
            offset=offset,
            display_value=True,
            fail_silently=False,
        )
        cats = [
            {
                "sys_id": r.get("sys_id", ""),
                "title": r.get("title", ""),
                "description": r.get("description", ""),
                "parent": r.get("parent", ""),
                "icon": r.get("icon", ""),
                "active": r.get("active", ""),
                "order": r.get("order", ""),
            }
            for r in records
        ]
        answer: Dict[str, Any] = {
            "success": True,
            "message": f"Retrieved {len(cats)} catalog categories",
            "categories": cats,
            **_page_totals(len(cats), server_total, offset),
            "limit": limit,
            "offset": offset,
        }
        if notes:
            answer["filter_notes"] = notes
        return answer
    except Exception as e:
        return {
            "success": False,
            "message": str(e),
            "categories": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }


def list_item_variables(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    catalog_item_id: str,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="item_option_new",
            query=f"cat_item={catalog_item_id}^ORDERBYorder",
            fields="sys_id,name,question_text,type,mandatory,default_value,help_text,order",
            limit=min(limit, 100),
            offset=offset,
            display_value=True,
        )
        return [
            {
                "sys_id": v.get("sys_id", ""),
                "name": v.get("name", ""),
                "label": v.get("question_text", ""),
                "type": v.get("type", ""),
                "mandatory": v.get("mandatory", ""),
                "default_value": v.get("default_value", ""),
                "help_text": v.get("help_text", ""),
                "order": v.get("order", ""),
            }
            for v in records
        ]
    except Exception as e:
        logger.error(f"Error getting catalog item variables: {e}")
        return []
