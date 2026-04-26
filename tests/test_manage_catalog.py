"""Tests for manage_catalog — Phase 4 service wiring."""

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
            ManageCatalogParams(action="update_category", title="X")
        with pytest.raises(ValidationError, match="at least one field"):
            ManageCatalogParams(action="update_category", category_id="abc")

    def test_update_item_requires_id_and_field(self):
        with pytest.raises(ValidationError, match="item_id"):
            ManageCatalogParams(action="update_item", name="X")
        with pytest.raises(ValidationError, match="at least one field"):
            ManageCatalogParams(action="update_item", item_id="abc")

    def test_move_items_requires_ids_and_target(self):
        with pytest.raises(ValidationError, match="item_ids"):
            ManageCatalogParams(action="move_items", target_category_id="cat2")
        with pytest.raises(ValidationError, match="target_category_id"):
            ManageCatalogParams(action="move_items", item_ids=["i1"])

    def test_create_variable_requires_core_fields(self):
        with pytest.raises(ValidationError, match="catalog_item_id"):
            ManageCatalogParams(
                action="create_variable",
                variable_name="x",
                variable_type="string",
                label="X",
            )
        with pytest.raises(ValidationError, match="variable_name"):
            ManageCatalogParams(
                action="create_variable",
                catalog_item_id="i1",
                variable_type="string",
                label="X",
            )
        with pytest.raises(ValidationError, match="variable_type"):
            ManageCatalogParams(
                action="create_variable",
                catalog_item_id="i1",
                variable_name="x",
                label="X",
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
            ManageCatalogParams(action="update_variable", label="X")


class TestDispatch:
    def test_create_category(self):
        with patch("servicenow_mcp.services.catalog.create_category") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_catalog(
                _config(),
                MagicMock(),
                ManageCatalogParams(action="create_category", title="Hardware", icon="hw"),
            )
            assert mock_fn.call_args.kwargs["title"] == "Hardware"
            assert mock_fn.call_args.kwargs["icon"] == "hw"

    def test_update_category(self):
        with patch("servicenow_mcp.services.catalog.update_category") as mock_fn:
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
            assert mock_fn.call_args.kwargs["category_id"] == "abc"
            assert mock_fn.call_args.kwargs["title"] == "New"
            assert mock_fn.call_args.kwargs["dry_run"] is True

    def test_update_item(self):
        with patch("servicenow_mcp.services.catalog.update_item") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_catalog(
                _config(),
                MagicMock(),
                ManageCatalogParams(action="update_item", item_id="i1", price="99", active=True),
            )
            assert mock_fn.call_args.kwargs["item_id"] == "i1"
            assert mock_fn.call_args.kwargs["price"] == "99"
            assert mock_fn.call_args.kwargs["active"] is True

    def test_move_items(self):
        with patch("servicenow_mcp.services.catalog.move_items") as mock_fn:
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
            assert mock_fn.call_args.kwargs["item_ids"] == ["i1", "i2"]
            assert mock_fn.call_args.kwargs["target_category_id"] == "cat2"

    def test_create_variable(self):
        with patch("servicenow_mcp.services.catalog.create_variable") as mock_fn:
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
            assert mock_fn.call_args.kwargs["catalog_item_id"] == "i1"
            assert mock_fn.call_args.kwargs["name"] == "comments"
            assert mock_fn.call_args.kwargs["variable_type"] == "string"
            assert mock_fn.call_args.kwargs["label"] == "Comments"
            assert mock_fn.call_args.kwargs["mandatory"] is True

    def test_update_variable(self):
        with patch("servicenow_mcp.services.catalog.update_variable") as mock_fn:
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
            assert mock_fn.call_args.kwargs["variable_id"] == "v1"
            assert mock_fn.call_args.kwargs["label"] == "Updated"
            assert mock_fn.call_args.kwargs["mandatory"] is False


class TestConfirmGate:
    def test_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._tool_requires_confirmation("manage_catalog") is True
