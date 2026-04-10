"""
Tests for the knowledge base tools.

This module contains tests for the knowledge base tools in the ServiceNow MCP server.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.knowledge_base import (
    CreateArticleParams,
    CreateCategoryParams,
    CreateKnowledgeBaseParams,
    GetArticleParams,
    ListArticlesParams,
    ListCategoriesParams,
    ListKnowledgeBasesParams,
    PublishArticleParams,
    UpdateArticleParams,
    create_article,
    create_category,
    create_knowledge_base,
    get_article,
    list_articles,
    list_categories,
    list_knowledge_bases,
    publish_article,
    update_article,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestKnowledgeBaseTools(unittest.TestCase):
    """Tests for the knowledge base tools."""

    def setUp(self):
        """Set up test fixtures."""
        auth_config = AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="test_user", password="test_password"),
        )
        self.server_config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=auth_config,
        )
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {
            "Authorization": "Bearer test",
            "Content-Type": "application/json",
        }

    def _finalize_response(self, mock_response):
        payload = mock_response.json.return_value
        mock_response.content = json.dumps(payload).encode("utf-8")
        mock_response.headers = {}
        mock_response.raise_for_status = MagicMock()
        return mock_response

    @patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache")
    def test_create_knowledge_base(self, mock_invalidate_query_cache):
        """Test creating a knowledge base."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "kb001",
                "title": "Test Knowledge Base",
                "description": "Test Description",
                "owner": "admin",
                "kb_managers": "it_managers",
                "workflow_publish": "Knowledge - Instant Publish",
                "workflow_retire": "Knowledge - Instant Retire",
            }
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = CreateKnowledgeBaseParams(
            title="Test Knowledge Base",
            description="Test Description",
            owner="admin",
            managers="it_managers",
        )
        result = create_knowledge_base(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result.success)
        self.assertEqual("kb001", result.kb_id)
        self.assertEqual("Test Knowledge Base", result.kb_name)

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("POST", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_knowledge_base", call_args[0][1])
        self.assertEqual("Test Knowledge Base", call_args[1]["json"]["title"])
        self.assertEqual("Test Description", call_args[1]["json"]["description"])
        self.assertEqual("admin", call_args[1]["json"]["owner"])
        self.assertEqual("it_managers", call_args[1]["json"]["kb_managers"])
        mock_invalidate_query_cache.assert_called_once_with(table="kb_knowledge_base")

    @patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache")
    def test_create_category(self, mock_invalidate_query_cache):
        """Test creating a category."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "cat001",
                "label": "Test Category",
                "description": "Test Category Description",
                "kb_knowledge_base": "kb001",
                "parent": "",
                "active": "true",
            }
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = CreateCategoryParams(
            title="Test Category",
            description="Test Category Description",
            knowledge_base="kb001",
            active=True,
        )
        result = create_category(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result.success)
        self.assertEqual("cat001", result.category_id)
        self.assertEqual("Test Category", result.category_name)

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("POST", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_category", call_args[0][1])
        self.assertEqual("Test Category", call_args[1]["json"]["label"])
        self.assertEqual("Test Category Description", call_args[1]["json"]["description"])
        self.assertEqual("kb001", call_args[1]["json"]["kb_knowledge_base"])
        self.assertEqual("true", call_args[1]["json"]["active"])
        mock_invalidate_query_cache.assert_called_once_with(table="kb_category")

    @patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache")
    def test_create_article(self, mock_invalidate_query_cache):
        """Test creating a knowledge article."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "art001",
                "short_description": "Test Article",
                "text": "This is a test article content",
                "kb_knowledge_base": "kb001",
                "kb_category": "cat001",
                "article_type": "text",
                "keywords": "test,article,knowledge",
                "workflow_state": "draft",
            }
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = CreateArticleParams(
            title="Test Article",
            short_description="Test Article",
            text="This is a test article content",
            knowledge_base="kb001",
            category="cat001",
            keywords="test,article,knowledge",
            article_type="text",
        )
        result = create_article(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result.success)
        self.assertEqual("art001", result.article_id)
        self.assertEqual("Test Article", result.article_title)

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("POST", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_knowledge", call_args[0][1])
        self.assertEqual("Test Article", call_args[1]["json"]["short_description"])
        self.assertEqual("This is a test article content", call_args[1]["json"]["text"])
        self.assertEqual("kb001", call_args[1]["json"]["kb_knowledge_base"])
        self.assertEqual("cat001", call_args[1]["json"]["kb_category"])
        self.assertEqual("text", call_args[1]["json"]["article_type"])
        self.assertEqual("test,article,knowledge", call_args[1]["json"]["keywords"])
        mock_invalidate_query_cache.assert_called_once_with(table="kb_knowledge")

    @patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache")
    def test_update_article(self, mock_invalidate_query_cache):
        """Test updating a knowledge article."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "art001",
                "short_description": "Updated Article",
                "text": "This is an updated article content",
                "kb_category": "cat002",
                "keywords": "updated,article,knowledge",
                "workflow_state": "draft",
            }
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = UpdateArticleParams(
            article_id="art001",
            title="Updated Article",
            text="This is an updated article content",
            category="cat002",
            keywords="updated,article,knowledge",
        )
        result = update_article(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result.success)
        self.assertEqual("art001", result.article_id)
        self.assertEqual("Updated Article", result.article_title)

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("PATCH", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_knowledge/art001", call_args[0][1])
        self.assertEqual("Updated Article", call_args[1]["json"]["short_description"])
        self.assertEqual("This is an updated article content", call_args[1]["json"]["text"])
        self.assertEqual("cat002", call_args[1]["json"]["kb_category"])
        self.assertEqual("updated,article,knowledge", call_args[1]["json"]["keywords"])
        mock_invalidate_query_cache.assert_called_once_with(table="kb_knowledge")

    @patch("servicenow_mcp.tools.knowledge_base.invalidate_query_cache")
    def test_publish_article(self, mock_invalidate_query_cache):
        """Test publishing a knowledge article."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "art001",
                "short_description": "Test Article",
                "workflow_state": "published",
            }
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = PublishArticleParams(article_id="art001", workflow_state="published")
        result = publish_article(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result.success)
        self.assertEqual("art001", result.article_id)
        self.assertEqual("Test Article", result.article_title)
        self.assertEqual("published", result.workflow_state)

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("PATCH", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_knowledge/art001", call_args[0][1])
        self.assertEqual("published", call_args[1]["json"]["workflow_state"])
        mock_invalidate_query_cache.assert_called_once_with(table="kb_knowledge")

    def test_list_articles(self):
        """Test listing knowledge articles."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "art001",
                    "short_description": "Test Article 1",
                    "kb_knowledge_base": {"display_value": "IT Knowledge Base"},
                    "kb_category": {"display_value": "Network"},
                    "workflow_state": {"display_value": "Published"},
                    "sys_created_on": "2023-01-01 00:00:00",
                    "sys_updated_on": "2023-01-02 00:00:00",
                },
                {
                    "sys_id": "art002",
                    "short_description": "Test Article 2",
                    "kb_knowledge_base": {"display_value": "IT Knowledge Base"},
                    "kb_category": {"display_value": "Software"},
                    "workflow_state": {"display_value": "Draft"},
                    "sys_created_on": "2023-01-03 00:00:00",
                    "sys_updated_on": "2023-01-04 00:00:00",
                },
            ]
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = ListArticlesParams(
            limit=10,
            offset=0,
            knowledge_base="kb001",
            category="cat001",
            workflow_state="published",
            query="network",
        )
        result = list_articles(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result["success"])
        self.assertEqual(2, len(result["articles"]))
        self.assertEqual("art001", result["articles"][0]["id"])
        self.assertEqual("Test Article 1", result["articles"][0]["title"])
        self.assertEqual("IT Knowledge Base", result["articles"][0]["knowledge_base"])
        self.assertEqual("Network", result["articles"][0]["category"])
        self.assertEqual("Published", result["articles"][0]["workflow_state"])

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("GET", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_knowledge", call_args[0][1])
        self.assertEqual(10, call_args[1]["params"]["sysparm_limit"])
        self.assertEqual(0, call_args[1]["params"]["sysparm_offset"])
        self.assertEqual("true", call_args[1]["params"]["sysparm_display_value"])

        # Verify the query syntax contains the correct pattern
        self.assertIn("sysparm_query", call_args[1]["params"])
        query = call_args[1]["params"]["sysparm_query"]
        self.assertIn("kb_knowledge_base.sys_id=kb001", query)
        self.assertIn("kb_category.sys_id=cat001", query)

    def test_get_article(self):
        """Test getting a knowledge article."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": {
                "sys_id": "art001",
                "short_description": "Test Article",
                "text": "This is a test article content",
                "kb_knowledge_base": {"display_value": "IT Knowledge Base"},
                "kb_category": {"display_value": "Network"},
                "workflow_state": {"display_value": "Published"},
                "sys_created_on": "2023-01-01 00:00:00",
                "sys_updated_on": "2023-01-02 00:00:00",
                "author": {"display_value": "admin"},
                "keywords": "test,article,knowledge",
                "article_type": "text",
                "view_count": "42",
            }
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = GetArticleParams(article_id="art001")
        result = get_article(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result["success"])
        self.assertEqual("art001", result["article"]["id"])
        self.assertEqual("Test Article", result["article"]["title"])
        self.assertEqual("This is a test article content", result["article"]["text"])
        self.assertEqual("IT Knowledge Base", result["article"]["knowledge_base"])
        self.assertEqual("Network", result["article"]["category"])
        self.assertEqual("Published", result["article"]["workflow_state"])
        self.assertEqual("admin", result["article"]["author"])
        self.assertEqual("test,article,knowledge", result["article"]["keywords"])
        self.assertEqual("text", result["article"]["article_type"])
        self.assertEqual("42", result["article"]["views"])

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("GET", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_knowledge", call_args[0][1])
        self.assertEqual("true", call_args[1]["params"]["sysparm_display_value"])
        self.assertEqual("sys_id=art001", call_args[1]["params"]["sysparm_query"])
        self.assertEqual(1, call_args[1]["params"]["sysparm_limit"])

    def test_create_knowledge_base_error(self):
        """Test error handling when creating a knowledge base."""
        # Mock error response
        self.auth_manager.make_request.side_effect = requests.RequestException("API error")

        # Call the method
        params = CreateKnowledgeBaseParams(title="Test Knowledge Base")
        result = create_knowledge_base(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertFalse(result.success)
        self.assertIn("Failed to create knowledge base", result.message)

    def test_get_article_not_found(self):
        """Test getting a non-existent article."""
        # Mock empty response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": []}
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = GetArticleParams(article_id="nonexistent")
        result = get_article(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])

    def test_list_knowledge_bases(self):
        """Test listing knowledge bases."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "kb001",
                    "title": "IT Knowledge Base",
                    "description": "Knowledge base for IT resources",
                    "owner": {"display_value": "admin"},
                    "kb_managers": {"display_value": "it_managers"},
                    "active": "true",
                    "sys_created_on": "2023-01-01 00:00:00",
                    "sys_updated_on": "2023-01-02 00:00:00",
                },
                {
                    "sys_id": "kb002",
                    "title": "HR Knowledge Base",
                    "description": "Knowledge base for HR resources",
                    "owner": {"display_value": "hr_admin"},
                    "kb_managers": {"display_value": "hr_managers"},
                    "active": "true",
                    "sys_created_on": "2023-01-03 00:00:00",
                    "sys_updated_on": "2023-01-04 00:00:00",
                },
            ]
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = ListKnowledgeBasesParams(limit=10, offset=0, active=True, query="IT")
        result = list_knowledge_bases(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result["success"])
        self.assertEqual(2, len(result["knowledge_bases"]))
        self.assertEqual("kb001", result["knowledge_bases"][0]["id"])
        self.assertEqual("IT Knowledge Base", result["knowledge_bases"][0]["title"])
        self.assertEqual(
            "Knowledge base for IT resources", result["knowledge_bases"][0]["description"]
        )
        self.assertEqual("admin", result["knowledge_bases"][0]["owner"])
        self.assertEqual("it_managers", result["knowledge_bases"][0]["managers"])
        self.assertTrue(result["knowledge_bases"][0]["active"])

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("GET", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_knowledge_base", call_args[0][1])
        self.assertEqual(10, call_args[1]["params"]["sysparm_limit"])
        self.assertEqual(0, call_args[1]["params"]["sysparm_offset"])
        self.assertEqual("true", call_args[1]["params"]["sysparm_display_value"])
        self.assertEqual(
            "active=true^titleLIKEIT^ORdescriptionLIKEIT",
            call_args[1]["params"]["sysparm_query"],
        )

    def test_list_categories(self):
        """Test listing categories in a knowledge base."""
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "result": [
                {
                    "sys_id": "cat001",
                    "label": "Network Troubleshooting",
                    "description": "Articles for network troubleshooting",
                    "kb_knowledge_base": {"display_value": "IT Knowledge Base"},
                    "parent": {"display_value": ""},
                    "active": "true",
                    "sys_created_on": "2023-01-01 00:00:00",
                    "sys_updated_on": "2023-01-02 00:00:00",
                },
                {
                    "sys_id": "cat002",
                    "label": "Software Setup",
                    "description": "Articles for software installation",
                    "kb_knowledge_base": {"display_value": "IT Knowledge Base"},
                    "parent": {"display_value": ""},
                    "active": "true",
                    "sys_created_on": "2023-01-03 00:00:00",
                    "sys_updated_on": "2023-01-04 00:00:00",
                },
            ]
        }
        self._finalize_response(mock_response)
        self.auth_manager.make_request.return_value = mock_response

        # Call the method
        params = ListCategoriesParams(knowledge_base="kb001", active=True, query="Network")
        result = list_categories(self.server_config, self.auth_manager, params)

        # Verify the result
        self.assertTrue(result["success"])
        self.assertEqual(2, len(result["categories"]))
        self.assertEqual("cat001", result["categories"][0]["id"])
        self.assertEqual("Network Troubleshooting", result["categories"][0]["title"])
        self.assertEqual(
            "Articles for network troubleshooting", result["categories"][0]["description"]
        )
        self.assertEqual("IT Knowledge Base", result["categories"][0]["knowledge_base"])
        self.assertEqual("", result["categories"][0]["parent_category"])
        self.assertTrue(result["categories"][0]["active"])

        # Verify the request
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual("GET", call_args[0][0])
        self.assertEqual(f"{self.server_config.api_url}/table/kb_category", call_args[0][1])
        self.assertEqual(10, call_args[1]["params"]["sysparm_limit"])
        self.assertEqual(0, call_args[1]["params"]["sysparm_offset"])
        self.assertEqual("true", call_args[1]["params"]["sysparm_display_value"])

        # Verify the query syntax contains the correct pattern
        self.assertIn("sysparm_query", call_args[1]["params"])
        query = call_args[1]["params"]["sysparm_query"]
        self.assertIn("kb_knowledge_base.sys_id=kb001", query)
        self.assertIn("active=true", query)
        self.assertIn("labelLIKENetwork", query)


class TestKnowledgeBaseParams(unittest.TestCase):
    """Tests for the knowledge base parameter classes."""

    def test_create_knowledge_base_params(self):
        """Test CreateKnowledgeBaseParams validation."""
        # Minimal required parameters
        params = CreateKnowledgeBaseParams(title="Test Knowledge Base")
        self.assertEqual("Test Knowledge Base", params.title)
        self.assertEqual("Knowledge - Instant Publish", params.publish_workflow)

        # All parameters
        params = CreateKnowledgeBaseParams(
            title="Test Knowledge Base",
            description="Test Description",
            owner="admin",
            managers="it_managers",
            publish_workflow="Custom Workflow",
            retire_workflow="Custom Retire Workflow",
        )
        self.assertEqual("Test Knowledge Base", params.title)
        self.assertEqual("Test Description", params.description)
        self.assertEqual("admin", params.owner)
        self.assertEqual("it_managers", params.managers)
        self.assertEqual("Custom Workflow", params.publish_workflow)
        self.assertEqual("Custom Retire Workflow", params.retire_workflow)

    def test_create_category_params(self):
        """Test CreateCategoryParams validation."""
        # Required parameters
        params = CreateCategoryParams(title="Test Category", knowledge_base="kb001")
        self.assertEqual("Test Category", params.title)
        self.assertEqual("kb001", params.knowledge_base)
        self.assertTrue(params.active)

        # All parameters
        params = CreateCategoryParams(
            title="Test Category",
            description="Test Description",
            knowledge_base="kb001",
            parent_category="parent001",
            active=False,
        )
        self.assertEqual("Test Category", params.title)
        self.assertEqual("Test Description", params.description)
        self.assertEqual("kb001", params.knowledge_base)
        self.assertEqual("parent001", params.parent_category)
        self.assertFalse(params.active)

    def test_create_article_params(self):
        """Test CreateArticleParams validation."""
        # Required parameters
        params = CreateArticleParams(
            title="Test Article",
            text="Test content",
            short_description="Test short description",
            knowledge_base="kb001",
            category="cat001",
        )
        self.assertEqual("Test Article", params.title)
        self.assertEqual("Test content", params.text)
        self.assertEqual("Test short description", params.short_description)
        self.assertEqual("kb001", params.knowledge_base)
        self.assertEqual("cat001", params.category)
        self.assertEqual("html", params.article_type)

        # All parameters
        params = CreateArticleParams(
            title="Test Article",
            text="Test content",
            short_description="Test short description",
            knowledge_base="kb001",
            category="cat001",
            keywords="test,article",
            article_type="html",
        )
        self.assertEqual("Test Article", params.title)
        self.assertEqual("Test content", params.text)
        self.assertEqual("Test short description", params.short_description)
        self.assertEqual("kb001", params.knowledge_base)
        self.assertEqual("cat001", params.category)
        self.assertEqual("test,article", params.keywords)
        self.assertEqual("html", params.article_type)


if __name__ == "__main__":
    unittest.main()
