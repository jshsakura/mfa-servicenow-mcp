"""Tests for flow_designer_tools.py — full Workflow Studio coverage."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import (
    GetActionDetailParams,
    GetDecisionTableDetailParams,
    GetFlowDetailsParams,
    GetFlowExecutionsParams,
    GetPlaybookDetailParams,
    ListActionsParams,
    ListDecisionTablesParams,
    ListFlowsParams,
    ListPlaybooksParams,
    _fetch_flow_structure,
    _fetch_flow_triggers,
    get_action_detail,
    get_decision_table_detail,
    get_flow_details,
    get_flow_executions,
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
    def test_get_flow_structure_no_snapshot(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = _fetch_flow_structure(
            self.config,
            self.auth_manager,
            "flow_no_snap",
        )

        self.assertFalse(result["success"])
        self.assertIn("No snapshot found", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_structure_prefers_published_snapshot(self, mock_qp):
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
    def test_get_flow_structure_nesting(self, mock_qp):
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
    def test_get_flow_structure_error(self, mock_qp):
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

    def test_try_processflow_api_returns_none_on_error(self):
        from servicenow_mcp.tools.flow_designer_tools import _try_processflow_api

        self.auth_manager.make_request.side_effect = Exception("Server error")

        result = _try_processflow_api(self.config, self.auth_manager, "f1")

        self.assertIsNone(result)

    def test_try_processflow_api_returns_none_on_empty_response(self):
        from servicenow_mcp.tools.flow_designer_tools import _try_processflow_api

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {}}
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "f1")

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
            ListActionsParams(active=True, name="Custom", scope="global"),
        )

        query = mock_qp.call_args[1]["query"]
        self.assertIn("active=true", query)
        self.assertIn("nameLIKECustom", query)
        self.assertIn("sys_scopeLIKEglobal", query)

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
            ListPlaybooksParams(active=True, status="Published", name="Incident", scope="global"),
        )

        query = mock_qp.call_args[1]["query"]
        self.assertIn("active=true", query)
        self.assertIn("status=Published", query)
        self.assertIn("labelLIKEIncident", query)
        self.assertIn("sys_scopeLIKEglobal", query)

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
            ListDecisionTablesParams(active=True, name="Priority", scope="global"),
        )

        query = mock_qp.call_args[1]["query"]
        self.assertIn("active=true", query)
        self.assertIn("nameLIKEPriority", query)
        self.assertIn("sys_scopeLIKEglobal", query)

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


if __name__ == "__main__":
    unittest.main()
