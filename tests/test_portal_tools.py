from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    GetPortalComponentParams,
    GetWidgetBundleParams,
    UpdatePortalComponentParams,
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
