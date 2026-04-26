"""Extra tests for portal_crud_tools.py — cover missed lines (96% → ~100%)."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_crud_tools import (
    ManagePortalComponentParams,
    ManagePortalLayoutParams,
    manage_portal_component,
    manage_portal_layout,
)
from servicenow_mcp.utils.config import ServerConfig

SCOPE = "scope-test-extra"


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestManagePortalLayoutAddRowWithCssClass:
    @patch("servicenow_mcp.services.portal_layout.create_row")
    def test_add_row_with_css_class(self, mock_create_row, mock_config, mock_auth):
        mock_create_row.return_value = {"success": True, "sys_id": "rw1"}
        params = ManagePortalLayoutParams(
            action="add_row",
            sp_container="ct1",
            css_class="row-eq-height",
        )
        result = manage_portal_layout(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_create_row.call_args.kwargs["css_class"] == "row-eq-height"


class TestManagePortalLayoutAddColumnWithCssClass:
    @patch("servicenow_mcp.services.portal_layout.create_column")
    def test_add_column_with_css_class(self, mock_create_col, mock_config, mock_auth):
        mock_create_col.return_value = {"success": True, "sys_id": "cl1"}
        params = ManagePortalLayoutParams(
            action="add_column",
            sp_row="rw1",
            size=6,
            css_class="col-custom",
        )
        result = manage_portal_layout(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_create_col.call_args.kwargs["css_class"] == "col-custom"


class TestManagePortalLayoutPlaceWidgetWithCss:
    @patch("servicenow_mcp.services.portal_layout.place_widget")
    def test_place_widget_with_instance_css(self, mock_place, mock_config, mock_auth):
        mock_place.return_value = {"success": True, "instance_id": "inst1"}
        params = ManagePortalLayoutParams(
            action="place_widget",
            sp_widget="wid-1",
            sp_column="col-1",
            instance_css=".custom{}",
        )
        result = manage_portal_layout(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_place.call_args.kwargs["css"] == ".custom{}"


class TestManagePortalLayoutMoveWidget:
    @patch("servicenow_mcp.services.portal_layout.move_widget")
    def test_move_widget_with_all_fields(self, mock_move, mock_config, mock_auth):
        mock_move.return_value = {"success": True}
        params = ManagePortalLayoutParams(
            action="move_widget",
            instance_id="inst-1",
            sp_column="col-new",
            order=5,
            widget_parameters='{"a":1}',
            instance_css=".moved{}",
        )
        result = manage_portal_layout(mock_config, mock_auth, params)
        assert result["success"] is True
        kw = mock_move.call_args.kwargs
        assert kw["instance_id"] == "inst-1"
        assert kw["sp_column"] == "col-new"
        assert kw["order"] == 5
        assert kw["widget_parameters"] == '{"a":1}'
        assert kw["css"] == ".moved{}"


class TestManagePortalComponentValidation:
    def test_create_provider_requires_name(self):
        with pytest.raises(ValueError, match="name is required"):
            ManagePortalComponentParams(
                action="create_provider",
                script="x",
                scope=SCOPE,
            )

    def test_create_provider_requires_script(self):
        with pytest.raises(ValueError, match="script is required"):
            ManagePortalComponentParams(
                action="create_provider",
                name="svc",
                scope=SCOPE,
            )

    def test_create_provider_requires_scope(self):
        with pytest.raises(ValueError, match="scope is required"):
            ManagePortalComponentParams(
                action="create_provider",
                name="svc",
                script="x",
            )

    def test_create_ng_template_requires_template_id(self):
        with pytest.raises(ValueError, match="template_id is required"):
            ManagePortalComponentParams(
                action="create_ng_template",
                template="<p/>",
                scope=SCOPE,
            )

    def test_create_ng_template_requires_template(self):
        with pytest.raises(ValueError, match="template is required"):
            ManagePortalComponentParams(
                action="create_ng_template",
                template_id="tpl.html",
                scope=SCOPE,
            )

    def test_create_ng_template_requires_scope(self):
        with pytest.raises(ValueError, match="scope is required"):
            ManagePortalComponentParams(
                action="create_ng_template",
                template_id="tpl.html",
                template="<p/>",
            )

    def test_update_code_requires_table(self):
        with pytest.raises(ValueError, match="table is required"):
            ManagePortalComponentParams(
                action="update_code",
                sys_id="abc",
                update_data={"script": "x"},
            )

    def test_update_code_requires_sys_id(self):
        with pytest.raises(ValueError, match="sys_id is required"):
            ManagePortalComponentParams(
                action="update_code",
                table="sp_widget",
                update_data={"script": "x"},
            )

    def test_update_code_requires_update_data(self):
        with pytest.raises(ValueError, match="update_data is required"):
            ManagePortalComponentParams(
                action="update_code",
                table="sp_widget",
                sys_id="abc",
            )


class TestManagePortalComponentDispatch:
    @patch("servicenow_mcp.services.portal_component.create_widget")
    def test_create_widget_with_widget_id(self, mock_create, mock_config, mock_auth):
        mock_create.return_value = {"success": True, "sys_id": "w1"}
        params = ManagePortalComponentParams(
            action="create_widget",
            name="W",
            scope=SCOPE,
            widget_id="custom_id",
        )
        result = manage_portal_component(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_create.call_args.kwargs["widget_id"] == "custom_id"

    @patch("servicenow_mcp.services.portal_component.create_angular_provider")
    def test_create_provider_with_type(self, mock_create, mock_config, mock_auth):
        mock_create.return_value = {"success": True, "sys_id": "ap1"}
        params = ManagePortalComponentParams(
            action="create_provider",
            name="svc",
            script="x",
            scope=SCOPE,
            provider_type="service",
        )
        result = manage_portal_component(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_create.call_args.kwargs["provider_type"] == "service"

    @patch("servicenow_mcp.services.portal_component.create_angular_provider")
    def test_create_provider_with_description(self, mock_create, mock_config, mock_auth):
        mock_create.return_value = {"success": True, "sys_id": "ap2"}
        params = ManagePortalComponentParams(
            action="create_provider",
            name="svc",
            script="x",
            scope=SCOPE,
            description="A service",
        )
        result = manage_portal_component(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_create.call_args.kwargs["description"] == "A service"

    @patch("servicenow_mcp.services.portal_component.create_header_footer")
    def test_create_header_footer_with_template_and_css(self, mock_create, mock_config, mock_auth):
        mock_create.return_value = {"success": True, "sys_id": "hf1"}
        params = ManagePortalComponentParams(
            action="create_header_footer",
            name="HF",
            scope=SCOPE,
            template="<header/>",
            css=".h{}",
        )
        result = manage_portal_component(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_create.call_args.kwargs["template"] == "<header/>"
        assert mock_create.call_args.kwargs["css"] == ".h{}"

    @patch("servicenow_mcp.services.portal_component.create_css_theme")
    def test_create_theme_with_css(self, mock_create, mock_config, mock_auth):
        mock_create.return_value = {"success": True, "sys_id": "cs1"}
        params = ManagePortalComponentParams(
            action="create_theme",
            name="Dark",
            scope=SCOPE,
            css="body{color:red}",
        )
        result = manage_portal_component(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_create.call_args.kwargs["css"] == "body{color:red}"

    @patch("servicenow_mcp.services.portal_component.create_ng_template")
    def test_create_ng_template_dispatch(self, mock_create, mock_config, mock_auth):
        mock_create.return_value = {"success": True, "sys_id": "ng1"}
        params = ManagePortalComponentParams(
            action="create_ng_template",
            template_id="my.html",
            template="<div/>",
            scope=SCOPE,
        )
        result = manage_portal_component(mock_config, mock_auth, params)
        assert result["success"] is True
        assert mock_create.call_args.kwargs["template_id"] == "my.html"

    @patch("servicenow_mcp.services.portal_component.create_ui_page")
    def test_create_ui_page_with_optional_fields(self, mock_create, mock_config, mock_auth):
        mock_create.return_value = {"success": True, "sys_id": "up1"}
        params = ManagePortalComponentParams(
            action="create_ui_page",
            name="page1",
            scope=SCOPE,
            html="<jelly/>",
            client_script="cs()",
            processing_script="ps()",
            description="desc",
            category="general",
        )
        result = manage_portal_component(mock_config, mock_auth, params)
        assert result["success"] is True
        kw = mock_create.call_args.kwargs
        assert kw["html"] == "<jelly/>"
        assert kw["client_script"] == "cs()"
        assert kw["processing_script"] == "ps()"
        assert kw["description"] == "desc"
        assert kw["category"] == "general"

    @patch("servicenow_mcp.tools.portal_crud_tools.update_portal_component")
    def test_update_code_dispatch(self, mock_update, mock_config, mock_auth):
        mock_update.return_value = {"success": True}
        params = ManagePortalComponentParams(
            action="update_code",
            table="sp_widget",
            sys_id="w1",
            update_data={"script": "new_script();"},
        )
        result = manage_portal_component(mock_config, mock_auth, params)
        assert result["success"] is True
        call_kwargs = mock_update.call_args[0][2]
        assert call_kwargs.table == "sp_widget"
        assert call_kwargs.sys_id == "w1"
