"""Tests for scrum_task_tools module."""

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


class TestListScrumTasks:
    """Tests for list_scrum_tasks."""

    def setUp(self):
        self.config = MagicMock(spec=ServerConfig)
        self.config.instance_url = "https://test.service-now.com"
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.scrum_task_tools.sn_query_page")
    def test_list_scrum_tasks_basic(self, mock_query):
        self.setUp()
        mock_query.return_value = (
            [{"sys_id": "1", "short_description": "Task 1"}],
            1,
        )

        params = ListScrumTasksParams()
        result = list_scrum_tasks(self.config, self.auth_manager, params)

        assert result["success"] is True
        assert result["count"] == 1
        assert result["scrum_tasks"][0]["sys_id"] == "1"
        mock_query.assert_called_once()
        call_kwargs = mock_query.call_args
        assert call_kwargs[1]["table"] == "rm_scrum_task"
        assert call_kwargs[1]["display_value"] is True

    @patch("servicenow_mcp.tools.scrum_task_tools.sn_query_page")
    def test_list_scrum_tasks_with_state_filter(self, mock_query):
        self.setUp()
        mock_query.return_value = ([], 0)

        params = ListScrumTasksParams(state="3")
        result = list_scrum_tasks(self.config, self.auth_manager, params)

        assert result["success"] is True
        call_kwargs = mock_query.call_args
        assert "state=3" in call_kwargs[1]["query"]

    @patch("servicenow_mcp.tools.scrum_task_tools.sn_query_page")
    def test_list_scrum_tasks_with_assignment_group_filter(self, mock_query):
        self.setUp()
        mock_query.return_value = ([], 0)

        params = ListScrumTasksParams(assignment_group="dev-team")
        result = list_scrum_tasks(self.config, self.auth_manager, params)

        assert result["success"] is True
        call_kwargs = mock_query.call_args
        assert "assignment_group=dev-team" in call_kwargs[1]["query"]

    @patch("servicenow_mcp.tools.scrum_task_tools.sn_query_page")
    def test_list_scrum_tasks_with_timeframe(self, mock_query):
        self.setUp()
        mock_query.return_value = (
            [{"sys_id": "2", "short_description": "Completed task"}],
            1,
        )

        params = ListScrumTasksParams(timeframe="completed")
        result = list_scrum_tasks(self.config, self.auth_manager, params)

        assert result["success"] is True
        call_kwargs = mock_query.call_args
        assert "end_date<" in call_kwargs[1]["query"]

    @patch("servicenow_mcp.tools.scrum_task_tools.sn_query_page")
    def test_list_scrum_tasks_with_additional_query(self, mock_query):
        self.setUp()
        mock_query.return_value = ([], 0)

        params = ListScrumTasksParams(query="priority=1")
        result = list_scrum_tasks(self.config, self.auth_manager, params)

        assert result["success"] is True
        call_kwargs = mock_query.call_args
        assert "priority=1" in call_kwargs[1]["query"]

    @patch(
        "servicenow_mcp.tools.scrum_task_tools.sn_query_page",
        side_effect=Exception("Network error"),
    )
    def test_list_scrum_tasks_error(self, mock_query):
        self.setUp()

        params = ListScrumTasksParams()
        result = list_scrum_tasks(self.config, self.auth_manager, params)

        assert result["success"] is False
        assert "Network error" in result["message"]

    @patch("servicenow_mcp.tools.scrum_task_tools.sn_query_page")
    def test_list_scrum_tasks_pagination(self, mock_query):
        self.setUp()
        mock_query.return_value = (
            [{"sys_id": str(i)} for i in range(5)],
            50,
        )

        params = ListScrumTasksParams(limit=5, offset=10)
        result = list_scrum_tasks(self.config, self.auth_manager, params)

        assert result["success"] is True
        assert result["total"] == 50
        assert result["count"] == 5
        call_kwargs = mock_query.call_args
        assert call_kwargs[1]["limit"] == 5
        assert call_kwargs[1]["offset"] == 10


class TestCreateScrumTask:
    """Tests for create_scrum_task."""

    def setUp(self):
        self.config = MagicMock(spec=ServerConfig)
        self.config.instance_url = "https://test.service-now.com"
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {"Authorization": "Bearer token"}

    @patch("servicenow_mcp.tools.scrum_task_tools.invalidate_query_cache")
    def test_create_scrum_task_success(self, mock_invalidate):
        self.setUp()
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "new123", "short_description": "New task"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = CreateScrumTaskParams(
            story="story_sys_id",
            short_description="New task",
            priority="2",
            state="1",
        )
        result = create_scrum_task(self.config, self.auth_manager, params)

        assert result["success"] is True
        assert result["scrum_task"]["sys_id"] == "new123"
        mock_invalidate.assert_called_once_with(table="rm_scrum_task")
        call_args = self.auth_manager.make_request.call_args
        assert call_args[0][0] == "POST"
        assert "rm_scrum_task" in call_args[0][1]

    @patch("servicenow_mcp.tools.scrum_task_tools.invalidate_query_cache")
    def test_create_scrum_task_minimal(self, mock_invalidate):
        self.setUp()
        response = MagicMock()
        response.json.return_value = {"result": {"sys_id": "min123"}}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = CreateScrumTaskParams(
            story="story_sys_id",
            short_description="Minimal task",
        )
        result = create_scrum_task(self.config, self.auth_manager, params)

        assert result["success"] is True
        call_args = self.auth_manager.make_request.call_args
        json_data = call_args[1]["json"]
        assert json_data["story"] == "story_sys_id"
        assert json_data["short_description"] == "Minimal task"
        assert "priority" not in json_data

    @patch("servicenow_mcp.tools.scrum_task_tools.invalidate_query_cache")
    def test_create_scrum_task_error(self, mock_invalidate):
        self.setUp()
        self.auth_manager.make_request.side_effect = Exception("Server error")

        params = CreateScrumTaskParams(
            story="story_sys_id",
            short_description="Fail task",
        )
        result = create_scrum_task(self.config, self.auth_manager, params)

        assert result["success"] is False
        assert "Server error" in result["message"]
        mock_invalidate.assert_not_called()


class TestUpdateScrumTask:
    """Tests for update_scrum_task."""

    def setUp(self):
        self.config = MagicMock(spec=ServerConfig)
        self.config.instance_url = "https://test.service-now.com"
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {"Authorization": "Bearer token"}

    @patch("servicenow_mcp.tools.scrum_task_tools.invalidate_query_cache")
    def test_update_scrum_task_success(self, mock_invalidate):
        self.setUp()
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "task123", "short_description": "Updated"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = UpdateScrumTaskParams(
            scrum_task_id="task123",
            short_description="Updated",
            state="3",
        )
        result = update_scrum_task(self.config, self.auth_manager, params)

        assert result["success"] is True
        assert result["scrum_task"]["sys_id"] == "task123"
        mock_invalidate.assert_called_once_with(table="rm_scrum_task")
        call_args = self.auth_manager.make_request.call_args
        assert call_args[0][0] == "PUT"
        assert "rm_scrum_task/task123" in call_args[0][1]

    @patch("servicenow_mcp.tools.scrum_task_tools.invalidate_query_cache")
    def test_update_scrum_task_error(self, mock_invalidate):
        self.setUp()
        self.auth_manager.make_request.side_effect = Exception("Not found")

        params = UpdateScrumTaskParams(
            scrum_task_id="bad_id",
            short_description="Update fail",
        )
        result = update_scrum_task(self.config, self.auth_manager, params)

        assert result["success"] is False
        assert "Not found" in result["message"]
        mock_invalidate.assert_not_called()
