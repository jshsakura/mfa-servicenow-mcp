"""
Service Catalog tools for the ServiceNow MCP server.

This module provides tools for querying and viewing the service catalog in ServiceNow.
"""

import logging
from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import catalog as _cat_svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

from .sn_api import sn_query_page

logger = logging.getLogger(__name__)


class CatalogResponse(BaseModel):
    """Response from catalog operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    data: Optional[Dict[str, Any]] = Field(default=None, description="Response data")


def get_catalog_item_variables(
    config: ServerConfig,
    auth_manager: AuthManager,
    item_id: str,
) -> List[Dict[str, Any]]:
    """Get variables for a specific service catalog item."""
    try:
        records, _ = sn_query_page(
            config,
            auth_manager,
            table="item_option_new",
            query=f"cat_item={item_id}^ORDERBYorder",
            fields="sys_id,name,question_text,type,mandatory,default_value,help_text,order",
            limit=100,
            offset=0,
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
        logger.error(f"Error getting catalog item variables: {str(e)}")
        return []


# ---------------------------------------------------------------------------
# manage_catalog — bundled CRUD for categories, items, and variables
# ---------------------------------------------------------------------------

_CATEGORY_UPDATE_FIELDS = ("title", "description", "parent", "icon", "active", "order")
_ITEM_UPDATE_FIELDS = (
    "name",
    "short_description",
    "description",
    "category",
    "price",
    "active",
    "order",
)
_VARIABLE_UPDATE_FIELDS = (
    "variable_name",
    "variable_type",
    "reference_table",
    "label",
    "mandatory",
    "help_text",
    "default_value",
    "description",
    "order",
    "reference_qualifier",
    "max_length",
    "min",
    "max",
)


class ManageCatalogParams(BaseModel):
    """Manage service catalog — categories, items, and item variables.

    Required per action:
      create_category:  title
      update_category:  category_id, at least one field
      update_item:      item_id, at least one field
      move_items:       item_ids, target_category_id
      create_variable:  catalog_item_id, variable_name, variable_type, label
      update_variable:  variable_id, at least one field
    """

    action: Literal[
        "list_items",
        "get_item",
        "list_categories",
        "list_item_variables",
        "create_category",
        "update_category",
        "update_item",
        "move_items",
        "create_variable",
        "update_variable",
    ] = Field(...)

    # read params (list_items/get_item/list_categories/list_item_variables)
    limit: int = Field(default=10, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    query: Optional[str] = Field(default=None, description="Search query")
    count_only: bool = Field(default=False, description="Return count only")

    # category create + update
    category_id: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    parent: Optional[str] = Field(default=None)
    icon: Optional[str] = Field(default=None)
    active: Optional[bool] = Field(default=None)
    order: Optional[int] = Field(default=None)

    # item update
    item_id: Optional[str] = Field(default=None)
    name: Optional[str] = Field(default=None)
    short_description: Optional[str] = Field(default=None)
    category: Optional[str] = Field(default=None)
    price: Optional[str] = Field(default=None)

    # move_items
    item_ids: Optional[List[str]] = Field(default=None)
    target_category_id: Optional[str] = Field(default=None)

    # variable create + update (prefix-renamed to avoid clashing with category fields)
    catalog_item_id: Optional[str] = Field(default=None)
    variable_id: Optional[str] = Field(default=None)
    variable_name: Optional[str] = Field(
        default=None, description="Internal name (create_variable)"
    )
    variable_type: Optional[str] = Field(
        default=None,
        description="Type code or label, checked on sys_choice: 6/Single Line Text, 8/Reference",
    )
    label: Optional[str] = Field(default=None)
    mandatory: Optional[bool] = Field(default=None)
    help_text: Optional[str] = Field(default=None)
    default_value: Optional[str] = Field(default=None)
    reference_table: Optional[str] = Field(default=None)
    reference_qualifier: Optional[str] = Field(default=None)
    max_length: Optional[int] = Field(default=None)
    min: Optional[int] = Field(default=None)
    max: Optional[int] = Field(default=None)

    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list_items": frozenset({"limit", "offset", "query", "count_only", "active", "category"}),
        "get_item": frozenset({"item_id"}),
        "list_categories": frozenset({"limit", "offset", "query", "count_only", "active"}),
        "list_item_variables": frozenset({"catalog_item_id"}),
        "create_category": frozenset(
            {"title", "description", "parent", "icon", "active", "order", "dry_run"}
        ),
        "update_category": frozenset(
            {
                "category_id",
                "title",
                "description",
                "parent",
                "icon",
                "active",
                "order",
                "dry_run",
            }
        ),
        "update_item": frozenset(
            {
                "item_id",
                "name",
                "short_description",
                "category",
                "description",
                "price",
                "active",
                "dry_run",
            }
        ),
        "move_items": frozenset({"item_ids", "target_category_id", "dry_run"}),
        "create_variable": frozenset(
            {
                "description",
                "catalog_item_id",
                "variable_name",
                "variable_type",
                "label",
                "mandatory",
                "help_text",
                "default_value",
                "reference_table",
                "reference_qualifier",
                "max_length",
                "min",
                "max",
                "order",
                "dry_run",
            }
        ),
        "update_variable": frozenset(
            {
                "description",
                "variable_id",
                "variable_name",
                "variable_type",
                "label",
                "mandatory",
                "help_text",
                "default_value",
                "reference_table",
                "reference_qualifier",
                "max_length",
                "min",
                "max",
                "order",
                "dry_run",
            }
        ),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageCatalogParams":
        a = self.action
        if a in ("list_items", "get_item", "list_categories", "list_item_variables"):
            pass
        elif a == "create_category":
            if not self.title:
                raise ValueError("title is required for action='create_category'")
        elif a == "update_category":
            if not self.category_id:
                raise ValueError("category_id is required for action='update_category'")
            if not any(getattr(self, f) is not None for f in _CATEGORY_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update_category'")
        elif a == "update_item":
            if not self.item_id:
                raise ValueError("item_id is required for action='update_item'")
            if not any(getattr(self, f) is not None for f in _ITEM_UPDATE_FIELDS):
                raise ValueError("at least one field must be provided for action='update_item'")
        elif a == "move_items":
            if not self.item_ids:
                raise ValueError("item_ids is required for action='move_items'")
            if not self.target_category_id:
                raise ValueError("target_category_id is required for action='move_items'")
        elif a == "create_variable":
            for f in ("catalog_item_id", "variable_name", "variable_type", "label"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='create_variable'")
        elif a == "update_variable":
            if not self.variable_id:
                raise ValueError("variable_id is required for action='update_variable'")
        return self


@register_tool(
    name="manage_catalog",
    params=ManageCatalogParams,
    description="Catalog category/item/variable CRUD (tables: sc_category, sc_cat_item, item_option_new).",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_catalog(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageCatalogParams,
) -> Dict[str, Any]:
    a = params.action
    if a == "list_items":
        return _cat_svc.list_items(
            config,
            auth_manager,
            active=params.active,
            category=params.category,
            query=params.query,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if a == "get_item":
        if not params.item_id:
            return {"success": False, "message": "item_id is required for action='get_item'"}
        return _cat_svc.get_item(config, auth_manager, item_id=params.item_id)
    if a == "list_categories":
        return _cat_svc.list_categories(
            config,
            auth_manager,
            active=params.active,
            query=params.query,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )
    if a == "list_item_variables":
        if not params.catalog_item_id:
            return {
                "success": False,
                "message": "catalog_item_id is required for action='list_item_variables'",
            }
        return {
            "success": True,
            "variables": _cat_svc.list_item_variables(
                config,
                auth_manager,
                catalog_item_id=params.catalog_item_id,
                limit=params.limit,
                offset=params.offset,
            ),
        }
    if a == "create_category":
        kwargs: Dict[str, Any] = {"title": params.title}
        for f in ("description", "parent", "icon", "active", "order"):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _cat_svc.create_category(config, auth_manager, **kwargs)
    if a == "update_category":
        kwargs = {"category_id": params.category_id, "dry_run": params.dry_run}
        for f in _CATEGORY_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _cat_svc.update_category(config, auth_manager, **kwargs)
    if a == "update_item":
        kwargs = {"item_id": params.item_id, "dry_run": params.dry_run}
        for f in _ITEM_UPDATE_FIELDS:
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _cat_svc.update_item(config, auth_manager, **kwargs)
    if a == "move_items":
        # ManageCatalogParams validator guarantees both are present for move_items.
        assert params.item_ids is not None
        assert params.target_category_id is not None
        return _cat_svc.move_items(
            config,
            auth_manager,
            item_ids=params.item_ids,
            target_category_id=params.target_category_id,
        )
    if a == "create_variable":
        kwargs = {
            "catalog_item_id": params.catalog_item_id,
            "name": params.variable_name,
            "variable_type": params.variable_type,
            "label": params.label,
        }
        for f in (
            "mandatory",
            "help_text",
            "default_value",
            "description",
            "order",
            "reference_table",
            "reference_qualifier",
            "max_length",
            "min",
            "max",
        ):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _cat_svc.create_variable(config, auth_manager, **kwargs)
    # update_variable
    kwargs = {"variable_id": params.variable_id}
    for f in _VARIABLE_UPDATE_FIELDS:
        v = getattr(params, f)
        if v is not None:
            kwargs[f] = v
    return _cat_svc.update_variable(config, auth_manager, **kwargs)
