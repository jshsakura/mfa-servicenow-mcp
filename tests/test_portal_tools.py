from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    DetectAngularImplicitGlobalsParams,
    DownloadPortalSourcesParams,
    GetPortalComponentParams,
    GetWidgetBundleParams,
    SearchPortalRegexMatchesParams,
    UpdatePortalComponentParams,
    detect_angular_implicit_globals,
    download_portal_sources,
    get_portal_component_code,
    get_widget_bundle,
    search_portal_regex_matches,
    update_portal_component,
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


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_get_widget_bundle_success(mock_sn_query, mock_config, mock_auth_manager):
    # Mock Widget Data
    mock_sn_query.side_effect = [
        {
            "success": True,
            "results": [
                {
                    "name": "Test Widget",
                    "sys_id": "wid-123",
                    "template": "<div></div>",
                    "id": "test_id",
                }
            ],
        },  # Widget
        {"success": True, "results": [{"sp_angular_provider": {"value": "prov-123"}}]},  # M2M
        {
            "success": True,
            "results": [{"name": "Test Provider", "sys_id": "prov-123", "type": "factory"}],
        },  # Provider
    ]

    params = GetWidgetBundleParams(widget_id="test_id")
    result = get_widget_bundle(mock_config, mock_auth_manager, params)

    assert "widget" in result
    assert result["widget"]["name"] == "Test Widget"
    assert "angular_providers" in result
    assert len(result["angular_providers"]) == 1
    assert result["angular_providers"][0]["name"] == "Test Provider"


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_get_portal_component_code_pagination(mock_sn_query, mock_config, mock_auth_manager):
    # Mock large script with line breaks
    large_script = "\n".join([f"var line{i} = {i};" for i in range(2000)])
    mock_sn_query.return_value = {
        "success": True,
        "results": [{"script": large_script, "sys_id": "sys-1", "name": "Test"}],
    }

    # First page
    params = GetPortalComponentParams(
        table="sp_widget", sys_id="sys-1", fields=["script"], script_max_length=5000
    )
    result = get_portal_component_code(mock_config, mock_auth_manager, params)

    assert len(result["script"]) <= 5000
    assert result["_script_total_length"] == len(large_script)
    assert result["_script_offset"] == 0
    assert result["_script_has_more"] is True
    assert result["_script_next_offset"] > 0
    # Should end at a newline boundary
    assert result["script"].endswith("\n")

    # Second page using next_offset
    params2 = GetPortalComponentParams(
        table="sp_widget",
        sys_id="sys-1",
        fields=["script"],
        script_offset=result["_script_next_offset"],
        script_max_length=5000,
    )
    result2 = get_portal_component_code(mock_config, mock_auth_manager, params2)
    assert result2["_script_offset"] == result["_script_next_offset"]


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_get_portal_component_code_minified_fallback(mock_sn_query, mock_config, mock_auth_manager):
    # Minified code — no newlines
    large_script = ";".join([f"var x{i}={i}" for i in range(3000)])
    mock_sn_query.return_value = {
        "success": True,
        "results": [{"script": large_script, "sys_id": "sys-1", "name": "Test"}],
    }

    params = GetPortalComponentParams(
        table="sp_widget", sys_id="sys-1", fields=["script"], script_max_length=5000
    )
    result = get_portal_component_code(mock_config, mock_auth_manager, params)

    assert len(result["script"]) <= 5000
    # Should end at a semicolon boundary
    assert result["script"].endswith(";")


def test_update_portal_component_success(mock_config, mock_auth_manager):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_auth_manager.make_request.return_value = mock_response

    params = UpdatePortalComponentParams(
        table="sp_widget", sys_id="sys-1", update_data={"client_script": "function() {}"}
    )
    result = update_portal_component(mock_config, mock_auth_manager, params)

    assert result["message"] == "Update successful"
    mock_auth_manager.make_request.assert_called_once()


def test_portal_search_defaults_are_conservative():
    params = SearchPortalRegexMatchesParams()

    assert params.source_types == ["widget"]
    assert params.include_linked_script_includes is False
    assert params.include_linked_angular_providers is False
    assert params.max_widgets == 25
    assert params.max_matches == 25
    assert params.page_size == 50


def test_portal_download_defaults_are_conservative():
    params = DownloadPortalSourcesParams()

    assert params.include_linked_script_includes is False
    assert params.include_linked_angular_providers is False
    assert params.max_widgets == 25
    assert params.page_size == 50


def test_portal_component_code_default_chunk_is_conservative():
    params = GetPortalComponentParams(table="sp_widget", sys_id="sys-1")

    assert params.script_max_length == 8000


def test_detect_angular_defaults_are_conservative():
    params = DetectAngularImplicitGlobalsParams()

    assert params.max_providers == 25
    assert params.max_matches == 25
    assert params.page_size == 50


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_download_portal_sources_exports_widget_provider_and_script_include(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query.side_effect = [
        {
            "success": True,
            "results": [
                {
                    "sys_id": "wid-1",
                    "name": "Quotation Widget",
                    "id": "quotation_widget",
                    "sys_scope": "x_bpm",
                    "template": "<div>ok</div>",
                    "script": "var si = new x_bpm.QuotationUtil();",
                    "client_script": "",
                    "link": "function link() {}",
                    "css": ".a{}",
                    "option_schema": '{"type":"object"}',
                    "demo_data": '{"demo":true}',
                }
            ],
        },
        {
            "success": True,
            "results": [
                {
                    "element": "template",
                    "column_label": "Body HTML template",
                    "internal_type": "html_template",
                    "read_only": "false",
                    "mandatory": "false",
                    "max_length": "65000",
                    "choice": "0",
                    "reference": "",
                    "attributes": "",
                }
            ],
        },
        {
            "success": True,
            "results": [
                {
                    "sp_widget": {"value": "wid-1"},
                    "sp_angular_provider": {"value": "prov-1"},
                }
            ],
        },
        {
            "success": True,
            "results": [
                {
                    "sys_id": "prov-1",
                    "name": "quotationService",
                    "script": "angular.module('x').factory('quotationService', function(){});",
                }
            ],
        },
        {
            "success": True,
            "results": [
                {
                    "sys_id": "si-1",
                    "name": "QuotationUtil",
                    "api_name": "x_bpm.QuotationUtil",
                    "script": "var gr = new GlideRecord('task');",
                }
            ],
        },
    ]

    result = download_portal_sources(
        mock_config,
        mock_auth_manager,
        DownloadPortalSourcesParams(
            output_dir=str(tmp_path),
            scope="x_bpm",
            include_linked_script_includes=True,
            include_linked_angular_providers=True,
        ),
    )

    assert result["success"] is True
    assert result["summary"]["widgets"] == 1
    assert result["summary"]["angular_providers"] == 1
    assert result["summary"]["script_includes"] == 1

    scope_root = tmp_path / "x_bpm"
    assert (tmp_path / "_settings.json").exists()
    assert (tmp_path / "scopes.json").exists()
    assert (tmp_path / "_last_error.json").exists()
    assert (scope_root / "sp_widget" / "quotation_widget" / "script.js").exists()
    assert (scope_root / "sp_widget" / "quotation_widget" / "client_script.js").exists()
    assert (scope_root / "sp_widget" / "quotation_widget" / "_widget.json").exists()
    assert (scope_root / "sp_widget" / "quotation_widget" / "_test_urls.txt").exists()
    assert (scope_root / "sp_angular_provider" / "quotationService.script.js").exists()
    assert (scope_root / "sys_script_include" / "QuotationUtil.script.js").exists()
    assert (scope_root / "sp_widget" / "_map.json").exists()
    assert (scope_root / "sp_angular_provider" / "_map.json").exists()
    assert (scope_root / "sys_script_include" / "_map.json").exists()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_download_portal_sources_defaults_to_current_working_directory(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query.return_value = {"success": True, "results": []}

    with patch("pathlib.Path.cwd", return_value=tmp_path):
        result = download_portal_sources(
            mock_config,
            mock_auth_manager,
            DownloadPortalSourcesParams(scope="x_bpm"),
        )

    assert result["success"] is True
    assert (tmp_path / "_settings.json").exists()
    assert (tmp_path / "_last_error.json").exists()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_download_portal_sources_widget_ids_mode_handles_missing_widget(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = download_portal_sources(
        mock_config,
        mock_auth_manager,
        DownloadPortalSourcesParams(
            output_dir=str(tmp_path), scope="x_bpm", widget_ids=["missing"]
        ),
    )

    assert result["success"] is True
    assert result["summary"]["widgets"] == 0
    assert (tmp_path / "x_bpm" / "sp_widget" / "_map.json").exists()


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_search_portal_regex_matches_returns_compact_line_matches(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.side_effect = [
        {
            "success": True,
            "results": [
                {
                    "sys_id": "wid-1",
                    "name": "RFQ Entry Widget",
                    "id": "rfq_entry_widget",
                    "script": "data.url='/ybpm?id=rfqentry'; var util = new RedirectUtil();",
                    "template": "",
                    "client_script": "",
                    "link": "",
                    "css": "",
                }
            ],
        },
        {
            "success": True,
            "results": [{"sp_angular_provider": {"value": "prov-1"}}],
        },
        {
            "success": True,
            "results": [
                {
                    "sys_id": "prov-1",
                    "name": "redirectProvider",
                    "script": "return '/ybpm?id=rfqentry';",
                }
            ],
        },
        {
            "success": True,
            "results": [
                {
                    "sys_id": "si-1",
                    "name": "RedirectUtil",
                    "script": "var path = '/ybpm?id=rfqentry';",
                }
            ],
        },
    ]

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            updated_by="jeongsh@sorin.co.kr",
            regex=r"/ybpm\?id=rfqentry",
            compact_output=True,
            source_types=["widget", "script_include", "angular_provider"],
            include_linked_script_includes=True,
            include_linked_angular_providers=True,
            max_widgets=20,
            max_matches=20,
        ),
    )

    assert result["success"] is True
    assert result["scan_summary"]["widgets_scanned"] == 1
    assert result["scan_summary"]["linked_angular_providers_scanned"] == 1
    assert result["scan_summary"]["linked_script_includes_scanned"] == 1
    assert result["scan_summary"]["match_count"] == 3
    assert any("Linked component expansion is enabled" in warning for warning in result["warnings"])

    locations = [item["location"] for item in result["matches"]]
    assert "sp_widget/RFQ_Entry_Widget/script" in locations
    assert "sp_angular_provider/redirectProvider/script" in locations
    assert "sys_script_include/RedirectUtil/script" in locations
    assert all(isinstance(item["line"], int) and item["line"] >= 1 for item in result["matches"])


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_search_portal_regex_matches_allows_missing_updated_by(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(regex=r"/ybpm\?id=rfqentry", max_widgets=5, max_matches=5),
    )

    assert result["success"] is True
    args, _kwargs = mock_sn_query.call_args
    query = args[2].query
    assert "sys_updated_by=" not in query
    assert any("No explicit widget/provider target" in warning for warning in result["warnings"])


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_search_portal_regex_matches_warns_and_clamps_broad_requests(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            regex=r"abc",
            max_widgets=999,
            max_matches=999,
            include_linked_script_includes=True,
            include_linked_angular_providers=True,
        ),
    )

    assert result["success"] is True
    assert result["scan_summary"]["max_widgets"] == 100
    assert result["scan_summary"]["max_matches"] == 100
    assert any("reduced to 100" in warning for warning in result["warnings"])
    assert any("Broad widget scans" in warning for warning in result["warnings"])


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_search_portal_regex_matches_targeted_widget_avoids_broad_target_warning(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {"success": True, "results": []}

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(regex=r"abc", widget_ids=["wid-1"]),
    )

    assert result["success"] is True
    assert not any(
        "No explicit widget/provider target" in warning for warning in result["warnings"]
    )


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_search_portal_regex_matches_minimal_output_mode(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {
        "success": True,
        "results": [
            {
                "sys_id": "wid-1",
                "name": "RFQ Entry Widget",
                "id": "rfq_entry_widget",
                "script": "data.url='/ybpm?id=rfqentry';",
                "template": "",
                "client_script": "",
                "link": "",
                "css": "",
            }
        ],
    }

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            regex=r"/ybpm\?id=rfqentry",
            output_mode="minimal",
            include_linked_script_includes=False,
            include_linked_angular_providers=False,
            max_widgets=5,
            max_matches=5,
        ),
    )

    assert result["success"] is True
    assert result["filters"]["output_mode"] == "minimal"
    assert result["scan_summary"]["output_mode"] == "minimal"
    assert len(result["matches"]) == 1
    assert set(result["matches"][0].keys()) == {"location", "line"}


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_detect_angular_implicit_globals_finds_undeclared_assignment(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {
        "success": True,
        "results": [
            {
                "sys_id": "prov-1",
                "name": "providerOne",
                "script": "function f(){ test = 'x'; }",
            }
        ],
    }

    result = detect_angular_implicit_globals(
        mock_config,
        mock_auth_manager,
        DetectAngularImplicitGlobalsParams(output_mode="full", max_matches=10),
    )

    assert result["success"] is True
    assert result["scan_summary"]["providers_scanned"] == 1
    assert result["scan_summary"]["finding_count"] == 1
    assert any("No explicit widget/provider target" in warning for warning in result["warnings"])
    finding = result["findings"][0]
    assert finding["variable"] == "test"
    assert finding["issue"] == "implicit_global_assignment"


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_detect_angular_implicit_globals_respects_let_const_declarations(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {
        "success": True,
        "results": [
            {
                "sys_id": "prov-1",
                "name": "providerOne",
                "script": "function f(){ let test = ''; const done = true; test = 'y'; doneLocal = 1; }",
            }
        ],
    }

    result = detect_angular_implicit_globals(
        mock_config,
        mock_auth_manager,
        DetectAngularImplicitGlobalsParams(output_mode="full", max_matches=10),
    )

    assert result["success"] is True
    assert result["scan_summary"]["finding_count"] == 1
    assert result["findings"][0]["variable"] == "doneLocal"


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_detect_angular_implicit_globals_minimal_mode_shape(
    mock_sn_query, mock_config, mock_auth_manager
):
    mock_sn_query.return_value = {
        "success": True,
        "results": [
            {
                "sys_id": "prov-1",
                "name": "providerOne",
                "script": "test = 'x';",
            }
        ],
    }

    result = detect_angular_implicit_globals(
        mock_config,
        mock_auth_manager,
        DetectAngularImplicitGlobalsParams(output_mode="minimal", max_matches=10),
    )

    assert result["success"] is True
    assert result["filters"]["output_mode"] == "minimal"
    assert set(result["findings"][0].keys()) == {"location", "line"}


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_download_portal_sources_warns_and_clamps_broad_requests(
    mock_sn_query, mock_config, mock_auth_manager, tmp_path
):
    mock_sn_query.side_effect = [
        {"success": True, "results": []},
        {"success": True, "results": []},
    ]

    result = download_portal_sources(
        mock_config,
        mock_auth_manager,
        DownloadPortalSourcesParams(
            output_dir=str(tmp_path),
            scope="x_bpm",
            max_widgets=999,
            include_linked_script_includes=True,
            include_linked_angular_providers=True,
        ),
    )

    assert result["success"] is True
    assert any("reduced to 100" in warning for warning in result["warnings"])
    assert any("Linked component expansion is enabled" in warning for warning in result["warnings"])
