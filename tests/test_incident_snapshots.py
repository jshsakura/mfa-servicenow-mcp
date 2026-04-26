"""Response-shape snapshots for manage_incident.

Pin manage_incident response shapes so Phase 4.0 service extraction produces
zero diffs against the live LLM contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.incident_tools import ManageIncidentParams, manage_incident

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots" / "incident"


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


def test_snap_manage_incident_create(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {"result": {"sys_id": "inc_001", "number": "INC0001000"}}
    )
    with patch("servicenow_mcp.services.incident.invalidate_query_cache"):
        result = manage_incident(
            mock_config,
            auth,
            ManageIncidentParams(
                action="create",
                short_description="Server down",
                priority="1",
                impact="2",
                urgency="2",
            ),
        )
    _assert_snapshot("manage_incident_create", result.model_dump())


def test_snap_manage_incident_update(mock_config, auth):
    # First make_request resolves sys_id (incident_id is sys_id-shaped already → skip lookup)
    auth.make_request.return_value = _mock_response(
        {"result": {"sys_id": "a" * 32, "number": "INC0001000"}}
    )
    with patch("servicenow_mcp.services.incident.invalidate_query_cache"):
        result = manage_incident(
            mock_config,
            auth,
            ManageIncidentParams(
                action="update",
                incident_id="a" * 32,
                state="2",
                work_notes="investigating",
            ),
        )
    _assert_snapshot("manage_incident_update", result.model_dump())


def test_snap_manage_incident_comment(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {"result": {"sys_id": "a" * 32, "number": "INC0001000"}}
    )
    with patch("servicenow_mcp.services.incident.invalidate_query_cache"):
        result = manage_incident(
            mock_config,
            auth,
            ManageIncidentParams(
                action="comment",
                incident_id="a" * 32,
                comment="Customer called for status",
                is_work_note=False,
            ),
        )
    _assert_snapshot("manage_incident_comment", result.model_dump())


def test_snap_manage_incident_resolve(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {"result": {"sys_id": "a" * 32, "number": "INC0001000"}}
    )
    with patch("servicenow_mcp.services.incident.invalidate_query_cache"):
        result = manage_incident(
            mock_config,
            auth,
            ManageIncidentParams(
                action="resolve",
                incident_id="a" * 32,
                resolution_code="Solved (Permanently)",
                resolution_notes="Restarted service",
            ),
        )
    _assert_snapshot("manage_incident_resolve", result.model_dump())


def test_snap_manage_incident_create_failure(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("boom: 500")
    with patch("servicenow_mcp.services.incident.invalidate_query_cache"):
        result = manage_incident(
            mock_config,
            auth,
            ManageIncidentParams(
                action="create",
                short_description="X",
            ),
        )
    _assert_snapshot("manage_incident_create_failure", result.model_dump())
