"""Tests for the non-blocking update-set awareness stamp (update_set_context).

The goal is full user awareness of WHERE a write lands — never blocking. These
pin: aligned (quiet), scope mismatch (loud ⚠), Default (loud ⚠), record-scope
unresolvable (base awareness only), basic auth (skip), and fail-open.
"""

from types import SimpleNamespace
from unittest.mock import patch

from servicenow_mcp.policies.write_guards import update_set_context
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _browser_server():
    config = ServerConfig(
        instance_url="https://dev.example.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig(username="jdoe")),
    )
    return SimpleNamespace(config=config, auth_manager=object())


def _basic_server():
    config = ServerConfig(
        instance_url="https://dev.example.com",
        auth=AuthConfig(type=AuthType.BASIC, basic={"username": "a", "password": "b"}),
    )
    return SimpleNamespace(config=config, auth_manager=object())


def test_basic_auth_skipped():
    # No network at all on basic auth — current update set is browser-session state.
    result = update_set_context(_basic_server(), "manage_script_include", {}, {"sys_id": "x"})
    assert result is None


def test_aligned_is_quiet():
    server = _browser_server()
    with (
        patch(
            "servicenow_mcp.tools.session_context_tools.get_current_update_set",
            return_value={"sys_id": "us-1", "name": "BPM Dev"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_one",
            side_effect=lambda srv, table, query, fields: {
                "sys_update_set": {"application": {"value": "bpm-scope", "display_value": "BPM"}},
                "sys_script_include": {"sys_scope": {"value": "bpm-scope", "display_value": "BPM"}},
            }.get(table),
        ),
    ):
        ctx = update_set_context(
            server,
            "manage_script_include",
            {"script_include_id": "si-1", "action": "update"},
            {"sys_id": "si-1"},
        )
    assert ctx["aligned"] is True
    assert ctx["update_set"] == "BPM Dev"
    assert ctx["record_scope"] == "BPM"
    # Nothing is off, so the stamp says nothing beyond the facts — a `note` here
    # is reserved for the cases that need a second look (Default / mismatch).
    assert "note" not in ctx


def test_scope_mismatch_is_loud():
    server = _browser_server()
    with (
        patch(
            "servicenow_mcp.tools.session_context_tools.get_current_update_set",
            return_value={"sys_id": "us-1", "name": "HBPM Pilot clone"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_one",
            side_effect=lambda srv, table, query, fields: {
                "sys_update_set": {"application": {"value": "hbpm-scope", "display_value": "HBPM"}},
                "sp_widget": {"sys_scope": {"value": "bpm-scope", "display_value": "BPM"}},
            }.get(table),
        ),
    ):
        ctx = update_set_context(
            server,
            "manage_portal_component",
            {"table": "sp_widget", "sys_id": "w-1", "action": "update_code"},
            {"sys_id": "w-1"},
        )
    assert ctx["aligned"] is False
    assert ctx["update_set_scope"] == "HBPM"
    assert ctx["record_scope"] == "BPM"
    assert "⚠" in ctx["note"]


def test_default_update_set_is_loud():
    server = _browser_server()
    with (
        patch(
            "servicenow_mcp.tools.session_context_tools.get_current_update_set",
            return_value={"sys_id": "us-def", "name": "Default"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_one",
            side_effect=lambda srv, table, query, fields: {
                "sys_update_set": {"application": {"value": "bpm-scope", "display_value": "BPM"}},
                "sp_widget": {"sys_scope": {"value": "bpm-scope", "display_value": "BPM"}},
            }.get(table),
        ),
    ):
        ctx = update_set_context(
            server,
            "manage_portal_component",
            {"table": "sp_widget", "sys_id": "w-1", "action": "update_code"},
            {"sys_id": "w-1"},
        )
    # Even though scopes match, Default is always flagged.
    assert ctx["aligned"] is False
    assert "Default" in ctx["note"]
    assert "⚠" in ctx["note"]


def test_record_unresolvable_gives_base_awareness():
    """When table+sys_id can't be resolved, still show WHERE writes land."""
    server = _browser_server()
    with (
        patch(
            "servicenow_mcp.tools.session_context_tools.get_current_update_set",
            return_value={"sys_id": "us-1", "name": "BPM Dev"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_one",
            side_effect=lambda srv, table, query, fields: (
                {"application": {"value": "bpm-scope", "display_value": "BPM"}}
                if table == "sys_update_set"
                else None
            ),
        ),
    ):
        ctx = update_set_context(server, "sn_write", {"action": "insert"}, {"no_sys_id": True})
    assert ctx["update_set"] == "BPM Dev"
    assert ctx["update_set_scope"] == "BPM"
    assert "record_scope" not in ctx  # couldn't resolve → no comparison
    assert "aligned" not in ctx
    assert "note" not in ctx  # nothing to flag — the two fields ARE the awareness


def test_no_current_update_set_returns_none():
    server = _browser_server()
    with patch(
        "servicenow_mcp.tools.session_context_tools.get_current_update_set",
        return_value=None,
    ):
        assert update_set_context(server, "manage_portal_component", {}, {}) is None


def test_fail_open_on_exception():
    server = _browser_server()
    with patch(
        "servicenow_mcp.tools.session_context_tools.get_current_update_set",
        side_effect=RuntimeError("boom"),
    ):
        assert update_set_context(server, "manage_portal_component", {}, {}) is None


# --- naming the set so it can be acted on ---------------------------------
# Two sets in different applications routinely carry the same name, and the
# picker labels its current selection "Name [Application]". A stamp that prints
# the label gives back a string sys_update_set does not store; a stamp that
# prints only a shared name identifies nothing at all.


def test_the_stamp_prefers_the_records_own_name_over_the_picker_label():
    server = _browser_server()
    with (
        patch(
            "servicenow_mcp.tools.session_context_tools.get_current_update_set",
            return_value={"sys_id": "us-1", "name": "Shared Name [My App]"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_one",
            side_effect=lambda srv, table, query, fields: {
                "sys_update_set": {
                    "name": "Shared Name",
                    "application": {"value": "scope-1", "display_value": "My App"},
                }
            }.get(table),
        ),
    ):
        ctx = update_set_context(server, "manage_script_include", {}, {"sys_id": "si-1"})

    # The label is not a name: update_set_name='Shared Name [My App]' resolves
    # to nothing, so handing it back breaks the round trip.
    assert ctx["update_set"] == "Shared Name"
    assert ctx["update_set_scope"] == "My App"


def test_the_stamp_always_carries_the_sys_id():
    # With a name shared by two sets, the sys_id is the only thing that says
    # which one this write landed in.
    server = _browser_server()
    with (
        patch(
            "servicenow_mcp.tools.session_context_tools.get_current_update_set",
            return_value={"sys_id": "us-1", "name": "Shared Name"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_one",
            side_effect=lambda srv, table, query, fields: {
                "sys_update_set": {
                    "name": "Shared Name",
                    "application": {"value": "scope-1", "display_value": "My App"},
                }
            }.get(table),
        ),
    ):
        ctx = update_set_context(server, "manage_script_include", {}, {"sys_id": "si-1"})

    assert ctx["update_set_id"] == "us-1"


def test_an_unreadable_set_record_falls_back_to_the_picker_name():
    # Fail-open: a name from the picker beats no name at all.
    server = _browser_server()
    with (
        patch(
            "servicenow_mcp.tools.session_context_tools.get_current_update_set",
            return_value={"sys_id": "us-1", "name": "Pilot"},
        ),
        patch("servicenow_mcp.policies.write_guards._fetch_one", return_value=None),
    ):
        ctx = update_set_context(server, "manage_script_include", {}, {"sys_id": "si-1"})

    assert ctx["update_set"] == "Pilot"
    assert ctx["update_set_id"] == "us-1"
