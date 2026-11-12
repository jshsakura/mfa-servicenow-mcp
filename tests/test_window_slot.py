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
    monkeypatch.setattr(reaper, "window_signed_in", lambda endpoint, hosts, **_: False)
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


@pytest.fixture
def signed_in(monkeypatch):
    """What the window's session reads as at exit. Default: nothing to keep."""
    from servicenow_mcp.browser import session

    answer = {"value": False}
    monkeypatch.setattr(session, "window_signed_in", lambda endpoint, hosts: answer["value"])
    return answer


def test_exit_closes_an_empty_window_and_releases_it(
    auth, tmp_path, procs, monkeypatch, killed, signed_in
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
    auth, tmp_path, procs, monkeypatch, killed, signed_in
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
    auth, tmp_path, procs, monkeypatch, killed, signed_in
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
    auth, tmp_path, procs, monkeypatch, killed, signed_in
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


@pytest.mark.parametrize("reading", [True, None], ids=["signed-in", "could-not-tell"])
def test_a_window_with_a_session_to_keep_stays_open_for_the_next_terminal(
    auth, tmp_path, procs, monkeypatch, killed, signed_in, reading
):
    # A live session may have cost an MFA challenge; closing the browser ends it.
    signed_in["value"] = reading
    window.claim_window_slot(auth)
    profile = _open_window(auth, tmp_path)
    monkeypatch.setattr(window, "_is_pid_alive", lambda pid: pid == 5151)
    monkeypatch.setattr(window, "_singleton_holder_pid", lambda d: 5151 if d == profile else None)

    assert window.close_windows_of_this_process() == []
    assert killed == []
    assert (tmp_path / f"debug_window_{BASE}.json").exists()  # reusable as is
    assert not (tmp_path / f"debug_slot_{BASE}.lease").exists()  # number handed on


# ---------------------------------------------------------------------------
# Is there a session worth keeping?
# ---------------------------------------------------------------------------


class _Page:
    def __init__(self, url, user=None):
        self.url = url
        self.user = user


class _Context:
    def __init__(self, pages, cookies=()):
        self.pages = list(pages)
        self._cookies = list(cookies)

    def cookies(self):
        return self._cookies


def _read_window(monkeypatch, pages, cookies=()):
    from contextlib import contextmanager

    from servicenow_mcp.browser import _offload, session

    @contextmanager
    def fake_browser(endpoint):
        yield SimpleNamespace(contexts=[_Context(pages, cookies)])

    monkeypatch.setattr(_offload, "cdp_browser", fake_browser)
    monkeypatch.setattr(_offload, "require_playwright", lambda: None)
    monkeypatch.setattr(_offload, "run_off_loop", lambda fn, timeout_s: fn())
    monkeypatch.setattr(
        session,
        "read_effective_user",
        lambda page: {"user": page.user} if page.user else None,
    )
    return session.window_signed_in("http://127.0.0.1:1", {"dev.example.com"})


DEV = "https://dev.example.com"


@pytest.mark.parametrize(
    "pages,cookies,expected",
    [
        ([_Page(f"{DEV}/sp", "admin")], (), True),
        ([_Page(f"{DEV}/sp", "guest"), _Page(f"{DEV}/now/nav", "bob")], (), True),
        ([_Page(f"{DEV}/sp", "guest")], (), False),
        ([_Page(f"{DEV}/login.do")], (), False),
        ([_Page("chrome://new-tab-page/")], (), False),
        ([_Page("chrome://new-tab-page/")], [{"domain": ".dev.example.com", "expires": -1}], None),
        (
            [_Page("chrome://new-tab-page/")],
            [{"domain": ".dev.example.com", "expires": 1893456000}],
            False,
        ),
        ([_Page(f"{DEV}/incident.do")], (), None),  # did not answer: not proof of empty
        ([_Page("https://x.service-now.com/sp", "admin")], (), True),
    ],
    ids=[
        "user",
        "any-tab-signed-in",
        "guest",
        "login-page",
        "blank-no-cookies",
        "session-cookie-but-no-tab",
        "only-persistent-cookies",
        "tab-did-not-answer",
        "unconfigured-instance-host",
    ],
)
def test_window_signed_in(monkeypatch, pages, cookies, expected):
    assert _read_window(monkeypatch, pages, cookies) is expected


def test_an_unreadable_window_is_could_not_tell(monkeypatch):
    from servicenow_mcp.browser import _offload, session

    def broken(fn, timeout_s):
        raise TimeoutError("cdp")

    monkeypatch.setattr(_offload, "require_playwright", lambda: None)
    monkeypatch.setattr(_offload, "run_off_loop", broken)
    assert session.window_signed_in("http://127.0.0.1:1", ()) is None


# ---------------------------------------------------------------------------
# After an MCP restart: continue in the window that holds the work, never guess
# ---------------------------------------------------------------------------


def _prior_window(tmp_path, number, pid, tabs, last_used_at=0.0):
    """A previous terminal's window: state file on disk, process and port live."""
    key = BASE + window_slot.window_suffix(number)
    state = {
        "pid": pid,
        "port": 9000 + number,
        "profile_dir": str(tmp_path / f"debug_profile_{key}"),
        "instance_url": "https://dev.example.com",
        "started_at": 1.0,
        "last_used_at": last_used_at,
    }
    (tmp_path / f"debug_window_{key}.json").write_text(json.dumps(state))
    return 9000 + number, tabs


@pytest.fixture
def live_windows(monkeypatch):
    """port -> tabs for every window whose browser answers."""
    ports = {}
    monkeypatch.setattr(window, "_is_pid_alive", lambda pid: True)
    monkeypatch.setattr(window, "_cdp_responds", lambda port, timeout_s=0: port in ports)
    monkeypatch.setattr(window, "_cdp_tabs", lambda port, timeout_s=0: ports.get(port))
    return ports


_STUDIO = [{"title": "Workflow Studio", "url": "dev.example.com/now/workflow-studio"}]
_HOME = [{"title": "Dashboard", "url": "dev.example.com/now/nav/ui/home"}]


def test_two_open_windows_after_a_restart_are_listed_not_guessed(
    auth, tmp_path, procs, live_windows
):
    live_windows.update(
        [_prior_window(tmp_path, 2, 501, _HOME), _prior_window(tmp_path, 3, 502, _STUDIO)]
    )

    out = window.choose_window_slot(auth, None)

    assert out["error"] == "CHOOSE_WINDOW"
    assert [(w["window"], w["tabs"][0]["title"]) for w in out["windows"]] == [
        (2, "Dashboard"),
        (3, "Workflow Studio"),
    ]
    assert not (tmp_path / f"debug_slot_{BASE}__w2.lease").exists()  # nothing taken


def test_picking_a_window_leases_exactly_that_one_and_sticks(auth, tmp_path, procs, live_windows):
    live_windows.update(
        [_prior_window(tmp_path, 2, 501, _HOME), _prior_window(tmp_path, 3, 502, _STUDIO)]
    )

    assert window.choose_window_slot(auth, 3) is None
    assert _holder(tmp_path, 3) == os.getpid()
    assert window.choose_window_slot(auth, None) is None  # chosen: no second question
    assert window.claim_window_slot(auth) == 3
    assert window.window_state_path(auth).endswith(f"debug_window_{BASE}__w3.json")


def test_a_single_open_window_is_continued_even_when_a_lower_number_is_free(
    auth, tmp_path, procs, live_windows
):
    # The lowest-free scan would open a NEW window 1 next to the work in window 3.
    live_windows.update([_prior_window(tmp_path, 3, 502, _STUDIO)])

    assert window.choose_window_slot(auth, None) is None
    assert window.claim_window_slot(auth) == 3


def test_a_window_another_terminal_holds_is_refused_and_not_listed(
    auth, tmp_path, procs, live_windows
):
    procs[OTHER_PID] = 2000.0
    _lease(tmp_path, 3, OTHER_PID)
    live_windows.update(
        [_prior_window(tmp_path, 2, 501, _HOME), _prior_window(tmp_path, 3, 502, _STUDIO)]
    )

    out = window.choose_window_slot(auth, 3)

    assert out["error"] == "WINDOW_NOT_AVAILABLE" and "another running terminal" in out["message"]
    assert [w["window"] for w in out["windows"]] == [2]
    assert _holder(tmp_path, 3) == OTHER_PID


def test_switching_windows_releases_the_old_lease(auth, tmp_path, procs, live_windows):
    assert window.choose_window_slot(auth, 2) is None
    assert window.choose_window_slot(auth, 4) is None

    assert not (tmp_path / f"debug_slot_{BASE}__w2.lease").exists()
    assert _holder(tmp_path, 4) == os.getpid()


def test_no_such_window_number(auth, procs, live_windows):
    assert window.choose_window_slot(auth, 9)["error"] == "WINDOW_NOT_AVAILABLE"


def test_a_window_with_no_tabs_is_not_offered(auth, tmp_path, procs, live_windows):
    live_windows.update(
        [_prior_window(tmp_path, 2, 501, []), _prior_window(tmp_path, 3, 502, _STUDIO)]
    )

    assert window.choose_window_slot(auth, None) is None
    assert window.claim_window_slot(auth) == 3


def test_tabs_are_read_from_the_window_without_devtools_or_query_strings(monkeypatch):
    import io

    body = json.dumps(
        [
            {"type": "page", "title": "Flow", "url": "https://dev.example.com/now/wf?sys_id=x"},
            {"type": "page", "title": "DevTools", "url": "devtools://devtools/inspector.html"},
            {"type": "service_worker", "title": "sw", "url": "https://dev.example.com/sw.js"},
        ]
    ).encode()

    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(window.urllib.request, "urlopen", lambda *a, **k: _Resp(body))

    assert window._cdp_tabs(9001) == [{"title": "Flow", "url": "dev.example.com/now/wf"}]
