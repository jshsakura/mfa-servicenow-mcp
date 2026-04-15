"""Tests for server_sse.py — SSE server, factory function, Starlette app creation."""

from unittest.mock import MagicMock, patch

from servicenow_mcp.server_sse import ServiceNowSSEMCP, create_servicenow_mcp, create_starlette_app
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


# ---------------------------------------------------------------------------
# create_starlette_app
# ---------------------------------------------------------------------------


class TestCreateStar:
    def test_creates_app_with_routes(self):
        mock_server = MagicMock()
        app = create_starlette_app(mock_server, debug=True)
        # Starlette app should have routes
        assert app is not None
        assert app.debug is True
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/sse" in route_paths


# ---------------------------------------------------------------------------
# ServiceNowSSEMCP
# ---------------------------------------------------------------------------


class TestServiceNowSSEMCP:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions", return_value={})
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_init(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        config = _make_config()
        server = ServiceNowSSEMCP(config)
        assert server.config.instance_url == "https://test.service-now.com"

    @patch("servicenow_mcp.server_sse.uvicorn")
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions", return_value={})
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_start_calls_uvicorn(self, mock_btsm, mock_ls, mock_gtd, mock_am, mock_uvicorn):
        config = _make_config()
        server = ServiceNowSSEMCP(config)
        server.start(host="127.0.0.1", port=9090)
        mock_uvicorn.run.assert_called_once()
        call_kwargs = mock_uvicorn.run.call_args
        assert (
            call_kwargs.kwargs.get("host") == "127.0.0.1"
            or call_kwargs[1].get("host") == "127.0.0.1"
        )


# ---------------------------------------------------------------------------
# create_servicenow_mcp factory
# ---------------------------------------------------------------------------


class TestCreateServicenowMcp:
    @patch("servicenow_mcp.server.AuthManager")
    @patch("servicenow_mcp.server.get_tool_definitions", return_value={})
    @patch("servicenow_mcp.server.load_skills", return_value=[])
    @patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={})
    def test_factory(self, mock_btsm, mock_ls, mock_gtd, mock_am):
        mcp = create_servicenow_mcp(
            instance_url="https://test.service-now.com",
            username="admin",
            password="password",
        )
        assert isinstance(mcp, ServiceNowSSEMCP)
        assert mcp.config.auth.type.value == "basic"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestSSEMain:
    @patch("servicenow_mcp.server_sse.create_servicenow_mcp")
    @patch("servicenow_mcp.server_sse.load_dotenv")
    @patch("sys.argv", ["server_sse", "--host", "0.0.0.0", "--port", "8080"])
    @patch.dict(
        "os.environ",
        {
            "SERVICENOW_INSTANCE_URL": "https://test.service-now.com",
            "SERVICENOW_USERNAME": "admin",
            "SERVICENOW_PASSWORD": "pass",
        },
    )
    def test_main(self, mock_dotenv, mock_factory):
        from servicenow_mcp.server_sse import main

        mock_instance = MagicMock()
        mock_factory.return_value = mock_instance
        main()
        mock_factory.assert_called_once()
        mock_instance.start.assert_called_once()
