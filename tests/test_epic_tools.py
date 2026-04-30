"""
Tests for the epic management tools.
"""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.epic_tools import (
    CreateEpicParams,
    ListEpicsParams,
    ManageEpicParams,
    UpdateEpicParams,
    create_epic,
    list_epics,
    manage_epic,
    update_epic,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestEpicTools(unittest.TestCase):
    """Tests for the epic management tools."""

    def setUp(self):
        """Set up test fixtures."""
        auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test", password="test"),
        )
        self.config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=auth_config,
        )
        self.auth_manager = MagicMock()

    # --- list_epics tests ---

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_basic(self, mock_query):
        """Test listing epics with default params."""
        mock_query.return_value = (
            [{"sys_id": "1", "short_description": "Epic 1"}],
            1,
        )

        params = ListEpicsParams()
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["epics"]), 1)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total"], 1)
        mock_query.assert_called_once()
        call_kwargs = mock_query.call_args
        self.assertEqual(call_kwargs[1]["table"], "rm_epic")
        self.assertEqual(call_kwargs[1]["display_value"], True)
        self.assertEqual(call_kwargs[1]["fail_silently"], False)

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_with_priority(self, mock_query):
        """Test that priority filter is included in query."""
        mock_query.return_value = ([], 0)

        params = ListEpicsParams(priority="1")
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args
        self.assertIn("priority=1", call_kwargs[1]["query"])

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_with_assignment_group(self, mock_query):
        """Test that assignment_group filter is included in query."""
        mock_query.return_value = (
            [{"sys_id": "1", "short_description": "Epic 1"}],
            1,
        )

        params = ListEpicsParams(assignment_group="dev-team")
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args
        self.assertIn("assignment_group=dev-team", call_kwargs[1]["query"])

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_with_timeframe_upcoming(self, mock_query):
        """Test upcoming timeframe query generation."""
        mock_query.return_value = ([], 0)

        params = ListEpicsParams(timeframe="upcoming")
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args
        self.assertIn("start_date>", call_kwargs[1]["query"])

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_with_timeframe_in_progress(self, mock_query):
        """Test in-progress timeframe query generation."""
        mock_query.return_value = ([], 0)

        params = ListEpicsParams(timeframe="in-progress")
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args
        query_str = call_kwargs[1]["query"]
        self.assertIn("start_date<", query_str)
        self.assertIn("^end_date>", query_str)

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_with_timeframe_completed(self, mock_query):
        """Test completed timeframe query generation."""
        mock_query.return_value = ([], 0)

        params = ListEpicsParams(timeframe="completed")
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args
        self.assertIn("end_date<", call_kwargs[1]["query"])

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_with_additional_query(self, mock_query):
        """Test additional query string is appended."""
        mock_query.return_value = ([], 0)

        params = ListEpicsParams(query="active=true")
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args
        self.assertIn("active=true", call_kwargs[1]["query"])

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_empty(self, mock_query):
        """Test listing epics with empty results."""
        mock_query.return_value = ([], 0)

        params = ListEpicsParams()
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["epics"], [])
        self.assertEqual(result["count"], 0)

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_error(self, mock_query):
        """Test listing epics when sn_query_page raises an exception."""
        mock_query.side_effect = Exception("Network error")

        params = ListEpicsParams()
        result = list_epics(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Network error", result["message"])

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_with_limit_and_offset(self, mock_query):
        """Test that limit and offset are passed correctly."""
        mock_query.return_value = ([], 0)

        params = ListEpicsParams(limit=50, offset=10)
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args
        self.assertEqual(call_kwargs[1]["limit"], 50)
        self.assertEqual(call_kwargs[1]["offset"], 10)

    @patch("servicenow_mcp.tools.epic_tools.sn_query_page")
    def test_list_epics_limit_capped_at_100(self, mock_query):
        """Test that limit is capped at 100."""
        mock_query.return_value = ([], 0)

        params = ListEpicsParams(limit=200)
        result = list_epics(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args
        self.assertEqual(call_kwargs[1]["limit"], 100)

    # --- create_epic tests ---

    @patch("servicenow_mcp.tools.epic_tools.invalidate_query_cache")
    def test_create_epic_success(self, mock_invalidate):
        """Test creating an epic with all fields."""
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "new123", "short_description": "Test Epic"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = CreateEpicParams(
            short_description="Test Epic",
            description="Detailed description",
            priority="1",
            state="1",
            assignment_group="dev-team",
            assigned_to="user1",
            work_notes="Initial notes",
        )
        result = create_epic(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["epic"]["sys_id"], "new123")
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "POST")
        self.assertIn("/api/now/table/rm_epic", call_args[0][1])
        mock_invalidate.assert_called_once_with(table="rm_epic")

        sent_data = call_args[1]["json"]
        self.assertEqual(sent_data["short_description"], "Test Epic")
        self.assertEqual(sent_data["description"], "Detailed description")
        self.assertEqual(sent_data["priority"], "1")
        self.assertEqual(sent_data["state"], "1")
        self.assertEqual(sent_data["assignment_group"], "dev-team")
        self.assertEqual(sent_data["assigned_to"], "user1")
        self.assertEqual(sent_data["work_notes"], "Initial notes")

    @patch("servicenow_mcp.tools.epic_tools.invalidate_query_cache")
    def test_create_epic_minimal(self, mock_invalidate):
        """Test creating an epic with only required fields."""
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "new456", "short_description": "Minimal Epic"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = CreateEpicParams(short_description="Minimal Epic")
        result = create_epic(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["epic"]["sys_id"], "new456")
        mock_invalidate.assert_called_once_with(table="rm_epic")

        sent_data = self.auth_manager.make_request.call_args[1]["json"]
        self.assertEqual(sent_data["short_description"], "Minimal Epic")
        self.assertNotIn("description", sent_data)
        self.assertNotIn("priority", sent_data)
        self.assertNotIn("assignment_group", sent_data)

    @patch("servicenow_mcp.tools.epic_tools.invalidate_query_cache")
    def test_create_epic_error(self, mock_invalidate):
        """Test error handling when creating an epic."""
        self.auth_manager.make_request.side_effect = Exception("Server error")

        params = CreateEpicParams(short_description="Test Epic")
        result = create_epic(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Server error", result["message"])
        mock_invalidate.assert_not_called()

    # --- update_epic tests ---

    @patch("servicenow_mcp.tools.epic_tools.invalidate_query_cache")
    def test_update_epic_success(self, mock_invalidate):
        """Test updating an epic successfully."""
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "epic123", "short_description": "Updated"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = UpdateEpicParams(
            epic_id="epic123",
            short_description="Updated",
            priority="2",
        )
        result = update_epic(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["epic"]["sys_id"], "epic123")
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args[0][0], "PUT")
        self.assertIn("/api/now/table/rm_epic/epic123", call_args[0][1])
        mock_invalidate.assert_called_once_with(table="rm_epic")

        sent_data = call_args[1]["json"]
        self.assertEqual(sent_data["short_description"], "Updated")
        self.assertEqual(sent_data["priority"], "2")

    @patch("servicenow_mcp.tools.epic_tools.invalidate_query_cache")
    def test_update_epic_error(self, mock_invalidate):
        """Test error handling when updating an epic."""
        self.auth_manager.make_request.side_effect = Exception("Not found")

        params = UpdateEpicParams(epic_id="nonexistent", short_description="Try update")
        result = update_epic(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Not found", result["message"])
        mock_invalidate.assert_not_called()

    @patch("servicenow_mcp.tools.epic_tools.invalidate_query_cache")
    def test_update_epic_empty_data(self, mock_invalidate):
        """Test updating an epic with no fields set (empty payload)."""
        response = MagicMock()
        response.json.return_value = {"result": {"sys_id": "epic123"}}
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = UpdateEpicParams(epic_id="epic123")
        result = update_epic(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        sent_data = self.auth_manager.make_request.call_args[1]["json"]
        self.assertEqual(sent_data, {})

    @patch("servicenow_mcp.tools.epic_tools.build_update_preview")
    def test_update_epic_dry_run(self, mock_preview):
        """Test dry run for updating an epic."""
        mock_preview.return_value = {"success": True, "preview": {}}
        params = UpdateEpicParams(epic_id="epic123", short_description="New", dry_run=True)
        result = update_epic(self.config, self.auth_manager, params)
        self.assertEqual(result, mock_preview.return_value)
        mock_preview.assert_called_once()


class TestManageEpic(unittest.TestCase):
    """Tests for manage_epic bundled tool."""

    def setUp(self):
        self.config = MagicMock(spec=ServerConfig)
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.epic_tools.create_epic")
    def test_manage_create(self, mock_create):
        mock_create.return_value = {"success": True}
        params = ManageEpicParams(action="create", short_description="S")
        manage_epic(self.config, self.auth_manager, params)
        mock_create.assert_called_once()

    @patch("servicenow_mcp.tools.epic_tools.update_epic")
    def test_manage_update(self, mock_update):
        mock_update.return_value = {"success": True}
        params = ManageEpicParams(action="update", epic_id="e1", description="D")
        manage_epic(self.config, self.auth_manager, params)
        mock_update.assert_called_once()

    @patch("servicenow_mcp.tools.epic_tools.list_epics")
    def test_manage_list(self, mock_list):
        mock_list.return_value = {"success": True}
        params = ManageEpicParams(action="list")
        manage_epic(self.config, self.auth_manager, params)
        mock_list.assert_called_once()


if __name__ == "__main__":
    unittest.main()
