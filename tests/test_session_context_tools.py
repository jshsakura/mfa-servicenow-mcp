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
