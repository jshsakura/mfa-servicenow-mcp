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


class TestListStories(unittest.TestCase):
    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="test", password="test")
        )
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com", auth=self.auth_config
        )
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_list_stories_basic(self, mock_query):
        mock_query.return_value = (
            [{"sys_id": "abc123", "short_description": "Story 1"}],
            1,
        )

        params = ListStoriesParams()
        result = list_stories(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["stories"]), 1)
        self.assertEqual(result["stories"][0]["sys_id"], "abc123")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total"], 1)
        mock_query.assert_called_once()
        call_kwargs = mock_query.call_args
        self.assertEqual(call_kwargs.kwargs["table"], "rm_story")

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_list_stories_with_state_filter(self, mock_query):
        mock_query.return_value = (
            [{"sys_id": "s1", "short_description": "Active story", "state": "2"}],
            1,
        )

        params = ListStoriesParams(state="2")
        result = list_stories(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        call_kwargs = mock_query.call_args.kwargs
        self.assertIn("state=2", call_kwargs["query"])

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_list_stories_with_timeframe(self, mock_query):
        mock_query.return_value = (
            [
                {"sys_id": "s1", "short_description": "Upcoming story"},
            ],
            1,
        )

        params = ListStoriesParams(timeframe="upcoming")
        result = list_stories(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args.kwargs
        self.assertIn("start_date>", call_kwargs["query"])

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_list_stories_empty(self, mock_query):
        mock_query.return_value = ([], 0)

        params = ListStoriesParams()
        result = list_stories(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["stories"], [])
        self.assertEqual(result["count"], 0)

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_list_stories_error(self, mock_query):
        mock_query.side_effect = Exception("Connection error")

        params = ListStoriesParams()
        result = list_stories(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Connection error", result["message"])


class TestCreateStory(unittest.TestCase):
    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="test", password="test")
        )
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com", auth=self.auth_config
        )
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.story_tools.invalidate_query_cache")
    def test_create_story_success(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "new123", "short_description": "New story"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = CreateStoryParams(
            short_description="New story",
            acceptance_criteria="Must pass tests",
            description="Detailed desc",
            state="1",
            assignment_group="group1",
        )
        result = create_story(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["story"]["sys_id"], "new123")
        self.auth_manager.make_request.assert_called_once()
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn("/api/now/table/rm_story", call_args.args[1])
        mock_invalidate.assert_called_once_with(table="rm_story")

    @patch("servicenow_mcp.tools.story_tools.invalidate_query_cache")
    def test_create_story_minimal(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "min123", "short_description": "Minimal story"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = CreateStoryParams(
            short_description="Minimal story",
            acceptance_criteria="AC",
        )
        result = create_story(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_args = self.auth_manager.make_request.call_args
        sent_data = (
            call_args.kwargs.get("json") or call_args.args[2]
            if len(call_args.args) > 2
            else call_args.kwargs["json"]
        )
        self.assertEqual(sent_data["short_description"], "Minimal story")
        self.assertEqual(sent_data["acceptance_criteria"], "AC")
        self.assertNotIn("description", sent_data)
        self.assertNotIn("state", sent_data)
        mock_invalidate.assert_called_once_with(table="rm_story")

    @patch("servicenow_mcp.tools.story_tools.invalidate_query_cache")
    def test_create_story_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Server error")

        params = CreateStoryParams(
            short_description="Fail story",
            acceptance_criteria="AC",
        )
        result = create_story(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Server error", result["message"])
        mock_invalidate.assert_not_called()


class TestUpdateStory(unittest.TestCase):
    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="test", password="test")
        )
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com", auth=self.auth_config
        )
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.story_tools.invalidate_query_cache")
    def test_update_story_success(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "upd123", "short_description": "Updated story", "state": "3"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = UpdateStoryParams(story_id="upd123", state="3")
        result = update_story(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["story"]["state"], "3")
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args.args[0], "PUT")
        self.assertIn("/api/now/table/rm_story/upd123", call_args.args[1])
        mock_invalidate.assert_called_once_with(table="rm_story")

    @patch("servicenow_mcp.tools.story_tools.invalidate_query_cache")
    def test_update_story_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Not found")

        params = UpdateStoryParams(story_id="bad_id", state="3")
        result = update_story(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Not found", result["message"])
        mock_invalidate.assert_not_called()


class TestListStoryDependencies(unittest.TestCase):
    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="test", password="test")
        )
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com", auth=self.auth_config
        )
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_list_story_dependencies_basic(self, mock_query):
        mock_query.return_value = (
            [{"sys_id": "dep1", "dependent_story": "s1", "prerequisite_story": "s2"}],
            1,
        )

        params = ListStoryDependenciesParams()
        result = list_story_dependencies(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["story_dependencies"]), 1)
        self.assertEqual(result["count"], 1)
        call_kwargs = mock_query.call_args.kwargs
        self.assertEqual(call_kwargs["table"], "m2m_story_dependencies")

    @patch("servicenow_mcp.tools.story_tools.sn_query_page")
    def test_list_story_dependencies_with_filters(self, mock_query):
        mock_query.return_value = (
            [{"sys_id": "dep1", "dependent_story": "abc", "prerequisite_story": "def"}],
            1,
        )

        params = ListStoryDependenciesParams(dependent_story="abc", prerequisite_story="def")
        result = list_story_dependencies(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_kwargs = mock_query.call_args.kwargs
        self.assertIn("dependent_story=abc", call_kwargs["query"])
        self.assertIn("prerequisite_story=def", call_kwargs["query"])


class TestCreateStoryDependency(unittest.TestCase):
    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="test", password="test")
        )
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com", auth=self.auth_config
        )
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.story_tools.invalidate_query_cache")
    def test_create_story_dependency_success(self, mock_invalidate):
        response = MagicMock()
        response.json.return_value = {
            "result": {"sys_id": "dep_new", "dependent_story": "s1", "prerequisite_story": "s2"}
        }
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = CreateStoryDependencyParams(dependent_story="s1", prerequisite_story="s2")
        result = create_story_dependency(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        self.assertEqual(result["story_dependency"]["sys_id"], "dep_new")
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args.args[0], "POST")
        self.assertIn("/api/now/table/m2m_story_dependencies", call_args.args[1])
        mock_invalidate.assert_called_once_with(table="m2m_story_dependencies")


class TestDeleteStoryDependency(unittest.TestCase):
    def setUp(self):
        self.auth_config = AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="test", password="test")
        )
        self.config = ServerConfig(
            instance_url="https://dev12345.service-now.com", auth=self.auth_config
        )
        self.auth_manager = MagicMock()

    @patch("servicenow_mcp.tools.story_tools.invalidate_query_cache")
    def test_delete_story_dependency_success(self, mock_invalidate):
        response = MagicMock()
        response.raise_for_status.return_value = None
        self.auth_manager.make_request.return_value = response

        params = DeleteStoryDependencyParams(dependency_id="dep_del")
        result = delete_story_dependency(self.config, self.auth_manager, params)

        self.assertTrue(result["success"])
        call_args = self.auth_manager.make_request.call_args
        self.assertEqual(call_args.args[0], "DELETE")
        self.assertIn("/api/now/table/m2m_story_dependencies/dep_del", call_args.args[1])
        mock_invalidate.assert_called_once_with(table="m2m_story_dependencies")

    @patch("servicenow_mcp.tools.story_tools.invalidate_query_cache")
    def test_delete_story_dependency_error(self, mock_invalidate):
        self.auth_manager.make_request.side_effect = Exception("Not found")

        params = DeleteStoryDependencyParams(dependency_id="bad_dep")
        result = delete_story_dependency(self.config, self.auth_manager, params)

        self.assertFalse(result["success"])
        self.assertIn("Not found", result["message"])
        mock_invalidate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
