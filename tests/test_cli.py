"""Tests for cli.py — argument parsing, config creation, main entry."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.cli import (
    _check_for_updates,
    _default_http_allowed_hosts,
    _pick_first_resolved,
    _resolve_env_reference,
    _split_csv,
    _warn_if_chromium_missing,
    create_config,
    main,
    parse_args,
)

# ---------------------------------------------------------------------------
# _resolve_env_reference
# ---------------------------------------------------------------------------


class TestResolveEnvReference:
    def test_none_returns_none(self):
        assert _resolve_env_reference(None) is None

    def test_empty_returns_empty(self):
        assert _resolve_env_reference("") == ""  # empty string returned as-is (falsy but not None)

    def test_plain_value_passthrough(self):
        assert _resolve_env_reference("admin") == "admin"

    @patch.dict("os.environ", {"MY_VAR": "secret"})
    def test_env_reference_resolved(self):
        assert _resolve_env_reference("${MY_VAR}") == "secret"

    @patch.dict("os.environ", {}, clear=True)
    def test_env_reference_missing(self):
        result = _resolve_env_reference("${MISSING_VAR}")
        assert result is None

    @patch.dict("os.environ", {"SELF_REF": "${SELF_REF}"})
    def test_self_referential_returns_none(self):
        assert _resolve_env_reference("${SELF_REF}") is None


# ---------------------------------------------------------------------------
# _pick_first_resolved
# ---------------------------------------------------------------------------


class TestPickFirstResolved:
    def test_first_non_empty(self):
        assert _pick_first_resolved(None, "value") == "value"

    def test_all_none(self):
        assert _pick_first_resolved(None, None) is None

    @patch.dict("os.environ", {"VAR": "resolved"})
    def test_resolves_env_ref(self):
        assert _pick_first_resolved("${VAR}") == "resolved"


# ---------------------------------------------------------------------------
# HTTP transport helpers
# ---------------------------------------------------------------------------


class TestHttpTransportHelpers:
    def test_split_csv_trims_empty_items(self):
        assert _split_csv("localhost, 127.0.0.1:8000, ,example.com") == [
            "localhost",
            "127.0.0.1:8000",
            "example.com",
        ]

    def test_default_http_allowed_hosts_include_loopback_with_port(self):
        hosts = _default_http_allowed_hosts("127.0.0.1", 8123)
        assert "127.0.0.1:8123" in hosts
        assert "localhost:8123" in hosts
        assert "[::1]:8123" in hosts


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------


class TestParseArgs:
    @patch(
        "sys.argv",
        ["cli", "--instance-url", "https://test.service-now.com", "--auth-type", "basic"],
    )
    def test_basic_args(self):
        args = parse_args()
        assert args.instance_url == "https://test.service-now.com"
        assert args.auth_type == "basic"

    @patch("sys.argv", ["cli", "--debug", "--timeout", "60"])
    @patch.dict("os.environ", {"SERVICENOW_INSTANCE_URL": "https://env.service-now.com"})
    def test_debug_and_timeout(self):
        args = parse_args()
        assert args.debug is True
        assert args.timeout == 60

    @patch(
        "sys.argv",
        [
            "cli",
            "--transport",
            "http",
            "--http-host",
            "0.0.0.0",
            "--http-port",
            "8123",
            "--http-path",
            "/servicenow-mcp",
        ],
    )
    @patch.dict("os.environ", {"SERVICENOW_INSTANCE_URL": "https://env.service-now.com"})
    def test_http_transport_args(self):
        args = parse_args()
        assert args.transport == "http"
        assert args.http_host == "0.0.0.0"
        assert args.http_port == 8123
        assert args.http_path == "/servicenow-mcp"

    @patch("sys.argv", ["cli"])
    @patch.dict(
        "os.environ",
        {
            "SERVICENOW_INSTANCE_URL": "https://env.service-now.com",
            "SERVICENOW_MCP_TRANSPORT": "http",
            "SERVICENOW_MCP_HTTP_JSON_RESPONSE": "true",
        },
    )
    def test_http_transport_env_defaults(self):
        args = parse_args()
        assert args.transport == "http"
        assert args.http_json_response is True


# ---------------------------------------------------------------------------
# create_config
# ---------------------------------------------------------------------------


class TestCreateConfig:
    def test_basic_auth_config(self):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "basic"
        args.username = "admin"
        args.password = "password"
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None
        config = create_config(args)
        assert config.instance_url == "https://test.service-now.com"
        assert config.auth.type.value == "basic"

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_ACTIVE_INSTANCE": "test",
            "SERVICENOW_INSTANCE_CONFIG": json.dumps(
                {
                    "dev": {"url": "https://dev.service-now.com"},
                    "test": {"url": "https://test.service-now.com"},
                }
            ),
        },
        clear=False,
    )
    def test_instance_config_active_alias_overrides_url(self):
        args = MagicMock()
        args.instance_url = "https://legacy.service-now.com"
        args.auth_type = "basic"
        args.username = "admin"
        args.password = "password"
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None

        config = create_config(args)

        assert config.instance_url == "https://test.service-now.com"

    @patch.dict(
        os.environ,
        {
            "SERVICENOW_ACTIVE_INSTANCE": "dev",
            "SERVICENOW_INSTANCE_CONFIG": json.dumps(
                {
                    "dev": {
                        "url": "https://dev.service-now.com",
                        "auth_type": "basic",
                        "username": "alias-admin",
                        "password": "alias-password",
                    }
                }
            ),
        },
        clear=True,
    )
    def test_instance_config_credentials_can_supply_basic_auth(self):
        args = MagicMock()
        args.instance_url = None
        args.auth_type = "basic"
        args.username = None
        args.password = None
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None

        config = create_config(args)

        assert config.instance_url == "https://dev.service-now.com"
        assert config.auth.basic.username == "alias-admin"

    def test_missing_instance_url_raises(self):
        args = MagicMock()
        args.instance_url = None
        args.auth_type = "basic"
        with patch.dict("os.environ", {}, clear=False):
            with patch("os.getenv", return_value=None):
                with pytest.raises(ValueError, match="instance URL"):
                    create_config(args)

    @patch.dict(os.environ, {}, clear=True)
    def test_basic_auth_missing_credentials_raises(self):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "basic"
        args.username = None
        args.password = None
        args.script_execution_api_resource_path = None
        with pytest.raises(ValueError, match="[Uu]sername"):
            create_config(args)

    def test_oauth_config(self):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "oauth"
        args.client_id = "cid"
        args.client_secret = "csecret"
        args.username = "admin"
        args.password = "password"
        args.token_url = None
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None
        config = create_config(args)
        assert config.auth.type.value == "oauth"
        assert config.auth.oauth is not None
        assert config.auth.oauth.token_url is not None
        assert config.auth.oauth.token_url.endswith("/oauth_token.do")

    def test_oauth_missing_credentials_raises(self):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "oauth"
        args.client_id = None
        args.client_secret = None
        args.username = None
        args.password = None
        args.token_url = None
        with pytest.raises(ValueError, match="[Cc]lient"):
            create_config(args)

    def test_api_key_config(self):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "api_key"
        args.api_key = "mykey"
        args.api_key_header = "X-Custom-Header"
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None
        config = create_config(args)
        assert config.auth.type.value == "api_key"

    def test_api_key_missing_raises(self):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "api_key"
        args.api_key = None
        args.api_key_header = "X-Key"
        with pytest.raises(ValueError, match="API key"):
            create_config(args)

    def test_browser_auth_config(self):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "browser"
        args.browser_username = "admin"
        args.browser_password = "pass"
        args.browser_login_url = None
        args.browser_probe_path = "/api/now/table/sys_user?sysparm_limit=1"
        args.browser_headless = "false"
        args.browser_timeout = 120
        args.browser_user_data_dir = None
        args.browser_session_ttl = 30
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None
        config = create_config(args)
        assert config.auth.type.value == "browser"

    def test_browser_probe_path_default_is_sys_user_preference(self):
        """v1.11.0: regardless of whether username is provided, default to
        sys_user_preference because many ServiceNow instances deny regular
        users read on the sys_user table, producing a permanent 401 polling
        loop. sys_user_preference is the safest universal default.
        """
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "browser"
        args.browser_username = "admin@example.com"
        args.browser_password = "pass"
        args.browser_login_url = None
        args.browser_probe_path = None
        args.browser_headless = "false"
        args.browser_timeout = 120
        args.browser_user_data_dir = None
        args.browser_session_ttl = 30
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None

        with patch.dict(os.environ, {"SERVICENOW_BROWSER_PROBE_PATH": ""}):
            config = create_config(args)

        probe = config.auth.browser.probe_path
        assert "sys_user_preference" in probe
        assert "user_name" not in probe  # no per-user sys_user query anymore

    def test_browser_probe_path_generic_fallback_when_no_username(self):
        """When neither probe_path nor username is provided, use the generic
        sys_user list probe (admin-only, but best we can do without credentials)."""
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "browser"
        args.browser_username = None
        args.browser_password = None
        args.browser_login_url = None
        args.browser_probe_path = None
        args.browser_headless = "false"
        args.browser_timeout = 120
        args.browser_user_data_dir = None
        args.browser_session_ttl = 30
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None

        with patch.dict(
            os.environ,
            {
                "SERVICENOW_BROWSER_PROBE_PATH": "",
                "SERVICENOW_BROWSER_USERNAME": "",
                "SERVICENOW_USERNAME": "",
            },
        ):
            config = create_config(args)

        probe = config.auth.browser.probe_path
        assert probe == "/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id"
        assert "user_name" not in probe

    def test_browser_probe_path_explicit_takes_priority_over_username(self):
        """An explicit browser_probe_path must win over the auto-generated one."""
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "browser"
        args.browser_username = "admin"
        args.browser_password = "pass"
        args.browser_login_url = None
        args.browser_probe_path = "/api/now/table/incident?sysparm_limit=1"
        args.browser_headless = "false"
        args.browser_timeout = 120
        args.browser_user_data_dir = None
        args.browser_session_ttl = 30
        args.debug = False
        args.timeout = 30
        args.script_execution_api_resource_path = None

        config = create_config(args)

        assert config.auth.browser.probe_path == "/api/now/table/incident?sysparm_limit=1"

    def test_unsupported_auth_type_raises(self):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "unknown_type"
        with pytest.raises(ValueError):
            create_config(args)


# ---------------------------------------------------------------------------
# _check_for_updates
# ---------------------------------------------------------------------------


class TestCheckForUpdates:
    @patch("servicenow_mcp.cli.urllib.request.urlopen")
    def test_newer_version_logs_warning(self, mock_urlopen):
        import json as _json

        mock_resp = MagicMock()
        mock_resp.read.return_value = _json.dumps({"info": {"version": "99.0.0"}}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        # Should not raise
        _check_for_updates()

    @patch("servicenow_mcp.cli.urllib.request.urlopen", side_effect=Exception("network"))
    def test_network_error_silent(self, mock_urlopen):
        # Should not raise
        _check_for_updates()


# ---------------------------------------------------------------------------
# _warn_if_chromium_missing
# ---------------------------------------------------------------------------


class TestWarnIfChromiumMissing:
    def test_non_browser_auth_skips(self):
        args = MagicMock()
        args.auth_type = "basic"
        # Should not raise — early-exit for non-browser auth.
        _warn_if_chromium_missing(args)

    def test_browser_auth_does_not_install(self):
        # Critical contract: this helper must NEVER call subprocess to
        # install Chromium (that would re-create the MCP handshake stall
        # we just removed). It only warns.
        import subprocess as _sp

        args = MagicMock()
        args.auth_type = "browser"
        with patch.object(_sp, "run") as mock_run, patch.object(_sp, "check_call") as mock_call:
            _warn_if_chromium_missing(args)
        mock_run.assert_not_called()
        mock_call.assert_not_called()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.setup_installer.main", return_value=0)
    def test_main_dispatches_setup_subcommand(self, mock_setup_main, mock_dotenv):
        with patch("sys.argv", ["cli", "setup", "opencode", "--instance-url", "https://x"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        mock_setup_main.assert_called_once_with(
            ["opencode", "--instance-url", "https://x"], action="setup"
        )

    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.setup_installer.main", return_value=0)
    def test_main_dispatches_remove_subcommand(self, mock_setup_main, mock_dotenv):
        with patch("sys.argv", ["cli", "remove", "opencode"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        mock_setup_main.assert_called_once_with(["opencode"], action="remove")

    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.cli._warn_if_chromium_missing")
    @patch("servicenow_mcp.cli._check_for_updates")
    @patch("servicenow_mcp.cli.parse_args")
    @patch("servicenow_mcp.cli.create_config")
    @patch("servicenow_mcp.cli.ServiceNowMCP")
    def test_main_success(
        self, mock_mcp, mock_create_config, mock_parse, mock_check, mock_ensure, mock_dotenv
    ):
        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.tool_package = None
        mock_args.transport = "stdio"
        mock_parse.return_value = mock_args
        mock_create_config.return_value = MagicMock()
        mock_mcp_instance = MagicMock()
        mock_mcp.return_value = mock_mcp_instance
        mock_mcp_instance.start.return_value = MagicMock()
        with patch("anyio.run"):
            main()

    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.cli.parse_args", side_effect=ValueError("bad config"))
    def test_main_value_error_exits(self, mock_parse, mock_dotenv):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.cli.parse_args", side_effect=RuntimeError("unexpected"))
    def test_main_unexpected_error_exits(self, mock_parse, mock_dotenv):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.cli._warn_if_chromium_missing")
    @patch("servicenow_mcp.cli._check_for_updates")
    @patch("servicenow_mcp.cli.parse_args")
    @patch("servicenow_mcp.cli.create_config")
    @patch("servicenow_mcp.cli.ServiceNowMCP")
    def test_main_with_tool_package(
        self, mock_mcp, mock_create_config, mock_parse, mock_check, mock_ensure, mock_dotenv
    ):
        mock_args = MagicMock()
        mock_args.debug = True
        mock_args.tool_package = "full"
        mock_args.transport = "stdio"
        mock_parse.return_value = mock_args
        mock_create_config.return_value = MagicMock()
        mock_mcp_instance = MagicMock()
        mock_mcp.return_value = mock_mcp_instance
        mock_mcp_instance.start.return_value = MagicMock()
        with patch.dict("os.environ", {}), patch("anyio.run"):
            main()

    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.cli._warn_if_chromium_missing")
    @patch("servicenow_mcp.cli._check_for_updates")
    @patch("servicenow_mcp.cli.parse_args")
    @patch("servicenow_mcp.cli.create_config")
    @patch("servicenow_mcp.cli.ServiceNowMCP")
    def test_main_http_transport_dispatches_http_runner(
        self, mock_mcp, mock_create_config, mock_parse, mock_check, mock_ensure, mock_dotenv
    ):
        mock_args = MagicMock()
        mock_args.debug = False
        mock_args.tool_package = None
        mock_args.transport = "http"
        mock_parse.return_value = mock_args
        mock_create_config.return_value = MagicMock()
        mock_mcp_instance = MagicMock()
        mock_mcp.return_value = mock_mcp_instance
        mock_server = MagicMock()
        mock_mcp_instance.start.return_value = mock_server
        with patch("anyio.run") as mock_anyio_run:
            main()
        from servicenow_mcp.cli import arun_http_server

        mock_anyio_run.assert_called_once_with(arun_http_server, mock_server, mock_args)
