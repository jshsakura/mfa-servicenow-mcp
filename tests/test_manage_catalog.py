"""Tests for manage_catalog — Phase 3e bundle (categories + items + variables)."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.catalog_tools import ManageCatalogParams, manage_catalog
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


class TestValidation:
    def test_create_category_requires_title(self):
        with pytest.raises(ValidationError, match="title"):
            ManageCatalogParams(action="create_category")

    def test_update_category_requires_id_and_field(self):
        with pytest.raises(ValidationError, match="category_id"):
            ManageCatalogParams(action="update_category", title="x")
        with pytest.raises(ValidationError, match="at least one field"):
            ManageCatalogParams(action="update_category", category_id="abc")

    def test_update_item_requires_id_and_field(self):
        with pytest.raises(ValidationError, match="item_id"):
            ManageCatalogParams(action="update_item", name="x")
        with pytest.raises(ValidationError, match="at least one field"):
            ManageCatalogParams(action="update_item", item_id="abc")

    def test_move_items_requires_ids_and_target(self):
        with pytest.raises(ValidationError, match="item_ids"):
            ManageCatalogParams(action="move_items", target_category_id="cat1")
        with pytest.raises(ValidationError, match="target_category_id"):
            ManageCatalogParams(action="move_items", item_ids=["i1"])

    def test_create_variable_requires_core_fields(self):
        with pytest.raises(ValidationError, match="catalog_item_id"):
            ManageCatalogParams(
                action="create_variable",
                variable_name="x",
                variable_type="string",
                label="L",
            )
        with pytest.raises(ValidationError, match="variable_name"):
            ManageCatalogParams(
                action="create_variable",
                catalog_item_id="i1",
                variable_type="string",
                label="L",
            )
        with pytest.raises(ValidationError, match="variable_type"):
            ManageCatalogParams(
                action="create_variable",
                catalog_item_id="i1",
                variable_name="x",
                label="L",
            )
        with pytest.raises(ValidationError, match="label"):
            ManageCatalogParams(
                action="create_variable",
                catalog_item_id="i1",
                variable_name="x",
                variable_type="string",
            )

    def test_update_variable_requires_id(self):
        with pytest.raises(ValidationError, match="variable_id"):
            ManageCatalogParams(action="update_variable", label="x")


class TestDispatch:
    def test_create_category(self):
        with patch("servicenow_mcp.tools.catalog_tools.create_catalog_category") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_catalog(
                _config(),
                MagicMock(),
                ManageCatalogParams(action="create_category", title="Hardware", icon="hw"),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.title == "Hardware"
            assert inner.icon == "hw"

    def test_update_category(self):
        with patch("servicenow_mcp.tools.catalog_tools.update_catalog_category") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_catalog(
                _config(),
                MagicMock(),
                ManageCatalogParams(
                    action="update_category",
                    category_id="abc",
                    title="New",
                    dry_run=True,
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.category_id == "abc"
            assert inner.title == "New"
            assert inner.dry_run is True

    def test_update_item(self):
        with patch("servicenow_mcp.tools.catalog_tools.update_catalog_item") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_catalog(
                _config(),
                MagicMock(),
                ManageCatalogParams(action="update_item", item_id="i1", price="99", active=True),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.item_id == "i1"
            assert inner.price == "99"
            assert inner.active is True

    def test_move_items(self):
        with patch("servicenow_mcp.tools.catalog_tools.move_catalog_items") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_catalog(
                _config(),
                MagicMock(),
                ManageCatalogParams(
                    action="move_items",
                    item_ids=["i1", "i2"],
                    target_category_id="cat2",
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.item_ids == ["i1", "i2"]
            assert inner.target_category_id == "cat2"

    def test_create_variable(self):
        with patch("servicenow_mcp.tools.catalog_tools.create_catalog_item_variable") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_catalog(
                _config(),
                MagicMock(),
                ManageCatalogParams(
                    action="create_variable",
                    catalog_item_id="i1",
                    variable_name="comments",
                    variable_type="string",
                    label="Comments",
                    mandatory=True,
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.catalog_item_id == "i1"
            assert inner.name == "comments"
            assert inner.type == "string"
            assert inner.label == "Comments"
            assert inner.mandatory is True

    def test_update_variable(self):
        with patch("servicenow_mcp.tools.catalog_tools.update_catalog_item_variable") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_catalog(
                _config(),
                MagicMock(),
                ManageCatalogParams(
                    action="update_variable",
                    variable_id="v1",
                    label="Updated",
                    mandatory=False,
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.variable_id == "v1"
            assert inner.label == "Updated"
            assert inner.mandatory is False


class TestConfirmGate:
    def test_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._tool_requires_confirmation("manage_catalog") is True
