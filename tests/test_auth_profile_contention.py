"""Shared-profile contention invariants (multisession login-storm, 2026-07-07).

The browser profile is deliberately SHARED across terminal tabs — one MFA
login, every tab adopts it from disk. These tests pin the two guards that make
that sharing safe when several MCP servers (local + uvx, possibly different
versions) run concurrently:

1. The headless session-restore probe must respect the cross-process login
   lock — a probe colliding with a sibling's visible login window kills that
   window in ~2s via Chromium's profile singleton, and the death is then
   misread as "user closed the window" (cooldown storm).
2. The persistent-context launcher must wait for the profile's Chromium
   SingletonLock to clear before launching, so even a sibling WITHOUT guard #1
   (an older version) can't make our window die at birth.
"""

import json
import os
import time
from unittest.mock import patch

from servicenow_mcp.auth import _browser_dom
from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig


def _make_browser_manager(tmp_path) -> AuthManager:
    cfg = AuthConfig(
        type=AuthType.BROWSER,
        browser=BrowserAuthConfig(headless=False, timeout_seconds=10),
    )
    with (
        patch.object(AuthManager, "_ensure_playwright_ready"),
        patch.object(AuthManager, "_load_session_from_disk"),
    ):
        manager = AuthManager(cfg, "https://example.service-now.com")
    manager._login_lock_path = str(tmp_path / "session.lock")
    return manager


def _hold_lock(manager: AuthManager) -> None:
    """Simulate a sibling process holding the cross-process login lock.

    Uses our own (alive) pid — _acquire_login_lock only checks liveness, not
    ownership, so this is exactly what a live sibling looks like.
    """
    with open(manager._login_lock_path, "w") as f:
        json.dump({"pid": os.getpid(), "timestamp": time.time()}, f)


class TestRestoreProbeRespectsLoginLock:
    def test_probe_skipped_when_lock_held_by_live_sibling(self, tmp_path):
        manager = _make_browser_manager(tmp_path)
        _hold_lock(manager)
        with patch.object(
            AuthManager, "_try_restore_browser_session_unlocked", return_value=True
        ) as unlocked:
            assert manager._try_restore_browser_session(manager.config.browser) is False
        unlocked.assert_not_called()
        # The sibling's lock must survive the skip untouched.
        assert os.path.exists(manager._login_lock_path)

    def test_probe_runs_and_releases_lock_when_free(self, tmp_path):
        manager = _make_browser_manager(tmp_path)
        with patch.object(
            AuthManager, "_try_restore_browser_session_unlocked", return_value=True
        ) as unlocked:
            assert manager._try_restore_browser_session(manager.config.browser) is True
        unlocked.assert_called_once()
        assert not os.path.exists(manager._login_lock_path)

    def test_probe_releases_lock_even_when_probe_raises(self, tmp_path):
        manager = _make_browser_manager(tmp_path)
        with patch.object(
            AuthManager,
            "_try_restore_browser_session_unlocked",
            side_effect=RuntimeError("playwright exploded"),
        ):
            try:
                manager._try_restore_browser_session(manager.config.browser)
            except RuntimeError:
                pass
        assert not os.path.exists(manager._login_lock_path)

    def test_stale_dead_pid_lock_does_not_block_probe(self, tmp_path):
        manager = _make_browser_manager(tmp_path)
        # A pid from a crashed sibling: max pid + unlikely-to-exist value.
        with open(manager._login_lock_path, "w") as f:
            json.dump({"pid": 2**22 + 12345, "timestamp": time.time()}, f)
        with patch.object(
            AuthManager, "_try_restore_browser_session_unlocked", return_value=False
        ) as unlocked:
            manager._try_restore_browser_session(manager.config.browser)
        unlocked.assert_called_once()


class TestSingletonHolderDetection:
    def test_no_lock_means_free(self, tmp_path):
        assert _browser_dom._singleton_holder_pid(str(tmp_path)) is None

    def test_dead_pid_is_stale_and_free(self, tmp_path):
        os.symlink(f"somehost.local-{2**22 + 12345}", tmp_path / "SingletonLock")
        assert _browser_dom._singleton_holder_pid(str(tmp_path)) is None

    def test_live_pid_is_busy(self, tmp_path):
        os.symlink(f"somehost.local-{os.getpid()}", tmp_path / "SingletonLock")
        assert _browser_dom._singleton_holder_pid(str(tmp_path)) == os.getpid()

    def test_unparseable_target_is_free(self, tmp_path):
        os.symlink("garbage-no-pid-here", tmp_path / "SingletonLock")
        assert _browser_dom._singleton_holder_pid(str(tmp_path)) is None


class TestLaunchWaitsForSingleton:
    def test_wait_returns_immediately_when_free(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(_browser_dom.time, "sleep", lambda s: calls.append(s))
        _browser_dom._wait_for_profile_singleton(str(tmp_path))
        assert calls == []

    def test_wait_ends_when_sibling_releases(self, tmp_path, monkeypatch):
        lock = tmp_path / "SingletonLock"
        os.symlink(f"somehost.local-{os.getpid()}", lock)
        monkeypatch.setattr(_browser_dom, "_SINGLETON_WAIT_S", 5.0)
        monkeypatch.setattr(_browser_dom, "_SINGLETON_POLL_S", 0.0)
        polls = {"n": 0}

        def _sleep(_s):
            polls["n"] += 1
            if polls["n"] == 3:
                os.unlink(lock)  # sibling finished its probe

        monkeypatch.setattr(_browser_dom.time, "sleep", _sleep)
        _browser_dom._wait_for_profile_singleton(str(tmp_path))
        assert polls["n"] == 3

    def test_wait_gives_up_after_budget_and_proceeds(self, tmp_path, monkeypatch):
        os.symlink(f"somehost.local-{os.getpid()}", tmp_path / "SingletonLock")
        monkeypatch.setattr(_browser_dom, "_SINGLETON_WAIT_S", 0.05)
        monkeypatch.setattr(_browser_dom, "_SINGLETON_POLL_S", 0.01)
        start = time.time()
        _browser_dom._wait_for_profile_singleton(str(tmp_path))  # must not hang
        assert time.time() - start < 2.0
