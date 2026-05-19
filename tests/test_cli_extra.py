"""Extra tests for cli.py — covering missed lines 362, 387-394, 419-437, 452, 457-458."""

import asyncio
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.cli import _start_parent_watchdog, _warn_if_chromium_missing, arun_server, main


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
# _warn_if_chromium_missing — must warn but never install (handshake-safe)
# ---------------------------------------------------------------------------


class TestWarnIfChromiumMissing:
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
            _warn_if_chromium_missing(args)

    def test_browser_auth_chromium_missing_does_not_install(self):
        """Critical: missing Chromium must NOT trigger a subprocess install.

        Prior auto-install caused MCP handshake timeouts (Codex
        "connection closed: initialize response") when Playwright shipped
        a new Chromium build. New contract: warn only, never block startup.
        """
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
                with patch("subprocess.check_call") as mock_check_call:
                    _warn_if_chromium_missing(args)
        mock_run.assert_not_called()
        mock_check_call.assert_not_called()

    def test_browser_auth_playwright_import_fails(self):
        """Missing playwright package must not crash startup either — warn only."""
        _install_playwright_mock()
        args = MagicMock()
        args.auth_type = "browser"

        with patch(
            "playwright.sync_api.sync_playwright",
            side_effect=ImportError("no playwright"),
        ):
            # Should not raise.
            _warn_if_chromium_missing(args)


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


class TestParentWatchdog:
    """Defends against ghost MCP servers when the host (Claude Code, Codex)
    dies abruptly without dropping our stdio pipes."""

    def test_skips_when_already_orphaned(self):
        """ppid <= 1 means we're already detached — nothing to watch."""
        with patch("servicenow_mcp.cli.os.getppid", return_value=1):
            with patch("servicenow_mcp.cli.threading.Thread") as mock_thread:
                _start_parent_watchdog()
        mock_thread.assert_not_called()

    def test_starts_daemon_thread_when_parented(self):
        with patch("servicenow_mcp.cli.os.getppid", return_value=12345):
            with patch("servicenow_mcp.cli.threading.Thread") as mock_thread:
                _start_parent_watchdog()
        mock_thread.assert_called_once()
        kwargs = mock_thread.call_args.kwargs
        assert kwargs.get("daemon") is True
        assert kwargs.get("name") == "parent-watchdog"
        mock_thread.return_value.start.assert_called_once()
