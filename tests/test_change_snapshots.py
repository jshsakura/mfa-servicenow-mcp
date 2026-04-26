"""Response-shape snapshots for manage_change.

Pin manage_change response shapes so Phase 4.0 service extraction produces
zero diffs. First run creates snapshots; subsequent runs assert byte-for-byte.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots" / "change"


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
        f"  If the change is intentional, delete the snapshot and re-run.\n"
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


def test_snap_manage_change_create(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {"result": {"sys_id": "ch_001", "number": "CHG0001", "state": "new"}}
    )
    with patch("servicenow_mcp.services.change.invalidate_query_cache"):
        result = manage_change(
            mock_config,
            auth,
            ManageChangeParams(
                action="create",
                short_description="Patch DB",
                type="normal",
                risk="low",
                impact="low",
            ),
        )
    _assert_snapshot("manage_change_create", result)


def test_snap_manage_change_update(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {"result": {"sys_id": "ch_001", "state": "2", "short_description": "Patch DB v2"}}
    )
    with patch("servicenow_mcp.services.change.invalidate_query_cache"):
        result = manage_change(
            mock_config,
            auth,
            ManageChangeParams(
                action="update",
                change_id="ch_001",
                state="2",
                short_description="Patch DB v2",
                work_notes="approved by CAB",
            ),
        )
    _assert_snapshot("manage_change_update", result)


def test_snap_manage_change_add_task(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {"result": {"sys_id": "tsk_001", "number": "CTASK0001"}}
    )
    with patch("servicenow_mcp.services.change.invalidate_query_cache"):
        result = manage_change(
            mock_config,
            auth,
            ManageChangeParams(
                action="add_task",
                change_id="ch_001",
                task_short_description="Run migration",
                task_assigned_to="user_42",
            ),
        )
    _assert_snapshot("manage_change_add_task", result)


def test_snap_manage_change_create_failure(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("boom: connection refused")
    with patch("servicenow_mcp.services.change.invalidate_query_cache"):
        result = manage_change(
            mock_config,
            auth,
            ManageChangeParams(
                action="create",
                short_description="X",
                type="normal",
            ),
        )
    _assert_snapshot("manage_change_create_failure", result)
