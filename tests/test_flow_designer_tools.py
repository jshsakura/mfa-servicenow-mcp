"""Focused tests for the consolidated Flow Designer read surface."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import (
    CompareFlowsParams,
    GetFlowDetailsParams,
    GetFlowExecutionsParams,
    ListFlowsParams,
    compare_flows,
    get_flow_details,
    get_flow_executions,
    list_flows,
)
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    ServerConfig,
)


def _make_basic_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        ),
    )


def _make_browser_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


class TestFlowDesignerTools(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.browser_config = _make_browser_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_flows_happy(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "f1", "name": "Flow One"}], 1)

        result = list_flows(self.config, self.auth_manager, ListFlowsParams())

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["flows"][0]["sys_id"], "f1")
        self.assertEqual(mock_qp.call_args[1]["table"], "sys_hub_flow")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    def test_list_flows_count_only(self, mock_count):
        mock_count.return_value = 42

        result = list_flows(self.config, self.auth_manager, ListFlowsParams(count_only=True))

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 42)
        self.assertNotIn("flows", result)

    @patch("servicenow_mcp.tools.flow_designer_tools._build_subflow_tree")
    @patch("servicenow_mcp.tools.flow_designer_tools._trace_pill_usage")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_execution_summary")
    @patch("servicenow_mcp.tools.flow_designer_tools._build_processflow_detail")
    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_get_flow_details_uses_processflow_for_rich_detail(
        self,
        mock_processflow,
        mock_build_detail,
        mock_exec_summary,
        mock_trace_pill,
        mock_subflow_tree,
    ):
        mock_processflow.return_value = {"result": {"id": "flow1", "name": "Flow One"}}
        mock_build_detail.return_value = {"triggers": [{"name": "Record Trigger"}], "actions": []}
        mock_exec_summary.return_value = {"counts": {"total": 3}, "recent": []}
        mock_trace_pill.return_value = {
            "pill": "trigger.current",
            "match_count": 1,
            "components": [],
        }
        mock_subflow_tree.return_value = {"flow_id": "flow1", "children": []}

        result = get_flow_details(
            self.browser_config,
            self.auth_manager,
            GetFlowDetailsParams(
                flow_id="flow1",
                include_structure=True,
                include_triggers=True,
                include_executions_summary=True,
                trace_pill="trigger.current",
                include_subflow_tree=True,
            ),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "processflow_api")
        self.assertEqual(result["structure"]["actions"], [])
        self.assertEqual(result["triggers"][0]["name"], "Record Trigger")
        self.assertEqual(result["executions_summary"]["counts"]["total"], 3)
        self.assertEqual(result["pill_trace"]["match_count"], 1)
        self.assertEqual(result["subflow_tree"]["flow_id"], "flow1")

    @patch("servicenow_mcp.tools.flow_designer_tools._build_subflow_tree")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_execution_summary")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_details_table_fallback_supports_new_options(
        self,
        mock_qp,
        mock_triggers,
        mock_structure,
        mock_exec_summary,
        mock_subflow_tree,
    ):
        mock_qp.return_value = ([{"sys_id": "flow1", "name": "Flow One"}], 1)
        mock_triggers.return_value = [{"sys_id": "t1"}]
        mock_structure.return_value = {"success": True, "flat_summary": []}
        mock_exec_summary.return_value = {"counts": {"total": 2}, "recent": []}
        mock_subflow_tree.return_value = {"flow_id": "flow1", "children": []}

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(
                flow_id="flow1",
                include_structure=True,
                include_triggers=True,
                include_executions_summary=True,
                trace_pill="trigger.current",
                include_subflow_tree=True,
            ),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "table_api")
        self.assertEqual(result["flow"]["sys_id"], "flow1")
        self.assertEqual(result["triggers"][0]["sys_id"], "t1")
        self.assertEqual(result["executions_summary"]["counts"]["total"], 2)
        self.assertEqual(result["subflow_tree"]["flow_id"], "flow1")
        self.assertEqual(result["pill_trace"]["pill"], "trigger.current")
        self.assertIn("browser auth", result["pill_trace"]["note"].lower())

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_details_not_found_returns_empty_flow(self, mock_qp):
        mock_qp.return_value = ([], 0)

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(flow_id="missing"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["flow"], {})

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_details_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("API error")

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(flow_id="flow1"),
        )

        self.assertFalse(result["success"])
        self.assertIn("API error", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_executions_list_mode(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "ctx1", "state": "Complete"}], 1)

        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(flow_id="flow1", errors_only=True),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["executions"][0]["sys_id"], "ctx1")
        self.assertEqual(mock_qp.call_args[1]["orderby"], "-sys_created_on")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_get_flow_executions_context_mode(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "ctx1"}], 1)

        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(context_id="ctx1"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["execution"]["sys_id"], "ctx1")

    @patch("servicenow_mcp.tools.flow_designer_tools._get_flow_for_compare")
    def test_compare_flows_happy(self, mock_get_flow):
        mock_get_flow.side_effect = [
            {
                "name": "Flow A",
                "status": "Published",
                "active": "true",
                "scope": "global",
                "inputs": [],
                "outputs": [],
                "actionInstances": [],
                "flowLogicInstances": [],
                "subFlowInstances": [],
                "triggerInstances": [],
                "flowVariables": [],
            },
            {
                "name": "Flow B",
                "status": "Draft",
                "active": "true",
                "scope": "global",
                "inputs": [],
                "outputs": [],
                "actionInstances": [],
                "flowLogicInstances": [],
                "subFlowInstances": [],
                "triggerInstances": [],
                "flowVariables": [],
            },
        ]

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(flow_id_a="a", flow_id_b="b"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["flow_a"]["sys_id"], "a")
        self.assertEqual(result["flow_b"]["sys_id"], "b")
        self.assertGreaterEqual(result["total_different"], 1)

    @patch("servicenow_mcp.tools.flow_designer_tools._get_flow_for_compare")
    @patch("servicenow_mcp.tools.flow_designer_tools._resolve_flow_id")
    def test_compare_flows_resolves_names(self, mock_resolve_flow_id, mock_get_flow):
        mock_resolve_flow_id.side_effect = [("a1", None), ("b1", None)]
        mock_get_flow.side_effect = [
            {
                "name": "Flow A",
                "status": "Published",
                "active": "true",
                "scope": "global",
                "inputs": [],
                "outputs": [],
                "actionInstances": [],
                "flowLogicInstances": [],
                "subFlowInstances": [],
                "triggerInstances": [],
                "flowVariables": [],
            },
            {
                "name": "Flow B",
                "status": "Published",
                "active": "true",
                "scope": "global",
                "inputs": [],
                "outputs": [],
                "actionInstances": [],
                "flowLogicInstances": [],
                "subFlowInstances": [],
                "triggerInstances": [],
                "flowVariables": [],
            },
        ]

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(name_a="Flow A", name_b="Flow B"),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["flow_a"]["sys_id"], "a1")
        self.assertEqual(result["flow_b"]["sys_id"], "b1")
        mock_resolve_flow_id.assert_any_call(self.config, self.auth_manager, None, "Flow A", "A")
        mock_resolve_flow_id.assert_any_call(self.config, self.auth_manager, None, "Flow B", "B")
