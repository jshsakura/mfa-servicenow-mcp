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

import servicenow_mcp.server as server_module
from servicenow_mcp.browser import _launch_lock, actions, badge
from servicenow_mcp.browser import capture as capture_module
from servicenow_mcp.browser import (
    cursor,
    evaluate,
    impersonate,
    launch_budget,
    login,
    report,
    server_scripts,
    window,
)
from servicenow_mcp.browser.badge import badge_init_script, badge_label, hide_badge_script
from servicenow_mcp.browser.capture import _instance_page
from servicenow_mcp.browser.probe import PROBE_GLOBAL, PROBE_SCRIPT, drain_script, presence_script
from servicenow_mcp.browser.session import describe_window_user
from servicenow_mcp.policies import write_guards
from servicenow_mcp.server import ServiceNowMCP
from servicenow_mcp.tools import browser_debug_tools as tools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeAuthManager:
    """The read-only surface window.py borrows from the frozen class.

    ``instance_url`` and ``config`` are real inputs, not decoration: the window
    key is derived from them, so a double that hardcoded one URL would make two
    different instances look like the same window.
    """

    def __init__(
        self,
        cache_dir: str,
        suffix: str = "dev_example_com_alice",
        instance_url: str = "https://dev.example.com",
        username: str = "alice@example.com",
    ):
        self._cache_dir = cache_dir
        self._suffix = suffix
        self.instance_url = instance_url
        self.config = SimpleNamespace(
            browser=SimpleNamespace(username=username) if username else None,
            basic=None,
        )

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
    dev = FakeAuthManager(str(tmp_path), "dev_example_com_alice", "https://dev.example.com")
    test = FakeAuthManager(str(tmp_path), "test_example_com_alice", "https://test.example.com")

    assert window.window_state_path(dev) != window.window_state_path(test)
    assert window.window_profile_dir(dev) != window.window_profile_dir(test)
    assert window.window_artifacts_dir(dev) != window.window_artifacts_dir(test)


def test_two_accounts_on_one_instance_get_separate_windows(tmp_path):
    """A session is a cookie jar per account — impersonating two people needs two."""
    alice = FakeAuthManager(str(tmp_path), "p_dev", "https://dev.example.com", "alice@example.com")
    bob = FakeAuthManager(str(tmp_path), "p_dev", "https://dev.example.com", "bob@example.com")

    assert window.window_state_path(alice) != window.window_state_path(bob)
    assert window.window_profile_dir(alice) != window.window_profile_dir(bob)


def test_a_profile_label_cannot_split_one_instance_into_two_windows(tmp_path):
    """The bug this fixes: same host, same account, two configs, two windows.

    ``_get_instance_user_suffix`` changes key SHAPE when a profile label exists
    (``{profile}_{host}`` vs ``{host}_{user}``), so a labelled config and a bare
    one pointed at the same instance as the same person never found each other's
    window. Nothing about the window key may depend on that label.
    """
    labelled = FakeAuthManager(
        str(tmp_path), "dev_dev_example_com", "https://dev.example.com", "alice@example.com"
    )
    bare = FakeAuthManager(
        str(tmp_path),
        "dev_example_com_alice_at_example_com",
        "https://dev.example.com",
        "alice@example.com",
    )

    assert labelled._get_instance_user_suffix() != bare._get_instance_user_suffix()
    assert window.window_state_path(labelled) == window.window_state_path(bare)
    assert window.window_profile_dir(labelled) == window.window_profile_dir(bare)
    assert window.window_impersonation_path(labelled) == window.window_impersonation_path(bare)


def test_the_window_key_survives_an_instance_url_it_cannot_parse(tmp_path):
    """No host to key on falls back rather than raising — paths must never throw."""
    broken = FakeAuthManager(str(tmp_path), "fallback_key", "", "alice@example.com")

    assert "fallback_key" in window.window_state_path(broken)


# ---------------------------------------------------------------------------
# Last-attach stamp — the model's half of "is anyone using this?"
# ---------------------------------------------------------------------------


def test_touching_a_window_records_when_and_persists_it(auth):
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=5.0
    )
    window.write_window_state(auth, state)

    stamped = window.touch_window(auth, state)

    assert stamped.last_used_at > state.started_at
    assert window.read_window_state(auth).last_used_at == stamped.last_used_at


def test_reading_a_window_counts_as_using_it(auth, monkeypatch):
    """An inspect every few minutes is active use; the reaper must see it."""
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=5.0
    )
    window.write_window_state(auth, state)
    monkeypatch.setattr(window, "is_window_alive", lambda s: True)

    found = window.find_window(auth)

    assert found.last_used_at > state.started_at


def test_a_state_file_written_before_the_stamp_existed_reads_as_untouched_since_launch(auth):
    """Legacy files must not read as idle since 1970 — that would reap them at once."""
    path = window.window_state_path(auth)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "pid": 7,
                "port": 8,
                "profile_dir": "/tmp/p",
                "instance_url": "https://dev.example.com",
                "started_at": 4242.0,
            },
            handle,
        )

    assert window.read_window_state(auth).last_used_at == 4242.0


# ---------------------------------------------------------------------------
# The probe's human-presence record
# ---------------------------------------------------------------------------


def test_only_trusted_events_stamp_human_presence():
    assert "if (!e || !e.isTrusted) return;" in PROBE_SCRIPT
    assert "lastHuman = Date.now();" in PROBE_SCRIPT


def test_pointer_and_key_events_are_watched_for_presence():
    """A person reading and clicking never types — input events alone would miss them."""
    assert "['input', 'change', 'pointerdown', 'keydown']" in PROBE_SCRIPT


def test_human_presence_survives_a_navigation():
    """Clicking a link IS an interaction; losing it per document inverts the signal."""
    assert "JSON.stringify({ events, seq, lastHuman })" in PROBE_SCRIPT
    assert "lastHuman = parsed.lastHuman || 0;" in PROBE_SCRIPT


def test_presence_reports_the_page_clock_alongside_the_stamp():
    """Both readings come from one clock so the caller never compares across processes."""
    assert "now: Date.now()," in PROBE_SCRIPT
    assert "lastHuman: lastHuman," in PROBE_SCRIPT


def test_presence_is_null_when_the_probe_cannot_answer():
    """An old probe survives an upgrade, and must read as no-evidence, not as empty."""
    assert "(p && p.presence) ? p.presence() : null" in presence_script()


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


def test_the_badge_names_the_profile_so_two_windows_are_distinguishable():
    # NOT the address: the address bar sits directly above the badge, so
    # repeating it spends the whole label on the one fact already on screen.
    assert badge_label("dev") == "MCP DEBUG \u00b7 dev"
    assert "https://" not in badge_init_script("dev")


def test_a_profile_always_draws_the_same_colour():
    """Colour identifies a window across sessions, so it cannot wobble."""
    assert badge.badge_accent("dev") == badge.badge_accent("dev")
    assert badge.badge_accent("DEV") == badge.badge_accent(" dev ")
    assert badge.badge_accent("dev") in badge._PALETTE


def test_names_the_old_keyword_table_could_not_see_get_their_own_colours():
    """The reason the table went: profile names are whatever a person chose.

    Every unrecognized name used to collapse onto one fallback blue, which is
    the badge's own question — "which window is this?" — left unanswered for
    the normal case.
    """
    custom = ["yoko-main", "customer-a", "sandbox2", "aaa", "bbb", "ccc"]
    colours = {name: badge.badge_accent(name) for name in custom}

    assert len(set(colours.values())) > 1, "custom names must not share one colour"


def test_the_meaning_is_in_the_words_not_the_colour():
    """Nothing is reserved, so the name itself has to be on screen — it is.

    A window called prod says so in text whatever colour it happened to draw,
    which is why dropping the reserved red cost nothing.
    """
    script = badge_init_script("prod")

    assert "PROFILE_NAME = 'prod'" in script
    assert badge.badge_accent("prod") in script


def test_the_profile_name_is_the_part_that_carries_the_colour():
    """ "MCP DEBUG" is identical on every window; colouring it answers nothing."""
    script = badge_init_script("dev")

    assert "nameEl.style.cssText" in script
    assert "'color:' + ACCENT" in script
    # The constant half is dimmed rather than tinted, so the name wins the glance.
    assert "text.style.cssText = 'color:rgba(233,233,236,.5)" in script


def test_the_signed_in_user_is_read_in_the_page_not_baked_in():
    # The window has its own session; a name captured when the script was
    # built would go stale the moment someone impersonates.
    script = badge_init_script("dev")

    assert "g_user.userName" in script
    assert "trackUser" in script


def test_the_badge_lives_in_a_closed_shadow_root_so_page_css_cannot_reach_it():
    script = badge_init_script("dev")

    assert "attachShadow({ mode: 'closed' })" in script
    assert "position:fixed" in script
    # The pill itself takes clicks — that is the collapse control. It is the
    # only part of the overlay that does, and it sits in the corner.
    assert "pointer-events:auto" in script
    assert "cursor:pointer" in script


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
    monkeypatch.setattr(tools, "arm", lambda state, **kw: {"armed": True})

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
        tools, "arm", lambda state, profile, **kw: armed_calls.append(profile) or {"armed": True}
    )

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(url="/sp?id=my_page"),
    )

    assert armed_calls == ["default"]
    assert result["recording"] is True


def test_a_window_with_no_tab_reports_that_it_is_not_recording(monkeypatch):
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, True))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda auth_manager: "/tmp/h.json")
    monkeypatch.setattr(tools, "arm", lambda state, **kw: {"armed": False, "reason": "no open tab"})

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
        lambda state, url, profile, allow_discard, new_tab, **kw: {
            "navigated": False,
            "url": "https://dev.example.com/form",
            "blocked_by_unsaved_input": ["short_description"],
            "input_basis": "typed",
        },
    )

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(url="/sp?id=other"),
    )

    assert result["navigated"] is False
    assert result["blocked_by_unsaved_input"] == ["short_description"]
    assert "new_tab=true" in result["hint"]
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
        actions.normalize([{"action": "drag", "selector": "#x"}])

    assert "drag" in str(excinfo.value)
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
    monkeypatch.setattr(tools, "arm", lambda state, **kw: {"armed": True})
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


# ---------------------------------------------------------------------------
# evaluate.py — the read door rejects statements by PARSING, not by pattern
# ---------------------------------------------------------------------------


def test_an_expression_is_compiled_as_an_expression():
    script = evaluate.expression_script("$scope.data.items.length")

    assert "new Function('return (' + src + ')')" in script
    # The source is embedded as a JSON string literal, so it cannot terminate
    # the wrapper and rewrite the surrounding script.
    assert '"$scope.data.items.length"' in script


def test_a_source_string_cannot_break_out_of_the_wrapper():
    # The payload IS in the script — as the contents of a string literal, which
    # is the point. What must not happen is it becoming code in the wrapper.
    source = '"); alert(1); ("'
    script = evaluate.expression_script(source)

    assert json.dumps(source) in script
    # Unescaped, the payload would close the call and add a second one.
    assert "})(" + source + ")" not in script
    assert script.count("new Function") == 1


def test_the_wrapper_survives_every_quote_and_newline_shape():
    for source in ('a\\"b', "a'b", "a\nb", "a\\b", "</script>", "`${x}`"):
        script = evaluate.expression_script(source)
        assert json.dumps(source).replace("</", "<\\/") in script


def test_the_body_door_awaits_so_a_fetch_is_not_reported_as_a_promise():
    script = evaluate.body_script("const r = await fetch('/x'); return r.status;")

    assert "async" in script
    assert "await fn()" in script


def test_a_failed_evaluation_keeps_the_reason_and_says_it_threw():
    out = evaluate.clamp_result({"ok": False, "error": "x is not defined", "threw": True})

    assert out["ok"] is False
    assert out["threw"] is True
    assert "not defined" in out["error"]


def test_a_small_value_comes_back_whole():
    out = evaluate.clamp_result({"ok": True, "value": {"a": 1}, "type": "object"})

    assert out == {"ok": True, "value": {"a": 1}, "type": "object"}


def test_an_oversized_value_is_cut_and_says_so():
    # Silent truncation is the failure mode here: half a value that reads as
    # complete sends the reader to a wrong conclusion.
    out = evaluate.clamp_result({"ok": True, "value": ["x" * 200] * 200, "type": "object"})

    assert out["truncated"] is True
    assert len(out["value"]) == evaluate.MAX_RESULT_CHARS
    assert "Narrow the expression" in out["note"]


def test_an_unserializable_value_degrades_instead_of_raising():
    out = evaluate.clamp_result({"ok": True, "value": {1, 2, 3}, "type": "object"})

    assert out["ok"] is True


def test_a_page_that_refuses_to_evaluate_is_an_error_not_an_exception():
    class Hostile:
        def evaluate(self, script):
            raise RuntimeError("Execution context was destroyed")

    out = evaluate.run_in_page(Hostile(), expression="1+1")

    assert out["ok"] is False
    assert "refused to evaluate" in out["error"]


# ---------------------------------------------------------------------------
# The eval action — write-classified AND separately approved
# ---------------------------------------------------------------------------


def test_eval_needs_a_source():
    with pytest.raises(ValueError) as excinfo:
        actions.normalize([{"action": "eval"}])

    assert "value" in str(excinfo.value)


def test_eval_needs_no_selector():
    normalized = actions.normalize([{"action": "eval", "value": "return 1"}])

    assert normalized[0]["selector"] is None


def test_an_eval_step_runs_the_source_and_returns_the_described_value():
    class Evaluating(FakePage):
        def __init__(self):
            super().__init__(known=[])
            self.scripts = []

        def evaluate(self, script):
            self.scripts.append(script)
            return {"ok": True, "value": 42, "type": "number"}

    page = Evaluating()
    out = actions._run_step(page, _step(action="eval", selector=None, value="return 42"), 1)

    assert out["result"] == {"ok": True, "value": 42, "type": "number"}
    assert "return 42" in page.scripts[0]


def test_an_eval_that_throws_fails_the_step_with_the_page_error():
    class Throwing(FakePage):
        def evaluate(self, script):
            return {"ok": False, "error": "g_form is not defined", "threw": True}

    with pytest.raises(actions.ActionError) as excinfo:
        actions._run_step(
            Throwing(known=[]), _step(action="eval", selector=None, value="g_form.x"), 2
        )

    assert "g_form is not defined" in str(excinfo.value)
    assert excinfo.value.index == 2


def test_running_code_needs_its_own_approval_on_top_of_the_tools(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("must not reach the window without confirm_eval")

    monkeypatch.setattr(tools, "find_window", _explode)

    result = tools.act_in_debug_window(
        MagicMock(),
        MagicMock(),
        tools.ActInDebugWindowParams(
            actions=[
                {"action": "click", "selector": "#x"},
                {"action": "eval", "value": "return 1"},
            ]
        ),
    )

    assert result["success"] is False
    assert result["eval_steps"] == [2]
    assert "confirm_eval='approve'" in result["error"]


def test_an_approved_eval_batch_proceeds(monkeypatch, tmp_path):
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        tools,
        "act",
        lambda state, **kw: {
            "url": "https://dev.example.com/sp",
            "seq": 1,
            "events": [],
            "steps": [
                {"step": 1, "action": "eval", "ok": True, "result": {"ok": True, "value": 3}}
            ],
            "dialogs": [],
            "failed_step": None,
            "skipped": 0,
        },
    )

    result = tools.act_in_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.ActInDebugWindowParams(
            actions=[{"action": "eval", "value": "return 3"}], confirm_eval="approve"
        ),
    )

    assert result["success"] is True
    assert result["steps"][0]["result"]["value"] == 3


def test_a_batch_with_no_eval_needs_no_extra_approval(monkeypatch, tmp_path):
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        tools,
        "act",
        lambda state, **kw: {
            "url": "https://dev.example.com/sp",
            "seq": 1,
            "events": [],
            "steps": [{"step": 1, "action": "click", "ok": True}],
            "dialogs": [],
            "failed_step": None,
            "skipped": 0,
        },
    )

    result = tools.act_in_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.ActInDebugWindowParams(actions=[{"action": "click", "selector": "#x"}]),
    )

    assert result["success"] is True


# ---------------------------------------------------------------------------
# Reading with evaluate — a read tool that can run code is gated as a write
# ---------------------------------------------------------------------------


def test_inspecting_with_an_expression_returns_its_value(monkeypatch, tmp_path):
    state = _state()
    seen = {}
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))

    def _capture(state, **kw):
        seen.update(kw)
        return {
            "url": "https://dev.example.com/sp",
            "seq": 1,
            "events": [],
            "evaluation": {"ok": True, "value": 12, "type": "number"},
        }

    monkeypatch.setattr(tools, "capture", _capture)

    result = tools.inspect_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.InspectDebugWindowParams(evaluate="$scope.data.items.length"),
    )

    assert seen["evaluate_expression"] == "$scope.data.items.length"
    assert result["evaluation"]["value"] == 12


def test_a_plain_inspect_carries_no_evaluation_key(monkeypatch, tmp_path):
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        tools,
        "capture",
        lambda state, **kw: {"url": "u", "seq": 1, "events": [], "evaluation": None},
    )

    result = tools.inspect_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.InspectDebugWindowParams(),
    )

    assert "evaluation" not in result


def test_evaluate_flips_the_read_tool_to_a_write():
    # `fetch(...)` is an expression. The read door cannot be promised
    # side-effect-free, so allow_writes=false has to be able to refuse it.
    assert write_guards._is_read_only("inspect_debug_window", {}) is True
    assert write_guards._is_read_only("inspect_debug_window", {"evaluate": "1+1"}) is False
    assert write_guards._is_read_only("inspect_debug_window", {"evaluate": ""}) is True


def test_both_classifiers_read_the_same_table():
    # The scaffold_page bug was two hand-mirrored tables drifting. This one is
    # consulted from server._is_read_only_call and write_guards._is_read_only.
    assert server_module.is_arg_triggered_write is write_guards.is_arg_triggered_write
    assert (
        ServiceNowMCP._is_read_only_call(ServiceNowMCP, "inspect_debug_window", {"evaluate": "1+1"})
        is False
    )


# ---------------------------------------------------------------------------
# Unsaved input: what a human typed vs what a widget filled in
# ---------------------------------------------------------------------------


def test_the_probe_records_only_trusted_input():
    # `isTrusted` is the browser's own "a human did this". Comparing against
    # defaultValue cannot tell a keystroke from `el.value = x`, which is why
    # every ng-model-bound field on a portal page read as half-typed.
    assert "e.isTrusted" in PROBE_SCRIPT
    assert "touched.add" in PROBE_SCRIPT


def test_the_probe_knows_whether_it_saw_the_document_from_the_start():
    # Injected into an already-loaded page, an empty touched set is not
    # evidence that nothing was typed — only that nothing was watched.
    assert "document.readyState !== 'loading'" in PROBE_SCRIPT
    assert "observedFromStart" in PROBE_SCRIPT


def test_typed_fields_are_reported_as_observed():
    class Page:
        def evaluate(self, script):
            return {"fields": ["short_description"], "observedFromStart": True}

    fields, basis = capture_module._dirty_fields(Page())

    assert fields == ["short_description"]
    assert basis == "typed"


def test_a_late_armed_probe_reports_partial_confidence():
    class Page:
        def evaluate(self, script):
            return {"fields": [], "observedFromStart": False}

    assert capture_module._dirty_fields(Page())[1] == "partial"


def test_without_the_probe_the_answer_is_labelled_a_guess():
    # This is the path that produced the false alarm on c.data.requestType.
    class Page:
        def __init__(self):
            self.calls = 0

        def evaluate(self, script):
            self.calls += 1
            return None if self.calls == 1 else ["c.data.requestType"]

    fields, basis = capture_module._dirty_fields(Page())

    assert fields == ["c.data.requestType"]
    assert basis == "guessed"


def test_a_page_that_cannot_be_probed_never_blocks_navigation():
    class Hostile:
        def evaluate(self, script):
            raise RuntimeError("context destroyed")

    assert capture_module._dirty_fields(Hostile()) == ([], "guessed")


def test_a_guess_steps_aside_into_a_new_tab_instead_of_refusing(monkeypatch):
    # A shared window that answers "no" to every navigation is not shared, it is
    # broken: the portal landing page reports eight fields nobody touched. The
    # guess now opens a tab beside them and says why.
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, False))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda a: "/tmp/h.json")
    monkeypatch.setattr(tools, "arm", lambda state, **kw: {"armed": True})
    monkeypatch.setattr(tools, "auto_login", lambda state, **kw: {"status": "no_credentials"})
    monkeypatch.setattr(tools, "window_login_path", lambda a: "/tmp/l.json")
    monkeypatch.setattr(
        tools,
        "navigate",
        lambda state, url, profile, allow_discard, new_tab, **kw: {
            "navigated": True,
            "url": "https://dev.example.com/sp?id=other",
            "new_tab": True,
            "tabs": 2,
            "kept_input": ["c.data.requestType", "request_date_from"],
            "input_basis": "guessed",
        },
    )

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(url="/sp?id=other"),
    )

    assert result["new_tab"] is True
    assert "2 field(s)" in result["opened_beside"]
    assert "discard_unsaved_input" in result["opened_beside"]


def test_observed_typing_still_refuses(monkeypatch):
    # The guess steps aside; a real person's keystrokes do not get stepped on.
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, False))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda a: "/tmp/h.json")
    monkeypatch.setattr(
        tools,
        "navigate",
        lambda state, url, profile, allow_discard, new_tab, **kw: {
            "navigated": False,
            "url": "https://dev.example.com/form",
            "blocked_by_unsaved_input": ["short_description"],
            "input_basis": "typed",
        },
    )

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(url="/sp?id=other"),
    )

    assert result["navigated"] is False
    assert result["input_basis"] == "typed"
    assert "Someone typed" in result["hint"]


def test_a_new_tab_leaves_the_form_alone(monkeypatch):
    # The answer to the block, not a way around it: the half-filled form stays
    # open in its tab while the page being checked loads beside it.
    state = window.WindowState(
        pid=1, port=2, profile_dir="/tmp/p", instance_url="https://dev.example.com", started_at=0.0
    )
    seen = {}
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, False))
    monkeypatch.setattr(tools, "budget_status", lambda path: (1, 6))
    monkeypatch.setattr(tools, "window_history_path", lambda a: "/tmp/h.json")
    monkeypatch.setattr(tools, "arm", lambda state, **kw: {"armed": True})
    monkeypatch.setattr(tools, "auto_login", lambda state, **kw: {"status": "no_credentials"})
    monkeypatch.setattr(tools, "window_login_path", lambda a: "/tmp/l.json")

    def _navigate(state, url, profile, allow_discard, new_tab, **kw):
        seen.update({"new_tab": new_tab, "allow_discard": allow_discard})
        return {"navigated": True, "url": url, "new_tab": True, "tabs": 2}

    monkeypatch.setattr(tools, "navigate", _navigate)

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.OpenDebugWindowParams(url="/sp?id=other", new_tab=True),
    )

    assert seen["new_tab"] is True
    # Never needs to discard: nothing is being navigated away from.
    assert seen["allow_discard"] is False
    assert result["new_tab"] is True
    assert result["tabs"] == 2


# ---------------------------------------------------------------------------
# The activity dot — "was that me or the model?"
# ---------------------------------------------------------------------------


def test_the_ring_is_the_environment_and_the_fill_is_activity():
    # Two signals on one dot, so neither has to be given up: the environment
    # must stay legible AT REST, which is when "I thought this was dev" happens.
    script = badge_init_script("prod")

    assert badge.IDLE_COLOUR in script, "at rest the fill is neutral grey"
    assert badge.badge_accent("prod") in script, "the ring still identifies the window"
    assert "snmcp-pulse" in script


def test_the_dot_reverts_on_its_own_if_a_call_dies_mid_flight():
    # A light that is always on stops being a light.
    script = badge_init_script("dev")

    assert f"setActive(false), {int(badge.ACTIVE_TTL_S * 1000)}" in script


def test_activity_can_be_lit_and_cleared():
    assert "setActive(true)" in badge.badge_activity_script(True)
    assert "setActive(false)" in badge.badge_activity_script(False)


def test_lighting_a_badge_that_was_never_mounted_is_a_no_op():
    # Injected into a page the badge never reached, this must not throw and
    # take the surrounding read down with it.
    assert "ref && ref.setActive" in badge.badge_activity_script(True)


def test_a_page_that_refuses_the_activity_script_does_not_fail_the_read():
    class Hostile:
        def evaluate(self, script):
            raise RuntimeError("context destroyed")

    capture_module._set_activity(Hostile(), True)  # must not raise


# ---------------------------------------------------------------------------
# Impersonation — one window, one session, every MCP session sharing it
# ---------------------------------------------------------------------------


class FakeSessionPage(FakePage):
    """A page that answers the three scripts impersonation runs against it."""

    def __init__(
        self,
        user="alice",
        url="https://dev.example.com/nav_to.do",
        response=None,
        becomes=None,
        dirty=(),
        impersonating=None,
    ):
        super().__init__(known=[], url=url)
        self.user = user
        self.impersonating = impersonating
        self.becomes = becomes
        self.dirty = list(dirty)
        self.response = (
            response
            if response is not None
            else {"sent": True, "ok": True, "status": 200, "had_token": True, "body": ""}
        )
        self.posts = []
        self.reloads = 0

    def evaluate(self, script):
        if "/api/now/ui/impersonate/" in script:
            self.posts.append(script)
            return {"ok": True, "value": self.response, "type": "object"}
        if "p.dirty()" in script:
            return {"fields": self.dirty, "observedFromStart": True}
        if not self.user:
            return None
        return {"user": self.user, "source": "g_user", "impersonating": self.impersonating}

    def reload(self, wait_until=None, timeout=None):
        self.reloads += 1
        if self.becomes is not None:
            self.user = self.becomes


def _marker(tmp_path):
    return str(tmp_path / "impersonation.json")


def test_impersonate_needs_a_user_to_become():
    with pytest.raises(ValueError) as excinfo:
        actions.normalize([{"action": "impersonate"}])

    assert "value" in str(excinfo.value)


def test_ending_an_impersonation_needs_no_arguments():
    normalized = actions.normalize([{"action": "end_impersonation"}])

    assert normalized[0]["selector"] is None and normalized[0]["value"] is None


def test_a_session_step_gets_twice_the_budget_because_it_reloads_and_verifies():
    plain = actions.budget_seconds(actions.normalize([{"action": "click", "selector": "#x"}]))
    session = actions.budget_seconds(
        actions.normalize([{"action": "impersonate", "value": "abel.tuter"}])
    )

    assert session > plain


def test_a_marker_from_a_closed_window_cannot_describe_the_next_one(tmp_path):
    path = _marker(tmp_path)
    impersonate.write_marker(path, started_at=100.0, original="alice", impersonated="bob")

    assert impersonate.read_marker(path, 100.0)["as"] == "bob"
    # A new window is a new session, signed in as itself.
    assert impersonate.read_marker(path, 200.0) is None


def test_impersonating_from_a_page_that_is_not_the_instance_is_refused():
    page = FakeSessionPage(url="https://example.org/other")

    out = impersonate.become(
        page, target="bob", marker_path="", started_at=1.0, instance_host="dev.example.com"
    )

    assert out["ok"] is False
    assert "example.org" in out["error"]
    # Never fired: a relative POST would have gone to the wrong origin.
    assert page.posts == []


def test_switching_user_refuses_to_reload_a_form_holding_unsaved_input(tmp_path):
    page = FakeSessionPage(dirty=["short_description"], becomes="bob")

    out = impersonate.become(page, target="bob", marker_path=_marker(tmp_path), started_at=1.0)

    assert out["ok"] is False
    assert out["blocked_by_unsaved_input"] == ["short_description"]
    assert "discard_unsaved_input=true" in out["error"]
    assert page.posts == [] and page.reloads == 0


def test_discarding_is_explicit_and_then_the_switch_proceeds(tmp_path):
    page = FakeSessionPage(dirty=["short_description"], becomes="bob")

    out = impersonate.become(
        page,
        target="bob",
        marker_path=_marker(tmp_path),
        started_at=1.0,
        allow_discard=True,
    )

    assert out["ok"] is True and out["now"] == "bob"


def test_a_missing_role_is_reported_as_the_missing_role(tmp_path):
    page = FakeSessionPage(
        response={"sent": True, "ok": False, "status": 403, "had_token": True, "body": ""}
    )

    out = impersonate.become(page, target="bob", marker_path=_marker(tmp_path), started_at=1.0)

    assert out["ok"] is False
    assert "impersonator" in out["error"]


def test_an_unknown_user_says_to_pass_a_user_name_not_a_display_name(tmp_path):
    page = FakeSessionPage(
        response={"sent": True, "ok": False, "status": 404, "had_token": True, "body": ""}
    )

    out = impersonate.become(
        page, target="Bob Smith", marker_path=_marker(tmp_path), started_at=1.0
    )

    assert out["ok"] is False
    assert "user_name" in out["error"]


def test_the_page_is_the_verdict_not_the_http_status(tmp_path):
    # 200 with an unchanged session is a failed impersonation, however the
    # instance chose to answer.
    page = FakeSessionPage(user="alice", becomes="alice")

    out = impersonate.become(page, target="bob", marker_path=_marker(tmp_path), started_at=1.0)

    assert out["ok"] is False
    assert "still 'alice'" in out["error"]


def test_a_successful_switch_reloads_the_same_page_rather_than_navigating(tmp_path):
    page = FakeSessionPage(user="alice", becomes="bob", url="https://dev.example.com/sp?id=form")

    out = impersonate.become(
        page,
        target="bob",
        marker_path=_marker(tmp_path),
        started_at=1.0,
        instance_host="dev.example.com",
    )

    assert out["ok"] is True and out["before"] == "alice" and out["now"] == "bob"
    assert page.reloads == 1
    assert out["url"] == "https://dev.example.com/sp?id=form"


def test_the_switch_records_who_to_go_back_to(tmp_path):
    path = _marker(tmp_path)
    page = FakeSessionPage(user="alice", becomes="bob")

    impersonate.become(page, target="bob", marker_path=path, started_at=7.0)

    assert impersonate.read_marker(path, 7.0) == {
        "started_at": 7.0,
        "original": "alice",
        "as": "bob",
        "at": pytest.approx(time.time(), abs=30),
    }


def test_hopping_between_users_still_points_home_to_the_real_account(tmp_path):
    path = _marker(tmp_path)
    page = FakeSessionPage(user="alice", becomes="bob")
    impersonate.become(page, target="bob", marker_path=path, started_at=7.0)

    page.becomes = "carol"
    impersonate.become(page, target="carol", marker_path=path, started_at=7.0)

    # Not 'bob' — end_impersonation must land on the account that signed in.
    assert impersonate.read_marker(path, 7.0)["original"] == "alice"


def test_any_session_can_end_what_another_session_started(tmp_path):
    path = _marker(tmp_path)
    impersonate.write_marker(path, started_at=7.0, original="alice", impersonated="bob")
    page = FakeSessionPage(user="bob", becomes="alice")

    out = impersonate.restore(page, marker_path=path, started_at=7.0)

    assert out["ok"] is True and out["now"] == "alice"
    assert impersonate.read_marker(path, 7.0) is None


def test_a_hand_made_impersonation_falls_back_to_the_signed_in_account(tmp_path):
    # No marker: the user clicked the avatar menu themselves.
    page = FakeSessionPage(user="bob", becomes="alice")

    out = impersonate.restore(
        page, marker_path=_marker(tmp_path), started_at=7.0, fallback_user="alice"
    )

    assert out["ok"] is True and out["now"] == "alice"


def test_with_nothing_to_go_back_to_it_says_so_instead_of_guessing(tmp_path):
    page = FakeSessionPage(user="bob")

    out = impersonate.restore(page, marker_path=_marker(tmp_path), started_at=7.0)

    assert out["ok"] is False
    assert "records the account it signed in as" in out["error"]


def test_ending_when_already_home_is_a_no_op_that_clears_the_marker(tmp_path):
    path = _marker(tmp_path)
    impersonate.write_marker(path, started_at=7.0, original="alice", impersonated="bob")
    page = FakeSessionPage(user="alice")

    out = impersonate.restore(page, marker_path=path, started_at=7.0)

    assert out["ok"] is True and out["already"] is True
    assert page.posts == []
    assert impersonate.read_marker(path, 7.0) is None


def test_the_page_wins_over_a_stale_marker():
    marker = {"as": "bob", "original": "alice"}

    assert impersonate.describe(marker, "bob") == {"as": "bob", "original": "alice"}
    # Ended by hand in the window: reporting 'bob' would send the next
    # investigation after the wrong account.
    assert impersonate.describe(marker, "alice") is None
    assert impersonate.describe(None, "bob") is None


def test_a_session_step_makes_the_batch_report_who_the_window_now_is(monkeypatch, tmp_path):
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(tools, "window_impersonation_path", lambda a: _marker(tmp_path))
    seen = {}

    def _act(state, **kw):
        seen.update(kw)
        return {
            "url": "https://dev.example.com/sp",
            "seq": 1,
            "events": [],
            "steps": [{"step": 1, "action": "impersonate", "ok": True, "impersonating": "bob"}],
            "dialogs": [],
            "failed_step": None,
            "skipped": 0,
            "effective_user": {"user": "bob", "source": "g_user"},
        }

    monkeypatch.setattr(tools, "act", _act)

    result = tools.act_in_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com", auth=SimpleNamespace()),
        MagicMock(),
        tools.ActInDebugWindowParams(actions=[{"action": "impersonate", "value": "bob"}]),
    )

    assert result["window_user"] == "bob"
    assert "every MCP session" in result["session_note"]
    # The tool layer resolves the window-scoped context; actions.py stays dumb.
    assert seen["session"]["marker_path"] == _marker(tmp_path)
    assert seen["session"]["instance_host"] == "dev.example.com"
    assert seen["session"]["started_at"] == state.started_at


def test_impersonation_needs_no_second_approval_the_way_eval_does(monkeypatch, tmp_path):
    # Deliberate: it cannot run code, cannot exceed the account's roles, cannot
    # touch the API session, and one step undoes it.
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(tools, "window_impersonation_path", lambda a: _marker(tmp_path))
    monkeypatch.setattr(
        tools,
        "act",
        lambda state, **kw: {
            "url": "u",
            "seq": 1,
            "events": [],
            "steps": [{"step": 1, "action": "impersonate", "ok": True}],
            "dialogs": [],
            "failed_step": None,
            "skipped": 0,
            "effective_user": {"user": "bob"},
        },
    )

    result = tools.act_in_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com", auth=SimpleNamespace()),
        MagicMock(),
        tools.ActInDebugWindowParams(actions=[{"action": "impersonate", "value": "bob"}]),
    )

    assert result["success"] is True


def test_a_read_reports_an_impersonation_another_session_started(monkeypatch, tmp_path):
    state = _state()
    impersonate.write_marker(
        _marker(tmp_path), started_at=state.started_at, original="alice", impersonated="bob"
    )
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(tools, "window_impersonation_path", lambda a: _marker(tmp_path))
    monkeypatch.setattr(
        tools,
        "capture",
        lambda state, **kw: {
            "url": "u",
            "seq": 1,
            "events": [],
            "effective_user": {"user": "bob", "source": "g_user"},
        },
    )

    result = tools.inspect_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com", auth=SimpleNamespace()),
        MagicMock(),
        tools.InspectDebugWindowParams(),
    )

    assert result["impersonating"] == {"as": "bob", "original": "alice"}


def test_opening_says_up_front_when_it_reuses_an_impersonating_window(monkeypatch, tmp_path):
    state = _state()
    impersonate.write_marker(
        _marker(tmp_path), started_at=state.started_at, original="alice", impersonated="bob"
    )
    monkeypatch.setattr(tools, "ensure_window", lambda auth_manager, **kw: (state, False))
    monkeypatch.setattr(tools, "arm", lambda state, **kw: {"armed": True})
    monkeypatch.setattr(tools, "auto_login", lambda state, **kw: {"status": "no_credentials"})
    monkeypatch.setattr(tools, "window_history_path", lambda a: str(tmp_path / "h.json"))
    monkeypatch.setattr(tools, "window_login_path", lambda a: str(tmp_path / "l.json"))
    monkeypatch.setattr(tools, "window_impersonation_path", lambda a: _marker(tmp_path))

    result = tools.open_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com", auth=SimpleNamespace()),
        MagicMock(),
        tools.OpenDebugWindowParams(),
    )

    assert result["impersonating"]["as"] == "bob"
    assert "end_impersonation" in result["impersonation_note"]


# ---------------------------------------------------------------------------
# The badge — always up, says who you are pretending to be, folds away
# ---------------------------------------------------------------------------


def test_the_badge_draws_an_impersonation_as_account_arrow_user():
    script = badge_init_script("dev", "alice")

    assert "const ACCOUNT = 'alice'" in script
    # account → user, in the "not the normal state" colour.
    assert "ACCOUNT + ' \\u2192 ' + user" in script
    assert badge.IMPERSONATING_COLOUR in script


def test_without_a_known_account_the_badge_just_names_whoever_is_signed_in():
    # An OAuth or API-key profile has no browser username to compare against;
    # inventing one would label every session an impersonation.
    script = badge_init_script("dev")

    assert "const ACCOUNT = ''" in script


def test_the_badge_puts_itself_back_when_the_page_re_renders_it_away():
    script = badge_init_script("dev")

    assert "root.contains(host)" in script
    assert f"}}, {badge.KEEPALIVE_MS})" in script


def test_the_badge_collapses_on_a_click_and_remembers_it_across_reloads():
    script = badge_init_script("dev")

    assert "wrap.addEventListener('click'" in script
    assert badge.COLLAPSED_KEY in script
    assert "localStorage.setItem(COLLAPSED_KEY" in script


def test_a_collapsed_badge_still_shows_the_environment_and_the_activity():
    # Folding away the names must not fold away the two signals nobody should
    # have to ask about.
    script = badge_init_script("dev")

    collapse_block = script[script.index("const paint = ") : script.index("const setCollapsed")]
    assert "dot" not in collapse_block
    assert "text.style.display" in collapse_block


def test_a_name_arriving_late_does_not_reopen_a_collapsed_badge():
    script = badge_init_script("dev")

    assert "trackUser(sep, userEl, paint)" in script


def test_the_account_the_badge_compares_against_survives_the_impersonation(tmp_path):
    # While impersonating, the page no longer knows the real account — the
    # marker does, and it has to win over the config for the badge to keep
    # drawing 'alice → bob' instead of deciding bob is the account.
    state = _state()
    impersonate.write_marker(
        _marker(tmp_path), started_at=state.started_at, original="alice", impersonated="bob"
    )
    config = SimpleNamespace(
        auth=SimpleNamespace(browser=SimpleNamespace(username="alice", password="x"))
    )

    class Auth(FakeAuthManager):
        pass

    auth_manager = Auth(str(tmp_path))
    original = tools.window_impersonation_path
    try:
        tools.window_impersonation_path = lambda a: _marker(tmp_path)
        assert tools._window_account(config, auth_manager, state) == "alice"
    finally:
        tools.window_impersonation_path = original


# ---------------------------------------------------------------------------
# Mixing the avatar menu with the tool — the live bug this pins
# ---------------------------------------------------------------------------


def test_the_user_we_go_home_to_is_never_one_we_were_pretending_to_be(tmp_path):
    # Found on a live instance: the user impersonated 'heejin' by hand, the tool
    # then impersonated 'carol', and end_impersonation went back to heejin —
    # a user nobody had ever signed in as. The page said so all along.
    path = _marker(tmp_path)
    page = FakeSessionPage(user="heejin", becomes="carol", impersonating=True)

    impersonate.become(page, target="carol", marker_path=path, started_at=3.0, login_user="alice")

    assert impersonate.read_marker(path, 3.0)["original"] == "alice"


def test_when_the_page_says_this_is_the_real_account_that_is_the_account(tmp_path):
    path = _marker(tmp_path)
    page = FakeSessionPage(user="alice", becomes="bob", impersonating=False)

    impersonate.become(page, target="bob", marker_path=path, started_at=3.0, login_user="ignored")

    assert impersonate.read_marker(path, 3.0)["original"] == "alice"


def test_a_hand_made_impersonation_is_reported_even_with_no_marker():
    detected = {"user": "bob", "source": "g_user", "impersonating": True}

    assert impersonate.describe_detected(detected, None) == {"as": "bob", "original": None}


def test_the_page_saying_this_is_the_real_account_beats_a_stale_marker():
    marker = {"as": "bob", "original": "alice"}
    detected = {"user": "alice", "source": "g_user", "impersonating": False}

    assert impersonate.describe_detected(detected, marker) is None


def test_a_page_that_does_not_expose_the_flag_falls_back_to_the_marker():
    marker = {"as": "bob", "original": "alice"}
    detected = {"user": "bob", "source": "g_user", "impersonating": None}

    assert impersonate.describe_detected(detected, marker) == {"as": "bob", "original": "alice"}


def test_ending_a_hand_made_impersonation_uses_the_configured_account(tmp_path):
    page = FakeSessionPage(user="heejin", becomes="alice", impersonating=True)

    out = impersonate.restore(
        page, marker_path=_marker(tmp_path), started_at=3.0, fallback_user="alice"
    )

    assert out["ok"] is True and out["now"] == "alice"


def test_the_effective_user_script_reads_the_platform_impersonation_flag():
    # Measured on a live instance: NOW.user_impersonating is true while
    # impersonating, on a portal page where NOW.user and g_user are both absent.
    from servicenow_mcp.browser.session import EFFECTIVE_USER_SCRIPT

    assert "user_impersonating" in EFFECTIVE_USER_SCRIPT


# ---------------------------------------------------------------------------
# Crash marks — why a reopened window came back with two of the same tab
# ---------------------------------------------------------------------------


def _prefs(profile_dir, payload):
    default = os.path.join(profile_dir, "Default")
    os.makedirs(default, exist_ok=True)
    path = os.path.join(default, "Preferences")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def test_a_crash_mark_is_cleared_so_no_tab_is_restored(tmp_path):
    # Closing by signal (stop_window, the reaper) is what Chromium records as a
    # crash — measured on a real profile: exit_type "Crashed", and the next
    # launch showed the restored tab AND the url we passed on the command line.
    profile = str(tmp_path / "profile")
    path = _prefs(profile, {"profile": {"exit_type": "Crashed"}, "other": {"keep": 1}})

    assert window.clear_restore_state(profile) is True

    saved = json.load(open(path))
    assert saved["profile"]["exit_type"] == "Normal"
    assert saved["profile"]["exited_cleanly"] is True
    # Everything else in that file belongs to Chromium, not to us.
    assert saved["other"] == {"keep": 1}


def test_a_clean_profile_is_left_untouched(tmp_path):
    profile = str(tmp_path / "profile")
    _prefs(profile, {"profile": {"exit_type": "Normal", "exited_cleanly": True}})

    assert window.clear_restore_state(profile) is False


def test_a_profile_that_never_ran_has_nothing_to_clear(tmp_path):
    assert window.clear_restore_state(str(tmp_path / "never")) is False


def test_unreadable_preferences_never_stop_a_window_from_opening(tmp_path):
    profile = str(tmp_path / "profile")
    os.makedirs(os.path.join(profile, "Default"))
    with open(os.path.join(profile, "Default", "Preferences"), "w") as handle:
        handle.write("{not json")

    assert window.clear_restore_state(profile) is False


def test_the_restore_bubble_can_never_cover_the_shared_page():
    args = window._launch_args(
        port=1, profile_dir="/tmp/p", viewport=(800, 600), url="https://x.test"
    )

    assert "--hide-crash-restore-bubble" in args


def test_the_session_files_chromium_restores_from_are_removed(tmp_path):
    # The measured cause: Sessions/Session_* and Tabs_* survive a signal-close,
    # so the next launch restores that tab and adds the one it was asked for —
    # two, then three, growing by one per cycle.
    profile = tmp_path / "profile"
    sessions = profile / "Default" / "Sessions"
    sessions.mkdir(parents=True)
    (sessions / "Session_13429694818788795").write_bytes(b"x")
    (sessions / "Tabs_13429694819516645").write_bytes(b"x")
    (profile / "Default" / "Last Session").write_bytes(b"x")
    cookies = profile / "Default" / "Cookies"
    cookies.write_bytes(b"sqlite")

    assert window.clear_restore_state(str(profile)) is True

    assert list(sessions.iterdir()) == []
    assert not (profile / "Default" / "Last Session").exists()
    # The signed-in session is the whole reason a reopen is silent. Never ours
    # to delete.
    assert cookies.read_bytes() == b"sqlite"


# ---------------------------------------------------------------------------
# Which tab do we continue in? The one someone was working in.
# ---------------------------------------------------------------------------


class PresencePage:
    """A tab that answers the probe's presence question with a stamp."""

    def __init__(self, url, last_human=None):
        self.url = url
        self.last_human = last_human

    def evaluate(self, script):
        if "presence" in script:
            if self.last_human is None:
                return None  # unarmed document: no say
            return {"lastHuman": self.last_human, "now": 9_000.0}
        return None


def test_with_one_tab_nothing_is_asked():
    only = PresencePage("https://dev.example.com/sp")

    assert capture_module._active_instance_page([only], "dev.example.com") is only


def test_the_tab_last_worked_in_wins_over_the_first_one():
    # A new tab opened beside a form would otherwise leave the model reading the
    # old page while the person looks at the new one.
    old = PresencePage("https://dev.example.com/sp", last_human=1000.0)
    new = PresencePage("https://dev.example.com/incident_list.do", last_human=8000.0)

    assert capture_module._active_instance_page([old, new], "dev.example.com") is new


def test_tabs_off_the_instance_are_never_chosen_over_one_on_it():
    off = PresencePage("https://docs.example.org/guide", last_human=9999.0)
    on = PresencePage("https://dev.example.com/sp", last_human=1.0)

    assert capture_module._active_instance_page([off, on], "dev.example.com") is on


def test_when_no_tab_can_answer_the_first_instance_tab_is_used():
    # An unarmed document is not a reason to pick the wrong page.
    first = PresencePage("https://dev.example.com/sp")
    second = PresencePage("https://dev.example.com/other")

    assert capture_module._active_instance_page([first, second], "dev.example.com") is first


def test_a_tab_that_refuses_to_answer_does_not_break_the_choice():
    class Hostile(PresencePage):
        def evaluate(self, script):
            raise RuntimeError("execution context destroyed")

    hostile = Hostile("https://dev.example.com/a")
    answering = PresencePage("https://dev.example.com/b", last_human=42.0)

    assert (
        capture_module._active_instance_page([hostile, answering], "dev.example.com") is answering
    )


def test_devtools_tabs_are_still_never_selected():
    devtools = PresencePage("devtools://devtools/bundled/inspector.html", last_human=9999.0)
    real = PresencePage("https://dev.example.com/sp", last_human=1.0)

    assert capture_module._active_instance_page([devtools, real], "dev.example.com") is real


class ArmablePage:
    def __init__(self, url, hostile=False):
        self.url = url
        self.hostile = hostile
        self.scripts = []

    def evaluate(self, script):
        if self.hostile:
            raise RuntimeError("execution context destroyed")
        self.scripts.append(script)
        return None


def test_every_instance_tab_gets_the_probe_not_just_the_chosen_one(auth):
    # The circle this breaks: no probe -> no say in which tab is being worked
    # in -> never chosen -> never armed.
    state = window.WindowState(
        pid=1, port=2, profile_dir="/p", instance_url="https://dev.example.com", started_at=0.0
    )
    tabs = [
        ArmablePage("https://dev.example.com/sp"),
        ArmablePage("https://dev.example.com/incident_list.do"),
        ArmablePage("https://docs.example.org/guide"),
        ArmablePage("devtools://devtools/bundled/inspector.html"),
    ]

    armed = capture_module._arm_tabs(tabs, state, "dev")

    assert armed == 2
    assert tabs[0].scripts and tabs[1].scripts
    # Someone's unrelated reading and the devtools window are not ours to touch.
    assert tabs[2].scripts == [] and tabs[3].scripts == []


def test_a_tab_that_refuses_the_probe_does_not_stop_the_others(auth):
    state = window.WindowState(
        pid=1, port=2, profile_dir="/p", instance_url="https://dev.example.com", started_at=0.0
    )
    tabs = [
        ArmablePage("https://dev.example.com/a", hostile=True),
        ArmablePage("https://dev.example.com/b"),
    ]

    assert capture_module._arm_tabs(tabs, state, "dev") == 1
    assert tabs[1].scripts


# ---------------------------------------------------------------------------
# server_scripts.py — running server-side code is not a click
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,surface",
    [
        ("https://dev.example.com/sys.scripts.do", "Background Scripts"),
        ("https://dev.example.com/nav_to.do?uri=sys_script_fix.do%3Fsys_id%3Dab", "Fix Script"),
        # A gate an encoder walks through is not a gate.
        ("https://dev.example.com/nav_to.do?uri=%2Fsys.scripts.do", "Background Scripts"),
        ("https://dev.example.com/SYS.SCRIPTS.DO", "Background Scripts"),
        ("https://dev.example.com/sysauto_script.do?sys_id=1", "Scheduled Script Execution"),
    ],
)
def test_a_script_runner_page_is_recognised_however_it_is_addressed(url, surface):
    assert server_scripts.surface_for_url(url) == surface


def test_an_ordinary_page_is_not_a_script_runner():
    assert server_scripts.surface_for_url("https://dev.example.com/incident.do?sys_id=1") is None
    assert server_scripts.surface_for_url("") is None


def test_the_run_verb_is_recognised_without_any_url():
    # A Fix Script run from a list view's context menu never loads its form,
    # so the URL half of the check has nothing to look at.
    assert server_scripts.surface_for_step(_step(selector="text=Run Fix Script")) == "Fix Script"
    assert server_scripts.surface_for_step(_step(selector='input[name="runscript"]')) == (
        "Background Scripts"
    )


def test_typing_a_script_is_not_running_one():
    # fill has to stay free: showing the user what you want run is the outcome
    # this gate is asking for.
    assert server_scripts.surface_for_step(_step(action="fill", value="gs.info('x')")) is None


def test_an_activating_step_on_a_script_runner_fails_that_step(monkeypatch):
    page = FakePage(known=["#run"], url="https://dev.example.com/sys.scripts.do")

    with pytest.raises(actions.ActionError) as excinfo:
        actions._run_step(page, _step(selector="#run"), 3)

    assert "Background Scripts" in str(excinfo.value)
    assert "confirm_script_exec='approve'" in str(excinfo.value)
    assert excinfo.value.index == 3


def test_the_same_step_proceeds_once_approved():
    page = FakePage(known=["#run"], url="https://dev.example.com/sys.scripts.do")

    assert actions._run_step(page, _step(selector="#run"), 1, None, True) == {}


def test_a_click_elsewhere_is_untouched_by_the_gate():
    page = FakePage(known=["#save"], url="https://dev.example.com/incident.do")

    assert actions._run_step(page, _step(selector="#save"), 1) == {}


def test_an_unreadable_url_does_not_break_an_ordinary_click():
    class Detached(FakePage):
        @property
        def url(self):
            raise RuntimeError("page has been closed")

        @url.setter
        def url(self, _value):
            pass

    assert actions._run_step(Detached(known=["#save"]), _step(selector="#save"), 1) == {}


def test_running_a_background_script_needs_its_own_approval(monkeypatch):
    def _explode(*args, **kwargs):
        raise AssertionError("must not reach the window without confirm_script_exec")

    monkeypatch.setattr(tools, "find_window", _explode)

    result = tools.act_in_debug_window(
        MagicMock(),
        MagicMock(),
        tools.ActInDebugWindowParams(
            actions=[
                {"action": "fill", "selector": "#script", "value": "gr.deleteMultiple()"},
                {"action": "click", "selector": "text=Run script"},
            ]
        ),
    )

    assert result["success"] is False
    assert result["script_exec_steps"] == [2]
    assert "confirm_script_exec='approve'" in result["error"]
    assert "Background Scripts" in result["error"]


def test_an_eval_that_posts_to_the_runner_needs_both_approvals(monkeypatch):
    monkeypatch.setattr(tools, "find_window", lambda a: pytest.fail("must not reach the window"))

    result = tools.act_in_debug_window(
        MagicMock(),
        MagicMock(),
        tools.ActInDebugWindowParams(
            actions=[{"action": "eval", "value": "fetch('/sys.scripts.do', {method:'POST'})"}],
            confirm_eval="approve",
        ),
    )

    assert result["success"] is False
    assert result["script_exec_steps"] == [1]


def test_an_approved_run_reaches_the_window_with_the_flag(monkeypatch, tmp_path):
    state = _state()
    seen = {}
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))

    def _act(state, **kw):
        seen.update(kw)
        return {
            "url": "https://dev.example.com/sys.scripts.do",
            "seq": 1,
            "events": [],
            "steps": [{"step": 1, "action": "click", "ok": True}],
            "dialogs": [],
            "failed_step": None,
            "skipped": 0,
        }

    monkeypatch.setattr(tools, "act", _act)

    result = tools.act_in_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.ActInDebugWindowParams(
            actions=[{"action": "click", "selector": "text=Run script"}],
            confirm_script_exec="approve",
        ),
    )

    assert result["success"] is True
    assert seen["allow_server_script"] is True


def test_a_window_already_on_the_runner_refuses_the_whole_batch(monkeypatch, tmp_path):
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))

    def _act(state, **kw):
        raise server_scripts.ServerScriptBlocked(
            server_scripts.rejection("Background Scripts"), surface="Background Scripts"
        )

    monkeypatch.setattr(tools, "act", _act)

    result = tools.act_in_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        # Neither selector names a run verb — only the live URL knows.
        tools.ActInDebugWindowParams(actions=[{"action": "click", "selector": "#go"}]),
    )

    assert result["success"] is False
    assert result["script_exec_surface"] == "Background Scripts"
    assert "confirm_script_exec='approve'" in result["error"]


def test_the_read_tool_cannot_post_to_the_runner_either(monkeypatch):
    monkeypatch.setattr(tools, "find_window", lambda a: pytest.fail("must not reach the window"))

    result = tools.inspect_debug_window(
        MagicMock(),
        MagicMock(),
        tools.InspectDebugWindowParams(evaluate="fetch('/sys.scripts.do',{method:'POST'})"),
    )

    assert result["success"] is False
    assert result["script_exec_surface"] == "Background Scripts"


def test_an_ordinary_expression_still_reads_freely(monkeypatch, tmp_path):
    state = _state()
    monkeypatch.setattr(tools, "find_window", lambda auth_manager: state)
    monkeypatch.setattr(tools, "window_cursor_path", lambda a: str(tmp_path / "c.json"))
    monkeypatch.setattr(tools, "window_artifacts_dir", lambda a: str(tmp_path / "artifacts"))
    monkeypatch.setattr(
        tools,
        "capture",
        lambda state, **kw: {
            "url": "https://dev.example.com/sp",
            "seq": 1,
            "events": [],
            "evaluation": {"ok": True, "value": 7},
        },
    )

    result = tools.inspect_debug_window(
        SimpleNamespace(instance_url="https://dev.example.com"),
        MagicMock(),
        tools.InspectDebugWindowParams(evaluate="$scope.data.items.length"),
    )

    assert result["success"] is True
    assert result["evaluation"]["value"] == 7
