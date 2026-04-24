"""Tests for flow_designer_tools.py — full Workflow Studio coverage."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import (
    CompareFlowsParams,
    GetActionDetailParams,
    GetDecisionTableDetailParams,
    GetFlowDetailsParams,
    GetFlowExecutionsParams,
    GetFlowFullDetailParams,
    GetPlaybookDetailParams,
    ListActionsParams,
    ListDecisionTablesParams,
    ListFlowsParams,
    ListPlaybooksParams,
    _fetch_flow_structure,
    _fetch_flow_triggers,
    compare_flows,
    get_action_detail,
    get_decision_table_detail,
    get_flow_details,
    get_flow_executions,
    get_flow_full_detail,
    get_playbook_detail,
    list_actions,
    list_decision_tables,
    list_flows,
    list_playbooks,
)
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    ServerConfig,
)


def _make_basic_config():
    """Create a test config with basic auth (Table API only)."""
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        ),
    )


def _make_browser_config():
    """Create a test config with browser auth (processflow API available)."""
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(),
        ),
    )


class TestFlowDesignerTools(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.browser_config = _make_browser_config()
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
            ListFlowsParams(status="Published", name="Incident", scope="global"),
        )

        self.assertTrue(result["success"])
        call_kwargs = mock_qp.call_args[1]
        query = call_kwargs["query"]
        self.assertIn("active=true", query)
        self.assertIn("status=Published", query)
        self.assertIn("nameLIKEIncident", query)
        self.assertIn("sys_scope.scope=global^ORsys_scope.name=global", query)

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

    # -- get_flow_structure (browser auth → processflow API) ------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_get_flow_structure_processflow_api_browser_auth(self, mock_processflow, mock_qp):
        """Browser auth → processflow API returns full structure in one call."""
        mock_processflow.return_value = {
            "result": {
                "id": "flow1",
                "name": "Test Flow",
                "actionInstances": [{"name": "Log", "position": "1"}],
                "flowLogicInstances": [],
                "subFlowInstances": [],
                "triggerInstances": [{"name": "Record Trigger"}],
                "flowVariables": [],
                "inputs": [],
                "outputs": [],
            }
        }

        result = _fetch_flow_structure(
            self.browser_config,
            self.auth_manager,
            "flow1",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "processflow_api")
        self.assertEqual(result["total_actions"], 1)
        self.assertEqual(result["total_triggers"], 1)
        self.assertIn("flat_summary", result)
        mock_qp.assert_not_called()

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_structure_basic_auth_skips_processflow(self, mock_qp, mock_processflow):
        """Basic auth → processflow API is never called."""
        mock_qp.return_value = ([], 0)

        _fetch_flow_structure(self.config, self.auth_manager, "flow1")

        mock_processflow.assert_not_called()

    # -- get_flow_structure (basic auth → Table API) -------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_structure_table_api_fallback(self, mock_qp):
        """Basic auth uses Table API (snapshot + components)."""
        snapshot_data = [{"sys_id": "snap1", "name": "Flow v1", "status": "Published"}]
        flow_record = [{"sys_id": "flow1", "name": "Test Flow", "label_cache": ""}]
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
        # Binding resolution: display_value=all returns dicts for reference fields
        binding_all = [
            {
                "sys_id": "s1",
                "name": "SubFlow Call",
                "order": "300",
                "position": "",
                "ui_id": "ui1",
                "parent_ui_id": "",
                "nesting_parent": "",
                "subflow": {"value": "snap_sub1", "display_value": "SubFlow Call"},
            },
        ]
        snap_all = [
            {
                "sys_id": "snap_sub1",
                "name": "SubFlow v1",
                "master_flow": {"value": "mf1", "display_value": "SubFlow Master"},
            }
        ]

        mock_qp.side_effect = [
            (snapshot_data, 1),
            (flow_record, 1),
            (actions_data, 1),
            (logic_data, 1),
            (subflow_data, 1),
            (binding_all, 1),
            (snap_all, 1),
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
        # Subflow bindings should be present when subflows exist
        self.assertIn("subflow_bindings", result)
        self.assertIn("mismatch_summary", result)
        self.assertEqual(len(result["subflow_bindings"]), 1)
        binding = result["subflow_bindings"][0]
        self.assertEqual(binding["subflow_snapshot_id"], "snap_sub1")
        self.assertEqual(binding["subflow_parent_flow_name"], "SubFlow Master")

        for entry in result["flat_summary"]:
            if entry["type"] == "action":
                self.assertIn("action_type", entry)
            elif entry["type"] == "logic":
                self.assertIn("logic_type", entry)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_structure_no_snapshot(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow_no_snap",
        )

        self.assertFalse(result["success"])
        self.assertIn("No snapshot", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_structure_prefers_published_snapshot(self, mock_qp):
        snapshot_data = [
            {"sys_id": "snap_draft", "name": "Flow v1", "status": "Draft"},
            {"sys_id": "snap_pub", "name": "Flow v2", "status": "Published"},
        ]
        flow_record = [{"sys_id": "flow1", "name": "Test Flow", "label_cache": ""}]
        mock_qp.side_effect = [
            (snapshot_data, 2),
            (flow_record, 1),
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
    def test_get_flow_structure_nesting(self, mock_qp):
        snapshot_data = [{"sys_id": "snap1", "status": "Published"}]
        flow_record = [{"sys_id": "flow1", "name": "Test Flow", "label_cache": ""}]
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
            (flow_record, 1),
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
    def test_get_flow_structure_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Connection failed")

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow1",
        )

        self.assertFalse(result["success"])
        # Snapshot query fails → no snapshot → error mentions the table
        self.assertIn("No snapshot", result["error"])

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

    # -- _try_processflow_api direct tests ---------------------------------

    def test_try_processflow_api_success(self):
        from servicenow_mcp.tools.flow_designer_tools import _try_processflow_api

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"id": "f1", "name": "Test Flow"}}
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "f1")

        self.assertIsNotNone(result)
        self.assertIn("result", result)
        # Verify correct endpoint
        call_args = self.auth_manager.make_request.call_args
        self.assertIn("/api/now/processflow/flow/f1", call_args[0][1])

    def test_try_processflow_api_returns_error_on_exception(self):
        from servicenow_mcp.tools.flow_designer_tools import _try_processflow_api

        self.auth_manager.make_request.side_effect = Exception("Server error")

        result = _try_processflow_api(self.config, self.auth_manager, "f1")

        self.assertIn("_error", result)
        self.assertIn("Server error", result["_error"])

    def test_try_processflow_api_returns_error_on_empty_response(self):
        from servicenow_mcp.tools.flow_designer_tools import _try_processflow_api

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {}}
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "f1")

        self.assertIn("_error", result)

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

    # -- list_flows type filter -----------------------------------------------

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_default_excludes_subflows(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_flows(self.config, self.auth_manager, ListFlowsParams())

        query = mock_qp.call_args[1]["query"]
        self.assertIn("type!=subflow", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_type_flow_excludes_subflows(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_flows(self.config, self.auth_manager, ListFlowsParams(type="flow"))

        query = mock_qp.call_args[1]["query"]
        self.assertIn("type!=subflow", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_type_subflow(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_flows(self.config, self.auth_manager, ListFlowsParams(type="subflow"))

        query = mock_qp.call_args[1]["query"]
        self.assertIn("type=subflow", query)
        self.assertIn("substatusISEMPTY", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_type_all(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_flows(self.config, self.auth_manager, ListFlowsParams(type="all"))

        query = mock_qp.call_args[1]["query"]
        self.assertNotIn("type!=subflow", query)
        self.assertNotIn("type=subflow", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    def test_list_flows_type_subflow_count_only(self, mock_cnt):
        mock_cnt.return_value = 311

        result = list_flows(
            self.config,
            self.auth_manager,
            ListFlowsParams(type="subflow", count_only=True),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 311)
        call_query = mock_cnt.call_args[0][3]
        self.assertIn("type=subflow", call_query)


class TestActionTools(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_actions_happy(self, mock_qp):
        actions = [
            {"sys_id": "a1", "name": "Custom Action", "active": "true", "status": "Published"},
        ]
        mock_qp.return_value = (actions, 1)

        result = list_actions(self.config, self.auth_manager, ListActionsParams())

        self.assertTrue(result["success"])
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["count"], 1)
        mock_qp.assert_called_once()
        self.assertEqual(mock_qp.call_args[1]["table"], "sys_hub_action_type_definition")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    def test_list_actions_count_only(self, mock_cnt):
        mock_cnt.return_value = 25

        result = list_actions(self.config, self.auth_manager, ListActionsParams(count_only=True))

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 25)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_actions_with_filters(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_actions(
            self.config,
            self.auth_manager,
            ListActionsParams(name="Custom", scope="global"),
        )

        query = mock_qp.call_args[1]["query"]
        self.assertIn("active=true", query)
        self.assertIn("nameLIKECustom", query)
        self.assertIn("sys_scope.scope=global^ORsys_scope.name=global", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_actions_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Network error")

        result = list_actions(self.config, self.auth_manager, ListActionsParams())

        self.assertFalse(result["success"])
        self.assertIn("Network error", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_actions_limit_capped(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_actions(self.config, self.auth_manager, ListActionsParams(limit=500))

        self.assertEqual(mock_qp.call_args[1]["limit"], 100)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_actions_empty_results(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = list_actions(self.config, self.auth_manager, ListActionsParams())

        self.assertTrue(result["success"])
        self.assertEqual(result["actions"], [])
        self.assertEqual(result["count"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_actions_with_query_and_offset(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_actions(
            self.config,
            self.auth_manager,
            ListActionsParams(query="sys_created_on>=2024-01-01", offset=20),
        )

        call_kwargs = mock_qp.call_args[1]
        self.assertIn("sys_created_on>=2024-01-01", call_kwargs["query"])
        self.assertEqual(call_kwargs["offset"], 20)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_action_detail_happy(self, mock_qp):
        action = {"sys_id": "a1", "name": "Custom Action", "description": "Does stuff"}
        mock_qp.return_value = ([action], 1)

        result = get_action_detail(
            self.config, self.auth_manager, GetActionDetailParams(action_id="a1")
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["action"]["name"], "Custom Action")
        self.assertEqual(mock_qp.call_args[1]["table"], "sys_hub_action_type_definition")
        self.assertEqual(mock_qp.call_args[1]["query"], "sys_id=a1")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_action_detail_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_action_detail(
            self.config, self.auth_manager, GetActionDetailParams(action_id="missing")
        )

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_action_detail_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("API error")

        result = get_action_detail(
            self.config, self.auth_manager, GetActionDetailParams(action_id="a1")
        )

        self.assertFalse(result["success"])
        self.assertIn("API error", result["error"])


class TestPlaybookTools(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_playbooks_happy(self, mock_qp):
        playbooks = [
            {"sys_id": "p1", "label": "Incident Playbook", "active": "true", "status": "Published"},
        ]
        mock_qp.return_value = (playbooks, 1)

        result = list_playbooks(self.config, self.auth_manager, ListPlaybooksParams())

        self.assertTrue(result["success"])
        self.assertEqual(len(result["playbooks"]), 1)
        self.assertEqual(mock_qp.call_args[1]["table"], "sys_pd_process_definition")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    def test_list_playbooks_count_only(self, mock_cnt):
        mock_cnt.return_value = 42

        result = list_playbooks(
            self.config, self.auth_manager, ListPlaybooksParams(count_only=True)
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 42)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_playbooks_with_filters(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_playbooks(
            self.config,
            self.auth_manager,
            ListPlaybooksParams(status="Published", name="Incident", scope="global"),
        )

        query = mock_qp.call_args[1]["query"]
        self.assertIn("active=true", query)
        self.assertIn("status=Published", query)
        self.assertIn("labelLIKEIncident", query)
        self.assertIn("sys_scope.scope=global^ORsys_scope.name=global", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_playbooks_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Timeout")

        result = list_playbooks(self.config, self.auth_manager, ListPlaybooksParams())

        self.assertFalse(result["success"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_playbooks_empty_results(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = list_playbooks(self.config, self.auth_manager, ListPlaybooksParams())

        self.assertTrue(result["success"])
        self.assertEqual(result["playbooks"], [])
        self.assertEqual(result["count"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_playbooks_limit_capped_and_offset(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_playbooks(self.config, self.auth_manager, ListPlaybooksParams(limit=999, offset=50))

        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["limit"], 100)
        self.assertEqual(call_kwargs["offset"], 50)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_playbooks_with_query(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_playbooks(
            self.config,
            self.auth_manager,
            ListPlaybooksParams(query="sys_created_on>=2024-01-01"),
        )

        self.assertIn("sys_created_on>=2024-01-01", mock_qp.call_args[1]["query"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_playbook_detail_happy(self, mock_qp):
        pb = {"sys_id": "p1", "label": "Incident Playbook", "description": "Handles incidents"}
        mock_qp.return_value = ([pb], 1)

        result = get_playbook_detail(
            self.config, self.auth_manager, GetPlaybookDetailParams(playbook_id="p1")
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["playbook"]["label"], "Incident Playbook")
        self.assertEqual(mock_qp.call_args[1]["table"], "sys_pd_process_definition")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_playbook_detail_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_playbook_detail(
            self.config, self.auth_manager, GetPlaybookDetailParams(playbook_id="missing")
        )

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_playbook_detail_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Connection error")

        result = get_playbook_detail(
            self.config, self.auth_manager, GetPlaybookDetailParams(playbook_id="p1")
        )

        self.assertFalse(result["success"])


class TestDecisionTableTools(unittest.TestCase):
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

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_decision_tables_happy(self, mock_qp):
        tables = [
            {"sys_id": "d1", "name": "Priority Matrix", "active": "true"},
        ]
        mock_qp.return_value = (tables, 1)

        result = list_decision_tables(self.config, self.auth_manager, ListDecisionTablesParams())

        self.assertTrue(result["success"])
        self.assertEqual(len(result["decision_tables"]), 1)
        self.assertEqual(mock_qp.call_args[1]["table"], "sys_decision")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    def test_list_decision_tables_count_only(self, mock_cnt):
        mock_cnt.return_value = 15

        result = list_decision_tables(
            self.config, self.auth_manager, ListDecisionTablesParams(count_only=True)
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 15)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_decision_tables_with_filters(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_decision_tables(
            self.config,
            self.auth_manager,
            ListDecisionTablesParams(name="Priority", scope="global"),
        )

        query = mock_qp.call_args[1]["query"]
        self.assertIn("active=true", query)
        self.assertIn("nameLIKEPriority", query)
        self.assertIn("sys_scope.scope=global^ORsys_scope.name=global", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_decision_tables_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Timeout")

        result = list_decision_tables(self.config, self.auth_manager, ListDecisionTablesParams())

        self.assertFalse(result["success"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_decision_tables_empty_results(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = list_decision_tables(self.config, self.auth_manager, ListDecisionTablesParams())

        self.assertTrue(result["success"])
        self.assertEqual(result["decision_tables"], [])
        self.assertEqual(result["count"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_decision_tables_limit_capped_and_offset(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_decision_tables(
            self.config, self.auth_manager, ListDecisionTablesParams(limit=999, offset=30)
        )

        call_kwargs = mock_qp.call_args[1]
        self.assertEqual(call_kwargs["limit"], 100)
        self.assertEqual(call_kwargs["offset"], 30)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_decision_tables_with_query(self, mock_qp):
        mock_qp.return_value = ([], 0)

        list_decision_tables(
            self.config,
            self.auth_manager,
            ListDecisionTablesParams(query="sys_updated_on>=2024-06-01"),
        )

        self.assertIn("sys_updated_on>=2024-06-01", mock_qp.call_args[1]["query"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_decision_table_detail_happy(self, mock_qp):
        dt = {"sys_id": "d1", "name": "Priority Matrix", "label": "Priority"}
        mock_qp.return_value = ([dt], 1)

        result = get_decision_table_detail(
            self.config, self.auth_manager, GetDecisionTableDetailParams(decision_table_id="d1")
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["decision_table"]["name"], "Priority Matrix")
        self.assertEqual(mock_qp.call_args[1]["table"], "sys_decision")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_decision_table_detail_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_decision_table_detail(
            self.config,
            self.auth_manager,
            GetDecisionTableDetailParams(decision_table_id="missing"),
        )

        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_decision_table_detail_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("API error")

        result = get_decision_table_detail(
            self.config, self.auth_manager, GetDecisionTableDetailParams(decision_table_id="d1")
        )

        self.assertFalse(result["success"])


class TestCompareFlows(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.browser_config = _make_browser_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_compare_flows_basic_auth_table_api(self, mock_qp, mock_struct, mock_trig):
        """Basic auth — compare via Table API with structure enrichment."""
        flow_a = {
            "sys_id": "a1",
            "name": "Old Review Flow",
            "status": "Published",
            "active": "true",
            "label_cache": "ref1:Old Approval Step,ref2:common",
        }
        flow_b = {
            "sys_id": "b1",
            "name": "New Review Flow",
            "status": "Published",
            "active": "true",
            "label_cache": "ref1:New Approval Step,ref2:common",
        }
        mock_qp.side_effect = [([flow_a], 1), ([flow_b], 1)]
        mock_struct.side_effect = [
            {
                "success": True,
                "flat_summary": [
                    {"type": "action", "name": "Log", "action_type": "log", "order": "1"},
                    {"type": "subflow", "name": "Old Approval Step", "order": "2"},
                ],
                "total_actions": 1,
                "total_logic": 0,
                "total_subflows": 1,
                "subflow_bindings": [
                    {
                        "order": "2",
                        "instance_name": "Old Approval Step",
                        "subflow_parent_flow_name": "Old Approval Step",
                        "subflow_parent_flow_id": "sf1",
                    },
                ],
            },
            {
                "success": True,
                "flat_summary": [
                    {"type": "action", "name": "Log", "action_type": "log", "order": "1"},
                    {"type": "subflow", "name": "New Approval Step", "order": "2"},
                ],
                "total_actions": 1,
                "total_logic": 0,
                "total_subflows": 1,
                "subflow_bindings": [
                    {
                        "order": "2",
                        "instance_name": "New Approval Step",
                        "subflow_parent_flow_name": "New Approval Step",
                        "subflow_parent_flow_id": "sf2",
                    },
                ],
            },
        ]
        mock_trig.side_effect = [[], []]

        result = compare_flows(
            self.config, self.auth_manager, CompareFlowsParams(flow_id_a="a1", flow_id_b="b1")
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["flow_a"]["name"], "Old Review Flow")
        self.assertEqual(result["flow_b"]["name"], "New Review Flow")
        self.assertGreater(result["total_different"], 0)
        # label_cache diff should show only_in_a / only_in_b
        lc_diff = next(d for d in result["differences"] if d["field"] == "label_cache")
        self.assertTrue(len(lc_diff["only_in_a"]) > 0 or len(lc_diff["only_in_b"]) > 0)
        # subflow_bindings should differ
        sb_diff = next(d for d in result["differences"] if d["field"] == "subflow_bindings")
        self.assertIn("Old Approval Step", sb_diff["only_in_a"])
        self.assertIn("New Approval Step", sb_diff["only_in_b"])

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_compare_flows_browser_auth_processflow(self, mock_pf):
        """Browser auth — compare via processflow API."""
        pf_a = {
            "result": {
                "id": "a1",
                "name": "Old Flow",
                "status": "Published",
                "active": True,
                "scope": "global",
                "actionInstances": [{"name": "Log", "actionType": "log", "position": "1"}],
                "flowLogicInstances": [],
                "subFlowInstances": [],
                "triggerInstances": [{"name": "Record"}],
                "flowVariables": [],
                "inputs": [{"name": "input1"}],
                "outputs": [],
                "label_cache": "common_ref",
            }
        }
        pf_b = {
            "result": {
                "id": "b1",
                "name": "New Flow",
                "status": "Published",
                "active": True,
                "scope": "global",
                "actionInstances": [
                    {"name": "Log", "actionType": "log", "position": "1"},
                    {"name": "Extra", "actionType": "custom", "position": "2"},
                ],
                "flowLogicInstances": [],
                "subFlowInstances": [],
                "triggerInstances": [{"name": "Record"}],
                "flowVariables": [],
                "inputs": [{"name": "input1"}],
                "outputs": [],
                "label_cache": "common_ref",
            }
        }
        mock_pf.side_effect = [pf_a, pf_b]

        result = compare_flows(
            self.browser_config,
            self.auth_manager,
            CompareFlowsParams(flow_id_a="a1", flow_id_b="b1"),
        )

        self.assertTrue(result["success"])
        # actions differ (1 vs 2)
        action_diff = next(d for d in result["differences"] if d["field"] == "actions")
        self.assertNotEqual(action_diff["flow_a"], action_diff["flow_b"])
        # label_cache identical → should be in identical_fields
        self.assertIn("label_cache", result["identical_fields"])

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_compare_flows_by_name(self, mock_qp, mock_struct, mock_trig):
        """Compare by name instead of sys_id — name resolved automatically."""
        flow_a = {"sys_id": "a1", "name": "Flow Alpha", "status": "Published", "active": "true"}
        flow_b = {"sys_id": "b1", "name": "Flow Beta", "status": "Published", "active": "true"}
        mock_struct.side_effect = [{"success": False}, {"success": False}]
        mock_trig.side_effect = [[], []]
        # name resolve A (exact), name resolve B (exact), flow record A, flow record B
        mock_qp.side_effect = [
            ([{"sys_id": "a1", "name": "Flow Alpha"}], 1),
            ([{"sys_id": "b1", "name": "Flow Beta"}], 1),
            ([flow_a], 1),
            ([flow_b], 1),
        ]

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(name_a="Flow Alpha", name_b="Flow Beta"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["flow_a"]["name"], "Flow Alpha")
        self.assertEqual(result["flow_b"]["name"], "Flow Beta")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_compare_flows_name_not_found(self, mock_qp):
        """Name resolve fails when no flow matches."""
        mock_qp.return_value = ([], 0)

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(name_a="Nonexistent Flow", name_b="Other"),
        )

        self.assertFalse(result["success"])
        self.assertIn("no flow found", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_compare_flows_no_id_no_name(self, mock_qp):
        """Error when neither flow_id nor name is provided."""
        result = compare_flows(self.config, self.auth_manager, CompareFlowsParams())

        self.assertFalse(result["success"])
        self.assertIn("provide flow_id or name", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_compare_flows_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = compare_flows(
            self.config, self.auth_manager, CompareFlowsParams(flow_id_a="missing", flow_id_b="b1")
        )

        self.assertFalse(result["success"])

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_compare_flows_identical(self, mock_qp, mock_struct, mock_trig):
        """Two identical flows should have 0 differences."""
        flow = {
            "sys_id": "x1",
            "name": "Same Flow",
            "status": "Published",
            "active": "true",
            "label_cache": "same_labels",
        }
        same_structure = {
            "success": True,
            "flat_summary": [{"type": "action", "name": "Log", "action_type": "log", "order": "1"}],
            "total_actions": 1,
            "total_logic": 0,
            "total_subflows": 0,
        }
        mock_qp.side_effect = [([flow], 1), ([{**flow}], 1)]
        mock_struct.side_effect = [same_structure, {**same_structure}]
        mock_trig.side_effect = [[], []]

        result = compare_flows(
            self.config, self.auth_manager, CompareFlowsParams(flow_id_a="x1", flow_id_b="x1")
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["total_different"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_compare_flows_without_label_cache(self, mock_qp, mock_struct, mock_trig):
        flow_a = {"sys_id": "a1", "name": "Flow A", "status": "Published", "active": "true"}
        flow_b = {"sys_id": "b1", "name": "Flow B", "status": "Published", "active": "true"}
        mock_qp.side_effect = [([flow_a], 1), ([flow_b], 1)]
        mock_struct.side_effect = [{"success": False}, {"success": False}]
        mock_trig.side_effect = [[], []]

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(flow_id_a="a1", flow_id_b="b1", include_label_cache=False),
        )

        self.assertTrue(result["success"])
        # label_cache should not appear in diff
        fields = [d["field"] for d in result["differences"]]
        self.assertNotIn("label_cache", fields)
        self.assertNotIn("label_cache", result["identical_fields"])


class TestSubflowBindings(unittest.TestCase):
    """Tests for subflow binding resolution and mismatch detection."""

    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_subflow_bindings_resolve_snapshot_to_master(self, mock_qp):
        """subflow_bindings should trace instance → snapshot → master_flow."""
        from servicenow_mcp.tools.flow_designer_tools import _fetch_subflow_bindings

        # display_value=all: reference fields become {value, display_value}
        instances_all = [
            {
                "sys_id": "inst1",
                "name": {"value": "sf1", "display_value": "New Approval Step"},
                "order": "100",
                "position": "",
                "ui_id": "ui_001",
                "parent_ui_id": "",
                "nesting_parent": "",
                "subflow": {"value": "snap_new", "display_value": "New Approval Step v2"},
            },
        ]
        snap_all = [
            {
                "sys_id": "snap_new",
                "name": "New Approval Step v2",
                "master_flow": {"value": "mf_new", "display_value": "New Approval Step"},
            }
        ]

        mock_qp.side_effect = [
            (instances_all, 1),
            (snap_all, 1),
        ]

        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", "")

        bindings = result["subflow_bindings"]
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0]["subflow_snapshot_id"], "snap_new")
        self.assertEqual(bindings[0]["subflow_parent_flow_id"], "mf_new")
        self.assertEqual(bindings[0]["subflow_parent_flow_name"], "New Approval Step")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_mismatch_detected_label_vs_binding(self, mock_qp):
        """Mismatch: label_cache says Old but actual binding points to New."""
        from servicenow_mcp.tools.flow_designer_tools import _fetch_subflow_bindings

        instances_all = [
            {
                "sys_id": "inst1",
                "name": {"value": "sf1", "display_value": "Approval Call"},
                "order": "100",
                "position": "",
                "ui_id": "ui_001",
                "parent_ui_id": "",
                "nesting_parent": "",
                "subflow": {"value": "snap_new", "display_value": "New Approval Step"},
            },
        ]
        snap_all = [
            {
                "sys_id": "snap_new",
                "name": "New Approval Step",
                "master_flow": {"value": "mf_new", "display_value": "New Approval Step"},
            }
        ]

        mock_qp.side_effect = [
            (instances_all, 1),
            (snap_all, 1),
        ]

        # label_cache says "Old Approval Step" but actual binding is "New Approval Step"
        label_cache = "Approval Call: Old Approval Step\nother label"

        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", label_cache)

        summary = result["mismatch_summary"]
        self.assertGreater(summary["mismatch_count"], 0)
        mismatch = summary["mismatches"][0]
        self.assertIn("Old", mismatch["label"])
        self.assertIn("New", mismatch["actual_subflow"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_no_mismatch_when_consistent(self, mock_qp):
        """No mismatch when label_cache matches actual bindings."""
        from servicenow_mcp.tools.flow_designer_tools import _fetch_subflow_bindings

        instances_all = [
            {
                "sys_id": "inst1",
                "name": {"value": "sf1", "display_value": "New Approval Call"},
                "order": "100",
                "position": "",
                "ui_id": "ui_001",
                "parent_ui_id": "",
                "nesting_parent": "",
                "subflow": {"value": "snap_new", "display_value": "New Approval Step"},
            },
        ]
        snap_all = [
            {
                "sys_id": "snap_new",
                "name": "New Approval Step",
                "master_flow": {"value": "mf_new", "display_value": "New Approval Step"},
            }
        ]

        mock_qp.side_effect = [
            (instances_all, 1),
            (snap_all, 1),
        ]

        # label_cache matches actual binding
        label_cache = "New Approval Call: New Approval Step"

        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", label_cache)

        self.assertEqual(result["mismatch_summary"]["mismatch_count"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_empty_subflows_returns_empty_bindings(self, mock_qp):
        """No subflow instances → empty bindings, no mismatches."""
        from servicenow_mcp.tools.flow_designer_tools import _fetch_subflow_bindings

        mock_qp.return_value = ([], 0)

        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", "some labels")

        self.assertEqual(result["subflow_bindings"], [])
        self.assertEqual(result["mismatch_summary"]["mismatch_count"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_structure_fallback_includes_bindings_when_subflows_exist(self, mock_qp):
        """_fetch_flow_structure table_api_fallback includes subflow_bindings."""
        snapshot = [{"sys_id": "snap1", "name": "Flow v1", "status": "Published"}]
        flow_rec = [
            {"sys_id": "flow1", "name": "Test Flow", "label_cache": "Sub Call: Old Actual Sub"}
        ]
        actions = []
        logic = []
        subflows_display = [
            {"sys_id": "s1", "name": "Sub Call", "order": "100", "nesting_parent": ""},
        ]
        # Binding queries (display_value=all format)
        bind_all = [
            {
                "sys_id": "s1",
                "name": {"value": "Sub Call", "display_value": "Sub Call"},
                "order": "100",
                "position": "",
                "ui_id": "u1",
                "parent_ui_id": "",
                "nesting_parent": "",
                "subflow": {"value": "snp1", "display_value": "New Actual Sub"},
            }
        ]
        snp_all = [
            {
                "sys_id": "snp1",
                "name": "New Actual Sub",
                "master_flow": {"value": "mf1", "display_value": "New Actual Sub"},
            }
        ]

        mock_qp.side_effect = [
            (snapshot, 1),
            (flow_rec, 1),
            (actions, 0),
            (logic, 0),
            (subflows_display, 1),
            (bind_all, 1),
            (snp_all, 1),
        ]

        result = _fetch_flow_structure(self.config, self.auth_manager, "flow1")

        self.assertTrue(result["success"])
        self.assertIn("subflow_bindings", result)
        self.assertIn("mismatch_summary", result)
        # Should detect mismatch: label has Old but binding is New
        self.assertIn("MISMATCH", result.get("note", "").upper())


class TestSnQueryHints(unittest.TestCase):
    """Tests for sn_query query_echo and hint diagnostics."""

    def test_hint_ampersand_in_IN_query(self):
        from servicenow_mcp.tools.sn_api import _generate_query_hint

        hint = _generate_query_hint("nameINFoo&Bar,Baz", "400 Bad Request")
        self.assertIsNotNone(hint)
        self.assertIn("&", hint)
        self.assertIn("sys_idIN", hint)

    def test_hint_timeout(self):
        from servicenow_mcp.tools.sn_api import _generate_query_hint

        hint = _generate_query_hint("nameLIKEtest", "Request timed out")
        self.assertIsNotNone(hint)
        self.assertIn("timed out", hint.lower())

    def test_hint_unauthorized(self):
        from servicenow_mcp.tools.sn_api import _generate_query_hint

        hint = _generate_query_hint("active=true", "401 Unauthorized")
        self.assertIsNotNone(hint)
        self.assertIn("expired", hint.lower())

    def test_no_hint_for_normal_query(self):
        from servicenow_mcp.tools.sn_api import _generate_query_hint

        hint = _generate_query_hint("active=true", "Some unknown error")
        self.assertIsNone(hint)

    @patch("servicenow_mcp.tools.sn_api.sn_query_page")
    def test_sn_query_error_includes_query_echo(self, mock_qp):
        from servicenow_mcp.tools.sn_api import GenericQueryParams, sn_query

        mock_qp.side_effect = RuntimeError("Connection failed")
        config = _make_basic_config()
        auth = MagicMock(spec=AuthManager)

        result = sn_query(
            config,
            auth,
            GenericQueryParams(table="incident", query="nameINFoo&Bar"),
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["query_echo"], "nameINFoo&Bar")
        self.assertIn("hint", result)
        self.assertIn("&", result["hint"])


class TestGetFlowFullDetail(unittest.TestCase):
    """Tests for get_flow_full_detail (processflow API)."""

    def setUp(self):
        self.basic_config = _make_basic_config()
        self.browser_config = _make_browser_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    def _pf_response(self, extra_actions=None, extra_logic=None, extra_subflows=None):
        actions = [
            {
                "order": "2",
                "id": "act001",
                "uiUniqueIdentifier": "uuid-step2",
                "parent": "uuid-parent-if",
                "name": "Ask For Approval",
                "actionTypeSysId": "at-approval",
                "actionType": {"name": "Ask For Approval", "internal_name": "ask_for_approval"},
                "inputs": [{"name": "approver", "value": "subflow.dept_head"}],
                "outputs": [],
            },
            {
                "order": "8",
                "id": "act002",
                "uiUniqueIdentifier": "uuid-step8",
                "parent": "uuid-parent-if",
                "name": "Ask For Approval",
                "actionTypeSysId": "at-approval",
                "actionType": {"name": "Ask For Approval", "internal_name": "ask_for_approval"},
                "inputs": [{"name": "approver", "value": "subflow.dept_head"}],
                "outputs": [],
            },
        ] + (extra_actions or [])
        logic = [
            {
                "order": "5",
                "id": "logic001",
                "uiUniqueIdentifier": "uuid-if",
                "parent": "",
                "flowLogicDefinition": {"name": "If", "type": "IF"},
                "inputs": [
                    {"name": "condition_name", "value": "rank == 12"},
                    {"name": "condition", "value": "{{subflow.rank}}=12"},
                ],
            }
        ] + (extra_logic or [])
        subflows = extra_subflows or []
        return {
            "result": {
                "id": "flow123",
                "name": "Approval Subflow",
                "status": "Published",
                "active": True,
                "scope": "global",
                "scopeName": "global",
                "masterSnapshotId": "snap-master",
                "latestSnapshot": "snap-latest",
                "triggerInstances": [],
                "inputs": [{"name": "sales_manager", "type": "GlideRecord"}],
                "outputs": [],
                "flowVariables": [{"name": "dept", "type": "string"}],
                "label_cache": [{"name": "subflow.dept_head", "label": "Dept Head"}],
                "actionInstances": actions,
                "flowLogicInstances": logic,
                "subFlowInstances": subflows,
            }
        }

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_happy_path_returns_all_sections(self, mock_pf):
        mock_pf.return_value = self._pf_response()
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123"),
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "processflow_api")
        self.assertEqual(len(result["actions"]), 2)
        self.assertEqual(len(result["logic"]), 1)
        self.assertEqual(len(result["variables"]), 1)
        self.assertEqual(result["counts"]["actions"], 2)
        self.assertEqual(result["counts"]["logic"], 1)

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_action_inputs_present(self, mock_pf):
        mock_pf.return_value = self._pf_response()
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123"),
        )
        self.assertTrue(result["success"])
        approvers = [a["inputs"] for a in result["actions"]]
        self.assertEqual(approvers[0][0]["value"], "subflow.dept_head")
        self.assertEqual(approvers[1][0]["value"], "subflow.dept_head")

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_action_type_filter(self, mock_pf):
        extra = [
            {
                "order": "3",
                "id": "act003",
                "uiUniqueIdentifier": "uuid-setvals",
                "parent": "",
                "name": "Set Values",
                "actionType": {"name": "Set Values", "internal_name": "set_values"},
                "inputs": [],
                "outputs": [],
            }
        ]
        mock_pf.return_value = self._pf_response(extra_actions=extra)
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123", action_type_filter="approval"),
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(result["actions"]), 2)
        for a in result["actions"]:
            self.assertIn("Approval", a["action_type_name"])

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_logic_conditions_present(self, mock_pf):
        mock_pf.return_value = self._pf_response()
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123"),
        )
        self.assertEqual(result["logic"][0]["logic_type"], "IF")
        self.assertEqual(result["logic"][0]["condition_label"], "rank == 12")
        self.assertEqual(result["logic"][0]["condition"], "{{subflow.rank}}=12")

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_subflow_inputs_included(self, mock_pf):
        subflows = [
            {
                "order": "10",
                "id": "sf001",
                "uiUniqueIdentifier": "uuid-sub1",
                "parent": "",
                "subflowSysId": "sub123",
                "subFlow": {"id": "sub123", "name": "Child Sub", "internalName": "child_sub"},
                "inputs": [{"name": "param1", "value": "trigger.record"}],
                "outputs": [],
            }
        ]
        mock_pf.return_value = self._pf_response(extra_subflows=subflows)
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123", include_subflow_inputs=True),
        )
        self.assertEqual(len(result["subflows"]), 1)
        self.assertEqual(result["subflows"][0]["inputs"][0]["value"], "trigger.record")
        self.assertEqual(result["subflows"][0]["subflow_name"], "Child Sub")
        self.assertEqual(result["subflows"][0]["subflow_sys_id"], "sub123")

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_subflow_inputs_excluded(self, mock_pf):
        subflows = [
            {
                "order": "10",
                "id": "sf001",
                "uiUniqueIdentifier": "uuid-sub1",
                "parent": "",
                "subflowSysId": "sub123",
                "subFlow": {"id": "sub123", "name": "Child Sub"},
                "inputs": [{"name": "param1", "value": "trigger.record"}],
                "outputs": [],
            }
        ]
        mock_pf.return_value = self._pf_response(extra_subflows=subflows)
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123", include_subflow_inputs=False),
        )
        self.assertEqual(len(result["subflows"]), 0)

    def test_requires_browser_auth(self):
        result = get_flow_full_detail(
            self.basic_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123"),
        )
        self.assertFalse(result["success"])
        self.assertIn("browser auth", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_api_error_propagated(self, mock_pf):
        mock_pf.return_value = {"_error": "HTTP 403 Forbidden"}
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123"),
        )
        self.assertFalse(result["success"])
        self.assertIn("403", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_api_returns_none(self, mock_pf):
        mock_pf.return_value = None
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123"),
        )
        self.assertFalse(result["success"])
        self.assertIn("None", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_actions_sorted_by_order(self, mock_pf):
        mock_pf.return_value = {
            "result": {
                "id": "f1",
                "name": "F",
                "actionInstances": [
                    {
                        "order": "8",
                        "id": "a8",
                        "uiUniqueIdentifier": "u8",
                        "parent": "",
                        "name": "B",
                        "actionType": {"name": "T"},
                        "inputs": [],
                        "outputs": [],
                    },
                    {
                        "order": "2",
                        "id": "a2",
                        "uiUniqueIdentifier": "u2",
                        "parent": "",
                        "name": "A",
                        "actionType": {"name": "T"},
                        "inputs": [],
                        "outputs": [],
                    },
                ],
                "flowLogicInstances": [],
                "subFlowInstances": [],
                "triggerInstances": [],
                "inputs": [],
                "outputs": [],
                "flowVariables": [],
            }
        }
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="f1"),
        )
        self.assertEqual(result["actions"][0]["order"], "2")
        self.assertEqual(result["actions"][1]["order"], "8")

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_label_cache_and_metadata_preserved(self, mock_pf):
        mock_pf.return_value = self._pf_response()
        result = get_flow_full_detail(
            self.browser_config,
            self.auth_manager,
            GetFlowFullDetailParams(flow_id="flow123"),
        )
        self.assertEqual(len(result["label_cache"]), 1)
        self.assertEqual(result["flow"]["master_snapshot_id"], "snap-master")
        self.assertEqual(result["flow"]["latest_snapshot"], "snap-latest")
        # Actions expose UI identifiers for nesting analysis
        self.assertEqual(result["actions"][0]["ui_id"], "uuid-step2")
        self.assertEqual(result["actions"][0]["parent_ui_id"], "uuid-parent-if")
        self.assertEqual(result["actions"][0]["action_type_name"], "Ask For Approval")


if __name__ == "__main__":
    unittest.main()
