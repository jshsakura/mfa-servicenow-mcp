"""Response-shape snapshots for manage_ui_policy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.ui_policy_tools import ManageUiPolicyParams, manage_ui_policy

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots" / "ui_policy"


def _assert_snapshot(name: str, actual: dict) -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOTS_DIR / f"{name}.json"
    actual_json = json.dumps(actual, sort_keys=True, indent=2, ensure_ascii=False, default=str)
    if not snap_path.exists():
        snap_path.write_text(actual_json + "\n", encoding="utf-8")
        pytest.skip(f"snapshot {name} created — re-run pytest to assert")
    expected = snap_path.read_text(encoding="utf-8").rstrip("\n")
    assert actual_json == expected, (
        f"\nSnapshot drift for {name}.\n"
        f"  Snapshot file: {snap_path}\n"
        f"  Response shape contract break — review the diff carefully.\n"
    )


def _mock_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    mock.raise_for_status = MagicMock()
    return mock


@pytest.fixture
def auth(mock_auth):
    mock_auth.make_request = MagicMock()
    return mock_auth


def test_snap_manage_ui_policy_create(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {
            "result": {
                "sys_id": "uip_001",
                "short_description": "Hide field on close",
                "table": "incident",
            }
        }
    )
    with patch("servicenow_mcp.services.ui_policy.invalidate_query_cache"):
        result = manage_ui_policy(
            mock_config,
            auth,
            ManageUiPolicyParams(
                action="create",
                table="incident",
                short_description="Hide field on close",
                conditions="state=6",
            ),
        )
    _assert_snapshot("manage_ui_policy_create", result)


def test_snap_manage_ui_policy_add_action(mock_config, auth):
    with patch("servicenow_mcp.services.ui_policy.sn_query_page") as mock_query:
        mock_query.return_value = (
            [{"sys_id": "uip_001", "short_description": "Hide on close", "table": "incident"}],
            1,
        )
        auth.make_request.return_value = _mock_response(
            {
                "result": {
                    "sys_id": "act_001",
                    "visible": "false",
                    "mandatory": None,
                    "disabled": None,
                }
            }
        )
        with patch("servicenow_mcp.services.ui_policy.invalidate_query_cache"):
            result = manage_ui_policy(
                mock_config,
                auth,
                ManageUiPolicyParams(
                    action="add_action",
                    ui_policy="uip_001",
                    field="resolution_code",
                    visible="false",
                ),
            )
    _assert_snapshot("manage_ui_policy_add_action", result)


def test_snap_manage_ui_policy_create_failure(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("boom")
    with patch("servicenow_mcp.services.ui_policy.invalidate_query_cache"):
        result = manage_ui_policy(
            mock_config,
            auth,
            ManageUiPolicyParams(
                action="create",
                table="incident",
                short_description="X",
            ),
        )
    _assert_snapshot("manage_ui_policy_create_failure", result)
