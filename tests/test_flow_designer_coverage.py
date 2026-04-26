"""Comprehensive tests for flow_designer_tools.py — targeting 80%+ coverage.

Covers: helpers, processflow paths, table API fallback paths, subflow binding
resolution, flow structure extraction, flow comparison, pill tracing, execution
summary, and error branches.
"""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import (
    CompareFlowsParams,
    GetFlowDetailsParams,
    GetFlowExecutionsParams,
    ListFlowsParams,
    _action_type_name,
    _build_component_tree,
    _build_processflow_detail,
    _build_subflow_tree,
    _diff_flows,
    _extract_comparable,
    _extract_pill_matches,
    _extract_processflow_structure,
    _fetch_execution_summary,
    _fetch_flow_structure,
    _fetch_flow_triggers,
    _fetch_subflow_bindings,
    _get_flow_for_compare,
    _get_snapshot_id,
    _is_browser_auth,
    _parse_label_cache,
    _resolve_flow_id,
    _safe_int,
    _trace_pill_usage,
    _try_processflow_api,
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


# ---------------------------------------------------------------------------
# Pure helper tests (no mocking needed)
# ---------------------------------------------------------------------------


class TestSafeInt(unittest.TestCase):
    def test_normal_int(self):
        self.assertEqual(_safe_int(42), 42)

    def test_string_int(self):
        self.assertEqual(_safe_int("7"), 7)

    def test_none(self):
        self.assertEqual(_safe_int(None), 0)

    def test_empty_string(self):
        self.assertEqual(_safe_int(""), 0)

    def test_non_numeric_string(self):
        self.assertEqual(_safe_int("abc"), 0)

    def test_float(self):
        self.assertEqual(_safe_int(3.7), 3)


class TestActionTypeName(unittest.TestCase):
    def test_dict_action_type(self):
        action = {"actionType": {"name": "Log", "internal_name": "log_action"}}
        self.assertEqual(_action_type_name(action), "Log")

    def test_dict_action_type_fallback_internal(self):
        action = {"actionType": {"internal_name": "log_action"}}
        self.assertEqual(_action_type_name(action), "log_action")

    def test_string_action_type(self):
        action = {"actionType": "SomeAction"}
        self.assertEqual(_action_type_name(action), "SomeAction")

    def test_none_action_type(self):
        self.assertEqual(_action_type_name({}), "")

    def test_missing_action_type(self):
        self.assertEqual(_action_type_name({"other": "val"}), "")


class TestExtractPillMatches(unittest.TestCase):
    def test_string_match(self):
        matches = _extract_pill_matches("trigger.current.assigned_to", "trigger.current")
        self.assertEqual(len(matches), 1)
        self.assertIn("trigger.current", matches[0]["value"])

    def test_string_no_match(self):
        matches = _extract_pill_matches("hello world", "trigger.current")
        self.assertEqual(len(matches), 0)

    def test_list_match(self):
        data = ["trigger.current.x", "other", "trigger.current.y"]
        matches = _extract_pill_matches(data, "trigger.current")
        self.assertEqual(len(matches), 2)

    def test_dict_match(self):
        data = {"field1": "trigger.current.x", "field2": "no match"}
        matches = _extract_pill_matches(data, "trigger.current")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["path"], "field1")

    def test_nested_structure(self):
        data = {"inputs": [{"value": "trigger.current"}, {"value": "other"}]}
        matches = _extract_pill_matches(data, "trigger.current")
        self.assertEqual(len(matches), 1)

    def test_empty_string_default_path(self):
        matches = _extract_pill_matches("trigger.current", "trigger.current")
        self.assertEqual(matches[0]["path"], "$")


class TestBuildComponentTree(unittest.TestCase):
    def test_flat_components(self):
        components = [
            {"sys_id": "a", "order": "1"},
            {"sys_id": "b", "order": "2"},
        ]
        tree = _build_component_tree(components)
        self.assertEqual(len(tree), 2)
        self.assertEqual(tree[0]["sys_id"], "a")

    def test_nested_components(self):
        components = [
            {"sys_id": "parent", "order": "1", "nesting_parent": ""},
            {"sys_id": "child", "order": "2", "nesting_parent": "parent"},
        ]
        tree = _build_component_tree(components)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["sys_id"], "parent")
        self.assertEqual(len(tree[0]["children"]), 1)
        self.assertEqual(tree[0]["children"][0]["sys_id"], "child")

    def test_empty_list(self):
        tree = _build_component_tree([])
        self.assertEqual(tree, [])

    def test_orphan_parent_reference(self):
        """Children referencing unknown parent go to root."""
        components = [
            {"sys_id": "orphan", "order": "1", "nesting_parent": "unknown_parent"},
        ]
        tree = _build_component_tree(components)
        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["sys_id"], "orphan")


class TestParseLabelCache(unittest.TestCase):
    def test_comma_separated(self):
        result = _parse_label_cache("label1,label2,label3")
        self.assertEqual(result, ["label1", "label2", "label3"])

    def test_newline_separated(self):
        result = _parse_label_cache("label1\nlabel2\nlabel3")
        self.assertEqual(result, ["label1", "label2", "label3"])

    def test_mixed_separators(self):
        result = _parse_label_cache("label1,label2\nlabel3")
        self.assertEqual(result, ["label1", "label2", "label3"])

    def test_empty_string(self):
        self.assertEqual(_parse_label_cache(""), [])

    def test_none(self):
        self.assertEqual(_parse_label_cache(None), [])

    def test_whitespace_handling(self):
        result = _parse_label_cache("  a  ,  b  ")
        self.assertEqual(result, ["a", "b"])


class TestBuildProcessflowDetail(unittest.TestCase):
    def test_basic_flow_data(self):
        flow_data = {
            "actionInstances": [
                {
                    "order": "100",
                    "uiUniqueIdentifier": "ui1",
                    "parent": "",
                    "id": "act1",
                    "actionTypeSysId": "ats1",
                    "actionType": {"name": "Log"},
                    "name": "Log Action",
                    "internalName": "log_action",
                    "inputs": [],
                    "outputs": [],
                },
            ],
            "flowLogicInstances": [
                {
                    "order": "200",
                    "uiUniqueIdentifier": "ui2",
                    "parent": "",
                    "id": "logic1",
                    "flowLogicDefinition": {"type": "if", "name": "If Condition"},
                    "name": "Check",
                    "inputs": [
                        {"name": "condition_name", "value": "My Condition"},
                        {"name": "condition", "value": "1=1"},
                    ],
                    "connectedTo": "",
                    "outputsToAssign": [],
                    "flowBlockId": "fb1",
                    "definitionId": "def1",
                },
            ],
            "subFlowInstances": [
                {
                    "order": "300",
                    "uiUniqueIdentifier": "ui3",
                    "parent": "",
                    "id": "sub1",
                    "subFlow": {
                        "name": "Sub Flow",
                        "internalName": "sub_flow",
                        "scopeName": "global",
                    },
                    "subflowSysId": "sf1",
                    "inputs": [{"name": "x", "value": "1"}],
                },
            ],
            "inputs": [{"name": "input1"}],
            "outputs": [{"name": "output1"}],
            "flowVariables": [{"name": "var1"}],
            "triggerInstances": [{"name": "trigger1"}],
            "label_cache": ["lc1"],
            "deletedFlowLogicInstances": [{"name": "deleted1"}],
        }
        detail = _build_processflow_detail(flow_data)
        self.assertEqual(len(detail["actions"]), 1)
        self.assertEqual(detail["actions"][0]["action_type_name"], "Log")
        self.assertEqual(len(detail["logic"]), 1)
        self.assertEqual(detail["logic"][0]["logic_type"], "if")
        self.assertEqual(detail["logic"][0]["condition_label"], "My Condition")
        self.assertEqual(detail["logic"][0]["condition"], "1=1")
        self.assertEqual(len(detail["subflows"]), 1)
        self.assertEqual(detail["subflows"][0]["subflow_name"], "Sub Flow")
        self.assertEqual(detail["counts"]["actions"], 1)
        self.assertEqual(detail["counts"]["logic"], 1)
        self.assertEqual(detail["counts"]["subflows"], 1)
        self.assertEqual(detail["counts"]["triggers"], 1)
        self.assertEqual(detail["counts"]["inputs"], 1)
        self.assertEqual(detail["counts"]["outputs"], 1)
        self.assertEqual(detail["counts"]["variables"], 1)
        self.assertEqual(len(detail["label_cache"]), 1)

    def test_empty_flow_data(self):
        detail = _build_processflow_detail({})
        self.assertEqual(detail["actions"], [])
        self.assertEqual(detail["logic"], [])
        self.assertEqual(detail["subflows"], [])
        self.assertEqual(detail["counts"]["actions"], 0)

    def test_logic_non_dict_inputs(self):
        flow_data = {
            "flowLogicInstances": [
                {
                    "order": "100",
                    "inputs": ["not_a_dict"],
                },
            ],
        }
        detail = _build_processflow_detail(flow_data)
        self.assertEqual(len(detail["logic"]), 1)
        self.assertEqual(detail["logic"][0]["condition_label"], "")

    def test_subflow_inputs_excluded(self):
        flow_data = {
            "subFlowInstances": [
                {
                    "order": "100",
                    "subFlow": {},
                    "inputs": [{"name": "x"}],
                },
            ],
        }
        detail = _build_processflow_detail(flow_data, include_subflow_inputs=False)
        self.assertEqual(detail["subflows"][0]["inputs"], [])

    def test_label_cache_string(self):
        flow_data = {"label_cache": "some_string"}
        detail = _build_processflow_detail(flow_data)
        # label_cache is a string → len(str(label_cache))
        self.assertIn("label_cache", detail)

    def test_null_inputs_outputs(self):
        flow_data = {
            "inputs": None,
            "outputs": None,
            "flowVariables": None,
            "triggerInstances": None,
            "label_cache": None,
            "deletedFlowLogicInstances": None,
        }
        detail = _build_processflow_detail(flow_data)
        self.assertEqual(detail["inputs"], [])
        self.assertEqual(detail["outputs"], [])
        self.assertEqual(detail["variables"], [])
        self.assertEqual(detail["triggers"], [])


class TestExtractProcessflowStructure(unittest.TestCase):
    def test_full_structure(self):
        result = {
            "result": {
                "actionInstances": [
                    {"name": "Act1", "position": 1, "actionType": "Log"},
                    {"name": "Act2", "order": 2, "action_type": "Email"},
                ],
                "flowLogicInstances": [
                    {"name": "If1", "position": 3, "type": "if"},
                    {"name": "If2", "order": 4, "compilableType": "foreach"},
                ],
                "subFlowInstances": [
                    {"name": "Sub1", "position": 5},
                ],
                "triggerInstances": [{"name": "T1"}],
                "flowVariables": [{"name": "v1"}],
                "inputs": [{"name": "i1"}],
                "outputs": [{"name": "o1"}],
            },
        }
        structure = _extract_processflow_structure(result)
        self.assertEqual(structure["total_actions"], 2)
        self.assertEqual(structure["total_logic"], 2)
        self.assertEqual(structure["total_subflows"], 1)
        self.assertEqual(structure["total_triggers"], 1)
        self.assertEqual(structure["total_variables"], 1)
        self.assertEqual(len(structure["flat_summary"]), 5)
        self.assertEqual(structure["flat_summary"][0]["type"], "action")

    def test_empty_result(self):
        structure = _extract_processflow_structure({"result": {}})
        self.assertEqual(structure["total_actions"], 0)
        self.assertEqual(structure["flat_summary"], [])

    def test_inputs_not_list(self):
        result = {"result": {"inputs": "not_a_list", "outputs": 42}}
        structure = _extract_processflow_structure(result)
        self.assertEqual(structure["inputs"], [])
        self.assertEqual(structure["outputs"], [])


class TestDiffFlows(unittest.TestCase):
    def test_identical(self):
        a = {"name": "Flow", "status": "Published"}
        b = {"name": "Flow", "status": "Published"}
        diff = _diff_flows(a, b)
        self.assertEqual(diff["total_identical"], 2)
        self.assertEqual(diff["total_different"], 0)

    def test_different(self):
        a = {"name": "Flow A", "status": "Published"}
        b = {"name": "Flow B", "status": "Draft"}
        diff = _diff_flows(a, b)
        self.assertEqual(diff["total_different"], 2)
        self.assertEqual(diff["total_identical"], 0)

    def test_label_cache_diff(self):
        a = {"label_cache": "ref1,ref2,ref3"}
        b = {"label_cache": "ref2,ref3,ref4"}
        diff = _diff_flows(a, b)
        self.assertEqual(diff["total_different"], 1)
        entry = diff["differences"][0]
        self.assertEqual(entry["only_in_a"], ["ref1"])
        self.assertEqual(entry["only_in_b"], ["ref4"])
        self.assertNotIn("flow_a", entry)

    def test_subflow_bindings_diff(self):
        a = {
            "subflow_bindings": [
                {"actual_subflow": "Sub A"},
                {"actual_subflow": "Sub Common"},
            ]
        }
        b = {
            "subflow_bindings": [
                {"actual_subflow": "Sub B"},
                {"actual_subflow": "Sub Common"},
            ]
        }
        diff = _diff_flows(a, b)
        entry = diff["differences"][0]
        self.assertEqual(entry["only_in_a"], ["Sub A"])
        self.assertEqual(entry["only_in_b"], ["Sub B"])
        self.assertIn("Sub Common", entry["common"])


class TestExtractComparable(unittest.TestCase):
    def test_processflow_format(self):
        flow_data = {
            "name": "Flow1",
            "status": "Published",
            "active": "true",
            "scope": "global",
            "actionInstances": [{"name": "A1", "actionType": "Log", "position": 1}],
            "flowLogicInstances": [{"name": "L1", "type": "if", "position": 2}],
            "subFlowInstances": [{"name": "S1", "position": 3}],
            "triggerInstances": [{"name": "T1"}],
            "flowVariables": [{"name": "V1"}],
            "inputs": [],
            "outputs": [],
            "label_cache": "cache_data",
        }
        result = _extract_comparable(flow_data, include_label_cache=True)
        self.assertEqual(result["name"], "Flow1")
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(result["trigger_count"], 1)
        self.assertEqual(result["variable_count"], 1)
        self.assertEqual(result["label_cache"], "cache_data")

    def test_processflow_format_no_label_cache(self):
        flow_data = {
            "actionInstances": [],
            "flowLogicInstances": [],
            "subFlowInstances": [],
        }
        result = _extract_comparable(flow_data, include_label_cache=False)
        self.assertNotIn("label_cache", result)

    def test_table_api_format_with_structure(self):
        flow_data = {
            "name": "TableFlow",
            "status": "Draft",
            "active": "true",
            "sys_scope": "x_app",
            "_structure": {
                "success": True,
                "flat_summary": [
                    {"name": "A1", "type": "action", "action_type": "Log", "order": 1},
                    {"name": "L1", "type": "logic", "logic_type": "if", "order": 2},
                    {"name": "S1", "type": "subflow", "order": 3},
                ],
                "total_actions": 1,
                "total_logic": 1,
                "total_subflows": 1,
                "subflow_bindings": [
                    {
                        "order": "3",
                        "instance_name": "Sub1",
                        "subflow_parent_flow_name": "Parent Subflow",
                        "subflow_parent_flow_id": "ps1",
                    },
                ],
            },
            "_triggers": [{"sys_id": "t1"}],
            "label_cache": "lc_data",
        }
        result = _extract_comparable(flow_data, include_label_cache=True)
        self.assertEqual(result["name"], "TableFlow")
        self.assertEqual(len(result["actions"]), 1)
        self.assertEqual(len(result["logic"]), 1)
        self.assertEqual(len(result["subflows"]), 1)
        self.assertEqual(result["total_actions"], 1)
        self.assertEqual(result["trigger_count"], 1)
        self.assertEqual(len(result["subflow_bindings"]), 1)
        self.assertEqual(result["label_cache"], "lc_data")

    def test_table_api_format_no_triggers(self):
        flow_data = {
            "name": "Flow",
            "_structure": {"success": False},
        }
        result = _extract_comparable(flow_data, include_label_cache=False)
        self.assertNotIn("trigger_count", result)
        self.assertNotIn("actions", result)


class TestIsBrowserAuth(unittest.TestCase):
    def test_basic_auth(self):
        config = _make_basic_config()
        self.assertFalse(_is_browser_auth(config))

    def test_browser_auth(self):
        config = _make_browser_config()
        self.assertTrue(_is_browser_auth(config))


# ---------------------------------------------------------------------------
# Helper tests that need mocking
# ---------------------------------------------------------------------------


class TestGetSnapshotId(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_returns_published_snapshot(self, mock_qp):
        mock_qp.return_value = (
            [
                {"sys_id": "snap1", "status": "Draft"},
                {"sys_id": "snap2", "status": "Published"},
            ],
            2,
        )
        result = _get_snapshot_id(self.config, self.auth_manager, "flow1")
        self.assertEqual(result, "snap2")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_fallback_to_first(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "snap1", "status": "Draft"}], 1)
        result = _get_snapshot_id(self.config, self.auth_manager, "flow1")
        self.assertEqual(result, "snap1")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_no_snapshots(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = _get_snapshot_id(self.config, self.auth_manager, "flow1")
        self.assertIsNone(result)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_exception_returns_none(self, mock_qp):
        mock_qp.side_effect = RuntimeError("API error")
        result = _get_snapshot_id(self.config, self.auth_manager, "flow1")
        self.assertIsNone(result)


class TestTracePillUsage(unittest.TestCase):
    def test_trace_finds_matches(self):
        flow_data = {
            "actionInstances": [
                {
                    "order": "100",
                    "uiUniqueIdentifier": "ui1",
                    "parent": "",
                    "id": "a1",
                    "actionTypeSysId": "",
                    "actionType": {"name": "Log"},
                    "name": "Log Action",
                    "internalName": "",
                    "inputs": [{"name": "val", "value": "trigger.current.x"}],
                    "outputs": [],
                },
            ],
            "flowLogicInstances": [],
            "subFlowInstances": [],
        }
        result = _trace_pill_usage(flow_data, "trigger.current")
        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["pill"], "trigger.current")
        self.assertEqual(len(result["components"]), 1)
        self.assertEqual(result["components"][0]["component_type"], "action")

    def test_trace_no_matches(self):
        flow_data = {
            "actionInstances": [],
            "flowLogicInstances": [],
            "subFlowInstances": [],
        }
        result = _trace_pill_usage(flow_data, "nonexistent")
        self.assertEqual(result["match_count"], 0)


class TestTryProcessflowApi(unittest.TestCase):
    def setUp(self):
        self.config = _make_browser_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    def test_successful_response(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": {
                "data": {
                    "id": "flow1",
                    "name": "My Flow",
                    "actionInstances": [],
                }
            }
        }
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("result", result)
        self.assertEqual(result["result"]["name"], "My Flow")

    def test_non_dict_response(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = "not a dict"
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("_error", result)

    def test_error_message_in_response(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": {
                "errorMessage": "Plugin not active",
                "errorCode": 1,
            }
        }
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("_error", result)
        self.assertIn("Plugin not active", result["_error"])

    def test_error_code_nonzero(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": {
                "errorCode": 42,
            }
        }
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("_error", result)

    def test_no_data_key(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": {
                "id": "flow1",
                "name": "My Flow",
            }
        }
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("result", result)
        self.assertEqual(result["result"]["name"], "My Flow")

    def test_empty_data_key(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": {
                "data": {},
            }
        }
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("result", result)
        self.assertEqual(result["result"]["data"], {})

    def test_no_result_key(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": "flow1",
            "name": "My Flow",
            "data": {"id": "f1", "name": "N"},
        }
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("result", result)

    def test_exception_returns_error(self):
        self.auth_manager.make_request.side_effect = RuntimeError("Connection failed")
        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("_error", result)
        self.assertIn("Connection failed", result["_error"])

    def test_result_is_list_not_dict(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": [1, 2, 3],
        }
        mock_resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = mock_resp

        result = _try_processflow_api(self.config, self.auth_manager, "flow1")
        self.assertIn("result", result)


# ---------------------------------------------------------------------------
# Tool-level tests with mocking
# ---------------------------------------------------------------------------


class TestListFlowsAdvanced(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_subflow_type_filter(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "sf1", "name": "SubFlow1"}], 1)
        result = list_flows(self.config, self.auth_manager, ListFlowsParams(type="subflow"))
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertIn("type=subflow", query)
        self.assertIn("substatusISEMPTY", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_all_type_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = list_flows(self.config, self.auth_manager, ListFlowsParams(type="all"))
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertNotIn("type!=", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_status_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = list_flows(self.config, self.auth_manager, ListFlowsParams(status="Published"))
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertIn("status=Published", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_name_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = list_flows(self.config, self.auth_manager, ListFlowsParams(name="Incident"))
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertIn("nameLIKEIncident", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_scope_filter(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = list_flows(self.config, self.auth_manager, ListFlowsParams(scope="global"))
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertIn("sys_scope.scope=global", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_additional_query(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = list_flows(
            self.config, self.auth_manager, ListFlowsParams(query="custom_field=value")
        )
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertIn("custom_field=value", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_include_inactive(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = list_flows(self.config, self.auth_manager, ListFlowsParams(include_inactive=True))
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertNotIn("active=true", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_exception_returns_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("API down")
        result = list_flows(self.config, self.auth_manager, ListFlowsParams())
        self.assertFalse(result["success"])
        self.assertIn("API down", result["error"])


class TestGetFlowDetailsAdvanced(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.browser_config = _make_browser_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_processflow_fails_falls_back_with_note(self, mock_qp):
        """Browser auth + processflow returns error → fallback with note."""
        mock_qp.return_value = ([{"sys_id": "flow1", "name": "Flow One"}], 1)

        with patch(
            "servicenow_mcp.tools.flow_designer_tools._try_processflow_api",
            return_value={"_error": "plugin not active"},
        ):
            result = get_flow_details(
                self.browser_config,
                self.auth_manager,
                GetFlowDetailsParams(
                    flow_id="flow1",
                    include_structure=True,
                ),
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "table_api")
        self.assertIn("processflow_note", result)

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api", return_value=None)
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_processflow_none_falls_back(self, mock_qp, mock_pf):
        mock_qp.return_value = ([{"sys_id": "flow1"}], 1)
        result = get_flow_details(
            self.browser_config,
            self.auth_manager,
            GetFlowDetailsParams(
                flow_id="flow1",
                include_structure=True,
            ),
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "table_api")
        self.assertIn("processflow_note", result)

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_triggers_included(self, mock_qp, mock_triggers):
        mock_qp.return_value = ([{"sys_id": "flow1", "name": "Flow One"}], 1)
        mock_triggers.return_value = [{"sys_id": "trig1"}]

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(
                flow_id="flow1",
                include_triggers=True,
            ),
        )
        self.assertEqual(result["triggers"][0]["sys_id"], "trig1")

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_structure_error_included(self, mock_qp, mock_structure):
        mock_qp.return_value = ([{"sys_id": "flow1", "name": "Flow One"}], 1)
        mock_structure.return_value = {"success": False, "error": "no snapshot"}

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(
                flow_id="flow1",
                include_structure=True,
            ),
        )
        self.assertIn("structure_error", result)

    @patch("servicenow_mcp.tools.flow_designer_tools._build_subflow_tree")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_subflow_tree_included(self, mock_qp, mock_tree):
        mock_qp.return_value = ([{"sys_id": "flow1"}], 1)
        mock_tree.return_value = {"flow_id": "flow1", "children": []}

        result = get_flow_details(
            self.config,
            self.auth_manager,
            GetFlowDetailsParams(
                flow_id="flow1",
                include_subflow_tree=True,
            ),
        )
        self.assertIn("subflow_tree", result)


class TestGetFlowExecutionsAdvanced(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_context_mode_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(context_id="missing"),
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["execution"], {})

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_context_mode_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("DB error")
        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(context_id="ctx1"),
        )
        self.assertFalse(result["success"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_mode_with_flow_name(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "ctx1"}], 1)
        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(flow_name="MyFlow"),
        )
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertIn("nameLIKEMyFlow", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_mode_with_state(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(state="Error"),
        )
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertIn("state=Error", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_mode_with_source_record(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(source_record="INC001"),
        )
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertIn("source_recordLIKEINC001", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_mode_error(self, mock_qp):
        mock_qp.side_effect = RuntimeError("Timeout")
        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(flow_id="f1"),
        )
        self.assertFalse(result["success"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_list_mode_no_filters(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "ctx1"}], 1)
        result = get_flow_executions(
            self.config,
            self.auth_manager,
            GetFlowExecutionsParams(),
        )
        self.assertTrue(result["success"])
        query = mock_qp.call_args[1]["query"]
        self.assertEqual(query, "")


class TestFetchExecutionSummary(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_with_snapshot(self, mock_snap, mock_count, mock_qp):
        mock_snap.return_value = "snap1"
        mock_count.return_value = 10
        mock_qp.return_value = ([{"sys_id": "ctx1"}], 1)

        result = _fetch_execution_summary(self.config, self.auth_manager, "flow1")
        self.assertIn("counts", result)
        self.assertIn("recent", result)
        self.assertEqual(result["counts"]["total"], 10)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_without_snapshot(self, mock_snap, mock_count, mock_qp):
        mock_snap.return_value = None
        mock_count.return_value = 5
        mock_qp.return_value = ([], 0)

        result = _fetch_execution_summary(self.config, self.auth_manager, "flow1")
        self.assertEqual(result["counts"]["total"], 5)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_count")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_snapshot_same_as_flow_id(self, mock_snap, mock_count, mock_qp):
        """Snapshot ID same as flow_id → should not duplicate."""
        mock_snap.return_value = "flow1"
        mock_count.return_value = 3
        mock_qp.return_value = ([], 0)

        result = _fetch_execution_summary(self.config, self.auth_manager, "flow1")
        self.assertEqual(result["counts"]["total"], 3)


class TestFetchFlowTriggers(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_with_snapshot(self, mock_snap, mock_qp):
        mock_snap.return_value = "snap1"
        mock_qp.return_value = ([{"sys_id": "trig1"}], 1)

        triggers = _fetch_flow_triggers(self.config, self.auth_manager, "flow1")
        self.assertEqual(len(triggers), 1)
        query = mock_qp.call_args[1]["query"]
        self.assertIn("flow=flow1", query)
        self.assertIn("flow=snap1", query)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_without_snapshot(self, mock_snap, mock_qp):
        mock_snap.return_value = None
        mock_qp.return_value = ([], 0)

        _fetch_flow_triggers(self.config, self.auth_manager, "flow1")
        query = mock_qp.call_args[1]["query"]
        self.assertEqual(query, "flow=flow1")


class TestBuildSubflowTree(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.browser_config = _make_browser_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_cycle_detection(self, mock_qp):
        """Should detect cycles and stop recursion."""
        result = _build_subflow_tree(
            self.config,
            self.auth_manager,
            "flow1",
            visited={"flow1"},
        )
        self.assertTrue(result["cycle_detected"])
        self.assertEqual(result["flow_id"], "flow1")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_basic_auth_table_fallback(self, mock_qp):
        mock_qp.return_value = (
            [{"sys_id": "flow1", "name": "My Flow", "type": "flow", "sys_scope": "global"}],
            1,
        )
        with patch(
            "servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure",
            return_value={"subflow_bindings": []},
        ):
            result = _build_subflow_tree(self.config, self.auth_manager, "flow1")
        self.assertEqual(result["name"], "My Flow")
        self.assertFalse(result["cycle_detected"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_basic_auth_no_records(self, mock_qp):
        mock_qp.return_value = ([], 0)
        with patch(
            "servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure",
            return_value={"subflow_bindings": []},
        ):
            result = _build_subflow_tree(self.config, self.auth_manager, "flow1")
        self.assertEqual(result["name"], "")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_browser_auth_processflow_with_subflows(self, mock_qp):
        processflow_data = {
            "result": {
                "name": "Parent Flow",
                "type": "flow",
                "scope": "global",
                "subFlowInstances": [
                    {
                        "order": "100",
                        "uiUniqueIdentifier": "ui1",
                        "subflowSysId": "child1",
                        "subFlow": {"name": "Child Flow", "id": "child1"},
                    },
                ],
            }
        }
        with patch(
            "servicenow_mcp.tools.flow_designer_tools._try_processflow_api",
            return_value=processflow_data,
        ):
            with patch(
                "servicenow_mcp.tools.flow_designer_tools._build_subflow_tree",
                side_effect=lambda c, a, fid, v=None: {
                    "flow_id": fid,
                    "name": "Child Flow",
                    "children": [],
                    "cycle_detected": False,
                },
            ):
                result = _build_subflow_tree(self.browser_config, self.auth_manager, "flow1")
        self.assertEqual(result["name"], "Parent Flow")
        self.assertEqual(len(result["children"]), 1)
        self.assertEqual(result["children"][0]["flow_id"], "child1")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_browser_auth_processflow_empty_name_falls_back(self, mock_qp):
        """Processflow returns empty name → falls back to table API."""
        processflow_data = {"result": {"name": "", "type": "", "scope": ""}}
        mock_qp.return_value = (
            [{"sys_id": "flow1", "name": "From Table", "type": "flow", "sys_scope": "global"}],
            1,
        )
        with patch(
            "servicenow_mcp.tools.flow_designer_tools._try_processflow_api",
            return_value=processflow_data,
        ):
            with patch(
                "servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure",
                return_value={"subflow_bindings": []},
            ):
                result = _build_subflow_tree(self.browser_config, self.auth_manager, "flow1")
        self.assertEqual(result["name"], "From Table")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_table_fallback_with_subflow_bindings(self, mock_qp):
        mock_qp.return_value = (
            [{"sys_id": "flow1", "name": "Flow", "type": "flow", "sys_scope": "global"}],
            1,
        )
        structure = {
            "subflow_bindings": [
                {
                    "order": "100",
                    "ui_id": "ui1",
                    "subflow_parent_flow_id": "child1",
                    "subflow_parent_flow_name": "Child Flow",
                },
            ],
        }
        with patch(
            "servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure",
            return_value=structure,
        ):
            with patch(
                "servicenow_mcp.tools.flow_designer_tools._build_subflow_tree",
                side_effect=lambda c, a, fid, v=None: {
                    "flow_id": fid,
                    "name": "Child",
                    "children": [],
                    "cycle_detected": False,
                },
            ):
                result = _build_subflow_tree(self.config, self.auth_manager, "flow1")
        self.assertEqual(len(result["children"]), 1)
        self.assertEqual(result["children"][0]["flow_id"], "child1")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_child_with_empty_flow_id(self, mock_qp):
        mock_qp.return_value = (
            [{"sys_id": "flow1", "name": "Flow", "type": "flow", "sys_scope": "global"}],
            1,
        )
        structure = {
            "subflow_bindings": [
                {
                    "order": "100",
                    "ui_id": "ui1",
                    "subflow_parent_flow_id": "",
                    "subflow_parent_flow_name": "",
                },
            ],
        }
        with patch(
            "servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure",
            return_value=structure,
        ):
            result = _build_subflow_tree(self.config, self.auth_manager, "flow1")
        self.assertEqual(len(result["children"]), 1)
        self.assertEqual(result["children"][0]["children"], [])


class TestFetchFlowStructure(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.browser_config = _make_browser_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_browser_auth_processflow(self, mock_pf):
        mock_pf.return_value = {
            "result": {
                "actionInstances": [{"name": "A1", "position": 1}],
                "flowLogicInstances": [{"name": "L1", "position": 2, "type": "if"}],
                "subFlowInstances": [{"name": "S1", "position": 3}],
                "triggerInstances": [{"name": "T1"}],
                "flowVariables": [{"name": "V1"}],
                "inputs": [],
                "outputs": [],
            }
        }
        result = _fetch_flow_structure(self.browser_config, self.auth_manager, "flow1")
        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "processflow_api")
        self.assertEqual(result["total_actions"], 1)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_table_api_no_snapshot(self, mock_snap, mock_qp):
        mock_snap.return_value = None
        result = _fetch_flow_structure(self.config, self.auth_manager, "flow1")
        self.assertFalse(result["success"])
        self.assertIn("No snapshot", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_subflow_bindings")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_table_api_full_structure(self, mock_snap, mock_qp, mock_bindings):
        mock_snap.return_value = "snap1"

        # First call: flow record for label_cache, then actions, logic, subflows
        mock_qp.side_effect = [
            # flow record
            ([{"sys_id": "flow1", "name": "My Flow", "label_cache": "lc1"}], 1),
            # actions
            (
                [
                    {
                        "sys_id": "a1",
                        "name": "Action1",
                        "order": "100",
                        "action_type": "Log",
                        "position": "100",
                        "nesting_parent": "",
                        "compilable_type": "",
                    },
                ],
                1,
            ),
            # logic
            (
                [
                    {
                        "sys_id": "l1",
                        "name": "If1",
                        "order": "200",
                        "type": "if",
                        "position": "200",
                        "nesting_parent": "",
                        "compilable_type": "",
                    },
                ],
                1,
            ),
            # subflows
            (
                [
                    {
                        "sys_id": "s1",
                        "name": "Sub1",
                        "order": "300",
                        "position": "300",
                        "nesting_parent": "",
                        "compilable_type": "",
                    },
                ],
                1,
            ),
        ]

        mock_bindings.return_value = {
            "subflow_bindings": [
                {
                    "order": "300",
                    "ui_id": "ui1",
                    "instance_name": "Sub1",
                    "subflow_snapshot_id": "snap_s1",
                    "subflow_parent_flow_id": "parent_flow",
                    "subflow_parent_flow_name": "Parent Subflow",
                    "label_matches": ["Sub1"],
                },
            ],
            "mismatch_summary": {"mismatch_count": 0, "mismatches": []},
        }

        # Need _try_processflow_api to return None (basic auth)
        with patch(
            "servicenow_mcp.tools.flow_designer_tools._try_processflow_api",
            return_value=None,
        ):
            result = _fetch_flow_structure(self.config, self.auth_manager, "flow1")

        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "table_api_fallback")
        self.assertEqual(result["total_actions"], 1)
        self.assertEqual(result["total_logic"], 1)
        self.assertEqual(result["total_subflows"], 1)
        self.assertIn("subflow_bindings", result)

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_subflow_bindings")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_table_api_no_subflows(self, mock_snap, mock_qp, mock_bindings):
        mock_snap.return_value = "snap1"
        mock_qp.side_effect = [
            ([{"sys_id": "flow1", "name": "Flow", "label_cache": ""}], 1),
            ([], 0),  # actions
            ([], 0),  # logic
            ([], 0),  # subflows
        ]

        with patch(
            "servicenow_mcp.tools.flow_designer_tools._try_processflow_api",
            return_value=None,
        ):
            result = _fetch_flow_structure(self.config, self.auth_manager, "flow1")

        self.assertTrue(result["success"])
        self.assertIn("basic auth", result["note"])

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_subflow_bindings")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_table_api_with_mismatches(self, mock_snap, mock_qp, mock_bindings):
        mock_snap.return_value = "snap1"
        mock_qp.side_effect = [
            ([{"sys_id": "flow1", "name": "Flow", "label_cache": "old_label"}], 1),
            ([], 0),  # actions
            ([], 0),  # logic
            (
                [
                    {
                        "sys_id": "s1",
                        "name": "Sub1",
                        "order": "100",
                        "position": "100",
                        "nesting_parent": "",
                        "compilable_type": "",
                    },
                ],
                1,
            ),  # subflows
        ]

        mock_bindings.return_value = {
            "subflow_bindings": [
                {
                    "order": "100",
                    "ui_id": "ui1",
                    "instance_name": "Sub1",
                    "subflow_snapshot_id": "snap_s1",
                    "subflow_parent_flow_id": "pf1",
                    "subflow_parent_flow_name": "Parent",
                    "label_matches": ["Old Name"],
                },
            ],
            "mismatch_summary": {
                "mismatch_count": 1,
                "mismatches": [
                    {
                        "ui_id": "ui1",
                        "order": "100",
                        "label": "Old Name",
                        "actual_subflow": "Parent",
                        "actual_subflow_id": "pf1",
                    }
                ],
            },
        }

        with patch(
            "servicenow_mcp.tools.flow_designer_tools._try_processflow_api",
            return_value=None,
        ):
            result = _fetch_flow_structure(self.config, self.auth_manager, "flow1")

        self.assertTrue(result["success"])
        self.assertIn("MISMATCH", result["note"])

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    @patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id")
    def test_table_api_exception(self, mock_snap, mock_qp):
        mock_snap.return_value = "snap1"
        mock_qp.side_effect = RuntimeError("DB error")

        with patch(
            "servicenow_mcp.tools.flow_designer_tools._try_processflow_api",
            return_value=None,
        ):
            result = _fetch_flow_structure(self.config, self.auth_manager, "flow1")

        self.assertFalse(result["success"])
        self.assertIn("DB error", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_browser_auth_processflow_none(self, mock_pf):
        """Browser auth but processflow returns None → table fallback."""
        mock_pf.return_value = None
        with patch(
            "servicenow_mcp.tools.flow_designer_tools._get_snapshot_id",
            return_value=None,
        ):
            result = _fetch_flow_structure(self.browser_config, self.auth_manager, "flow1")
        self.assertFalse(result["success"])

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_browser_auth_processflow_error(self, mock_pf):
        mock_pf.return_value = {"_error": "plugin not active"}
        result = _fetch_flow_structure(self.browser_config, self.auth_manager, "flow1")
        self.assertTrue(result["success"])
        self.assertEqual(result["source"], "processflow_api")
        self.assertEqual(result["total_actions"], 0)


class TestFetchSubflowBindings(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_no_instances(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", "label1")
        self.assertEqual(result["subflow_bindings"], [])
        self.assertEqual(result["mismatch_summary"]["mismatch_count"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_full_binding_resolution(self, mock_qp):
        mock_qp.side_effect = [
            (
                [
                    {
                        "sys_id": "inst1",
                        "name": {"value": "Sub Instance", "display_value": "Sub Instance Display"},
                        "order": {"value": "100"},
                        "position": {"value": "100"},
                        "ui_id": {"value": "ui1"},
                        "parent_ui_id": {"value": ""},
                        "nesting_parent": {"value": ""},
                        "subflow": {"value": "snap_s1", "display_value": "Sub Flow Display"},
                    },
                ],
                1,
            ),
            (
                [
                    {
                        "sys_id": "snap_s1",
                        "name": {
                            "value": "Sub Flow Snapshot",
                            "display_value": "Sub Flow Snapshot Display",
                        },
                        "master_flow": {"value": "master1", "display_value": "Master Flow"},
                    },
                ],
                1,
            ),
            ([], 0),
        ]

        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", "label1")
        self.assertEqual(len(result["subflow_bindings"]), 1)
        binding = result["subflow_bindings"][0]
        self.assertEqual(binding["subflow_parent_flow_id"], "master1")
        self.assertEqual(binding["subflow_parent_flow_name"], "Master Flow")
        self.assertEqual(result["mismatch_summary"]["mismatch_count"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_binding_with_mismatch(self, mock_qp):
        mock_qp.side_effect = [
            # instances
            (
                [
                    {
                        "sys_id": "inst1",
                        "name": {"value": "", "display_value": ""},
                        "order": {"value": "100"},
                        "position": {"value": "100"},
                        "ui_id": {"value": "ui1"},
                        "parent_ui_id": {"value": ""},
                        "nesting_parent": {"value": ""},
                        "subflow": {"value": "snap_s1", "display_value": "Old Subflow"},
                    },
                ],
                1,
            ),
            # snapshots
            (
                [
                    {
                        "sys_id": "snap_s1",
                        "name": {"value": "New Subflow", "display_value": "New Subflow"},
                        "master_flow": {"value": "master1", "display_value": "New Master"},
                    },
                ],
                1,
            ),
        ]

        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", "Old Subflow")
        # The label "Old Subflow" matches but actual is "New Master"
        self.assertGreater(result["mismatch_summary"]["mismatch_count"], 0)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_snapshot_string_fields(self, mock_qp):
        mock_qp.side_effect = [
            (
                [
                    {
                        "sys_id": "inst1",
                        "name": {"value": "Sub1", "display_value": "Sub1"},
                        "order": {"value": "100"},
                        "position": {"value": "100"},
                        "ui_id": {"value": "ui1"},
                        "parent_ui_id": {"value": ""},
                        "nesting_parent": {"value": ""},
                        "subflow": {"value": "snap_s1", "display_value": "Sub1"},
                    },
                ],
                1,
            ),
            (
                [
                    {
                        "sys_id": "snap_s1",
                        "name": "Sub1 Snap",
                        "master_flow": "master1",
                    },
                ],
                1,
            ),
            ([{"sys_id": "master1", "name": "Master Flow"}], 1),
        ]

        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", "")
        self.assertEqual(len(result["subflow_bindings"]), 1)
        self.assertEqual(result["subflow_bindings"][0]["subflow_parent_flow_id"], "master1")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_empty_subflow_ref(self, mock_qp):
        mock_qp.side_effect = [
            (
                [
                    {
                        "sys_id": "inst1",
                        "name": {"value": "Sub1", "display_value": "Sub1"},
                        "order": {"value": "100"},
                        "position": {"value": "100"},
                        "ui_id": {"value": "ui1"},
                        "parent_ui_id": {"value": ""},
                        "nesting_parent": {"value": ""},
                        "subflow": {"value": "", "display_value": ""},
                    },
                ],
                1,
            ),
        ]

        result = _fetch_subflow_bindings(self.config, self.auth_manager, "snap1", "")
        self.assertEqual(len(result["subflow_bindings"]), 1)
        self.assertEqual(result["subflow_bindings"][0]["subflow_snapshot_id"], "")


class TestGetFlowForCompare(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.browser_config = _make_browser_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_browser_auth_success(self, mock_pf):
        mock_pf.return_value = {"result": {"name": "Flow1", "id": "f1"}}
        result = _get_flow_for_compare(self.browser_config, self.auth_manager, "f1")
        self.assertEqual(result["name"], "Flow1")

    @patch("servicenow_mcp.tools.flow_designer_tools._try_processflow_api")
    def test_browser_auth_fallback(self, mock_pf):
        mock_pf.return_value = {"_error": "fail"}
        with patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page") as mock_qp:
            mock_qp.return_value = ([{"sys_id": "f1", "name": "Flow1"}], 1)
            with patch(
                "servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure",
                return_value={"success": True},
            ):
                with patch(
                    "servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers",
                    return_value=[],
                ):
                    result = _get_flow_for_compare(self.browser_config, self.auth_manager, "f1")
        self.assertEqual(result.get("_error"), "fail")

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_table_api_not_found(self, mock_qp, mock_structure, mock_triggers):
        mock_qp.return_value = ([], 0)
        result = _get_flow_for_compare(self.config, self.auth_manager, "missing")
        self.assertIsNone(result)

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_table_api_success(self, mock_qp, mock_structure, mock_triggers):
        mock_qp.return_value = ([{"sys_id": "f1", "name": "Flow1"}], 1)
        mock_structure.return_value = {"success": True, "flat_summary": []}
        mock_triggers.return_value = [{"sys_id": "t1"}]
        result = _get_flow_for_compare(self.config, self.auth_manager, "f1")
        self.assertEqual(result["name"], "Flow1")
        self.assertIn("_structure", result)
        self.assertEqual(result["_triggers"], [{"sys_id": "t1"}])

    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_triggers")
    @patch("servicenow_mcp.tools.flow_designer_tools._fetch_flow_structure")
    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_table_api_structure_failure(self, mock_qp, mock_structure, mock_triggers):
        mock_qp.return_value = ([{"sys_id": "f1", "name": "Flow1"}], 1)
        mock_structure.return_value = {"success": False}
        mock_triggers.return_value = []
        result = _get_flow_for_compare(self.config, self.auth_manager, "f1")
        self.assertNotIn("_structure", result)


class TestResolveFlowId(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    def test_flow_id_provided(self):
        fid, err = _resolve_flow_id(self.config, self.auth_manager, "abc123", None, "A")
        self.assertEqual(fid, "abc123")
        self.assertIsNone(err)

    def test_no_flow_id_no_name(self):
        fid, err = _resolve_flow_id(self.config, self.auth_manager, None, None, "A")
        self.assertIsNone(fid)
        self.assertIn("provide flow_id or name", err)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_name_exact_match(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "abc123", "name": "My Flow"}], 1)
        fid, err = _resolve_flow_id(self.config, self.auth_manager, None, "My Flow", "A")
        self.assertEqual(fid, "abc123")
        self.assertIsNone(err)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_name_contains_match(self, mock_qp):
        mock_qp.side_effect = [
            ([], 0),
            ([{"sys_id": "abc123", "name": "My Flow Name"}], 1),
        ]
        fid, err = _resolve_flow_id(self.config, self.auth_manager, None, "My Flow Name", "A")
        self.assertEqual(fid, "abc123")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_name_multiple_matches_exact_in_results(self, mock_qp):
        mock_qp.return_value = (
            [
                {"sys_id": "id1", "name": "Other Flow"},
                {"sys_id": "id2", "name": "My Flow"},
            ],
            2,
        )
        fid, err = _resolve_flow_id(self.config, self.auth_manager, None, "My Flow", "A")
        self.assertEqual(fid, "id2")

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_name_multiple_matches_no_exact(self, mock_qp):
        mock_qp.side_effect = [
            (
                [
                    {"sys_id": "id1", "name": "Flow A"},
                    {"sys_id": "id2", "name": "Flow B"},
                ],
                2,
            ),
        ]
        fid, err = _resolve_flow_id(self.config, self.auth_manager, None, "Flow", "A")
        self.assertIsNone(fid)
        self.assertIn("matched 2 flows", err)

    @patch("servicenow_mcp.tools.flow_designer_tools.sn_query_page")
    def test_name_not_found(self, mock_qp):
        mock_qp.side_effect = [([], 0), ([], 0)]
        fid, err = _resolve_flow_id(self.config, self.auth_manager, None, "Nonexistent", "A")
        self.assertIsNone(fid)
        self.assertIn("no flow found", err)


class TestCompareFlowsAdvanced(unittest.TestCase):
    def setUp(self):
        self.config = _make_basic_config()
        self.auth_manager = MagicMock(spec=AuthManager)

    @patch("servicenow_mcp.tools.flow_designer_tools._get_flow_for_compare")
    @patch("servicenow_mcp.tools.flow_designer_tools._resolve_flow_id")
    def test_flow_a_not_found(self, mock_resolve, mock_get_flow):
        mock_resolve.side_effect = [("a1", None), ("b1", None)]
        mock_get_flow.side_effect = [None, {"name": "Flow B"}]

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(flow_id_a="a1", flow_id_b="b1"),
        )
        self.assertFalse(result["success"])
        self.assertIn("Flow A not found", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._get_flow_for_compare")
    @patch("servicenow_mcp.tools.flow_designer_tools._resolve_flow_id")
    def test_flow_b_not_found(self, mock_resolve, mock_get_flow):
        mock_resolve.side_effect = [("a1", None), ("b1", None)]
        mock_get_flow.side_effect = [
            {"name": "Flow A", "actionInstances": []},
            None,
        ]

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(flow_id_a="a1", flow_id_b="b1"),
        )
        self.assertFalse(result["success"])
        self.assertIn("Flow B not found", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._resolve_flow_id")
    def test_resolve_error_a(self, mock_resolve):
        mock_resolve.return_value = (None, "Flow A: provide flow_id or name")

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(name_a="Missing"),
        )
        self.assertFalse(result["success"])
        self.assertIn("provide flow_id or name", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._resolve_flow_id")
    def test_resolve_error_b(self, mock_resolve):
        mock_resolve.side_effect = [
            ("a1", None),
            (None, "Flow B: provide flow_id or name"),
        ]

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(flow_id_a="a1", name_b="Missing"),
        )
        self.assertFalse(result["success"])
        self.assertIn("provide flow_id or name", result["error"])

    @patch("servicenow_mcp.tools.flow_designer_tools._get_flow_for_compare")
    @patch("servicenow_mcp.tools.flow_designer_tools._resolve_flow_id")
    def test_exception_in_compare(self, mock_resolve, mock_get_flow):
        mock_resolve.side_effect = [("a1", None), ("b1", None)]
        mock_get_flow.side_effect = RuntimeError("Unexpected error")

        result = compare_flows(
            self.config,
            self.auth_manager,
            CompareFlowsParams(flow_id_a="a1", flow_id_b="b1"),
        )
        self.assertFalse(result["success"])
        self.assertIn("Unexpected error", result["error"])


if __name__ == "__main__":
    unittest.main()
