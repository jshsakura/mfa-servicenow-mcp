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
                    "theme.name": "Coral",
                    "default": "true",
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
        assert result["portals"][0]["theme"] == "Coral"
        fields = mock_sn_query.call_args[0][2].fields
        # Dictionary names, measured live: default_/css/sp_rectangle are dropped silently.
        assert "default" in fields.split(",") and "default_" not in fields

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


def _portal_side_effect(tables):
    """sn_query stub answering per table; records the queries it saw."""
    seen = []

    def _fake(config, auth, params):
        seen.append(params)
        return tables.get(params.table, {"success": True, "results": [], "total_count": 0})

    return _fake, seen


_PORTAL_ROW = {
    "sys_id": "aaaa1111bbbb2222cccc3333dddd4444",
    "title": "Self Service",
    "url_suffix": "sp",
    "default": "false",
    "homepage.id": "index",
    "login_page.id": "login",
    "notfound_page.id": "404",
    "sc_catalog.title": "Service Catalog",
    "kb_knowledge_base.title": "IT",
    "theme": "bbbb2222cccc3333dddd4444eeee5555",
    "theme.name": "Coral",
    "dark_theme": "",
    "css_variables": "$grid-gutter-width: 15px !default;",
    "sys_scope.scope": "global",
}
_THEME_ROW = {
    "sys_id": "bbbb2222cccc3333dddd4444eeee5555",
    "name": "Coral",
    "header": "cccc3333dddd4444eeee5555ffff6666",
    "header.name": "Stock Header",
    "footer": "",
    "navbar_fixed": "true",
    "footer_fixed": "false",
    "turn_off_scss_compilation": "false",
    "matching_now_experience_theme": "dddd4444eeee5555ffff6666aaaa7777",
    "matching_now_experience_theme.name": "Coral",
    "css_variables": "$brand-primary: #1f8476;",
    "sys_scope.scope": "global",
}


class TestGetPortal:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_detail_reads_dictionary_fields(self, mock_sn_query, mock_config, mock_auth_manager):
        fake, seen = _portal_side_effect({"sp_portal": {"success": True, "results": [_PORTAL_ROW]}})
        mock_sn_query.side_effect = fake
        result = get_portal(mock_config, mock_auth_manager, GetPortalParams(portal_id="sp"))

        portal = result["portal"]
        assert result["success"] is True
        assert portal["catalog"] == "Service Catalog"
        assert portal["homepage"] == "index"
        assert portal["is_default"] is False
        assert portal["css_variables"] == "$grid-gutter-width: 15px !default;"
        fields = seen[0].fields.split(",")
        for dead in ("default_", "css", "catalog", "sp_rectangle"):
            assert dead not in fields

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_detail_returns_the_whole_theme(self, mock_sn_query, mock_config, mock_auth_manager):
        css_row = {
            "order": "1",
            "sp_css_include": "eeee5555ffff6666aaaa7777bbbb8888",
            "sp_css_include.name": "Coral Style",
            "sp_css_include.source": "local",
            "sp_css_include.url": "",
            "sp_css_include.sp_css": "ffff6666aaaa7777bbbb8888cccc9999",
            "sp_css_include.sp_css.name": "Coral style",
        }
        fake, seen = _portal_side_effect(
            {
                "sp_portal": {"success": True, "results": [_PORTAL_ROW]},
                "sp_theme": {"success": True, "results": [_THEME_ROW]},
                "m2m_sp_theme_css_include": {
                    "success": True,
                    "results": [css_row],
                    "total_count": 1,
                },
                "m2m_sp_theme_js_include": {"success": True, "results": [], "total_count": 0},
            }
        )
        mock_sn_query.side_effect = fake
        theme = get_portal(mock_config, mock_auth_manager, GetPortalParams(portal_id="sp"))["theme"]

        assert theme["name"] == "Coral"
        assert theme["header"] == {"name": "Stock Header", "sys_id": _THEME_ROW["header"]}
        assert theme["footer"] is None
        assert theme["navbar_fixed"] is True
        assert theme["next_experience_theme"]["name"] == "Coral"
        assert theme["css_variables"] == "$brand-primary: #1f8476;"
        assert theme["css_includes"]["complete"] is True
        assert theme["css_includes"]["rows"][0]["sp_css"] == "Coral style"
        assert theme["css_includes"]["rows"][0]["url"] is None
        assert theme["js_includes"] == {"checked": True, "complete": True, "total": 0, "rows": []}
        include_queries = [q for q in seen if q.table.startswith("m2m_sp_theme")]
        assert all(q.query == f"sp_theme={_THEME_ROW['sys_id']}" for q in include_queries)

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_large_variables_are_withheld_with_the_call_that_fetches_them(
        self, mock_sn_query, mock_config, mock_auth_manager
    ):
        big = {**_THEME_ROW, "css_variables": "$x: 1;\n" * 2000, "sys_scope.scope": "x_myapp"}
        fake, _ = _portal_side_effect(
            {
                "sp_portal": {"success": True, "results": [_PORTAL_ROW]},
                "sp_theme": {"success": True, "results": [big]},
            }
        )
        mock_sn_query.side_effect = fake
        theme = get_portal(mock_config, mock_auth_manager, GetPortalParams(portal_id="sp"))["theme"]

        withheld = theme["css_variables"]
        assert withheld["withheld"] is True
        assert withheld["lines"] == 2000
        assert "families=['theme']" in withheld["get_all"] and "x_myapp" in withheld["get_all"]

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_capped_include_read_says_incomplete(
        self, mock_sn_query, mock_config, mock_auth_manager
    ):
        fake, _ = _portal_side_effect(
            {
                "sp_portal": {"success": True, "results": [_PORTAL_ROW]},
                "sp_theme": {"success": True, "results": [_THEME_ROW]},
                "m2m_sp_theme_css_include": {
                    "success": True,
                    "results": [{"sp_css_include.name": "a"}],
                    "total_count": 140,
                },
                "m2m_sp_theme_js_include": {"success": False, "message": "boom"},
            }
        )
        mock_sn_query.side_effect = fake
        theme = get_portal(mock_config, mock_auth_manager, GetPortalParams(portal_id="sp"))["theme"]

        assert theme["css_includes"]["complete"] is False
        assert theme["css_includes"]["total"] == 140
        # A failed read is not an empty one.
        assert theme["js_includes"]["checked"] is False

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_unreadable_theme_is_not_reported_as_no_theme(
        self, mock_sn_query, mock_config, mock_auth_manager
    ):
        fake, _ = _portal_side_effect(
            {
                "sp_portal": {"success": True, "results": [_PORTAL_ROW]},
                "sp_theme": {"success": True, "results": []},
            }
        )
        mock_sn_query.side_effect = fake
        theme = get_portal(mock_config, mock_auth_manager, GetPortalParams(portal_id="sp"))["theme"]

        assert theme["sys_id"] == _PORTAL_ROW["theme"]
        assert "hidden from this account by ACL" in theme["error"]

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_not_found(self, mock_sn_query, mock_config, mock_auth_manager):
        mock_sn_query.return_value = {"success": True, "results": []}

        params = GetPortalParams(portal_id="nonexistent")
        result = get_portal(mock_config, mock_auth_manager, params)

        assert result["success"] is False
        assert "absent, or hidden" in result["error"]


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
                    {
                        "sys_id": "c-1",
                        "order": "0",
                        "background_color": "#fff",
                        "container_class_name": "hero",
                        "class_name": "",
                        "width": "container-fluid",
                    }
                ],
            },
            # rows in container
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "r-1",
                        "sp_container": "c-1",
                        "order": "0",
                        "class_name": "row-tight",
                    }
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
                        "class_name": "col-pad",
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
                        "css": ".panel { border: 0; }",
                        "color": "primary",
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
        # Styling comes from the dictionary's columns — a css_class key was never real.
        assert layout[0]["css_class"] == "hero"
        assert layout[0]["width"] == "container-fluid"
        assert layout[0]["background_color"] == "#fff"
        assert layout[0]["rows"][0]["css_class"] == "row-tight"
        assert layout[0]["rows"][0]["columns"][0]["css_class"] == "col-pad"
        assert w["css"] == ".panel { border: 0; }"
        assert w["color"] == "primary"
        fields = [c[0][2].fields for c in mock_sn_query.call_args_list]
        assert not any("css_class" in f for f in fields)

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
                    {
                        "sys_id": "c-2",
                        "order": "2",
                        "background_color": "",
                        "container_class_name": "",
                    },
                    {
                        "sys_id": "c-1",
                        "order": "1",
                        "background_color": "",
                        "container_class_name": "",
                    },
                ],
            },
            {
                "success": True,
                "results": [
                    {"sys_id": "r-2", "sp_container": "c-1", "order": "2", "class_name": ""},
                    {"sys_id": "r-1", "sp_container": "c-1", "order": "1", "class_name": ""},
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
                        "class_name": "",
                    },
                    {
                        "sys_id": "col-1",
                        "sp_row": "r-1",
                        "order": "1",
                        "size": "6",
                        "class_name": "",
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
