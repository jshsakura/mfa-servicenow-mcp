"""Tests for flow_designer_tools.py — shared query helper migration."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import (
    GetFlowDetailsParams,
    GetFlowExecutionsParams,
    ListFlowsParams,
    _fetch_flow_structure,
    _fetch_flow_triggers,
    get_flow_details,
    get_flow_executions,
    list_flows,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestFlowDesignerTools(unittest.TestCase):
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
            "Authorization": "Bearer test",
            "Content-Type": "application/json",
        }

    # -- list_flows ----------------------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_happy(self, mock_qp):
        flows_data = [
            {
                "sys_id": "f1",
                "name": "Incident Auto-Assign",
                "status": "Published",
                "active": "true",
            },
            {
                "sys_id": "f2",
                "name": "Change Approval",
                "status": "Draft",
                "active": "true",
            },
        ]
        mock_qp.return_value = (flows_data, 2)

        result = list_flows(self.config, self.auth_manager, ListFlowsParams())

        self.assertTrue(result["success"])
        self.assertEqual(len(result["flows"]), 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["total"], 2)
        mock_qp.assert_called_once()
        call_kwargs = mock_qp.call_args
        self.assertEqual(call_kwargs[1]["table"], "sys_hub_flow")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    def test_list_flows_count_only(self, mock_cnt):
        mock_cnt.return_value = 42

        result = list_flows(
            self.config,
            self.auth_manager,
            ListFlowsParams(count_only=True),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 42)
        self.assertNotIn("flows", result)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_with_filters(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = list_flows(
            self.config,
            self.auth_manager,
            ListFlowsParams(active=True, status="Published", name="Incident", scope="global"),
        )

        self.assertTrue(result["success"])
        call_kwargs = mock_qp.call_args[1]
        query = call_kwargs["query"]
        self.assertIn("active=true", query)
        self.assertIn("status=Published", query)
        self.assertIn("nameLIKEIncident", query)
        self.assertIn("sys_scopeLIKEglobal", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Network error")

        result = list_flows(self.config, self.auth_manager, ListFlowsParams())

        self.assertFalse(result["success"])
        self.assertIn("Network error", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_with_additional_query(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_flows(
            self.config,
            self.auth_manager,
            ListFlowsParams(query="sys_created_on>=2024-01-01"),
        )

        call_query = mock_qp.call_args[1]["query"]
        self.assertIn("sys_created_on>=2024-01-01", call_query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_respects_limit_and_offset(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_flows(
            self.config,
            self.auth_manager,
            ListFlowsParams(limit=50, offset=100),
        )

        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["limit"], 50)
        self.assertEqual(call_kwargs["offset"], 100)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_limit_capped_at_100(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_flows(
            self.config,
            self.auth_manager,
            ListFlowsParams(limit=500),
        )

        self.assertEqual(mock_qp.call_args[1]["limit"], 100)

    # -- get_flow_details ----------------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_details_happy(self, mock_qp):
        flow_data = [
            {
                "sys_id": "abc123",
                "name": "Test Flow",
                "status": "Published",
                "active": "true",
                "trigger_type": "Record",
            }
        ]
        mock_qp.return_value = (flow_data, 1)

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(flow_id="abc123"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["flow"]["sys_id"], "abc123")
        # Without include_triggers, triggers should not be in response
        self.assertNotIn("triggers", result)

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_details_with_triggers(self, mock_qp, mock_triggers):
        flow_data = [{"sys_id": "abc123", "name": "Test Flow"}]
        mock_qp.return_value = (flow_data, 1)
        mock_triggers.return_value = [{"sys_id": "t1", "name": "Record Trigger"}]

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(flow_id="abc123", include_triggers=True),
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["triggers"]), 1)
        mock_triggers.assert_called_once()

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_details_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(flow_id="nonexistent"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["flow"], {})

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_details_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("API error")

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(flow_id="abc123"),
        )

        self.assertFalse(result["success"])
        self.assertIn("API error", result["error"])

    # -- get_flow_structure --------------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._try_flow_designer_api")
    def test_get_flow_structure_designer_api(self, mock_designer_api, mock_qp):
        mock_designer_api.return_value = {
            "result": {
                "flow_id": "flow1",
                "actions": [{"name": "Log"}],
            }
        }

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow1",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "flow_designer_api")
        self.assertIn("data", result)
        mock_qp.assert_not_called()

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._try_flow_designer_api")
    def test_get_flow_structure_table_api_fallback(self, mock_designer_api, mock_qp):
        mock_designer_api.return_value = None

        snapshot_data = [{"sys_id": "snap1", "name": "Flow v1", "status": "Published"}]
        actions_data = [
            {"sys_id": "a1", "name": "Log Action", "order": "100", "nesting_parent": ""},
        ]
        logic_data = [
            {
                "sys_id": "l1",
                "name": "If condition",
                "order": "200",
                "type": "IF",
                "nesting_parent": "",
            },
        ]
        subflow_data = [
            {"sys_id": "s1", "name": "SubFlow Call", "order": "300", "nesting_parent": ""},
        ]

        mock_qp.side_effect = [
            (snapshot_data, 1),
            (actions_data, 1),
            (logic_data, 1),
            (subflow_data, 1),
        ]

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow1",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "table_api_fallback")
        self.assertEqual(result["snapshot_id"], "snap1")
        self.assertEqual(result["total_actions"], 1)
        self.assertEqual(result["total_logic"], 1)
        self.assertEqual(result["total_subflows"], 1)
        self.assertIn("flat_summary", result)
        self.assertIn("tree", result)

        for entry in result["flat_summary"]:
            if entry["type"] == "action":
                self.assertIn("action_type", entry)
            elif entry["type"] == "logic":
                self.assertIn("logic_type", entry)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._try_flow_designer_api")
    def test_get_flow_structure_no_snapshot(self, mock_designer_api, mock_qp):
        mock_designer_api.return_value = None
        mock_qp.return_value = ([], 0)

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow_no_snap",
        )

        self.assertFalse(result["success"])
        self.assertIn("No snapshot found", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._try_flow_designer_api")
    def test_get_flow_structure_prefers_published_snapshot(self, mock_designer_api, mock_qp):
        mock_designer_api.return_value = None

        snapshot_data = [
            {"sys_id": "snap_draft", "name": "Flow v1", "status": "Draft"},
            {"sys_id": "snap_pub", "name": "Flow v2", "status": "Published"},
        ]
        mock_qp.side_effect = [
            (snapshot_data, 2),
            ([], 0),
            ([], 0),
            ([], 0),
        ]

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow1",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["snapshot_id"], "snap_pub")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._try_flow_designer_api")
    def test_get_flow_structure_nesting(self, mock_designer_api, mock_qp):
        mock_designer_api.return_value = None

        snapshot_data = [{"sys_id": "snap1", "status": "Published"}]
        actions_data = [
            {
                "sys_id": "a1",
                "name": "Parent Action",
                "order": "100",
                "nesting_parent": "",
                "action_type": "log",
            },
            {
                "sys_id": "a2",
                "name": "Child Action",
                "order": "200",
                "nesting_parent": "a1",
                "action_type": "log",
            },
        ]
        mock_qp.side_effect = [
            (snapshot_data, 1),
            (actions_data, 2),
            ([], 0),
            ([], 0),
        ]

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow1",
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["tree"]), 1)
        self.assertEqual(len(result["tree"][0]["children"]), 1)
        self.assertEqual(result["tree"][0]["children"][0]["sys_id"], "a2")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._try_flow_designer_api")
    def test_get_flow_structure_error(self, mock_designer_api, mock_qp):
        mock_designer_api.return_value = None
        mock_qp.side_effect = RuntimeError("Connection failed")

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow1",
        )

        self.assertFalse(result["success"])
        self.assertIn("Connection failed", result["error"])

    # -- get_flow_executions -------------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_executions_happy(self, mock_qp):
        exec_data = [
            {
                "sys_id": "ctx1",
                "name": "Incident Flow",
                "state": "Complete",
                "sys_created_on": "2024-01-15 10:00:00",
            },
            {
                "sys_id": "ctx2",
                "name": "Change Flow",
                "state": "Error",
                "error_message": "Script error",
                "sys_created_on": "2024-01-14 08:00:00",
            },
        ]
        mock_qp.return_value = (exec_data, 2)

        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(),
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["executions"]), 2)
        self.assertEqual(result["count"], 2)

        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["table"], "sys_flow_context")
        self.assertEqual(call_kwargs["orderby"], "-sys_created_on")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_executions_with_filters(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(
                flow_name="Incident",
                flow_id="f1",
                state="Error",
                source_record="INC001",
                errors_only=True,
            ),
        )

        self.assertTrue(result["success"])
        call_query = mock_qp.call_args[1]["query"]
        self.assertIn("nameLIKEIncident", call_query)
        self.assertIn("flow=f1", call_query)
        self.assertIn("state=Error", call_query)
        self.assertIn("source_recordLIKEINC001", call_query)
        self.assertIn("stateINError,Cancelled", call_query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_executions_errors_only(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(errors_only=True),
        )

        call_query = mock_qp.call_args[1]["query"]
        self.assertIn("stateINError,Cancelled", call_query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_executions_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Timeout")

        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(),
        )

        self.assertFalse(result["success"])
        self.assertIn("Timeout", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_executions_empty_query_with_orderby(self, mock_qp):
        mock_qp.return_value = ([], 0)

        get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(),
        )

        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["query"], "")
        self.assertEqual(call_kwargs["orderby"], "-sys_created_on")

    # -- get_flow_execution_detail -------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_execution_detail_happy(self, mock_qp):
        detail_data = [
            {
                "sys_id": "ctx_detail1",
                "name": "Incident Flow",
                "state": "Complete",
                "run_time": "5",
                "error_message": "",
                "source_table": "incident",
                "source_record": "INC0010001",
            }
        ]
        mock_qp.return_value = (detail_data, 1)

        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(context_id="ctx_detail1"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["execution"]["sys_id"], "ctx_detail1")
        self.assertEqual(result["execution"]["state"], "Complete")

        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["table"], "sys_flow_context")
        self.assertEqual(call_kwargs["query"], "sys_id=ctx_detail1")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_execution_detail_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(context_id="nonexistent"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["execution"], {})

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_execution_detail_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Not found")

        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(context_id="ctx1"),
        )

        self.assertFalse(result["success"])
        self.assertIn("Not found", result["error"])

    # -- get_flow_triggers ---------------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_triggers_happy(self, mock_qp):
        snapshot_data = [{"sys_id": "snap1", "status": "Published"}]
        trigger_data = [
            {
                "sys_id": "trig1",
                "name": "Record Created",
                "flow": "flow1",
            },
            {
                "sys_id": "trig2",
                "name": "Record Updated",
                "flow": "snap1",
            },
        ]
        mock_qp.side_effect = [(snapshot_data, 1), (trigger_data, 2)]

        triggers = _fetch_flow_triggers(
            self.config,
            self.auth_manager,
            "flow1",
        )

        self.assertEqual(len(triggers), 2)

        trigger_call = mock_qp.call_args_list[1][1]
        self.assertEqual(trigger_call["table"], "sys_hub_trigger_instance")
        trigger_query = trigger_call["query"]
        self.assertIn("flow=flow1", trigger_query)
        self.assertIn("flow=snap1", trigger_query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_triggers_no_snapshot(self, mock_qp):
        mock_qp.side_effect = [([], 0), ([], 0)]

        triggers = _fetch_flow_triggers(
            self.config,
            self.auth_manager,
            "flow1",
        )

        self.assertEqual(triggers, [])
        trigger_query = mock_qp.call_args_list[1][1]["query"]
        self.assertEqual(trigger_query, "flow=flow1")

    # -- _try_flow_designer_api direct tests ---------------------------------

    def test_try_flow_designer_api_success(self):
        from servicenow_mcp.tools.flow_designer_tools import _try_flow_designer_api

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"flow_id": "f1", "actions": []}}
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_flow_designer_api(self.config, self.auth_manager, "f1")

        assert result is not None
        self.assertIn("result", result)

    def test_try_flow_designer_api_falls_back_to_second_path(self):
        from servicenow_mcp.tools.flow_designer_tools import _try_flow_designer_api

        fail_resp = MagicMock()
        fail_resp.raise_for_status.side_effect = Exception("Not found")

        success_resp = MagicMock()
        success_resp.json.return_value = {"result": {"flow_id": "f1"}}
        success_resp.raise_for_status.return_value = None

        self.auth_manager.make_request.side_effect = [fail_resp, success_resp]

        result = _try_flow_designer_api(self.config, self.auth_manager, "f1")

        self.assertIsNotNone(result)
        self.assertEqual(self.auth_manager.make_request.call_count, 2)

    def test_try_flow_designer_api_returns_none_when_both_fail(self):
        from servicenow_mcp.tools.flow_designer_tools import _try_flow_designer_api

        self.auth_manager.make_request.side_effect = Exception("Server error")

        result = _try_flow_designer_api(self.config, self.auth_manager, "f1")

        self.assertIsNone(result)

    # -- _get_snapshot_id direct tests ---------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_snapshot_id_prefers_published(self, mock_qp):
        from servicenow_mcp.tools.flow_designer_tools import _get_snapshot_id

        snapshots = [
            {"sys_id": "snap_draft", "status": "Draft"},
            {"sys_id": "snap_pub", "status": "Published"},
        ]
        mock_qp.return_value = (snapshots, 2)

        result = _get_snapshot_id(self.config, self.auth_manager, "flow1")

        self.assertEqual(result, "snap_pub")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_snapshot_id_falls_back_to_first(self, mock_qp):
        from servicenow_mcp.tools.flow_designer_tools import _get_snapshot_id

        snapshots = [
            {"sys_id": "snap1", "status": "Draft"},
        ]
        mock_qp.return_value = (snapshots, 1)

        result = _get_snapshot_id(self.config, self.auth_manager, "flow1")

        self.assertEqual(result, "snap1")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_snapshot_id_returns_none_empty(self, mock_qp):
        from servicenow_mcp.tools.flow_designer_tools import _get_snapshot_id

        mock_qp.return_value = ([], 0)

        result = _get_snapshot_id(self.config, self.auth_manager, "flow1")

        self.assertIsNone(result)

    # -- _build_component_tree tests -----------------------------------------

    def test_build_component_tree_flat(self):
        from servicenow_mcp.tools.flow_designer_tools import _build_component_tree

        components = [
            {"sys_id": "a1", "order": "100", "nesting_parent": ""},
            {"sys_id": "a2", "order": "200", "nesting_parent": ""},
        ]

        tree = _build_component_tree(components)

        self.assertEqual(len(tree), 2)
        self.assertEqual(len(tree[0]["children"]), 0)

    def test_build_component_tree_nested(self):
        from servicenow_mcp.tools.flow_designer_tools import _build_component_tree

        components = [
            {"sys_id": "a1", "order": "100", "nesting_parent": ""},
            {"sys_id": "a2", "order": "200", "nesting_parent": "a1"},
            {"sys_id": "a3", "order": "300", "nesting_parent": "a1"},
        ]

        tree = _build_component_tree(components)

        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["sys_id"], "a1")
        self.assertEqual(len(tree[0]["children"]), 2)

    def test_build_component_tree_empty(self):
        from servicenow_mcp.tools.flow_designer_tools import _build_component_tree

        tree = _build_component_tree([])

        self.assertEqual(tree, [])


if __name__ == "__main__":
    unittest.main()
