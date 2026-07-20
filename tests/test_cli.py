"""Tests for cli.py — argument parsing, config creation, main entry."""

import json
import logging
import os
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.cli import (
    _check_for_updates,
    _default_http_allowed_hosts,
    _maybe_use_bundled_chromium,
    _pick_first_resolved,
    _resolve_env_reference,
    _split_csv,
    _warn_if_chromium_missing,
    configure_logging,
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
        args.server_name = "ServiceNow"
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
        args.server_name = "ServiceNow"

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
        args.server_name = "ServiceNow"

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
        args.server_name = "ServiceNow"
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
        args.server_name = "ServiceNow"
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
        args.server_name = "ServiceNow"
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
        args.server_name = "ServiceNow"

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
        args.server_name = "ServiceNow"

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
        args.server_name = "ServiceNow"

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


class TestMaybeUseBundledChromium:
    """Auto-detects any ms-play* directory next to the exe so the release
    zip works whether the user renames it to ms-playwright/ or leaves the
    default unzip name (ms-playwright-chromium-linux-x64-1.13.7/). Must
    not override an explicit user setting, and must skip cleanly when
    there's no bundled directory (uvx/dev mode)."""

    def _make_exe(self, tmp_path) -> str:
        exe = tmp_path / "servicenow-mcp"
        exe.write_text("")
        return str(exe)

    def _make_layout(
        self, tmp_path, *, dir_name: str = "ms-playwright", with_chromium: bool = True
    ) -> str:
        exe = self._make_exe(tmp_path)
        ms = tmp_path / dir_name
        ms.mkdir()
        if with_chromium:
            (ms / "chromium-1234").mkdir()
        return exe

    def test_sets_env_when_sibling_dir_has_chromium(self, tmp_path):
        exe = self._make_layout(tmp_path, with_chromium=True)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            with patch("servicenow_mcp.cli.sys.executable", exe):
                _maybe_use_bundled_chromium()
            assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(tmp_path / "ms-playwright")

    def test_matches_default_unzip_directory_name(self, tmp_path):
        # `unzip ms-playwright-chromium-linux-x64-1.13.7.zip` with default
        # GUI extractors creates a directory named after the zip. The
        # auto-detect must still find it without forcing users to rename.
        exe = self._make_layout(
            tmp_path,
            dir_name="ms-playwright-chromium-linux-x64-1.13.7",
            with_chromium=True,
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            with patch("servicenow_mcp.cli.sys.executable", exe):
                _maybe_use_bundled_chromium()
            assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == str(
                tmp_path / "ms-playwright-chromium-linux-x64-1.13.7"
            )

    def test_skips_when_user_already_set(self, tmp_path):
        exe = self._make_layout(tmp_path, with_chromium=True)
        with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": "/user/override"}, clear=False):
            with patch("servicenow_mcp.cli.sys.executable", exe):
                _maybe_use_bundled_chromium()
            assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/user/override"

    def test_skips_when_no_sibling_directory(self, tmp_path):
        exe = self._make_exe(tmp_path)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            with patch("servicenow_mcp.cli.sys.executable", exe):
                _maybe_use_bundled_chromium()
            assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ

    def test_skips_when_sibling_dir_empty(self, tmp_path):
        # Empty ms-play* shouldn't trick the probe — Playwright would
        # then fail to find chromium and the user gets a confusing error
        # instead of falling through to the standard cache.
        exe = self._make_layout(tmp_path, with_chromium=False)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
            with patch("servicenow_mcp.cli.sys.executable", exe):
                _maybe_use_bundled_chromium()
            assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


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


# ---------------------------------------------------------------------------
# configure_logging — import must have no side effect; force controls override
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def _restore(self, root, saved_handlers, saved_level):
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)

    def test_force_false_no_op_when_handlers_present(self):
        root = logging.getLogger()
        saved_handlers, saved_level = list(root.handlers), root.level
        try:
            sentinel = logging.NullHandler()
            for h in list(root.handlers):
                root.removeHandler(h)
            root.addHandler(sentinel)
            configure_logging(force=False)
            # Existing handler left untouched — no stomping on a host config.
            assert root.handlers == [sentinel]
        finally:
            self._restore(root, saved_handlers, saved_level)

    def test_force_true_resets_and_attaches_stream_handler(self):
        root = logging.getLogger()
        saved_handlers, saved_level = list(root.handlers), root.level
        try:
            for h in list(root.handlers):
                root.removeHandler(h)
            root.addHandler(logging.NullHandler())
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("LOG_FILE", None)
                configure_logging(force=True)
            assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
            assert not any(isinstance(h, logging.NullHandler) for h in root.handlers)
            assert root.level == logging.INFO
        finally:
            self._restore(root, saved_handlers, saved_level)

    def test_log_file_adds_rotating_handler(self, tmp_path):
        root = logging.getLogger()
        saved_handlers, saved_level = list(root.handlers), root.level
        try:
            log_path = tmp_path / "out.log"
            with patch.dict(os.environ, {"LOG_FILE": str(log_path)}, clear=False):
                configure_logging(force=True)
            assert any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers)
        finally:
            self._restore(root, saved_handlers, saved_level)

    def test_log_file_directory_gets_per_pid_filename(self, tmp_path):
        # Multiple processes rotating ONE shared file race each other (shards +
        # lost history). Directory-style LOG_FILE must yield a per-PID file.
        root = logging.getLogger()
        saved_handlers, saved_level = list(root.handlers), root.level
        try:
            with patch.dict(
                os.environ,
                {"LOG_FILE": str(tmp_path) + os.sep, "SERVICENOW_INSTANCE_URL": ""},
                clear=False,
            ):
                configure_logging(force=True)
            rotating = [
                h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
            ]
            assert rotating, "directory LOG_FILE must still attach a rotating handler"
            assert rotating[0].baseFilename.endswith(f"servicenow-mcp_default.{os.getpid()}.log")
        finally:
            self._restore(root, saved_handlers, saved_level)

    def test_stale_process_logs_swept_fresh_kept(self, tmp_path):
        import time

        from servicenow_mcp.cli import _LOG_RETENTION_DAYS, _sweep_stale_process_logs

        stale = tmp_path / "servicenow-mcp_default.99999.log"
        stale_rotated = tmp_path / "servicenow-mcp_default.99999.log.2"
        fresh = tmp_path / "servicenow-mcp_default.11111.log"
        other_slug = tmp_path / "servicenow-mcp_otherhost.99999.log"
        for f in (stale, stale_rotated, fresh, other_slug):
            f.write_text("x")
        old = time.time() - (_LOG_RETENTION_DAYS + 1) * 86400
        for f in (stale, stale_rotated, other_slug):
            os.utime(f, (old, old))

        _sweep_stale_process_logs(str(tmp_path), "default")

        assert not stale.exists() and not stale_rotated.exists()
        assert fresh.exists(), "files inside the retention window must survive"
        assert other_slug.exists(), "sweep must stay scoped to its own instance slug"


class TestServerName:
    """`--server-name` / SERVICENOW_MCP_SERVER_NAME (issue #77).

    Multiple connections (dev/stg/prd) that all advertise "ServiceNow" get
    namespaced by client load order, which is unstable across reloads — an
    agent cannot tell which connection is production. These pin the resolution
    order and the backward-compatible default.
    """

    def _args(self, **over):
        args = MagicMock()
        args.instance_url = "https://test.service-now.com"
        args.auth_type = "basic"
        args.username = "admin"
        args.password = "password"
        args.debug = False
        args.timeout = 30
        args.server_name = "ServiceNow"
        for k, v in over.items():
            setattr(args, k, v)
        return args

    def test_defaults_to_servicenow(self):
        """Existing single-connection installs must keep their namespace."""
        assert create_config(self._args()).server_name == "ServiceNow"

    def test_explicit_name_is_used(self):
        assert create_config(self._args(server_name="snow-prd")).server_name == "snow-prd"

    @patch.dict(os.environ, {"SERVICENOW_MCP_SERVER_NAME": "snow-stg"}, clear=False)
    def test_env_var_supplies_default(self):
        with patch("sys.argv", ["servicenow-mcp", "--instance-url", "https://x.service-now.com"]):
            assert parse_args().server_name == "snow-stg"

    @patch.dict(os.environ, {"SERVICENOW_MCP_SERVER_NAME": "from-env"}, clear=False)
    def test_flag_beats_env_var(self):
        argv = [
            "servicenow-mcp",
            "--instance-url",
            "https://x.service-now.com",
            "--server-name",
            "from-flag",
        ]
        with patch("sys.argv", argv):
            assert parse_args().server_name == "from-flag"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_name_falls_back(self, blank):
        """A blank name would advertise nothing — worse than the default."""
        assert create_config(self._args(server_name=blank)).server_name == "ServiceNow"

    def test_server_advertises_configured_name(self):
        """The wiring that actually matters: config -> FastMCP + self.name."""
        from servicenow_mcp.server import ServiceNowMCP

        srv = ServiceNowMCP(
            {
                "instance_url": "https://example.service-now.com",
                "auth": {
                    "type": "basic",
                    "basic": {"username": "admin", "password": "password"},
                },
                "server_name": "snow-prd",
            }
        )

        assert srv.name == "snow-prd"
        assert srv.mcp_server.name == "snow-prd"
