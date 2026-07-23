"""Tests for manage_scripted_rest (sys_ws_definition / sys_ws_operation)."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.scripted_rest_tools import ManageScriptedRestParams, manage_scripted_rest
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

SVC = "servicenow_mcp.services.scripted_rest"


def _mock_response(result):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"result": result}
    return resp


class TestManageScriptedRest(unittest.TestCase):
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
        return manage_scripted_rest(self.config, self.auth, ManageScriptedRestParams(**kw))

    # --- list ---

    @patch(f"{SVC}.sn_query_page")
    def test_list_happy(self, mock_query):
        mock_query.return_value = (
            [
                {
                    "sys_id": "def1",
                    "name": "My API",
                    "service_id": "my_api",
                    "short_description": "desc",
                    "active": {"display_value": "true"},
                    "sys_scope": {"display_value": "Global"},
                    "sys_updated_on": "2026-01-01 00:00:00",
                }
            ],
            1,
        )
        result = self._run(action="list", query="My", active=True)
        self.assertTrue(result["success"])
        self.assertEqual(1, len(result["services"]))
        self.assertEqual("def1", result["services"][0]["sys_id"])
        self.assertTrue(result["services"][0]["active"])
        self.assertEqual("Global", result["services"][0]["scope"])
        _, kwargs = mock_query.call_args
        self.assertEqual("active=true^nameLIKEMy", kwargs["query"])
        self.assertEqual("sys_ws_definition", kwargs["table"])

    @patch(f"{SVC}.sn_count")
    def test_list_count_only(self, mock_count):
        mock_count.return_value = 7
        result = self._run(action="list", count_only=True, active=True)
        self.assertTrue(result["success"])
        self.assertEqual(7, result["count"])
        mock_count.assert_called_once_with(
            self.config, self.auth, "sys_ws_definition", "active=true"
        )

    # --- get ---

    @patch(f"{SVC}.sn_query_page")
    def test_get_happy_with_resources(self, mock_query):
        # 1st call: resolve service; 2nd call: list operations
        mock_query.side_effect = [
            ([{"sys_id": "def1", "name": "My API", "service_id": "my_api", "active": "true"}], 1),
            (
                [
                    {
                        "sys_id": "op1",
                        "name": "getItem",
                        "http_method": "GET",
                        "relative_path": "/{id}",
                        "operation_uri": "/api/x/my_api/{id}",
                        "active": "true",
                    }
                ],
                1,
            ),
        ]
        result = self._run(action="get", service="My API")
        self.assertTrue(result["success"])
        self.assertEqual("def1", result["service"]["sys_id"])
        self.assertEqual(1, result["resource_count"])
        self.assertEqual("GET", result["resources"][0]["http_method"])

    @patch(f"{SVC}.sn_query_page")
    def test_get_not_found_suggests(self, mock_query):
        mock_query.side_effect = [
            ([], 0),  # resolve miss
            ([{"name": "My API", "sys_id": "def1", "service_id": "my_api"}], 1),  # nameLIKE
        ]
        result = self._run(action="get", service="My AP")
        self.assertFalse(result["success"])
        self.assertIn("did_you_mean", result)
        self.assertEqual("My API", result["did_you_mean"][0]["name"])

    # --- create_service ---

    def test_create_service_happy(self):
        self.auth.make_request.return_value = _mock_response(
            {"sys_id": "def1", "name": "My API", "service_id": "my_api"}
        )
        result = self._run(action="create_service", name="My API", short_description="d")
        self.assertTrue(result["success"])
        self.assertEqual("def1", result["sys_id"])
        args, kwargs = self.auth.make_request.call_args
        self.assertEqual("POST", args[0])
        self.assertTrue(args[1].endswith("/api/now/table/sys_ws_definition"))
        self.assertEqual("My API", kwargs["json"]["name"])
        self.assertEqual("true", kwargs["json"]["active"])

    def test_create_service_error(self):
        self.auth.make_request.side_effect = RuntimeError("boom")
        result = self._run(action="create_service", name="My API")
        self.assertFalse(result["success"])
        self.assertIn("boom", result["message"])

    # --- create_resource ---

    @patch(f"{SVC}.sn_query_page")
    def test_create_resource_happy(self, mock_query):
        mock_query.return_value = ([{"sys_id": "def1", "name": "My API"}], 1)  # parent resolve
        self.auth.make_request.return_value = _mock_response(
            {"sys_id": "op1", "name": "getItem", "http_method": "GET", "operation_uri": "/u"}
        )
        result = self._run(
            action="create_resource",
            service="My API",
            name="getItem",
            http_method="get",
            relative_path="/{id}",
            operation_script="(function(){})();",
        )
        self.assertTrue(result["success"])
        self.assertEqual("op1", result["sys_id"])
        self.assertEqual("def1", result["service_sys_id"])
        _, kwargs = self.auth.make_request.call_args
        body = kwargs["json"]
        self.assertEqual("def1", body["web_service_definition"])
        self.assertEqual("GET", body["http_method"])  # uppercased
        self.assertEqual("/{id}", body["relative_path"])

    @patch(f"{SVC}.sn_query_page")
    def test_create_resource_parent_not_found(self, mock_query):
        mock_query.return_value = ([], 0)
        result = self._run(action="create_resource", service="Nope", name="x", http_method="GET")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])
        self.auth.make_request.assert_not_called()

    # --- update_resource ---

    @patch(f"{SVC}.sn_query_page")
    def test_update_resource_happy(self, mock_query):
        mock_query.return_value = ([{"sys_id": "op1", "name": "getItem"}], 1)
        self.auth.make_request.return_value = _mock_response({"sys_id": "op1", "name": "getItem"})
        result = self._run(
            action="update_resource", resource_id="op1", http_method="post", active=False
        )
        self.assertTrue(result["success"])
        args, kwargs = self.auth.make_request.call_args
        self.assertEqual("PATCH", args[0])
        self.assertEqual("POST", kwargs["json"]["http_method"])
        self.assertEqual("false", kwargs["json"]["active"])

    @patch(f"{SVC}.sn_query_page")
    def test_update_resource_not_found(self, mock_query):
        mock_query.return_value = ([], 0)
        result = self._run(action="update_resource", resource_id="ghost", http_method="GET")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])
        self.auth.make_request.assert_not_called()

    @patch(f"{SVC}.build_update_preview")
    @patch(f"{SVC}.sn_query_page")
    def test_update_resource_dry_run(self, mock_query, mock_preview):
        mock_query.return_value = ([{"sys_id": "op1", "name": "getItem"}], 1)
        mock_preview.return_value = {"dry_run": True, "operation": "update"}
        result = self._run(
            action="update_resource", resource_id="op1", relative_path="/new", dry_run=True
        )
        self.assertTrue(result["dry_run"])
        self.auth.make_request.assert_not_called()
        mock_preview.assert_called_once()

    # --- update_service ---

    @patch(f"{SVC}.sn_query_page")
    def test_update_service_happy(self, mock_query):
        mock_query.return_value = ([{"sys_id": "def1", "name": "My API"}], 1)
        self.auth.make_request.return_value = _mock_response({"sys_id": "def1", "name": "My API"})
        result = self._run(
            action="update_service", service="My API", service_id="renamed", active=True
        )
        self.assertTrue(result["success"])
        _, kwargs = self.auth.make_request.call_args
        self.assertEqual("renamed", kwargs["json"]["service_id"])
        self.assertEqual("true", kwargs["json"]["active"])

    # --- validation ---

    def test_validation_errors(self):
        bad = [
            {"action": "get"},
            {"action": "create_service"},
            {"action": "create_resource", "service": "s", "name": "r"},
            {"action": "update_resource", "resource_id": "x"},
            {"action": "update_service", "service": "s"},
        ]
        for kw in bad:
            with self.assertRaises(ValueError):
                ManageScriptedRestParams(**kw)


if __name__ == "__main__":
    unittest.main()
