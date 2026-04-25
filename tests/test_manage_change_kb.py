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
        with patch("servicenow_mcp.tools.change_tools.create_change_request") as mock_create:
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
            inner = mock_create.call_args[0][2]
            assert inner.short_description == "rebuild db"
            assert inner.type == "normal"
            assert inner.risk == "low"

    def test_update_dispatches(self):
        with patch("servicenow_mcp.tools.change_tools.update_change_request") as mock_update:
            mock_update.return_value = {"success": True}
            manage_change(
                _config(),
                MagicMock(),
                ManageChangeParams(action="update", change_id="abc", state="2", risk="medium"),
            )
            inner = mock_update.call_args[0][2]
            assert inner.change_id == "abc"
            assert inner.state == "2"
            assert inner.risk == "medium"

    def test_add_task_dispatches(self):
        with patch("servicenow_mcp.tools.change_tools.add_change_task") as mock_add:
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
            inner = mock_add.call_args[0][2]
            assert inner.change_id == "abc"
            assert inner.short_description == "patch db"
            assert inner.assigned_to == "user1"


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
        with patch("servicenow_mcp.tools.knowledge_base.create_article") as mock_create:
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
            inner = mock_create.call_args[0][2]
            assert inner.title == "t"
            assert inner.text == "body"
            assert inner.knowledge_base == "kb1"
            assert inner.article_type == "wiki"

    def test_update_dispatches_with_dry_run_flag(self):
        with patch("servicenow_mcp.tools.knowledge_base.update_article") as mock_update:
            mock_update.return_value = ArticleResponse(success=True, message="ok")
            manage_kb_article(
                _config(),
                MagicMock(),
                ManageKbArticleParams(action="update", article_id="abc", title="new", dry_run=True),
            )
            inner = mock_update.call_args[0][2]
            assert inner.article_id == "abc"
            assert inner.title == "new"
            assert inner.dry_run is True

    def test_publish_dispatches(self):
        with patch("servicenow_mcp.tools.knowledge_base.publish_article") as mock_publish:
            mock_publish.return_value = ArticleResponse(success=True, message="ok")
            manage_kb_article(
                _config(),
                MagicMock(),
                ManageKbArticleParams(
                    action="publish", article_id="abc", workflow_state="published"
                ),
            )
            inner = mock_publish.call_args[0][2]
            assert inner.article_id == "abc"
            assert inner.workflow_state == "published"
