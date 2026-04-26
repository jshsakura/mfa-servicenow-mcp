"""Tests for manage_changeset — Phase 3a bundle."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.changeset_tools import ManageChangesetParams, manage_changeset
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


# ---------------------------------------------------------------------------
# Per-action validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_create_requires_name_and_application(self):
        with pytest.raises(ValidationError, match="name"):
            ManageChangesetParams(action="create", application="app1")
        with pytest.raises(ValidationError, match="application"):
            ManageChangesetParams(action="create", name="my changeset")

    def test_update_requires_changeset_id(self):
        with pytest.raises(ValidationError, match="changeset_id"):
            ManageChangesetParams(action="update", state="2")

    def test_update_requires_at_least_one_field(self):
        with pytest.raises(ValidationError, match="at least one field"):
            ManageChangesetParams(action="update", changeset_id="abc")

    def test_commit_requires_changeset_id(self):
        with pytest.raises(ValidationError, match="changeset_id"):
            ManageChangesetParams(action="commit")

    def test_publish_requires_changeset_id(self):
        with pytest.raises(ValidationError, match="changeset_id"):
            ManageChangesetParams(action="publish")

    def test_add_file_requires_changeset_id_and_path_and_content(self):
        with pytest.raises(ValidationError, match="changeset_id"):
            ManageChangesetParams(action="add_file", file_path="x.js", file_content="...")
        with pytest.raises(ValidationError, match="file_path"):
            ManageChangesetParams(action="add_file", changeset_id="abc", file_content="...")
        with pytest.raises(ValidationError, match="file_content"):
            ManageChangesetParams(action="add_file", changeset_id="abc", file_path="x.js")

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            ManageChangesetParams(action="archive")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Dispatch — manage_changeset routes to the service layer
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_create_dispatches(self):
        with patch("servicenow_mcp.services.changeset.create") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_changeset(
                _config(),
                MagicMock(),
                ManageChangesetParams(
                    action="create", name="my cs", application="app1", description="d"
                ),
            )
            assert mock_fn.call_args.kwargs["name"] == "my cs"
            assert mock_fn.call_args.kwargs["application"] == "app1"
            assert mock_fn.call_args.kwargs["description"] == "d"

    def test_update_dispatches(self):
        with patch("servicenow_mcp.services.changeset.update") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_changeset(
                _config(),
                MagicMock(),
                ManageChangesetParams(action="update", changeset_id="abc", state="in progress"),
            )
            assert mock_fn.call_args.kwargs["changeset_id"] == "abc"
            assert mock_fn.call_args.kwargs["state"] == "in progress"

    def test_commit_dispatches(self):
        with patch("servicenow_mcp.services.changeset.commit") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_changeset(
                _config(),
                MagicMock(),
                ManageChangesetParams(action="commit", changeset_id="abc", commit_message="ship"),
            )
            assert mock_fn.call_args.kwargs["changeset_id"] == "abc"
            assert mock_fn.call_args.kwargs["commit_message"] == "ship"

    def test_publish_dispatches(self):
        with patch("servicenow_mcp.services.changeset.publish") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_changeset(
                _config(),
                MagicMock(),
                ManageChangesetParams(
                    action="publish", changeset_id="abc", publish_notes="release v1"
                ),
            )
            assert mock_fn.call_args.kwargs["changeset_id"] == "abc"
            assert mock_fn.call_args.kwargs["publish_notes"] == "release v1"

    def test_add_file_dispatches(self):
        with patch("servicenow_mcp.services.changeset.add_file") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_changeset(
                _config(),
                MagicMock(),
                ManageChangesetParams(
                    action="add_file",
                    changeset_id="abc",
                    file_path="x.js",
                    file_content="content",
                ),
            )
            assert mock_fn.call_args.kwargs["changeset_id"] == "abc"
            assert mock_fn.call_args.kwargs["file_path"] == "x.js"
            assert mock_fn.call_args.kwargs["file_content"] == "content"


# ---------------------------------------------------------------------------
# Confirm gate
# ---------------------------------------------------------------------------


class TestConfirmGate:
    def test_manage_changeset_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._tool_requires_confirmation("manage_changeset") is True
