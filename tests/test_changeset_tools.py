"""Tests for the changeset tools (surviving read tool: get_changeset_details)."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.changeset_tools import GetChangesetDetailsParams, get_changeset_details
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestChangesetTools(unittest.TestCase):
    """Tests for get_changeset_details."""

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
        self.assertIn("Last 7 days", query)

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_with_timeframe_last_week(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(timeframe="last_week")
        get_changeset_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs[1]["query"]
        self.assertIn("Last week", query)

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_with_timeframe_last_month(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(timeframe="last_month")
        get_changeset_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs[1]["query"]
        self.assertIn("Last month", query)

    @patch("servicenow_mcp.tools.changeset_tools.sn_count")
    def test_list_changesets_count_only(self, mock_count):
        mock_count.return_value = 5

        params = GetChangesetDetailsParams(count_only=True)
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 5)

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_error(self, mock_query_page):
        mock_query_page.side_effect = Exception("Server error")

        params = GetChangesetDetailsParams()
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Server error", result["message"])

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_list_changesets_combined_filters(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(
            state="in_progress", application="App1", developer="test.user"
        )
        get_changeset_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs[1]["query"]
        self.assertIn("state=in_progress", query)
        self.assertIn("application=App1", query)
        self.assertIn("developer=test.user", query)

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_get_changeset_details_found(self, mock_query_page):
        changeset_data = {
            "sys_id": "123",
            "name": "Test Changeset",
            "state": "in_progress",
        }
        changes_data = [{"sys_id": "456", "name": "Change 1"}]

        mock_query_page.side_effect = [
            ([changeset_data], 1),
            (changes_data, 1),
        ]

        params = GetChangesetDetailsParams(changeset_id="123")
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["changeset"]["sys_id"], "123")
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["change_count"], 1)

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_get_changeset_details_not_found(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangesetDetailsParams(changeset_id="nonexistent")
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    @patch("servicenow_mcp.tools.changeset_tools.sn_query_page")
    def test_get_changeset_details_error(self, mock_query_page):
        mock_query_page.side_effect = Exception("DB error")

        params = GetChangesetDetailsParams(changeset_id="123")
        result = get_changeset_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("DB error", result["message"])


class TestChangesetToolsParams(unittest.TestCase):
    """Tests for GetChangesetDetailsParams."""

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


if __name__ == "__main__":
    unittest.main()
