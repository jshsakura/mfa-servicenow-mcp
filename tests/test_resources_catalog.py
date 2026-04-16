"""Tests for servicenow_mcp.resources.catalog module."""

import asyncio

from conftest import make_mock_response

from servicenow_mcp.resources.catalog import (
    CatalogCategoryListParams,
    CatalogListParams,
    CatalogResource,
    _coerce_bool,
    _coerce_int,
)

# ---------------------------------------------------------------------------
# Helper coercion functions
# ---------------------------------------------------------------------------


def test_coerce_bool_true_values():
    assert _coerce_bool(True) is True
    assert _coerce_bool("true") is True
    assert _coerce_bool("True") is True
    assert _coerce_bool(" TRUE ") is True


def test_coerce_bool_false_values():
    assert _coerce_bool(False) is False
    assert _coerce_bool("false") is False
    assert _coerce_bool("anything") is False
    assert _coerce_bool("") is False


def test_coerce_int_valid():
    assert _coerce_int(5) == 5
    assert _coerce_int("42") == 42


def test_coerce_int_invalid():
    assert _coerce_int(None) == 0
    assert _coerce_int("abc") == 0


# ---------------------------------------------------------------------------
# CatalogResource.list_catalog_items
# ---------------------------------------------------------------------------


def test_list_catalog_items_success(mock_config, mock_auth):
    mock_auth.make_request.return_value = make_mock_response(
        {
            "result": [
                {
                    "sys_id": "item1",
                    "name": "Laptop",
                    "short_description": "A laptop",
                    "category": "hardware",
                    "price": "1000",
                    "picture": None,
                    "active": "true",
                    "order": "10",
                }
            ]
        }
    )
    resource = CatalogResource(mock_config, mock_auth)
    items = asyncio.run(resource.list_catalog_items(CatalogListParams()))
    assert len(items) == 1
    assert items[0].sys_id == "item1"
    assert items[0].name == "Laptop"
    assert items[0].active is True
    assert items[0].order == 10


def test_list_catalog_items_with_category_and_query(mock_config, mock_auth):
    mock_auth.make_request.return_value = make_mock_response({"result": []})
    resource = CatalogResource(mock_config, mock_auth)
    params = CatalogListParams(category="hw", query="laptop")
    asyncio.run(resource.list_catalog_items(params))
    call_args = mock_auth.make_request.call_args
    query = call_args.kwargs.get("params", {})
    assert "category=hw" in query["sysparm_query"]
    assert "laptop" in query["sysparm_query"]


def test_list_catalog_items_exception(mock_config, mock_auth):
    from requests import RequestException

    mock_auth.make_request.side_effect = RequestException("timeout")
    resource = CatalogResource(mock_config, mock_auth)
    items = asyncio.run(resource.list_catalog_items(CatalogListParams()))
    assert items == []


# ---------------------------------------------------------------------------
# CatalogResource.get_catalog_item
# ---------------------------------------------------------------------------


def test_get_catalog_item_success(mock_config, mock_auth):
    item_data = {
        "sys_id": "item1",
        "name": "Laptop",
        "active": "true",
        "order": "5",
    }
    variables_data = [
        {
            "sys_id": "var1",
            "name": "quantity",
            "question_text": "How many?",
            "type": "integer",
            "mandatory": "true",
            "default_value": "1",
            "help_text": "Enter quantity",
            "order": "0",
        }
    ]
    mock_auth.make_request.side_effect = [
        make_mock_response({"result": item_data}),
        make_mock_response({"result": variables_data}),
    ]
    resource = CatalogResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_catalog_item("item1"))
    assert result["active"] is True
    assert result["order"] == 5
    assert len(result["variables"]) == 1
    assert result["variables"][0].name == "quantity"


def test_get_catalog_item_not_found(mock_config, mock_auth):
    mock_auth.make_request.return_value = make_mock_response({"result": {}})
    resource = CatalogResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_catalog_item("missing"))
    assert "error" in result
    assert "not found" in result["error"]


def test_get_catalog_item_exception(mock_config, mock_auth):
    from requests import RequestException

    mock_auth.make_request.side_effect = RequestException("server error")
    resource = CatalogResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_catalog_item("item1"))
    assert "error" in result
    assert "Error getting catalog item" in result["error"]


# ---------------------------------------------------------------------------
# CatalogResource.get_catalog_item_variables
# ---------------------------------------------------------------------------


def test_get_catalog_item_variables_success(mock_config, mock_auth):
    mock_auth.make_request.return_value = make_mock_response(
        {
            "result": [
                {
                    "sys_id": "v1",
                    "name": "urgency",
                    "question_text": "Urgency",
                    "type": "1",
                    "mandatory": "false",
                    "default_value": None,
                    "help_text": None,
                    "order": "100",
                }
            ]
        }
    )
    resource = CatalogResource(mock_config, mock_auth)
    variables = asyncio.run(resource.get_catalog_item_variables("item1"))
    assert len(variables) == 1
    assert variables[0].sys_id == "v1"
    assert variables[0].mandatory is False
    assert variables[0].order == 100


def test_get_catalog_item_variables_exception(mock_config, mock_auth):
    mock_auth.make_request.side_effect = Exception("fail")
    resource = CatalogResource(mock_config, mock_auth)
    variables = asyncio.run(resource.get_catalog_item_variables("item1"))
    assert variables == []


# ---------------------------------------------------------------------------
# CatalogResource.list_catalog_categories
# ---------------------------------------------------------------------------


def test_list_catalog_categories_success(mock_config, mock_auth):
    mock_auth.make_request.return_value = make_mock_response(
        {
            "result": [
                {
                    "sys_id": "cat1",
                    "title": "Hardware",
                    "description": "HW items",
                    "parent": None,
                    "icon": None,
                    "active": "true",
                    "order": "1",
                }
            ]
        }
    )
    resource = CatalogResource(mock_config, mock_auth)
    categories = asyncio.run(resource.list_catalog_categories(CatalogCategoryListParams()))
    assert len(categories) == 1
    assert categories[0].title == "Hardware"


def test_list_catalog_categories_with_query(mock_config, mock_auth):
    mock_auth.make_request.return_value = make_mock_response({"result": []})
    resource = CatalogResource(mock_config, mock_auth)
    params = CatalogCategoryListParams(query="soft")
    asyncio.run(resource.list_catalog_categories(params))
    call_args = mock_auth.make_request.call_args
    query = call_args.kwargs.get("params", {})
    assert "soft" in query["sysparm_query"]


def test_list_catalog_categories_exception(mock_config, mock_auth):
    mock_auth.make_request.side_effect = Exception("fail")
    resource = CatalogResource(mock_config, mock_auth)
    categories = asyncio.run(resource.list_catalog_categories(CatalogCategoryListParams()))
    assert categories == []


# ---------------------------------------------------------------------------
# CatalogResource.read
# ---------------------------------------------------------------------------


def test_read_missing_item_id(mock_config, mock_auth):
    resource = CatalogResource(mock_config, mock_auth)
    result = asyncio.run(resource.read({}))
    assert result == {"error": "Missing item_id parameter"}
    mock_auth.make_request.assert_not_called()


def test_read_delegates_to_get_catalog_item(mock_config, mock_auth):
    mock_auth.make_request.side_effect = [
        make_mock_response({"result": {"sys_id": "x", "active": True, "order": 0}}),
        make_mock_response({"result": []}),
    ]
    resource = CatalogResource(mock_config, mock_auth)
    result = asyncio.run(resource.read({"item_id": "x"}))
    assert result["sys_id"] == "x"
