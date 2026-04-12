"""
Tests for the changeset tools.

This module contains tests for the changeset tools in the ServiceNow MCP server.
"""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.changeset_tools import (
    AddFileToChangesetParams,
    CommitChangesetParams,
    CreateChangesetParams,
    GetChangesetDetailsParams,
    PublishChangesetParams,
    UpdateChangesetParams,
    add_file_to_changeset,
    commit_changeset,
    create_changeset,
    get_changeset_details,
    publish_changeset,
    update_changeset,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestChangesetTools(unittest.TestCase):
    """Tests for the changeset tools."""

    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        )
        self.config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=self.auth_config,
        )
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {"Authorization": "Bearer test"}

    def _make_response(self, json_data):
        resp = MagicMock()
        resp.json.return_value = json_data
        resp.raise_for_status.return_value = None
        resp.headers = {}
        resp.content = b""
        return resp

    # --- get_changeset_details (list mode) ---

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_basic(self, mock_query_page):
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "123",
                    "name": "Test Changeset",
                    "state": "in_progress",
                }
            ],
            1,
        )

        params = GetChangesetDetailsParams(limit=10, offset=0)
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["changesets"]), 1)
        self.assertEqual(result["changesets"][0]["sys_id"], "123")
        mock_query_page.assert_called_once_with(
            self.config,
            self.auth_manager,
            table="sys_update_set",
            query="",
            fields="",
            limit=10,
            offset=0,
        )

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_with_state_filter(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(state="in_progress")
        get_changeset_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        self.assertEqual(call_kwargs[1]["query"], "state=in_progress")

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_with_timeframe_recent(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(timeframe="recent")
        get_changeset_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs[1]["query"]
        self.assertIn("sys_created_onONLast 7 days", query)

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_with_timeframe_last_week(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(timeframe="last_week")
        get_changeset_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs[1]["query"]
        self.assertIn("sys_created_onONLast week", query)

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_with_timeframe_last_month(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(timeframe="last_month")
        get_changeset_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs[1]["query"]
        self.assertIn("sys_created_onONLast month", query)

    @patch("servicenow_mcp.tools.changeset_tools.sn_count")
    def test_list_changesets_count_only(self, mock_count):
        mock_count.return_value = 42

        params = GetChangesetDetailsParams(count_only=True, state="in_progress")
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 42)
        mock_count.assert_called_once_with(
            self.config, self.auth_manager, "sys_update_set", "state=in_progress"
        )

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_error(self, mock_query_page):
        mock_query_page.side_effect = Exception("Network error")

        params = GetChangesetDetailsParams()
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Network error", result["message"])

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_combined_filters(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(
            state="in_progress", application="Test App", developer="test.user"
        )
        get_changeset_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs[1]["query"]
        self.assertIn("state=in_progress", query)
        self.assertIn("application=Test App", query)
        self.assertIn("developer=test.user", query)

    # --- get_changeset_details ---

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_get_changeset_details_found(self, mock_query_page):
        changeset_data = {
            "sys_id": "123",
            "name": "Test Changeset",
            "state": "in_progress",
        }
        changes_data = [
            {
                "sys_id": "456",
                "name": "test_file.py",
                "type": "file",
                "update_set": "123",
            }
        ]
        mock_query_page.side_effect = [
            ([changeset_data], 1),
            (changes_data, 1),
        ]

        params = GetChangesetDetailsParams(changeset_id="123")
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["sys_id"], "123")
        self.assertEqual(result["changeset"]["name"], "Test Changeset")
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["sys_id"], "456")
        self.assertEqual(result["change_count"], 1)

        self.assertEqual(mock_query_page.call_count, 2)
        first_call = mock_query_page.call_args_list[0]
        self.assertEqual(first_call[1]["table"], "sys_update_set")
        self.assertEqual(first_call[1]["query"], "sys_id=123")
        second_call = mock_query_page.call_args_list[1]
        self.assertEqual(second_call[1]["table"], "sys_update_xml")
        self.assertEqual(second_call[1]["query"], "update_set=123")

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_get_changeset_details_not_found(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(changeset_id="nonexistent")
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_get_changeset_details_error(self, mock_query_page):
        mock_query_page.side_effect = Exception("Server error")

        params = GetChangesetDetailsParams(changeset_id="123")
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Server error", result["message"])

    # --- create_changeset ---

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_create_changeset_success(self, mock_invalidate):
        self.auth_manager.make_request.return_value = self._make_response(
            {
                "result": {
                    "sys_id": "abc",
                    "name": "New Changeset",
                    "application": "Test App",
                }
            }
        )

        params = CreateChangesetParams(
            name="New Changeset",
            application="Test App",
            description="A test changeset",
        )
        result = create_changeset(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["sys_id"], "abc")
        self.assertEqual(result["message"], "Changeset created successfully")
        mock_invalidate.assert_called_once_with(table="sys_update_set")

        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/api/now/table/sys_update_set", args[1])
        self.assertEqual(kwargs["json"]["name"], "New Changeset")
        self.assertEqual(kwargs["json"]["application"], "Test App")
        self.assertEqual(kwargs["json"]["description"], "A test changeset")

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_create_changeset_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Create failed")

        params = CreateChangesetParams(name="Test", application="App")
        result = create_changeset(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Create failed", result["message"])
        mock_invalidate.assert_not_called()

    # --- update_changeset ---

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_update_changeset_success(self, mock_invalidate):
        self.auth_manager.make_request.return_value = self._make_response(
            {
                "result": {
                    "sys_id": "123",
                    "name": "Updated Name",
                    "state": "in_progress",
                }
            }
        )

        params = UpdateChangesetParams(
            changeset_id="123",
            name="Updated Name",
            state="in_progress",
        )
        result = update_changeset(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["sys_id"], "123")
        self.assertEqual(result["message"], "Changeset updated successfully")
        mock_invalidate.assert_called_once_with(table="sys_update_set")

        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "PATCH")
        self.assertIn("/api/now/table/sys_update_set/123", args[1])
        self.assertEqual(kwargs["json"]["name"], "Updated Name")
        self.assertEqual(kwargs["json"]["state"], "in_progress")

    def test_update_changeset_no_fields(self):
        params = UpdateChangesetParams(changeset_id="123")
        result = update_changeset(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No fields to update")
        self.auth_manager.make_request.assert_not_called()

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_update_changeset_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Update failed")

        params = UpdateChangesetParams(changeset_id="123", name="New Name")
        result = update_changeset(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Update failed", result["message"])
        mock_invalidate.assert_not_called()

    # --- commit_changeset ---

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_commit_changeset_success(self, mock_invalidate):
        self.auth_manager.make_request.return_value = self._make_response(
            {
                "result": {
                    "sys_id": "123",
                    "name": "Test Changeset",
                    "state": "complete",
                }
            }
        )

        params = CommitChangesetParams(
            changeset_id="123",
            commit_message="Final commit",
        )
        result = commit_changeset(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["state"], "complete")
        self.assertEqual(result["message"], "Changeset committed successfully")
        mock_invalidate.assert_called_once_with(table="sys_update_set")

        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "PATCH")
        self.assertIn("/api/now/table/sys_update_set/123", args[1])
        self.assertEqual(kwargs["json"]["state"], "complete")
        self.assertEqual(kwargs["json"]["description"], "Final commit")

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_commit_changeset_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Commit failed")

        params = CommitChangesetParams(changeset_id="123")
        result = commit_changeset(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Commit failed", result["message"])
        mock_invalidate.assert_not_called()

    # --- publish_changeset ---

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_publish_changeset_success(self, mock_invalidate):
        self.auth_manager.make_request.return_value = self._make_response(
            {
                "result": {
                    "sys_id": "123",
                    "name": "Test Changeset",
                    "state": "published",
                }
            }
        )

        params = PublishChangesetParams(changeset_id="123")
        result = publish_changeset(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["state"], "published")
        self.assertEqual(result["message"], "Changeset published successfully")
        mock_invalidate.assert_called_once_with(table="sys_update_set")

        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "PATCH")
        self.assertEqual(kwargs["json"]["state"], "published")

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_publish_changeset_with_notes(self, mock_invalidate):
        self.auth_manager.make_request.return_value = self._make_response(
            {"result": {"sys_id": "123", "state": "published"}}
        )

        params = PublishChangesetParams(
            changeset_id="123",
            publish_notes="Release notes here",
        )
        result = publish_changeset(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(kwargs["json"]["description"], "Release notes here")
        mock_invalidate.assert_called_once_with(table="sys_update_set")

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_publish_changeset_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Publish failed")

        params = PublishChangesetParams(changeset_id="123")
        result = publish_changeset(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Publish failed", result["message"])
        mock_invalidate.assert_not_called()

    # --- add_file_to_changeset ---

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_add_file_to_changeset_success(self, mock_invalidate):
        self.auth_manager.make_request.return_value = self._make_response(
            {
                "result": {
                    "sys_id": "456",
                    "name": "test_file.py",
                    "type": "file",
                    "update_set": "123",
                    "payload": "print('hello')",
                }
            }
        )

        params = AddFileToChangesetParams(
            changeset_id="123",
            file_path="test_file.py",
            file_content="print('hello')",
        )
        result = add_file_to_changeset(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["file"]["sys_id"], "456")
        self.assertEqual(result["message"], "File added to changeset successfully")
        mock_invalidate.assert_called_once_with(table="sys_update_xml")

        args, kwargs = self.auth_manager.make_request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/api/now/table/sys_update_xml", args[1])
        self.assertEqual(kwargs["json"]["update_set"], "123")
        self.assertEqual(kwargs["json"]["name"], "test_file.py")
        self.assertEqual(kwargs["json"]["payload"], "print('hello')")
        self.assertEqual(kwargs["json"]["type"], "file")

    @patch("servicenow_mcp.tools.changeset_tools.invalidate_query_cache")
    def test_add_file_to_changeset_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Add file failed")

        params = AddFileToChangesetParams(
            changeset_id="123",
            file_path="test.py",
            file_content="code",
        )
        result = add_file_to_changeset(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Add file failed", result["message"])
        mock_invalidate.assert_not_called()


class TestChangesetToolsParams(unittest.TestCase):
    """Tests for the changeset tools parameter classes."""

    def test_get_changeset_details_params_list_mode(self):
        params = GetChangesetDetailsParams(
            limit=20,
            offset=10,
            state="in_progress",
            application="Test App",
            developer="test.user",
            timeframe="recent",
            query="name=test",
        )
        self.assertIsNone(params.changeset_id)
        self.assertEqual(params.limit, 20)
        self.assertEqual(params.offset, 10)
        self.assertEqual(params.state, "in_progress")
        self.assertEqual(params.application, "Test App")
        self.assertEqual(params.developer, "test.user")
        self.assertEqual(params.timeframe, "recent")
        self.assertEqual(params.query, "name=test")

    def test_get_changeset_details_params_defaults(self):
        params = GetChangesetDetailsParams()
        self.assertIsNone(params.changeset_id)
        self.assertEqual(params.limit, 10)
        self.assertEqual(params.offset, 0)
        self.assertIsNone(params.state)
        self.assertFalse(params.count_only)

    def test_get_changeset_details_params_detail_mode(self):
        params = GetChangesetDetailsParams(changeset_id="123")
        self.assertEqual(params.changeset_id, "123")

    def test_create_changeset_params(self):
        params = CreateChangesetParams(
            name="Test Changeset",
            description="Test description",
            application="Test App",
            developer="test.user",
        )
        self.assertEqual(params.name, "Test Changeset")
        self.assertEqual(params.description, "Test description")
        self.assertEqual(params.application, "Test App")
        self.assertEqual(params.developer, "test.user")

    def test_update_changeset_params(self):
        params = UpdateChangesetParams(
            changeset_id="123",
            name="Updated Changeset",
            description="Updated description",
            state="in_progress",
            developer="test.user",
        )
        self.assertEqual(params.changeset_id, "123")
        self.assertEqual(params.name, "Updated Changeset")
        self.assertEqual(params.description, "Updated description")
        self.assertEqual(params.state, "in_progress")
        self.assertEqual(params.developer, "test.user")

    def test_commit_changeset_params(self):
        params = CommitChangesetParams(
            changeset_id="123",
            commit_message="Commit message",
        )
        self.assertEqual(params.changeset_id, "123")
        self.assertEqual(params.commit_message, "Commit message")

    def test_commit_changeset_params_no_message(self):
        params = CommitChangesetParams(changeset_id="123")
        self.assertIsNone(params.commit_message)

    def test_publish_changeset_params(self):
        params = PublishChangesetParams(
            changeset_id="123",
            publish_notes="Publish notes",
        )
        self.assertEqual(params.changeset_id, "123")
        self.assertEqual(params.publish_notes, "Publish notes")

    def test_add_file_to_changeset_params(self):
        params = AddFileToChangesetParams(
            changeset_id="123",
            file_path="test_file.py",
            file_content="print('Hello, world!')",
        )
        self.assertEqual(params.changeset_id, "123")
        self.assertEqual(params.file_path, "test_file.py")
        self.assertEqual(params.file_content, "print('Hello, world!')")


if __name__ == "__main__":
    unittest.main()
