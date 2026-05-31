"""Tests for write guards (servicenow_mcp.policies.write_guards).

Guards covered (v1.12.28.1 — simplified):
  G3 — Concurrent edit detection on sn_write update/delete
  G6 — Flow Designer raw write block
  G7 — Publish-class extra confirmation
  read-only bypass + master-toggle
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest

from servicenow_mcp.policies import (
    PolicyViolation,
    run_post_confirm_guards,
    run_write_guards,
    strip_guard_fields,
)
from servicenow_mcp.policies.write_guards import _is_publish_class, _is_read_only


class _MockAuth:
    username = "dev.user@example.com"


class _MockConfig:
    auth = _MockAuth()


class _MockServer:
    config = _MockConfig()
    auth_manager = _MockAuth()


_SERVER = _MockServer()


def _utc_iso_minus_min(minutes: int) -> str:
    """Return 'YYYY-MM-DD HH:MM:SS' minutes ago (UTC)."""
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return ts.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Read-only / publish-class detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool, args, expected_read_only",
    [
        ("sn_query", {}, True),
        ("sn_aggregate", {}, True),
        ("sn_schema", {}, True),
        ("sn_health", {}, True),
        ("sn_write", {"table": "incident", "action": "create"}, False),
        ("manage_workflow", {"action": "list"}, True),
        ("manage_workflow", {"action": "create"}, False),
        ("manage_flow_designer", {"action": "list"}, True),
        ("manage_flow_designer", {"action": "save"}, False),
        ("manage_flow_designer", {"action": "get_detail"}, True),
        ("update_remote_from_local", {}, False),
        ("publish_changeset", {}, False),
        ("get_widget_bundle", {}, True),
        ("download_app_sources", {}, True),
    ],
)
def test_is_read_only(tool: str, args: Dict[str, Any], expected_read_only: bool) -> None:
    assert _is_read_only(tool, args) is expected_read_only


@pytest.mark.parametrize(
    "tool, args, expected",
    [
        ("publish_changeset", {}, True),
        ("commit_changeset", {}, True),
        ("update_remote_from_local", {}, True),
        ("approve_change", {}, True),
        ("submit_change_for_approval", {}, True),
        ("manage_changeset", {"action": "publish"}, True),
        ("manage_changeset", {"action": "commit"}, True),
        ("manage_changeset", {"action": "create"}, False),
        ("manage_flow_designer", {"action": "save", "publish": True}, True),
        ("manage_flow_designer", {"action": "save", "publish": False}, False),
        ("manage_flow_designer", {"action": "save"}, False),
        ("sn_query", {}, False),
        ("sn_write", {}, False),
    ],
)
def test_is_publish_class(tool: str, args: Dict[str, Any], expected: bool) -> None:
    assert _is_publish_class(tool, args) is expected


# ---------------------------------------------------------------------------
# G6 — Flow Designer raw write
# ---------------------------------------------------------------------------


def test_g6_blocks_sys_hub_flow_via_sn_write() -> None:
    with pytest.raises(PolicyViolation, match=r"\[G6\]"):
        run_write_guards(
            _SERVER, "sn_write", {"table": "sys_hub_flow", "action": "create", "fields": {}}
        )


def test_g6_blocks_action_instance() -> None:
    with pytest.raises(PolicyViolation, match=r"\[G6\]"):
        run_write_guards(
            _SERVER,
            "sn_write",
            {"table": "sys_hub_action_instance", "action": "create", "fields": {}},
        )


def test_g6_blocks_variable_value_for_flow_document() -> None:
    with pytest.raises(PolicyViolation, match=r"\[G6\].*sys_variable_value"):
        run_write_guards(
            _SERVER,
            "sn_write",
            {
                "table": "sys_variable_value",
                "action": "create",
                "fields": {"document": "sys_hub_action_instance"},
            },
        )


def test_g6_allows_variable_value_for_non_flow_document() -> None:
    run_write_guards(
        _SERVER,
        "sn_write",
        {
            "table": "sys_variable_value",
            "action": "create",
            "fields": {"document": "incident"},
        },
    )


def test_g6_allows_sn_write_to_unrelated_table() -> None:
    run_write_guards(_SERVER, "sn_write", {"table": "incident", "action": "create", "fields": {}})


# ---------------------------------------------------------------------------
# G7 — Publish-class extra confirm
# ---------------------------------------------------------------------------


def test_g7_blocks_publish_changeset_without_confirm_publish() -> None:
    with pytest.raises(PolicyViolation, match=r"\[G7\]"):
        run_write_guards(_SERVER, "publish_changeset", {"changeset_id": "abc"})


def test_g7_allows_publish_changeset_with_confirm_publish() -> None:
    run_write_guards(
        _SERVER, "publish_changeset", {"changeset_id": "abc", "confirm_publish": "approve"}
    )


def test_g7_blocks_update_remote_from_local() -> None:
    with pytest.raises(PolicyViolation, match=r"\[G7\]"):
        run_write_guards(_SERVER, "update_remote_from_local", {})


def test_g7_blocks_manage_changeset_publish() -> None:
    with pytest.raises(PolicyViolation, match=r"\[G7\]"):
        run_write_guards(_SERVER, "manage_changeset", {"action": "publish"})


def test_g7_allows_manage_changeset_create() -> None:
    run_write_guards(_SERVER, "manage_changeset", {"action": "create", "name": "x"})


def test_g7_blocks_manage_flow_designer_save_with_publish() -> None:
    with pytest.raises(PolicyViolation, match=r"\[G7\]"):
        run_write_guards(
            _SERVER, "manage_flow_designer", {"action": "save", "flow_id": "abc", "publish": True}
        )


def test_g7_allows_manage_flow_designer_save_without_publish() -> None:
    run_write_guards(
        _SERVER,
        "manage_flow_designer",
        {"action": "save", "flow_id": "abc", "publish": False},
    )


# ---------------------------------------------------------------------------
# G3 — Concurrent edit detection
# ---------------------------------------------------------------------------


def test_g3_blocks_when_other_user_edited_recently() -> None:
    """Within the 10-min window, other user's edit blocks our update."""
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": "alice@example.com",
            "sys_updated_on": _utc_iso_minus_min(3),
        },
    ):
        with pytest.raises(PolicyViolation, match=r"(?s)\[G3\].*alice"):
            run_post_confirm_guards(
                _SERVER,
                "sn_write",
                {"table": "incident", "action": "update", "sys_id": "xyz", "fields": {}},
            )


def test_g3_allows_when_my_own_recent_edit() -> None:
    """My own recent edit should not block."""
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": _MockAuth.username,
            "sys_updated_on": _utc_iso_minus_min(3),
        },
    ):
        run_post_confirm_guards(
            _SERVER,
            "sn_write",
            {"table": "incident", "action": "update", "sys_id": "xyz", "fields": {}},
        )


def test_g3_allows_when_other_user_edit_is_old() -> None:
    """Outside window, other user's edit should not block."""
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": "alice@example.com",
            "sys_updated_on": _utc_iso_minus_min(60),  # 1 hour ago
        },
    ):
        run_post_confirm_guards(
            _SERVER,
            "sn_write",
            {"table": "incident", "action": "update", "sys_id": "xyz", "fields": {}},
        )


def test_g3_only_applies_to_update_and_delete() -> None:
    """Create has no target record to check — skip."""
    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
        run_post_confirm_guards(
            _SERVER,
            "sn_write",
            {"table": "incident", "action": "create", "fields": {}},
        )
        mocked_fetch.assert_not_called()


def test_g3_only_applies_to_sn_write() -> None:
    """G3 is sn_write-specific. A manage_* CREATE has no existing record, so no
    guard (G3 or G8-registry) does an audit fetch."""
    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
        run_post_confirm_guards(_SERVER, "manage_changeset", {"action": "create", "name": "x"})
        mocked_fetch.assert_not_called()


def test_g3_fails_open_on_missing_audit_data() -> None:
    """If audit fetch returns None, don't block (fail-open)."""
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value=None,
    ):
        run_post_confirm_guards(
            _SERVER,
            "sn_write",
            {"table": "incident", "action": "update", "sys_id": "xyz", "fields": {}},
        )


def test_g3_custom_window_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Window configurable via env var."""
    monkeypatch.setenv("SERVICENOW_CONCURRENT_EDIT_WINDOW_MIN", "60")
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": "alice@example.com",
            "sys_updated_on": _utc_iso_minus_min(30),
        },
    ):
        with pytest.raises(PolicyViolation, match=r"\[G3\]"):
            run_post_confirm_guards(
                _SERVER,
                "sn_write",
                {"table": "incident", "action": "update", "sys_id": "xyz", "fields": {}},
            )


# ---------------------------------------------------------------------------
# Read-only bypass + master toggle
# ---------------------------------------------------------------------------


def test_read_only_tools_skip_all_guards() -> None:
    run_write_guards(_SERVER, "sn_query", {"table": "sys_hub_flow"})
    run_write_guards(_SERVER, "manage_flow_designer", {"action": "get_detail", "flow_id": "abc"})


def test_guards_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICENOW_WRITE_GUARDS", "off")
    # Even raw sys_hub_flow write goes through
    run_write_guards(
        _SERVER, "sn_write", {"table": "sys_hub_flow", "action": "create", "fields": {}}
    )


# ---------------------------------------------------------------------------
# strip_guard_fields
# ---------------------------------------------------------------------------


def test_strip_guard_fields_removes_confirm_publish() -> None:
    cleaned = strip_guard_fields({"action": "save", "confirm_publish": "approve", "flow_id": "abc"})
    assert "confirm_publish" not in cleaned
    assert cleaned == {"action": "save", "flow_id": "abc"}


# ---------------------------------------------------------------------------
# G8 — generalized concurrent-edit: same protection for any write tool that
# names its target via table + sys_id (portal CRUD, etc.). Never overwrite
# someone else's concurrent edit blindly.
# ---------------------------------------------------------------------------


def _portal_update_args() -> Dict[str, Any]:
    return {"table": "sp_widget", "sys_id": "wid-1", "update_data": {"css": ".a{}"}}


def test_g8_blocks_portal_update_when_other_user_edited_recently() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": "alice@example.com",
            "sys_updated_on": _utc_iso_minus_min(3),
        },
    ):
        with pytest.raises(PolicyViolation, match=r"(?s)\[G8\].*alice"):
            run_post_confirm_guards(_SERVER, "update_portal_component", _portal_update_args())


def test_g8_allows_my_own_recent_edit() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": _MockAuth.username,
            "sys_updated_on": _utc_iso_minus_min(2),
        },
    ):
        run_post_confirm_guards(_SERVER, "update_portal_component", _portal_update_args())


def test_g8_allows_old_other_user_edit() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": "alice@example.com",
            "sys_updated_on": _utc_iso_minus_min(90),
        },
    ):
        run_post_confirm_guards(_SERVER, "update_portal_component", _portal_update_args())


def test_g8_skips_when_no_explicit_table_and_sys_id() -> None:
    """Generic G8 (non-registry tool): without table+sys_id it can't identify the
    record, so it must NOT fetch/guess — fail-open."""
    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
        run_post_confirm_guards(_SERVER, "update_portal_component", {"update_data": {}})
        mocked_fetch.assert_not_called()


def test_g8_does_not_double_fetch_for_sn_write() -> None:
    """sn_write is handled by G3; G8 must skip it (no duplicate audit fetch)."""
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value=None,
    ) as mocked_fetch:
        run_post_confirm_guards(
            _SERVER,
            "sn_write",
            {"table": "incident", "action": "update", "sys_id": "xyz", "fields": {}},
        )
        assert mocked_fetch.call_count == 1  # G3 only, not G3 + G8


def test_g8_fails_open_on_missing_audit() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value=None,
    ):
        run_post_confirm_guards(_SERVER, "update_portal_component", _portal_update_args())


def test_concurrent_guard_off_switch_disables_g3_and_g8() -> None:
    import os
    from unittest.mock import patch as _patch

    with _patch.dict(os.environ, {"SERVICENOW_CONCURRENT_EDIT_GUARD": "off"}):
        with _patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
            run_post_confirm_guards(_SERVER, "update_portal_component", _portal_update_args())
            run_post_confirm_guards(
                _SERVER,
                "sn_write",
                {"table": "incident", "action": "update", "sys_id": "x", "fields": {}},
            )
            mocked_fetch.assert_not_called()


# ---------------------------------------------------------------------------
# G8 registry — concurrent-edit for manage_* tools that identify the record by
# a tool-specific id arg (incident_id, change_id, workflow_id, …).
# ---------------------------------------------------------------------------


def test_g8_registry_blocks_manage_incident_update_other_user() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": "alice@example.com",
            "sys_updated_on": _utc_iso_minus_min(2),
        },
    ):
        with pytest.raises(PolicyViolation, match=r"(?s)\[G8\].*alice"):
            run_post_confirm_guards(
                _SERVER,
                "manage_incident",
                {"action": "update", "incident_id": "INC0001", "short_description": "x"},
            )


def test_g8_registry_allows_my_own_edit() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": _MockAuth.username,
            "sys_updated_on": _utc_iso_minus_min(2),
        },
    ):
        run_post_confirm_guards(
            _SERVER,
            "manage_workflow",
            {"action": "update", "workflow_id": "wf-1", "name": "x"},
        )


def test_g8_registry_skips_create_action() -> None:
    """Create makes a new record — nothing to clash with; no audit fetch."""
    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
        run_post_confirm_guards(_SERVER, "manage_user", {"action": "create", "user_name": "newbie"})
        mocked_fetch.assert_not_called()


def test_g8_registry_skips_when_id_arg_missing() -> None:
    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
        run_post_confirm_guards(_SERVER, "manage_changeset", {"action": "update"})
        mocked_fetch.assert_not_called()


def test_g8_registry_or_query_matches_sys_id_or_number() -> None:
    """incident_id may be a sys_id OR an INC number → audit query ORs both."""
    captured = {}

    def _fake_fetch(ctx, table, query):
        captured["table"] = table
        captured["query"] = query
        return None  # fail-open; we only inspect the query

    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit", _fake_fetch):
        run_post_confirm_guards(
            _SERVER, "manage_incident", {"action": "resolve", "incident_id": "INC0009"}
        )
    assert captured["table"] == "incident"
    assert captured["query"] == "sys_id=INC0009^ORnumber=INC0009"


# ---------------------------------------------------------------------------
# G9 — duplicate-name create block (only for tables where a duplicate name is a
# real clash). Post-confirm, fail-open, overridable with allow_duplicate='true'.
# ---------------------------------------------------------------------------


def test_g9_blocks_create_when_name_exists() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_existing_by_name",
        return_value={"sys_id": "us-1", "name": "Sprint 5"},
    ):
        with pytest.raises(PolicyViolation, match=r"(?s)\[G9\].*already exists"):
            run_post_confirm_guards(
                _SERVER, "manage_changeset", {"action": "create", "name": "Sprint 5"}
            )


def test_g9_allows_create_when_name_is_unique() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_existing_by_name",
        return_value=None,
    ):
        run_post_confirm_guards(
            _SERVER, "manage_workflow", {"action": "create", "name": "Fresh WF"}
        )


def test_g9_override_with_allow_duplicate() -> None:
    """Explicit allow_duplicate='true' creates anyway — no existence check at all."""
    with patch("servicenow_mcp.policies.write_guards._fetch_existing_by_name") as mocked:
        run_post_confirm_guards(
            _SERVER,
            "manage_group",
            {"action": "create", "name": "Admins", "allow_duplicate": "true"},
        )
        mocked.assert_not_called()


def test_g9_fails_open_when_existence_check_unavailable() -> None:
    """Permission-flexible: if the existence read can't run, never block."""
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_existing_by_name",
        return_value=None,  # _fetch returns None on ACL/transient failure
    ):
        run_post_confirm_guards(_SERVER, "manage_user", {"action": "create", "user_name": "jdoe"})


def test_g9_skips_non_create_actions() -> None:
    with patch("servicenow_mcp.policies.write_guards._fetch_existing_by_name") as mocked:
        run_post_confirm_guards(
            _SERVER, "manage_changeset", {"action": "update", "changeset_id": "abc"}
        )
        mocked.assert_not_called()


def test_g9_skips_unregistered_tool() -> None:
    """rm_story/rm_epic style creates (duplicate short_description is normal) are
    NOT registered → never blocked."""
    with patch("servicenow_mcp.policies.write_guards._fetch_existing_by_name") as mocked:
        run_post_confirm_guards(
            _SERVER, "manage_story", {"action": "create", "short_description": "Dup title"}
        )
        mocked.assert_not_called()


def test_g9_skips_when_name_missing() -> None:
    with patch("servicenow_mcp.policies.write_guards._fetch_existing_by_name") as mocked:
        run_post_confirm_guards(_SERVER, "manage_changeset", {"action": "create"})
        mocked.assert_not_called()


def test_strip_post_confirm_fields_removes_allow_duplicate() -> None:
    from servicenow_mcp.policies.write_guards import strip_post_confirm_fields

    cleaned = strip_post_confirm_fields(
        {"action": "create", "name": "x", "allow_duplicate": "true"}
    )
    assert "allow_duplicate" not in cleaned
    assert cleaned == {"action": "create", "name": "x"}
