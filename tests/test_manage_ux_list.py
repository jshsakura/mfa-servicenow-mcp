"""Tests for manage_ux_list (sys_ux_list)."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.tools.ux_list_tools import ManageUxListParams, manage_ux_list
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

SVC = "servicenow_mcp.services.ux_list"


def _mock_response(result):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"result": result}
    return resp


class TestManageUxList(unittest.TestCase):
    def setUp(self):
        invalidate_query_cache()
        auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        )
        self.config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=auth_config,
        )
        self.auth = MagicMock(spec=AuthManager)
        self.auth.get_headers.return_value = {"Content-Type": "application/json"}

    def _run(self, **kw):
        return manage_ux_list(self.config, self.auth, ManageUxListParams(**kw))

    # --- list ---

    @patch(f"{SVC}.sn_query_page")
    def test_list_happy(self, mock_query):
        mock_query.return_value = (
            [
                {
                    "sys_id": "l1",
                    "title": "Direct OI",
                    "table": "x_myapp_oi_report",
                    "view": {"display_value": "YKO_DIRECT_OI"},
                    "columns": "new_number,state",
                    "fixed_query": "company=abc",
                    "condition": "",
                    "order": "40",
                    "active": {"display_value": "true"},
                    "sys_scope": {"display_value": "BPM"},
                    "sys_updated_on": "2026-01-01 00:00:00",
                }
            ],
            1,
        )
        result = self._run(action="list", table="x_myapp_oi_report")
        self.assertTrue(result["success"])
        self.assertEqual(1, len(result["lists"]))
        self.assertEqual("l1", result["lists"][0]["sys_id"])
        self.assertEqual("YKO_DIRECT_OI", result["lists"][0]["view"])
        self.assertTrue(result["lists"][0]["active"])
        _, kwargs = mock_query.call_args
        self.assertEqual("table=x_myapp_oi_report", kwargs["query"])
        self.assertEqual("sys_ux_list", kwargs["table"])

    @patch("servicenow_mcp.tools.sn_api.sn_count")
    def test_list_count_only(self, mock_count):
        mock_count.return_value = 4
        result = self._run(action="list", table="x_myapp_oi_report", count_only=True)
        self.assertTrue(result["success"])
        self.assertEqual(4, result["count"])
        mock_count.assert_called_once_with(
            self.config, self.auth, "sys_ux_list", "table=x_myapp_oi_report"
        )

    @patch("servicenow_mcp.tools.sn_api.sn_count")
    def test_list_count_only_reports_a_read_that_failed(self, mock_count):
        mock_count.side_effect = RuntimeError("stats endpoint timed out")
        result = self._run(action="list", count_only=True)
        self.assertFalse(result["success"])
        self.assertIn("timed out", result["message"])
        self.assertNotIn("count", result)

    # --- get ---

    @patch(f"{SVC}.sn_query_page")
    def test_get_happy(self, mock_query):
        mock_query.return_value = (
            [
                {
                    "sys_id": "l1",
                    "title": "Direct OI",
                    "table": "x_myapp_oi_report",
                    "view": None,
                    "columns": "new_number,state",
                    "fixed_query": "company=abc",
                    "condition": "",
                    "order": "40",
                    "active": "true",
                    "sys_scope": "BPM",
                    "sys_updated_on": "2026-01-01 00:00:00",
                }
            ],
            1,
        )
        result = self._run(action="get", sys_id="l1")
        self.assertTrue(result["success"])
        self.assertEqual("Direct OI", result["list"]["title"])

    @patch(f"{SVC}.sn_query_page")
    def test_get_not_found(self, mock_query):
        mock_query.return_value = ([], 0)
        result = self._run(action="get", sys_id="ghost")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    # --- update: view resolution ---

    @patch(f"{SVC}.sn_query_page")
    def test_update_resolves_view_name_to_sys_id(self, mock_query):
        # 1st call: get_list existence check; 2nd: resolve view by name
        mock_query.side_effect = [
            ([{"sys_id": "l1", "title": "Direct OI"}], 1),
            ([{"sys_id": "80e4...view", "name": "yko_direct_oi"}], 1),
        ]
        self.auth.make_request.return_value = _mock_response({"sys_id": "l1", "title": "Direct OI"})
        result = self._run(action="update", sys_id="l1", view="YKO_DIRECT_OI")
        self.assertTrue(result["success"])
        _, kwargs = self.auth.make_request.call_args
        # The reference field gets a real sys_id, never the display name.
        self.assertEqual("80e4...view", kwargs["json"]["view"])

    @patch(f"{SVC}.sn_query_page")
    def test_update_unresolvable_view_name_fails_loud(self, mock_query):
        mock_query.side_effect = [
            ([{"sys_id": "l1", "title": "Direct OI"}], 1),  # get_list
            ([], 0),  # view lookup miss
        ]
        result = self._run(action="update", sys_id="l1", view="Nonexistent View")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])
        self.auth.make_request.assert_not_called()

    @patch(f"{SVC}.sn_query_page")
    def test_update_view_accepts_bare_sys_id_without_a_lookup(self, mock_query):
        mock_query.return_value = ([{"sys_id": "l1", "title": "Direct OI"}], 1)  # get_list only
        self.auth.make_request.return_value = _mock_response({"sys_id": "l1", "title": "Direct OI"})
        result = self._run(action="update", sys_id="l1", view="80e464b13be64310ec3cbf2a85e45ab2")
        self.assertTrue(result["success"])
        mock_query.assert_called_once()  # only the existence check — no name lookup
        _, kwargs = self.auth.make_request.call_args
        self.assertEqual("80e464b13be64310ec3cbf2a85e45ab2", kwargs["json"]["view"])

    # --- update: clearing columns ---

    @patch(f"{SVC}.sn_query_page")
    def test_update_can_clear_columns_with_empty_string(self, mock_query):
        mock_query.return_value = ([{"sys_id": "l1", "title": "Direct OI"}], 1)
        self.auth.make_request.return_value = _mock_response({"sys_id": "l1", "title": "Direct OI"})
        result = self._run(action="update", sys_id="l1", columns="")
        self.assertTrue(result["success"])
        _, kwargs = self.auth.make_request.call_args
        self.assertEqual("", kwargs["json"]["columns"])

    # --- update: not found / dry run ---

    @patch(f"{SVC}.sn_query_page")
    def test_update_not_found(self, mock_query):
        mock_query.return_value = ([], 0)
        result = self._run(action="update", sys_id="ghost", columns="")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])
        self.auth.make_request.assert_not_called()

    @patch(f"{SVC}.build_update_preview")
    @patch(f"{SVC}.sn_query_page")
    def test_update_dry_run(self, mock_query, mock_preview):
        mock_query.return_value = ([{"sys_id": "l1", "title": "Direct OI"}], 1)
        mock_preview.return_value = {"dry_run": True, "operation": "update"}
        result = self._run(action="update", sys_id="l1", fixed_query="company=x", dry_run=True)
        self.assertTrue(result["dry_run"])
        self.auth.make_request.assert_not_called()
        mock_preview.assert_called_once()

    # --- validation ---

    def test_validation_errors(self):
        bad = [
            {"action": "get"},
            {"action": "update", "sys_id": "l1"},  # no field to change
            {"action": "update", "fixed_query": "x"},  # no sys_id
        ]
        for kw in bad:
            with self.assertRaises(ValueError):
                ManageUxListParams(**kw)


if __name__ == "__main__":
    unittest.main()
