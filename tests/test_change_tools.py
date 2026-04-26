"""
Tests for the change management tools.
"""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.change_tools import (
    ApproveChangeParams,
    GetChangeRequestDetailsParams,
    RejectChangeParams,
    SubmitChangeForApprovalParams,
    approve_change,
    get_change_request_details,
    reject_change,
    submit_change_for_approval,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestChangeTools(unittest.TestCase):
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
        self.auth_manager.get_headers.return_value = {
            "Authorization": "Basic dGVzdF91c2VyOnRlc3RfcGFzc3dvcmQ="
        }

    def _make_response(self, json_data):
        mock_response = MagicMock()
        mock_response.json.return_value = json_data
        mock_response.raise_for_status = MagicMock()
        return mock_response

    # ------------------------------------------------------------------ #
    # get_change_request_details – list mode (no change_id)
    # ------------------------------------------------------------------ #

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_list_change_requests_basic(self, mock_query_page):
        mock_query_page.return_value = (
            [{"sys_id": "ch1", "number": "CHG001"}],
            1,
        )
        params = GetChangeRequestDetailsParams()
        result = get_change_request_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["change_requests"]), 1)
        self.assertEqual(result["total"], 1)
        mock_query_page.assert_called_once_with(
            self.config,
            self.auth_manager,
            table="change_request",
            query="",
            fields="",
            limit=10,
            offset=0,
            display_value=True,
        )

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_list_change_requests_with_filters(self, mock_query_page):
        mock_query_page.return_value = (
            [{"sys_id": "ch1", "state": "open", "type": "normal"}],
            1,
        )
        params = GetChangeRequestDetailsParams(
            state="open",
            type="normal",
            category="Hardware",
            assignment_group="IT Support",
            query="short_description=Test",
        )
        result = get_change_request_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query_page.call_args
        query = (
            call_kwargs[1]["query"] if "query" in call_kwargs[1] else call_kwargs.kwargs["query"]
        )
        self.assertIn("state=open", query)
        self.assertIn("type=normal", query)
        self.assertIn("category=Hardware", query)
        self.assertIn("assignment_group=IT Support", query)
        self.assertIn("short_description=Test", query)

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_list_change_requests_timeframe_upcoming(self, mock_query_page):
        mock_query_page.return_value = ([], 0)
        params = GetChangeRequestDetailsParams(timeframe="upcoming")
        get_change_request_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs.kwargs.get("query", "")
        self.assertIn("start_date>", query)

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_list_change_requests_timeframe_in_progress(self, mock_query_page):
        mock_query_page.return_value = ([], 0)
        params = GetChangeRequestDetailsParams(timeframe="in-progress")
        get_change_request_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs.kwargs.get("query", "")
        self.assertIn("start_date<", query)
        self.assertIn("^end_date>", query)

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_list_change_requests_timeframe_completed(self, mock_query_page):
        mock_query_page.return_value = ([], 0)
        params = GetChangeRequestDetailsParams(timeframe="completed")
        get_change_request_details(self.config, self.auth_manager, params)

        call_kwargs = mock_query_page.call_args
        query = call_kwargs.kwargs.get("query", "")
        self.assertIn("end_date<", query)

    @patch("servicenow_mcp.tools.change_tools.sn_count")
    def test_list_change_requests_count_only(self, mock_count):
        mock_count.return_value = 42
        params = GetChangeRequestDetailsParams(count_only=True)
        result = get_change_request_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 42)
        mock_count.assert_called_once_with(
            self.config,
            self.auth_manager,
            "change_request",
            "",
        )

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_list_change_requests_error(self, mock_query_page):
        mock_query_page.side_effect = Exception("Network error")
        params = GetChangeRequestDetailsParams()
        result = get_change_request_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error listing change requests", result["message"])

    # ------------------------------------------------------------------ #
    # get_change_request_details
    # ------------------------------------------------------------------ #

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_get_change_request_details_found(self, mock_query_page):
        cr_data = {"sys_id": "cr123", "number": "CHG001", "short_description": "Test"}
        task_data = {"sys_id": "t1", "short_description": "Task 1"}
        mock_query_page.side_effect = [
            ([cr_data], 1),
            ([task_data], 1),
        ]

        params = GetChangeRequestDetailsParams(change_id="cr123")
        result = get_change_request_details(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["change_request"]["sys_id"], "cr123")
        self.assertEqual(len(result["tasks"]), 1)

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_get_change_request_details_not_found(self, mock_query_page):
        mock_query_page.return_value = ([], 0)

        params = GetChangeRequestDetailsParams(change_id="nonexistent")
        result = get_change_request_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_get_change_request_details_error(self, mock_query_page):
        mock_query_page.side_effect = Exception("Server error")

        params = GetChangeRequestDetailsParams(change_id="cr123")
        result = get_change_request_details(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error getting change request details", result["message"])

    # ------------------------------------------------------------------ #
    # submit_change_for_approval
    # ------------------------------------------------------------------ #

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    def test_submit_change_for_approval_success(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = [
            self._make_response({"result": {"sys_id": "cr1", "state": "assess"}}),
            self._make_response({"result": {"sys_id": "appr1", "state": "requested"}}),
        ]

        params = SubmitChangeForApprovalParams(change_id="cr1")
        result = submit_change_for_approval(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(self.auth_manager.make_request.call_count, 2)
        mock_invalidate.assert_any_call(table="change_request")
        mock_invalidate.assert_any_call(table="sysapproval_approver")
        self.assertEqual(mock_invalidate.call_count, 2)

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    def test_submit_change_for_approval_patch_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("PATCH failed")

        params = SubmitChangeForApprovalParams(change_id="cr1")
        result = submit_change_for_approval(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error submitting change for approval", result["message"])
        mock_invalidate.assert_not_called()

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    def test_submit_change_for_approval_post_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = [
            self._make_response({"result": {"sys_id": "cr1", "state": "assess"}}),
            Exception("POST approval failed"),
        ]

        params = SubmitChangeForApprovalParams(change_id="cr1")
        result = submit_change_for_approval(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error submitting change for approval", result["message"])
        mock_invalidate.assert_not_called()

    # ------------------------------------------------------------------ #
    # approve_change
    # ------------------------------------------------------------------ #

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_approve_change_success(self, mock_query_page, mock_invalidate):
        mock_query_page.return_value = (
            [{"sys_id": "approval123", "state": "requested"}],
            1,
        )
        self.auth_manager.make_request.return_value = self._make_response(
            {"result": {"sys_id": "..."}}
        )

        params = ApproveChangeParams(change_id="cr123")
        result = approve_change(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(self.auth_manager.make_request.call_count, 2)
        mock_invalidate.assert_any_call(table="sysapproval_approver")
        mock_invalidate.assert_any_call(table="change_request")

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_approve_change_no_approval_record(self, mock_query_page, mock_invalidate):
        mock_query_page.return_value = ([], 0)

        params = ApproveChangeParams(change_id="cr123")
        result = approve_change(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("No approval record found", result["message"])
        self.auth_manager.make_request.assert_not_called()
        mock_invalidate.assert_not_called()

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_approve_change_dry_run(self, mock_query_page):
        """dry_run=True returns a preview and issues no PATCH."""
        mock_query_page.side_effect = [
            ([{"sys_id": "approval123"}], 1),
            ([{"sys_id": "cr123", "number": "CHG0001", "state": "assess"}], 1),
        ]
        params = ApproveChangeParams(change_id="cr123", dry_run=True)
        result = approve_change(self.config, self.auth_manager, params)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["operation"], "approve_change")
        self.assertEqual(result["approval_record"]["new_state"], "approved")
        self.assertEqual(result["change_record"]["proposed_state"], "implement")
        self.auth_manager.make_request.assert_not_called()

    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_reject_change_dry_run(self, mock_query_page):
        """dry_run=True returns rejection preview without PATCH."""
        mock_query_page.side_effect = [
            ([{"sys_id": "approval456"}], 1),
            ([{"sys_id": "cr456", "number": "CHG0002", "state": "assess"}], 1),
        ]
        params = RejectChangeParams(
            change_id="cr456", rejection_reason="risk too high", dry_run=True
        )
        result = reject_change(self.config, self.auth_manager, params)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["approval_record"]["new_state"], "rejected")
        self.assertEqual(result["change_record"]["proposed_state"], "canceled")
        self.assertEqual(result["approval_record"]["rejection_reason"], "risk too high")
        self.auth_manager.make_request.assert_not_called()

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_approve_change_error(self, mock_query_page, mock_invalidate):
        mock_query_page.return_value = (
            [{"sys_id": "approval123", "state": "requested"}],
            1,
        )
        self.auth_manager.make_request.side_effect = Exception("PATCH failed")

        params = ApproveChangeParams(change_id="cr123")
        result = approve_change(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error approving change", result["message"])
        mock_invalidate.assert_not_called()

    # ------------------------------------------------------------------ #
    # reject_change
    # ------------------------------------------------------------------ #

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_reject_change_success(self, mock_query_page, mock_invalidate):
        mock_query_page.return_value = (
            [{"sys_id": "approval123", "state": "requested"}],
            1,
        )
        self.auth_manager.make_request.return_value = self._make_response(
            {"result": {"sys_id": "..."}}
        )

        params = RejectChangeParams(change_id="cr123", rejection_reason="Bad idea")
        result = reject_change(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(self.auth_manager.make_request.call_count, 2)

        # Verify PATCH calls contain correct data
        calls = self.auth_manager.make_request.call_args_list
        first_patch_body = calls[0][1]["json"]
        self.assertEqual(first_patch_body["state"], "rejected")
        self.assertEqual(first_patch_body["comments"], "Bad idea")

        second_patch_body = calls[1][1]["json"]
        self.assertEqual(second_patch_body["state"], "canceled")
        self.assertIn("Bad idea", second_patch_body["work_notes"])

        mock_invalidate.assert_any_call(table="sysapproval_approver")
        mock_invalidate.assert_any_call(table="change_request")

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_reject_change_no_approval_record(self, mock_query_page, mock_invalidate):
        mock_query_page.return_value = ([], 0)

        params = RejectChangeParams(change_id="cr123", rejection_reason="No")
        result = reject_change(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("No approval record found", result["message"])
        self.auth_manager.make_request.assert_not_called()
        mock_invalidate.assert_not_called()

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_reject_change_error(self, mock_query_page, mock_invalidate):
        mock_query_page.return_value = (
            [{"sys_id": "approval123", "state": "requested"}],
            1,
        )
        self.auth_manager.make_request.side_effect = Exception("PATCH failed")

        params = RejectChangeParams(change_id="cr123", rejection_reason="Bad")
        result = reject_change(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Error rejecting change", result["message"])
        mock_invalidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
