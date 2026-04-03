from unittest.mock import MagicMock

from servicenow_mcp.tools.sn_api import GenericQueryParams, HealthCheckParams, sn_health, sn_query
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def test_sn_query_uses_auth_manager_make_request():
    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )
    auth_manager = MagicMock()
    response = MagicMock()
    response.json.return_value = {"result": [{"sys_id": "1"}]}
    auth_manager.make_request.return_value = response

    result = sn_query(config, auth_manager, GenericQueryParams(table="incident"))

    assert result["success"] is True
    assert result["count"] == 1
    assert auth_manager.make_request.call_count == 1


def test_sn_health_treats_browser_probe_acl_failure_as_authenticated_warning():
    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(probe_path="/api/now/table/incident?sysparm_limit=1"),
        ),
    )
    auth_manager = MagicMock()
    response = MagicMock()
    response.status_code = 403
    response.headers = {}
    response.url = "https://example.service-now.com/api/now/table/incident"
    response.is_redirect = False
    response.json.return_value = {"error": {"message": "forbidden"}}
    auth_manager.make_request.return_value = response

    result = sn_health(config, auth_manager, HealthCheckParams())

    assert result["ok"] is True
    assert result["status_code"] == 403
    assert "warning" in result
