from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_management_tools import (
    GetPageParams,
    GetPortalParams,
    GetWidgetInstanceParams,
    get_page,
    get_portal,
    get_widget_instance,
)
from servicenow_mcp.utils.config import ServerConfig


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth_manager():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


# ---------------------------------------------------------------------------
# Portal Instance Tests
# ---------------------------------------------------------------------------


class TestListPortals:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_success(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "portal-1",
                    "title": "Self Service",
                    "url_suffix": "sp",
                    "homepage": "index",
                    "theme": "theme-1",
                    "default_": "true",
                },
            ],
            "total_count": 1,
        }

        params = GetPortalParams(limit=10)
        result = get_portal(mock_config, mock_auth_manager, params)

        assert result["success"] is True
        assert len(result["portals"]) == 1
        assert result["portals"][0]["title"] == "Self Service"
        assert result["portals"][0]["is_default"] is True

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_with_query_filter(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {"success": True, "results": [], "total_count": 0}

        params = GetPortalParams(query="Service")
        get_portal(mock_config, mock_auth_manager, params)

        call_args = mock_sn_query.call_args[0][2]
        assert "titleLIKEService" in call_args.query

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_query_failure(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {"success": False, "message": "Error"}

        params = GetPortalParams()
        result = get_portal(mock_config, mock_auth_manager, params)

        assert result["success"] is False
        assert result["portals"] == []


class TestGetPortal:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_by_url_suffix(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "portal-1",
                    "title": "Self Service",
                    "url_suffix": "sp",
                    "homepage": "index",
                    "theme": "theme-1",
                    "default_": "false",
                    "css": "",
                    "kb_knowledge_base": "",
                    "catalog": "cat-1",
                    "sc_catalog": "",
                    "login_page": "login",
                    "notfound_page": "404",
                    "sys_scope": "global",
                },
            ],
        }

        params = GetPortalParams(portal_id="sp")
        result = get_portal(mock_config, mock_auth_manager, params)

        assert result["success"] is True
        assert result["portal"]["url_suffix"] == "sp"
        assert result["portal"]["catalog"] == "cat-1"

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_not_found(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {"success": True, "results": []}

        params = GetPortalParams(portal_id="nonexistent")
        result = get_portal(mock_config, mock_auth_manager, params)

        assert result["success"] is False


# ---------------------------------------------------------------------------
# Page Tests
# ---------------------------------------------------------------------------


class TestListPages:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_success(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "page-1",
                    "id": "index",
                    "title": "Homepage",
                    "internal": "false",
                    "public": "true",
                    "draft": "false",
                    "sys_scope": "global",
                },
            ],
            "total_count": 1,
        }

        params = GetPageParams(limit=10)
        result = get_page(mock_config, mock_auth_manager, params)

        assert result["success"] is True
        assert len(result["pages"]) == 1
        assert result["pages"][0]["id"] == "index"
        assert result["pages"][0]["public"] is True

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_with_title_filter(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {"success": True, "results": [], "total_count": 0}

        params = GetPageParams(query="Home")
        get_page(mock_config, mock_auth_manager, params)

        call_args = mock_sn_query.call_args[0][2]
        assert "titleLIKEHome" in call_args.query


class TestGetPage:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_without_layout(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "page-1",
                    "id": "index",
                    "title": "Homepage",
                    "internal": "false",
                    "public": "true",
                    "draft": "false",
                    "css": "",
                    "sys_scope": "global",
                },
            ],
        }

        params = GetPageParams(page_id="index", include_layout=False)
        result = get_page(mock_config, mock_auth_manager, params)

        assert result["success"] is True
        assert result["page"]["id"] == "index"
        assert "layout" not in result["page"]

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_with_layout(self, mock_sn_query, mock_config, mock_auth_manager):
        # page query, container query, row query, column query, instance query
        mock_sn_query.side_effect = [
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "page-1",
                        "id": "index",
                        "title": "Homepage",
                        "internal": "false",
                        "public": "true",
                        "draft": "false",
                        "css": "",
                        "sys_scope": "global",
                    },
                ],
            },
            # containers
            {
                "success": True,
                "results": [
                    {"sys_id": "c-1", "order": "0", "background_color": "", "css_class": ""}
                ],
            },
            # rows in container
            {
                "success": True,
                "results": [
                    {"sys_id": "r-1", "sp_container": "c-1", "order": "0", "css_class": ""}
                ],
            },
            # columns in row
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "col-1",
                        "sp_row": "r-1",
                        "order": "0",
                        "size": "12",
                        "css_class": "",
                    }
                ],
            },
            # instances in column
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "inst-1",
                        "sp_column": "col-1",
                        "sp_widget": "wid-1",
                        "order": "0",
                        "widget_parameters": "",
                        "css": "",
                    }
                ],
            },
            # widget metadata (bulk resolve)
            {
                "success": True,
                "results": [{"sys_id": "wid-1", "id": "my_widget", "name": "My Widget"}],
            },
        ]

        params = GetPageParams(page_id="index", include_layout=True)
        result = get_page(mock_config, mock_auth_manager, params)

        assert result["success"] is True
        layout = result["page"]["layout"]
        assert len(layout) == 1
        assert len(layout[0]["rows"]) == 1
        assert len(layout[0]["rows"][0]["columns"]) == 1
        assert len(layout[0]["rows"][0]["columns"][0]["widgets"]) == 1
        w = layout[0]["rows"][0]["columns"][0]["widgets"][0]
        assert w["widget"] == "wid-1"
        assert w["widget_id"] == "my_widget"
        assert w["widget_name"] == "My Widget"

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_with_layout_preserves_ordering(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.side_effect = [
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "page-1",
                        "id": "index",
                        "title": "Homepage",
                        "internal": "false",
                        "public": "true",
                        "draft": "false",
                        "css": "",
                        "sys_scope": "global",
                    }
                ],
            },
            {
                "success": True,
                "results": [
                    {"sys_id": "c-2", "order": "2", "background_color": "", "css_class": ""},
                    {"sys_id": "c-1", "order": "1", "background_color": "", "css_class": ""},
                ],
            },
            {
                "success": True,
                "results": [
                    {"sys_id": "r-2", "sp_container": "c-1", "order": "2", "css_class": ""},
                    {"sys_id": "r-1", "sp_container": "c-1", "order": "1", "css_class": ""},
                ],
            },
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "col-2",
                        "sp_row": "r-1",
                        "order": "2",
                        "size": "6",
                        "css_class": "",
                    },
                    {
                        "sys_id": "col-1",
                        "sp_row": "r-1",
                        "order": "1",
                        "size": "6",
                        "css_class": "",
                    },
                ],
            },
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "inst-2",
                        "sp_column": "col-1",
                        "sp_widget": "wid-2",
                        "order": "2",
                        "widget_parameters": "",
                        "css": "",
                    },
                    {
                        "sys_id": "inst-1",
                        "sp_column": "col-1",
                        "sp_widget": "wid-1",
                        "order": "1",
                        "widget_parameters": "",
                        "css": "",
                    },
                ],
            },
            # widget metadata (bulk resolve)
            {
                "success": True,
                "results": [
                    {"sys_id": "wid-1", "id": "widget_one", "name": "Widget One"},
                    {"sys_id": "wid-2", "id": "widget_two", "name": "Widget Two"},
                ],
            },
        ]

        result = get_page(mock_config, mock_auth_manager, GetPageParams(page_id="index"))

        assert result["success"] is True
        layout = result["page"]["layout"]
        assert [container["sys_id"] for container in layout] == ["c-1", "c-2"]
        assert [row["sys_id"] for row in layout[0]["rows"]] == ["r-1", "r-2"]
        assert [column["sys_id"] for column in layout[0]["rows"][0]["columns"]] == [
            "col-1",
            "col-2",
        ]
        assert [widget["sys_id"] for widget in layout[0]["rows"][0]["columns"][0]["widgets"]] == [
            "inst-1",
            "inst-2",
        ]

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_not_found(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {"success": True, "results": []}

        params = GetPageParams(page_id="nonexistent")
        result = get_page(mock_config, mock_auth_manager, params)

        assert result["success"] is False


# ---------------------------------------------------------------------------
# Widget Instance Tests
# ---------------------------------------------------------------------------


class TestListWidgetInstances:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_by_widget(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "inst-1",
                    "sp_widget": "wid-1",
                    "sp_column": "col-1",
                    "order": "0",
                    "css": "",
                },
                {
                    "sys_id": "inst-2",
                    "sp_widget": "wid-1",
                    "sp_column": "col-2",
                    "order": "1",
                    "css": "",
                },
            ],
            "total_count": 2,
        }

        params = GetWidgetInstanceParams(widget_id="wid-1")
        result = get_widget_instance(mock_config, mock_auth_manager, params)

        assert result["success"] is True
        assert len(result["instances"]) == 2

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_by_page(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {"success": True, "results": [], "total_count": 0}

        params = GetWidgetInstanceParams(page_id="page-1")
        get_widget_instance(mock_config, mock_auth_manager, params)

        call_args = mock_sn_query.call_args[0][2]
        assert "sp_column.sp_row.sp_container.sp_page=page-1" in call_args.query


class TestGetWidgetInstance:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_success(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "inst-1",
                    "sp_widget": "wid-1",
                    "sp_column": "col-1",
                    "order": "0",
                    "widget_parameters": '{"title":"Hello"}',
                    "css": ".widget { color: red; }",
                    "sys_scope": "global",
                },
            ],
        }

        params = GetWidgetInstanceParams(instance_id="inst-1")
        result = get_widget_instance(mock_config, mock_auth_manager, params)

        assert result["success"] is True
        assert result["instance"]["widget_parameters"] == '{"title":"Hello"}'

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_not_found(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {"success": True, "results": []}

        params = GetWidgetInstanceParams(instance_id="nonexistent")
        result = get_widget_instance(mock_config, mock_auth_manager, params)

        assert result["success"] is False


# ---------------------------------------------------------------------------
# Param Validation Tests
# ---------------------------------------------------------------------------


class TestParamValidation:
    def test_get_portal_defaults_to_list_mode(self):
        p = GetPortalParams()
        assert p.portal_id is None
        assert p.limit == 20
        assert p.offset == 0

    def test_get_page_defaults(self):
        p = GetPageParams(page_id="test")
        assert p.include_layout is True
