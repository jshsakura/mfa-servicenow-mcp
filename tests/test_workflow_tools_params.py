import unittest
from unittest.mock import MagicMock

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.workflow_tools import (
    _get_auth_and_config,
    create_workflow,
    get_workflow_details,
    list_workflows,
)
from servicenow_mcp.utils.config import ServerConfig


class TestWorkflowToolsParams(unittest.TestCase):
    """Test parameter handling in workflow tools."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock objects for AuthManager and ServerConfig
        self.auth_manager = MagicMock(spec=AuthManager)
        self.auth_manager.get_headers.return_value = {"Authorization": "Bearer test-token"}

        self.server_config = MagicMock(spec=ServerConfig)
        self.server_config.instance_url = "https://test-instance.service-now.com"

    def test_get_auth_and_config_correct_order(self):
        """Test _get_auth_and_config with parameters in the correct order."""
        auth, config = _get_auth_and_config(self.auth_manager, self.server_config)
        self.assertEqual(auth, self.auth_manager)
        self.assertEqual(config, self.server_config)

    def test_get_auth_and_config_swapped_order(self):
        """Test _get_auth_and_config with parameters in the swapped order."""
        auth, config = _get_auth_and_config(self.server_config, self.auth_manager)
        self.assertEqual(auth, self.auth_manager)
        self.assertEqual(config, self.server_config)

    def test_get_auth_and_config_error_handling(self):
        """Test _get_auth_and_config error handling with invalid parameters."""
        # Create objects that don't have the required attributes
        invalid_obj1 = MagicMock()
        # Explicitly remove attributes to ensure they don't exist
        del invalid_obj1.get_headers
        del invalid_obj1.instance_url

        invalid_obj2 = MagicMock()
        # Explicitly remove attributes to ensure they don't exist
        del invalid_obj2.get_headers
        del invalid_obj2.instance_url

        with self.assertRaises(ValueError):
            _get_auth_and_config(invalid_obj1, invalid_obj2)

    def test_list_workflows_correct_params(self):
        """Test list_workflows with parameters in the correct order."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": [{"sys_id": "123", "name": "Test Workflow"}]}
        mock_response.headers = {"X-Total-Count": "1"}
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        result = list_workflows(self.auth_manager, self.server_config, {"limit": 10})

        # Verify the function called make_request with the correct parameters
        self.auth_manager.make_request.assert_called_once()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["workflows"][0]["name"], "Test Workflow")

    def test_list_workflows_swapped_params(self):
        """Test list_workflows with parameters in the swapped order."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": [{"sys_id": "123", "name": "Test Workflow"}]}
        mock_response.headers = {"X-Total-Count": "1"}
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function with swapped parameters
        result = list_workflows(self.server_config, self.auth_manager, {"limit": 10})

        # Verify the function still works correctly
        self.auth_manager.make_request.assert_called_once()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["workflows"][0]["name"], "Test Workflow")

    def test_get_workflow_details_correct_params(self):
        """Test get_workflow_details with parameters in the correct order."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"sys_id": "123", "name": "Test Workflow"}}
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        result = get_workflow_details(self.auth_manager, self.server_config, {"workflow_id": "123"})

        # Verify the function called make_request with the correct parameters
        self.auth_manager.make_request.assert_called_once()
        self.assertEqual(result["workflow"]["name"], "Test Workflow")

    def test_get_workflow_details_swapped_params(self):
        """Test get_workflow_details with parameters in the swapped order."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"sys_id": "123", "name": "Test Workflow"}}
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function with swapped parameters
        result = get_workflow_details(self.server_config, self.auth_manager, {"workflow_id": "123"})

        # Verify the function still works correctly
        self.auth_manager.make_request.assert_called_once()
        self.assertEqual(result["workflow"]["name"], "Test Workflow")

    def test_create_workflow_correct_params(self):
        """Test create_workflow with parameters in the correct order."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"sys_id": "123", "name": "New Workflow"}}
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function
        result = create_workflow(
            self.auth_manager,
            self.server_config,
            {"name": "New Workflow", "description": "Test description"},
        )

        # Verify the function called make_request with the correct parameters
        self.auth_manager.make_request.assert_called_once()
        self.assertEqual(result["workflow"]["name"], "New Workflow")
        self.assertEqual(result["message"], "Workflow created successfully")

    def test_create_workflow_swapped_params(self):
        """Test create_workflow with parameters in the swapped order."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {"sys_id": "123", "name": "New Workflow"}}
        mock_response.raise_for_status = MagicMock()
        self.auth_manager.make_request.return_value = mock_response

        # Call the function with swapped parameters
        result = create_workflow(
            self.server_config,
            self.auth_manager,
            {"name": "New Workflow", "description": "Test description"},
        )

        # Verify the function still works correctly
        self.auth_manager.make_request.assert_called_once()
        self.assertEqual(result["workflow"]["name"], "New Workflow")
        self.assertEqual(result["message"], "Workflow created successfully")


if __name__ == "__main__":
    unittest.main()
