"""
Tests for deep analysis tools: resolve_widget_chain and resolve_page_dependencies.

Covers:
1. resolve_widget_chain — single widget, depth 1/2/3, SI extraction
2. resolve_page_dependencies — page-level multi-widget, dedup, dependency map
3. _extract_si_refs_from_script — SI name extraction from GlideRecord/GlideAjax
4. Edge cases: empty providers, no widgets on page, shared providers
"""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    ResolvePageDependenciesParams,
    ResolveWidgetChainParams,
    _extract_si_refs_from_script,
    resolve_page_dependencies,
    resolve_widget_chain,
)

# ================================================================
# _extract_si_refs_from_script
# ================================================================


class TestExtractSIRefs:
    def test_new_pattern(self):
        script = 'var helper = new MyCustomHelper();\nvar gr = new GlideRecord("incident");'
        refs = _extract_si_refs_from_script(script)
        assert "MyCustomHelper" in refs
        assert "GlideRecord" not in refs

    def test_glideajax_pattern(self):
        script = "var ga = new GlideAjax('MyAjaxHandler');\nga.addParam('sysparm_name', 'getData');"
        refs = _extract_si_refs_from_script(script)
        assert "MyAjaxHandler" in refs

    def test_mixed_patterns(self):
        script = """
        var util = new PortalUtils();
        var ajax = new GlideAjax("DataService");
        var gr = new GlideRecord("sys_user");
        var dt = new GlideDateTime();
        """
        refs = _extract_si_refs_from_script(script)
        assert "PortalUtils" in refs
        assert "DataService" in refs
        assert "GlideRecord" not in refs
        assert "GlideDateTime" not in refs

    def test_empty_script(self):
        assert _extract_si_refs_from_script("") == set()

    def test_no_matches(self):
        script = "var x = 1;\nfunction foo() { return x; }"
        assert _extract_si_refs_from_script(script) == set()

    def test_filters_all_builtin_constructors(self):
        builtins = [
            "GlideRecord",
            "GlideAggregate",
            "GlideDateTime",
            "GlideDate",
            "GlideDuration",
            "GlideFilter",
            "GlideRecordSecure",
            "GlideSession",
            "GlideSysAttachment",
            "GlideSchedule",
            "GlideSystem",
            "GlideElement",
            "GlideEmail",
            "Date",
            "Array",
            "Object",
            "Map",
            "Set",
            "RegExp",
            "Error",
            "JSON",
            "XMLDocument",
        ]
        for b in builtins:
            script = f"var x = new {b}();"
            refs = _extract_si_refs_from_script(script)
            assert b not in refs, f"{b} should be filtered"


# ================================================================
# resolve_widget_chain
# ================================================================


class TestResolveWidgetChain:
    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_depth_1_widget_only(self, mock_query, mock_config, mock_auth):
        mock_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "w1",
                    "name": "Widget1",
                    "id": "widget-1",
                    "script": "var gr = new GlideRecord('task');",
                    "client_script": "c.data",
                    "template": "<div>{{c.data.title}}</div>",
                }
            ],
        }

        result = resolve_widget_chain(
            mock_config,
            mock_auth,
            ResolveWidgetChainParams(widget_id="w1", depth=1),
        )

        assert result["success"] is True
        assert result["widget"]["name"] == "Widget1"
        assert result["providers"] == []
        assert result["script_includes"] == []
        assert mock_query.call_count == 1

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_depth_2_with_providers(self, mock_query, mock_config, mock_auth):
        mock_query.side_effect = [
            # Widget fetch
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "w1",
                        "name": "W1",
                        "id": "w-1",
                        "script": "",
                        "client_script": "",
                        "template": "",
                    }
                ],
            },
            # M2M fetch
            {
                "success": True,
                "results": [{"sp_angular_provider": "p1"}, {"sp_angular_provider": "p2"}],
            },
            # Provider fetch
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "p1",
                        "name": "ProvA",
                        "type": "factory",
                        "script": "function() {}",
                        "client_script": "",
                    },
                    {
                        "sys_id": "p2",
                        "name": "ProvB",
                        "type": "service",
                        "script": "svc code",
                        "client_script": "",
                    },
                ],
            },
        ]

        result = resolve_widget_chain(
            mock_config,
            mock_auth,
            ResolveWidgetChainParams(widget_id="w1", depth=2),
        )

        assert result["success"] is True
        assert len(result["providers"]) == 2
        assert result["providers"][0]["name"] == "ProvA"
        assert result["script_includes"] == []

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_depth_3_extracts_script_includes(self, mock_query, mock_config, mock_auth):
        mock_query.side_effect = [
            # Widget
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "w1",
                        "name": "W1",
                        "id": "w-1",
                        "script": "var h = new MyHelper();",
                        "client_script": "",
                        "template": "",
                    }
                ],
            },
            # M2M
            {"success": True, "results": [{"sp_angular_provider": "p1"}]},
            # Providers
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "p1",
                        "name": "ProvA",
                        "type": "factory",
                        "script": "var ajax = new GlideAjax('DataService');",
                        "client_script": "",
                    }
                ],
            },
            # Script includes
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "si1",
                        "name": "MyHelper",
                        "api_name": "global.MyHelper",
                        "script": "var MyHelper = Class.create();",
                        "client_callable": "false",
                    },
                    {
                        "sys_id": "si2",
                        "name": "DataService",
                        "api_name": "global.DataService",
                        "script": "var DataService = Class.create();",
                        "client_callable": "true",
                    },
                ],
            },
        ]

        result = resolve_widget_chain(
            mock_config,
            mock_auth,
            ResolveWidgetChainParams(widget_id="w1", depth=3),
        )

        assert result["success"] is True
        assert len(result["script_includes"]) == 2
        si_names = {si["name"] for si in result["script_includes"]}
        assert "MyHelper" in si_names
        assert "DataService" in si_names

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_widget_not_found(self, mock_query, mock_config, mock_auth):
        mock_query.return_value = {"success": True, "results": []}

        result = resolve_widget_chain(
            mock_config,
            mock_auth,
            ResolveWidgetChainParams(widget_id="nonexistent"),
        )

        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_truncation(self, mock_query, mock_config, mock_auth):
        long_script = "x" * 20000
        mock_query.return_value = {
            "success": True,
            "results": [
                {
                    "sys_id": "w1",
                    "name": "W1",
                    "id": "w-1",
                    "script": long_script,
                    "client_script": "",
                    "template": "",
                }
            ],
        }

        result = resolve_widget_chain(
            mock_config,
            mock_auth,
            ResolveWidgetChainParams(widget_id="w1", depth=1, max_source_length=1000),
        )

        assert len(result["widget"]["script"]) < 1100
        assert "TRUNCATED" in result["widget"]["script"]


# ================================================================
# resolve_page_dependencies
# ================================================================


class TestResolvePageDependencies:
    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_page_with_multiple_widgets(self, mock_get_page, mock_query, mock_config, mock_auth):
        # Page layout with 3 widgets
        mock_get_page.return_value = {
            "success": True,
            "page": {"title": "Test Page", "id": "test_page"},
            "instances": [
                {"widget_sys_id": "w1", "widget_name": "Widget1"},
                {"widget_sys_id": "w2", "widget_name": "Widget2"},
                {"widget_sys_id": "w3", "widget_name": "Widget3"},
            ],
        }
        mock_query.side_effect = [
            # Widgets batch fetch
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "w1",
                        "name": "Widget1",
                        "script": "a",
                        "client_script": "",
                        "template": "",
                    },
                    {
                        "sys_id": "w2",
                        "name": "Widget2",
                        "script": "b",
                        "client_script": "",
                        "template": "",
                    },
                    {
                        "sys_id": "w3",
                        "name": "Widget3",
                        "script": "c",
                        "client_script": "",
                        "template": "",
                    },
                ],
            },
            # M2M: w1→p1,p2; w2→p2,p3; w3→p1 (p1 and p2 are shared)
            {
                "success": True,
                "results": [
                    {"sp_widget": "w1", "sp_angular_provider": "p1"},
                    {"sp_widget": "w1", "sp_angular_provider": "p2"},
                    {"sp_widget": "w2", "sp_angular_provider": "p2"},
                    {"sp_widget": "w2", "sp_angular_provider": "p3"},
                    {"sp_widget": "w3", "sp_angular_provider": "p1"},
                ],
            },
            # Providers (deduplicated: p1, p2, p3 — only 3 not 5)
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "p1",
                        "name": "SharedProv1",
                        "type": "factory",
                        "script": "sp1",
                        "client_script": "",
                    },
                    {
                        "sys_id": "p2",
                        "name": "SharedProv2",
                        "type": "service",
                        "script": "sp2",
                        "client_script": "",
                    },
                    {
                        "sys_id": "p3",
                        "name": "UniqueProv3",
                        "type": "factory",
                        "script": "sp3",
                        "client_script": "",
                    },
                ],
            },
        ]

        result = resolve_page_dependencies(
            mock_config,
            mock_auth,
            ResolvePageDependenciesParams(page_id="test_page", depth=2),
        )

        assert result["success"] is True
        assert len(result["widgets"]) == 3
        assert len(result["providers"]) == 3  # Deduplicated!

        # Dependency map
        dep_map = result["dependency_map"]
        assert "SharedProv1" in dep_map["shared_providers"]
        assert dep_map["shared_providers"]["SharedProv1"]["used_by_widgets"] == 2
        assert "SharedProv2" in dep_map["shared_providers"]
        assert dep_map["shared_providers"]["SharedProv2"]["used_by_widgets"] == 2

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_empty_page(self, mock_get_page, mock_config, mock_auth):
        mock_get_page.return_value = {
            "success": True,
            "page": {"title": "Empty Page", "id": "empty"},
            "instances": [],
        }

        result = resolve_page_dependencies(
            mock_config,
            mock_auth,
            ResolvePageDependenciesParams(page_id="empty"),
        )

        assert result["success"] is True
        assert len(result["widgets"]) == 0

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_page_not_found(self, mock_get_page, mock_config, mock_auth):
        mock_get_page.return_value = {"success": False}

        result = resolve_page_dependencies(
            mock_config,
            mock_auth,
            ResolvePageDependenciesParams(page_id="nonexistent"),
        )

        assert result["success"] is False

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_depth_3_with_si_dedup(self, mock_get_page, mock_query, mock_config, mock_auth):
        """Multiple widgets reference the same SI — should be fetched once."""
        mock_get_page.return_value = {
            "success": True,
            "page": {"title": "Complex", "id": "complex"},
            "instances": [
                {"widget_sys_id": "w1", "widget_name": "W1"},
                {"widget_sys_id": "w2", "widget_name": "W2"},
            ],
        }
        mock_query.side_effect = [
            # Widgets — both reference SharedUtil
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "w1",
                        "name": "W1",
                        "script": "var u = new SharedUtil();",
                        "client_script": "",
                        "template": "",
                    },
                    {
                        "sys_id": "w2",
                        "name": "W2",
                        "script": "var u = new SharedUtil(); var h = new Helper();",
                        "client_script": "",
                        "template": "",
                    },
                ],
            },
            # M2M: no providers
            {"success": True, "results": []},
            # Script includes (deduplicated: SharedUtil + Helper = 2, not 3)
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "si1",
                        "name": "SharedUtil",
                        "api_name": "global.SharedUtil",
                        "script": "code1",
                        "client_callable": "false",
                    },
                    {
                        "sys_id": "si2",
                        "name": "Helper",
                        "api_name": "global.Helper",
                        "script": "code2",
                        "client_callable": "false",
                    },
                ],
            },
        ]

        result = resolve_page_dependencies(
            mock_config,
            mock_auth,
            ResolvePageDependenciesParams(page_id="complex", depth=3),
        )

        assert result["success"] is True
        assert len(result["script_includes"]) == 2
        si_names = {si["name"] for si in result["script_includes"]}
        assert si_names == {"SharedUtil", "Helper"}

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_save_to_disk(self, mock_get_page, mock_query, mock_config, mock_auth, tmp_path):
        mock_get_page.return_value = {
            "success": True,
            "page": {"title": "Save Test", "id": "save_test"},
            "instances": [{"widget_sys_id": "w1", "widget_name": "W1"}],
        }
        mock_query.side_effect = [
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "w1",
                        "name": "W1",
                        "script": "server code",
                        "client_script": "client code",
                        "template": "<div>hi</div>",
                    }
                ],
            },
            {"success": True, "results": []},  # no providers
        ]

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = resolve_page_dependencies(
                mock_config,
                mock_auth,
                ResolvePageDependenciesParams(page_id="save_test", depth=3, save_to_disk=True),
            )

        assert result["success"] is True
        assert "saved_to" in result
        saved_dir = tmp_path / "temp" / "test" / "save_test"
        assert (saved_dir / "_dependency_map.json").exists()
        assert (saved_dir / "sp_widget" / "W1" / "script.js").exists()
        assert (saved_dir / "sp_widget" / "W1" / "template.html").exists()
