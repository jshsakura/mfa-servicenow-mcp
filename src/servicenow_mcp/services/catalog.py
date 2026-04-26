"""Service catalog (sc_category, sc_cat_item, item_option_new) service layer.

Business logic for create_category / update_category / update_item /
move_items / create_variable / update_variable operations.
``manage_catalog`` in tools/catalog_tools.py is the sole public entry point.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_count, sn_query_page
from servicenow_mcp.utils.config import ServerConfig

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
    data: Dict[str, Any] = {
        "cat_item": catalog_item_id,
        "name": name,
        "type": variable_type,
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
    if max_length:
        data["max_length"] = max_length
    if min is not None:
        data["min"] = min
    if max is not None:
        data["max"] = max

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
    if max_length is not None:
        data["max_length"] = max_length
    if min is not None:
        data["min"] = min
    if max is not None:
        data["max"] = max

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
    filters = []
    if active:
        filters.append("active=true")
    if category:
        filters.append(f"category={category}")
    if query:
        filters.append(f"short_descriptionLIKE{query}^ORnameLIKE{query}")
    qs = "^".join(filters)
    if count_only:
        return {"success": True, "count": sn_count(config, auth_manager, "sc_cat_item", qs)}
    try:
        records, _ = sn_query_page(
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
        return {
            "success": True,
            "message": f"Retrieved {len(items)} catalog items",
            "items": items,
            "total": len(items),
            "limit": limit,
            "offset": offset,
        }
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
        variables = list_item_variables(config, auth_manager, catalog_item_id=item_id)
        return {
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
    except Exception as e:
        return {"success": False, "message": str(e), "data": None}


def list_categories(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    active: Optional[bool] = None,
    query: Optional[str] = None,
    limit: int = 10,
    offset: int = 0,
) -> Dict[str, Any]:
    filters = []
    if active:
        filters.append("active=true")
    if query:
        filters.append(f"titleLIKE{query}^ORdescriptionLIKE{query}")
    qs = "^".join(filters)
    try:
        records, _ = sn_query_page(
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
        return {
            "success": True,
            "message": f"Retrieved {len(cats)} catalog categories",
            "categories": cats,
            "total": len(cats),
            "limit": limit,
            "offset": offset,
        }
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
