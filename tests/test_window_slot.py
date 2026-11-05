"""One debug window per terminal: each MCP process leases its own window number.

Two terminals testing as two users need two cookie jars. Window 1 is the window
every earlier release opened (same key, same profile); window N>1 gets its own.
"""

import json
import os
import time
from types import SimpleNamespace

import pytest

from servicenow_mcp.browser import badge, reaper, window, window_slot
from servicenow_mcp.browser.reaper import IDLE_AFTER_S, reap_idle_windows

BASE = "alice_at_ex_com"
OTHER_PID = 424242  # stands in for another terminal's MCP process


class FakeAuthManager:
    def __init__(self, cache_dir, instance_url="https://dev.example.com", username="alice@ex.com"):
        self._cache_dir = cache_dir
        self.instance_url = instance_url
        self.config = SimpleNamespace(browser=SimpleNamespace(username=username), basic=None)

    def _get_cache_dir(self):
        return self._cache_dir

    def _get_instance_user_suffix(self):
        return "unused"


@pytest.fixture
def auth(tmp_path):
    return FakeAuthManager(str(tmp_path))


@pytest.fixture
def procs(monkeypatch):
    """Which pids are running, and when each started. Ours is always running."""
    table = {os.getpid(): 1000.0}
    monkeypatch.setattr(window_slot, "_is_pid_alive", lambda pid: pid in table)
    monkeypatch.setattr(window_slot, "_started_at", lambda pid: table.get(pid))
    monkeypatch.setattr(window_slot, "_my_start", None)
    return table


def _lease(tmp_path, number, pid, started_at=2000.0, raw=None):
    path = tmp_path / f"debug_slot_{BASE}{window_slot.window_suffix(number)}.lease"
    path.write_text(raw if raw is not None else json.dumps({"pid": pid, "started_at": started_at}))
    return path


def _holder(tmp_path, number):
    path = tmp_path / f"debug_slot_{BASE}{window_slot.window_suffix(number)}.lease"
    return json.loads(path.read_text())["pid"]


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------


def test_the_first_terminal_gets_window_1_and_keeps_the_old_key(auth, tmp_path, procs):
    assert window.claim_window_slot(auth) == 1
    assert _holder(tmp_path, 1) == os.getpid()
    assert window.window_state_path(auth).endswith(f"debug_window_{BASE}.json")
    assert window.window_profile_dir(auth).endswith(f"debug_profile_{BASE}")


def test_a_second_terminal_gets_its_own_window_profile_and_session(auth, tmp_path, procs):
    procs[OTHER_PID] = 2000.0
    _lease(tmp_path, 1, OTHER_PID)

    assert window.claim_window_slot(auth) == 2
    assert window.window_profile_dir(auth).endswith(f"debug_profile_{BASE}__w2")
    assert window.window_state_path(auth).endswith(f"debug_window_{BASE}__w2.json")
    # Impersonation and the login budget are per window: a second user lives here.
    assert f"{BASE}__w2." in os.path.basename(window.window_impersonation_path(auth))
    assert f"{BASE}__w2." in os.path.basename(window.window_login_path(auth))


def test_a_dead_terminals_window_is_taken_over(auth, tmp_path, procs):
    _lease(tmp_path, 1, OTHER_PID)  # not in procs: exited

    assert window.claim_window_slot(auth) == 1
    assert _holder(tmp_path, 1) == os.getpid()


def test_a_reused_pid_does_not_hold_a_window(auth, tmp_path, procs):
    procs[OTHER_PID] = 9999.0  # running, but started after the lease was written
    _lease(tmp_path, 1, OTHER_PID, started_at=2000.0)

    assert window.claim_window_slot(auth) == 1


def test_an_unreadable_lease_is_not_a_free_window(auth, tmp_path, procs):
    _lease(tmp_path, 1, 0, raw="{not json")

    assert window.claim_window_slot(auth) == 2


def test_the_lease_is_kept_for_the_process_lifetime(auth, tmp_path, procs):
    procs[OTHER_PID] = 2000.0
    _lease(tmp_path, 1, OTHER_PID)
    assert window.claim_window_slot(auth) == 2
    # Window 1 frees up later; this terminal stays on its own window.
    (tmp_path / f"debug_slot_{BASE}.lease").unlink()
    assert window.claim_window_slot(auth) == 2


def test_a_lost_lease_is_claimed_again(auth, tmp_path, procs):
    assert window.claim_window_slot(auth) == 1
    (tmp_path / f"debug_slot_{BASE}.lease").unlink()

    assert window.claim_window_slot(auth) == 1
    assert _holder(tmp_path, 1) == os.getpid()


def test_with_every_window_held_it_shares_window_1_and_says_so(auth, tmp_path, procs):
    for number in range(1, window_slot.MAX_WINDOWS + 1):
        procs[OTHER_PID + number] = 2000.0
        _lease(tmp_path, number, OTHER_PID + number)

    assert window.claim_window_slot(auth) == 1
    assert window.window_shared_fallback(auth) is True
    assert window.window_state_path(auth).endswith(f"debug_window_{BASE}.json")


def test_a_claim_that_cannot_run_falls_back_to_window_1(auth, procs, monkeypatch):
    def broken(*a, **k):
        raise OSError("read-only")

    monkeypatch.setattr(window_slot, "_scan", broken)
    assert window.claim_window_slot(auth) == 1
    assert window.window_shared_fallback(auth) is True


def test_release_drops_only_our_own_lease(auth, tmp_path, procs):
    window.claim_window_slot(auth)
    window_slot.release(str(tmp_path), BASE)
    assert not (tmp_path / f"debug_slot_{BASE}.lease").exists()
    _lease(tmp_path, 1, OTHER_PID)
    window_slot.release(str(tmp_path), BASE)
    assert _holder(tmp_path, 1) == OTHER_PID


def test_number_of_reads_keys_and_profile_paths():
    assert window_slot.number_of(BASE) == 1
    assert window_slot.number_of(f"{BASE}__w3") == 3
    assert window_slot.number_of(f"/x/debug_profile_{BASE}__w2") == 2


# ---------------------------------------------------------------------------
# Legacy profile, reaper, badge
# ---------------------------------------------------------------------------


def test_only_window_1_adopts_a_pre_merge_profile(auth, tmp_path, procs):
    legacy = tmp_path / f"debug_profile_dev_example_com_{BASE}"
    legacy.mkdir()
    (legacy / "Cookies").write_text("x")
    procs[OTHER_PID] = 2000.0
    _lease(tmp_path, 1, OTHER_PID)
    window.claim_window_slot(auth)

    assert window.adopt_legacy_profile(auth) == ""
    assert legacy.exists()


def test_the_reaper_keeps_a_window_another_running_terminal_holds(auth, tmp_path, monkeypatch):
    now = time.time()
    other = window.KeyedWindow(str(tmp_path), f"{BASE}__w2")
    window.write_window_state(
        other,
        window.WindowState(
            pid=77,
            port=9333,
            profile_dir=str(tmp_path / f"debug_profile_{BASE}__w2"),
            instance_url="https://dev.example.com",
            started_at=1.0,
            last_used_at=now - IDLE_AFTER_S - 600,
        ),
    )
    liveness = window.Liveness(process=True, port=True, pages=1)
    monkeypatch.setattr(reaper, "window_liveness", lambda state: liveness)
    monkeypatch.setattr(reaper, "read_presence", lambda s: {"idle_ms": 1e9, "dirty": 0})
    killed = []
    monkeypatch.setattr(reaper, "terminate_pid", lambda pid: killed.append(pid) or True)
    lease = tmp_path / f"debug_slot_{BASE}__w2.lease"
    lease.write_text(json.dumps({"pid": OTHER_PID, "started_at": None}))

    monkeypatch.setattr(window_slot, "_is_pid_alive", lambda pid: pid == OTHER_PID)
    assert reap_idle_windows(auth, now=now) == [] and killed == []

    # The same window, its terminal gone: idle, so it is collected as before.
    monkeypatch.setattr(window_slot, "_is_pid_alive", lambda pid: False)
    assert len(reap_idle_windows(auth, now=now)) == 1 and killed == [77]


def test_the_badge_numbers_windows_from_2_up():
    assert "'MCP DEBUG'" in badge.badge_init_script("dev").replace('"', "'")
    script = badge.badge_init_script("dev", window_number=2).replace('"', "'")
    assert "'MCP DEBUG 2'" in script


def test_tool_output_names_the_window(auth, tmp_path, procs):
    from servicenow_mcp.tools.browser_debug_tools import _window_identity

    procs[OTHER_PID] = 2000.0
    _lease(tmp_path, 1, OTHER_PID)
    window.claim_window_slot(auth)
    state = SimpleNamespace(
        instance_host="dev.example.com", profile_dir=window.window_profile_dir(auth)
    )
    out = _window_identity(state, SimpleNamespace(instance_url=""), auth)
    assert out["window"] == 2 and "window_shared" not in out


# ---------------------------------------------------------------------------
# A terminal's window lives as long as the terminal
# ---------------------------------------------------------------------------


def _open_window(auth, tmp_path, pid=5151):
    profile = tmp_path / "profile"
    window.write_window_state(
        auth,
        window.WindowState(
            pid=pid,
            port=9333,
            profile_dir=str(profile),
            instance_url="https://dev.example.com",
            started_at=1.0,
            last_used_at=time.time(),
        ),
    )
    return str(profile)


@pytest.fixture
def killed(monkeypatch):
    seen = []
    monkeypatch.setattr(window, "terminate_pid", lambda pid: seen.append(pid) or True)
    return seen


def test_exit_closes_the_terminals_window_and_releases_it(
    auth, tmp_path, procs, monkeypatch, killed
):
    procs[OTHER_PID] = 2000.0
    _lease(tmp_path, 1, OTHER_PID)
    window.claim_window_slot(auth)  # window 2
    profile = _open_window(auth, tmp_path)
    monkeypatch.setattr(window, "_is_pid_alive", lambda pid: pid == 5151)
    monkeypatch.setattr(window, "_singleton_holder_pid", lambda d: 5151 if d == profile else None)
    marker = tmp_path / f"debug_window_{BASE}__w2.dev_example_com.impersonation.json"
    marker.write_text("{}")

    assert window.close_windows_of_this_process() == [f"{BASE}__w2"]
    assert killed == [5151]
    assert not (tmp_path / f"debug_window_{BASE}__w2.json").exists()
    assert not marker.exists()
    assert not (tmp_path / f"debug_slot_{BASE}__w2.lease").exists()
    # The other terminal's window 1 is not ours and is left alone.
    assert (tmp_path / f"debug_slot_{BASE}.lease").exists()


def test_exit_never_signals_a_pid_that_is_not_the_window(
    auth, tmp_path, procs, monkeypatch, killed
):
    window.claim_window_slot(auth)
    _open_window(auth, tmp_path)
    monkeypatch.setattr(window, "_is_pid_alive", lambda pid: True)  # pid reused by something
    monkeypatch.setattr(window, "_singleton_holder_pid", lambda d: None)

    assert window.close_windows_of_this_process() == []
    assert killed == []
    # Not proven gone, so its state stays for whoever reuses it.
    assert (tmp_path / f"debug_window_{BASE}.json").exists()


def test_a_shared_fallback_window_is_never_closed_at_exit(
    auth, tmp_path, procs, monkeypatch, killed
):
    for number in range(1, window_slot.MAX_WINDOWS + 1):
        procs[OTHER_PID + number] = 2000.0
        _lease(tmp_path, number, OTHER_PID + number)
    window.claim_window_slot(auth)
    _open_window(auth, tmp_path)
    monkeypatch.setattr(window, "_is_pid_alive", lambda pid: True)
    monkeypatch.setattr(window, "_singleton_holder_pid", lambda d: 5151)

    assert window.close_windows_of_this_process() == [] and killed == []


def test_a_window_taken_over_after_we_were_presumed_dead_is_left_alone(
    auth, tmp_path, procs, monkeypatch, killed
):
    window.claim_window_slot(auth)
    _open_window(auth, tmp_path)
    _lease(tmp_path, 1, OTHER_PID)  # someone else holds it now
    monkeypatch.setattr(window, "_is_pid_alive", lambda pid: True)
    monkeypatch.setattr(window, "_singleton_holder_pid", lambda d: 5151)

    assert window.close_windows_of_this_process() == [] and killed == []
    assert _holder(tmp_path, 1) == OTHER_PID


def test_no_lease_is_written_without_a_real_cache_dir(tmp_path, procs, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert window_slot.claim("<MagicMock name='x'>", BASE) == 1
    assert list(tmp_path.iterdir()) == []
