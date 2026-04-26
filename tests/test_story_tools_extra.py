"""Extra tests for story_tools.py — targeting error paths and optional field branches."""

import unittest
from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.story_tools import (
    CreateStoryDependencyParams,
    CreateStoryParams,
    DeleteStoryDependencyParams,
    ListStoriesParams,
    ListStoryDependenciesParams,
    UpdateStoryParams,
    create_story,
    create_story_dependency,
    delete_story_dependency,
    list_stories,
    list_story_dependencies,
    update_story,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


class TestCreateStoryOptionalFields(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com",
            auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
        )
        self.auth_manager = MagicMock()

    def test_create_with_all_optional_fields(self):
        resp = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "s1"}}
        resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = resp

        params = CreateStoryParams(
            short_description="Story",
            acceptance_criteria="AC",
            description="Desc",
            assigned_to="user1",
            epic="epic1",
            project="proj1",
            work_notes="notes",
        )
        result = create_story(self.config, self.auth_manager, params)
        assert result["success"] is True
        _, kwargs = self.auth_manager.make_request.call_args
        assert kwargs["json"]["description"] == "Desc"
        assert kwargs["json"]["assigned_to"] == "user1"
        assert kwargs["json"]["epic"] == "epic1"
        assert kwargs["json"]["project"] == "proj1"
        assert kwargs["json"]["work_notes"] == "notes"

    def test_create_error(self):
        self.auth_manager.make_request.side_effect = Exception("create error")
        params = CreateStoryParams(short_description="Story", acceptance_criteria="AC")
        result = create_story(self.config, self.auth_manager, params)
        assert result["success"] is False


class TestUpdateStoryOptionalFields(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com",
            auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
        )
        self.auth_manager = MagicMock()

    def test_update_with_all_fields(self):
        resp = MagicMock()
        resp.json.return_value = {"result": {"sys_id": "s1"}}
        resp.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = resp

        params = UpdateStoryParams(
            story_id="s1",
            short_description="Updated",
            acceptance_criteria="AC",
            description="Desc",
            state="3",
            assignment_group="grp1",
            story_points=5,
            epic="epic1",
            project="proj1",
            assigned_to="user1",
            work_notes="notes",
        )
        result = update_story(self.config, self.auth_manager, params)
        assert result["success"] is True
        _, kwargs = self.auth_manager.make_request.call_args
        assert kwargs["json"]["acceptance_criteria"] == "AC"
        assert kwargs["json"]["story_points"] == 5
        assert kwargs["json"]["work_notes"] == "notes"

    def test_update_error(self):
        self.auth_manager.make_request.side_effect = Exception("update error")
        params = UpdateStoryParams(story_id="s1", state="3")
        result = update_story(self.config, self.auth_manager, params)
        assert result["success"] is False

    @patch("servicenow_mcp.tools.story_tools.build_update_preview")
    def test_update_dry_run(self, mock_preview):
        mock_preview.return_value = {"preview": True}
        params = UpdateStoryParams(story_id="s1", short_description="test", dry_run=True)
        result = update_story(self.config, self.auth_manager, params)
        assert result == {"preview": True}
        mock_preview.assert_called_once()


class TestListStoriesTimeframes(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com",
            auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
        )
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_timeframe_in_progress(self, mock_query):
        mock_query.return_value = ([{"sys_id": "s1"}], 1)
        params = ListStoriesParams(timeframe="in-progress")
        result = list_stories(self.config, self.auth_manager, params)
        assert result["success"] is True
        assert "start_date<" in mock_query.call_args.kwargs["query"]

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_timeframe_completed(self, mock_query):
        mock_query.return_value = ([{"sys_id": "s1"}], 1)
        params = ListStoriesParams(timeframe="completed")
        result = list_stories(self.config, self.auth_manager, params)
        assert result["success"] is True
        assert "end_date<" in mock_query.call_args.kwargs["query"]

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_with_query_string(self, mock_query):
        mock_query.return_value = ([], 0)
        params = ListStoriesParams(query="assignment_group=xyz")
        result = list_stories(self.config, self.auth_manager, params)
        assert result["success"] is True
        assert "assignment_group=xyz" in mock_query.call_args.kwargs["query"]

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_error(self, mock_query):
        mock_query.side_effect = Exception("query error")
        params = ListStoriesParams()
        result = list_stories(self.config, self.auth_manager, params)
        assert result["success"] is False


class TestListStoryDependencies(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com",
            auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
        )
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_with_query(self, mock_query):
        mock_query.return_value = ([{"sys_id": "d1"}], 1)
        params = ListStoryDependenciesParams(query="dependent_story=abc")
        result = list_story_dependencies(self.config, self.auth_manager, params)
        assert result["success"] is True
        assert "dependent_story=abc" in mock_query.call_args.kwargs["query"]

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_error(self, mock_query):
        mock_query.side_effect = Exception("dep error")
        params = ListStoryDependenciesParams()
        result = list_story_dependencies(self.config, self.auth_manager, params)
        assert result["success"] is False


class TestCreateStoryDependencyError(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com",
            auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
        )
        self.auth_manager = MagicMock()

    def test_create_error(self):
        self.auth_manager.make_request.side_effect = Exception("dep create error")
        params = CreateStoryDependencyParams(dependent_story="s1", prerequisite_story="s2")
        result = create_story_dependency(self.config, self.auth_manager, params)
        assert result["success"] is False


class TestDeleteStoryDependencyError(unittest.TestCase):
    def setUp(self):
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com",
            auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
        )
        self.auth_manager = MagicMock()

    def test_delete_error(self):
        self.auth_manager.make_request.side_effect = Exception("delete error")
        params = DeleteStoryDependencyParams(dependency_id="d1")
        result = delete_story_dependency(self.config, self.auth_manager, params)
        assert result["success"] is False
