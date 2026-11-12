"""G11 — update-set confirmation: ask once per set before a captured write.

Not a wall: the question carries the current set, the caller's open sets and
recent set names, and the three ways forward; a named approval or an explicit
manage_session_context pick ends it for that set.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from servicenow_mcp.policies import write_guards as wg
from servicenow_mcp.policies.write_guards import (
    CONFIRM_UPDATE_SET_FIELD,
    PolicyViolation,
    _g11_update_set_confirmation,
    note_update_set_chosen,
    strip_post_confirm_fields,
)

SET_ID = "aaaa1111bbbb2222cccc3333dddd4444"
OTHER_ID = "eeee5555ffff6666aaaa7777bbbb8888"
DEFAULT_ID = "cccc9999dddd0000eeee1111ffff2222"


def _ctx(tool="manage_script_include", auth="browser", url="https://test.service-now.com", **args):
    config = SimpleNamespace(
        instance_url=url, auth=SimpleNamespace(type=SimpleNamespace(value=auth))
    )
    server = SimpleNamespace(config=config, auth_manager=SimpleNamespace())
    return SimpleNamespace(server=server, tool_name=tool, arguments={"action": "update", **args})


@pytest.fixture(autouse=True)
def _fresh_memory():
    wg._CONFIRMED_UPDATE_SETS.clear()
    yield
    wg._CONFIRMED_UPDATE_SETS.clear()


def _patches(current, rec=None, recent=None, me="alice"):
    return (
        patch(
            "servicenow_mcp.tools.session_context_tools.get_current_update_set",
            return_value=current,
        ),
        patch.object(wg, "_fetch_one", return_value=rec),
        patch.object(wg, "_recent_update_sets", return_value=recent),
        patch.object(wg, "_current_username", return_value=me),
    )


def _run(ctx, current, rec=None, recent=None, me="alice"):
    p1, p2, p3, p4 = _patches(current, rec, recent, me)
    with p1, p2, p3 as recent_mock, p4:
        _g11_update_set_confirmation(ctx)
        return recent_mock


def _raise(ctx, current, rec=None, recent=None, me="alice") -> str:
    with pytest.raises(PolicyViolation) as exc:
        _run(ctx, current, rec, recent, me)
    return str(exc.value)


CUR = {"sys_id": SET_ID, "name": "Sprint 12 fixes"}
REC = {
    "application": {"value": "x", "display_value": "My App"},
    "sys_created_by": {"value": "alice", "display_value": "alice"},
}
RECENT = [
    {"sys_id": SET_ID, "name": "Sprint 12 fixes", "state": "in progress", "application": "My App"},
    {"sys_id": OTHER_ID, "name": "Sprint 13 work", "state": "in progress", "application": "My App"},
    {"sys_id": "1", "name": "Sprint 11 fixes", "state": "complete", "application": "My App"},
]


def test_first_write_into_unchosen_set_asks_with_options() -> None:
    msg = _raise(_ctx(), CUR, REC, RECENT)
    assert "[G11]" in msg
    assert "'Sprint 12 fixes'" in msg and SET_ID in msg and "My App" in msg
    # open sets list excludes the current one and closed ones
    assert "Sprint 13 work" in msg.split("Your open sets:")[1].split(".")[0]
    assert "Sprint 11 fixes" not in msg.split("Your open sets:")[1].split(".")[0]
    # recent names offered for a name proposal
    assert "'Sprint 11 fixes'" in msg
    assert f"{CONFIRM_UPDATE_SET_FIELD}='Sprint 12 fixes'" in msg
    assert "manage_changeset(action='create'" in msg
    assert "ASK THE USER" in msg and "Nothing was written" in msg


def test_named_approval_passes_and_is_remembered() -> None:
    _run(_ctx(**{CONFIRM_UPDATE_SET_FIELD: "sprint 12 FIXES"}), CUR, REC, RECENT)
    # Next write into the same set: no approval needed, no lookups made.
    recent = _run(_ctx(), CUR, REC, RECENT)
    recent.assert_not_called()


def test_approval_by_sys_id_passes() -> None:
    _run(_ctx(**{CONFIRM_UPDATE_SET_FIELD: SET_ID}), CUR, REC, RECENT)


def test_approval_naming_a_different_set_does_not_pass() -> None:
    msg = _raise(_ctx(**{CONFIRM_UPDATE_SET_FIELD: "Sprint 13 work"}), CUR, REC, RECENT)
    assert "[G11]" in msg
    assert "You approved 'Sprint 13 work', but this write would be captured into" in msg


def test_a_first_ask_does_not_claim_an_approval() -> None:
    msg = _raise(_ctx(), CUR, REC, RECENT)
    assert "You approved" not in msg


def test_switched_set_asks_again() -> None:
    _run(_ctx(**{CONFIRM_UPDATE_SET_FIELD: "Sprint 12 fixes"}), CUR, REC, RECENT)
    msg = _raise(_ctx(), {"sys_id": OTHER_ID, "name": "Sprint 13 work"}, REC, RECENT)
    assert "Sprint 13 work" in msg


def test_approval_is_per_instance() -> None:
    _run(_ctx(**{CONFIRM_UPDATE_SET_FIELD: "Sprint 12 fixes"}), CUR, REC, RECENT)
    _raise(_ctx(url="https://other.service-now.com"), CUR, REC, RECENT)


def test_default_says_it_will_not_ship_and_approval_is_not_remembered() -> None:
    cur = {"sys_id": DEFAULT_ID, "name": "Default [Global]"}
    msg = _raise(_ctx(), cur, REC, RECENT)
    assert "'Default'" in msg and "never promote" in msg
    assert f"{CONFIRM_UPDATE_SET_FIELD}='Default'" in msg
    _run(_ctx(**{CONFIRM_UPDATE_SET_FIELD: "Default"}), cur, REC, RECENT)
    _raise(_ctx(), cur, REC, RECENT)  # asks again on the next write


def test_someone_elses_set_is_named() -> None:
    rec = {**REC, "sys_created_by": {"value": "bob", "display_value": "bob"}}
    msg = _raise(_ctx(), CUR, rec, RECENT)
    assert "created by bob, not you ('alice')" in msg


def test_unlisted_sets_say_so_instead_of_silence() -> None:
    msg = _raise(_ctx(), CUR, REC, recent=None)
    assert "could not be listed" in msg


def test_unresolved_user_says_so() -> None:
    msg = _raise(_ctx(), CUR, REC, RECENT, me="")
    assert "session user unresolved" in msg


def test_explicit_pick_counts_as_chosen() -> None:
    ctx = _ctx()
    note_update_set_chosen(ctx.server.config, SET_ID, "Sprint 12 fixes")
    _run(ctx, CUR, REC, RECENT)


def test_explicit_pick_of_default_still_asks() -> None:
    ctx = _ctx()
    note_update_set_chosen(ctx.server.config, DEFAULT_ID, "Default [Global]")
    _raise(ctx, {"sys_id": DEFAULT_ID, "name": "Default"}, REC, RECENT)


@pytest.mark.parametrize("tool", ["manage_incident", "manage_changeset", "manage_session_context"])
def test_exempt_tools_skip(tool) -> None:
    with patch("servicenow_mcp.tools.session_context_tools.get_current_update_set") as get_current:
        _g11_update_set_confirmation(_ctx(tool=tool))
    get_current.assert_not_called()


def test_basic_auth_skips() -> None:
    with patch("servicenow_mcp.tools.session_context_tools.get_current_update_set") as get_current:
        _g11_update_set_confirmation(_ctx(auth="basic"))
    get_current.assert_not_called()


def test_unreadable_set_fails_open_by_default() -> None:
    _run(_ctx(), None)


def test_unreadable_set_fail_closed_asks(monkeypatch) -> None:
    monkeypatch.setenv("SERVICENOW_WRITE_GUARDS_FAIL", "closed")
    msg = _raise(_ctx(), None)
    assert "Could not read" in msg


def test_confirm_update_set_is_stripped_before_tool() -> None:
    out = strip_post_confirm_fields({"a": 1, CONFIRM_UPDATE_SET_FIELD: "x"})
    assert out == {"a": 1}


def test_no_sets_of_mine_is_said_and_team_names_fill_the_pattern() -> None:
    team = [
        {"sys_id": "1", "name": "Sprint 13 work", "state": "in progress", "application": "My App"},
        {"sys_id": "2", "name": "Sprint 13 work", "state": "in progress", "application": "My App"},
        {"sys_id": "3", "name": "Sprint 12 fixes", "state": "complete", "application": "My App"},
    ]
    p1, p2, _p3, p4 = _patches(CUR, REC)
    with (
        p1,
        p2,
        p4,
        patch.object(wg, "_recent_update_sets", side_effect=lambda ctx, who: [] if who else team),
    ):
        with pytest.raises(PolicyViolation) as exc:
            _g11_update_set_confirmation(_ctx())
    msg = str(exc.value)
    assert "You ('alice') have created no update sets on this instance." in msg
    team_part = msg.split("Recent set names on this instance")[1]
    assert team_part.count("'Sprint 13 work'") == 1  # de-duplicated
    assert "'Sprint 12 fixes'" in team_part


def test_enough_names_of_mine_skip_the_team_read() -> None:
    p1, p2, _p3, p4 = _patches(CUR, REC)
    with p1, p2, p4, patch.object(wg, "_recent_update_sets", return_value=RECENT) as rec:
        with pytest.raises(PolicyViolation):
            _g11_update_set_confirmation(_ctx())
    assert rec.call_count == 1
