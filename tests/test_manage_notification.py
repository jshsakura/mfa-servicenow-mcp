"""Tests for manage_notification (sysevent_email_action / sysevent_email_template)."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.notification_tools import ManageNotificationParams, manage_notification
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

SVC = "servicenow_mcp.services.notification"


def _mock_response(result):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"result": result}
    return resp


class TestManageNotification(unittest.TestCase):
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
        return manage_notification(self.config, self.auth, ManageNotificationParams(**kw))

    # --- list ---

    @patch(f"{SVC}.sn_query_page")
    def test_list_happy(self, mock_query):
        mock_query.return_value = (
            [
                {
                    "sys_id": "n1",
                    "subject": "Returned to request",
                    "collection": "x_myapp_alpha",
                    "event_name": "activate.life.cycle.migration",
                    "condition": "stateCHANGESFROM4^stateCHANGESTO3",
                    "category": {"display_value": "Misc"},
                    "template": {"display_value": "returned.to.request YKO OM"},
                    "active": {"display_value": "false"},
                    "weight": "0",
                    "recipient_users": "",
                    "recipient_groups": "",
                    "recipient_fields": "assignment_group,requestor",
                    "message_html": "",
                    "message_text": "",
                    "from": "",
                    "reply_to": "",
                    "sys_scope": {"display_value": "BPM"},
                    "sys_updated_on": "2026-01-01 00:00:00",
                }
            ],
            1,
        )
        result = self._run(action="list", collection="x_myapp_alpha")
        self.assertTrue(result["success"])
        self.assertEqual(1, len(result["notifications"]))
        self.assertEqual("n1", result["notifications"][0]["sys_id"])
        self.assertEqual("Misc", result["notifications"][0]["category"])
        self.assertFalse(result["notifications"][0]["active"])
        _, kwargs = mock_query.call_args
        self.assertEqual("collection=x_myapp_alpha", kwargs["query"])
        self.assertEqual("sysevent_email_action", kwargs["table"])

    @patch("servicenow_mcp.tools.sn_api.sn_count")
    def test_list_count_only(self, mock_count):
        mock_count.return_value = 3
        result = self._run(action="list", active=True, count_only=True)
        self.assertTrue(result["success"])
        self.assertEqual(3, result["count"])
        mock_count.assert_called_once_with(
            self.config, self.auth, "sysevent_email_action", "active=true"
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
    def test_get_not_found(self, mock_query):
        mock_query.return_value = ([], 0)
        result = self._run(action="get", sys_id="ghost")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    # --- create: reference resolution ---

    @patch(f"{SVC}.sn_query_page")
    def test_create_resolves_category_and_template_by_name(self, mock_query):
        mock_query.side_effect = [
            ([{"sys_id": "cat1", "name": "Misc"}], 1),  # category lookup
            ([{"sys_id": "tpl1", "name": "returned.to.request YKO OM"}], 1),  # template lookup
        ]
        self.auth.make_request.return_value = _mock_response(
            {"sys_id": "n1", "subject": "Returned"}
        )
        result = self._run(
            action="create",
            category="Misc",
            template="returned.to.request YKO OM",
            collection="x_myapp_alpha",
            subject="Returned",
        )
        self.assertTrue(result["success"])
        _, kwargs = self.auth.make_request.call_args
        self.assertEqual("cat1", kwargs["json"]["category"])
        self.assertEqual("tpl1", kwargs["json"]["template"])

    @patch(f"{SVC}.sn_query_page")
    def test_create_unresolvable_category_fails_loud(self, mock_query):
        mock_query.return_value = ([], 0)  # category lookup miss
        result = self._run(action="create", category="Nonexistent Category")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])
        self.auth.make_request.assert_not_called()

    @patch(f"{SVC}.sn_query_page")
    def test_create_from_address_maps_to_reserved_field_name(self, mock_query):
        mock_query.return_value = ([{"sys_id": "cat1", "name": "Misc"}], 1)
        self.auth.make_request.return_value = _mock_response({"sys_id": "n1", "subject": "x"})
        result = self._run(action="create", category="Misc", from_address="noreply@example.com")
        self.assertTrue(result["success"])
        _, kwargs = self.auth.make_request.call_args
        self.assertEqual("noreply@example.com", kwargs["json"]["from"])
        self.assertNotIn("from_address", kwargs["json"])

    @patch(f"{SVC}.sn_query_page")
    def test_create_writes_name_and_the_trigger_checkboxes(self, mock_query):
        """The four fields a notification is USELESS without: without them a
        created record has no name and fires on nothing."""
        mock_query.return_value = ([{"sys_id": "cat1", "name": "Misc"}], 1)
        self.auth.make_request.return_value = _mock_response(
            {"sys_id": "n1", "name": "State Changed Return"}
        )
        result = self._run(
            action="create",
            category="Misc",
            name="State Changed Return",
            collection="x_myapp_alpha",
            action_insert=False,
            action_update=True,
            send_self=False,
            active=True,
        )
        self.assertTrue(result["success"])
        _, kwargs = self.auth.make_request.call_args
        body = kwargs["json"]
        self.assertEqual("State Changed Return", body["name"])
        self.assertEqual("false", body["action_insert"])
        self.assertEqual("true", body["action_update"])
        self.assertEqual("false", body["send_self"])
        self.assertEqual("true", body["active"])
        self.assertEqual("State Changed Return", result["name"])

    @patch(f"{SVC}.sn_query_page")
    def test_create_omits_triggers_left_unset(self, mock_query):
        """None means "do not write", not False — an unset checkbox must not
        silently overwrite the platform default."""
        mock_query.return_value = ([{"sys_id": "cat1", "name": "Misc"}], 1)
        self.auth.make_request.return_value = _mock_response({"sys_id": "n1"})
        self._run(action="create", category="Misc", name="Only a name")
        _, kwargs = self.auth.make_request.call_args
        for f in ("action_insert", "action_update", "send_self"):
            self.assertNotIn(f, kwargs["json"])

    @patch(f"{SVC}.sn_query_page")
    def test_get_reports_trigger_state_as_booleans(self, mock_query):
        mock_query.return_value = (
            [
                {
                    "sys_id": "n1",
                    "name": "State Changed Return",
                    "active": "true",
                    "action_insert": "false",
                    "action_update": "true",
                    "send_self": "false",
                }
            ],
            1,
        )
        notif = self._run(action="get", sys_id="n1")["notification"]
        self.assertEqual("State Changed Return", notif["name"])
        self.assertIs(True, notif["action_update"])
        self.assertIs(False, notif["action_insert"])
        self.assertIs(False, notif["send_self"])

    # --- update ---

    @patch(f"{SVC}.sn_query_page")
    def test_update_recipient_fields(self, mock_query):
        mock_query.return_value = ([{"sys_id": "n1", "subject": "S"}], 1)
        self.auth.make_request.return_value = _mock_response({"sys_id": "n1", "subject": "S"})
        result = self._run(
            action="update", sys_id="n1", recipient_fields="assignment_group,requestor"
        )
        self.assertTrue(result["success"])
        _, kwargs = self.auth.make_request.call_args
        self.assertEqual("assignment_group,requestor", kwargs["json"]["recipient_fields"])

    @patch(f"{SVC}.sn_query_page")
    def test_update_not_found(self, mock_query):
        mock_query.return_value = ([], 0)
        result = self._run(action="update", sys_id="ghost", subject="x")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])
        self.auth.make_request.assert_not_called()

    @patch(f"{SVC}.build_update_preview")
    @patch(f"{SVC}.sn_query_page")
    def test_update_dry_run(self, mock_query, mock_preview):
        mock_query.return_value = ([{"sys_id": "n1", "subject": "S"}], 1)
        mock_preview.return_value = {"dry_run": True, "operation": "update"}
        result = self._run(action="update", sys_id="n1", active=False, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.auth.make_request.assert_not_called()
        mock_preview.assert_called_once()

    # --- templates ---

    @patch(f"{SVC}.sn_query_page")
    def test_list_templates_happy(self, mock_query):
        mock_query.return_value = (
            [
                {
                    "sys_id": "tpl1",
                    "name": "returned.to.request YKO OM",
                    "subject": "s",
                    "collection": "",
                    "message_html": "<p>hi</p>",
                    "message_text": "hi",
                    "sys_scope": {"display_value": "BPM"},
                    "sys_updated_on": "2026-01-01 00:00:00",
                }
            ],
            1,
        )
        result = self._run(action="list_templates", query="returned")
        self.assertTrue(result["success"])
        self.assertEqual(1, len(result["templates"]))
        _, kwargs = mock_query.call_args
        self.assertEqual("sysevent_email_template", kwargs["table"])

    def test_create_template_happy(self):
        self.auth.make_request.return_value = _mock_response(
            {"sys_id": "tpl1", "name": "returned.to.request YKO OM"}
        )
        result = self._run(
            action="create_template",
            name="returned.to.request YKO OM",
            subject="${number} returned",
            message_html="<p>hi</p>",
        )
        self.assertTrue(result["success"])
        args, kwargs = self.auth.make_request.call_args
        self.assertEqual("POST", args[0])
        self.assertTrue(args[1].endswith("/api/now/table/sysevent_email_template"))
        self.assertEqual("returned.to.request YKO OM", kwargs["json"]["name"])

    @patch(f"{SVC}.sn_query_page")
    def test_update_template_not_found(self, mock_query):
        mock_query.return_value = ([], 0)
        result = self._run(action="update_template", sys_id="ghost", subject="x")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    # --- validation ---

    def test_validation_errors(self):
        bad = [
            {"action": "get"},
            {"action": "get_template"},
            {"action": "create"},  # no category
            {"action": "create_template"},  # no name
            {"action": "update", "sys_id": "n1"},  # no field to change
            {"action": "update"},  # no sys_id
            {"action": "update_template", "sys_id": "t1"},  # no field to change
        ]
        for kw in bad:
            with self.assertRaises(ValueError):
                ManageNotificationParams(**kw)


if __name__ == "__main__":
    unittest.main()
