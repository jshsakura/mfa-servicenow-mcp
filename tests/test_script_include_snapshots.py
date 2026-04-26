"""Response-shape snapshots for manage_script_include.

Pin manage_script_include response shapes so Phase 4.0 service extraction
produces zero diffs against the live LLM contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.tools.script_include_tools import (
    ManageScriptIncludeParams,
    manage_script_include,
)

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots" / "script_include"


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


def _si_record(name="MyUtil", client_callable="true"):
    return {
        "sys_id": "si_001",
        "name": name,
        "script": "var MyUtil = Class.create();",
        "description": "Test SI",
        "api_name": f"global.{name}",
        "client_callable": client_callable,
        "active": "true",
        "access": "package_private",
        "sys_created_on": "2023-01-01 00:00:00",
        "sys_updated_on": "2023-01-02 00:00:00",
        "sys_created_by": None,
        "sys_updated_by": None,
    }


def _sn_query_resp(records: list) -> MagicMock:
    """Mock response compatible with sn_query_page (uses .content for JSON)."""
    body = {"result": records}
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.content = json.dumps(body).encode("utf-8")
    m.headers = {}
    return m


def _op_resp(body: dict | None = None, text: str | None = None) -> MagicMock:
    """Mock response for POST/PATCH/DELETE/xmlhttp operations."""
    m = MagicMock()
    m.raise_for_status = MagicMock()
    if body is not None:
        m.json.return_value = body
    if text is not None:
        m.text = text
    return m


@pytest.fixture
def auth(mock_auth):
    mock_auth.make_request = MagicMock()
    return mock_auth


def test_snap_manage_script_include_create(mock_config, auth):
    auth.make_request.return_value = _op_resp(
        body={"result": {"sys_id": "si_001", "name": "MyUtil"}}
    )
    result = manage_script_include(
        mock_config,
        auth,
        ManageScriptIncludeParams(
            action="create", name="MyUtil", script="var MyUtil = Class.create();"
        ),
    )
    _assert_snapshot(
        "manage_script_include_create",
        result.model_dump() if hasattr(result, "model_dump") else result,
    )


def test_snap_manage_script_include_update(mock_config, auth):
    auth.make_request.side_effect = [
        _sn_query_resp([_si_record()]),
        _op_resp(body={"result": {"sys_id": "si_001", "name": "MyUtil"}}),
    ]
    result = manage_script_include(
        mock_config,
        auth,
        ManageScriptIncludeParams(action="update", script_include_id="si_001", active=False),
    )
    _assert_snapshot(
        "manage_script_include_update",
        result.model_dump() if hasattr(result, "model_dump") else result,
    )


def test_snap_manage_script_include_delete(mock_config, auth):
    auth.make_request.side_effect = [
        _sn_query_resp([_si_record()]),
        _op_resp(),
    ]
    result = manage_script_include(
        mock_config,
        auth,
        ManageScriptIncludeParams(action="delete", script_include_id="si_001"),
    )
    _assert_snapshot(
        "manage_script_include_delete",
        result.model_dump() if hasattr(result, "model_dump") else result,
    )


def test_snap_manage_script_include_execute(mock_config, auth):
    auth.make_request.side_effect = [
        _sn_query_resp([_si_record(client_callable="true")]),
        _op_resp(text='{"answer": "42"}'),
    ]
    result = manage_script_include(
        mock_config,
        auth,
        ManageScriptIncludeParams(action="execute", name="MyUtil", method="doWork"),
    )
    _assert_snapshot(
        "manage_script_include_execute",
        result.model_dump() if hasattr(result, "model_dump") else result,
    )


def test_snap_manage_script_include_create_failure(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("API error: 500")
    result = manage_script_include(
        mock_config,
        auth,
        ManageScriptIncludeParams(action="create", name="MyUtil", script="var x = 1;"),
    )
    _assert_snapshot(
        "manage_script_include_create_failure",
        result.model_dump() if hasattr(result, "model_dump") else result,
    )
