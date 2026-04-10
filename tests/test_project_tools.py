"""Tests for project management tools."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.project_tools import (
    CreateProjectParams,
    ListProjectsParams,
    UpdateProjectParams,
    create_project,
    list_projects,
    update_project,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestProjectTools(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://example.service-now.com",
            auth=AuthConfig(
                type=AuthType.BASIC,
                basic=BasicAuthConfig(username="admin", password="password"),
            ),
        )
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_basic(self, mock_query):
        mock_query.return_value = (
            [{"sys_id": "1", "short_description": "Test Project"}],
            1,
        )
        result = list_projects(self.config, self.auth_manager, ListProjectsParams())
        self.assertTrue(result["success"])
        self.assertEqual(len(result["projects"]), 1)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total"], 1)
        mock_query.assert_called_once()
        call_kwargs = mock_query.call_args
        self.assertEqual(call_kwargs.kwargs["table"], "pm_project")
        self.assertEqual(call_kwargs.kwargs["display_value"], True)

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_with_timeframe_filter(self, mock_query):
        mock_query.return_value = ([], 0)
        result = list_projects(
            self.config,
            self.auth_manager,
            ListProjectsParams(timeframe="in-progress"),
        )
        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args.kwargs
        query = call_kwargs["query"]
        self.assertIn("start_date<", query)
        self.assertIn("^end_date>", query)

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_with_state_and_group(self, mock_query):
        mock_query.return_value = (
            [{"sys_id": "2", "short_description": "Filtered"}],
            1,
        )
        result = list_projects(
            self.config,
            self.auth_manager,
            ListProjectsParams(state="2", assignment_group="devops"),
        )
        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args.kwargs
        query = call_kwargs["query"]
        self.assertIn("state=2", query)
        self.assertIn("assignment_group=devops", query)
        self.assertIn("^", query)

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_with_extra_query(self, mock_query):
        mock_query.return_value = ([{"sys_id": "3"}], 1)
        result = list_projects(
            self.config,
            self.auth_manager,
            ListProjectsParams(query="priority=1"),
        )
        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args.kwargs
        self.assertIn("priority=1", call_kwargs["query"])

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_empty(self, mock_query):
        mock_query.return_value = ([], 0)
        result = list_projects(self.config, self.auth_manager, ListProjectsParams())
        self.assertTrue(result["success"])
        self.assertEqual(result["projects"], [])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["total"], 0)

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_limit_capped_at_100(self, mock_query):
        mock_query.return_value = ([], 0)
        list_projects(
            self.config,
            self.auth_manager,
            ListProjectsParams(limit=500),
        )
        call_kwargs = mock_query.call_args.kwargs
        self.assertEqual(call_kwargs["limit"], 100)

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_default_limit_and_offset(self, mock_query):
        mock_query.return_value = ([], 0)
        list_projects(self.config, self.auth_manager, ListProjectsParams())
        call_kwargs = mock_query.call_args.kwargs
        self.assertEqual(call_kwargs["limit"], 10)
        self.assertEqual(call_kwargs["offset"], 0)

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_error(self, mock_query):
        mock_query.side_effect = Exception("Connection refused")
        result = list_projects(self.config, self.auth_manager, ListProjectsParams())
        self.assertFalse(result["success"])
        self.assertIn("Connection refused", result["message"])

    @patch("servicenow_mcp.tools.project_tools.invalidate_query_cache")
    def test_create_project_success(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {"result": {"sys_id": "new123", "short_description": "New"}}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        result = create_project(
            self.config,
            self.auth_manager,
            CreateProjectParams(short_description="New Project"),
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["project"]["sys_id"], "new123")
        mock_invalidate.assert_called_once_with(table="pm_project")

        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "POST")
        self.assertIn("/api/now/table/pm_project", call_args[0][1])

    @patch("servicenow_mcp.tools.project_tools.invalidate_query_cache")
    def test_create_project_with_all_fields(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {"result": {"sys_id": "full123"}}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        result = create_project(
            self.config,
            self.auth_manager,
            CreateProjectParams(
                short_description="Full Project",
                description="A detailed description",
                status="green",
                state="2",
                project_manager="pm_sys_id",
                percentage_complete=50,
                assignment_group="group_sys_id",
                assigned_to="user_sys_id",
                start_date="2026-01-01",
                end_date="2026-12-31",
            ),
        )
        self.assertTrue(result["success"])
        sent_data = self.auth_manager.make_request.call_args.kwargs.get(
            "json"
        ) or self.auth_manager.make_request.call_args[1].get("json", {})
        self.assertEqual(sent_data["short_description"], "Full Project")
        self.assertEqual(sent_data["description"], "A detailed description")
        self.assertEqual(sent_data["status"], "green")
        self.assertEqual(sent_data["state"], "2")
        self.assertEqual(sent_data["project_manager"], "pm_sys_id")
        self.assertEqual(sent_data["percentage_complete"], 50)
        self.assertEqual(sent_data["assignment_group"], "group_sys_id")
        self.assertEqual(sent_data["assigned_to"], "user_sys_id")
        self.assertEqual(sent_data["start_date"], "2026-01-01")
        self.assertEqual(sent_data["end_date"], "2026-12-31")

    @patch("servicenow_mcp.tools.project_tools.invalidate_query_cache")
    def test_create_project_minimal(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {"result": {"sys_id": "min123"}}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        result = create_project(
            self.config,
            self.auth_manager,
            CreateProjectParams(short_description="Minimal"),
        )
        self.assertTrue(result["success"])
        sent_data = self.auth_manager.make_request.call_args.kwargs.get(
            "json"
        ) or self.auth_manager.make_request.call_args[1].get("json", {})
        self.assertEqual(sent_data["short_description"], "Minimal")
        self.assertNotIn("description", sent_data)
        self.assertNotIn("status", sent_data)

    def test_create_project_error(self):
        self.auth_manager.make_request.side_effect = Exception("Server error")
        result = create_project(
            self.config,
            self.auth_manager,
            CreateProjectParams(short_description="Fail"),
        )
        self.assertFalse(result["success"])
        self.assertIn("Server error", result["message"])

    @patch("servicenow_mcp.tools.project_tools.invalidate_query_cache")
    def test_update_project_success(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "upd123", "short_description": "Updated"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        result = update_project(
            self.config,
            self.auth_manager,
            UpdateProjectParams(project_id="abc123", short_description="Updated"),
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["project"]["sys_id"], "upd123")
        mock_invalidate.assert_called_once_with(table="pm_project")

        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "PUT")
        self.assertIn("/api/now/table/pm_project/abc123", call_args[0][1])

    @patch("servicenow_mcp.tools.project_tools.invalidate_query_cache")
    def test_update_project_multiple_fields(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {"result": {"sys_id": "multi123"}}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        result = update_project(
            self.config,
            self.auth_manager,
            UpdateProjectParams(
                project_id="proj1",
                short_description="Updated Name",
                state="3",
                status="red",
                percentage_complete=100,
            ),
        )
        self.assertTrue(result["success"])
        sent_data = self.auth_manager.make_request.call_args.kwargs.get(
            "json"
        ) or self.auth_manager.make_request.call_args[1].get("json", {})
        self.assertEqual(sent_data["short_description"], "Updated Name")
        self.assertEqual(sent_data["state"], "3")
        self.assertEqual(sent_data["status"], "red")
        self.assertEqual(sent_data["percentage_complete"], 100)

    def test_update_project_error(self):
        self.auth_manager.make_request.side_effect = Exception("Not found")
        result = update_project(
            self.config,
            self.auth_manager,
            UpdateProjectParams(project_id="bad_id", short_description="Nope"),
        )
        self.assertFalse(result["success"])
        self.assertIn("Not found", result["message"])

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_timeframe_upcoming(self, mock_query):
        mock_query.return_value = ([], 0)
        list_projects(
            self.config,
            self.auth_manager,
            ListProjectsParams(timeframe="upcoming"),
        )
        query = mock_query.call_args.kwargs["query"]
        self.assertIn("start_date>", query)
        self.assertNotIn("end_date", query)

    @patch("servicenow_mcp.tools.project_tools.sn_query_page")
    def test_list_projects_timeframe_completed(self, mock_query):
        mock_query.return_value = ([], 0)
        list_projects(
            self.config,
            self.auth_manager,
            ListProjectsParams(timeframe="completed"),
        )
        query = mock_query.call_args.kwargs["query"]
        self.assertIn("end_date<", query)
        self.assertNotIn("start_date", query)


if __name__ == "__main__":
    unittest.main()
