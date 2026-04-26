"""Extra tests for cli.py — covering missed lines 362, 387-394, 419-437, 452, 457-458."""

import asyncio
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.cli import _ensure_playwright_browser, arun_server, main


def _install_playwright_mock():
    """Ensure a mock playwright.sync_api module exists for patching."""
    if "playwright" not in sys.modules:
        pw = types.ModuleType("playwright")
        pw.sync_api = types.ModuleType("playwright.sync_api")
        pw.sync_api.sync_playwright = MagicMock()
        sys.modules["playwright"] = pw
        sys.modules["playwright.sync_api"] = pw.sync_api


# ---------------------------------------------------------------------------
# Line 362: unsupported auth type ValueError (already tested but ensure it)
# This is covered by test_unsupported_auth_type_raises in test_cli.py
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Lines 387-394: arun_server
# ---------------------------------------------------------------------------


class TestArunServer:
    @patch("mcp.server.stdio.stdio_server")
    def test_arun_server_calls_run(self, mock_stdio_server):
        mock_streams = (MagicMock(), MagicMock())

        class AsyncCM:
            async def __aenter__(self):
                return mock_streams

            async def __aexit__(self, *args):
                return False

        mock_stdio_server.return_value = AsyncCM()

        mock_server = MagicMock()
        mock_server.run = MagicMock(return_value=asyncio.sleep(0))
        mock_init_opts = MagicMock()
        mock_server.create_initialization_options.return_value = mock_init_opts

        asyncio.run(arun_server(mock_server))

        mock_server.create_initialization_options.assert_called_once()
        mock_server.run.assert_called_once()


# ---------------------------------------------------------------------------
# Lines 419-437: _ensure_playwright_browser with browser auth
# ---------------------------------------------------------------------------


class TestEnsurePlaywrightBrowserBrowserAuth:
    def test_browser_auth_chromium_found(self):
        _install_playwright_mock()
        args = MagicMock()
        args.auth_type = "browser"

        mock_pw = MagicMock()
        mock_pw.chromium.executable_path = "/usr/bin/chromium"

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch("playwright.sync_api.sync_playwright", return_value=mock_cm):
            _ensure_playwright_browser(args)

    def test_browser_auth_chromium_missing_installs(self):
        _install_playwright_mock()
        args = MagicMock()
        args.auth_type = "browser"

        mock_pw = MagicMock()
        type(mock_pw.chromium).executable_path = property(
            lambda self: (_ for _ in ()).throw(Exception("not found"))
        )

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch("playwright.sync_api.sync_playwright", return_value=mock_cm):
            with patch("subprocess.run") as mock_run:
                _ensure_playwright_browser(args)
                mock_run.assert_called_once()

    def test_browser_auth_chromium_install_fails_logs_warning(self):
        _install_playwright_mock()
        args = MagicMock()
        args.auth_type = "browser"

        mock_pw = MagicMock()
        type(mock_pw.chromium).executable_path = property(
            lambda self: (_ for _ in ()).throw(Exception("not found"))
        )

        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_pw)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with patch("playwright.sync_api.sync_playwright", return_value=mock_cm):
            with patch("subprocess.run", side_effect=Exception("install failed")):
                _ensure_playwright_browser(args)

    def test_browser_auth_playwright_import_fails(self):
        _install_playwright_mock()
        args = MagicMock()
        args.auth_type = "browser"

        with patch(
            "playwright.sync_api.sync_playwright",
            side_effect=ImportError("no playwright"),
        ):
            _ensure_playwright_browser(args)


# ---------------------------------------------------------------------------
# Lines 452, 457-458: main() uninstall alias + ValueError from setup_installer
# ---------------------------------------------------------------------------


class TestMainUninstallAndError:
    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.setup_installer.main", return_value=0)
    def test_main_dispatches_uninstall_as_remove(self, mock_setup_main, mock_dotenv):
        """'uninstall' subcommand should be aliased to 'remove' action."""
        with patch("sys.argv", ["cli", "uninstall", "opencode"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 0
        mock_setup_main.assert_called_once_with(["opencode"], action="remove")

    @patch("dotenv.load_dotenv")
    @patch("servicenow_mcp.setup_installer.main", side_effect=ValueError("bad config"))
    def test_main_setup_value_error_exits_1(self, mock_setup_main, mock_dotenv):
        """ValueError from setup_installer should result in SystemExit(1)."""
        with patch("sys.argv", ["cli", "setup", "opencode"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
        assert exc_info.value.code == 1
