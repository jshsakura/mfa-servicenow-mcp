import json
import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.incident_tools import (
    AddCommentParams,
    CreateIncidentParams,
    GetIncidentByNumberParams,
    IncidentResponse,
    ListIncidentsParams,
    ResolveIncidentParams,
    UpdateIncidentParams,
    _resolve_incident_sys_id,
    add_comment,
    create_incident,
    get_incident_by_number,
    list_incidents,
    resolve_incident,
    update_incident,
)
from servicenow_mcp.utils.config import ServerConfig


class TestIncidentTools(unittest.TestCase):
    def setUp(self):
        self.config = MagicMock(spec=ServerConfig)
        self.config.api_url = "https://test.service-now.com/api/now"
        self.config.instance_url = "https://test.service-now.com"
        self.config.timeout = 30
        self.config.request_timeout = (10, 30)
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {"Content-Type": "application/json"}

    def _mock_response(self, json_body, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_body
        resp.raise_for_status = MagicMock()
        resp.content = json.dumps(json_body).encode("utf-8")
        return resp

    # --- list_incidents ---

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_list_incidents_basic(self, mock_query_page):
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "abc123",
                    "number": "INC001",
                    "short_description": "Test",
                    "description": "Desc",
                    "state": "New",
                    "priority": "1",
                    "assigned_to": "John Doe",
                    "category": "Software",
                    "subcategory": "Email",
                    "sys_created_on": "2025-01-01",
                    "sys_updated_on": "2025-01-02",
                }
            ],
            1,
        )
        params = ListIncidentsParams()
        result = list_incidents(self.config, self.auth_manager, params)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["incidents"]), 1)
        self.assertEqual(result["incidents"][0]["number"], "INC001")
        mock_query_page.assert_called_once_with(
            self.config,
            self.auth_manager,
            table="incident",
            query="",
            fields="sys_id,number,short_description,description,state,priority,assigned_to,category,subcategory,sys_created_on,sys_updated_on",
            limit=10,
            offset=0,
            display_value=True,
            fail_silently=False,
        )

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_list_incidents_with_filters(self, mock_query_page):
        mock_query_page.return_value = ([], 0)
        params = ListIncidentsParams(
            state="1", category="Software", assigned_to="admin", query="error"
        )
        result = list_incidents(self.config, self.auth_manager, params)
        self.assertTrue(result["success"])
        expected_query = (
            "state=1^assigned_to=admin^category=Software"
            "^short_descriptionLIKEerror^ORdescriptionLIKEerror"
        )
        mock_query_page.assert_called_once_with(
            self.config,
            self.auth_manager,
            table="incident",
            query=expected_query,
            fields="sys_id,number,short_description,description,state,priority,assigned_to,category,subcategory,sys_created_on,sys_updated_on",
            limit=10,
            offset=0,
            display_value=True,
            fail_silently=False,
        )

    @patch("servicenow_mcp.tools.incident_tools.sn_count")
    def test_list_incidents_count_only(self, mock_count):
        mock_count.return_value = 42
        params = ListIncidentsParams(count_only=True, state="1")
        result = list_incidents(self.config, self.auth_manager, params)
        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 42)
        mock_count.assert_called_once_with(self.config, self.auth_manager, "incident", "state=1")

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_list_incidents_empty(self, mock_query_page):
        mock_query_page.return_value = ([], 0)
        params = ListIncidentsParams()
        result = list_incidents(self.config, self.auth_manager, params)
        self.assertTrue(result["success"])
        self.assertEqual(result["incidents"], [])
        self.assertEqual(result["message"], "Found 0 incidents")

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_list_incidents_error(self, mock_query_page):
        mock_query_page.side_effect = Exception("Network error")
        params = ListIncidentsParams()
        result = list_incidents(self.config, self.auth_manager, params)
        self.assertFalse(result["success"])
        self.assertIn("Network error", result["message"])
        self.assertEqual(result["incidents"], [])

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_list_incidents_assigned_to_dict(self, mock_query_page):
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "abc123",
                    "number": "INC002",
                    "short_description": "Test",
                    "description": "",
                    "state": "New",
                    "priority": "2",
                    "assigned_to": {"display_value": "Jane Doe", "value": "sys123"},
                    "category": "Hardware",
                    "subcategory": None,
                    "sys_created_on": "2025-01-01",
                    "sys_updated_on": "2025-01-01",
                }
            ],
            1,
        )
        params = ListIncidentsParams()
        result = list_incidents(self.config, self.auth_manager, params)
        self.assertTrue(result["success"])
        self.assertEqual(result["incidents"][0]["assigned_to"], "Jane Doe")

    # --- get_incident_by_number ---

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_get_incident_by_number_found(self, mock_query_page):
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "abc123",
                    "number": "INC0010001",
                    "short_description": "Test incident",
                    "description": "Details",
                    "state": "New",
                    "priority": "1 - Critical",
                    "assigned_to": "John Doe",
                    "category": "Software",
                    "subcategory": "Email",
                    "sys_created_on": "2025-06-25 10:00:00",
                    "sys_updated_on": "2025-06-25 10:00:00",
                }
            ],
            1,
        )
        params = GetIncidentByNumberParams(incident_number="INC0010001")
        result = get_incident_by_number(self.config, self.auth_manager, params)
        self.assertTrue(result["success"])
        self.assertEqual(result["incident"]["number"], "INC0010001")
        mock_query_page.assert_called_once_with(
            self.config,
            self.auth_manager,
            table="incident",
            query="number=INC0010001",
            fields="",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_get_incident_by_number_not_found(self, mock_query_page):
        mock_query_page.return_value = ([], 0)
        params = GetIncidentByNumberParams(incident_number="INC9999999")
        result = get_incident_by_number(self.config, self.auth_manager, params)
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Incident not found: INC9999999")

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_get_incident_by_number_error(self, mock_query_page):
        mock_query_page.side_effect = Exception("Timeout")
        params = GetIncidentByNumberParams(incident_number="INC001")
        result = get_incident_by_number(self.config, self.auth_manager, params)
        self.assertFalse(result["success"])
        self.assertIn("Timeout", result["message"])

    @patch("servicenow_mcp.tools.incident_tools.sn_query_page")
    def test_get_incident_by_number_assigned_to_dict(self, mock_query_page):
        mock_query_page.return_value = (
            [
                {
                    "sys_id": "abc123",
                    "number": "INC001",
                    "short_description": "Test",
                    "description": "",
                    "state": "New",
                    "priority": "2",
                    "assigned_to": {"display_value": "Jane Doe", "value": "xyz"},
                    "category": "Software",
                    "subcategory": None,
                    "sys_created_on": "2025-01-01",
                    "sys_updated_on": "2025-01-01",
                }
            ],
            1,
        )
        params = GetIncidentByNumberParams(incident_number="INC001")
        result = get_incident_by_number(self.config, self.auth_manager, params)
        self.assertTrue(result["success"])
        self.assertEqual(result["incident"]["assigned_to"], "Jane Doe")

    # --- create_incident ---

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_create_incident_success(self, mock_invalidate):
        mock_response = self._mock_response({"result": {"sys_id": "new123", "number": "INC0099"}})
        self.auth_manager.make_request.return_value = mock_response
        params = CreateIncidentParams(short_description="Test incident")
        result = create_incident(self.config, self.auth_manager, params)
        self.assertTrue(result.success)
        self.assertEqual(result.incident_id, "new123")
        self.assertEqual(result.incident_number, "INC0099")
        self.auth_manager.make_request.assert_called_once_with(
            "POST",
            f"{self.config.api_url}/table/incident",
            json={"short_description": "Test incident"},
            headers=self.auth_manager.get_headers.return_value,
            timeout=self.config.timeout,
        )
        mock_invalidate.assert_called_once_with(table="incident")

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_create_incident_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Server error")
        params = CreateIncidentParams(short_description="Test")
        result = create_incident(self.config, self.auth_manager, params)
        self.assertFalse(result.success)
        self.assertIn("Server error", result.message)
        mock_invalidate.assert_not_called()

    # --- update_incident ---

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_update_incident_success(self, mock_invalidate):
        resolve_response = self._mock_response({"result": [{"sys_id": "sys123"}]})
        update_response = self._mock_response({"result": {"sys_id": "sys123", "number": "INC001"}})
        self.auth_manager.make_request.side_effect = [
            resolve_response,
            update_response,
        ]
        params = UpdateIncidentParams(incident_id="INC001", short_description="Updated")
        result = update_incident(self.config, self.auth_manager, params)
        self.assertTrue(result.success)
        self.assertEqual(result.incident_number, "INC001")
        mock_invalidate.assert_called_once_with(table="incident")

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_update_incident_not_found(self, mock_invalidate):
        resolve_response = self._mock_response({"result": []})
        self.auth_manager.make_request.return_value = resolve_response
        params = UpdateIncidentParams(incident_id="INC999", short_description="Updated")
        result = update_incident(self.config, self.auth_manager, params)
        self.assertFalse(result.success)
        self.assertIn("not found", result.message)
        mock_invalidate.assert_not_called()

    # --- resolve_incident ---

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_resolve_incident_success(self, mock_invalidate):
        resolve_response = self._mock_response({"result": [{"sys_id": "sys123"}]})
        put_response = self._mock_response({"result": {"sys_id": "sys123", "number": "INC001"}})
        self.auth_manager.make_request.side_effect = [
            resolve_response,
            put_response,
        ]
        params = ResolveIncidentParams(
            incident_id="sys123",
            resolution_code="Solved (Permanently)",
            resolution_notes="Fixed",
        )
        result = resolve_incident(self.config, self.auth_manager, params)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Incident resolved successfully")
        mock_invalidate.assert_called_once_with(table="incident")
        put_call_args = self.auth_manager.make_request.call_args_list[1]
        self.assertEqual(put_call_args[1]["json"]["state"], "6")
        self.assertEqual(put_call_args[1]["json"]["close_code"], "Solved (Permanently)")
        self.assertEqual(put_call_args[1]["json"]["close_notes"], "Fixed")

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_resolve_incident_not_found(self, mock_invalidate):
        resolve_response = self._mock_response({"result": []})
        self.auth_manager.make_request.return_value = resolve_response
        params = ResolveIncidentParams(
            incident_id="INC999",
            resolution_code="Solved",
            resolution_notes="Fixed",
        )
        result = resolve_incident(self.config, self.auth_manager, params)
        self.assertFalse(result.success)
        mock_invalidate.assert_not_called()

    # --- add_comment ---

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_add_comment_success(self, mock_invalidate):
        resolve_response = self._mock_response({"result": [{"sys_id": "sys123"}]})
        put_response = self._mock_response({"result": {"sys_id": "sys123", "number": "INC001"}})
        self.auth_manager.make_request.side_effect = [
            resolve_response,
            put_response,
        ]
        params = AddCommentParams(incident_id="INC001", comment="Hello world")
        result = add_comment(self.config, self.auth_manager, params)
        self.assertTrue(result.success)
        put_call_args = self.auth_manager.make_request.call_args_list[1]
        self.assertEqual(put_call_args[1]["json"], {"comments": "Hello world"})
        mock_invalidate.assert_called_once_with(table="incident")

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_add_comment_work_note(self, mock_invalidate):
        resolve_response = self._mock_response({"result": [{"sys_id": "sys123"}]})
        put_response = self._mock_response({"result": {"sys_id": "sys123", "number": "INC001"}})
        self.auth_manager.make_request.side_effect = [
            resolve_response,
            put_response,
        ]
        params = AddCommentParams(incident_id="INC001", comment="Internal note", is_work_note=True)
        result = add_comment(self.config, self.auth_manager, params)
        self.assertTrue(result.success)
        put_call_args = self.auth_manager.make_request.call_args_list[1]
        self.assertEqual(put_call_args[1]["json"], {"work_notes": "Internal note"})
        mock_invalidate.assert_called_once_with(table="incident")

    # --- _resolve_incident_sys_id ---

    def test_resolve_incident_sys_id_direct(self):
        sys_id = "a" * 32
        result, err = _resolve_incident_sys_id(self.config, self.auth_manager, sys_id)
        self.assertEqual(result, sys_id)
        self.assertIsNone(err)
        self.auth_manager.make_request.assert_not_called()

    def test_resolve_incident_by_number(self):
        mock_response = self._mock_response({"result": [{"sys_id": "resolved123"}]})
        self.auth_manager.make_request.return_value = mock_response
        result, err = _resolve_incident_sys_id(self.config, self.auth_manager, "INC001")
        self.assertEqual(result, "resolved123")
        self.assertIsNone(err)

    def test_resolve_sys_id_not_found(self):
        mock_response = self._mock_response({"result": []})
        self.auth_manager.make_request.return_value = mock_response
        result, err = _resolve_incident_sys_id(self.config, self.auth_manager, "INC999")
        self.assertIsNone(result)
        self.assertIsNotNone(err)
        self.assertFalse(err.success)

    def test_resolve_incident_error(self):
        self.auth_manager.make_request.side_effect = Exception("Timeout")
        result, err = _resolve_incident_sys_id(self.config, self.auth_manager, "INC001")
        self.assertIsNone(result)
        self.assertIsNotNone(err)
        self.assertIn("Timeout", err.message)

    # --- invalidation after write ---

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_invalidation_after_create(self, mock_invalidate):
        mock_response = self._mock_response({"result": {"sys_id": "new123", "number": "INC001"}})
        self.auth_manager.make_request.return_value = mock_response
        params = CreateIncidentParams(short_description="Test")
        create_incident(self.config, self.auth_manager, params)
        mock_invalidate.assert_called_once_with(table="incident")

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_invalidation_after_update(self, mock_invalidate):
        resolve_resp = self._mock_response({"result": [{"sys_id": "abc"}]})
        update_resp = self._mock_response({"result": {"sys_id": "abc", "number": "INC001"}})
        self.auth_manager.make_request.side_effect = [resolve_resp, update_resp]
        params = UpdateIncidentParams(incident_id="abc" + "0" * 29, short_description="Updated")
        update_incident(self.config, self.auth_manager, params)
        mock_invalidate.assert_called_once_with(table="incident")

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_invalidation_after_resolve(self, mock_invalidate):
        resolve_resp = self._mock_response({"result": [{"sys_id": "abc"}]})
        put_resp = self._mock_response({"result": {"sys_id": "abc", "number": "INC001"}})
        self.auth_manager.make_request.side_effect = [resolve_resp, put_resp]
        params = ResolveIncidentParams(
            incident_id="abc" + "0" * 29,
            resolution_code="Solved",
            resolution_notes="Done",
        )
        resolve_incident(self.config, self.auth_manager, params)
        mock_invalidate.assert_called_once_with(table="incident")

    @patch("servicenow_mcp.tools.incident_tools.invalidate_query_cache")
    def test_invalidation_after_add_comment(self, mock_invalidate):
        resolve_resp = self._mock_response({"result": [{"sys_id": "abc"}]})
        put_resp = self._mock_response({"result": {"sys_id": "abc", "number": "INC001"}})
        self.auth_manager.make_request.side_effect = [resolve_resp, put_resp]
        params = AddCommentParams(incident_id="abc" + "0" * 29, comment="Note")
        add_comment(self.config, self.auth_manager, params)
        mock_invalidate.assert_called_once_with(table="incident")


if __name__ == "__main__":
    unittest.main()
