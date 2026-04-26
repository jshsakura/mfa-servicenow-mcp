"""Tests for manage_change and manage_kb_article — Phase 2 bundles."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change
from servicenow_mcp.tools.knowledge_base import (
    ArticleResponse,
    ManageKbArticleParams,
    manage_kb_article,
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


# ---------------------------------------------------------------------------
# manage_change validation + dispatch
# ---------------------------------------------------------------------------


class TestManageChangeValidation:
    def test_create_requires_short_description_and_type(self):
        with pytest.raises(ValidationError, match="short_description"):
            ManageChangeParams(action="create", type="normal")
        with pytest.raises(ValidationError, match="type is required"):
            ManageChangeParams(action="create", short_description="x")

    def test_create_type_must_be_in_enum(self):
        with pytest.raises(ValidationError):
            ManageChangeParams(
                action="create",
                short_description="x",
                type="hotfix",  # type: ignore[arg-type]
            )

    def test_update_requires_change_id(self):
        with pytest.raises(ValidationError, match="change_id"):
            ManageChangeParams(action="update", state="2")

    def test_update_requires_field(self):
        with pytest.raises(ValidationError, match="at least one field"):
            ManageChangeParams(action="update", change_id="abc")

    def test_add_task_requires_change_id_and_task_short_description(self):
        with pytest.raises(ValidationError, match="change_id"):
            ManageChangeParams(action="add_task", task_short_description="t")
        with pytest.raises(ValidationError, match="task_short_description"):
            ManageChangeParams(action="add_task", change_id="abc")


class TestManageChangeDispatch:
    def test_create_dispatches(self):
        with patch("servicenow_mcp.services.change.create") as mock_create:
            mock_create.return_value = {"success": True}
            manage_change(
                _config(),
                MagicMock(),
                ManageChangeParams(
                    action="create",
                    short_description="rebuild db",
                    type="normal",
                    risk="low",
                ),
            )
            kwargs = mock_create.call_args.kwargs
            assert kwargs["short_description"] == "rebuild db"
            assert kwargs["type"] == "normal"
            assert kwargs["risk"] == "low"

    def test_update_dispatches(self):
        with patch("servicenow_mcp.services.change.update") as mock_update:
            mock_update.return_value = {"success": True}
            manage_change(
                _config(),
                MagicMock(),
                ManageChangeParams(action="update", change_id="abc", state="2", risk="medium"),
            )
            kwargs = mock_update.call_args.kwargs
            assert kwargs["change_id"] == "abc"
            assert kwargs["state"] == "2"
            assert kwargs["risk"] == "medium"

    def test_add_task_dispatches(self):
        with patch("servicenow_mcp.services.change.add_task") as mock_add:
            mock_add.return_value = {"success": True}
            manage_change(
                _config(),
                MagicMock(),
                ManageChangeParams(
                    action="add_task",
                    change_id="abc",
                    task_short_description="patch db",
                    task_assigned_to="user1",
                ),
            )
            kwargs = mock_add.call_args.kwargs
            assert kwargs["change_id"] == "abc"
            assert kwargs["short_description"] == "patch db"
            assert kwargs["assigned_to"] == "user1"


# ---------------------------------------------------------------------------
# manage_kb_article validation + dispatch
# ---------------------------------------------------------------------------


class TestManageKbArticleValidation:
    def test_create_requires_all_mandatory_fields(self):
        with pytest.raises(ValidationError, match="action='create' requires"):
            ManageKbArticleParams(action="create", title="t")

    def test_update_requires_article_id(self):
        with pytest.raises(ValidationError, match="article_id"):
            ManageKbArticleParams(action="update", title="t")

    def test_update_requires_field(self):
        with pytest.raises(ValidationError, match="at least one field"):
            ManageKbArticleParams(action="update", article_id="abc")

    def test_publish_requires_article_id(self):
        with pytest.raises(ValidationError, match="article_id"):
            ManageKbArticleParams(action="publish")


class TestManageKbArticleDispatch:
    def test_create_dispatches(self):
        with patch("servicenow_mcp.services.kb_article.create") as mock_create:
            mock_create.return_value = ArticleResponse(success=True, message="ok")
            manage_kb_article(
                _config(),
                MagicMock(),
                ManageKbArticleParams(
                    action="create",
                    title="t",
                    text="body",
                    short_description="sd",
                    knowledge_base="kb1",
                    category="cat1",
                    article_type="wiki",
                ),
            )
            kwargs = mock_create.call_args.kwargs
            assert kwargs["title"] == "t"
            assert kwargs["text"] == "body"
            assert kwargs["knowledge_base"] == "kb1"
            assert kwargs["article_type"] == "wiki"

    def test_update_dispatches_with_dry_run_flag(self):
        with patch("servicenow_mcp.services.kb_article.update") as mock_update:
            mock_update.return_value = ArticleResponse(success=True, message="ok")
            manage_kb_article(
                _config(),
                MagicMock(),
                ManageKbArticleParams(action="update", article_id="abc", title="new", dry_run=True),
            )
            kwargs = mock_update.call_args.kwargs
            assert kwargs["article_id"] == "abc"
            assert kwargs["title"] == "new"
            assert kwargs["dry_run"] is True

    def test_publish_dispatches(self):
        with patch("servicenow_mcp.services.kb_article.publish") as mock_publish:
            mock_publish.return_value = ArticleResponse(success=True, message="ok")
            manage_kb_article(
                _config(),
                MagicMock(),
                ManageKbArticleParams(
                    action="publish", article_id="abc", workflow_state="published"
                ),
            )
            kwargs = mock_publish.call_args.kwargs
            assert kwargs["article_id"] == "abc"
            assert kwargs["workflow_state"] == "published"
