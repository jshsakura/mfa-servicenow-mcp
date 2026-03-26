from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    DownloadPortalSourcesParams,
    GetPortalComponentParams,
    GetWidgetBundleParams,
    UpdatePortalComponentParams,
    download_portal_sources,
    get_portal_component_code,
    get_widget_bundle,
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
def test_get_portal_component_code_truncation(mock_sn_query, mock_config, mock_auth_manager):
    # Mock Large Script
    large_script = "x" * 15000
    mock_sn_query.return_value = {
        "success": True,
        "results": [{"script": large_script, "sys_id": "sys-1", "name": "Test"}],
    }

    params = GetPortalComponentParams(table="sp_widget", sys_id="sys-1", fields=["script"])
    result = get_portal_component_code(mock_config, mock_auth_manager, params)

    assert len(result["script"]) < 15000
    assert "[TRUNCATED FOR CONTEXT SAFETY]" in result["script"]
    assert result["_script_is_truncated"] is True


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
        DownloadPortalSourcesParams(output_dir=str(tmp_path), scope="x_bpm"),
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
