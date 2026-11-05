"""Service catalog (sc_category, sc_cat_item, item_option_new) service layer.

Business logic for create_category / update_category / update_item /
move_items / create_variable / update_variable operations, plus item
authoring (create_item / copy_item / variable sets / choices / client scripts).
``manage_catalog`` in tools/catalog_tools.py is the sole public entry point.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services.choices import resolve_choice
from servicenow_mcp.tools._preview import build_create_preview, build_update_preview
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
    catalog_item_id: Optional[str] = None,
    variable_set: Optional[str] = None,
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
    map_to_field: Optional[bool] = None,
    target_field: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Add a form variable to a catalog item OR to a variable set (exactly one)."""
    if bool(catalog_item_id) == bool(variable_set):
        return {
            "success": False,
            "message": "Exactly one of catalog_item_id or variable_set is required",
        }
    if variable_set:
        refusal = _writable_target(config, auth_manager, "item_option_new_set", variable_set)
        if refusal is not None:
            return refusal
    type_code, refusal = resolve_variable_type(config, auth_manager, variable_type)
    if refusal is not None:
        return refusal
    data: Dict[str, Any] = {
        "cat_item" if catalog_item_id else "variable_set": catalog_item_id or variable_set,
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
    if map_to_field is not None:
        data["map_to_field"] = str(map_to_field).lower()
    if target_field:
        data["field"] = target_field

    if dry_run:
        return build_create_preview(table="item_option_new", proposed=data)

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


# ---------------------------------------------------------------------------
# Item authoring — create_item, copy_item, variable sets, choices, client scripts
# ---------------------------------------------------------------------------

_IO_REF = re.compile(r"IO:([0-9a-fA-F]{32})")

_ITEM_COPY_FIELDS = (
    "short_description",
    "description",
    "category",
    "sc_catalogs",
    "flow_designer_flow",
    "workflow",
    "delivery_plan",
)
_VAR_COPY_FIELDS = (
    "name",
    "question_text",
    "type",
    "order",
    "mandatory",
    "default_value",
    "reference",
    "reference_qual",
    "active",
    "help_text",
    "description",
    "attributes",
    "scale_min",
    "scale_max",
    "read_only",
    "hidden",
    "tooltip",
    "instructions",
    "choice_table",
    "choice_field",
    "choice_direction",
)
_CHOICE_COPY_FIELDS = ("text", "value", "order", "inactive")
_POLICY_COPY_FIELDS = (
    "short_description",
    "applies_catalog",
    "applies_req_item",
    "applies_sc_task",
    "applies_target_record",
    "active",
    "order",
    "on_load",
    "reverse_if_false",
    "run_scripts",
    "script_true",
    "script_false",
)
_POLICY_ACTION_COPY_FIELDS = ("order", "mandatory", "visible", "disabled", "cleared")
_SCRIPT_COPY_FIELDS = (
    "name",
    "type",
    "ui_type",
    "script",
    "active",
    "applies_to",
    "applies_catalog",
    "applies_req_item",
    "applies_sc_task",
)


class _WriteFailed(Exception):
    def __init__(self, table: str, old_id: str, message: str):
        super().__init__(message)
        self.table, self.old_id, self.message = table, old_id, message


def _jheaders(auth_manager: AuthManager) -> Dict[str, str]:
    headers = auth_manager.get_headers()
    headers["Accept"] = "application/json"
    headers["Content-Type"] = "application/json"
    return headers


def _table_write(
    config: ServerConfig,
    auth_manager: AuthManager,
    method: str,
    table: str,
    body: Optional[Dict[str, Any]] = None,
    sys_id: Optional[str] = None,
) -> Dict[str, Any]:
    """POST/PATCH/DELETE one row; raises on failure. Returns the ``result`` dict."""
    url = f"{config.instance_url}/api/now/table/{table}" + (f"/{sys_id}" if sys_id else "")
    kwargs: Dict[str, Any] = {"headers": _jheaders(auth_manager), "timeout": config.timeout}
    if body is not None:
        kwargs["json"] = body
    response = auth_manager.make_request(method, url, **kwargs)
    response.raise_for_status()
    invalidate_query_cache(table=table)
    if method == "DELETE":
        return {}
    return response.json().get("result", {}) or {}


def _rows(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    truncated: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Raising read of up to ``_FULL_CAP`` rows; a full page is recorded in ``truncated``."""
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=_FULL_CAP,
        offset=0,
        display_value="all",
        fail_silently=False,
    )
    if truncated is not None and len(rows) >= _FULL_CAP:
        truncated.append(table)
    return rows


def _reread(
    config: ServerConfig, auth_manager: AuthManager, table: str, sys_id: str, fields: str
) -> Optional[Dict[str, Any]]:
    """Read the record back after a write; None when it cannot be read (not 'absent')."""
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=f"sys_id={sys_id}",
            fields=fields,
            limit=1,
            offset=0,
            display_value="all",
            no_count=True,
            fail_silently=False,
        )
    except Exception:
        return None
    if not rows:
        return None
    return {k: _rv(v) for k, v in rows[0].items()}


def _is_customer_package(pkg_value: str, pkg_label: str, scope_label: str) -> bool:
    """Heuristic: empty package, a scoped (x_) customer app, or one named like its scope."""
    if not pkg_value:
        return True
    low = f"{pkg_label} {scope_label}".lower()
    if "x_" in low:
        return True
    return bool(scope_label) and pkg_label.strip().lower() == scope_label.strip().lower()


def _writable_target(
    config: ServerConfig, auth_manager: AuthManager, table: str, sys_id: str
) -> Optional[Dict[str, Any]]:
    """Refusal dict when ``sys_id`` in ``table`` is OOTB/protected or cannot be read, else None.

    This client never edits OOTB in place. An unreadable or missing target is a
    refusal, not a pass.
    """
    try:
        rows = _rows(
            config,
            auth_manager,
            table,
            f"sys_id={sys_id}",
            "sys_id,sys_policy,sys_package,sys_scope",
        )
    except Exception as e:
        return {
            "success": False,
            "error": "TARGET_UNREADABLE",
            "message": f"Could not read {table} {sys_id} to check it is not OOTB: {e}",
        }
    if not rows:
        return {
            "success": False,
            "error": "TARGET_NOT_FOUND",
            "message": f"{table} {sys_id} not found; nothing was written",
        }
    row = rows[0]
    policy = str(_rv(row.get("sys_policy"))).strip().lower()
    if policy in ("read", "protected"):
        return {
            "success": False,
            "error": "OOTB_PROTECTED",
            "message": (
                f"{table} {sys_id} is protected (sys_policy='{policy}'); this client never "
                "edits OOTB records in place. Copy it and edit the copy."
            ),
        }
    pkg_v, pkg_l = str(_rv(row.get("sys_package"))), str(_dv(row.get("sys_package")))
    scope_l = str(_dv(row.get("sys_scope")))
    if not _is_customer_package(pkg_v, pkg_l, scope_l):
        return {
            "success": False,
            "error": "OOTB_PACKAGE",
            "message": (
                f"{table} {sys_id} belongs to package '{pkg_l}' (scope '{scope_l}'), not a "
                "customer package; this client never edits OOTB records in place."
            ),
        }
    return None


def _fail(prefix: str, e: Exception) -> Dict[str, Any]:
    logger.error(f"{prefix}: {e}")
    return {"success": False, "message": f"{prefix}: {e}"}


def create_item(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    short_description: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    sc_catalogs: Optional[str] = None,
    active: bool = False,
    flow_designer_flow: Optional[str] = None,
    workflow: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create an sc_cat_item (inactive by default). flow_designer_flow and workflow are exclusive."""
    if flow_designer_flow and workflow:
        return {
            "success": False,
            "error": "ENGINE_CONFLICT",
            "message": "Set flow_designer_flow or workflow, not both",
        }
    body: Dict[str, Any] = {"name": name, "active": str(active).lower()}
    for k, v in (
        ("short_description", short_description),
        ("description", description),
        ("category", category),
        ("sc_catalogs", sc_catalogs),
        ("flow_designer_flow", flow_designer_flow),
        ("workflow", workflow),
    ):
        if v:
            body[k] = v
    if dry_run:
        return build_create_preview(table="sc_cat_item", proposed=body)
    try:
        result = _table_write(config, auth_manager, "POST", "sc_cat_item", body)
    except Exception as e:
        return _fail("Error creating catalog item", e)
    sys_id = result.get("sys_id", "")
    proof = _reread(
        config,
        auth_manager,
        "sc_cat_item",
        sys_id,
        "sys_id,name,short_description,category,sc_catalogs,active,flow_designer_flow,workflow",
    )
    return {
        "success": True,
        "message": f"Created catalog item '{name}' (active={str(active).lower()})",
        "sys_id": sys_id,
        "verified": proof is not None,
        "record": proof,
    }


def create_record_producer(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    table_name: str,
    short_description: Optional[str] = None,
    category: Optional[str] = None,
    sc_catalogs: Optional[str] = None,
    script: Optional[str] = None,
    active: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create an sc_cat_item_producer (inactive by default) that inserts into ``table_name``."""
    try:
        found = _rows(config, auth_manager, "sys_db_object", f"name={table_name}", "name")
    except Exception as e:
        return {
            "success": False,
            "error": "TABLE_UNVERIFIED",
            "message": f"Could not check that table '{table_name}' exists: {e}. Nothing was written.",
        }
    if not any(str(_rv(r.get("name"))) == table_name for r in found):
        return {
            "success": False,
            "error": "TABLE_NOT_FOUND",
            "message": f"Table '{table_name}' does not exist; nothing was written.",
        }
    body: Dict[str, Any] = {
        "name": name,
        "table_name": table_name,
        "active": str(active).lower(),
    }
    for k, v in (
        ("short_description", short_description),
        ("category", category),
        ("sc_catalogs", sc_catalogs),
        ("script", script),
    ):
        if v:
            body[k] = v
    if dry_run:
        return build_create_preview(table="sc_cat_item_producer", proposed=body)
    try:
        result = _table_write(config, auth_manager, "POST", "sc_cat_item_producer", body)
    except Exception as e:
        return _fail("Error creating record producer", e)
    sys_id = result.get("sys_id", "")
    proof = _reread(
        config,
        auth_manager,
        "sc_cat_item_producer",
        sys_id,
        "sys_id,name,short_description,category,sc_catalogs,active,table_name,script",
    )
    return {
        "success": True,
        "message": f"Created record producer '{name}' -> {table_name} (active={str(active).lower()})",
        "sys_id": sys_id,
        "verified": proof is not None,
        "record": proof,
    }


def _remap_io(text: str, idmap: Dict[str, str], unmapped: set) -> str:
    def sub(m: "re.Match[str]") -> str:
        old = m.group(1)
        if old in idmap:
            return "IO:" + idmap[old]
        unmapped.add(old)
        return m.group(0)

    return _IO_REF.sub(sub, text or "")


def _copy_body(row: Dict[str, Any], fields: Tuple[str, ...]) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    for f in fields:
        v = _rv(row.get(f))
        if v not in ("", None):
            body[f] = v
    return body


def copy_item(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    item_id: str,
    name: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Copy an item with its variables, choices, set links, UI policies and client scripts.

    Everything is READ first (a read failure writes nothing); then written in
    order. A write failure stops the copy and reports what exists — no rollback.
    """
    truncated: List[str] = []
    try:
        src_rows = _rows(
            config,
            auth_manager,
            "sc_cat_item",
            f"sys_id={item_id}",
            "sys_id," + ",".join(_ITEM_COPY_FIELDS),
        )
        if not src_rows:
            return {
                "success": False,
                "error": "SOURCE_NOT_FOUND",
                "message": f"{item_id} not found",
            }
        src = src_rows[0]
        variables = _rows(
            config,
            auth_manager,
            "item_option_new",
            f"cat_item={item_id}^ORDERBYorder",
            "sys_id," + ",".join(_VAR_COPY_FIELDS),
            truncated,
        )
        var_ids = [_rv(v.get("sys_id")) for v in variables]
        choices: List[Dict[str, Any]] = []
        for ch in _chunks(var_ids):
            choices += _rows(
                config,
                auth_manager,
                "question_choice",
                f"questionIN{','.join(ch)}",
                "sys_id,question," + ",".join(_CHOICE_COPY_FIELDS),
                truncated,
            )
        links = _rows(
            config,
            auth_manager,
            "io_set_item",
            f"sc_cat_item={item_id}",
            "sys_id,variable_set,order",
            truncated,
        )
        policies = _rows(
            config,
            auth_manager,
            "catalog_ui_policy",
            f"catalog_item={item_id}",
            "sys_id,catalog_conditions," + ",".join(_POLICY_COPY_FIELDS),
            truncated,
        )
        pol_ids = [_rv(p.get("sys_id")) for p in policies]
        actions: List[Dict[str, Any]] = []
        for ch in _chunks(pol_ids):
            actions += _rows(
                config,
                auth_manager,
                "catalog_ui_policy_action",
                f"ui_policyIN{','.join(ch)}",
                "sys_id,ui_policy,catalog_variable,variable,"
                + ",".join(_POLICY_ACTION_COPY_FIELDS),
                truncated,
            )
        scripts = _rows(
            config,
            auth_manager,
            "catalog_script_client",
            f"cat_item={item_id}",
            "sys_id,cat_variable," + ",".join(_SCRIPT_COPY_FIELDS),
            truncated,
        )
    except Exception as e:
        return _fail("Could not read the source item; nothing was written", e)
    if truncated:
        return {
            "success": False,
            "error": "SOURCE_READ_INCOMPLETE",
            "message": (
                f"Read of {sorted(set(truncated))} hit the {_FULL_CAP}-row cap, so the copy "
                "could not be proven complete; nothing was written"
            ),
        }

    skipped: List[Dict[str, str]] = []
    item_body: Dict[str, Any] = {"name": name, "active": "false"}
    item_body.update(_copy_body(src, _ITEM_COPY_FIELDS))
    if item_body.get("flow_designer_flow") and item_body.get("workflow"):
        item_body.pop("workflow")
        skipped.append(
            {
                "table": "sc_cat_item",
                "id": item_id,
                "reason": "source has both flow_designer_flow and workflow; copied the flow only",
            }
        )

    plan = {
        "item_option_new": len(variables),
        "question_choice": len(choices),
        "io_set_item": len(links),
        "catalog_ui_policy": len(policies),
        "catalog_ui_policy_action": len(actions),
        "catalog_script_client": len(scripts),
    }
    if dry_run:
        preview = build_create_preview(table="sc_cat_item", proposed=item_body)
        preview["operation"] = "copy_item"
        preview["source_item"] = item_id
        preview["would_copy"] = plan
        preview["skipped"] = skipped
        return preview

    created: Dict[str, List[Dict[str, str]]] = {}
    idmap: Dict[str, str] = {}
    unmapped: set = set()

    def post(table: str, old_id: str, body: Dict[str, Any]) -> str:
        try:
            new_id = _table_write(config, auth_manager, "POST", table, body).get("sys_id", "")
        except Exception as e:
            raise _WriteFailed(table, old_id, str(e)) from e
        if not new_id:
            raise _WriteFailed(table, old_id, "POST returned no sys_id")
        created.setdefault(table, []).append({"old": old_id, "new": new_id})
        return new_id

    new_item = ""
    try:
        new_item = post("sc_cat_item", item_id, item_body)
        for v in variables:
            old = _rv(v.get("sys_id"))
            body = _copy_body(v, _VAR_COPY_FIELDS)
            body["cat_item"] = new_item
            idmap[old] = post("item_option_new", old, body)
        for c in choices:
            q = _rv(c.get("question"))
            if q not in idmap:
                skipped.append(
                    {
                        "table": "question_choice",
                        "id": _rv(c.get("sys_id")),
                        "reason": "variable not copied",
                    }
                )
                continue
            body = _copy_body(c, _CHOICE_COPY_FIELDS)
            body["question"] = idmap[q]
            post("question_choice", _rv(c.get("sys_id")), body)
        for ln in links:
            body = {"sc_cat_item": new_item, "variable_set": _rv(ln.get("variable_set"))}
            if _rv(ln.get("order")) != "":
                body["order"] = _rv(ln.get("order"))
            post("io_set_item", _rv(ln.get("sys_id")), body)
        pol_map: Dict[str, str] = {}
        for p in policies:
            old = _rv(p.get("sys_id"))
            body = _copy_body(p, _POLICY_COPY_FIELDS)
            cond = _rv(p.get("catalog_conditions"))
            if cond:
                body["catalog_conditions"] = _remap_io(cond, idmap, unmapped)
            body["catalog_item"] = new_item
            pol_map[old] = post("catalog_ui_policy", old, body)
        for a in actions:
            pol = _rv(a.get("ui_policy"))
            if pol not in pol_map:
                skipped.append(
                    {
                        "table": "catalog_ui_policy_action",
                        "id": _rv(a.get("sys_id")),
                        "reason": "ui policy not copied",
                    }
                )
                continue
            body = _copy_body(a, _POLICY_ACTION_COPY_FIELDS)
            cv = _rv(a.get("catalog_variable"))
            if cv:
                body["catalog_variable"] = _remap_io(cv, idmap, unmapped)
            var = _rv(a.get("variable"))
            if var:
                body["variable"] = idmap.get(var, var)
            body["ui_policy"] = pol_map[pol]
            body["catalog_item"] = new_item
            post("catalog_ui_policy_action", _rv(a.get("sys_id")), body)
        for s in scripts:
            body = _copy_body(s, _SCRIPT_COPY_FIELDS)
            cvar = _rv(s.get("cat_variable"))
            if cvar:
                body["cat_variable"] = _remap_io(cvar, idmap, unmapped)
            body["cat_item"] = new_item
            post("catalog_script_client", _rv(s.get("sys_id")), body)
    except _WriteFailed as f:
        return {
            "success": False,
            "error": "COPY_INCOMPLETE",
            "message": (
                f"Copy stopped at {f.table} (source {f.old_id}): {f.message}. Records already "
                "created were left in place (no rollback)."
            ),
            "new_item_id": new_item,
            "created": created,
            "failed": {"table": f.table, "old_id": f.old_id, "error": f.message},
            "skipped": skipped,
        }

    notes = ["Linked variable sets are shared with the source item, not copied."]
    if unmapped:
        notes.append(
            "IO: references to variables outside this item (kept as-is, e.g. set variables): "
            + ", ".join(sorted(unmapped))
        )
    proof = _reread(config, auth_manager, "sc_cat_item", new_item, "sys_id,name,active")
    return {
        "success": True,
        "message": f"Copied item {item_id} to {new_item} (active=false)",
        "new_item_id": new_item,
        "verified": proof is not None,
        "record": proof,
        "created": created,
        "skipped": skipped,
        "notes": notes,
    }


_SET_FIELDS = ("title", "internal_name", "description", "type", "order", "display_title", "layout")


def _set_body(**kw: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    for k, v in kw.items():
        if v is None:
            continue
        body[k] = str(v).lower() if isinstance(v, bool) else v
    return body


def create_variable_set(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    title: str,
    internal_name: str,
    description: Optional[str] = None,
    set_type: Optional[str] = None,
    order: Optional[int] = None,
    display_title: Optional[bool] = None,
    layout: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create an item_option_new_set."""
    body = _set_body(
        title=title,
        internal_name=internal_name,
        description=description,
        type=set_type,
        order=order,
        display_title=display_title,
        layout=layout,
    )
    if dry_run:
        return build_create_preview(table="item_option_new_set", proposed=body)
    try:
        result = _table_write(config, auth_manager, "POST", "item_option_new_set", body)
    except Exception as e:
        return _fail("Error creating variable set", e)
    sys_id = result.get("sys_id", "")
    proof = _reread(
        config, auth_manager, "item_option_new_set", sys_id, "sys_id," + ",".join(_SET_FIELDS)
    )
    return {
        "success": True,
        "message": f"Created variable set '{title}'",
        "sys_id": sys_id,
        "verified": proof is not None,
        "record": proof,
    }


def update_variable_set(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    variable_set: str,
    title: Optional[str] = None,
    internal_name: Optional[str] = None,
    description: Optional[str] = None,
    set_type: Optional[str] = None,
    order: Optional[int] = None,
    display_title: Optional[bool] = None,
    layout: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Update an item_option_new_set (refused when OOTB/protected)."""
    body = _set_body(
        title=title,
        internal_name=internal_name,
        description=description,
        type=set_type,
        order=order,
        display_title=display_title,
        layout=layout,
    )
    if not body:
        return {"success": False, "message": "No update parameters provided"}
    refusal = _writable_target(config, auth_manager, "item_option_new_set", variable_set)
    if refusal is not None:
        return refusal
    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="item_option_new_set",
            sys_id=variable_set,
            proposed=body,
            identifier_fields=["title", "internal_name"],
        )
    try:
        _table_write(config, auth_manager, "PATCH", "item_option_new_set", body, variable_set)
    except Exception as e:
        return _fail("Error updating variable set", e)
    proof = _reread(
        config,
        auth_manager,
        "item_option_new_set",
        variable_set,
        "sys_id," + ",".join(_SET_FIELDS),
    )
    return {
        "success": True,
        "message": f"Updated variable set {variable_set}",
        "sys_id": variable_set,
        "verified": proof is not None,
        "record": proof,
    }


def attach_variable_set(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    catalog_item_id: str,
    variable_set: str,
    order: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Link a variable set to an item via io_set_item (idempotent)."""
    refusal = _writable_target(config, auth_manager, "sc_cat_item", catalog_item_id)
    if refusal is not None:
        return refusal
    try:
        if not _rows(
            config, auth_manager, "item_option_new_set", f"sys_id={variable_set}", "sys_id"
        ):
            return {
                "success": False,
                "error": "SET_NOT_FOUND",
                "message": f"variable set {variable_set} not found; nothing was written",
            }
        existing = _rows(
            config,
            auth_manager,
            "io_set_item",
            f"sc_cat_item={catalog_item_id}^variable_set={variable_set}",
            "sys_id,order",
        )
    except Exception as e:
        return _fail("Could not read the current links; nothing was written", e)
    if existing:
        return {
            "success": True,
            "already_attached": True,
            "message": "Variable set is already attached; nothing written",
            "link_ids": [_rv(r.get("sys_id")) for r in existing],
        }
    body: Dict[str, Any] = {"sc_cat_item": catalog_item_id, "variable_set": variable_set}
    if order is not None:
        body["order"] = str(order)
    if dry_run:
        return build_create_preview(table="io_set_item", proposed=body)
    try:
        result = _table_write(config, auth_manager, "POST", "io_set_item", body)
    except Exception as e:
        return _fail("Error attaching variable set", e)
    link_id = result.get("sys_id", "")
    proof = _reread(
        config, auth_manager, "io_set_item", link_id, "sys_id,sc_cat_item,variable_set,order"
    )
    return {
        "success": True,
        "already_attached": False,
        "message": "Attached variable set",
        "link_id": link_id,
        "verified": proof is not None,
        "record": proof,
    }


def detach_variable_set(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    catalog_item_id: str,
    variable_set: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Delete only the io_set_item row(s) linking the set to the item."""
    refusal = _writable_target(config, auth_manager, "sc_cat_item", catalog_item_id)
    if refusal is not None:
        return refusal
    try:
        links = _rows(
            config,
            auth_manager,
            "io_set_item",
            f"sc_cat_item={catalog_item_id}^variable_set={variable_set}",
            "sys_id",
        )
    except Exception as e:
        return _fail("Could not read the current links; nothing was deleted", e)
    ids = [_rv(r.get("sys_id")) for r in links]
    if not ids:
        return {
            "success": True,
            "not_attached": True,
            "message": "Variable set was not attached; nothing deleted",
        }
    if dry_run:
        return {
            "dry_run": True,
            "operation": "delete",
            "target": {"table": "io_set_item"},
            "would_delete": ids,
            "note": "Only the link rows are deleted; the set and its variables stay.",
        }
    deleted: List[str] = []
    for lid in ids:
        try:
            _table_write(config, auth_manager, "DELETE", "io_set_item", None, lid)
        except Exception as e:
            out = _fail("Error detaching variable set", e)
            out["deleted"] = deleted
            return out
        deleted.append(lid)
    return {"success": True, "message": "Detached variable set", "deleted": deleted}


def _parent_of_variable(
    config: ServerConfig, auth_manager: AuthManager, variable_id: str
) -> Tuple[Optional[Tuple[str, str]], Optional[Dict[str, Any]]]:
    """Return ``((table, id), None)`` for the variable's owner, else ``(None, refusal)``."""
    try:
        rows = _rows(
            config,
            auth_manager,
            "item_option_new",
            f"sys_id={variable_id}",
            "sys_id,cat_item,variable_set",
        )
    except Exception as e:
        return None, _fail("Could not read the variable; nothing was written", e)
    if not rows:
        return None, {
            "success": False,
            "error": "VARIABLE_NOT_FOUND",
            "message": f"variable {variable_id} not found",
        }
    item, vset = _rv(rows[0].get("cat_item")), _rv(rows[0].get("variable_set"))
    if item:
        return ("sc_cat_item", item), None
    if vset:
        return ("item_option_new_set", vset), None
    return None, {
        "success": False,
        "error": "VARIABLE_ORPHAN",
        "message": "variable has neither cat_item nor variable_set; cannot check ownership",
    }


def set_choices(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    variable_id: str,
    choices: List[Dict[str, Any]],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Make a variable's question_choice rows match the desired list; never hard-deletes."""
    if not choices:
        return {"success": False, "message": "choices must be a non-empty list"}
    desired: Dict[str, Dict[str, Any]] = {}
    for i, c in enumerate(choices):
        value, text = c.get("value"), c.get("text")
        if value in (None, "") or text in (None, ""):
            return {"success": False, "message": f"choices[{i}] needs both value and text"}
        value = str(value)
        if value in desired:
            return {"success": False, "message": f"duplicate choice value '{value}'"}
        desired[value] = {
            "value": value,
            "text": str(text),
            "order": str(c["order"]) if c.get("order") is not None else str((i + 1) * 100),
            "inactive": str(bool(c.get("inactive", False))).lower(),
        }
    parent, refusal = _parent_of_variable(config, auth_manager, variable_id)
    if refusal is not None:
        return refusal
    assert parent is not None
    refusal = _writable_target(config, auth_manager, *parent)
    if refusal is not None:
        return refusal
    truncated: List[str] = []
    try:
        current = _rows(
            config,
            auth_manager,
            "question_choice",
            f"question={variable_id}",
            "sys_id,value,text,order,inactive",
            truncated,
        )
    except Exception as e:
        return _fail("Could not read current choices; nothing was written", e)
    if truncated:
        return {
            "success": False,
            "error": "CHOICES_READ_INCOMPLETE",
            "message": "Current choices hit the read cap; cannot compute a complete diff",
        }
    by_value: Dict[str, Dict[str, Any]] = {}
    for r in current:
        v = str(_rv(r.get("value")))
        if v in by_value:
            return {
                "success": False,
                "error": "AMBIGUOUS_CURRENT_CHOICES",
                "message": f"variable already has two choice rows with value '{v}'; fix by hand",
            }
        by_value[v] = r

    adds: List[Dict[str, Any]] = []
    updates: List[Dict[str, Any]] = []
    deactivations: List[Dict[str, Any]] = []
    unchanged = 0
    for v, want in desired.items():
        row = by_value.get(v)
        if row is None:
            adds.append(want)
            continue
        diff = {k: want[k] for k in ("text", "order") if str(_rv(row.get(k))) != want[k]}
        if str(_rv(row.get("inactive"))).lower() != want["inactive"]:
            diff["inactive"] = want["inactive"]
        if diff:
            updates.append({"sys_id": _rv(row.get("sys_id")), "value": v, "changes": diff})
        else:
            unchanged += 1
    for v, row in by_value.items():
        if v not in desired and str(_rv(row.get("inactive"))).lower() != "true":
            deactivations.append({"sys_id": _rv(row.get("sys_id")), "value": v})

    diff_out = {"add": adds, "update": updates, "deactivate": deactivations, "unchanged": unchanged}
    if dry_run:
        return {
            "dry_run": True,
            "operation": "set_choices",
            "variable_id": variable_id,
            "diff": diff_out,
        }

    applied: Dict[str, List[Any]] = {"add": [], "update": [], "deactivate": []}
    try:
        for a in adds:
            body = dict(a, question=variable_id)
            applied["add"].append(
                _table_write(config, auth_manager, "POST", "question_choice", body).get(
                    "sys_id", ""
                )
            )
        for u in updates:
            _table_write(
                config, auth_manager, "PATCH", "question_choice", u["changes"], u["sys_id"]
            )
            applied["update"].append(u["sys_id"])
        for d in deactivations:
            _table_write(
                config, auth_manager, "PATCH", "question_choice", {"inactive": "true"}, d["sys_id"]
            )
            applied["deactivate"].append(d["sys_id"])
    except Exception as e:
        return {
            "success": False,
            "error": "SET_CHOICES_INCOMPLETE",
            "message": f"Stopped part-way: {e}. Rows already written were left in place.",
            "applied": applied,
            "diff": diff_out,
        }
    return {
        "success": True,
        "message": f"Choices set: {len(adds)} added, {len(updates)} updated, "
        f"{len(deactivations)} deactivated",
        "applied": applied,
        "diff": diff_out,
    }


def create_client_script(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    name: str,
    script_type: str,
    script: str,
    catalog_item_id: Optional[str] = None,
    variable_set: Optional[str] = None,
    cat_variable: Optional[str] = None,
    ui_type: Optional[str] = None,
    applies_catalog: Optional[bool] = None,
    applies_req_item: Optional[bool] = None,
    applies_sc_task: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create a catalog_script_client on an item or a variable set."""
    if bool(catalog_item_id) == bool(variable_set):
        return {
            "success": False,
            "message": "Exactly one of catalog_item_id or variable_set is required",
        }
    if script_type not in ("onLoad", "onChange", "onSubmit"):
        return {"success": False, "message": "script_type must be onLoad, onChange or onSubmit"}
    if script_type == "onChange" and not cat_variable:
        return {"success": False, "message": "cat_variable is required for onChange"}
    if catalog_item_id:
        p_table, p_id, p_col = "sc_cat_item", catalog_item_id, "cat_item"
    else:
        p_table, p_id, p_col = "item_option_new_set", str(variable_set), "variable_set"
    refusal = _writable_target(config, auth_manager, p_table, p_id)
    if refusal is not None:
        return refusal
    body: Dict[str, Any] = {
        "name": name,
        "type": script_type,
        "script": script,
        p_col: p_id,
        "active": "true",
    }
    for k, v in (
        ("cat_variable", cat_variable),
        ("ui_type", ui_type),
        ("applies_catalog", applies_catalog),
        ("applies_req_item", applies_req_item),
        ("applies_sc_task", applies_sc_task),
    ):
        if v is not None:
            body[k] = str(v).lower() if isinstance(v, bool) else v
    if dry_run:
        return build_create_preview(table="catalog_script_client", proposed=body)
    try:
        result = _table_write(config, auth_manager, "POST", "catalog_script_client", body)
    except Exception as e:
        return _fail("Error creating catalog client script", e)
    sys_id = result.get("sys_id", "")
    proof = _reread(
        config,
        auth_manager,
        "catalog_script_client",
        sys_id,
        "sys_id,name,type,cat_item,variable_set,cat_variable,active",
    )
    return {
        "success": True,
        "message": f"Created catalog client script '{name}'",
        "sys_id": sys_id,
        "verified": proof is not None,
        "record": proof,
        "next_step": (
            "Later edits to the script body go through download + update_remote_from_local, "
            "not this action."
        ),
    }
