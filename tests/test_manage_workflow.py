"""Tests for manage_workflow — Phase 3c bundle."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.workflow_tools import ManageWorkflowParams, manage_workflow
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


class TestValidation:
    def test_create_requires_name(self):
        with pytest.raises(ValidationError, match="name"):
            ManageWorkflowParams(action="create")

    def test_update_requires_workflow_id_and_field(self):
        with pytest.raises(ValidationError, match="workflow_id"):
            ManageWorkflowParams(action="update", name="x")
        with pytest.raises(ValidationError, match="at least one field"):
            ManageWorkflowParams(action="update", workflow_id="abc")

    def test_activate_deactivate_delete_require_id(self):
        for action in ("activate", "deactivate", "delete"):
            with pytest.raises(ValidationError, match="workflow_id"):
                ManageWorkflowParams(action=action)  # type: ignore[arg-type]

    def test_add_activity_requires_version_name_type(self):
        with pytest.raises(ValidationError, match="workflow_version_id"):
            ManageWorkflowParams(action="add_activity", activity_name="x", activity_type="task")
        with pytest.raises(ValidationError, match="activity_name"):
            ManageWorkflowParams(
                action="add_activity",
                workflow_version_id="v1",
                activity_type="task",
            )
        with pytest.raises(ValidationError, match="activity_type"):
            ManageWorkflowParams(action="add_activity", workflow_version_id="v1", activity_name="x")

    def test_update_activity_requires_id_and_field(self):
        with pytest.raises(ValidationError, match="activity_id"):
            ManageWorkflowParams(action="update_activity", activity_name="x")
        with pytest.raises(ValidationError, match="at least one field"):
            ManageWorkflowParams(action="update_activity", activity_id="abc")

    def test_delete_activity_requires_id(self):
        with pytest.raises(ValidationError, match="activity_id"):
            ManageWorkflowParams(action="delete_activity")

    def test_reorder_requires_workflow_id_and_activity_ids(self):
        with pytest.raises(ValidationError, match="workflow_id"):
            ManageWorkflowParams(action="reorder_activities", activity_ids=["a"])
        with pytest.raises(ValidationError, match="activity_ids"):
            ManageWorkflowParams(action="reorder_activities", workflow_id="abc")


class TestDispatch:
    def test_create(self):
        with patch("servicenow_mcp.tools.workflow_tools.create_workflow") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(action="create", name="My WF", table="incident", active=True),
            )
            inner = mock_fn.call_args[0][2]
            assert inner["name"] == "My WF"
            assert inner["table"] == "incident"

    def test_update(self):
        with patch("servicenow_mcp.tools.workflow_tools.update_workflow") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(action="update", workflow_id="abc", active=False),
            )
            inner = mock_fn.call_args[0][2]
            assert inner["workflow_id"] == "abc"
            assert inner["active"] is False

    def test_activate(self):
        with patch("servicenow_mcp.tools.workflow_tools.activate_workflow") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(action="activate", workflow_id="abc"),
            )
            assert mock_fn.call_args[0][2]["workflow_id"] == "abc"

    def test_deactivate(self):
        with patch("servicenow_mcp.tools.workflow_tools.deactivate_workflow") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(action="deactivate", workflow_id="abc"),
            )
            assert mock_fn.call_args[0][2]["workflow_id"] == "abc"

    def test_delete_workflow(self):
        with patch("servicenow_mcp.tools.workflow_tools.delete_workflow") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(action="delete", workflow_id="abc", dry_run=True),
            )
            inner = mock_fn.call_args[0][2]
            assert inner["workflow_id"] == "abc"
            assert inner["dry_run"] is True

    def test_add_activity(self):
        with patch("servicenow_mcp.tools.workflow_tools.add_workflow_activity") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(
                    action="add_activity",
                    workflow_version_id="v1",
                    activity_name="Approval",
                    activity_type="approval",
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner["workflow_version_id"] == "v1"
            assert inner["name"] == "Approval"
            assert inner["activity_type"] == "approval"

    def test_update_activity(self):
        with patch("servicenow_mcp.tools.workflow_tools.update_workflow_activity") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(
                    action="update_activity", activity_id="a1", activity_name="New"
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner["activity_id"] == "a1"
            assert inner["name"] == "New"

    def test_delete_activity(self):
        with patch("servicenow_mcp.tools.workflow_tools.delete_workflow_activity") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(action="delete_activity", activity_id="a1"),
            )
            assert mock_fn.call_args[0][2]["activity_id"] == "a1"

    def test_reorder_activities(self):
        with patch("servicenow_mcp.tools.workflow_tools.reorder_workflow_activities") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(
                _config(),
                MagicMock(),
                ManageWorkflowParams(
                    action="reorder_activities",
                    workflow_id="abc",
                    activity_ids=["a1", "a2", "a3"],
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner["workflow_id"] == "abc"
            assert inner["activity_ids"] == ["a1", "a2", "a3"]

    def test_dispatcher_passes_config_first(self):
        # Regression guard: dispatcher must hand sub-functions (config, auth_manager, dict),
        # matching the post-refactor sub-function signature. Previously the read branches
        # passed (auth_manager, config, ...) which silently broke list/get/list_versions/
        # get_activities because list_workflows etc. unpack the first arg as ServerConfig.
        cfg = _config()
        auth = MagicMock(name="auth")
        with patch("servicenow_mcp.tools.workflow_tools.list_workflows") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_workflow(cfg, auth, ManageWorkflowParams(action="list"))
            assert mock_fn.call_args[0][0] is cfg
            assert mock_fn.call_args[0][1] is auth
            assert isinstance(mock_fn.call_args[0][2], dict)


class TestConfirmGate:
    def test_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._tool_requires_confirmation("manage_workflow") is True
