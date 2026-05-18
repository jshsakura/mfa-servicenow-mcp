"""Tests for write guards (servicenow_mcp.policies.write_guards).

Covers v1.12.28 guards:
  G6 — Flow Designer raw write block
  G7 — Publish-class extra confirmation
  read-only bypass

G1/G2/G5 require live ServiceNow lookups so they're exercised via the
mocked _fetch_current_update_set path.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest

from servicenow_mcp.policies import PolicyViolation, run_write_guards, strip_guard_fields
from servicenow_mcp.policies.write_guards import _is_publish_class, _is_read_only


class _MockServer:
    """Stand-in for ServiceNowMCP — guards only touch server.config /
    .auth_manager when fetching update set info, which is mocked below."""

    config = None
    auth_manager = None


_SERVER = _MockServer()


# ---------------------------------------------------------------------------
# Read-only / publish-class detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool, args, expected_read_only",
    [
        ("sn_query", {}, True),
        ("sn_aggregate", {}, True),
        ("sn_schema", {}, True),
        ("sn_discover", {}, True),
        ("sn_health", {}, True),
        ("sn_nl", {}, True),
        ("sn_nl", {"execute": True}, False),
        ("sn_write", {"table": "incident", "action": "create"}, False),
        ("sn_batch", {}, False),
        ("manage_workflow", {"action": "list"}, True),
        ("manage_workflow", {"action": "get"}, True),
        ("manage_workflow", {"action": "create"}, False),
        ("manage_flow_designer", {"action": "list"}, True),
        ("manage_flow_designer", {"action": "get_detail"}, True),
        ("manage_flow_designer", {"action": "save"}, False),
        ("manage_flow_designer", {"action": "checkout"}, False),
        ("manage_incident", {"action": "get"}, True),
        ("manage_incident", {"action": "create"}, False),
        ("update_remote_from_local", {}, False),
        ("publish_changeset", {}, False),
        ("audit_pending_changes", {}, True),
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
        ("manage_changeset", {"action": "get"}, False),
        ("manage_flow_designer", {"action": "save", "publish": True}, True),
        ("manage_flow_designer", {"action": "save", "publish": False}, False),
        ("manage_flow_designer", {"action": "save"}, False),
        ("manage_flow_designer", {"action": "checkout"}, False),
        ("sn_query", {}, False),
        ("sn_write", {}, False),
    ],
)
def test_is_publish_class(tool: str, args: Dict[str, Any], expected: bool) -> None:
    assert _is_publish_class(tool, args) is expected


# ---------------------------------------------------------------------------
# G6 — Flow Designer raw write block
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
    # Should not raise G6 — incident document is OK
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
    # sn_write to "incident" is fine from G6's perspective.
    # (G1/G2/G5 may block, but those need env vars / live data — skipped here.)
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
    # create is write but not publish-class
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
# Read-only bypass
# ---------------------------------------------------------------------------


def test_read_only_tools_skip_all_guards() -> None:
    # sn_query against sys_hub_flow — should NOT trigger G6
    run_write_guards(_SERVER, "sn_query", {"table": "sys_hub_flow"})
    # manage_flow_designer get_detail — read-only
    run_write_guards(_SERVER, "manage_flow_designer", {"action": "get_detail", "flow_id": "abc"})


# ---------------------------------------------------------------------------
# strip_guard_fields
# ---------------------------------------------------------------------------


def test_strip_guard_fields_removes_publish_and_large_set_flags() -> None:
    cleaned = strip_guard_fields(
        {
            "action": "save",
            "confirm_publish": "approve",
            "confirm_large_update_set": "approve",
            "flow_id": "abc",
        }
    )
    assert "confirm_publish" not in cleaned
    assert "confirm_large_update_set" not in cleaned
    assert cleaned == {"action": "save", "flow_id": "abc"}


# ---------------------------------------------------------------------------
# Master toggle
# ---------------------------------------------------------------------------


def test_guards_disabled_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICENOW_WRITE_GUARDS", "off")
    # Should NOT raise even though raw sys_hub_flow write is attempted
    run_write_guards(
        _SERVER, "sn_write", {"table": "sys_hub_flow", "action": "create", "fields": {}}
    )


# ---------------------------------------------------------------------------
# G1 (mocked) — active update set mismatch
# ---------------------------------------------------------------------------


def test_g1_active_update_set_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICENOW_ACTIVE_UPDATE_SET", "expected_sys_id")
    monkeypatch.setenv("SERVICENOW_ACTIVE_UPDATE_SET_NAME", "Expected Set")

    with patch(
        "servicenow_mcp.policies.write_guards._fetch_current_update_set",
        return_value={"sys_id": "wrong_sys_id", "name": "Wrong Set"},
    ):
        with pytest.raises(PolicyViolation, match=r"\[G1\].*Active update set mismatch"):
            run_write_guards(
                _SERVER, "sn_write", {"table": "incident", "action": "create", "fields": {}}
            )


def test_g1_passes_when_active_us_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVICENOW_ACTIVE_UPDATE_SET", "expected_sys_id")
    with (
        patch(
            "servicenow_mcp.policies.write_guards._fetch_current_update_set",
            return_value={"sys_id": "expected_sys_id", "name": "Expected Set"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_update_set_size",
            return_value=10,
        ),
    ):
        # Should pass
        run_write_guards(
            _SERVER, "sn_write", {"table": "incident", "action": "create", "fields": {}}
        )


# ---------------------------------------------------------------------------
# G2 (mocked) — name denylist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "us_name",
    [
        "[NOT USE] Old Backup",
        "[notuse] thing",
        "Default Update Set",
        "stash_temp",
        "Preview only",
        "archive_2024",
        "Deprecated DMR work",
    ],
)
def test_g2_denylist_blocks(us_name: str) -> None:
    with patch(
        "servicenow_mcp.policies.write_guards._fetch_current_update_set",
        return_value={"sys_id": "x", "name": us_name},
    ):
        with pytest.raises(PolicyViolation, match=r"\[G2\]"):
            run_write_guards(
                _SERVER, "sn_write", {"table": "incident", "action": "create", "fields": {}}
            )


def test_g2_allows_clean_name() -> None:
    with (
        patch(
            "servicenow_mcp.policies.write_guards._fetch_current_update_set",
            return_value={"sys_id": "x", "name": "DMR20 Sandbox Work"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_update_set_size",
            return_value=10,
        ),
    ):
        run_write_guards(
            _SERVER, "sn_write", {"table": "incident", "action": "create", "fields": {}}
        )


# ---------------------------------------------------------------------------
# G5 (mocked) — update set size
# ---------------------------------------------------------------------------


def test_g5_blocks_at_hard_threshold() -> None:
    with (
        patch(
            "servicenow_mcp.policies.write_guards._fetch_current_update_set",
            return_value={"sys_id": "x", "name": "Working Set"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_update_set_size",
            return_value=6000,
        ),
    ):
        with pytest.raises(PolicyViolation, match=r"\[G5\].*hard block"):
            run_write_guards(
                _SERVER, "sn_write", {"table": "incident", "action": "create", "fields": {}}
            )


def test_g5_warn_threshold_requires_extra_confirm() -> None:
    with (
        patch(
            "servicenow_mcp.policies.write_guards._fetch_current_update_set",
            return_value={"sys_id": "x", "name": "Working Set"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_update_set_size",
            return_value=1500,
        ),
    ):
        with pytest.raises(PolicyViolation, match=r"\[G5\].*warning"):
            run_write_guards(
                _SERVER, "sn_write", {"table": "incident", "action": "create", "fields": {}}
            )


def test_g5_warn_threshold_passes_with_confirm() -> None:
    with (
        patch(
            "servicenow_mcp.policies.write_guards._fetch_current_update_set",
            return_value={"sys_id": "x", "name": "Working Set"},
        ),
        patch(
            "servicenow_mcp.policies.write_guards._fetch_update_set_size",
            return_value=1500,
        ),
    ):
        run_write_guards(
            _SERVER,
            "sn_write",
            {
                "table": "incident",
                "action": "create",
                "fields": {},
                "confirm_large_update_set": "approve",
            },
        )
