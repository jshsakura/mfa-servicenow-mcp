"""Response-shape snapshots for knowledge_base wrappers and manage_kb_article.

These tests assert byte-for-byte equality against pre-recorded JSON snapshots.
A snapshot diff means the response shape changed — that is a contract break
with live LLM consumers, regardless of whether other tests pass.

Phase 4.0 service extraction must produce zero diffs against these snapshots.
First run creates the snapshot files (and skips); subsequent runs assert.

To regenerate after an intentional response-shape change:
    rm tests/snapshots/knowledge_base/<name>.json
    pytest tests/test_knowledge_base_snapshots.py -k <name>
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.knowledge_base import ManageKbArticleParams, manage_kb_article

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots" / "knowledge_base"


def _assert_snapshot(name: str, actual: dict) -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snap_path = SNAPSHOTS_DIR / f"{name}.json"
    actual_json = json.dumps(actual, sort_keys=True, indent=2, ensure_ascii=False)
    if not snap_path.exists():
        snap_path.write_text(actual_json + "\n", encoding="utf-8")
        pytest.skip(f"snapshot {name} created — re-run pytest to assert")
    expected = snap_path.read_text(encoding="utf-8").rstrip("\n")
    assert actual_json == expected, (
        f"\nSnapshot drift for {name}.\n"
        f"  Snapshot file: {snap_path}\n"
        f"  This is a response-shape contract break — review the diff carefully.\n"
        f"  If the change is intentional, delete the snapshot and re-run.\n"
    )


def _mock_response(payload: dict) -> MagicMock:
    """Build a mock requests.Response-like object."""
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    mock.raise_for_status = MagicMock()
    return mock


@pytest.fixture
def auth(mock_auth):
    """Auth manager with a make_request method we control."""
    mock_auth.make_request = MagicMock()
    return mock_auth


# ----------------------------------------------------------------------
# manage_kb_article action snapshots (the surface that survives Phase 4.0)
# ----------------------------------------------------------------------


def test_snap_manage_kb_article_create(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {
            "result": {
                "sys_id": "art_002",
                "short_description": "Bundle Create",
                "workflow_state": "draft",
            }
        }
    )
    with patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache"):
        result = manage_kb_article(
            mock_config,
            auth,
            ManageKbArticleParams(
                action="create",
                title="Bundle Create",
                text="<p>body</p>",
                short_description="short",
                knowledge_base="kb_001",
                category="cat_001",
                keywords="kw1",
                article_type="html",
            ),
        )
    _assert_snapshot("manage_kb_article_create", result.model_dump())


def test_snap_manage_kb_article_update(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {
            "result": {
                "sys_id": "art_002",
                "short_description": "Bundle Updated",
                "workflow_state": "draft",
            }
        }
    )
    with patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache"):
        result = manage_kb_article(
            mock_config,
            auth,
            ManageKbArticleParams(
                action="update",
                article_id="art_002",
                title="Bundle Updated",
                text="<p>edit</p>",
                category="cat_002",
                keywords="kw2",
            ),
        )
    _assert_snapshot("manage_kb_article_update", result.model_dump())


def test_snap_manage_kb_article_publish(mock_config, auth):
    auth.make_request.return_value = _mock_response(
        {
            "result": {
                "sys_id": "art_002",
                "short_description": "Bundle Publish",
                "workflow_state": "published",
            }
        }
    )
    with patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache"):
        result = manage_kb_article(
            mock_config,
            auth,
            ManageKbArticleParams(
                action="publish",
                article_id="art_002",
                workflow_state="published",
            ),
        )
    _assert_snapshot("manage_kb_article_publish", result.model_dump())


# ----------------------------------------------------------------------
# Failure-shape snapshots (network/server error path)
# ----------------------------------------------------------------------


def test_snap_manage_kb_article_publish_failure(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("boom: 500 Internal Server Error")
    with patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache"):
        result = manage_kb_article(
            mock_config,
            auth,
            ManageKbArticleParams(action="publish", article_id="art_999"),
        )
    _assert_snapshot("manage_kb_article_publish_failure", result.model_dump())
