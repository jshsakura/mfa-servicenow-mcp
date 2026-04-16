"""Tests for cli.py — argument parsing, config creation, main entry."""

import os
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.cli import (
    _check_for_updates,
    _ensure_playwright_browser,
    _pick_first_resolved,
    _resolve_env_reference,
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
# _ensure_playwright_browser
# ---------------------------------------------------------------------------


class TestEnsurePlaywrightBrowser:
    def test_non_browser_auth_skips(self):
        args = MagicMock()
        args.auth_type = "basic"
        # Should not raise
        _ensure_playwright_browser(args)


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
    @patch("servicenow_mcp.cli._ensure_playwright_browser")
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
    @patch("servicenow_mcp.cli._ensure_playwright_browser")
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
        mock_parse.return_value = mock_args
        mock_create_config.return_value = MagicMock()
        mock_mcp_instance = MagicMock()
        mock_mcp.return_value = mock_mcp_instance
        mock_mcp_instance.start.return_value = MagicMock()
        with patch.dict("os.environ", {}), patch("anyio.run"):
            main()
