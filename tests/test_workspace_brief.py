"""Tests for workspace_brief (session situational awareness).

Pinned invariants:
- Offline half (your edits, conflict sidecars, baseline coverage) is pure disk
  reads — include_remote=False must touch no network path.
- Refresh judgment is LIVE (server count query above the local watermark),
  never a local-only guess; a missing watermark reports as unchecked, not clean.
- Trees downloaded from a different instance are never refresh-checked against
  the active one.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.workspace_tools import WorkspaceBriefParams, workspace_brief
from servicenow_mcp.utils.baseline import remote_sidecar_path_for, write_baseline_for
from servicenow_mcp.utils.config import ServerConfig


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth():
    return MagicMock()


@pytest.fixture
def workspace(tmp_path):
    """temp/<instance>/<scope> tree with one widget, seeded baseline."""
    tree = tmp_path / "temp" / "test" / "x_app"
    widget_dir = tree / "sp_widget" / "my-widget"
    widget_dir.mkdir(parents=True)
    (tmp_path / "temp" / "test" / "_settings.json").write_text(
        json.dumps({"name": "test", "url": "https://test.service-now.com", "g_ck": ""}),
        encoding="utf-8",
    )
    (tree / "_manifest.json").write_text(
        json.dumps({"scope": "x_app", "instance": "https://test.service-now.com"}),
        encoding="utf-8",
    )
    script = widget_dir / "script.js"
    script.write_text("var x = 1;", encoding="utf-8")
    write_baseline_for(script, "var x = 1;")
    (tree / "sp_widget" / "_map.json").write_text(
        json.dumps({"my-widget": "wid-1"}), encoding="utf-8"
    )
    (tree / "sp_widget" / "_sync_meta.json").write_text(
        json.dumps(
            {
                "my-widget": {
                    "sys_id": "wid-1",
                    "sys_updated_on": "2025-01-10 10:00:00",
                    "downloaded_at": "2025-01-10T10:05:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    return tmp_path / "temp"


class TestOfflineHalf:
    def test_clean_tree_reports_protected_and_no_edits(self, mock_config, mock_auth, workspace):
        result = workspace_brief(
            mock_config,
            mock_auth,
            WorkspaceBriefParams(root=str(workspace), include_remote=False),
        )
        tree = result["trees"][0]
        assert tree["scope"] == "x_app"
        assert tree["components"] == 1
        assert tree["baseline_protected"] == "1/1"
        assert "your_edits" not in tree
        assert "refresh" not in tree  # offline mode: no live judgment at all
        assert "user" not in result["identity"]

    def test_detects_your_edits_and_conflict_sidecar(self, mock_config, mock_auth, workspace):
        script = workspace / "test" / "x_app" / "sp_widget" / "my-widget" / "script.js"
        script.write_text("var x = 1; // my edit", encoding="utf-8")
        remote_sidecar_path_for(script).write_text("var x = 2;", encoding="utf-8")

        result = workspace_brief(
            mock_config,
            mock_auth,
            WorkspaceBriefParams(root=str(workspace), include_remote=False),
        )
        tree = result["trees"][0]
        assert tree["your_edits"] == ["sp_widget/my-widget:script.js"]
        assert tree["unresolved_conflicts"] == ["sp_widget/my-widget (script.remote.js)"]
        assert any("merge" in step for step in result["next_steps"])

    def test_missing_root_notes_nothing_downloaded(self, mock_config, mock_auth, tmp_path):
        result = workspace_brief(
            mock_config,
            mock_auth,
            WorkspaceBriefParams(root=str(tmp_path / "nowhere"), include_remote=False),
        )
        assert result["trees"] == []
        assert "note" in result


class TestLiveHalf:
    @patch("servicenow_mcp.tools.workspace_tools.resolve_live_username")
    @patch("servicenow_mcp.tools.workspace_tools.sn_query_page")
    def test_refresh_needed_is_a_live_judgment(
        self, mock_page, mock_user, mock_config, mock_auth, workspace
    ):
        mock_user.return_value = "admin"
        mock_page.return_value = ([{"sys_updated_on": "2025-02-01 00:00:00"}], 3)

        result = workspace_brief(mock_config, mock_auth, WorkspaceBriefParams(root=str(workspace)))
        refresh = result["trees"][0]["refresh"]
        assert refresh["needed"] is True
        assert refresh["changed_records"] == 3
        assert refresh["newest_remote"] == "2025-02-01 00:00:00"
        assert "incremental=True" in refresh["how"]
        assert any("3 record(s) changed" in step for step in result["next_steps"])
        # The judgment came from a server query above the local watermark.
        query = mock_page.call_args[1]["query"]
        assert "sys_updated_on>2025-01-10 10:00:00" in query
        assert result["identity"]["user"] == "admin"

    @patch("servicenow_mcp.tools.workspace_tools.resolve_live_username")
    @patch("servicenow_mcp.tools.workspace_tools.sn_query_page")
    def test_up_to_date_tree(self, mock_page, mock_user, mock_config, mock_auth, workspace):
        mock_user.return_value = "admin"
        mock_page.return_value = ([], 0)

        result = workspace_brief(mock_config, mock_auth, WorkspaceBriefParams(root=str(workspace)))
        assert result["trees"][0]["refresh"]["needed"] is False
        assert "next_steps" not in result

    @patch("servicenow_mcp.tools.workspace_tools.resolve_live_username")
    @patch("servicenow_mcp.tools.workspace_tools.sn_query_page")
    def test_other_instance_tree_is_never_checked_against_active(
        self, mock_page, mock_user, mock_config, mock_auth, workspace
    ):
        mock_user.return_value = "admin"
        (workspace / "test" / "_settings.json").write_text(
            json.dumps({"name": "dev", "url": "https://dev.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        result = workspace_brief(mock_config, mock_auth, WorkspaceBriefParams(root=str(workspace)))
        tree = result["trees"][0]
        assert tree["other_instance"] == "https://dev.service-now.com"
        assert "refresh" not in tree
        mock_page.assert_not_called()
