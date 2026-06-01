"""Tests for manage_session_context — current app / update set switching."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.session_context_tools import (
    ManageSessionContextParams,
    ensure_current_app,
    ensure_current_update_set,
    get_current_update_set,
    is_default_update_set,
    manage_session_context,
)
from servicenow_mcp.utils.config import ServerConfig


def _browser_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={
            "type": "browser",
            "browser": {"username": "jeongsh", "instance_url": "https://test.service-now.com"},
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
        ManageSessionContextParams(action="set_app", app_id="41c8a9e73b1e4a10ec3cbf2a85e45ab7"),
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
