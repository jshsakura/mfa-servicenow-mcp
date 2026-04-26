"""
Tests for the workflow management tools.
"""

import json
import unittest
from unittest.mock import MagicMock

import requests

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.tools.workflow_tools import (
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


class TestWorkflowTools(unittest.TestCase):
    """Tests for the workflow management tools."""

    def setUp(self):
        """Set up test fixtures."""
        self.auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        )
        self.server_config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=self.auth_config,
        )
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {
            "Authorization": "Bearer test",
            "Content-Type": "application/json",
        }

    def _finalize_response(self, mock_response):
        payload = mock_response.json.return_value
        mock_response.content = json.dumps(payload).encode("utf-8")
        mock_response.headers = getattr(mock_response, "headers", {}) or {}
        mock_response.raise_for_status = MagicMock()

    def test_list_workflows_success(self):
        """Test listing workflows successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "workflow123",
                    "name": "Incident Approval",
                    "description": "Workflow for incident approval",
                    "active": "true",
                    "table": "incident",
                },
                {
                    "sys_id": "workflow456",
                    "name": "Change Request",
                    "description": "Workflow for change requests",
                    "active": "true",
                    "table": "change_request",
                },
            ]
        }
        mock_response.headers = {"X-Total-Count": "2"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "limit": 10,
            "active": True,
        }
        result = list_workflows(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(len(result["workflows"]), 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["workflows"][0]["sys_id"], "workflow123")
        self.assertEqual(result["workflows"][1]["sys_id"], "workflow456")

    def test_list_workflows_empty_result(self):
        """Test listing workflows with empty result."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": []}
        mock_response.headers = {"X-Total-Count": "0"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "limit": 10,
            "active": True,
        }
        result = list_workflows(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(len(result["workflows"]), 0)
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["total"], 0)

    def test_list_workflows_error(self):
        """Test listing workflows with error."""
        # Mock the response
        self.auth_manager.make_request.side_effect = requests.RequestException("API Error")

        # Call the function
        params = {
            "limit": 10,
            "active": True,
        }
        result = list_workflows(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertIn("error", result)
        self.assertEqual(result["error"], "API Error")

    def test_get_workflow_details_success(self):
        """Test getting workflow details successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "workflow123",
                    "name": "Incident Approval",
                    "description": "Workflow for incident approval",
                    "active": "true",
                    "table": "incident",
                }
            ]
        }
        mock_response.headers = {"X-Total-Count": "1"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "workflow_id": "workflow123",
        }
        result = get_workflow_details(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["workflow"]["sys_id"], "workflow123")
        self.assertEqual(result["workflow"]["name"], "Incident Approval")

    def test_get_workflow_details_error(self):
        """Test getting workflow details with error."""
        # Mock the response
        self.auth_manager.make_request.side_effect = requests.RequestException("API Error")

        # Call the function
        params = {
            "workflow_id": "workflow123",
        }
        result = get_workflow_details(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertIn("error", result)
        self.assertEqual(result["error"], "API Error")

    def test_list_workflow_versions_success(self):
        """Test listing workflow versions successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "version123",
                    "workflow": "workflow123",
                    "name": "Version 1",
                    "version": "1",
                    "published": "true",
                },
                {
                    "sys_id": "version456",
                    "workflow": "workflow123",
                    "name": "Version 2",
                    "version": "2",
                    "published": "true",
                },
            ]
        }
        mock_response.headers = {"X-Total-Count": "2"}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "workflow_id": "workflow123",
            "include_versions": True,
        }
        result = get_workflow_details(self.server_config, self.auth_manager, params)

        # Verify the result — versions are nested in the response
        self.assertIn("versions", result)
        self.assertEqual(len(result["versions"]), 2)
        self.assertEqual(result["versions"][0]["sys_id"], "version123")
        self.assertEqual(result["versions"][1]["sys_id"], "version456")

    def test_get_workflow_activities_success(self):
        """Test getting workflow activities successfully."""
        # First call: workflow details
        workflow_response = MagicMock()
        workflow_response.json.return_value = {
            "result": [{"sys_id": "workflow123", "name": "Test WF"}]
        }
        workflow_response.headers = {"X-Total-Count": "1"}
        self._finalize_response(workflow_response)

        # Second call: version query
        version_response = MagicMock()
        version_response.json.return_value = {
            "result": [
                {
                    "sys_id": "version123",
                    "workflow": "workflow123",
                    "name": "Version 1",
                    "version": "1",
                    "published": "true",
                }
            ]
        }
        version_response.headers = {"X-Total-Count": "1"}
        self._finalize_response(version_response)

        # Third call: activities query
        activities_response = MagicMock()
        activities_response.json.return_value = {
            "result": [
                {
                    "sys_id": "activity123",
                    "workflow_version": "version123",
                    "name": "Approval",
                    "order": "100",
                    "activity_definition": "approval",
                },
                {
                    "sys_id": "activity456",
                    "workflow_version": "version123",
                    "name": "Notification",
                    "order": "200",
                    "activity_definition": "notification",
                },
            ]
        }
        activities_response.headers = {"X-Total-Count": "2"}
        self._finalize_response(activities_response)

        self.auth_manager.make_request.side_effect = [
            workflow_response,
            version_response,
            activities_response,
        ]

        # Call the function
        params = {
            "workflow_id": "workflow123",
            "include_activities": True,
        }
        result = get_workflow_details(self.server_config, self.auth_manager, params)

        # Verify the result — activities are nested in the response
        self.assertEqual(len(result["activities"]), 2)
        self.assertEqual(result["activity_count"], 2)
        self.assertEqual(result["version_id"], "version123")
        self.assertEqual(result["activities"][0]["sys_id"], "activity123")
        self.assertEqual(result["activities"][1]["sys_id"], "activity456")

    def test_get_workflow_activities_returns_error_when_no_published_version(self):
        """Test latest published version fallback when no versions exist."""
        # First call: workflow details (found)
        workflow_response = MagicMock()
        workflow_response.json.return_value = {
            "result": [{"sys_id": "workflow123", "name": "Test WF"}]
        }
        workflow_response.headers = {"X-Total-Count": "1"}
        self._finalize_response(workflow_response)

        # Second call: version query (empty — no published versions)
        version_response = MagicMock()
        version_response.json.return_value = {"result": []}
        version_response.headers = {"X-Total-Count": "0"}
        self._finalize_response(version_response)

        self.auth_manager.make_request.side_effect = [workflow_response, version_response]

        result = get_workflow_details(
            self.server_config,
            self.auth_manager,
            {"workflow_id": "workflow123", "include_activities": True},
        )

        self.assertIn("activities_error", result)
        self.assertIn("No published versions found", result["activities_error"])

    def test_create_workflow_success(self):
        """Test creating a workflow successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "workflow789",
                "name": "New Workflow",
                "description": "A new workflow",
                "active": "true",
                "table": "incident",
            }
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "name": "New Workflow",
            "description": "A new workflow",
            "table": "incident",
            "active": True,
        }
        result = create_workflow(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["workflow"]["sys_id"], "workflow789")
        self.assertEqual(result["workflow"]["name"], "New Workflow")
        self.assertEqual(result["message"], "Workflow created successfully")

    def test_update_workflow_dry_run(self):
        """dry_run=True returns proposed_changes diff and issues no PATCH."""
        invalidate_query_cache()
        fetch_response = MagicMock()
        fetch_response.json.return_value = {
            "result": [
                {
                    "sys_id": "wf_dry",
                    "name": "Old Name",
                    "active": "true",
                    "description": "old",
                }
            ]
        }
        self._finalize_response(fetch_response)
        self.auth_manager.make_request.return_value = fetch_response

        params = {
            "workflow_id": "wf_dry",
            "name": "New Name",
            "description": "new",
            "dry_run": True,
        }
        result = update_workflow(self.server_config, self.auth_manager, params)

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["operation"], "update")
        self.assertIn("name", result["proposed_changes"])
        self.assertEqual(result["proposed_changes"]["name"]["before"], "Old Name")
        self.assertEqual(result["proposed_changes"]["name"]["after"], "New Name")
        for call in self.auth_manager.make_request.call_args_list:
            self.assertEqual(call.args[0], "GET")

    def test_update_workflow_success(self):
        """Test updating a workflow successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "workflow123",
                "name": "Updated Workflow",
                "description": "Updated description",
                "active": "true",
                "table": "incident",
            }
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "workflow_id": "workflow123",
            "name": "Updated Workflow",
            "description": "Updated description",
        }
        result = update_workflow(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["workflow"]["sys_id"], "workflow123")
        self.assertEqual(result["workflow"]["name"], "Updated Workflow")
        self.assertEqual(result["message"], "Workflow updated successfully")

    def test_activate_workflow_success(self):
        """Test activating a workflow successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "workflow123",
                "name": "Incident Approval",
                "active": "true",
            }
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "workflow_id": "workflow123",
        }
        result = activate_workflow(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["workflow"]["sys_id"], "workflow123")
        self.assertEqual(result["workflow"]["active"], "true")
        self.assertEqual(result["message"], "Workflow activated successfully")

    def test_deactivate_workflow_success(self):
        """Test deactivating a workflow successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "workflow123",
                "name": "Incident Approval",
                "active": "false",
            }
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "workflow_id": "workflow123",
        }
        result = deactivate_workflow(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["workflow"]["sys_id"], "workflow123")
        self.assertEqual(result["workflow"]["active"], "false")
        self.assertEqual(result["message"], "Workflow deactivated successfully")

    def test_add_workflow_activity_success(self):
        """Test adding a workflow activity successfully."""
        # Mock the response for activity creation
        activity_response = MagicMock()
        activity_response.json.return_value = {
            "result": {
                "sys_id": "activity789",
                "workflow_version": "version123",
                "name": "New Activity",
                "order": "200",
                "activity_definition": "approval",
            }
        }
        activity_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = activity_response

        # Call the function -- add_workflow_activity requires workflow_version_id
        params = {
            "workflow_version_id": "version123",
            "name": "New Activity",
            "activity_type": "approval",
            "description": "A new approval activity",
        }
        result = add_workflow_activity(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["activity"]["sys_id"], "activity789")
        self.assertEqual(result["activity"]["name"], "New Activity")
        self.assertEqual(result["message"], "Workflow activity added successfully")

    def test_update_workflow_activity_dry_run_no_op(self):
        """dry_run with identical values flags no-op fields."""
        invalidate_query_cache()
        fetch_response = MagicMock()
        fetch_response.json.return_value = {
            "result": [{"sys_id": "act_dry", "name": "Same", "description": "Same desc"}]
        }
        self._finalize_response(fetch_response)
        self.auth_manager.make_request.return_value = fetch_response

        params = {
            "activity_id": "act_dry",
            "name": "Same",
            "description": "Same desc",
            "dry_run": True,
        }
        result = update_workflow_activity(self.server_config, self.auth_manager, params)

        self.assertTrue(result["dry_run"])
        self.assertIn("name", result["no_op_fields"])
        self.assertIn("description", result["no_op_fields"])
        self.assertEqual(result["proposed_changes"], {})

    def test_update_workflow_activity_success(self):
        """Test updating a workflow activity successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "activity123",
                "name": "Updated Activity",
                "description": "Updated description",
            }
        }
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "activity_id": "activity123",
            "name": "Updated Activity",
            "description": "Updated description",
        }
        result = update_workflow_activity(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["activity"]["sys_id"], "activity123")
        self.assertEqual(result["activity"]["name"], "Updated Activity")
        self.assertEqual(result["message"], "Activity updated successfully")

    def test_delete_workflow_activity_success(self):
        """Test deleting a workflow activity successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "activity_id": "activity123",
        }
        result = delete_workflow_activity(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["message"], "Activity deleted successfully")
        self.assertEqual(result["activity_id"], "activity123")

    def test_delete_workflow_activity_dry_run(self):
        """dry_run=True must return a preview and issue no DELETE."""
        invalidate_query_cache()
        # Target fetch (sn_query_page): return a matching row
        fetch_response = MagicMock()
        fetch_response.json.return_value = {
            "result": [{"sys_id": "activity_dry", "name": "Approve Request"}]
        }
        self._finalize_response(fetch_response)
        self.auth_manager.make_request.return_value = fetch_response

        params = {"activity_id": "activity_dry", "dry_run": True}
        result = delete_workflow_activity(self.server_config, self.auth_manager, params)

        self.assertTrue(result.get("dry_run"))
        self.assertEqual(result["operation"], "delete")
        self.assertEqual(result["target"]["table"], "wf_activity")
        self.assertTrue(result["target_found"])
        self.assertIn("precision_notes", result)
        # No DELETE request was issued — every call was a GET
        for call in self.auth_manager.make_request.call_args_list:
            self.assertEqual(call.args[0], "GET")

    def test_delete_workflow_dry_run_with_dependencies(self):
        """dry_run=True on delete_workflow returns dependency counts."""
        invalidate_query_cache()

        def _mock_request(method, url, **kwargs):
            resp = MagicMock()
            resp.headers = {}
            if "/api/now/stats/" in url:
                # Aggregate API for dependency count
                resp.json.return_value = {"result": {"stats": {"count": "5"}}}
            else:
                # Target fetch
                resp.json.return_value = {"result": [{"sys_id": "wf_dry", "name": "Onboarding"}]}
            resp.content = json.dumps(resp.json.return_value).encode("utf-8")
            resp.raise_for_status = MagicMock()
            return resp

        self.auth_manager.make_request.side_effect = _mock_request

        params = {"workflow_id": "wf_dry", "dry_run": True}
        result = delete_workflow(self.server_config, self.auth_manager, params)

        self.assertTrue(result.get("dry_run"))
        self.assertEqual(result["target"]["table"], "wf_workflow")
        self.assertTrue(result["target_found"])
        self.assertIn("versions", result["dependencies"])
        self.assertIn("activities", result["dependencies"])
        self.assertIn("running_contexts", result["dependencies"])
        self.assertTrue(result["precision_notes"]["dependency_check"])
        # No DELETE request was issued
        for call in self.auth_manager.make_request.call_args_list:
            self.assertEqual(call.args[0], "GET")

    def test_reorder_workflow_activities_success(self):
        """Test reordering workflow activities successfully."""
        # Mock the response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {}}
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        params = {
            "workflow_id": "workflow123",
            "activity_ids": ["activity1", "activity2", "activity3"],
        }
        result = reorder_workflow_activities(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertEqual(result["message"], "Activities reordered")
        self.assertEqual(result["workflow_id"], "workflow123")
        self.assertEqual(len(result["results"]), 3)
        self.assertTrue(all(item["success"] for item in result["results"]))
        self.assertEqual(result["results"][0]["activity_id"], "activity1")
        self.assertEqual(result["results"][0]["new_order"], 100)
        self.assertEqual(result["results"][1]["activity_id"], "activity2")
        self.assertEqual(result["results"][1]["new_order"], 200)
        self.assertEqual(result["results"][2]["activity_id"], "activity3")
        self.assertEqual(result["results"][2]["new_order"], 300)


if __name__ == "__main__":
    unittest.main()
