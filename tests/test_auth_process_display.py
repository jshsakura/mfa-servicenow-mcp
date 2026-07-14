"""Invariants for the two stateless auth predicates extracted in v1.19.10.

Both pin bugs that four rounds of external review missed:

1. `os.kill(pid, 0)` TERMINATES the target on Windows (CPython os.kill: any
   signal other than CTRL_C_EVENT/CTRL_BREAK_EVENT goes to TerminateProcess).
   The startup lock sweep ran that check against every peer's lock file, so a
   second MCP host booting on Windows killed the first host's in-flight login.
   `_is_pid_alive` must NEVER signal the target.

2. The visible-login fallback launched Chromium with headless=False even on a
   display-less Linux host, where no human can complete the MFA it exists for.
"""

import inspect
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

import servicenow_mcp.auth._browser_dom as browser_dom_module
import servicenow_mcp.auth._process as process_module
import servicenow_mcp.auth.auth_manager as auth_manager_module
from servicenow_mcp.auth._display import (
    VISIBLE_BROWSER_UNAVAILABLE,
    _visible_browser_unavailable_reason,
)
from servicenow_mcp.auth._process import _is_pid_alive
from servicenow_mcp.auth.auth_manager import AuthManager


class TestIsPidAlive:
    def test_current_process_is_alive(self):
        assert _is_pid_alive(os.getpid()) is True

    def test_unused_pid_is_dead(self):
        # PID_MAX_LIMIT on Linux is 2^22; this is unreachable on any platform.
        assert _is_pid_alive(2**30) is False

    @pytest.mark.parametrize("pid", [0, -1, None, "1234", 3.5])
    def test_invalid_pid_is_dead(self, pid):
        assert _is_pid_alive(pid) is False

    def test_pid_owned_by_another_user_counts_as_alive(self):
        """Stealing a live peer's lock is worse than waiting out a dead one."""
        with patch("servicenow_mcp.auth._process.os.kill", side_effect=PermissionError):
            assert _is_pid_alive(4242) is True

    def test_windows_never_calls_os_kill(self):
        """THE bug: os.kill(pid, 0) is TerminateProcess on Windows.

        If this test ever fails, a Windows user's sibling MCP process is being
        killed by a liveness check.
        """
        kernel32 = MagicMock()
        kernel32.OpenProcess.return_value = 0x1234

        # GetExitCodeProcess(handle, byref(code)) -> writes STILL_ACTIVE, returns 1
        def _get_exit_code(_handle, code_ref):
            code_ref._obj.value = 259  # STILL_ACTIVE
            return 1

        kernel32.GetExitCodeProcess.side_effect = _get_exit_code

        with (
            patch.object(sys, "platform", "win32"),
            patch("servicenow_mcp.auth._process._get_kernel32", return_value=kernel32),
            patch("servicenow_mcp.auth._process.os.kill") as os_kill,
        ):
            assert _is_pid_alive(4242) is True

        os_kill.assert_not_called()
        kernel32.CloseHandle.assert_called_once_with(0x1234)

    def test_windows_exited_process_is_dead(self):
        kernel32 = MagicMock()
        kernel32.OpenProcess.return_value = 0x1234

        def _get_exit_code(_handle, code_ref):
            code_ref._obj.value = 0  # exited cleanly
            return 1

        kernel32.GetExitCodeProcess.side_effect = _get_exit_code

        with (
            patch.object(sys, "platform", "win32"),
            patch("servicenow_mcp.auth._process._get_kernel32", return_value=kernel32),
        ):
            assert _is_pid_alive(4242) is False

    def test_windows_open_process_denied_counts_as_alive(self):
        kernel32 = MagicMock()
        kernel32.OpenProcess.return_value = None  # NULL handle

        with (
            patch.object(sys, "platform", "win32"),
            patch("servicenow_mcp.auth._process._get_kernel32", return_value=kernel32),
            patch("servicenow_mcp.auth._process._last_error", return_value=5),
        ):
            assert _is_pid_alive(4242) is True  # ERROR_ACCESS_DENIED → exists

    def test_windows_open_process_invalid_pid_is_dead(self):
        kernel32 = MagicMock()
        kernel32.OpenProcess.return_value = None

        with (
            patch.object(sys, "platform", "win32"),
            patch("servicenow_mcp.auth._process._get_kernel32", return_value=kernel32),
            patch("servicenow_mcp.auth._process._last_error", return_value=87),
        ):
            assert _is_pid_alive(4242) is False  # ERROR_INVALID_PARAMETER → gone


class TestNoRawOsKillInAuthLayer:
    """The permanent guard: `os.kill` must never reappear as a liveness probe.

    On Windows that call is TerminateProcess. Every liveness question in the
    auth layer has to route through `_is_pid_alive`, which branches per platform.
    """

    @pytest.mark.parametrize(
        "module",
        [auth_manager_module, browser_dom_module],
        ids=["auth_manager", "_browser_dom"],
    )
    def test_module_does_not_call_os_kill(self, module):
        source = inspect.getsource(module)
        assert "os.kill(" not in source, (
            f"{module.__name__} calls os.kill directly — on Windows that "
            "TERMINATES the target. Use _is_pid_alive from auth/_process.py."
        )

    def test_process_module_is_the_only_os_kill_caller(self):
        source = inspect.getsource(process_module)
        # The module docstring quotes the CPython warning verbatim — that's
        # documentation, not a call site. Only the code body may contain one.
        body = source.replace(inspect.getdoc(process_module) or "", "")
        assert body.count("os.kill(") == 1
        assert 'sys.platform == "win32"' in body  # and it's behind a platform gate


class TestLockSweepUsesPortableLiveness:
    """The sweep must classify locks through the cross-platform predicate."""

    def test_live_holder_lock_is_kept(self, tmp_path):
        lock = tmp_path / "session_x.lock"
        lock.write_text(json.dumps({"pid": os.getpid(), "timestamp": 0}))

        with patch("servicenow_mcp.auth.auth_manager._is_pid_alive", return_value=True) as alive:
            assert AuthManager._is_lock_file_stale(str(lock), 0.0) is False
        alive.assert_called_once_with(os.getpid())

    def test_dead_holder_lock_is_stale(self, tmp_path):
        lock = tmp_path / "session_x.lock"
        lock.write_text(json.dumps({"pid": 2**30, "timestamp": 0}))
        assert AuthManager._is_lock_file_stale(str(lock), 0.0) is True

    def test_corrupt_lock_is_stale(self, tmp_path):
        lock = tmp_path / "session_x.lock"
        lock.write_text("not json")
        assert AuthManager._is_lock_file_stale(str(lock), 0.0) is True


class TestLoginLockAgeBackstop:
    """PID reuse cannot deadlock the login lock: age is checked first."""

    def test_age_expiry_beats_a_live_looking_pid(self, tmp_path):
        manager = AuthManager.__new__(AuthManager)
        manager._login_lock_path = str(tmp_path / "session_x.lock")
        # A live pid (ours) but a lock older than the staleness ceiling: this is
        # what a reused pid looks like from the outside.
        stale_ts = 1.0
        with open(manager._login_lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": stale_ts}, f)

        now = stale_ts + AuthManager.LOGIN_LOCK_STALE_AFTER_SECONDS + 1
        with patch("servicenow_mcp.auth.auth_manager.time.time", return_value=now):
            assert manager._acquire_login_lock() is True  # collected, not deadlocked

    def test_fresh_lock_held_by_live_peer_is_respected(self, tmp_path):
        manager = AuthManager.__new__(AuthManager)
        manager._login_lock_path = str(tmp_path / "session_x.lock")
        with open(manager._login_lock_path, "w") as f:
            json.dump({"pid": os.getpid(), "timestamp": 1.0}, f)

        with patch("servicenow_mcp.auth.auth_manager.time.time", return_value=2.0):
            assert manager._acquire_login_lock() is False


class TestVisibleBrowserUnavailable:
    def test_linux_without_display_is_blocked(self):
        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {}, clear=True):
            assert _visible_browser_unavailable_reason() == VISIBLE_BROWSER_UNAVAILABLE

    def test_linux_with_x11_is_allowed(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True),
        ):
            assert _visible_browser_unavailable_reason() is None

    def test_linux_with_wayland_is_allowed(self):
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True),
        ):
            assert _visible_browser_unavailable_reason() is None

    @pytest.mark.parametrize("platform", ["darwin", "win32"])
    def test_desktop_platforms_always_allowed(self, platform):
        with patch.object(sys, "platform", platform), patch.dict(os.environ, {}, clear=True):
            assert _visible_browser_unavailable_reason() is None

    def test_reason_names_the_non_interactive_auth_types(self):
        """The error has to tell a headless-server user what to do instead."""
        for auth_type in ("basic", "oauth", "api_key"):
            assert auth_type in VISIBLE_BROWSER_UNAVAILABLE


class TestHeadlessHostDoesNotOpenDoomedVisibleWindow:
    """MFA fallback on a display-less host fails fast instead of hanging."""

    def _manager(self):
        manager = AuthManager.__new__(AuthManager)
        manager.config = MagicMock()
        manager._browser_setup_error = None  # startup probe was clean
        return manager

    def test_mfa_fallback_raises_actionable_error_without_relaunching(self):
        manager = self._manager()
        browser_config = MagicMock()
        calls = []

        def _sync_login(cfg, interactive):
            calls.append(interactive)
            raise ValueError("MFA_REQUIRED: totp needed")

        with (
            patch.object(AuthManager, "_login_with_browser_sync", side_effect=_sync_login),
            patch(
                "servicenow_mcp.auth.auth_manager._visible_browser_unavailable_reason",
                return_value=VISIBLE_BROWSER_UNAVAILABLE,
            ),
        ):
            with pytest.raises(ValueError, match="no display server"):
                manager._login_with_browser(browser_config, force_interactive=False)

        # Exactly one attempt — the headless one. No doomed visible relaunch.
        assert calls == [False]

    def test_fallback_still_runs_when_a_display_exists(self):
        manager = self._manager()
        browser_config = MagicMock()
        calls = []

        def _sync_login(cfg, interactive):
            calls.append(interactive)
            if not interactive:
                raise ValueError("MFA_REQUIRED: totp needed")

        with (
            patch.object(AuthManager, "_login_with_browser_sync", side_effect=_sync_login),
            patch(
                "servicenow_mcp.auth.auth_manager._visible_browser_unavailable_reason",
                return_value=None,
            ),
        ):
            manager._login_with_browser(browser_config, force_interactive=False)

        assert calls == [False, True]  # headless attempt, then visible fallback
