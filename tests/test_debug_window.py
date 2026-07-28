"""Tests for the shared debug window (servicenow_mcp.browser + its two tools).

These exercise real logic, not wiring: event compaction actually groups and
counts, the duplicate detector actually distinguishes a double-submit from two
deliberate clicks, and the guards actually refuse. The browser itself cannot be
driven in CI, so the boundary tested here is "everything up to the CDP attach".
"""

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.browser import (
    _launch_lock,
    actions,
    cursor,
    launch_budget,
    login,
    report,
    window,
)
from servicenow_mcp.browser.badge import badge_init_script, badge_label, hide_badge_script
from servicenow_mcp.browser.capture import _instance_page
from servicenow_mcp.browser.probe import PROBE_GLOBAL, PROBE_SCRIPT, drain_script
from servicenow_mcp.browser.session import describe_window_user
from servicenow_mcp.policies import write_guards
from servicenow_mcp.tools import browser_debug_tools as tools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeAuthManager:
    """Only the two read-only helpers window.py borrows from the frozen class."""

    def __init__(self, cache_dir: str, suffix: str = "dev_example_com_alice"):
        self._cache_dir = cache_dir
        self._suffix = suffix
        self.instance_url = "https://dev.example.com"

    def _get_cache_dir(self) -> str:
        return self._cache_dir

    def _get_instance_user_suffix(self) -> str:
        return self._suffix


@pytest.fixture
def auth(tmp_path):
    return FakeAuthManager(str(tmp_path))


def _xhr(seq, t, method, url, status=200, req_hash=None, head=None):
    return {
        "seq": seq,
        "t": t,
        "kind": "xhr",
        "method": method,
        "url": url,
        "status": status,
        "ms": 12,
        "req": {"bytes": 40, "hash": req_hash, "head": head} if req_hash or head else None,
    }


def _console(seq, t, msg, level="error"):
    return {"seq": seq, "t": t, "kind": "console", "level": level, "msg": msg}


# ---------------------------------------------------------------------------
# report.py — console compaction
# ---------------------------------------------------------------------------


def test_repeated_console_errors_collapse_to_one_group_with_a_count():
    events = [_console(i, 1000 + i, "TypeError: cannot read 'x' of undefined") for i in range(40)]

    summary = report.summarize_console(events)

    assert summary["errors"] == 40
    assert len(summary["top"]) == 1
    assert summary["top"][0]["count"] == 40


def test_messages_differing_only_by_sys_id_or_number_group_together():
    events = [
        _console(1, 1000, "Widget 8a1b2c3d4e5f60718293a4b5c6d7e8f9 failed at row 3"),
        _console(2, 1001, "Widget 1111111122222222333333334444aaaa failed at row 17"),
    ]

    summary = report.summarize_console(events)

    assert len(summary["top"]) == 1, "sys_id and row number are noise, not distinct errors"
    assert summary["top"][0]["count"] == 2


def test_distinct_errors_stay_distinct():
    events = [
        _console(1, 1000, "TypeError: undefined is not a function"),
        _console(2, 1001, "ReferenceError: spUtil is not defined"),
    ]

    summary = report.summarize_console(events)

    assert len(summary["top"]) == 2


def test_console_groups_beyond_the_cap_are_counted_not_dropped_silently():
    events = [_console(i, 1000 + i, f"distinct error kind {chr(97 + i)}") for i in range(9)]

    summary = report.summarize_console(events)

    assert len(summary["top"]) == report.MAX_CONSOLE_GROUPS
    assert summary["groups_omitted"] == 9 - report.MAX_CONSOLE_GROUPS


# ---------------------------------------------------------------------------
# report.py — duplicate detection (the double-save question)
# ---------------------------------------------------------------------------


def test_same_post_twice_in_quick_succession_is_flagged_as_a_duplicate():
    events = [
        _xhr(
            1,
            10_000,
            "POST",
            "https://x/api/now/sp/widget/abc",
            req_hash="deadbeef",
            head="{'a':1}",
        ),
        _xhr(2, 10_023, "POST", "https://x/api/now/sp/widget/abc", req_hash="deadbeef"),
    ]

    duplicates = report.summarize_network(events)["duplicates"]

    assert len(duplicates) == 1
    assert duplicates[0]["count"] == 2
    assert duplicates[0]["min_gap_ms"] == 23
    assert duplicates[0]["same_payload"] is True


def test_two_posts_far_apart_are_two_deliberate_clicks_not_a_duplicate():
    events = [
        _xhr(1, 10_000, "POST", "https://x/api/now/sp/widget/abc", req_hash="deadbeef"),
        _xhr(
            2,
            10_000 + report.DUPLICATE_WINDOW_MS + 1,
            "POST",
            "https://x/api/now/sp/widget/abc",
            req_hash="deadbeef",
        ),
    ]

    assert report.summarize_network(events)["duplicates"] == []


def test_repeated_gets_are_not_duplicates():
    events = [_xhr(i, 10_000 + i, "GET", "https://x/api/now/table/incident") for i in range(5)]

    assert report.summarize_network(events)["duplicates"] == []


def test_duplicate_grouping_ignores_the_query_string_but_not_the_path():
    events = [
        _xhr(1, 10_000, "POST", "https://x/api/now/sp/widget/abc?v=1", req_hash="h"),
        _xhr(2, 10_010, "POST", "https://x/api/now/sp/widget/abc?v=2", req_hash="h"),
        _xhr(3, 10_020, "POST", "https://x/api/now/sp/widget/OTHER", req_hash="h"),
    ]

    duplicates = report.summarize_network(events)["duplicates"]

    assert len(duplicates) == 1
    assert duplicates[0]["path"] == "/api/now/sp/widget/abc"


def test_failed_requests_are_counted_and_listed():
    events = [
        _xhr(1, 1, "GET", "https://x/api/now/table/sys_user", status=403),
        _xhr(2, 2, "GET", "https://x/api/now/table/incident", status=200),
    ]

    network = report.summarize_network(events)

    assert network["xhr"] == 2
    assert network["failed"] == 1
    assert network["failures"][0]["status"] == 403


# ---------------------------------------------------------------------------
# report.py — verdict and compaction
# ---------------------------------------------------------------------------


def test_verdict_leads_with_the_duplicate_finding():
    events = [
        _xhr(1, 10_000, "POST", "https://x/api/now/sp/widget/abc", req_hash="h"),
        _xhr(2, 10_023, "POST", "https://x/api/now/sp/widget/abc", req_hash="h"),
    ]
    network = report.summarize_network(events)

    verdict = report.build_verdict(report.summarize_console([]), network, watched=0)

    assert "2x" in verdict and "23ms" in verdict
    assert "client fired it more than once" in verdict


def test_clean_page_gets_an_explicit_all_clear():
    verdict = report.build_verdict(
        report.summarize_console([]), report.summarize_network([]), watched=30
    )

    assert "No errors" in verdict and "30s" in verdict


def test_compact_writes_bodies_to_disk_and_returns_only_a_path(tmp_path):
    events = [_console(1, 1, "boom"), _xhr(2, 2, "POST", "https://x/y", req_hash="h")]
    raw = {"url": "https://x/sp", "title": "t", "seq": 2, "events": events}

    result = report.compact(raw, artifacts_dir=str(tmp_path / "art"))

    assert "events" not in result, "raw events must never be returned inline"
    saved = json.loads(open(result["artifacts"], encoding="utf-8").read())
    assert len(saved) == 2


def test_compact_reports_dropped_events_rather_than_hiding_truncation():
    raw = {"url": "u", "seq": 500, "dropped": 120, "events": []}

    result = report.compact(raw, artifacts_dir="")

    assert result["dropped_events"] == 120


def test_compact_omits_screenshot_and_styles_when_not_requested():
    result = report.compact({"url": "u", "seq": 1, "events": []}, artifacts_dir="")

    assert "screenshot" not in result
    assert "styles" not in result


# ---------------------------------------------------------------------------
# launch_budget.py — the runaway-window guard
# ---------------------------------------------------------------------------


def test_relaunching_seconds_after_a_launch_is_refused_as_a_crash_loop(tmp_path):
    path = str(tmp_path / "h.json")
    now = 1_000_000.0
    launch_budget.record_launch(path, now=now)

    with pytest.raises(launch_budget.LaunchBudgetExceeded, match="already gone"):
        launch_budget.check_launch_allowed(path, now=now + 2)


def test_a_relaunch_after_the_cooldown_is_allowed(tmp_path):
    path = str(tmp_path / "h.json")
    now = 1_000_000.0
    launch_budget.record_launch(path, now=now)

    launch_budget.check_launch_allowed(path, now=now + launch_budget.MIN_RELAUNCH_INTERVAL_S + 1)


def test_too_many_launches_in_the_window_are_refused(tmp_path):
    path = str(tmp_path / "h.json")
    now = 1_000_000.0
    for index in range(launch_budget.MAX_LAUNCHES_PER_WINDOW):
        launch_budget.record_launch(path, now=now + index * 30)

    with pytest.raises(launch_budget.LaunchBudgetExceeded, match="reopening in a loop"):
        launch_budget.check_launch_allowed(path, now=now + 300)


def test_launches_older_than_the_window_stop_counting(tmp_path):
    path = str(tmp_path / "h.json")
    now = 1_000_000.0
    for index in range(launch_budget.MAX_LAUNCHES_PER_WINDOW):
        launch_budget.record_launch(path, now=now + index)

    launch_budget.check_launch_allowed(path, now=now + launch_budget.LAUNCH_WINDOW_S + 10)


def test_checking_the_budget_does_not_consume_it(tmp_path):
    path = str(tmp_path / "h.json")

    launch_budget.check_launch_allowed(path, now=1_000_000.0)
    launch_budget.check_launch_allowed(path, now=1_000_000.0)

    assert launch_budget.recent_launches(path, now=1_000_000.0) == []


# ---------------------------------------------------------------------------
# _launch_lock.py — one window across N MCP hosts
# ---------------------------------------------------------------------------


def test_a_second_claim_on_a_live_lock_does_not_succeed(tmp_path):
    path = str(tmp_path / "w.claim")

    assert _launch_lock._try_claim(path) is True
    assert _launch_lock._try_claim(path) is False


def test_the_claim_is_released_when_the_block_exits(tmp_path):
    path = str(tmp_path / "w.claim")

    with _launch_lock.launch_claim(path) as claimed:
        assert claimed is True
        assert os.path.exists(path)

    assert not os.path.exists(path)


def test_the_claim_is_released_even_when_the_block_raises(tmp_path):
    path = str(tmp_path / "w.claim")

    with pytest.raises(ValueError):
        with _launch_lock.launch_claim(path):
            raise ValueError("launch blew up")

    assert not os.path.exists(path)


def test_a_claim_older_than_the_stale_window_is_collectable(tmp_path):
    path = str(tmp_path / "w.claim")
    _launch_lock._try_claim(path)
    old = time.time() - _launch_lock.CLAIM_STALE_AFTER_S - 10
    os.utime(path, (old, old))

    assert _launch_lock._claim_is_stale(path) is True


def test_a_fresh_claim_held_by_a_live_process_is_not_stale(tmp_path):
    path = str(tmp_path / "w.claim")
    _launch_lock._try_claim(path)

    assert _launch_lock._claim_is_stale(path) is False


# ---------------------------------------------------------------------------
# cursor.py — the since_last high-water mark
# ---------------------------------------------------------------------------


def test_cursor_round_trips(tmp_path):
    path = str(tmp_path / "c.json")
    cursor.write_cursor(path, 42)

    assert cursor.read_cursor(path) == 42


def test_since_last_false_reads_from_the_beginning(tmp_path):
    path = str(tmp_path / "c.json")
    cursor.write_cursor(path, 42)

    assert cursor.resolve_after_seq(path, since_last=False) == 0


def test_an_explicit_after_seq_overrides_the_cursor(tmp_path):
    path = str(tmp_path / "c.json")
    cursor.write_cursor(path, 42)

    assert cursor.resolve_after_seq(path, since_last=True, explicit=7) == 7


def test_a_missing_cursor_reads_everything(tmp_path):
    assert cursor.resolve_after_seq(str(tmp_path / "nope.json"), since_last=True) == 0


# ---------------------------------------------------------------------------
# window.py — identity, state, and the "never launch on read" rule
# ---------------------------------------------------------------------------


def test_the_debug_window_is_always_headed_regardless_of_login_headless_config(monkeypatch):
    # The shared window exists to be looked at. SERVICENOW_BROWSER_HEADLESS
    # governs the LOGIN browser and must never reach this launch path — a
    # headless shared screen is a contradiction.
    monkeypatch.setenv("SERVICENOW_BROWSER_HEADLESS", "true")

    args = window._launch_args(port=9333, profile_dir="/tmp/p", viewport=(800, 600), url="")

    assert window.DEBUG_WINDOW_ALWAYS_HEADED is True
    assert not any("headless" in arg for arg in args)


def test_the_launch_binds_the_debugging_port_to_loopback_only():
    args = window._launch_args(port=9333, profile_dir="/tmp/p", viewport=(800, 600), url="")

    assert "--remote-debugging-port=9333" in args
    assert "--remote-allow-origins=http://127.0.0.1" in args


def test_the_debug_profile_is_never_the_login_profile(auth):
    profile = window.window_profile_dir(auth)

    assert "debug_profile_" in os.path.basename(profile)
    assert os.path.basename(profile) != f"profile_{auth._get_instance_user_suffix()}"


def test_two_instances_get_separate_windows(tmp_path):
    dev = FakeAuthManager(str(tmp_path), "dev_example_com_alice")
    test = FakeAuthManager(str(tmp_path), "test_example_com_alice")

    assert window.window_state_path(dev) != window.window_state_path(test)
    assert window.window_profile_dir(dev) != window.window_profile_dir(test)
    assert window.window_artifacts_dir(dev) != window.window_artifacts_dir(test)


def test_window_state_round_trips_through_disk(auth):
    state = window.WindowState(
        pid=4242,
        port=9333,
        profile_dir="/tmp/p",
        instance_url="https://dev.example.com",
        started_at=1.0,
    )

    window.write_window_state(auth, state)

    assert window.read_window_state(auth) == state


def test_malformed_state_is_ignored_rather_than_raised(auth):
    path = window.window_state_path(auth)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")

    assert window.read_window_state(auth) is None


def test_find_window_never_launches(auth, monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("a read must never put a window on the user's screen")

    monkeypatch.setattr(window, "launch_window", _explode)
    monkeypatch.setattr(window, "ensure_window", _explode)

    assert window.find_window(auth) is None


def test_find_window_ignores_a_dead_pid(auth, monkeypatch):
    window.write_window_state(
        auth,
        window.WindowState(
            pid=999_999_999, port=9333, profile_dir="/tmp/p", instance_url="", started_at=1.0
        ),
    )
    monkeypatch.setattr(window, "_is_pid_alive", lambda pid: False)

    assert window.find_window(auth) is None


def test_a_live_pid_with_a_dead_port_is_not_a_live_window(monkeypatch):
    state = window.WindowState(
        pid=1, port=9333, profile_dir="/tmp/p", instance_url="", started_at=1.0
    )
    monkeypatch.setattr(window, "_is_pid_alive", lambda pid: True)
    monkeypatch.setattr(window, "_cdp_responds", lambda port, timeout_s=1.0: False)

    assert window.is_window_alive(state) is False


# ---------------------------------------------------------------------------
# capture.py — picking the right tab
# ---------------------------------------------------------------------------


def test_the_tab_on_the_instance_wins_over_an_unrelated_one():
    pages = [
        SimpleNamespace(url="https://news.example.org/"),
        SimpleNamespace(url="https://dev.example.com/sp?id=my_page"),
    ]

    assert _instance_page(pages, "dev.example.com") is pages[1]


def test_devtools_tabs_are_never_selected():
    pages = [SimpleNamespace(url="devtools://devtools/bundled/x.html")]

    assert _instance_page(pages, "dev.example.com") is None


def test_with_no_instance_tab_the_first_real_tab_is_used():
    pages = [
        SimpleNamespace(url="devtools://devtools/x"),
        SimpleNamespace(url="about:blank"),
    ]

    assert _instance_page(pages, "dev.example.com") is pages[1]


# ---------------------------------------------------------------------------
# badge.py / probe.py — identity on screen, collector in the page
# ---------------------------------------------------------------------------


def test_the_badge_names_the_instance_so_two_windows_are_distinguishable():
    assert "dev.example.com" in badge_label("dev.example.com", "profile_x")


def test_the_badge_lives_in_a_closed_shadow_root_so_page_css_cannot_reach_it():
    script = badge_init_script("dev.example.com", "p")

    assert "attachShadow({ mode: 'closed' })" in script
    assert "position:fixed" in script
    assert "pointer-events:none" in script


def test_the_badge_can_be_hidden_for_screenshots():
    assert "'none'" in hide_badge_script()


def test_the_probe_is_idempotent_so_re_injection_is_safe():
    assert "if (window[G]) return;" in PROBE_SCRIPT


def test_the_probe_caps_its_own_buffer_in_the_page():
    # Trimming at the source is what stops a runaway error loop from becoming a
    # payload this process has to receive and parse.
    assert "events.length > MAX" in PROBE_SCRIPT


def test_the_probe_records_a_payload_hash_not_the_payload():
    assert "hash(text)" in PROBE_SCRIPT
    assert "text.slice(0, HEAD)" in PROBE_SCRIPT


def test_drain_reads_only_events_after_the_high_water_mark():
    assert "drain(12)" in drain_script(12)
    assert PROBE_GLOBAL in drain_script(0)


# ---------------------------------------------------------------------------
# session.py — window identity vs API identity
# ---------------------------------------------------------------------------


def test_a_different_user_in_the_window_is_reported_as_a_note_not_a_failure():
    described = describe_window_user({"user": "bob", "source": "g_user"}, "alice")

    assert described["window_user"] == "bob"
    assert "not what the" in described["note"]


def test_the_same_user_produces_no_note():
    described = describe_window_user({"user": "Alice", "source": "g_user"}, "alice")

    assert "note" not in described


def test_an_unreadable_user_is_reported_as_unknown():
    described = describe_window_user(None, "alice")

    assert described["window_user"] is None


# ---------------------------------------------------------------------------
# tools — the side-effect asymmetry
# ---------------------------------------------------------------------------


def test_inspect_reports_no_window_instead_of_opening_one(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("inspect must never launch a window")

    monkeypatch.setattr(tools, "find_window", lambda auth_manager: None)
    monkeypatch.setattr(tools, "ensure_window", _explode)

    result = tools.inspect_debug_window(MagicMock(), MagicMock(), tools.InspectDebugWindowParams())

    assert result["success"] is False
    assert result["window_open"] is False
    assert "open_debug_window" in result["error"]


def test_inspect_rejects_an_unknown_screenshot_mode():
    result = tools.inspect_debug_window(
        MagicMock(), MagicMock(), tools.InspectDebugWindowParams(screenshot="pdf")
    )

    assert result["success"] is False
    assert "viewport" in result["error"]


def test_element_screenshot_requires_a_selector():
    result = tools.inspect_debug_window(
        MagicMock(), MagicMock(), tools.InspectDebugWindowParams(screenshot="element")
    )

    assert result["success"] is False
    assert "selector" in result["error"]


def test_open_reports_reuse_rather_than_opening_a_second_window(monkeypatch):
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, False))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda auth_manager: "/tmp/h.json")
    monkeypatch.setattr(tools, "arm", lambda state, profile: {"armed": True})

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(),
    )

    assert result["opened"] is False
    assert result["reused"] is True
    assert result["instance_target"] == "dev.example.com"


def test_opening_arms_the_collector_before_the_user_clicks_anything(monkeypatch):
    # The submit that causes a double-save happens before the first inspect.
    # If arming waited for that inspect, the evidence would never be recorded.
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    armed_calls = []
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, True))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda auth_manager: "/tmp/h.json")
    monkeypatch.setattr(
        tools, "arm", lambda state, profile: armed_calls.append(profile) or {"armed": True}
    )

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(url="/sp?id=my_page"),
    )

    assert armed_calls == ["https://dev.example.com"]
    assert result["recording"] is True


def test_a_window_with_no_tab_reports_that_it_is_not_recording(monkeypatch):
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, True))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda auth_manager: "/tmp/h.json")
    monkeypatch.setattr(
        tools, "arm", lambda state, profile: {"armed": False, "reason": "no open tab"}
    )

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(),
    )

    assert result["recording"] is False
    assert "no open tab" in result["recording_note"]


def test_open_refuses_to_discard_unsaved_input_by_default(monkeypatch):
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, False))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda auth_manager: "/tmp/h.json")
    monkeypatch.setattr(
        tools,
        "navigate",
        lambda state, url, profile, allow_discard: {
            "navigated": False,
            "url": "https://dev.example.com/form",
            "blocked_by_unsaved_input": ["short_description"],
        },
    )

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(url="/sp?id=other"),
    )

    assert result["navigated"] is False
    assert result["blocked_by_unsaved_input"] == ["short_description"]
    assert "discard_unsaved_input=true" in result["hint"]


def test_a_launch_budget_refusal_surfaces_as_an_error_not_an_exception(monkeypatch):
    def _refuse(auth_manager, **kwargs):
        raise launch_budget.LaunchBudgetExceeded("too many windows")

    monkeypatch.setattr(tools, "ensure_window", _refuse)

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(),
    )

    assert result["success"] is False
    assert "too many windows" in result["error"]


def test_relative_urls_resolve_against_the_instance():
    resolved = tools._resolve_url(
        SimpleNamespace(instance_url="https://dev.example.com/"), "/sp?id=x"
    )

    assert resolved == "https://dev.example.com/sp?id=x"


def test_absolute_urls_are_left_alone():
    resolved = tools._resolve_url(
        SimpleNamespace(instance_url="https://dev.example.com"), "https://other.test/x"
    )

    assert resolved == "https://other.test/x"


# ---------------------------------------------------------------------------
# Fake DOM — enough of Playwright's surface for login.py and actions.py
# ---------------------------------------------------------------------------


class FakeLocator:
    """Understands the comma unions login.py builds out of the selector tuples."""

    def __init__(self, target, selector):
        self.target = target
        self.selector = selector

    def _matches(self):
        return [
            part.strip() for part in self.selector.split(",") if part.strip() in self.target.known
        ]

    def count(self):
        return len(self._matches())

    @property
    def first(self):
        return self

    def _record(self, name, *args):
        if self.selector in self.target.unactionable:
            raise RuntimeError(f"element for {self.selector} is not actionable")
        self.target.calls.append((name, self.selector, *args))

    def click(self, timeout=None):
        self._record("click")

    def dblclick(self, timeout=None):
        self._record("dblclick")

    def fill(self, value, timeout=None):
        self._record("fill", value)

    def select_option(self, value, timeout=None):
        self._record("select", value)

    def check(self, timeout=None):
        self._record("check")

    def uncheck(self, timeout=None):
        self._record("uncheck")

    def hover(self, timeout=None):
        self._record("hover")

    def press(self, key, timeout=None):
        self._record("press", key)

    def scroll_into_view_if_needed(self, timeout=None):
        self._record("scroll_to")


class FakeTarget:
    """A page or a frame. `known` is what exists in this document."""

    def __init__(self, known=(), url="https://dev.example.com/login.do", unactionable=()):
        self.known = set(known)
        self.url = url
        self.calls = []
        self.unactionable = set(unactionable)

    def locator(self, selector):
        return FakeLocator(self, selector)

    # Page-level convenience methods, which auth/_browser_dom.py uses directly.
    def fill(self, selector, value):
        if selector not in self.known:
            raise RuntimeError("no such field")
        self.calls.append(("fill", selector, value))

    def click(self, selector):
        if selector not in self.known:
            raise RuntimeError("no such button")
        self.calls.append(("click", selector))


class FakeKeyboard:
    def __init__(self):
        self.pressed = []

    def press(self, key):
        self.pressed.append(key)


class FakePage(FakeTarget):
    def __init__(self, known=(), frames=(), url="https://dev.example.com/login.do", **kwargs):
        super().__init__(known=known, url=url, **kwargs)
        self._frames = list(frames)
        self.keyboard = FakeKeyboard()
        self.waited_for = []

    @property
    def main_frame(self):
        return self

    @property
    def frames(self):
        return [self] + self._frames

    def wait_for_selector(self, selector, timeout=None, state=None):
        self.waited_for.append(selector)
        if FakeLocator(self, selector).count():
            return object()
        raise RuntimeError("timeout waiting for selector")


# ---------------------------------------------------------------------------
# login.py — credentials, the one-attempt claim, filling
# ---------------------------------------------------------------------------


def _config(browser=None, basic=None):
    return SimpleNamespace(auth=SimpleNamespace(browser=browser, basic=basic))


def test_browser_credentials_win_over_basic():
    config = _config(
        browser=SimpleNamespace(username="alice", password="b-secret"),
        basic=SimpleNamespace(username="bob", password="a-secret"),
    )

    assert login.saved_credentials(config) == ("alice", "b-secret")


def test_basic_credentials_are_used_when_browser_has_none():
    config = _config(
        browser=SimpleNamespace(username=None, password=None),
        basic=SimpleNamespace(username="bob", password="a-secret"),
    )

    assert login.saved_credentials(config) == ("bob", "a-secret")


def test_half_a_credential_is_not_a_credential():
    # Filling a username and submitting nothing useful is worse than not trying.
    config = _config(browser=SimpleNamespace(username="alice", password=None))

    assert login.saved_credentials(config) is None


def test_an_oauth_profile_has_nothing_to_fill():
    assert login.saved_credentials(SimpleNamespace(auth=SimpleNamespace())) is None
    assert login.saved_credentials(SimpleNamespace()) is None


def _state(started_at=100.0):
    return window.WindowState(
        pid=1,
        port=2,
        profile_dir="/tmp/p",
        instance_url="https://dev.example.com",
        started_at=started_at,
    )


def test_the_attempt_marker_is_keyed_to_the_window_not_the_instance(tmp_path):
    # Reopening the window is how a person retries after fixing a typo, so a
    # NEW window must get a fresh attempt even though the file still exists.
    path = str(tmp_path / "login.json")
    first = _state(started_at=100.0)
    login.record_attempt(path, first)

    assert login.already_attempted(path, first) is True
    assert login.already_attempted(path, _state(started_at=200.0)) is False


def test_a_missing_or_corrupt_marker_means_no_attempt_has_been_spent(tmp_path):
    path = str(tmp_path / "login.json")
    assert login.already_attempted(path, _state()) is False

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert login.already_attempted(path, _state()) is False


def test_auto_login_without_credentials_never_touches_the_browser(monkeypatch):
    def _explode():
        raise AssertionError("Playwright must not be required with nothing to fill")

    monkeypatch.setattr(login, "require_playwright", _explode)

    assert login.auto_login(_state(), credentials=None, marker_path="/tmp/x")["status"] == (
        "no_credentials"
    )


def test_a_spent_window_does_not_get_a_second_attempt(tmp_path, monkeypatch):
    # The lockout guard: a wrong password retried on every open is how an
    # account gets locked, and the retry could not succeed anyway.
    path = str(tmp_path / "login.json")
    login.record_attempt(path, _state())
    monkeypatch.setattr(
        login,
        "require_playwright",
        lambda: (_ for _ in ()).throw(AssertionError("must not attach")),
    )

    result = login.auto_login(_state(), credentials=("alice", "s"), marker_path=path)

    assert result["status"] == "already_attempted"


def test_a_login_form_inside_an_iframe_is_still_found():
    frame = FakeTarget(known=["input#user_password"])
    page = FakePage(known=[], frames=[frame])

    assert login._wait_for_login_form(page) is True


def test_a_signed_in_page_is_not_a_login_page():
    page = FakePage(known=["#header"], url="https://dev.example.com/sp")

    assert login._wait_for_login_form(page) is False


def test_filling_submits_with_the_login_button_when_there_is_one():
    page = FakePage(known=["input#user_name", "input#user_password", "button#sysverb_login"])

    outcome = login._fill_and_submit(page, "alice", "s3cret")

    assert outcome == {"filled": True, "submitted": True, "via": "click button#sysverb_login"}
    assert ("fill", "input#user_name", "alice") in page.calls
    assert ("click", "button#sysverb_login") in page.calls


def test_a_form_with_no_recognizable_button_is_submitted_with_enter():
    page = FakePage(known=["input#user_name", "input#user_password"])

    outcome = login._fill_and_submit(page, "alice", "s3cret")

    assert outcome["submitted"] is True
    assert outcome["via"] == "Enter"
    assert ("press", "input#user_password", "Enter") in page.calls


def test_an_sso_form_in_a_frame_is_filled_in_that_frame():
    frame = FakeTarget(
        known=["input[name='loginfmt']", "input[type='password']", "input#idSIButton9"]
    )
    page = FakePage(known=["#chrome"], frames=[frame])

    outcome = login._fill_and_submit(page, "alice", "s3cret")

    assert outcome["filled"] is True
    assert ("fill", "input[name='loginfmt']", "alice") in frame.calls
    assert page.calls == []


def test_an_unrecognized_form_reports_that_rather_than_claiming_success():
    page = FakePage(known=["#nothing_familiar"])

    assert login._fill_and_submit(page, "alice", "s")["filled"] is False


def test_the_submitted_message_hands_mfa_to_the_user():
    note = login.describe({"status": "submitted", "user": "alice"})

    assert "alice" in note
    assert "MFA" in note


def test_the_already_attempted_message_says_how_to_retry():
    note = login.describe({"status": "already_attempted"})

    assert "close the window" in note.lower()


def test_nothing_is_said_when_nothing_happened():
    assert login.describe({"status": "no_login_form"}) is None
    assert login.describe({"status": "no_credentials"}) is None


# ---------------------------------------------------------------------------
# probe.py — credentials never reach the buffer
# ---------------------------------------------------------------------------


def test_the_probe_strips_credentials_in_the_page_before_buffering():
    # The window types a real password into a real form; an IdP that posts it
    # over fetch would otherwise land it in an artifacts file on disk.
    assert "<redacted>" in PROBE_SCRIPT
    assert "password" in PROBE_SCRIPT
    # Redaction happens at the source, not in a later Python stage.
    assert PROBE_SCRIPT.index("const redact") < PROBE_SCRIPT.index("const summarize")


def test_request_urls_are_redacted_too_so_a_query_token_does_not_survive():
    assert "redact(meta.url || '')" in PROBE_SCRIPT
    assert "redact(String((input && input.url) || input || ''))" in PROBE_SCRIPT


def test_the_byte_count_still_describes_the_real_payload():
    # Redaction changes the text; reporting the redacted length would quietly
    # misstate how big the request was.
    assert "const bytes = text.length;" in PROBE_SCRIPT
    assert PROBE_SCRIPT.index("const bytes = text.length;") < PROBE_SCRIPT.index(
        "text = redact(text)"
    )


# ---------------------------------------------------------------------------
# actions.py — validation before the browser is touched
# ---------------------------------------------------------------------------


def test_an_unknown_action_is_rejected_with_the_supported_list():
    with pytest.raises(ValueError) as excinfo:
        actions.normalize([{"action": "eval", "selector": "#x"}])

    assert "eval" in str(excinfo.value)
    assert "click" in str(excinfo.value)


def test_an_empty_batch_is_rejected():
    with pytest.raises(ValueError):
        actions.normalize([])


def test_a_batch_longer_than_the_cap_is_rejected():
    with pytest.raises(ValueError) as excinfo:
        actions.normalize([{"action": "click", "selector": "#x"}] * (actions.MAX_ACTIONS + 1))

    assert str(actions.MAX_ACTIONS) in str(excinfo.value)


def test_a_click_without_a_selector_is_rejected_before_anything_runs():
    with pytest.raises(ValueError) as excinfo:
        actions.normalize([{"action": "click"}])

    assert "selector" in str(excinfo.value)


def test_a_fill_without_a_value_is_rejected():
    with pytest.raises(ValueError) as excinfo:
        actions.normalize([{"action": "fill", "selector": "#x"}])

    assert "value" in str(excinfo.value)


def test_a_press_without_a_key_is_rejected():
    with pytest.raises(ValueError) as excinfo:
        actions.normalize([{"action": "press"}])

    assert "key" in str(excinfo.value)


def test_an_empty_string_is_a_legitimate_fill_value():
    # Clearing a field is a real step; `not value` would have rejected it.
    normalized = actions.normalize([{"action": "fill", "selector": "#x", "value": ""}])

    assert normalized[0]["value"] == ""


def test_timeouts_and_pauses_are_clamped_not_trusted():
    normalized = actions.normalize(
        [
            {"action": "click", "selector": "#x", "timeout_ms": 10_000_000},
            {"action": "wait", "ms": 10_000_000},
        ]
    )

    assert normalized[0]["timeout_ms"] == actions.MAX_STEP_TIMEOUT_MS
    assert normalized[1]["ms"] == actions.MAX_WAIT_MS


def test_the_offload_budget_covers_every_step_in_the_batch():
    one = actions.budget_seconds(actions.normalize([{"action": "click", "selector": "#x"}]))
    three = actions.budget_seconds(actions.normalize([{"action": "click", "selector": "#x"}] * 3))

    assert three > one


# ---------------------------------------------------------------------------
# actions.py — running a step
# ---------------------------------------------------------------------------


def _step(**overrides):
    base = {
        "action": "click",
        "selector": "#x",
        "value": None,
        "key": None,
        "ms": 0,
        "timeout_ms": 500,
        "state": "visible",
    }
    base.update(overrides)
    return base


def test_a_selector_is_resolved_against_frames_not_just_the_page():
    # ServiceNow puts real forms in gsft_main; main-frame-only would miss them.
    frame = FakeTarget(known=["#incident_save"])
    page = FakePage(known=["#header"], frames=[frame])

    actions._run_step(page, _step(selector="#incident_save"), 1)

    assert ("click", "#incident_save") in frame.calls


def test_a_selector_that_never_appears_fails_with_the_step_number():
    page = FakePage(known=["#header"])

    with pytest.raises(actions.ActionError) as excinfo:
        actions._run_step(page, _step(selector="#missing", timeout_ms=100), 3)

    assert excinfo.value.index == 3
    assert "#missing" in str(excinfo.value)
    assert "frame" in str(excinfo.value)


def test_an_element_that_refuses_the_click_reports_why():
    page = FakePage(known=["#save"], unactionable=["#save"])

    with pytest.raises(actions.ActionError) as excinfo:
        actions._run_step(page, _step(selector="#save"), 1)

    assert "not actionable" in str(excinfo.value)


def test_fill_passes_the_value_through():
    page = FakePage(known=["#short_description"])

    actions._run_step(
        page, _step(action="fill", selector="#short_description", value="broken widget"), 1
    )

    assert ("fill", "#short_description", "broken widget") in page.calls


def test_press_without_a_selector_goes_to_the_keyboard():
    page = FakePage(known=[])

    actions._run_step(page, _step(action="press", selector=None, key="Escape"), 1)

    assert page.keyboard.pressed == ["Escape"]


def test_wait_for_returns_as_soon_as_the_element_is_there():
    page = FakePage(known=[".notification"])

    result = actions._run_step(page, _step(action="wait_for", selector=".notification"), 1)

    assert result == {"state": "visible"}


def test_wait_for_hidden_is_satisfied_by_an_absent_element():
    page = FakePage(known=[])

    result = actions._run_step(
        page, _step(action="wait_for", selector=".spinner", state="hidden"), 1
    )

    assert result == {"state": "hidden"}


def test_wait_for_times_out_with_a_message_naming_the_selector():
    page = FakePage(known=[])

    with pytest.raises(actions.ActionError) as excinfo:
        actions._run_step(page, _step(action="wait_for", selector=".never", timeout_ms=200), 2)

    assert ".never" in str(excinfo.value)
    assert excinfo.value.index == 2


def test_wait_actually_pauses():
    page = FakePage(known=[])
    started = time.time()

    result = actions._run_step(page, _step(action="wait", selector=None, ms=120), 1)

    assert result == {"waited_ms": 120}
    assert time.time() - started >= 0.1


# ---------------------------------------------------------------------------
# tools — acting is a separate, write-classified tool
# ---------------------------------------------------------------------------


def test_acting_never_opens_a_window(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("acting must never launch a window")

    monkeypatch.setattr(tools, "find_window", lambda auth_manager: None)
    monkeypatch.setattr(tools, "ensure_window", _explode)

    result = tools.act_in_debug_window(
        MagicMock(),
        MagicMock(),
        tools.ActInDebugWindowParams(actions=[{"action": "click", "selector": "#x"}]),
    )

    assert result["success"] is False
    assert result["window_open"] is False
    assert "open_debug_window" in result["error"]


def test_an_invalid_batch_is_rejected_before_the_window_is_even_looked_up(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("validation must happen before the browser is touched")

    monkeypatch.setattr(tools, "find_window", _explode)

    result = tools.act_in_debug_window(
        MagicMock(),
        MagicMock(),
        tools.ActInDebugWindowParams(actions=[{"action": "fill", "selector": "#x"}]),
    )

    assert result["success"] is False
    assert "value" in result["error"]


def test_a_failed_step_still_returns_the_report_that_explains_it(monkeypatch, tmp_path):
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        tools,
        "act",
        lambda state, **kw: {
            "url": "https://dev.example.com/form",
            "title": "Incident",
            "seq": 7,
            "events": [_console(7, 1000, "TypeError: x is undefined")],
            "steps": [
                {"step": 1, "action": "click", "selector": "#save", "ok": True},
                {"step": 2, "action": "wait_for", "selector": ".ok", "ok": False, "error": "gone"},
            ],
            "dialogs": [],
            "failed_step": 2,
            "skipped": 1,
        },
    )

    result = tools.act_in_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.ActInDebugWindowParams(
            actions=[
                {"action": "click", "selector": "#save"},
                {"action": "wait_for", "selector": ".ok"},
            ]
        ),
    )

    assert result["success"] is False
    assert result["failed_step"] == 2
    assert result["skipped_steps"] == 1
    # The point of returning the report anyway: it says WHY the wait failed.
    assert "console error" in result["verdict"]


def test_an_accepted_dialog_is_always_reported(monkeypatch, tmp_path):
    # A confirm box that was answered changes what the click actually did.
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        tools,
        "act",
        lambda state, **kw: {
            "url": "https://dev.example.com/form",
            "seq": 1,
            "events": [],
            "steps": [{"step": 1, "action": "click", "selector": "#delete", "ok": True}],
            "dialogs": [{"type": "confirm", "message": "Delete this record?", "accepted": True}],
            "failed_step": None,
            "skipped": 0,
        },
    )

    result = tools.act_in_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.ActInDebugWindowParams(actions=[{"action": "click", "selector": "#delete"}]),
    )

    assert result["success"] is True
    assert result["dialogs"][0]["message"] == "Delete this record?"
    assert result["dialogs"][0]["accepted"] is True


def test_acting_is_classified_as_a_write():
    # A click on Save creates a record just as surely as the Table API would,
    # and the name matches no mutating prefix — so it must be listed by name.
    assert "act_in_debug_window" in write_guards.MUTATING_TOOL_NAMES
    assert write_guards._is_read_only("act_in_debug_window", {}) is False


# ---------------------------------------------------------------------------
# tools — auto-login on open
# ---------------------------------------------------------------------------


def _open_with_login(monkeypatch, login_result, config):
    state = _state()
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, True))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda a: "/tmp/h.json")
    monkeypatch.setattr(tools, "window_login_path", lambda a: "/tmp/l.json")
    monkeypatch.setattr(tools, "arm", lambda state, profile: {"armed": True})
    monkeypatch.setattr(tools, "auto_login", lambda state, **kw: login_result)
    return tools.open_debug_window(config, MagicMock(), tools.OpenDebugWindowParams())


def test_opening_signs_the_window_in_with_the_saved_credentials(monkeypatch):
    config = SimpleNamespace(
        instance_url="https://dev.example.com",
        auth=SimpleNamespace(browser=SimpleNamespace(username="alice", password="s"), basic=None),
    )

    result = _open_with_login(
        monkeypatch, {"status": "submitted", "user": "alice", "via": "click"}, config
    )

    assert result["auto_login"] == "submitted"
    assert "alice" in result["hint"]


def test_opening_says_nothing_about_login_when_there_is_nothing_to_fill(monkeypatch):
    config = SimpleNamespace(
        instance_url="https://dev.example.com", auth=SimpleNamespace(browser=None, basic=None)
    )

    result = _open_with_login(monkeypatch, {"status": "no_credentials"}, config)

    assert "auto_login" not in result
    # The original "it may ask for login once" guidance still applies.
    assert "own ServiceNow session" in result["hint"]


def test_a_failed_auto_login_does_not_fail_the_open(monkeypatch):
    config = SimpleNamespace(
        instance_url="https://dev.example.com",
        auth=SimpleNamespace(browser=SimpleNamespace(username="alice", password="s"), basic=None),
    )

    result = _open_with_login(
        monkeypatch, {"status": "error", "error": "connection refused"}, config
    )

    assert result["success"] is True
    assert result["auto_login"] == "error"
    assert "manually" in result["hint"]
