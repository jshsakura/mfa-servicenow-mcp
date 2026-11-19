"""`expect` (check mid-batch) and the settle after input steps.

Measured in one live Workflow Studio session: 110 act calls, 2-4 steps each,
203 fixed waits (275s) guessed after keypresses, because the caller could not
check the page between steps and the page could not say when it was done.
"""

import time

import pytest

from servicenow_mcp.browser import actions
from servicenow_mcp.browser.page_state import PAGE_STATE_SCRIPT
from servicenow_mcp.browser.probe import PROBE_GLOBAL


class ScriptedPage:
    """A page whose state and open-request count follow a script, one per read."""

    def __init__(self, states, busy=(0,)):
        self.states = list(states)
        self.busy = list(busy)
        self.reads = 0

    @property
    def frames(self):
        return [self]

    def evaluate(self, expression):
        if expression == PAGE_STATE_SCRIPT:
            self.reads += 1
            state = self.states[0] if len(self.states) == 1 else self.states.pop(0)
            if isinstance(state, Exception):
                raise state
            return dict(state)
        if PROBE_GLOBAL in expression and "busy" in expression:
            return self.busy[0] if len(self.busy) == 1 else self.busy.pop(0)
        raise AssertionError(f"unexpected evaluate: {expression[:60]}")


def _expect(value, state=None, timeout_ms=None):
    raw = {"action": "expect", "value": value}
    if state:
        raw["state"] = state
    if timeout_ms:
        raw["timeout_ms"] = timeout_ms
    return actions.normalize([raw])[0]


MENU = {"focused": {"tag": "input", "label": "Search"}, "menu": ["Look Up Record", "Update"]}


# --- expect --------------------------------------------------------------


def test_expect_finds_text_in_an_open_menu():
    out = actions._expect(ScriptedPage([MENU]), _expect("look up record"), 1)
    assert out == {"expected": "'look up record' in menu"}


def test_expect_waits_for_the_state_to_arrive():
    page = ScriptedPage([{"focused": {"tag": "a", "label": "Add"}}, MENU])
    out = actions._expect(page, _expect("Look Up Record"), 1)
    assert "menu" in out["expected"] and page.reads == 2


def test_focused_scope_does_not_accept_a_menu_item():
    with pytest.raises(actions.ActionError) as raised:
        actions._expect(ScriptedPage([MENU]), _expect("Look Up", "focused", 200), 3)
    message = str(raised.value)
    assert raised.value.index == 3
    # Says where the page IS, so the next call needs no screenshot.
    assert "Now: focused 'Search'" in message and "Look Up Record" in message
    assert "not run" in message


def test_an_open_menu_is_found_by_its_trigger():
    # Live: the trigger was in open_popups and expect looked everywhere else.
    page = ScriptedPage([{"open_popups": ["More Actions menu"], "near_focus": ["Properties"]}])
    out = actions._expect(page, _expect("More Actions", "listed"), 1)
    assert out == {"expected": "'More Actions' in open_popups"}


def test_gone_passes_once_the_text_is_absent():
    page = ScriptedPage([{"dialogs": ["Discard changes? [Cancel | OK]"]}, {}])
    assert actions._expect(page, _expect("Discard", "gone"), 1) == {"expected": "'Discard' gone"}


def test_an_unread_page_is_neither_there_nor_gone():
    page = ScriptedPage([RuntimeError("Execution context was destroyed")])
    for scope in ("gone", "any"):
        with pytest.raises(actions.ActionError) as raised:
            actions._expect(page, _expect("Save", scope, 200), 1)
        assert "could not be read" in str(raised.value)


def test_expect_is_validated_before_the_browser_is_touched():
    with pytest.raises(ValueError, match="needs a value"):
        actions.normalize([{"action": "expect"}])
    with pytest.raises(ValueError, match="any, focused, listed, gone"):
        actions.normalize([{"action": "expect", "value": "x", "state": "visible"}])
    step = _expect("x")
    assert step["state"] == "any" and step["timeout_ms"] == actions.EXPECT_DEFAULT_TIMEOUT_MS


# --- settle --------------------------------------------------------------


def test_settle_returns_once_the_page_stops_changing_and_requests_are_done():
    page = ScriptedPage(
        [{"focused": {"label": "a"}}, {"focused": {"label": "b"}}, MENU], busy=[1, 0]
    )
    started = time.time()
    assert actions._settle(page) == {}
    assert time.time() - started < actions.SETTLE_CAP_MS / 1000.0


def test_an_open_request_holds_the_settle(monkeypatch):
    monkeypatch.setattr(actions, "SETTLE_CAP_MS", 400)
    out = actions._settle(ScriptedPage([MENU], busy=[2]))
    assert out == {"settle_capped": "400ms, 2 request(s) still open"}


def test_a_page_that_never_stops_changing_is_capped(monkeypatch):
    monkeypatch.setattr(actions, "SETTLE_CAP_MS", 400)
    states = [{"focused": {"label": str(i)}} for i in range(200)]
    out = actions._settle(ScriptedPage(states))
    assert out == {"settle_capped": "400ms, the page kept changing"}


def test_no_request_counter_is_said_not_passed_off_as_the_full_check():
    # A window open across an upgrade keeps its old probe: no busy() to ask.
    assert actions._settle(ScriptedPage([MENU], busy=[-1])) == {"settle_signal": "page state only"}


def test_input_steps_settle_and_an_explicit_wait_is_not_doubled():
    steps = actions.normalize(
        [
            {"action": "press", "key": "Enter"},
            {"action": "press", "key": "Enter"},
            {"action": "wait", "ms": 500},
            {"action": "expect", "value": "Look Up"},
            {"action": "type", "value": "Look Up Record"},
        ]
    )
    assert [actions.settles_after(steps, i) for i in range(1, 6)] == [
        True,
        False,
        False,
        False,
        True,
    ]


def test_the_batch_budget_covers_every_settle():
    steps = actions.normalize([{"action": "press", "key": "Enter"}] * 3)
    plain = sum(s["timeout_ms"] for s in steps) / 1000.0 + 60.0
    assert actions.budget_seconds(steps) == plain + 3 * actions.SETTLE_CAP_MS / 1000.0
