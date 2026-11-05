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
      create_item:      name (inactive unless active=true; flow_designer_flow XOR workflow)
      create_record_producer: name, table_name (target; checked), script optional (inactive)
      copy_item:        item_id (source), name (new, inactive)
      create_variable_set: title, internal_name
      update_variable_set: variable_set, at least one field
      attach_variable_set / detach_variable_set: catalog_item_id, variable_set
      set_choices:      variable_id, choices [{value,text,order,inactive?}] (full desired list)
      create_client_script: name, script_type, script, catalog_item_id XOR variable_set
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
        "create_item",
        "create_record_producer",
        "copy_item",
        "create_variable_set",
        "update_variable_set",
        "attach_variable_set",
        "detach_variable_set",
        "set_choices",
        "create_client_script",
    ] = Field(...)

    # read params (list_items/get_item/list_categories/list_item_variables)
    limit: int = Field(default=10, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    query: Optional[str] = Field(default=None, description="Search query")
    count_only: bool = Field(default=False, description="Return count only")
    detail: Literal["summary", "full"] = Field(
        default="summary",
        description="get_item: full adds engine, origin, sets, variables, choices, policies, scripts",
    )

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

    table_name: Optional[str] = Field(
        default=None, description="Target table the record producer inserts into"
    )
    map_to_field: Optional[bool] = Field(
        default=None, description="Variable writes a target-table field (record producer)"
    )
    target_field: Optional[str] = Field(
        default=None, description="Target-table column for map_to_field"
    )

    # item / variable-set / choices / client-script authoring
    sc_catalogs: Optional[str] = Field(default=None, description="Catalog sys_ids, comma-separated")
    flow_designer_flow: Optional[str] = Field(
        default=None, description="Flow sys_id (not with workflow)"
    )
    workflow: Optional[str] = Field(default=None, description="Workflow sys_id (not with flow)")
    variable_set: Optional[str] = Field(
        default=None, description="item_option_new_set sys_id (create_variable: instead of item)"
    )
    internal_name: Optional[str] = Field(default=None, description="Variable set internal name")
    set_type: Optional[str] = Field(default=None, description="Variable set type")
    display_title: Optional[bool] = Field(default=None, description="Show set title on form")
    layout: Optional[str] = Field(default=None, description="Variable set layout")
    choices: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Full desired list: {value,text,order?,inactive?}"
    )
    script_type: Optional[Literal["onLoad", "onChange", "onSubmit"]] = Field(default=None)
    script: Optional[str] = Field(default=None, description="Client script body")
    cat_variable: Optional[str] = Field(default=None, description="Variable (onChange)")
    ui_type: Optional[str] = Field(default=None)
    applies_catalog: Optional[bool] = Field(default=None)
    applies_req_item: Optional[bool] = Field(default=None)
    applies_sc_task: Optional[bool] = Field(default=None)

    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list_items": frozenset({"limit", "offset", "query", "count_only", "active", "category"}),
        "get_item": frozenset({"item_id", "detail"}),
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
                "variable_set",
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
                "map_to_field",
                "target_field",
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
        "create_item": frozenset(
            {
                "name",
                "short_description",
                "description",
                "category",
                "sc_catalogs",
                "active",
                "flow_designer_flow",
                "workflow",
                "dry_run",
            }
        ),
        "create_record_producer": frozenset(
            {
                "name",
                "table_name",
                "short_description",
                "category",
                "sc_catalogs",
                "script",
                "active",
                "dry_run",
            }
        ),
        "copy_item": frozenset({"item_id", "name", "dry_run"}),
        "create_variable_set": frozenset(
            {
                "title",
                "internal_name",
                "description",
                "set_type",
                "order",
                "display_title",
                "layout",
                "dry_run",
            }
        ),
        "update_variable_set": frozenset(
            {
                "variable_set",
                "title",
                "internal_name",
                "description",
                "set_type",
                "order",
                "display_title",
                "layout",
                "dry_run",
            }
        ),
        "attach_variable_set": frozenset({"catalog_item_id", "variable_set", "order", "dry_run"}),
        "detach_variable_set": frozenset({"catalog_item_id", "variable_set", "dry_run"}),
        "set_choices": frozenset({"variable_id", "choices", "dry_run"}),
        "create_client_script": frozenset(
            {
                "name",
                "catalog_item_id",
                "variable_set",
                "script_type",
                "cat_variable",
                "ui_type",
                "applies_catalog",
                "applies_req_item",
                "applies_sc_task",
                "script",
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
            for f in ("variable_name", "variable_type", "label"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='create_variable'")
            if bool(self.catalog_item_id) == bool(self.variable_set):
                raise ValueError(
                    "exactly one of catalog_item_id or variable_set is required "
                    "for action='create_variable'"
                )
        elif a == "create_item":
            if not self.name:
                raise ValueError("name is required for action='create_item'")
            if self.flow_designer_flow and self.workflow:
                raise ValueError("set flow_designer_flow or workflow, not both")
        elif a == "create_record_producer":
            for f in ("name", "table_name"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='create_record_producer'")
        elif a == "copy_item":
            for f in ("item_id", "name"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='copy_item'")
        elif a == "create_variable_set":
            for f in ("title", "internal_name"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='create_variable_set'")
        elif a == "update_variable_set":
            if not self.variable_set:
                raise ValueError("variable_set is required for action='update_variable_set'")
            if not any(
                getattr(self, f) is not None
                for f in (
                    "title",
                    "internal_name",
                    "description",
                    "set_type",
                    "order",
                    "display_title",
                    "layout",
                )
            ):
                raise ValueError(
                    "at least one field must be provided for action='update_variable_set'"
                )
        elif a in ("attach_variable_set", "detach_variable_set"):
            for f in ("catalog_item_id", "variable_set"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='{a}'")
        elif a == "set_choices":
            if not self.variable_id:
                raise ValueError("variable_id is required for action='set_choices'")
            if not self.choices:
                raise ValueError("choices is required for action='set_choices'")
        elif a == "create_client_script":
            for f in ("name", "script_type", "script"):
                if not getattr(self, f):
                    raise ValueError(f"{f} is required for action='create_client_script'")
            if bool(self.catalog_item_id) == bool(self.variable_set):
                raise ValueError("exactly one of catalog_item_id or variable_set is required")
            if self.script_type == "onChange" and not self.cat_variable:
                raise ValueError("cat_variable is required for onChange")
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
        return _cat_svc.get_item(config, auth_manager, item_id=params.item_id, detail=params.detail)
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
            "variable_set": params.variable_set,
            "dry_run": params.dry_run,
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
            "map_to_field",
            "target_field",
        ):
            v = getattr(params, f)
            if v is not None:
                kwargs[f] = v
        return _cat_svc.create_variable(config, auth_manager, **kwargs)
    if a == "create_item":
        kwargs = {"name": params.name, "dry_run": params.dry_run}
        for f in (
            "short_description",
            "description",
            "category",
            "sc_catalogs",
            "flow_designer_flow",
            "workflow",
        ):
            if getattr(params, f) is not None:
                kwargs[f] = getattr(params, f)
        if params.active is not None:
            kwargs["active"] = params.active
        return _cat_svc.create_item(config, auth_manager, **kwargs)
    if a == "create_record_producer":
        kwargs = {
            "name": params.name,
            "table_name": params.table_name,
            "dry_run": params.dry_run,
        }
        for f in ("short_description", "category", "sc_catalogs", "script"):
            if getattr(params, f) is not None:
                kwargs[f] = getattr(params, f)
        if params.active is not None:
            kwargs["active"] = params.active
        return _cat_svc.create_record_producer(config, auth_manager, **kwargs)
    if a == "copy_item":
        return _cat_svc.copy_item(
            config,
            auth_manager,
            item_id=str(params.item_id),
            name=str(params.name),
            dry_run=params.dry_run,
        )
    if a in ("create_variable_set", "update_variable_set"):
        kwargs = {"dry_run": params.dry_run}
        for f in (
            "title",
            "internal_name",
            "description",
            "set_type",
            "order",
            "display_title",
            "layout",
        ):
            if getattr(params, f) is not None:
                kwargs[f] = getattr(params, f)
        if a == "create_variable_set":
            return _cat_svc.create_variable_set(config, auth_manager, **kwargs)
        return _cat_svc.update_variable_set(
            config, auth_manager, variable_set=str(params.variable_set), **kwargs
        )
    if a == "attach_variable_set":
        return _cat_svc.attach_variable_set(
            config,
            auth_manager,
            catalog_item_id=str(params.catalog_item_id),
            variable_set=str(params.variable_set),
            order=params.order,
            dry_run=params.dry_run,
        )
    if a == "detach_variable_set":
        return _cat_svc.detach_variable_set(
            config,
            auth_manager,
            catalog_item_id=str(params.catalog_item_id),
            variable_set=str(params.variable_set),
            dry_run=params.dry_run,
        )
    if a == "set_choices":
        return _cat_svc.set_choices(
            config,
            auth_manager,
            variable_id=str(params.variable_id),
            choices=params.choices or [],
            dry_run=params.dry_run,
        )
    if a == "create_client_script":
        return _cat_svc.create_client_script(
            config,
            auth_manager,
            name=str(params.name),
            script_type=str(params.script_type),
            script=str(params.script),
            catalog_item_id=params.catalog_item_id,
            variable_set=params.variable_set,
            cat_variable=params.cat_variable,
            ui_type=params.ui_type,
            applies_catalog=params.applies_catalog,
            applies_req_item=params.applies_req_item,
            applies_sc_task=params.applies_sc_task,
            dry_run=params.dry_run,
        )
    # update_variable
    kwargs = {"variable_id": params.variable_id}
    for f in _VARIABLE_UPDATE_FIELDS:
        v = getattr(params, f)
        if v is not None:
            kwargs[f] = v
    return _cat_svc.update_variable(config, auth_manager, **kwargs)
