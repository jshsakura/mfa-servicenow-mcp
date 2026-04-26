"""Tests for knowledge_base uncovered paths — manage_kb_article, edge cases, error handling."""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.knowledge_base import (
    CreateCategoryParams,
    CreateKnowledgeBaseParams,
    GetArticleParams,
    ListArticlesParams,
    ListCategoriesParams,
    ListKnowledgeBasesParams,
    ManageKbArticleParams,
    create_category,
    create_knowledge_base,
    get_article,
    list_articles,
    list_categories,
    list_knowledge_bases,
    manage_kb_article,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _setup():
    auth_config = AuthConfig(
        type=AuthType.BASIC,
        basic=BasicAuthConfig(username="test_user", password="test_password"),
    )
    config = ServerConfig(instance_url="https://test.service-now.com", auth=auth_config)
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {
        "Authorization": "Bearer test",
        "Content-Type": "application/json",
    }
    return config, auth


def _mock_response(payload, auth):
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.content = json.dumps(payload).encode("utf-8")
    mock_resp.headers = {}
    mock_resp.raise_for_status = MagicMock()
    auth.make_request.return_value = mock_resp
    return mock_resp


class TestManageKbArticle:
    @patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
    def test_create_action(self, mock_invalidate):
        config, auth = _setup()
        _mock_response(
            {"result": {"sys_id": "new001", "short_description": "Managed Article"}}, auth
        )

        params = ManageKbArticleParams(
            action="create",
            title="Managed Article",
            text="Content",
            short_description="Short desc",
            knowledge_base="kb001",
            category="cat001",
        )
        result = manage_kb_article(config, auth, params)
        assert result.success is True
        assert result.article_id == "new001"

    @patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
    def test_create_action_with_keywords(self, mock_invalidate):
        config, auth = _setup()
        _mock_response({"result": {"sys_id": "new002", "short_description": "KW Article"}}, auth)

        params = ManageKbArticleParams(
            action="create",
            title="KW Article",
            text="Content",
            short_description="Short desc",
            knowledge_base="kb001",
            category="cat001",
            keywords="test,kw",
            article_type="text",
        )
        result = manage_kb_article(config, auth, params)
        assert result.success is True
        call_data = auth.make_request.call_args[1]["json"]
        assert call_data["keywords"] == "test,kw"
        assert call_data["article_type"] == "text"

    @patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
    def test_update_action(self, mock_invalidate):
        config, auth = _setup()
        _mock_response({"result": {"sys_id": "art1", "short_description": "Updated"}}, auth)

        params = ManageKbArticleParams(
            action="update",
            article_id="art1",
            title="Updated",
        )
        result = manage_kb_article(config, auth, params)
        assert result.success is True

    @patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
    def test_publish_action(self, mock_invalidate):
        config, auth = _setup()
        _mock_response(
            {
                "result": {
                    "sys_id": "art1",
                    "short_description": "Published",
                    "workflow_state": "published",
                }
            },
            auth,
        )

        params = ManageKbArticleParams(
            action="publish",
            article_id="art1",
            workflow_state="published",
        )
        result = manage_kb_article(config, auth, params)
        assert result.success is True
        assert result.workflow_state == "published"

    @patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
    def test_publish_action_with_version(self, mock_invalidate):
        config, auth = _setup()
        _mock_response({"result": {"sys_id": "art1", "workflow_state": "published"}}, auth)

        params = ManageKbArticleParams(
            action="publish",
            article_id="art1",
            workflow_state="published",
            workflow_version="v2",
        )
        result = manage_kb_article(config, auth, params)
        assert result.success is True
        call_data = auth.make_request.call_args[1]["json"]
        assert call_data["workflow_version"] == "v2"

    def test_create_validation_missing_fields(self):
        with pytest.raises(ValueError, match="action='create' requires"):
            ManageKbArticleParams(
                action="create",
                title="Only Title",
            )

    def test_update_validation_no_article_id(self):
        with pytest.raises(ValueError, match="article_id is required"):
            ManageKbArticleParams(
                action="update",
                title="Some Title",
            )

    def test_update_validation_no_fields(self):
        with pytest.raises(ValueError, match="at least one field"):
            ManageKbArticleParams(
                action="update",
                article_id="art1",
            )

    def test_publish_validation_no_article_id(self):
        with pytest.raises(ValueError, match="article_id is required"):
            ManageKbArticleParams(action="publish")


class TestCreateCategoryEdgeCases:
    @patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache")
    def test_with_parent_category_and_table(self, mock_invalidate):
        config, auth = _setup()
        _mock_response({"result": {"sys_id": "sub001", "label": "SubCat"}}, auth)

        params = CreateCategoryParams(
            title="SubCat",
            knowledge_base="kb001",
            parent_category="parent001",
            parent_table="kb_category",
            active=False,
        )
        result = create_category(config, auth, params)
        assert result.success is True
        call_data = auth.make_request.call_args[1]["json"]
        assert call_data["parent"] == "parent001"
        assert call_data["parent_table"] == "kb_category"
        assert call_data["active"] == "false"


class TestListKnowledgeBasesEdgeCases:
    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_error_response(self, mock_query):
        config, auth = _setup()
        mock_query.side_effect = Exception("Network error")

        params = ListKnowledgeBasesParams()
        result = list_knowledge_bases(config, auth, params)

        assert result["success"] is False
        assert result["knowledge_bases"] == []
        assert result["count"] == 0


class TestListArticlesEdgeCases:
    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_error_response(self, mock_query):
        config, auth = _setup()
        mock_query.side_effect = Exception("Network error")

        params = ListArticlesParams()
        result = list_articles(config, auth, params)

        assert result["success"] is False
        assert result["articles"] == []

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_non_list_result_logs_warning(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = ("not a list", 0)

        params = ListArticlesParams()
        result = list_articles(config, auth, params)

        assert result["success"] is True
        assert result["articles"] == []


class TestListCategoriesEdgeCases:
    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_non_list_result(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = ("not a list", 0)

        params = ListCategoriesParams()
        result = list_categories(config, auth, params)

        assert result["success"] is True
        assert result["categories"] == []

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_error_response(self, mock_query):
        config, auth = _setup()
        mock_query.side_effect = Exception("fail")

        params = ListCategoriesParams()
        result = list_categories(config, auth, params)

        assert result["success"] is False
        assert result["categories"] == []

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_string_kb_and_parent_fields(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = (
            [
                {
                    "sys_id": "cat1",
                    "label": "Cat",
                    "description": "",
                    "kb_knowledge_base": "KB Name String",
                    "parent": "Parent Name String",
                    "active": "true",
                    "sys_created_on": "",
                    "sys_updated_on": "",
                }
            ],
            1,
        )

        params = ListCategoriesParams()
        result = list_categories(config, auth, params)

        assert result["success"] is True
        assert result["categories"][0]["knowledge_base"] == "KB Name String"
        assert result["categories"][0]["parent_category"] == "Parent Name String"

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_alternative_kb_and_parent_field_names(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = (
            [
                {
                    "sys_id": "cat1",
                    "label": "Cat",
                    "description": "",
                    "kb_knowledge_base_value": "Alt KB",
                    "parent_value": "Alt Parent",
                    "active": True,
                    "sys_created_on": "",
                    "sys_updated_on": "",
                }
            ],
            1,
        )

        params = ListCategoriesParams()
        result = list_categories(config, auth, params)

        assert result["success"] is True
        assert result["categories"][0]["knowledge_base"] == "Alt KB"
        assert result["categories"][0]["parent_category"] == "Alt Parent"

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_display_value_field_names(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = (
            [
                {
                    "sys_id": "cat1",
                    "label": "Cat",
                    "description": "",
                    "kb_knowledge_base.display_value": "Display KB",
                    "parent.display_value": "Display Parent",
                    "active": "true",
                    "sys_created_on": "",
                    "sys_updated_on": "",
                }
            ],
            1,
        )

        params = ListCategoriesParams()
        result = list_categories(config, auth, params)

        assert result["success"] is True
        assert result["categories"][0]["knowledge_base"] == "Display KB"
        assert result["categories"][0]["parent_category"] == "Display Parent"

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_non_dict_item_skipped(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = (
            [
                "not a dict",
                {
                    "sys_id": "cat1",
                    "label": "Valid",
                    "description": "",
                    "active": "true",
                    "sys_created_on": "",
                    "sys_updated_on": "",
                },
            ],
            2,
        )

        params = ListCategoriesParams()
        result = list_categories(config, auth, params)

        assert result["success"] is True
        assert result["count"] == 1


class TestCreateKnowledgeBaseEdgeCases:
    def test_create_kb_error(self):
        config, auth = _setup()
        auth.make_request.side_effect = Exception("Server error")

        params = CreateKnowledgeBaseParams(title="Test KB")
        result = create_knowledge_base(config, auth, params)

        assert result.success is False
        assert "Failed to create" in result.message


class TestGetArticleEdgeCases:
    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_dict_result_type(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = (
            [
                {
                    "sys_id": "art1",
                    "short_description": "Dict Art",
                    "text": "Content",
                    "sys_created_on": "",
                    "sys_updated_on": "",
                }
            ],
            1,
        )

        params = GetArticleParams(article_id="art1")
        result = get_article(config, auth, params)
        assert result["success"] is True

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_error_response(self, mock_query):
        config, auth = _setup()
        mock_query.side_effect = Exception("fail")

        params = GetArticleParams(article_id="art1")
        result = get_article(config, auth, params)
        assert result["success"] is False
        assert "Failed to get" in result["message"]

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_string_kb_field_unchanged(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = (
            [
                {
                    "sys_id": "art1",
                    "short_description": "Art",
                    "text": "T",
                    "kb_knowledge_base": "KB String",
                    "sys_created_on": "",
                    "sys_updated_on": "",
                }
            ],
            1,
        )

        params = GetArticleParams(article_id="art1")
        result = get_article(config, auth, params)
        assert result["success"] is True
        # get_article only extracts dict display_value, string fields leave knowledge_base empty
        assert result["article"]["knowledge_base"] == ""


class TestListKnowledgeBasesNonListResult:
    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_non_list_result(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = ("not a list", 0)

        params = ListKnowledgeBasesParams()
        result = list_knowledge_bases(config, auth, params)

        assert result["success"] is True
        assert result["knowledge_bases"] == []

    @patch("servicenow_mcp.tools.knowledge_base.sn_query_page")
    def test_non_dict_item_skipped(self, mock_query):
        config, auth = _setup()
        mock_query.return_value = (
            ["not a dict"],
            1,
        )

        params = ListKnowledgeBasesParams()
        result = list_knowledge_bases(config, auth, params)

        assert result["success"] is True
        assert result["count"] == 0
