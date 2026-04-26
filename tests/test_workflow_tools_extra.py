"""Extra tests for workflow_tools.py — covering missed lines 1118-1154, 1170-1189,
1336, 1338, 1345, 1347."""

import json
from unittest.mock import MagicMock

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.workflow_tools import (
    ManageWorkflowParams,
    get_workflow_activities,
    list_workflow_versions,
    manage_workflow,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _make_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


def _make_auth():
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {"Authorization": "Bearer t"}
    return auth


def _finalize(resp):
    payload = resp.json.return_value
    resp.content = json.dumps(payload).encode("utf-8")
    resp.headers = resp.headers or {}
    resp.raise_for_status = MagicMock()


# ---------------------------------------------------------------------------
# Lines 1118-1154: list_workflow_versions
# ---------------------------------------------------------------------------


class TestListWorkflowVersions:
    def test_success(self):
        config = _make_config()
        auth = _make_auth()

        resp = MagicMock()
        resp.json.return_value = {
            "result": [
                {"sys_id": "v1", "workflow": "wf1", "version": "1", "published": "true"},
                {"sys_id": "v2", "workflow": "wf1", "version": "2", "published": "false"},
            ]
        }
        resp.headers = {"X-Total-Count": "2"}
        _finalize(resp)
        auth.make_request.return_value = resp

        result = list_workflow_versions(auth, config, {"workflow_id": "wf1"})
        assert result["count"] == 2
        assert result["total"] == 2
        assert result["workflow_id"] == "wf1"

    def test_missing_workflow_id(self):
        config = _make_config()
        auth = _make_auth()
        result = list_workflow_versions(auth, config, {})
        assert "error" in result
        assert "required" in result["error"].lower()

    def test_published_only_filter(self):
        config = _make_config()
        auth = _make_auth()

        resp = MagicMock()
        resp.json.return_value = {
            "result": [
                {"sys_id": "v1", "workflow": "wf1", "version": "1", "published": "true"},
            ]
        }
        resp.headers = {"X-Total-Count": "1"}
        _finalize(resp)
        auth.make_request.return_value = resp

        result = list_workflow_versions(
            auth, config, {"workflow_id": "wf1", "published_only": True}
        )
        assert result["count"] == 1
        call_args = auth.make_request.call_args
        query = call_args.kwargs.get("params", {}).get("sysparm_query", "")
        assert "published=true" in query

    def test_query_error(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.side_effect = RuntimeError("network error")

        result = list_workflow_versions(auth, config, {"workflow_id": "wf1"})
        assert "error" in result

    def test_with_custom_limit_and_offset(self):
        config = _make_config()
        auth = _make_auth()

        resp = MagicMock()
        resp.json.return_value = {"result": []}
        resp.headers = {"X-Total-Count": "0"}
        _finalize(resp)
        auth.make_request.return_value = resp

        result = list_workflow_versions(
            auth, config, {"workflow_id": "wf1", "limit": 5, "offset": 10}
        )
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# Lines 1170-1189: get_workflow_activities
# ---------------------------------------------------------------------------


class TestGetWorkflowActivities:
    def test_missing_workflow_id(self):
        config = _make_config()
        auth = _make_auth()
        result = get_workflow_activities(auth, config, {})
        assert "error" in result
        assert "required" in result["error"].lower()

    def test_success_with_version_id(self):
        config = _make_config()
        auth = _make_auth()

        activities_resp = MagicMock()
        activities_resp.json.return_value = {
            "result": [
                {"sys_id": "a1", "name": "Approval", "order": "100"},
            ]
        }
        activities_resp.headers = {"X-Total-Count": "1"}
        _finalize(activities_resp)

        version_resp = MagicMock()
        version_resp.json.return_value = {"result": [{"sys_id": "v1", "published": "true"}]}
        version_resp.headers = {"X-Total-Count": "1"}
        _finalize(version_resp)

        auth.make_request.side_effect = [version_resp, activities_resp]

        result = get_workflow_activities(auth, config, {"workflow_id": "wf1", "version_id": "v1"})
        assert result["workflow_id"] == "wf1"

    def test_query_error(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.side_effect = RuntimeError("network error")

        result = get_workflow_activities(auth, config, {"workflow_id": "wf1"})
        assert "error" in result


# ---------------------------------------------------------------------------
# Lines 1336, 1338, 1345, 1347: manage_workflow add_activity/update_activity
# with optional description and attributes
# ---------------------------------------------------------------------------


class TestManageWorkflowOptionalFields:
    def test_add_activity_with_description_and_attributes(self):
        config = _make_config()
        auth = _make_auth()

        resp = MagicMock()
        resp.json.return_value = {
            "result": {
                "sys_id": "act1",
                "name": "MyActivity",
                "workflow_version": "v1",
            }
        }
        resp.headers = {"X-Total-Count": "1"}
        _finalize(resp)
        auth.make_request.return_value = resp

        result = manage_workflow(
            config,
            auth,
            ManageWorkflowParams(
                action="add_activity",
                workflow_version_id="v1",
                activity_name="MyActivity",
                activity_type="approval",
                activity_description="Approve the change",
                attributes={"approver": "manager"},
                confirm="approve",
            ),
        )
        assert result["activity"]["sys_id"] == "act1"

    def test_add_activity_without_optional_fields(self):
        config = _make_config()
        auth = _make_auth()

        resp = MagicMock()
        resp.json.return_value = {
            "result": {
                "sys_id": "act2",
                "name": "MinimalActivity",
                "workflow_version": "v1",
            }
        }
        resp.headers = {"X-Total-Count": "1"}
        _finalize(resp)
        auth.make_request.return_value = resp

        result = manage_workflow(
            config,
            auth,
            ManageWorkflowParams(
                action="add_activity",
                workflow_version_id="v1",
                activity_name="MinimalActivity",
                activity_type="notification",
                confirm="approve",
            ),
        )
        assert result["activity"]["sys_id"] == "act2"

    def test_update_activity_with_description_and_attributes(self):
        config = _make_config()
        auth = _make_auth()

        resp = MagicMock()
        resp.json.return_value = {
            "result": {
                "sys_id": "act1",
                "name": "UpdatedActivity",
            }
        }
        resp.headers = {"X-Total-Count": "1"}
        _finalize(resp)
        auth.make_request.return_value = resp

        result = manage_workflow(
            config,
            auth,
            ManageWorkflowParams(
                action="update_activity",
                activity_id="act1",
                activity_name="UpdatedActivity",
                activity_description="New description",
                attributes={"timeout": "30"},
                confirm="approve",
            ),
        )
        assert result["activity"]["name"] == "UpdatedActivity"

    def test_update_activity_without_optional_fields(self):
        config = _make_config()
        auth = _make_auth()

        resp = MagicMock()
        resp.json.return_value = {
            "result": {
                "sys_id": "act1",
                "name": "Renamed",
            }
        }
        resp.headers = {"X-Total-Count": "1"}
        _finalize(resp)
        auth.make_request.return_value = resp

        result = manage_workflow(
            config,
            auth,
            ManageWorkflowParams(
                action="update_activity",
                activity_id="act1",
                activity_name="Renamed",
                confirm="approve",
            ),
        )
        assert result["activity"]["name"] == "Renamed"
