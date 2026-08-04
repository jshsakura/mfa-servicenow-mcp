"""The reaper closes unused windows — and, far more importantly, refuses to.

Every test that asserts a window SURVIVES is the load-bearing one. Closing a
window somebody is looking at is the failure this feature can cause, and it is
worse than the pile of browsers it exists to prevent.
"""

import json
import os
import time
from types import SimpleNamespace

import pytest

from servicenow_mcp.browser import reaper, window
from servicenow_mcp.browser.reaper import IDLE_AFTER_S, reap_idle_windows

LONG_AGO = IDLE_AFTER_S + 600.0


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
def now():
    return time.time()


@pytest.fixture
def mine(tmp_path):
    return FakeAuthManager(str(tmp_path))


def _plant(auth, *, instance_url, username, pid=4242, last_used_at=0.0, started_at=1.0):
    """Write a state file for another configuration's window."""
    other = FakeAuthManager(auth._get_cache_dir(), instance_url, username)
    state = window.WindowState(
        pid=pid,
        port=9333,
        profile_dir="/tmp/p",
        instance_url=instance_url,
        started_at=started_at,
        last_used_at=last_used_at,
    )
    window.write_window_state(other, state)
    return other, state


def _all_alive(monkeypatch, alive=True, pages=1):
    # reaper.py binds these at import, so patching window.* would leave the
    # reaper on the real ones — and every "survives" test below would then pass
    # for the wrong reason (a fake pid is not running).
    #
    # `pages=1` keeps the existing cases meaning what they meant: a running
    # window with something open in it. The reaper judges on `.process`, not on
    # `.reusable` — a window whose last tab is gone is precisely what it should
    # collect, so calling that "not running" would strand it forever.
    liveness = window.Liveness(process=alive, port=alive, pages=pages if alive else None)
    monkeypatch.setattr(reaper, "window_liveness", lambda state: liveness)


def _presence(monkeypatch, value):
    monkeypatch.setattr(reaper, "read_presence", lambda state: value)


def _killed(monkeypatch):
    """Record every pid the reaper terminates."""
    seen = []

    def _terminate(pid):
        seen.append(pid)
        return True

    monkeypatch.setattr(reaper, "terminate_pid", _terminate)
    return seen


# ---------------------------------------------------------------------------
# Enumeration
# ---------------------------------------------------------------------------


def test_sidecars_are_not_mistaken_for_windows(mine, tmp_path):
    _plant(mine, instance_url="https://test.example.com", username="alice@ex.com")
    for sidecar in (".cursor", ".login", ".launches", ".impersonation"):
        name = f"debug_window_test_example_com_alice_at_ex_com{sidecar}.json"
        (tmp_path / name).write_text("{}", encoding="utf-8")

    assert reaper.list_window_keys(mine) == ["test_example_com_alice_at_ex_com"]


# ---------------------------------------------------------------------------
# Refusals — the ones that matter
# ---------------------------------------------------------------------------


def test_the_window_being_asked_for_is_never_a_candidate(mine, monkeypatch, now):
    window.write_window_state(
        mine,
        window.WindowState(
            pid=11,
            port=1,
            profile_dir="/tmp/p",
            instance_url="https://dev.example.com",
            started_at=1.0,
            last_used_at=now - LONG_AGO,
        ),
    )
    _all_alive(monkeypatch)
    _presence(monkeypatch, {"idle_ms": LONG_AGO * 1000, "dirty": 0, "answered": True})
    killed = _killed(monkeypatch)

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []
    assert window.read_window_state(mine) is not None


def test_a_recently_used_window_survives(mine, monkeypatch, now):
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        last_used_at=now - 60,
    )
    _all_alive(monkeypatch)
    killed = _killed(monkeypatch)

    # Presence is never even asked for: last-attach alone already vetoes.
    monkeypatch.setattr(
        reaper, "read_presence", lambda state: pytest.fail("must not attach to a window in use")
    )

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []


def test_a_window_someone_is_touching_survives(mine, monkeypatch, now):
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        last_used_at=now - LONG_AGO,
    )
    _all_alive(monkeypatch)
    # No tool has attached for ages, but the page saw a trusted event a minute
    # ago — across that span the model produced no input, so that was a person.
    _presence(monkeypatch, {"idle_ms": 60_000.0, "dirty": 0, "answered": True})
    killed = _killed(monkeypatch)

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []


def test_a_window_with_unsaved_input_survives(mine, monkeypatch, now):
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        last_used_at=now - LONG_AGO,
    )
    _all_alive(monkeypatch)
    _presence(monkeypatch, {"idle_ms": LONG_AGO * 1000, "dirty": 2, "answered": True})
    killed = _killed(monkeypatch)

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []


def test_a_window_that_cannot_answer_survives(mine, monkeypatch, now):
    """No evidence is not evidence of absence — an old probe must not be fatal."""
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        last_used_at=now - LONG_AGO,
    )
    _all_alive(monkeypatch)
    _presence(monkeypatch, None)
    killed = _killed(monkeypatch)

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []


def test_an_impersonating_window_survives(mine, tmp_path, monkeypatch, now):
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        last_used_at=now - LONG_AGO,
        started_at=1234.5,
    )
    marker = tmp_path / "debug_window_test_example_com_alice_at_ex_com.impersonation.json"
    marker.write_text(
        json.dumps({"started_at": 1234.5, "original": "alice@ex.com", "as": "bob@ex.com"}),
        encoding="utf-8",
    )
    _all_alive(monkeypatch)
    _presence(monkeypatch, {"idle_ms": LONG_AGO * 1000, "dirty": 0, "answered": True})
    killed = _killed(monkeypatch)

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []


def test_an_impersonation_marker_from_a_closed_window_does_not_protect_this_one(
    mine, tmp_path, monkeypatch, now
):
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        last_used_at=now - LONG_AGO,
        started_at=9999.0,
    )
    marker = tmp_path / "debug_window_test_example_com_alice_at_ex_com.impersonation.json"
    marker.write_text(json.dumps({"started_at": 1234.5, "as": "bob@ex.com"}), encoding="utf-8")
    _all_alive(monkeypatch)
    _presence(monkeypatch, {"idle_ms": LONG_AGO * 1000, "dirty": 0, "answered": True})
    killed = _killed(monkeypatch)

    assert len(reap_idle_windows(mine, now=now)) == 1
    assert killed == [4242]


# ---------------------------------------------------------------------------
# Closing
# ---------------------------------------------------------------------------


def test_an_idle_untouched_window_is_closed_and_reported(mine, tmp_path, monkeypatch, now):
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        pid=777,
        last_used_at=now - LONG_AGO,
    )
    _all_alive(monkeypatch)
    _presence(monkeypatch, {"idle_ms": None, "dirty": 0, "answered": True})
    killed = _killed(monkeypatch)

    closed = reap_idle_windows(mine, now=now)

    assert killed == [777]
    assert [entry["instance"] for entry in closed] == ["test.example.com"]
    assert closed[0]["idle_minutes"] >= 30
    assert not os.path.exists(tmp_path / "debug_window_test_example_com_alice_at_ex_com.json")


def test_a_window_whose_last_tab_was_closed_is_collected(mine, tmp_path, monkeypatch, now):
    """The tab-less browser is the reaper's job, not something it steps over.

    Chromium survives its last window on macOS, so this state is created by the
    user closing the window — measured here as three resident processes, one of
    them since the previous Friday. It has no unsaved input to protect and no
    presence to ask, so the presence read below is deliberately absent: reaching
    it would mean the reaper tried to talk to a window with nothing open.
    """
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        pid=778,
        last_used_at=now - LONG_AGO,
    )
    _all_alive(monkeypatch, pages=0)
    _presence(monkeypatch, None)  # "could not ask" — must NOT be what decides
    killed = _killed(monkeypatch)

    closed = reap_idle_windows(mine, now=now)

    assert killed == [778]
    assert [entry["instance"] for entry in closed] == ["test.example.com"]


def test_a_window_that_cannot_report_its_tabs_is_left_alone(mine, tmp_path, monkeypatch, now):
    """`pages is None` is not `pages == 0`; an unread signal closes nothing."""
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        pid=779,
        last_used_at=now - LONG_AGO,
    )
    _all_alive(monkeypatch, pages=None)
    _presence(monkeypatch, None)
    killed = _killed(monkeypatch)

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []


def test_a_dead_window_leaves_no_state_behind(mine, tmp_path, monkeypatch, now):
    """A pid that is already gone is not 'closed', but its state file must go."""
    _plant(
        mine,
        instance_url="https://test.example.com",
        username="alice@ex.com",
        last_used_at=now - LONG_AGO,
    )
    _all_alive(monkeypatch, alive=False)
    killed = _killed(monkeypatch)

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []
    # Not running is a refusal, so the file is left for the normal stale-state
    # path in ensure_window to clear when that window is next asked for.
    assert os.path.exists(tmp_path / "debug_window_test_example_com_alice_at_ex_com.json")


def test_a_broken_state_file_never_breaks_a_launch(mine, tmp_path, monkeypatch, now):
    (tmp_path / "debug_window_test_example_com_bob.json").write_text("{not json", encoding="utf-8")
    _all_alive(monkeypatch)
    killed = _killed(monkeypatch)

    assert reap_idle_windows(mine, now=now) == []
    assert killed == []


# ---------------------------------------------------------------------------
# What the user is told
# ---------------------------------------------------------------------------


def _open_window(monkeypatch, retired, **overrides):
    """Drive open_debug_window with everything past the reaper stubbed out."""
    from unittest.mock import MagicMock

    import servicenow_mcp.tools.browser_debug_tools as tools

    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    monkeypatch.setattr(
        tools, "reap_idle_windows", overrides.get("reap", lambda auth_manager: retired)
    )
    monkeypatch.setattr(
        tools, "ensure_window", overrides.get("ensure", lambda auth_manager, **kw: (state, True))
    )
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda auth_manager: "/tmp/h.json")
    monkeypatch.setattr(tools, "arm", lambda state, **kw: {"armed": True})
    return tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(),
    )


def test_a_closed_window_is_named_in_the_answer(monkeypatch):
    """A window that leaves the screen unannounced reads as the crash this fixes."""
    retired = [{"instance": "test.example.com", "idle_minutes": 47}]

    result = _open_window(monkeypatch, retired)

    assert result["closed_idle_windows"] == retired


def test_nothing_closed_says_nothing(monkeypatch):
    """Housekeeping that found no work costs the model no tokens."""
    result = _open_window(monkeypatch, [])

    assert "closed_idle_windows" not in result


def test_a_closure_is_reported_even_when_the_open_then_fails(monkeypatch):
    def _explode(auth_manager, **kw):
        raise RuntimeError("no chromium")

    retired = [{"instance": "test.example.com", "idle_minutes": 47}]

    result = _open_window(monkeypatch, retired, ensure=_explode)

    assert result["success"] is False
    assert result["closed_idle_windows"] == retired


def test_a_broken_reaper_never_blocks_a_window(monkeypatch):
    """Housekeeping must never stand between the user and the window they asked for."""

    def _explode(auth_manager):
        raise OSError("cache dir vanished")

    result = _open_window(monkeypatch, [], reap=_explode)

    assert result["success"] is True
    assert "closed_idle_windows" not in result
