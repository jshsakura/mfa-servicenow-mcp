"""
Additional tests for workflow_tools to increase coverage to 80%+.

Covers: error paths, missing workflow_id, empty params, _unwrap_params fallback,
count_only, delete_workflow, and exception paths for every CRUD function.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.workflow_tools import (
    CreateWorkflowParams,
    ListWorkflowsParams,
    _unwrap_params,
    activate_workflow,
    add_workflow_activity,
    create_workflow,
    deactivate_workflow,
    delete_workflow,
    delete_workflow_activity,
    get_workflow_details,
    list_workflows,
    reorder_workflow_activities,
    update_workflow,
    update_workflow_activity,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


def _make_auth():
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {
        "Authorization": "Bearer test",
        "Content-Type": "application/json",
    }
    return auth


def _ok_response(payload, headers=None):
    mock = MagicMock()
    mock.json.return_value = payload
    mock.status_code = 200
    mock.raise_for_status = MagicMock()
    mock.content = json.dumps(payload).encode("utf-8")
    mock.headers = headers or {}
    return mock


class TestUnwrapParams(unittest.TestCase):
    """Cover line 145: _unwrap_params fallback when params is neither dict nor model."""

    def test_returns_raw_value_when_not_dict_or_model(self):
        result = _unwrap_params("some_string", ListWorkflowsParams)
        self.assertEqual(result, "some_string")

    def test_unwraps_pydantic_model(self):
        model = CreateWorkflowParams(name="Test")
        result = _unwrap_params(model, CreateWorkflowParams)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["name"], "Test")


class TestListWorkflowsEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_count_only(self):
        """Cover line 246-247: count_only branch."""
        with patch("servicenow_mcp.tools.workflow_tools.sn_count", return_value=42):
            result = list_workflows(self.config, self.auth, {"count_only": True})
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 42)

    def test_name_and_query_filters(self):
        """Cover lines 238, 241: name and query filters."""
        resp = _ok_response({"result": []}, {"X-Total-Count": "0"})
        self.auth.make_request.return_value = resp
        result = list_workflows(self.config, self.auth, {"name": "test", "query": "table=incident"})
        self.assertEqual(result["count"], 0)

    def test_get_auth_config_error_returns_error(self):
        """Cover lines 227-229."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = list_workflows(obj1, obj2, {})
        self.assertIn("error", result)


class TestGetWorkflowDetailsEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_missing_workflow_id(self):
        """Cover line 294."""
        result = get_workflow_details(self.config, self.auth, {})
        self.assertEqual(result["error"], "Workflow ID is required")

    def test_auth_config_error(self):
        """Cover lines 289-290."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = get_workflow_details(obj1, obj2, {"workflow_id": "abc"})
        self.assertIn("error", result)

    def test_workflow_not_found(self):
        """Cover line 309."""
        resp = _ok_response({"result": []}, {"X-Total-Count": "0"})
        self.auth.make_request.return_value = resp
        result = get_workflow_details(self.config, self.auth, {"workflow_id": "nonexistent"})
        self.assertIn("not found", result["error"])

    def test_include_activities_with_version_id(self):
        """Cover the version_id branch in _fetch_workflow_activities."""
        wf_resp = _ok_response(
            {"result": [{"sys_id": "wf1", "name": "WF"}]}, {"X-Total-Count": "1"}
        )
        act_resp = _ok_response(
            {"result": [{"sys_id": "act1", "name": "A1"}]}, {"X-Total-Count": "1"}
        )
        self.auth.make_request.side_effect = [wf_resp, act_resp]
        result = get_workflow_details(
            self.config,
            self.auth,
            {
                "workflow_id": "wf1",
                "include_activities": True,
                "version_id": "ver1",
            },
        )
        self.assertEqual(result["activities"][0]["sys_id"], "act1")


class TestCreateWorkflowEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_missing_name(self):
        """Cover line 432."""
        result = create_workflow(self.config, self.auth, {})
        self.assertEqual(result["error"], "Workflow name is required")

    def test_auth_config_error(self):
        """Cover lines 426-428."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = create_workflow(obj1, obj2, {"name": "test"})
        self.assertIn("error", result)

    def test_with_attributes(self):
        """Cover line 450: attributes branch."""
        resp = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "wf1", "name": "Test"}}
        resp.raise_for_status = MagicMock()
        self.auth.make_request.return_value = resp
        result = create_workflow(
            self.config,
            self.auth,
            {"name": "Test", "attributes": {"custom_field": "val"}},
        )
        self.assertEqual(result["message"], "Workflow created successfully")

    def test_exception_path(self):
        """Cover lines 466-468."""
        self.auth.make_request.side_effect = Exception("API down")
        result = create_workflow(self.config, self.auth, {"name": "Test"})
        self.assertIn("error", result)


class TestUpdateWorkflowEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_auth_config_error(self):
        """Cover lines 500-502."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = update_workflow(obj1, obj2, {"workflow_id": "wf1", "name": "x"})
        self.assertIn("error", result)

    def test_missing_workflow_id(self):
        """Cover line 506."""
        result = update_workflow(self.config, self.auth, {})
        self.assertEqual(result["error"], "Workflow ID is required")

    def test_no_update_params(self):
        """Cover line 528."""
        result = update_workflow(self.config, self.auth, {"workflow_id": "wf1"})
        self.assertEqual(result["error"], "No update parameters provided")

    def test_table_and_active_and_attributes(self):
        """Cover lines 518, 521, 525."""
        resp = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "wf1"}}
        resp.raise_for_status = MagicMock()
        self.auth.make_request.return_value = resp
        result = update_workflow(
            self.config,
            self.auth,
            {
                "workflow_id": "wf1",
                "table": "incident",
                "active": False,
                "attributes": {"x": 1},
            },
        )
        self.assertEqual(result["message"], "Workflow updated successfully")

    def test_exception_path(self):
        """Cover lines 544-546."""
        self.auth.make_request.side_effect = Exception("Boom")
        result = update_workflow(self.config, self.auth, {"workflow_id": "wf1", "name": "x"})
        self.assertIn("error", result)


class TestActivateWorkflowEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_auth_config_error(self):
        """Cover lines 578-580."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = activate_workflow(obj1, obj2, {"workflow_id": "wf1"})
        self.assertIn("error", result)

    def test_missing_workflow_id(self):
        """Cover line 584."""
        result = activate_workflow(self.config, self.auth, {})
        self.assertEqual(result["error"], "Workflow ID is required")

    def test_exception_path(self):
        """Cover lines 605-607."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = activate_workflow(self.config, self.auth, {"workflow_id": "wf1"})
        self.assertIn("error", result)


class TestDeactivateWorkflowEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_auth_config_error(self):
        """Cover lines 639-641."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = deactivate_workflow(obj1, obj2, {"workflow_id": "wf1"})
        self.assertIn("error", result)

    def test_missing_workflow_id(self):
        """Cover line 645."""
        result = deactivate_workflow(self.config, self.auth, {})
        self.assertEqual(result["error"], "Workflow ID is required")

    def test_exception_path(self):
        """Cover lines 666-668."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = deactivate_workflow(self.config, self.auth, {"workflow_id": "wf1"})
        self.assertIn("error", result)


class TestAddWorkflowActivityEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_auth_config_error(self):
        """Cover lines 700-702."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = add_workflow_activity(obj1, obj2, {"workflow_version_id": "v1", "name": "a"})
        self.assertIn("error", result)

    def test_missing_workflow_version_id(self):
        """Cover line 707."""
        result = add_workflow_activity(self.config, self.auth, {})
        self.assertEqual(result["error"], "Workflow version ID is required")

    def test_missing_activity_name(self):
        """Cover line 711."""
        result = add_workflow_activity(self.config, self.auth, {"workflow_version_id": "v1"})
        self.assertEqual(result["error"], "Activity name is required")

    def test_with_attributes(self):
        """Cover line 727."""
        resp = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "act1"}}
        resp.raise_for_status = MagicMock()
        self.auth.make_request.return_value = resp
        result = add_workflow_activity(
            self.config,
            self.auth,
            {
                "workflow_version_id": "v1",
                "name": "Act",
                "activity_type": "task",
                "attributes": {"key": "val"},
            },
        )
        self.assertEqual(result["message"], "Workflow activity added successfully")

    def test_exception_path(self):
        """Cover lines 743-745."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = add_workflow_activity(
            self.config,
            self.auth,
            {"workflow_version_id": "v1", "name": "Act", "activity_type": "task"},
        )
        self.assertIn("error", result)


class TestUpdateWorkflowActivityEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_auth_config_error(self):
        """Cover lines 777-779."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = update_workflow_activity(obj1, obj2, {"activity_id": "a1", "name": "x"})
        self.assertIn("error", result)

    def test_missing_activity_id(self):
        """Cover line 783."""
        result = update_workflow_activity(self.config, self.auth, {})
        self.assertEqual(result["error"], "Activity ID is required")

    def test_with_attributes(self):
        """Cover line 796."""
        resp = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "a1"}}
        resp.raise_for_status = MagicMock()
        self.auth.make_request.return_value = resp
        result = update_workflow_activity(
            self.config,
            self.auth,
            {"activity_id": "a1", "attributes": {"key": "val"}},
        )
        self.assertEqual(result["message"], "Activity updated successfully")

    def test_no_update_params(self):
        """Cover line 799."""
        result = update_workflow_activity(self.config, self.auth, {"activity_id": "a1"})
        self.assertEqual(result["error"], "No update parameters provided")

    def test_exception_path(self):
        """Cover lines 815-817."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = update_workflow_activity(
            self.auth, self.config, {"activity_id": "a1", "name": "x"}
        )
        self.assertIn("error", result)


class TestDeleteWorkflowActivityEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_auth_config_error(self):
        """Cover lines 849-851."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = delete_workflow_activity(obj1, obj2, {"activity_id": "a1"})
        self.assertIn("error", result)

    def test_missing_activity_id(self):
        """Cover line 855."""
        result = delete_workflow_activity(self.config, self.auth, {})
        self.assertEqual(result["error"], "Activity ID is required")

    def test_exception_path(self):
        """Cover lines 870-872."""
        self.auth.make_request.side_effect = Exception("Fail")
        result = delete_workflow_activity(self.config, self.auth, {"activity_id": "a1"})
        self.assertIn("error", result)


class TestReorderWorkflowActivitiesEdgeCases(unittest.TestCase):
    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_auth_config_error(self):
        """Cover lines 904-906."""
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = reorder_workflow_activities(
            obj1, obj2, {"workflow_id": "wf1", "activity_ids": ["a1"]}
        )
        self.assertIn("error", result)

    def test_missing_workflow_id(self):
        """Cover line 910."""
        result = reorder_workflow_activities(self.config, self.auth, {})
        self.assertEqual(result["error"], "Workflow ID is required")

    def test_missing_activity_ids(self):
        """Cover line 914."""
        result = reorder_workflow_activities(self.config, self.auth, {"workflow_id": "wf1"})
        self.assertEqual(result["error"], "Activity IDs are required")

    def test_partial_failure(self):
        """Cover lines 939-941: individual activity reorder failure."""
        ok_resp = MagicMock()
        ok_resp.json.return_value = {"result": {}}
        ok_resp.raise_for_status = MagicMock()

        self.auth.make_request.side_effect = [ok_resp, Exception("Fail"), ok_resp]
        result = reorder_workflow_activities(
            self.config,
            self.auth,
            {"workflow_id": "wf1", "activity_ids": ["a1", "a2", "a3"]},
        )
        self.assertTrue(result["results"][0]["success"])
        self.assertFalse(result["results"][1]["success"])
        self.assertTrue(result["results"][2]["success"])

    def test_outer_exception(self):
        """Cover lines 955-957: outer try/except."""
        # Make get_headers raise to trigger the outer exception
        self.auth.get_headers.side_effect = Exception("Outer fail")
        result = reorder_workflow_activities(
            self.config,
            self.auth,
            {"workflow_id": "wf1", "activity_ids": ["a1"]},
        )
        self.assertIn("error", result)


class TestDeleteWorkflow(unittest.TestCase):
    """Cover lines 977-1005: the delete_workflow function."""

    def setUp(self):
        self.config = _make_config()
        self.auth = _make_auth()

    def test_success(self):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        self.auth.make_request.return_value = resp
        result = delete_workflow(self.config, self.auth, {"workflow_id": "wf1"})
        self.assertIn("deleted successfully", result["message"])
        self.assertEqual(result["workflow_id"], "wf1")

    def test_auth_config_error(self):
        obj1 = MagicMock()
        del obj1.get_headers
        del obj1.instance_url
        obj2 = MagicMock()
        del obj2.get_headers
        del obj2.instance_url
        result = delete_workflow(obj1, obj2, {"workflow_id": "wf1"})
        self.assertIn("error", result)

    def test_missing_workflow_id(self):
        result = delete_workflow(self.config, self.auth, {})
        self.assertEqual(result["error"], "Workflow ID is required")

    def test_exception_path(self):
        self.auth.make_request.side_effect = Exception("Fail")
        result = delete_workflow(self.config, self.auth, {"workflow_id": "wf1"})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
