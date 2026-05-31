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

from servicenow_mcp.policies import PolicyViolation, run_write_guards, strip_guard_fields
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
            run_write_guards(
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
        run_write_guards(
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
        run_write_guards(
            _SERVER,
            "sn_write",
            {"table": "incident", "action": "update", "sys_id": "xyz", "fields": {}},
        )


def test_g3_only_applies_to_update_and_delete() -> None:
    """Create has no target record to check — skip."""
    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
        run_write_guards(
            _SERVER,
            "sn_write",
            {"table": "incident", "action": "create", "fields": {}},
        )
        mocked_fetch.assert_not_called()


def test_g3_only_applies_to_sn_write() -> None:
    """manage_X writes not yet covered by G3 — that's OK in v1.12.28.1."""
    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
        run_write_guards(_SERVER, "manage_changeset", {"action": "update", "changeset_id": "abc"})
        mocked_fetch.assert_not_called()


def test_g3_fails_open_on_missing_audit_data() -> None:
    """If audit fetch returns None, don't block (fail-open)."""
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value=None,
    ):
        run_write_guards(
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
            run_write_guards(
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
            run_write_guards(_SERVER, "update_portal_component", _portal_update_args())


def test_g8_allows_my_own_recent_edit() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": _MockAuth.username,
            "sys_updated_on": _utc_iso_minus_min(2),
        },
    ):
        run_write_guards(_SERVER, "update_portal_component", _portal_update_args())


def test_g8_allows_old_other_user_edit() -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value={
            "sys_updated_by": "alice@example.com",
            "sys_updated_on": _utc_iso_minus_min(90),
        },
    ):
        run_write_guards(_SERVER, "update_portal_component", _portal_update_args())


def test_g8_skips_when_no_explicit_table_and_sys_id() -> None:
    """Conservative: without table+sys_id, G8 can't identify the record, so it
    must NOT fetch/guess — fail-open (covered later by a number-based registry)."""
    with patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
        run_write_guards(_SERVER, "manage_change", {"action": "update", "number": "CHG001"})
        mocked_fetch.assert_not_called()


def test_g8_does_not_double_fetch_for_sn_write() -> None:
    """sn_write is handled by G3; G8 must skip it (no duplicate audit fetch)."""
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_record_audit",
        return_value=None,
    ) as mocked_fetch:
        run_write_guards(
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
        run_write_guards(_SERVER, "update_portal_component", _portal_update_args())


def test_concurrent_guard_off_switch_disables_g3_and_g8() -> None:
    import os
    from unittest.mock import patch as _patch

    with _patch.dict(os.environ, {"SERVICENOW_CONCURRENT_EDIT_GUARD": "off"}):
        with _patch("servicenow_mcp.policies.write_guards._fetch_record_audit") as mocked_fetch:
            run_write_guards(_SERVER, "update_portal_component", _portal_update_args())
            run_write_guards(
                _SERVER,
                "sn_write",
                {"table": "incident", "action": "update", "sys_id": "x", "fields": {}},
            )
            mocked_fetch.assert_not_called()
