"""Tests for manage_portal_layout and manage_portal_component — Phase 3f."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.portal_crud_tools import (
    ManagePortalComponentParams,
    ManagePortalLayoutParams,
    manage_portal_component,
    manage_portal_layout,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


# ---------------------------------------------------------------------------
# manage_portal_layout — pages, containers, rows, columns, widget instances
# ---------------------------------------------------------------------------


class TestLayoutValidation:
    def test_create_page_requires_id_title_scope(self):
        with pytest.raises(ValidationError, match="page_id"):
            ManagePortalLayoutParams(action="create_page", title="X", scope="s1")
        with pytest.raises(ValidationError, match="title"):
            ManagePortalLayoutParams(action="create_page", page_id="my", scope="s1")
        with pytest.raises(ValidationError, match="scope"):
            ManagePortalLayoutParams(action="create_page", page_id="my", title="X")

    def test_update_page_requires_sys_id_and_field(self):
        with pytest.raises(ValidationError, match="sys_id"):
            ManagePortalLayoutParams(action="update_page", title="x")
        with pytest.raises(ValidationError, match="at least one field"):
            ManagePortalLayoutParams(action="update_page", sys_id="abc")

    def test_add_container_requires_sp_page(self):
        with pytest.raises(ValidationError, match="sp_page"):
            ManagePortalLayoutParams(action="add_container")

    def test_add_row_requires_sp_container(self):
        with pytest.raises(ValidationError, match="sp_container"):
            ManagePortalLayoutParams(action="add_row")

    def test_add_column_requires_sp_row(self):
        with pytest.raises(ValidationError, match="sp_row"):
            ManagePortalLayoutParams(action="add_column")

    def test_place_widget_requires_widget_and_column(self):
        with pytest.raises(ValidationError, match="sp_widget"):
            ManagePortalLayoutParams(action="place_widget", sp_column="c1")
        with pytest.raises(ValidationError, match="sp_column"):
            ManagePortalLayoutParams(action="place_widget", sp_widget="w1")

    def test_move_widget_requires_instance_id(self):
        with pytest.raises(ValidationError, match="instance_id"):
            ManagePortalLayoutParams(action="move_widget", sp_column="c1")


class TestLayoutDispatch:
    def test_create_page(self):
        with patch("servicenow_mcp.services.portal_layout.create_page") as m:
            m.return_value = {"success": True}
            manage_portal_layout(
                _config(),
                MagicMock(),
                ManagePortalLayoutParams(
                    action="create_page",
                    page_id="landing",
                    title="Landing",
                    scope="s1",
                    public=True,
                ),
            )
            kw = m.call_args.kwargs
            assert kw["page_id"] == "landing"
            assert kw["title"] == "Landing"
            assert kw["scope"] == "s1"
            assert kw["public"] is True

    def test_update_page(self):
        with patch("servicenow_mcp.services.portal_layout.update_page") as m:
            m.return_value = {"success": True}
            manage_portal_layout(
                _config(),
                MagicMock(),
                ManagePortalLayoutParams(
                    action="update_page", sys_id="abc", title="New", dry_run=True
                ),
            )
            kw = m.call_args.kwargs
            assert kw["sys_id"] == "abc"
            assert kw["title"] == "New"
            assert kw["dry_run"] is True

    def test_add_container(self):
        with patch("servicenow_mcp.services.portal_layout.create_container") as m:
            m.return_value = {"success": True}
            manage_portal_layout(
                _config(),
                MagicMock(),
                ManagePortalLayoutParams(
                    action="add_container", sp_page="p1", order=10, width="container-fluid"
                ),
            )
            kw = m.call_args.kwargs
            assert kw["sp_page"] == "p1"
            assert kw["order"] == 10
            assert kw["width"] == "container-fluid"

    def test_add_row(self):
        with patch("servicenow_mcp.services.portal_layout.create_row") as m:
            m.return_value = {"success": True}
            manage_portal_layout(
                _config(),
                MagicMock(),
                ManagePortalLayoutParams(action="add_row", sp_container="c1", order=5),
            )
            kw = m.call_args.kwargs
            assert kw["sp_container"] == "c1"
            assert kw["order"] == 5

    def test_add_column(self):
        with patch("servicenow_mcp.services.portal_layout.create_column") as m:
            m.return_value = {"success": True}
            manage_portal_layout(
                _config(),
                MagicMock(),
                ManagePortalLayoutParams(action="add_column", sp_row="r1", order=2, size=6),
            )
            kw = m.call_args.kwargs
            assert kw["sp_row"] == "r1"
            assert kw["size"] == 6

    def test_place_widget(self):
        with patch("servicenow_mcp.services.portal_layout.place_widget") as m:
            m.return_value = {"success": True}
            manage_portal_layout(
                _config(),
                MagicMock(),
                ManagePortalLayoutParams(
                    action="place_widget",
                    sp_widget="w1",
                    sp_column="c1",
                    order=1,
                    widget_parameters='{"x":1}',
                ),
            )
            kw = m.call_args.kwargs
            assert kw["sp_widget"] == "w1"
            assert kw["sp_column"] == "c1"
            assert kw["widget_parameters"] == '{"x":1}'

    def test_move_widget(self):
        with patch("servicenow_mcp.services.portal_layout.move_widget") as m:
            m.return_value = {"success": True}
            manage_portal_layout(
                _config(),
                MagicMock(),
                ManagePortalLayoutParams(
                    action="move_widget",
                    instance_id="i1",
                    sp_column="c2",
                    order=3,
                ),
            )
            kw = m.call_args.kwargs
            assert kw["instance_id"] == "i1"
            assert kw["sp_column"] == "c2"


# ---------------------------------------------------------------------------
# manage_portal_component — widget, provider, theme, ng_template, ui_page,
# header_footer, update_code
# ---------------------------------------------------------------------------


class TestComponentValidation:
    def test_create_widget_requires_name_and_scope(self):
        with pytest.raises(ValidationError, match="name"):
            ManagePortalComponentParams(action="create_widget", scope="s1")
        with pytest.raises(ValidationError, match="scope"):
            ManagePortalComponentParams(action="create_widget", name="w")

    def test_create_provider_requires_name_script_scope(self):
        with pytest.raises(ValidationError, match="script"):
            ManagePortalComponentParams(action="create_provider", name="x", scope="s1")

    def test_create_ng_template_requires_template_id_html_scope(self):
        with pytest.raises(ValidationError, match="template_id"):
            ManagePortalComponentParams(action="create_ng_template", template="<x/>", scope="s1")
        with pytest.raises(ValidationError, match="template"):
            ManagePortalComponentParams(action="create_ng_template", template_id="t", scope="s1")

    def test_update_code_requires_table_sys_id_data(self):
        with pytest.raises(ValidationError, match="table"):
            ManagePortalComponentParams(action="update_code", sys_id="abc", update_data={"x": "y"})
        with pytest.raises(ValidationError, match="sys_id"):
            ManagePortalComponentParams(
                action="update_code", table="sp_widget", update_data={"x": "y"}
            )
        with pytest.raises(ValidationError, match="update_data"):
            ManagePortalComponentParams(action="update_code", table="sp_widget", sys_id="abc")


class TestComponentDispatch:
    def test_create_widget(self):
        with patch("servicenow_mcp.services.portal_component.create_widget") as m:
            m.return_value = {"success": True}
            manage_portal_component(
                _config(),
                MagicMock(),
                ManagePortalComponentParams(
                    action="create_widget",
                    name="MyWidget",
                    scope="s1",
                    template="<div/>",
                ),
            )
            assert m.call_args.kwargs["name"] == "MyWidget"
            assert m.call_args.kwargs["scope"] == "s1"
            assert m.call_args.kwargs["template"] == "<div/>"

    def test_create_provider(self):
        with patch("servicenow_mcp.services.portal_component.create_angular_provider") as m:
            m.return_value = {"success": True}
            manage_portal_component(
                _config(),
                MagicMock(),
                ManagePortalComponentParams(
                    action="create_provider",
                    name="svc",
                    script="function(){}",
                    scope="s1",
                ),
            )
            assert m.call_args.kwargs["name"] == "svc"

    def test_create_header_footer(self):
        with patch("servicenow_mcp.services.portal_component.create_header_footer") as m:
            m.return_value = {"success": True}
            manage_portal_component(
                _config(),
                MagicMock(),
                ManagePortalComponentParams(
                    action="create_header_footer",
                    name="hdr",
                    scope="s1",
                ),
            )
            assert m.call_args.kwargs["name"] == "hdr"

    def test_create_theme(self):
        with patch("servicenow_mcp.services.portal_component.create_css_theme") as m:
            m.return_value = {"success": True}
            manage_portal_component(
                _config(),
                MagicMock(),
                ManagePortalComponentParams(
                    action="create_theme", name="dark", scope="s1", css="body{}"
                ),
            )
            assert m.call_args.kwargs["name"] == "dark"

    def test_create_ng_template(self):
        with patch("servicenow_mcp.services.portal_component.create_ng_template") as m:
            m.return_value = {"success": True}
            manage_portal_component(
                _config(),
                MagicMock(),
                ManagePortalComponentParams(
                    action="create_ng_template",
                    template_id="my.html",
                    template="<div/>",
                    scope="s1",
                ),
            )
            assert m.call_args.kwargs["template_id"] == "my.html"
            assert m.call_args.kwargs["template"] == "<div/>"

    def test_create_ui_page(self):
        with patch("servicenow_mcp.services.portal_component.create_ui_page") as m:
            m.return_value = {"success": True}
            manage_portal_component(
                _config(),
                MagicMock(),
                ManagePortalComponentParams(action="create_ui_page", name="my_ui", scope="s1"),
            )
            assert m.call_args.kwargs["name"] == "my_ui"

    def test_update_code(self):
        with patch("servicenow_mcp.tools.portal_crud_tools.update_portal_component") as m:
            m.return_value = {"success": True}
            manage_portal_component(
                _config(),
                MagicMock(),
                ManagePortalComponentParams(
                    action="update_code",
                    table="sp_widget",
                    sys_id="abc",
                    update_data={"client_script": "..."},
                ),
            )
            inner = m.call_args[0][2]
            assert inner.table == "sp_widget"
            assert inner.sys_id == "abc"
            assert inner.update_data == {"client_script": "..."}


class TestConfirmGate:
    def test_layout_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._tool_requires_confirmation("manage_portal_layout") is True

    def test_component_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._tool_requires_confirmation("manage_portal_component") is True
