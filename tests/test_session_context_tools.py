"""Tests for manage_session_context — current app / update set switching."""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.session_context_tools import (
    ManageSessionContextParams,
    _resolve_update_set_by_name,
    check_update_set_for_push,
    ensure_current_app,
    ensure_current_update_set,
    get_current_update_set,
    get_last_update_set_for_record,
    is_default_update_set,
    manage_session_context,
    split_picker_label,
)
from servicenow_mcp.utils.config import ServerConfig


def _browser_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={
            "type": "browser",
            "browser": {"username": "testuser", "instance_url": "https://test.service-now.com"},
        },
    )


def _basic_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "pw"}},
    )


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = ""
    r.raise_for_status = MagicMock()
    return r


# --- validation -----------------------------------------------------------
def test_set_app_requires_app_id():
    with pytest.raises(ValueError, match="app_id is required"):
        ManageSessionContextParams(action="set_app")


def test_unknown_action_rejected():
    with pytest.raises(ValueError, match="action must be one of"):
        ManageSessionContextParams(action="bogus")


# --- auth gating ----------------------------------------------------------
def test_non_browser_auth_blocked():
    auth = MagicMock()
    result = manage_session_context(_basic_config(), auth, ManageSessionContextParams(action="get"))
    assert result["success"] is False
    assert result["error"] == "browser_auth_required"
    auth.make_request.assert_not_called()


# --- get ------------------------------------------------------------------
def test_get_returns_current_app_and_update_set():
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({"result": {"current": {"sysId": "app-1", "name": "HBPM"}}}),
        _resp({"result": {"current": {"sysId": "us-1", "name": "HBPM Pilot"}}}),
    ]
    result = manage_session_context(
        _browser_config(), auth, ManageSessionContextParams(action="get")
    )
    assert result["success"] is True
    assert result["application"] == {"sys_id": "app-1", "name": "HBPM"}
    assert result["update_set"] == {"sys_id": "us-1", "name": "HBPM Pilot"}


# --- set_app: verified by read-back --------------------------------------
def test_set_app_success_when_readback_matches():
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # PUT
        _resp({"result": {"current": {"sysId": "app-1", "name": "HBPM"}}}),  # GET verify
    ]
    result = manage_session_context(
        _browser_config(), auth, ManageSessionContextParams(action="set_app", app_id="app-1")
    )
    assert result["success"] is True
    assert result["current"]["sys_id"] == "app-1"


def test_set_app_reports_failure_when_not_applied():
    # PUT "succeeds" but the read-back shows a different app → must NOT claim success.
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # PUT
        _resp({"result": {"current": {"sysId": "bpm-old", "name": "BPM"}}}),  # GET verify
    ]
    result = manage_session_context(
        _browser_config(), auth, ManageSessionContextParams(action="set_app", app_id="app-1")
    )
    assert result["success"] is False
    assert result["error"] == "not_applied"
    assert result["current"]["sys_id"] == "bpm-old"


def test_set_app_with_update_set_sets_both_in_one_call():
    # scope + update set are managed together — set_app with an update_set sets both.
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # app PUT
        _resp({"result": {"current": {"sysId": "app-1", "name": "BPM"}}}),  # app GET
        _resp({}),  # update set PUT
        _resp({"result": {"current": {"sysId": "us-1", "name": "My Set"}}}),  # update set GET
    ]
    result = manage_session_context(
        _browser_config(),
        auth,
        ManageSessionContextParams(action="set_app", app_id="app-1", update_set_id="us-1"),
    )
    assert result["success"] is True
    assert result["application"]["sys_id"] == "app-1"
    assert result["update_set"]["sys_id"] == "us-1"


def test_set_app_without_update_set_unchanged():
    # set_app alone still returns the single-result shape (no update_set wrangling).
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),
        _resp({"result": {"current": {"sysId": "app-1", "name": "BPM"}}}),
    ]
    result = manage_session_context(
        _browser_config(), auth, ManageSessionContextParams(action="set_app", app_id="app-1")
    )
    assert result["success"] is True
    assert result["current"]["sys_id"] == "app-1"
    assert auth.make_request.call_count == 2  # only app PUT+GET, no update-set calls


def test_set_update_set_success():
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),
        _resp({"result": {"current": {"sysId": "us-9", "name": "Pilot"}}}),
    ]
    result = manage_session_context(
        _browser_config(),
        auth,
        ManageSessionContextParams(action="set_update_set", update_set_id="us-9"),
    )
    assert result["success"] is True


# --- set_update_set by NAME ----------------------------------------------
def test_set_update_set_requires_id_or_name():
    with pytest.raises(ValueError, match="update_set_id or update_set_name is required"):
        ManageSessionContextParams(action="set_update_set")


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_set_update_set_by_name_resolves_and_switches(mock_query):
    # Name → unique in-progress sys_id, then PUT + verified read-back.
    mock_query.return_value = ([{"sys_id": "us-9", "name": "HBPM Pilot"}], 1)
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # PUT
        _resp({"result": {"current": {"sysId": "us-9", "name": "HBPM Pilot"}}}),  # verify
    ]
    result = manage_session_context(
        _browser_config(),
        auth,
        ManageSessionContextParams(action="set_update_set", update_set_name="HBPM Pilot"),
    )
    assert result["success"] is True
    assert result["current"]["sys_id"] == "us-9"


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_set_update_set_by_name_not_found(mock_query):
    mock_query.return_value = ([], 0)
    auth = MagicMock()
    result = manage_session_context(
        _browser_config(),
        auth,
        ManageSessionContextParams(action="set_update_set", update_set_name="Nope"),
    )
    assert result["success"] is False
    assert result["error"] == "not_found"
    auth.make_request.assert_not_called()  # never attempted a switch


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_set_update_set_by_name_ambiguous(mock_query):
    # Two in-progress matches, neither an exact case-insensitive match → ambiguous.
    mock_query.return_value = (
        [
            {"sys_id": "us-1", "name": "Pilot A"},
            {"sys_id": "us-2", "name": "Pilot B"},
        ],
        2,
    )
    auth = MagicMock()
    result = manage_session_context(
        _browser_config(),
        auth,
        ManageSessionContextParams(action="set_update_set", update_set_name="Pilot"),
    )
    assert result["success"] is False
    assert result["error"] == "ambiguous"
    assert len(result["candidates"]) == 2


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_set_update_set_by_name_exact_wins_over_substring(mock_query):
    # Exact case-insensitive match is chosen even when substring matches also exist.
    mock_query.return_value = (
        [
            {"sys_id": "us-1", "name": "Pilot Extended"},
            {"sys_id": "us-2", "name": "Pilot"},
        ],
        2,
    )
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),
        _resp({"result": {"current": {"sysId": "us-2", "name": "Pilot"}}}),
    ]
    result = manage_session_context(
        _browser_config(),
        auth,
        ManageSessionContextParams(action="set_update_set", update_set_name="Pilot"),
    )
    assert result["success"] is True
    assert result["current"]["sys_id"] == "us-2"


# --- ensure_current_update_set (used by create paths) --------------------
def test_ensure_current_update_set_skips_for_basic_auth():
    auth = MagicMock()
    out = ensure_current_update_set(_basic_config(), auth, "us-9")
    assert out["switched"] is False
    assert out["skipped"] == "not_browser_auth"
    auth.make_request.assert_not_called()


def test_ensure_current_update_set_noop_when_already_current():
    # A 32-char hex string is treated as a sys_id → no name lookup, just read-back.
    sys_id = "a" * 32
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({"result": {"current": {"sysId": sys_id, "name": "Pilot"}}}),  # GET only
    ]
    out = ensure_current_update_set(_browser_config(), auth, sys_id)
    assert out["switched"] is False
    assert out["already_current"] is True
    assert auth.make_request.call_count == 1  # no PUT


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_ensure_current_update_set_by_name_switches(mock_query):
    mock_query.return_value = ([{"sys_id": "us-9", "name": "HBPM Pilot"}], 1)
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({"result": {"current": {"sysId": "old", "name": "Other"}}}),  # GET current
        _resp({}),  # PUT
        _resp({"result": {"current": {"sysId": "us-9", "name": "HBPM Pilot"}}}),  # verify
    ]
    out = ensure_current_update_set(_browser_config(), auth, "HBPM Pilot")
    assert out["switched"] is True


# --- get_current_update_set / is_default_update_set (silent-move guard) ---
def test_get_current_update_set_none_for_basic_auth():
    auth = MagicMock()
    assert get_current_update_set(_basic_config(), auth) is None
    auth.make_request.assert_not_called()


def test_get_current_update_set_reads_browser_session():
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-1", "name": "Pilot"}}}
    )
    out = get_current_update_set(_browser_config(), auth)
    assert out == {"sys_id": "us-1", "name": "Pilot"}


def test_get_current_update_set_swallows_errors():
    auth = MagicMock()
    auth.make_request.side_effect = Exception("boom")
    assert get_current_update_set(_browser_config(), auth) is None


# --- check_update_set_for_push (pre-write capture warning) ----------------
# The invariant under test is as much what this does NOT do: it never creates or
# switches an update set. A push must not write a sys_update_set record nobody
# asked for, so every case below asserts read-only behaviour.
def test_check_update_set_for_push_warns_on_default():
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-def", "name": "Default"}}}
    )
    out = check_update_set_for_push(_browser_config(), auth)
    assert out is not None
    assert out["update_set"] == "Default"
    assert "not" in out["warning"].lower()
    assert "recommended_action" in out
    # Read-only: exactly one GET, never a PUT and never an insert.
    assert auth.make_request.call_count == 1
    assert auth.make_request.call_args[0][0] == "GET"


def test_check_update_set_for_push_silent_on_a_real_set():
    """A correctly-captured push (no record context) pays zero tokens to say so."""
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-1", "name": "My Feature"}}}
    )
    assert check_update_set_for_push(_browser_config(), auth) is None


@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_check_update_set_for_push_confirms_when_switched_away(mock_last):
    """Named set differs from where THIS record was last captured → confirm intent."""
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Other Feature"}}}
    )
    mock_last.return_value = {"sys_id": "us-old", "name": "Original Feature"}
    out = check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1")
    assert out is not None
    assert out["current_update_set"] == "Other Feature"
    assert out["last_worked_update_set"] == "Original Feature"
    assert "confirm" in out


@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_check_update_set_for_push_attributes_the_earlier_capture(mock_last):
    """WHO/WHEN must ride along — an unattributed diff reads as 'you switched'."""
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Other Feature"}}}
    )
    mock_last.return_value = {
        "sys_id": "us-old",
        "name": "Original Feature",
        "by": "another.dev",
        "at": "2026-07-27 05:35:00",
    }
    out = check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1")
    assert out["last_worked_by"] == "another.dev"
    assert out["last_worked_at"] == "2026-07-27 05:35:00"
    assert "another.dev" in out["confirm"] and "05:35:00" in out["confirm"]
    # Must not imply the MCP changed session state — it only ever reads.
    assert "Nothing was created or switched" in out["confirm"]


@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_a_picker_label_is_not_a_suffixed_name(mock_last):
    """'Some Dev [My App]' from the picker IS 'Some Dev'.

    This case used to be reported as "two sets whose names differ by a suffix",
    which sent people looking for a set named 'Some Dev [My App]' that does not
    exist. The two sys_ids really are two sets — but they share a NAME, and the
    application is the thing that tells them apart.
    """
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Some Dev [My App]"}}}
    )
    mock_last.return_value = {"sys_id": "us-old", "name": "Some Dev"}
    out = check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1")

    assert out["current_update_set"] == "Some Dev"
    assert out["current_update_set_application"] == "My App"
    assert "both named 'Some Dev'" in out["note"]
    assert "differ by a suffix" not in out["note"]


@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_two_sets_sharing_a_name_must_be_switched_by_sys_id(mock_last):
    # Recommending update_set_name here would resolve ambiguously — or silently
    # pick the other one, which is the failure this whole change is about.
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Shared Name [App A]"}}}
    )
    mock_last.return_value = {"sys_id": "us-old", "name": "Shared Name"}
    out = check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1")

    assert "update_set_id='us-old'" in out["confirm"]
    assert "update_set_name=" not in out["confirm"]
    assert out["current_update_set_id"] == "us-new"
    assert out["last_worked_update_set_id"] == "us-old"


@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_genuinely_suffixed_names_are_still_flagged_as_lookalikes(mock_last):
    """'Pilot' vs 'Pilot Phase 2' are two sets; a split there is easy to miss."""
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Pilot Phase 2"}}}
    )
    mock_last.return_value = {"sys_id": "us-old", "name": "Pilot"}
    out = check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1")

    assert "only differ by a suffix" in out["note"]
    # Names are unambiguous here, so the cheaper name-based switch is fine.
    assert "update_set_name='Pilot'" in out["confirm"]


@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_check_update_set_for_push_omits_note_for_unrelated_names(mock_last):
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Other Feature"}}}
    )
    mock_last.return_value = {"sys_id": "us-old", "name": "Original Feature"}
    assert "note" not in check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1")


@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_check_update_set_for_push_silent_when_still_in_same_set(mock_last):
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-1", "name": "My Feature"}}}
    )
    mock_last.return_value = {"sys_id": "us-1", "name": "My Feature"}
    assert check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1") is None


@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_check_update_set_for_push_silent_on_first_edit(mock_last):
    """No prior capture for the record → nothing to have switched away from."""
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-1", "name": "My Feature"}}}
    )
    mock_last.return_value = None
    assert check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1") is None


def test_check_update_set_for_push_silent_for_basic_auth():
    """The picker is session-only; uncertainty must stay silent, not guess."""
    auth = MagicMock()
    assert check_update_set_for_push(_basic_config(), auth) is None
    auth.make_request.assert_not_called()


def test_check_update_set_for_push_silent_when_unreadable():
    auth = MagicMock()
    auth.make_request.side_effect = Exception("boom")
    assert check_update_set_for_push(_browser_config(), auth) is None


def test_is_default_update_set_matches_by_name():
    assert is_default_update_set({"sys_id": "x", "name": "Default"}) is True
    assert is_default_update_set({"sys_id": "x", "name": "default"}) is True
    assert is_default_update_set({"sys_id": "x", "name": "HBPM Pilot"}) is False
    assert is_default_update_set(None) is False


# --- ensure_current_app (used by create paths) ---------------------------
def test_ensure_current_app_skips_for_basic_auth():
    auth = MagicMock()
    out = ensure_current_app(_basic_config(), auth, "app-1")
    assert out["switched"] is False
    assert out["skipped"] == "not_browser_auth"
    auth.make_request.assert_not_called()


def test_ensure_current_app_noop_when_already_current():
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({"result": {"current": {"sysId": "app-1", "name": "HBPM"}}}),  # GET only
    ]
    out = ensure_current_app(_browser_config(), auth, "app-1")
    assert out["switched"] is False
    assert out["already_current"] is True
    assert auth.make_request.call_count == 1  # no PUT


def test_ensure_current_app_switches_when_different():
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({"result": {"current": {"sysId": "bpm-old", "name": "BPM"}}}),  # GET current
        _resp({}),  # PUT
        _resp({"result": {"current": {"sysId": "app-1", "name": "HBPM"}}}),  # GET verify
    ]
    out = ensure_current_app(_browser_config(), auth, "app-1")
    assert out["switched"] is True


# --- concoursepicker is a UI endpoint: same-origin headers + canonical body ---
def _resp_text(text, status=403):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = {}
    r.raise_for_status = MagicMock()
    return r


def test_set_app_sends_ui_context_headers_and_value_body():
    """The picker PUT must look UI-driven (Referer/Origin) and carry the
    concoursepicker-canonical 'value' key, or ServiceNow 403s an admin's switch."""
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # PUT
        _resp({"result": {"current": {"sysId": "app-1", "name": "HBPM"}}}),  # GET verify
    ]
    manage_session_context(
        _browser_config(), auth, ManageSessionContextParams(action="set_app", app_id="app-1")
    )
    put_call = auth.make_request.call_args_list[0]
    assert put_call.args[0] == "PUT"
    headers = put_call.kwargs["headers"]
    assert headers["Referer"].startswith("https://test.service-now.com")
    assert headers["Origin"] == "https://test.service-now.com"
    assert put_call.kwargs["json"]["value"] == "app-1"


def test_get_current_sends_ui_context_headers():
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({"result": {"current": {"sysId": "a", "name": "A"}}}),
        _resp({"result": {"current": {"sysId": "u", "name": "U"}}}),
    ]
    manage_session_context(_browser_config(), auth, ManageSessionContextParams(action="get"))
    get_call = auth.make_request.call_args_list[0]
    assert get_call.args[0] == "GET"
    assert get_call.kwargs["headers"]["Origin"] == "https://test.service-now.com"


def test_put_403_surfaces_server_reason():
    """A rejected picker PUT must report the server's reason, not a bare 403."""
    auth = MagicMock()
    auth.make_request.side_effect = [_resp_text("Forbidden: XSRF token mismatch", status=403)]
    result = manage_session_context(
        _browser_config(), auth, ManageSessionContextParams(action="set_app", app_id="app-1")
    )
    assert result["success"] is False
    assert "403" in result["message"]
    assert "XSRF" in result["message"]


def test_not_applied_attaches_raw_diagnostics():
    """Mirrors the dev failure: PUT accepted (200) but read-back current is empty.
    The raw GET/PUT payloads must be attached so a shape mismatch can be fixed."""
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # PUT (200, no 403)
        _resp({"result": {"current": {"sysId": "", "name": ""}}}),  # read-back: empty current
    ]
    result = manage_session_context(
        _browser_config(),
        auth,
        ManageSessionContextParams(action="set_app", app_id="aaaa1111bbbb2222cccc3333dddd4444"),
    )
    assert result["success"] is False
    assert result["error"] == "not_applied"
    assert result["diagnostics"]["put"]["status"] == 200
    assert result["diagnostics"]["readback"]["status"] == 200


def test_picker_value_handles_list_with_selected_flag():
    """Concoursepicker list-shape response: the active option is flagged, not
    nested under 'current'. It must parse instead of reading as empty."""
    from servicenow_mcp.tools.session_context_tools import _picker_value

    payload = {
        "result": [
            {"sysId": "global-1", "name": "Global", "selected": False},
            {"sysId": "bpm-1", "name": "BPM", "selected": True},
        ]
    }
    assert _picker_value(payload) == {"sys_id": "bpm-1", "name": "BPM"}


def test_set_app_success_with_list_shape_readback():
    """End-to-end: PUT ok, read-back returns the list shape with BPM selected."""
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # PUT
        _resp({"result": [{"sysId": "bpm-1", "name": "BPM", "selected": True}]}),  # read-back
    ]
    result = manage_session_context(
        _browser_config(), auth, ManageSessionContextParams(action="set_app", app_id="bpm-1")
    )
    assert result["success"] is True
    assert result["current"]["sys_id"] == "bpm-1"


def test_picker_value_current_as_bare_sys_id_string():
    """The dev application-picker case: current is a bare sys_id string, not a
    {sysId:...} object. Old parser read this as empty → false not_applied."""
    from servicenow_mcp.tools.session_context_tools import _picker_value

    assert _picker_value({"result": {"current": "eeee5555ffff6666aaaa7777bbbb8888"}}) == {
        "sys_id": "eeee5555ffff6666aaaa7777bbbb8888",
        "name": "",
    }


def test_picker_value_nested_list_under_key():
    from servicenow_mcp.tools.session_context_tools import _picker_value

    payload = {
        "result": {
            "default": {"sysId": "global", "name": "Global"},
            "list": [
                {"sysId": "global", "name": "Global", "selected": False},
                {"sysId": "hbpm-1", "name": "HBPM", "selected": True},
            ],
        }
    }
    assert _picker_value(payload) == {"sys_id": "hbpm-1", "name": "HBPM"}


def test_picker_value_top_level_value_field():
    from servicenow_mcp.tools.session_context_tools import _picker_value

    assert _picker_value({"result": {"value": "hbpm-1", "displayValue": "HBPM"}}) == {
        "sys_id": "hbpm-1",
        "name": "HBPM",
    }


def test_picker_value_empty_current_stays_empty():
    """An empty current object must still resolve to empty (a real failed switch
    must not be masked by the more aggressive resolver)."""
    from servicenow_mcp.tools.session_context_tools import _picker_value

    assert _picker_value({"result": {"current": {"sysId": "", "name": ""}}}) == {
        "sys_id": "",
        "name": "",
    }


def test_set_app_success_with_bare_string_current_readback():
    """End-to-end: switch reports success when the read-back uses the bare-string
    current shape that previously produced a false not_applied."""
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # PUT
        _resp({"result": {"current": "hbpm-1"}}),  # read-back: bare sys_id string
    ]
    result = manage_session_context(
        _browser_config(), auth, ManageSessionContextParams(action="set_app", app_id="hbpm-1")
    )
    assert result["success"] is True
    assert result["current"]["sys_id"] == "hbpm-1"


def test_picker_value_real_application_shape_bare_current_plus_list():
    """The ACTUAL dev /concoursepicker/application shape: current is a bare
    sys_id string, names live in result.list. Must resolve sys_id AND name."""
    from servicenow_mcp.tools.session_context_tools import _picker_value

    payload = {
        "result": {
            "current": "aaaa1111bbbb2222cccc3333dddd4444",
            "list": [
                {"sysId": "global", "name": "Global", "scopeName": "global"},
                {
                    "sysId": "aaaa1111bbbb2222cccc3333dddd4444",
                    "name": "BPM",
                    "scopeName": "x_acme_bpm",
                },
                {
                    "sysId": "eeee5555ffff6666aaaa7777bbbb8888",
                    "name": "HBPM",
                    "scopeName": "x_acme_hbpm",
                },
            ],
        }
    }
    assert _picker_value(payload) == {
        "sys_id": "aaaa1111bbbb2222cccc3333dddd4444",
        "name": "BPM",
    }


def test_set_app_success_with_real_application_shape():
    """End-to-end set_app against the real bare-current+list shape."""
    auth = MagicMock()
    auth.make_request.side_effect = [
        _resp({}),  # PUT
        _resp(
            {
                "result": {
                    "current": "eeee5555ffff6666aaaa7777bbbb8888",
                    "list": [
                        {"sysId": "eeee5555ffff6666aaaa7777bbbb8888", "name": "HBPM"},
                    ],
                }
            }
        ),
    ]
    result = manage_session_context(
        _browser_config(),
        auth,
        ManageSessionContextParams(action="set_app", app_id="eeee5555ffff6666aaaa7777bbbb8888"),
    )
    assert result["success"] is True
    assert result["current"] == {"sys_id": "eeee5555ffff6666aaaa7777bbbb8888", "name": "HBPM"}


# --- picker labels vs names (the "which set is this?" confusion) -----------
# The update-set picker labels entries "Name [Application]". That label is not
# the name: sys_update_set stores the name alone, every reference display value
# shows the name alone, and update_set_name resolves against the name alone.
# Handing the label back produced a string that could not be fed into the tool
# that accepts one — and made one set look like two.


def test_a_picker_label_splits_into_a_name_and_an_application():
    assert split_picker_label("Pilot [My App]") == ("Pilot", "My App")
    assert split_picker_label("  Pilot [My App]  ") == ("Pilot", "My App")


def test_a_name_without_a_label_is_left_alone():
    assert split_picker_label("Pilot") == ("Pilot", "")
    assert split_picker_label("") == ("", "")


def test_only_a_trailing_bracket_group_is_a_label():
    # A set genuinely named "[Draft] Pilot" keeps its name — the application is
    # read from the record, never guessed from the string.
    assert split_picker_label("[Draft] Pilot") == ("[Draft] Pilot", "")
    assert split_picker_label("Release [Q3] notes") == ("Release [Q3] notes", "")


def test_the_current_update_set_reports_the_name_that_round_trips():
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-1", "name": "Pilot [My App]"}}}
    )

    out = get_current_update_set(_browser_config(), auth)

    assert out["name"] == "Pilot"
    assert out["application"] == "My App"


def test_the_default_set_is_recognized_through_its_label():
    # The picker calls it "Default [Global]". An exact match against that string
    # is False — and would silently drop the one warning that costs a deploy.
    assert is_default_update_set({"sys_id": "x", "name": "Default [Global]"}) is True
    assert is_default_update_set({"sys_id": "x", "name": "Default"}) is True
    assert is_default_update_set({"sys_id": "x", "name": "Default Pilot"}) is False


def test_the_default_warning_survives_a_labelled_picker_value():
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-def", "name": "Default [Global]"}}}
    )

    out = check_update_set_for_push(_browser_config(), auth)

    assert out is not None
    assert out["update_set"] == "Default"
    assert "never promote" in out["warning"]


# --- resolving a name when two sets share one -----------------------------


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_same_name_candidates_are_told_apart_by_application(mock_query):
    mock_query.return_value = (
        [
            {"sys_id": "us-1", "name": "Shared Name", "application": "App A"},
            {"sys_id": "us-2", "name": "Shared Name", "application": "App B"},
        ],
        2,
    )

    out = _resolve_update_set_by_name(_browser_config(), MagicMock(), "Shared Name")

    assert out["error"] == "ambiguous"
    assert "share the name" in out["message"]
    assert "update_set_id=<sys_id>" in out["message"]
    # Without the application these are two visually identical rows — which is
    # exactly how the pair became impossible to tell apart.
    assert {c["application"] for c in out["candidates"]} == {"App A", "App B"}


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_a_label_pasted_back_resolves_instead_of_failing(mock_query):
    # The caller shows "Shared Name [App B]" because that is what an earlier
    # response showed THEM. nameLIKE on that string matches nothing.
    mock_query.return_value = (
        [
            {"sys_id": "us-1", "name": "Shared Name", "application": "App A"},
            {"sys_id": "us-2", "name": "Shared Name", "application": "App B"},
        ],
        2,
    )

    out = _resolve_update_set_by_name(_browser_config(), MagicMock(), "Shared Name [App B]")

    assert out.get("error") is None
    assert out["sys_id"] == "us-2"
    assert mock_query.call_args.kwargs["query"].startswith("state=in progress^nameLIKEShared Name^")


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_an_unknown_application_in_a_label_stays_ambiguous_rather_than_guessing(mock_query):
    mock_query.return_value = (
        [
            {"sys_id": "us-1", "name": "Shared Name", "application": "App A"},
            {"sys_id": "us-2", "name": "Shared Name", "application": "App B"},
        ],
        2,
    )

    out = _resolve_update_set_by_name(_browser_config(), MagicMock(), "Shared Name [App C]")

    assert out["error"] == "ambiguous"


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
def test_a_unique_hit_carries_its_application(mock_query):
    mock_query.return_value = ([{"sys_id": "us-1", "name": "Pilot", "application": "My App"}], 1)

    out = _resolve_update_set_by_name(_browser_config(), MagicMock(), "Pilot")

    assert out == {"sys_id": "us-1", "name": "Pilot", "application": "My App"}


# --- the OTHER set is looked up, never inferred from its name -------------
# Reported from a live session: the check announced "two in-progress update sets
# share this name, your change is split" when the two same-named sets were
# COMPLETE and belonged to a different application. It had the sys_id in hand and
# described the set from a name match instead of reading it.
@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_a_closed_earlier_set_is_not_a_split(mock_last, mock_page):
    """You cannot capture into a completed set, so nothing is split to rejoin.

    The old advice — switch back and re-save — was not just noise, it was
    impossible to carry out.
    """
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Sprint 12 fixes"}}}
    )
    mock_last.return_value = {"sys_id": "us-old", "name": "Sprint 12 fixes"}
    mock_page.return_value = (
        [
            {
                "sys_id": "us-old",
                "name": "Sprint 12 fixes",
                "state": "complete",
                "application": "Other App",
            }
        ],
        1,
    )

    assert check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1") is None


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_two_genuinely_open_sets_sharing_a_name_still_warn(mock_last, mock_page):
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Sprint 12 fixes"}}}
    )
    mock_last.return_value = {"sys_id": "us-old", "name": "Sprint 12 fixes"}
    mock_page.return_value = (
        [
            {
                "sys_id": "us-old",
                "name": "Sprint 12 fixes",
                "state": "in progress",
                "application": "My App",
            }
        ],
        1,
    )

    out = check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1")
    assert out is not None
    assert "in-progress" in out["note"]
    assert "us-old" in out["note"] and "us-new" in out["note"]
    assert out["last_worked_update_set_state"] == "in progress"


@patch("servicenow_mcp.tools.session_context_tools.sn_query_page")
@patch("servicenow_mcp.tools.session_context_tools.get_last_update_set_for_record")
def test_an_unreadable_state_is_never_reported_as_in_progress(mock_last, mock_page):
    """Unknown is not 'in progress'. The check may keep confirming, but it may
    not assert a fact about a set it could not read."""
    auth = MagicMock()
    auth.make_request.return_value = _resp(
        {"result": {"current": {"sysId": "us-new", "name": "Sprint 12 fixes"}}}
    )
    mock_last.return_value = {"sys_id": "us-old", "name": "Sprint 12 fixes"}
    mock_page.side_effect = Exception("ACL")

    out = check_update_set_for_push(_browser_config(), auth, "sp_widget", "wid-1")
    assert out is not None
    assert "in-progress" not in out["note"]
    assert "us-old" in out["note"]


# --- the reference read itself --------------------------------------------
# Every test above mocks get_last_update_set_for_record and hands it a clean
# {"sys_id": ...}. That is exactly how the producer drifted from its consumer:
# it returned a LABEL in the sys_id slot for months and the suite stayed green.
# These exercise the real function against the shapes the Table API returns.
def _table_resp(rows):
    r = MagicMock()
    r.status_code = 200
    r.content = json.dumps({"result": rows}).encode()
    r.headers = {}
    r.json.return_value = {"result": rows}
    r.text = ""
    r.raise_for_status = MagicMock()
    return r


_US_A = "133742d8" + "a" * 24
_US_B = "1d2be25d" + "b" * 24


def test_last_update_set_asks_for_both_halves_of_the_reference():
    """display_value='all' — the id and the label must arrive separately."""
    auth = MagicMock()
    auth.make_request.return_value = _table_resp(
        [
            {
                "name": "sp_widget_wid-ref1",
                "update_set": {"value": _US_A, "display_value": "Alice"},
                "sys_updated_by": {"value": "alice", "display_value": "alice"},
                "sys_updated_on": {"value": "2026-07-27 05:35:00", "display_value": "27/07/2026"},
            }
        ]
    )
    out = get_last_update_set_for_record(_browser_config(), auth, "sp_widget", "wid-ref1")
    assert out["sys_id"] == _US_A
    assert out["name"] == "Alice"
    assert out["by"] == "alice"
    assert auth.make_request.call_args.kwargs["params"]["sysparm_display_value"] == "all"


def test_a_reference_label_is_never_returned_as_a_sys_id():
    """The regression: sysparm_display_value=true collapses the ref to its LABEL.

    A label in the sys_id slot compares unequal to every real sys_id, so the
    push check reported one set as two on every single push of an already
    captured record.
    """
    auth = MagicMock()
    auth.make_request.return_value = _table_resp(
        [{"name": "sp_widget_wid-ref2", "update_set": "Alice", "sys_updated_by": "alice"}]
    )
    out = get_last_update_set_for_record(_browser_config(), auth, "sp_widget", "wid-ref2")
    assert out["sys_id"] == ""
    assert out["name"] == "Alice"


def test_a_bare_sys_id_string_is_still_read_as_an_id():
    auth = MagicMock()
    auth.make_request.return_value = _table_resp(
        [{"name": "sp_widget_wid-ref3", "update_set": _US_A, "sys_updated_by": "alice"}]
    )
    out = get_last_update_set_for_record(_browser_config(), auth, "sp_widget", "wid-ref3")
    assert out["sys_id"] == _US_A
    assert out["name"] == ""


def _routing_auth(update_set_field, current_id=_US_A, current_name="Alice [My App]"):
    """Picker GET -> current selection; table GET -> the record's last capture."""

    def _req(method, url, **kwargs):
        if "concoursepicker" in url:
            return _resp({"result": {"current": {"sysId": current_id, "name": current_name}}})
        return _table_resp(
            [
                {
                    "name": "sp_angular_provider_prov-x",
                    "update_set": update_set_field,
                    "sys_updated_by": "alice",
                    "sys_updated_on": "2026-08-27 09:01:53",
                }
            ]
        )

    auth = MagicMock()
    auth.make_request.side_effect = _req
    return auth


def test_repushing_into_the_same_set_says_nothing():
    """The live failure: same set both sides, reported as 'two sets, one name'."""
    auth = _routing_auth({"value": _US_A, "display_value": "Alice"})
    assert (
        check_update_set_for_push(_browser_config(), auth, "sp_angular_provider", "prov-1") is None
    )


def test_a_genuinely_different_set_is_still_confirmed():
    auth = _routing_auth({"value": _US_B, "display_value": "Alice 1"})
    out = check_update_set_for_push(_browser_config(), auth, "sp_angular_provider", "prov-2")
    assert out is not None
    assert out["last_worked_update_set_id"] == _US_B
    assert out["last_worked_set_identified"] is True


def test_an_unresolvable_reference_is_not_reported_as_a_second_set():
    """Matching label + no id is an UNREAD signal, never evidence of a split."""
    auth = _routing_auth("Alice")
    out = check_update_set_for_push(_browser_config(), auth, "sp_angular_provider", "prov-3")
    assert out is not None
    assert out["last_worked_set_identified"] is False
    assert "both named" not in out.get("note", "")
    assert "NOT determined" in out["note"]
    assert "most likely the same set" in out["note"]
