"""Legacy-compatible Service Catalog resource helpers."""

from __future__ import annotations

from typing import Any

import requests
from pydantic import BaseModel

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig

RequestParams = dict[str, str | int]


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class CatalogListParams(BaseModel):
    limit: int = 10
    offset: int = 0
    category: str | None = None
    query: str | None = None


class CatalogCategoryListParams(BaseModel):
    limit: int = 10
    offset: int = 0
    query: str | None = None


class CatalogItemVariableModel(BaseModel):
    sys_id: str
    name: str
    label: str
    type: str
    mandatory: bool
    default_value: str | None = None
    help_text: str | None = None
    order: int = 0


class CatalogItemModel(BaseModel):
    sys_id: str
    name: str
    short_description: str | None = None
    category: str | None = None
    price: str | None = None
    picture: str | None = None
    active: bool
    order: int = 0


class CatalogCategoryModel(BaseModel):
    sys_id: str
    title: str
    description: str | None = None
    parent: str | None = None
    icon: str | None = None
    active: bool
    order: int = 0


class CatalogResource:
    def __init__(self, config: ServerConfig, auth_manager: AuthManager):
        self.config = config
        self.auth_manager = auth_manager

    async def list_catalog_items(self, params: CatalogListParams) -> list[CatalogItemModel]:
        query_parts = ["active=true"]
        if params.category:
            query_parts.append(f"category={params.category}")
        if params.query:
            query_parts.append(f"short_descriptionLIKE{params.query}^ORnameLIKE{params.query}")
        request_params: RequestParams = {
            "sysparm_limit": params.limit,
            "sysparm_offset": params.offset,
            "sysparm_query": "^".join(query_parts),
        }

        try:
            response = requests.get(
                f"{self.config.instance_url}/api/now/table/sc_cat_item",
                headers=self.auth_manager.get_headers(),
                params=request_params,
            )
            response.raise_for_status()
            results = response.json().get("result", [])
        except Exception:
            return []

        return [
            CatalogItemModel(
                sys_id=str(item.get("sys_id", "")),
                name=str(item.get("name", "")),
                short_description=item.get("short_description"),
                category=item.get("category"),
                price=item.get("price"),
                picture=item.get("picture"),
                active=_coerce_bool(item.get("active")),
                order=_coerce_int(item.get("order")),
            )
            for item in results
        ]

    async def get_catalog_item(self, item_id: str) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{self.config.instance_url}/api/now/table/sc_cat_item/{item_id}",
                headers=self.auth_manager.get_headers(),
            )
            response.raise_for_status()
            item = response.json().get("result", {})
            if not item:
                return {"error": f"Catalog item '{item_id}' not found"}
            variables = await self.get_catalog_item_variables(item_id)
            return {
                **item,
                "active": _coerce_bool(item.get("active")),
                "order": _coerce_int(item.get("order")),
                "variables": variables,
            }
        except Exception as exc:
            return {"error": f"Error getting catalog item: {exc}"}

    async def get_catalog_item_variables(self, item_id: str) -> list[CatalogItemVariableModel]:
        try:
            request_params: RequestParams = {"sysparm_query": f"cat_item={item_id}^ORDERBYorder"}
            response = requests.get(
                f"{self.config.instance_url}/api/now/table/item_option_new",
                headers=self.auth_manager.get_headers(),
                params=request_params,
            )
            response.raise_for_status()
            results = response.json().get("result", [])
        except Exception:
            return []

        return [
            CatalogItemVariableModel(
                sys_id=str(item.get("sys_id", "")),
                name=str(item.get("name", "")),
                label=str(item.get("question_text", "")),
                type=str(item.get("type", "")),
                mandatory=_coerce_bool(item.get("mandatory")),
                default_value=item.get("default_value"),
                help_text=item.get("help_text"),
                order=_coerce_int(item.get("order")),
            )
            for item in results
        ]

    async def list_catalog_categories(
        self, params: CatalogCategoryListParams
    ) -> list[CatalogCategoryModel]:
        query_parts = ["active=true"]
        if params.query:
            query_parts.append(f"titleLIKE{params.query}^ORdescriptionLIKE{params.query}")
        request_params: RequestParams = {
            "sysparm_limit": params.limit,
            "sysparm_offset": params.offset,
            "sysparm_query": "^".join(query_parts),
        }

        try:
            response = requests.get(
                f"{self.config.instance_url}/api/now/table/sc_category",
                headers=self.auth_manager.get_headers(),
                params=request_params,
            )
            response.raise_for_status()
            results = response.json().get("result", [])
        except Exception:
            return []

        return [
            CatalogCategoryModel(
                sys_id=str(item.get("sys_id", "")),
                title=str(item.get("title", "")),
                description=item.get("description"),
                parent=item.get("parent"),
                icon=item.get("icon"),
                active=_coerce_bool(item.get("active")),
                order=_coerce_int(item.get("order")),
            )
            for item in results
        ]

    async def read(self, payload: dict[str, Any]) -> dict[str, Any]:
        item_id = payload.get("item_id")
        if not item_id:
            return {"error": "Missing item_id parameter"}
        return await self.get_catalog_item(str(item_id))
