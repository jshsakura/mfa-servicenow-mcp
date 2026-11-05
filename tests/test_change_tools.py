"""
Tests for the change management tools.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.change_tools import (
    ApproveChangeParams,
    RejectChangeParams,
    SubmitChangeForApprovalParams,
    approve_change,
    reject_change,
    submit_change_for_approval,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# Writes to choice columns resolve against sys_choice first; answered by conftest.
pytestmark = pytest.mark.usefixtures("live_choices")


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
        # The caller check + approval write live in approval_tools (own tests in
        # test_approval_tools.py); here decide_approval is stubbed as "allowed and applied",
        # so the approval PATCH is no longer one of make_request's calls.
        patcher = patch(
            "servicenow_mcp.tools.change_tools.decide_approval",
            return_value={"success": True, "basis": "approver", "caller": "test_user"},
        )
        self.mock_decide = patcher.start()
        self.addCleanup(patcher.stop)

    def _make_response(self, json_data):
        mock_response = MagicMock()
        mock_response.json.return_value = json_data
        mock_response.raise_for_status = MagicMock()
        return mock_response

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
        self.assertEqual(self.auth_manager.make_request.call_count, 1)  # change_request only
        self.assertEqual(self.mock_decide.call_args[1]["approval_id"], "approval123")
        self.assertEqual(self.mock_decide.call_args[1]["decision"], "approved")
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
        # change_request.state is an integer choice: the word was stored as-is and
        # the change never moved. -1 = Implement.
        self.assertEqual(result["change_record"]["proposed_state"], "-1")
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
        self.assertEqual(result["change_record"]["proposed_state"], "4")  # Canceled
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
        self.assertEqual(self.auth_manager.make_request.call_count, 1)

        # The approval write moved to decide_approval; the change PATCH is what remains.
        kw = self.mock_decide.call_args[1]
        self.assertEqual(kw["decision"], "rejected")
        self.assertEqual(kw["comments"], "Bad idea")
        change_patch_body = self.auth_manager.make_request.call_args_list[0][1]["json"]
        self.assertEqual(change_patch_body["state"], "4")  # Canceled
        self.assertIn("Bad idea", change_patch_body["work_notes"])

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

    # ------------------------------------------------------------------ #
    # correctness fixes: approver targeting, change_state, pending pref
    # ------------------------------------------------------------------ #

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_approve_change_targets_specified_approver(self, mock_query_page, mock_invalidate):
        """approver_id selects THAT approver's record, not just the first."""
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "ap_alice",
                    "approver": {"value": "u_alice", "display_value": "Alice"},
                    "state": "requested",
                },
                {
                    "sys_id": "ap_bob",
                    "approver": {"value": "u_bob", "display_value": "Bob"},
                    "state": "requested",
                },
            ],
            2,
        )
        self.auth_manager.make_request.return_value = self._make_response({"result": {}})

        params = ApproveChangeParams(change_id="cr1", approver_id="u_bob")
        result = approve_change(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        # The decision must target Bob's approval record, not the first row.
        self.assertEqual(self.mock_decide.call_args[1]["approval_id"], "ap_bob")
        # The broadened lookup queries document_id OR sysapproval.
        q = mock_query_page.call_args[1]["query"]
        self.assertIn("document_id=cr1", q)
        self.assertIn("ORsysapproval=cr1", q)

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_approve_change_unknown_approver_errors(self, mock_query_page, mock_invalidate):
        mock_query_page.return_value = (
            [{"sys_id": "ap_alice", "approver": {"value": "u_alice"}, "state": "requested"}],
            1,
        )
        params = ApproveChangeParams(change_id="cr1", approver_id="u_nobody")
        result = approve_change(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("No approval record for approver", result["message"])
        self.auth_manager.make_request.assert_not_called()

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_approve_change_state_override(self, mock_query_page, mock_invalidate):
        """change_state overrides the default (Implement), resolved to its code."""
        mock_query_page.return_value = ([{"sys_id": "ap1", "state": "requested"}], 1)
        self.auth_manager.make_request.return_value = self._make_response({"result": {}})

        params = ApproveChangeParams(change_id="cr1", change_state="scheduled")
        result = approve_change(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        change_patch_body = self.auth_manager.make_request.call_args_list[0][1]["json"]
        self.assertEqual(change_patch_body["state"], "-2")  # Scheduled

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_approve_change_prefers_pending_record(self, mock_query_page, mock_invalidate):
        """An already-approved record is skipped in favor of a pending one."""
        mock_query_page.return_value = (
            [
                {"sys_id": "ap_done", "approver": {"value": "u1"}, "state": "approved"},
                {"sys_id": "ap_open", "approver": {"value": "u2"}, "state": "requested"},
            ],
            2,
        )
        self.auth_manager.make_request.return_value = self._make_response({"result": {}})

        params = ApproveChangeParams(change_id="cr1")
        approve_change(self.config, self.auth_manager, params)

        self.assertEqual(self.mock_decide.call_args[1]["approval_id"], "ap_open")

    # ------------------------------------------------------------------ #
    # caller verification (delegated to approval_tools.decide_approval)
    # ------------------------------------------------------------------ #

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_refused_caller_stops_before_change_write(self, mock_query_page, mock_invalidate):
        """approve on someone else's behalf without confirmation: nothing is written."""
        mock_query_page.return_value = (
            [{"sys_id": "ap_bob", "approver": {"value": "u_bob"}, "state": "requested"}],
            1,
        )
        self.mock_decide.return_value = {"success": False, "error": "caller_not_approver"}
        result = approve_change(
            self.config,
            self.auth_manager,
            ApproveChangeParams(change_id="cr1", approver_id="u_bob"),
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "caller_not_approver")
        self.auth_manager.make_request.assert_not_called()
        mock_invalidate.assert_not_called()

    @patch("servicenow_mcp.tools.change_tools.invalidate_query_cache")
    @patch("servicenow_mcp.tools.change_tools.sn_query_page")
    def test_confirm_on_behalf_is_forwarded(self, mock_query_page, mock_invalidate):
        mock_query_page.return_value = (
            [{"sys_id": "ap_bob", "approver": {"value": "u_bob"}, "state": "requested"}],
            1,
        )
        self.auth_manager.make_request.return_value = self._make_response({"result": {}})
        reject_change(
            self.config,
            self.auth_manager,
            RejectChangeParams(
                change_id="cr1", rejection_reason="no", approver_id="u_bob", confirm_on_behalf="bob"
            ),
        )
        self.assertEqual(self.mock_decide.call_args[1]["confirm_on_behalf"], "bob")


if __name__ == "__main__":
    unittest.main()
