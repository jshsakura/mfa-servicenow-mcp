"""Unit tests for the ui_policy service module."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.services import ui_policy as svc
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _auth():
    m = MagicMock()
    m.get_headers.return_value = {"Authorization": "Basic xxx"}
    return m


def _resp(payload, status=200):
    r = MagicMock()
    r.json.return_value = payload
    r.status_code = status
    r.raise_for_status = MagicMock()
    return r


class TestCreate(unittest.TestCase):
    @patch("servicenow_mcp.services.ui_policy.invalidate_query_cache")
    def test_happy_path(self, mock_inv):
        auth = _auth()
        auth.make_request.return_value = _resp(
            {"result": {"sys_id": "p1", "short_description": "SD"}}
        )
        result = svc.create(
            _config(),
            auth,
            table="incident",
            short_description="SD",
            conditions="state=6",
            reverse_if_false=True,
            on_load=True,
            active=True,
            global_policy=True,
            order=200,
            view_name="default",
            script_true="alert('true')",
            script_false="alert('false')",
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["ui_policy_id"], "p1")
        mock_inv.assert_called_once_with(table="sys_ui_policy")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["table"], "incident")
        self.assertEqual(body["short_description"], "SD")
        self.assertEqual(body["conditions"], "state=6")
        self.assertEqual(body["reverse_if_false"], "true")
        self.assertEqual(body["on_load"], "true")
        self.assertEqual(body["order"], "200")
        self.assertEqual(body["view"], "default")
        self.assertEqual(body["script_true"], "alert('true')")
        self.assertEqual(body["script_false"], "alert('false')")

    @patch("servicenow_mcp.services.ui_policy.invalidate_query_cache")
    def test_error(self, mock_inv):
        auth = _auth()
        auth.make_request.side_effect = Exception("fail")
        result = svc.create(_config(), auth, table="i", short_description="s")
        self.assertFalse(result["success"])


class TestAddAction(unittest.TestCase):
    @patch("servicenow_mcp.services.ui_policy.sn_query_page")
    @patch("servicenow_mcp.services.ui_policy.invalidate_query_cache")
    def test_happy_path(self, mock_inv, mock_qp):
        mock_qp.return_value = ([{"sys_id": "p1", "table": "incident"}], 1)
        auth = _auth()
        auth.make_request.return_value = _resp({"result": {"sys_id": "a1"}})
        result = svc.add_action(
            _config(),
            auth,
            ui_policy="p1",
            field="priority",
            mandatory="true",
            visible="false",
            disabled="true",
            cleared="false",
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["action_id"], "a1")
        mock_inv.assert_called_once_with(table="sys_ui_policy_action")
        body = auth.make_request.call_args[1]["json"]
        self.assertEqual(body["ui_policy"], "p1")
        self.assertEqual(body["field"], "priority")
        self.assertEqual(body["mandatory"], "true")
        self.assertEqual(body["visible"], "false")
        self.assertEqual(body["disabled"], "true")
        self.assertEqual(body["cleared"], "false")

    @patch("servicenow_mcp.services.ui_policy.sn_query_page")
    def test_policy_not_found(self, mock_qp):
        mock_qp.return_value = ([], 0)
        result = svc.add_action(_config(), _auth(), ui_policy="missing", field="f")
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    @patch("servicenow_mcp.services.ui_policy.sn_query_page")
    def test_verify_error(self, mock_qp):
        mock_qp.side_effect = Exception("query fail")
        result = svc.add_action(_config(), _auth(), ui_policy="p1", field="f")
        self.assertFalse(result["success"])

    @patch("servicenow_mcp.services.ui_policy.sn_query_page")
    def test_post_error(self, mock_qp):
        mock_qp.return_value = ([{"sys_id": "p1", "table": "i"}], 1)
        auth = _auth()
        auth.make_request.side_effect = Exception("post fail")
        result = svc.add_action(_config(), auth, ui_policy="p1", field="f")
        self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
