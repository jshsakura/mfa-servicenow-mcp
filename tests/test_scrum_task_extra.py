"""Tests for scrum_task_tools uncovered paths — dry_run, all optional fields, timeframe variants."""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.scrum_task_tools import (
    CreateScrumTaskParams,
    ListScrumTasksParams,
    UpdateScrumTaskParams,
    create_scrum_task,
    list_scrum_tasks,
    update_scrum_task,
)
from servicenow_mcp.utils.config import ServerConfig


def _setup():
    config = MagicMock(spec=ServerConfig)
    config.instance_url = "https://test.service-now.com"
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {"Authorization": "Bearer token"}
    return config, auth


class TestCreateScrumTaskAllFields:
    @patch("servicenow_mcp.tools.scrum_task_tools.invalidate_query_cache")
    def test_all_optional_fields(self, mock_invalidate):
        config, auth = _setup()
        response = MagicMock()
        response.json.return_value = {"result": {"sys_id": "all123"}}
        response.raise_for_status.return_value = None
        auth.make_request.return_value = response

        params = CreateScrumTaskParams(
            story="story1",
            short_description="Full task",
            priority="1",
            planned_hours=8,
            remaining_hours=6,
            hours=2,
            description="Detailed description",
            type="2",
            state="2",
            assignment_group="dev-team",
            assigned_to="john",
            work_notes="Starting work",
        )
        result = create_scrum_task(config, auth, params)

        assert result["success"] is True
        call_data = auth.make_request.call_args[1]["json"]
        assert call_data["priority"] == "1"
        assert call_data["planned_hours"] == 8
        assert call_data["remaining_hours"] == 6
        assert call_data["hours"] == 2
        assert call_data["description"] == "Detailed description"
        assert call_data["type"] == "2"
        assert call_data["state"] == "2"
        assert call_data["assignment_group"] == "dev-team"
        assert call_data["assigned_to"] == "john"
        assert call_data["work_notes"] == "Starting work"


class TestUpdateScrumTaskDryRun:
    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_dry_run_returns_preview(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = (
            [
                {
                    "sys_id": "task1",
                    "sys_scope": "global",
                    "number": "TSK001",
                    "short_description": "Old",
                    "state": "1",
                }
            ],
            1,
        )

        params = UpdateScrumTaskParams(
            scrum_task_id="task1",
            short_description="Updated",
            state="3",
            dry_run=True,
        )
        result = update_scrum_task(config, auth, params)

        assert result["dry_run"] is True
        assert result["operation"] == "update"
        assert "state" in result["proposed_changes"]


class TestUpdateScrumTaskAllFields:
    @patch("servicenow_mcp.tools.scrum_task_tools.invalidate_query_cache")
    def test_all_optional_fields(self, mock_invalidate):
        config, auth = _setup()
        response = MagicMock()
        response.json.return_value = {"result": {"sys_id": "task1"}}
        response.raise_for_status.return_value = None
        auth.make_request.return_value = response

        params = UpdateScrumTaskParams(
            scrum_task_id="task1",
            short_description="Updated",
            priority="2",
            planned_hours=4,
            remaining_hours=3,
            hours=1,
            description="New desc",
            type="3",
            state="3",
            assignment_group="qa-team",
            assigned_to="jane",
            work_notes="Done",
        )
        result = update_scrum_task(config, auth, params)

        assert result["success"] is True
        call_data = auth.make_request.call_args[1]["json"]
        assert call_data["short_description"] == "Updated"
        assert call_data["priority"] == "2"
        assert call_data["planned_hours"] == 4
        assert call_data["remaining_hours"] == 3
        assert call_data["hours"] == 1
        assert call_data["description"] == "New desc"
        assert call_data["type"] == "3"
        assert call_data["state"] == "3"
        assert call_data["assignment_group"] == "qa-team"
        assert call_data["assigned_to"] == "jane"
        assert call_data["work_notes"] == "Done"


class TestListScrumTasksTimeframes:
    @patch("servicenow_mcp.tools.scrum_task_tools.sn_query_page")
    def test_upcoming_timeframe(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = ([], 0)
        params = ListScrumTasksParams(timeframe="upcoming")
        result = list_scrum_tasks(config, auth, params)
        assert result["success"] is True
        assert "start_date>" in mock_query.call_args[1]["query"]

    @patch("servicenow_mcp.tools.scrum_task_tools.sn_query_page")
    def test_in_progress_timeframe(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = ([], 0)
        params = ListScrumTasksParams(timeframe="in-progress")
        result = list_scrum_tasks(config, auth, params)
        assert result["success"] is True
        query = mock_query.call_args[1]["query"]
        assert "start_date<" in query
        assert "end_date>" in query
