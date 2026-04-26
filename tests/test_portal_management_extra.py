"""Extra tests for portal_management_tools.py — cover missed branches (94% → ~100%)."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_management_tools import (
    GetPageParams,
    GetWidgetInstanceParams,
    _order_key,
    get_page,
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
def mock_auth():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


# ---------------------------------------------------------------------------
# _order_key: lines 38-39 (TypeError/ValueError branch)
# ---------------------------------------------------------------------------


class TestOrderKeyEdgeCases:
    def test_none_order(self):
        result = _order_key({"sys_id": "abc"})
        assert result == (0, "abc")

    def test_non_numeric_order(self):
        result = _order_key({"order": "not-a-number", "sys_id": "xyz"})
        assert result == (0, "xyz")

    def test_missing_sys_id(self):
        result = _order_key({"order": "5"})
        assert result == (5, "")


# ---------------------------------------------------------------------------
# get_page: line 264 (query failure branch)
# ---------------------------------------------------------------------------


class TestGetPageQueryFailure:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_page_list_query_failure(self, mock_sn_query, mock_config, mock_auth):
        mock_sn_query.return_value = {"success": False, "message": "Server error"}
        params = GetPageParams(limit=10)
        result = get_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert result["pages"] == []


# ---------------------------------------------------------------------------
# _build_layout: line 296 (no containers)
# ---------------------------------------------------------------------------


class TestBuildLayoutNoContainers:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_layout_no_containers(self, mock_sn_query, mock_config, mock_auth):
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
            # containers: empty
            {"success": True, "results": []},
        ]
        params = GetPageParams(page_id="index", include_layout=True)
        result = get_page(mock_config, mock_auth, params)
        assert result["success"] is True
        assert result["page"]["layout"] == []


# ---------------------------------------------------------------------------
# _build_layout: lines 357, 370, 377, 392 (skip entries with missing refs)
# ---------------------------------------------------------------------------


class TestBuildLayoutSkipsMissingRefs:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_instance_without_column_skipped(self, mock_sn_query, mock_config, mock_auth):
        """Instance with empty sp_column should be skipped (line 357)."""
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
            {
                "success": True,
                "results": [
                    {"sys_id": "c-1", "order": "0", "background_color": "", "css_class": ""}
                ],
            },
            {
                "success": True,
                "results": [
                    {"sys_id": "r-1", "sp_container": "c-1", "order": "0", "css_class": ""}
                ],
            },
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
            # Instance with empty sp_column
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "inst-1",
                        "sp_column": "",
                        "sp_widget": "wid-1",
                        "order": "0",
                        "widget_parameters": "",
                        "css": "",
                    }
                ],
            },
            {"success": True, "results": [{"sys_id": "wid-1", "id": "w", "name": "W"}]},
        ]
        params = GetPageParams(page_id="index", include_layout=True)
        result = get_page(mock_config, mock_auth, params)
        assert result["success"] is True
        # The instance with empty sp_column is skipped, so no widgets
        widgets = result["page"]["layout"][0]["rows"][0]["columns"][0]["widgets"]
        assert len(widgets) == 0

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_instance_with_widget_parameters(self, mock_sn_query, mock_config, mock_auth):
        """Instance with widget_parameters should include them (line 370)."""
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
            {
                "success": True,
                "results": [
                    {"sys_id": "c-1", "order": "0", "background_color": "", "css_class": ""}
                ],
            },
            {
                "success": True,
                "results": [
                    {"sys_id": "r-1", "sp_container": "c-1", "order": "0", "css_class": ""}
                ],
            },
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
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "inst-1",
                        "sp_column": "col-1",
                        "sp_widget": "wid-1",
                        "order": "0",
                        "widget_parameters": '{"limit":10}',
                        "css": "",
                    }
                ],
            },
            {"success": True, "results": [{"sys_id": "wid-1", "id": "w", "name": "W"}]},
        ]
        params = GetPageParams(page_id="index", include_layout=True)
        result = get_page(mock_config, mock_auth, params)
        assert result["success"] is True
        widget = result["page"]["layout"][0]["rows"][0]["columns"][0]["widgets"][0]
        assert widget["widget_parameters"] == '{"limit":10}'

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_column_without_row_skipped(self, mock_sn_query, mock_config, mock_auth):
        """Column with empty sp_row should be skipped (line 377)."""
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
            {
                "success": True,
                "results": [
                    {"sys_id": "c-1", "order": "0", "background_color": "", "css_class": ""}
                ],
            },
            {
                "success": True,
                "results": [
                    {"sys_id": "r-1", "sp_container": "c-1", "order": "0", "css_class": ""}
                ],
            },
            # Column with empty sp_row
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "col-1",
                        "sp_row": "",
                        "order": "0",
                        "size": "12",
                        "css_class": "",
                    }
                ],
            },
            {"success": True, "results": []},
            {"success": True, "results": []},
        ]
        params = GetPageParams(page_id="index", include_layout=True)
        result = get_page(mock_config, mock_auth, params)
        assert result["success"] is True
        columns = result["page"]["layout"][0]["rows"][0]["columns"]
        assert len(columns) == 0

    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_row_without_container_skipped(self, mock_sn_query, mock_config, mock_auth):
        """Row with empty sp_container should be skipped (line 392)."""
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
            {
                "success": True,
                "results": [
                    {"sys_id": "c-1", "order": "0", "background_color": "", "css_class": ""}
                ],
            },
            # Row with empty sp_container
            {
                "success": True,
                "results": [
                    {"sys_id": "r-1", "sp_container": "", "order": "0", "css_class": ""},
                ],
            },
            {"success": True, "results": []},
            {"success": True, "results": []},
            {"success": True, "results": []},
        ]
        params = GetPageParams(page_id="index", include_layout=True)
        result = get_page(mock_config, mock_auth, params)
        assert result["success"] is True
        rows = result["page"]["layout"][0]["rows"]
        assert len(rows) == 0


# ---------------------------------------------------------------------------
# get_widget_instance: line 522 (query failure)
# ---------------------------------------------------------------------------


class TestListWidgetInstancesQueryFailure:
    @patch("servicenow_mcp.tools.portal_management_tools.sn_query")
    def test_query_failure(self, mock_sn_query, mock_config, mock_auth):
        mock_sn_query.return_value = {"success": False, "message": "Server error"}
        params = GetWidgetInstanceParams(widget_id="wid-1")
        result = get_widget_instance(mock_config, mock_auth, params)
        assert result["success"] is False
        assert result["instances"] == []
