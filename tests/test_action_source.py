"""Tests for manage_flow_designer get_action_source (custom action script read).

The internal Script-step body of a custom Flow Designer action lives in
sys_variable_value keyed by the step instance — not on the action definition.
get_action_source walks definition -> sys_hub_step_instance -> sys_variable_value.
"""

from unittest.mock import patch

import pytest

from servicenow_mcp.tools.flow_designer_tools import (
    SCRIPT_STEP_VAR_SYSID,
    GetActionSourceParams,
    get_action_source,
)
from servicenow_mcp.tools.flow_tools import ManageFlowDesignerParams, manage_flow_designer
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

ACTION_SID = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
SCRIPT_BODY = (
    "(function execute(inputs, outputs) {\n  outputs.success = 'true';\n})(inputs, outputs);"
)


@pytest.fixture()
def cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def auth():
    from unittest.mock import MagicMock

    from servicenow_mcp.auth.auth_manager import AuthManager

    return MagicMock(spec=AuthManager)


def _def_row(**over):
    row = {
        "sys_id": ACTION_SID,
        "name": "My Action",
        "internal_name": "my_action",
        "master_snapshot": "",
        "latest_snapshot": "",
        "sys_scope": "x_my_app",
    }
    row.update(over)
    return row


def _PATCH():
    return patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")


def test_resolve_by_sys_id_returns_script(cfg, auth):
    with _PATCH() as q:
        q.side_effect = [
            ([_def_row()], 1),  # definition lookup
            (
                [
                    {
                        "sys_id": "step1",
                        "label": "Script step",
                        "order": "1",
                        "step_type": "stype",
                        "action": ACTION_SID,
                    }
                ],
                1,
            ),  # step instances
            (
                [
                    {
                        "document_key": "step1",
                        "variable": SCRIPT_STEP_VAR_SYSID,
                        "value": SCRIPT_BODY,
                    }
                ],
                1,
            ),  # vars
        ]
        result = get_action_source(cfg, auth, GetActionSourceParams(action_ref=ACTION_SID))

    assert result["success"] is True
    assert result["action"]["internal_name"] == "my_action"
    assert result["step_count"] == 1
    step = result["steps"][0]
    assert step["script"] == SCRIPT_BODY
    assert step["is_live"] is True


def test_not_found_short_circuits(cfg, auth):
    with _PATCH() as q:
        # not a sys_id -> exact then LIKE, both empty; no step query issued
        q.side_effect = [([], 0), ([], 0)]
        result = get_action_source(cfg, auth, GetActionSourceParams(action_ref="nope"))

    assert result["success"] is False
    assert "not found" in result["error"].lower()
    assert q.call_count == 2


def test_include_versions_widens_step_query(cfg, auth):
    with _PATCH() as q:
        q.side_effect = [
            ([_def_row(master_snapshot="m1", latest_snapshot="l1")], 1),
            ([], 0),  # steps (content irrelevant here)
        ]
        get_action_source(
            cfg, auth, GetActionSourceParams(action_ref=ACTION_SID, include_versions=True)
        )
        step_call = q.call_args_list[1]
    query = step_call.kwargs["query"]
    assert ACTION_SID in query and "m1" in query and "l1" in query


def test_fallback_to_longest_value_when_no_script_var(cfg, auth):
    long_val = "x" * 80
    with _PATCH() as q:
        q.side_effect = [
            ([_def_row()], 1),
            (
                [
                    {
                        "sys_id": "step1",
                        "label": "REST step",
                        "order": "1",
                        "step_type": "st",
                        "action": ACTION_SID,
                    }
                ],
                1,
            ),
            (
                [
                    {"document_key": "step1", "variable": "other", "value": long_val},
                    {"document_key": "step1", "variable": "v2", "value": "short"},
                ],
                1,
            ),
        ]
        result = get_action_source(cfg, auth, GetActionSourceParams(action_ref=ACTION_SID))

    assert result["steps"][0]["script"] == long_val


def test_live_script_present_marks_running_source_live(cfg, auth):
    with _PATCH() as q:
        q.side_effect = [
            ([_def_row(master_snapshot="m1", latest_snapshot="l1")], 1),
            (
                [
                    {
                        "sys_id": "step1",
                        "label": "Script step",
                        "order": "1",
                        "step_type": "st",
                        "action": ACTION_SID,
                    }
                ],
                1,
            ),
            (
                [
                    {
                        "document_key": "step1",
                        "variable": SCRIPT_STEP_VAR_SYSID,
                        "value": SCRIPT_BODY,
                    }
                ],
                1,
            ),
        ]
        result = get_action_source(cfg, auth, GetActionSourceParams(action_ref=ACTION_SID))

    # Live body present -> no snapshot round-trip, running source is live.
    assert result["live_script_present"] is True
    assert result["auto_recovered_from_snapshot"] is False
    assert result["running_source"] == "live"
    assert result["steps"][0]["source"] == "live"
    assert q.call_count == 3  # def + steps + vars, no fallback


def test_empty_live_script_auto_recovers_from_snapshot(cfg, auth):
    """The user's scenario: live definition step is empty; the running code is
    frozen in the published snapshot. The tool must surface it without asking
    for include_versions and flag that the live definition is empty."""
    with _PATCH() as q:
        q.side_effect = [
            ([_def_row(master_snapshot="m1", latest_snapshot="l1")], 1),
            # live step exists but its script body was cleared (sandbox testing)
            (
                [
                    {
                        "sys_id": "live_step",
                        "label": "Script step",
                        "order": "1",
                        "step_type": "st",
                        "action": ACTION_SID,
                    }
                ],
                1,
            ),
            (
                [{"document_key": "live_step", "variable": SCRIPT_STEP_VAR_SYSID, "value": ""}],
                1,
            ),  # empty body
            # auto-fallback: snapshot step carries the real running script
            (
                [
                    {
                        "sys_id": "snap_step",
                        "label": "Script step",
                        "order": "1",
                        "step_type": "st",
                        "action": "l1",
                    }
                ],
                1,
            ),
            (
                [
                    {
                        "document_key": "snap_step",
                        "variable": SCRIPT_STEP_VAR_SYSID,
                        "value": SCRIPT_BODY,
                    }
                ],
                1,
            ),
        ]
        result = get_action_source(cfg, auth, GetActionSourceParams(action_ref=ACTION_SID))

    assert result["live_script_present"] is False
    assert result["auto_recovered_from_snapshot"] is True
    assert result["running_source"] == "snapshot:latest"
    assert result["running_step_sys_id"] == "snap_step"
    assert "EMPTY" in result["diagnosis"] and "Republish" in result["diagnosis"]
    snap_step = next(s for s in result["steps"] if s["sys_id"] == "snap_step")
    assert snap_step["source"] == "snapshot:latest"
    assert snap_step["script"] == SCRIPT_BODY
    # fallback query targeted the snapshot bases, not the definition
    fallback_query = q.call_args_list[3].kwargs["query"]
    assert "l1" in fallback_query and "m1" in fallback_query and ACTION_SID not in fallback_query


def test_no_fallback_when_no_snapshot_exists(cfg, auth):
    with _PATCH() as q:
        q.side_effect = [
            ([_def_row()], 1),  # no snapshots on the definition
            (
                [
                    {
                        "sys_id": "live_step",
                        "label": "Script step",
                        "order": "1",
                        "step_type": "st",
                        "action": ACTION_SID,
                    }
                ],
                1,
            ),
            ([{"document_key": "live_step", "variable": SCRIPT_STEP_VAR_SYSID, "value": ""}], 1),
        ]
        result = get_action_source(cfg, auth, GetActionSourceParams(action_ref=ACTION_SID))

    assert result["live_script_present"] is False
    assert result["auto_recovered_from_snapshot"] is False
    assert result["running_source"] is None
    assert q.call_count == 3  # nothing to fall back to


def test_router_routes_get_action_source(cfg, auth):
    with patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page") as q:
        q.side_effect = [
            ([_def_row()], 1),
            (
                [
                    {
                        "sys_id": "step1",
                        "label": "Script step",
                        "order": "1",
                        "step_type": "st",
                        "action": ACTION_SID,
                    }
                ],
                1,
            ),
            (
                [
                    {
                        "document_key": "step1",
                        "variable": SCRIPT_STEP_VAR_SYSID,
                        "value": SCRIPT_BODY,
                    }
                ],
                1,
            ),
        ]
        result = manage_flow_designer(
            cfg, auth, ManageFlowDesignerParams(action="get_action_source", action_ref=ACTION_SID)
        )
    assert result["success"] is True
    assert result["steps"][0]["script"] == SCRIPT_BODY


def test_router_requires_action_ref():
    with pytest.raises(ValueError, match="action_ref"):
        ManageFlowDesignerParams(action="get_action_source")
