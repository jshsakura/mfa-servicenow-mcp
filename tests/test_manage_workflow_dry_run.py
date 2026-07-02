"""dry_run must NEVER be silently swallowed: every manage_workflow action that
advertises dry_run in _FIELDS_BY_ACTION must return a preview and issue no
mutating request when dry_run=True. (Regression: create/activate/deactivate/
reorder_activities/add_activity used to drop the flag and write live.)
"""

import json
from unittest.mock import MagicMock

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.workflow_tools import ManageWorkflowParams, manage_workflow
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

_MUTATING_METHODS = ("POST", "PATCH", "PUT", "DELETE")


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _auth(rows=None):
    """Table API GETs (preview target/current-order lookups) return rows;
    any mutating call would also be captured for the no-write assertion."""
    payload = {"result": rows if rows is not None else []}
    resp = MagicMock()
    resp.json.return_value = payload
    resp.content = json.dumps(payload).encode()
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(return_value=resp)
    auth.get_headers = MagicMock(return_value={})
    return auth


def _assert_no_mutation(auth):
    mutating = [c for c in auth.make_request.call_args_list if c.args[0] in _MUTATING_METHODS]
    assert not mutating, f"dry_run issued mutating calls: {mutating}"


def test_create_dry_run_previews_without_posting():
    auth = _auth()
    result = manage_workflow(
        _config(),
        auth,
        ManageWorkflowParams(action="create", name="My WF", table="incident", dry_run=True),
    )
    assert result["dry_run"] is True
    assert result["operation"] == "create"
    assert result["proposed_record"]["name"] == "My WF"
    _assert_no_mutation(auth)


def test_activate_dry_run_previews_without_patching():
    # NOTE: distinct workflow_id per test — sn_query_page caches identical
    # queries in-process, so sharing an id would leak rows across tests.
    auth = _auth(rows=[{"sys_id": "wf_act1", "name": "My WF", "active": "false"}])
    result = manage_workflow(
        _config(),
        auth,
        ManageWorkflowParams(action="activate", workflow_id="wf_act1", dry_run=True),
    )
    assert result["dry_run"] is True
    assert result["proposed_changes"]["active"]["after"] == "true"
    _assert_no_mutation(auth)


def test_deactivate_dry_run_previews_without_patching():
    auth = _auth(rows=[{"sys_id": "wf_deact1", "name": "My WF", "active": "true"}])
    result = manage_workflow(
        _config(),
        auth,
        ManageWorkflowParams(action="deactivate", workflow_id="wf_deact1", dry_run=True),
    )
    assert result["dry_run"] is True
    assert result["proposed_changes"]["active"]["after"] == "false"
    _assert_no_mutation(auth)


def test_reorder_dry_run_plans_without_patching():
    auth = _auth(
        rows=[
            {"sys_id": "act2", "name": "Second", "order": "200"},
            {"sys_id": "act1", "name": "First", "order": "100"},
        ]
    )
    result = manage_workflow(
        _config(),
        auth,
        ManageWorkflowParams(
            action="reorder_activities",
            workflow_id="wf1",
            activity_ids=["act2", "act1"],
            dry_run=True,
        ),
    )
    assert result["dry_run"] is True
    assert result["planned_updates"][0] == {
        "activity_id": "act2",
        "new_order": 100,
        "name": "Second",
        "current_order": "200",
    }
    _assert_no_mutation(auth)


def test_add_activity_dry_run_previews_without_posting():
    auth = _auth()
    result = manage_workflow(
        _config(),
        auth,
        ManageWorkflowParams(
            action="add_activity",
            workflow_version_id="v1",
            activity_name="Approve",
            activity_type="approval",
            dry_run=True,
        ),
    )
    assert result["dry_run"] is True
    assert result["operation"] == "create"
    assert result["proposed_record"]["workflow_version"] == "v1"
    _assert_no_mutation(auth)
