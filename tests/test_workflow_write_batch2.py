"""Batch-2 workflow write hardening: the live delete path must respect running
contexts (previously only the voluntary dry-run surfaced them), and a partial
reorder failure must not read as success.
"""

import json
from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.workflow_tools import (
    ManageWorkflowParams,
    activate_workflow,
    deactivate_workflow,
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


class TestReorderRefusesInsteadOfPretending:
    """`wf_activity` has no `order` column, so there was never anything to set.

    Measured on a live instance: `order=999999` matches all 786 rows, because
    ServiceNow drops a condition naming a field the table does not have; a PATCH
    setting one is accepted and ignored the same way. The tool sent its PATCHes,
    every one returned 200, and it reported "Activities reordered" having changed
    nothing — with tests for round-trips, parallelism and partial-failure honesty
    all green against a mock that echoed the field back.

    Execution order in a legacy workflow is the wf_transition graph. Until that
    is built, refusing is the only honest answer.
    """

    def _call(self, **over):
        args = {"workflow_id": "wf1", "activity_ids": ["a1", "a2"]}
        args.update(over)
        return reorder_workflow_activities(_config(), MagicMock(spec=AuthManager), args)

    def test_it_refuses_and_names_the_reason(self):
        result = self._call()

        assert result["success"] is False
        assert result["error"] == "REORDER_NOT_SUPPORTED"
        assert "wf_transition" in result["message"]

    def test_it_writes_nothing(self):
        auth = MagicMock(spec=AuthManager)
        reorder_workflow_activities(_config(), auth, {"workflow_id": "wf1", "activity_ids": ["a1"]})
        auth.make_request.assert_not_called()

    def test_a_dry_run_is_refused_too(self):
        # A preview of writes that cannot land is the same false report, one step
        # earlier — it would still print a plan somebody could act on.
        result = self._call(dry_run=True)

        assert result["success"] is False
        assert result["error"] == "REORDER_NOT_SUPPORTED"

    def test_missing_arguments_are_still_reported_first(self):
        assert "Workflow ID" in self._call(workflow_id="")["error"]
        assert "Activity IDs" in self._call(activity_ids=[])["error"]


class TestWorkflowActivationTargetsTheVersion:
    """`wf_workflow` has no `active` column; the live marker is on the VERSION.

    Measured across 51 workflows on a live instance: `wf_workflow_version.published`
    is true on exactly one version per workflow (48) or none (3) — never two.
    `active` on the same table is not that signal; one workflow carried four
    active versions with none published. The old code PATCHed
    `wf_workflow.active`, which does not exist: accepted, dropped, answered 200,
    and reported "Workflow activated successfully".
    """

    def _auth(self, versions, patched=None):
        auth = MagicMock(spec=AuthManager)
        auth.get_headers.return_value = {}
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"result": patched or {"sys_id": "v1", "published": "true"}}
        auth.make_request.return_value = resp
        return auth, versions

    def test_activate_publishes_the_newest_version(self):
        auth, versions = self._auth([{"sys_id": "v2"}, {"sys_id": "v1"}])
        with patch("servicenow_mcp.tools.workflow_tools.sn_query_page", return_value=(versions, 2)):
            result = activate_workflow(_config(), auth, {"workflow_id": "wf1"})

        assert result["success"] is True
        method, url = auth.make_request.call_args[0][:2]
        assert method == "PATCH"
        assert "/wf_workflow_version/v2" in url  # newest first
        assert auth.make_request.call_args.kwargs["json"] == {"published": "true"}

    def test_activate_is_a_no_op_when_a_version_is_already_published(self):
        rows = [{"sys_id": "v1", "published": "true"}]
        auth, _ = self._auth(rows)
        with patch("servicenow_mcp.tools.workflow_tools.sn_query_page", return_value=(rows, 1)):
            result = activate_workflow(_config(), auth, {"workflow_id": "wf1"})

        assert result["success"] is True
        assert result["already_published"] == "v1"
        auth.make_request.assert_not_called()

    def test_deactivate_unpublishes_the_live_version(self):
        rows = [{"sys_id": "v1", "published": "true"}]
        auth, _ = self._auth(rows, patched={"sys_id": "v1", "published": "false"})
        with patch("servicenow_mcp.tools.workflow_tools.sn_query_page", return_value=(rows, 1)):
            result = deactivate_workflow(_config(), auth, {"workflow_id": "wf1"})

        assert result["success"] is True
        assert auth.make_request.call_args.kwargs["json"] == {"published": "false"}

    def test_deactivate_says_so_when_nothing_is_published(self):
        rows = [{"sys_id": "v1", "published": "false"}]
        auth, _ = self._auth(rows)
        with patch("servicenow_mcp.tools.workflow_tools.sn_query_page", return_value=(rows, 1)):
            result = deactivate_workflow(_config(), auth, {"workflow_id": "wf1"})

        assert result["success"] is True
        auth.make_request.assert_not_called()

    def test_two_published_versions_are_refused_rather_than_guessed(self):
        # The invariant says at most one. If an instance breaks it, retiring an
        # arbitrary one of them could take down the wrong workflow version.
        rows = [{"sys_id": "v2", "published": "true"}, {"sys_id": "v1", "published": "true"}]
        auth, _ = self._auth(rows)
        with patch("servicenow_mcp.tools.workflow_tools.sn_query_page", return_value=(rows, 2)):
            result = deactivate_workflow(_config(), auth, {"workflow_id": "wf1"})

        assert result["success"] is False
        assert result["error"] == "AMBIGUOUS_PUBLISHED_VERSION"
        auth.make_request.assert_not_called()

    def test_a_workflow_with_no_versions_is_not_reported_as_activated(self):
        auth, _ = self._auth([])
        with patch("servicenow_mcp.tools.workflow_tools.sn_query_page", return_value=([], 0)):
            result = activate_workflow(_config(), auth, {"workflow_id": "wf1"})

        assert result["success"] is False
        assert result["error"] == "NO_VERSIONS"
        auth.make_request.assert_not_called()
