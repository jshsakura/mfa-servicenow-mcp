"""Batch-2 workflow write hardening: the live delete path must respect running
contexts (previously only the voluntary dry-run surfaced them), and a partial
reorder failure must not read as success.
"""

import json
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.workflow_tools import (
    ManageWorkflowParams,
    delete_workflow,
    manage_workflow,
    reorder_workflow_activities,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _resp(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    resp.content = json.dumps(payload).encode()
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    return resp


def _auth_with_context_count(count):
    def _mr(method, url, **kwargs):
        if "/api/now/stats/" in url:
            return _resp({"result": {"stats": {"count": str(count)}}})
        return _resp({"result": {}})

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    auth.get_headers = MagicMock(return_value={})
    return auth


class TestDeleteWorkflowLiveGuard:
    def test_blocked_when_active_contexts_running(self):
        auth = _auth_with_context_count(3)
        result = delete_workflow(_config(), auth, {"workflow_id": "wf1"})
        assert "delete blocked" in result["error"]
        assert result["active_contexts"] == 3
        assert not any(c.args[0] == "DELETE" for c in auth.make_request.call_args_list)

    def test_force_deletes_despite_running_contexts(self):
        auth = _auth_with_context_count(3)
        result = delete_workflow(_config(), auth, {"workflow_id": "wf1", "force": True})
        assert "deleted successfully" in result["message"]
        assert any(c.args[0] == "DELETE" for c in auth.make_request.call_args_list)

    def test_proceeds_when_no_active_contexts(self):
        auth = _auth_with_context_count(0)
        result = delete_workflow(_config(), auth, {"workflow_id": "wf1"})
        assert "deleted successfully" in result["message"]

    def test_fails_open_when_count_unavailable(self):
        # sn_count swallows its own errors to 0; a raising auth layer must not
        # block the delete either (fail-open, matching guard philosophy).
        def _mr(method, url, **kwargs):
            if "/api/now/stats/" in url:
                raise RuntimeError("stats API down")
            return _resp({"result": {}})

        auth = MagicMock(spec=AuthManager)
        auth.make_request = MagicMock(side_effect=_mr)
        auth.get_headers = MagicMock(return_value={})
        result = delete_workflow(_config(), auth, {"workflow_id": "wf1"})
        assert "deleted successfully" in result["message"]

    def test_dispatcher_forwards_force(self):
        with patch("servicenow_mcp.tools.workflow_tools.delete_workflow") as mock_fn:
            mock_fn.return_value = {"message": "ok"}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(action="delete", workflow_id="wf1", force=True),
            )
            inner = mock_fn.call_args[0][2]
            assert inner["force"] is True


class TestReorderHonesty:
    def _auth_failing_on(self, bad_id):
        def _mr(method, url, **kwargs):
            if bad_id in url:
                raise RuntimeError("PATCH denied")
            return _resp({"result": {}})

        auth = MagicMock(spec=AuthManager)
        auth.make_request = MagicMock(side_effect=_mr)
        auth.get_headers = MagicMock(return_value={})
        return auth

    def test_partial_failure_is_not_reported_as_success(self):
        auth = self._auth_failing_on("act2")
        result = reorder_workflow_activities(
            _config(), auth, {"workflow_id": "wf1", "activity_ids": ["act1", "act2", "act3"]}
        )
        assert result["success"] is False
        assert "INCOMPLETE" in result["message"]
        assert "1 of 3" in result["message"]

    def test_full_success_keeps_plain_message(self):
        auth = self._auth_failing_on("no-such-id")
        result = reorder_workflow_activities(
            _config(), auth, {"workflow_id": "wf1", "activity_ids": ["act1", "act2"]}
        )
        assert result["success"] is True
        assert result["message"] == "Activities reordered"
