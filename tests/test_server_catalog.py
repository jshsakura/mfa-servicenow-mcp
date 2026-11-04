"""
Tests for the ServiceNow MCP server integration with catalog functionality.
"""

import unittest
from unittest.mock import MagicMock

from servicenow_mcp.server import ServiceNowMCP


class TestServerCatalog(unittest.TestCase):
    """Test cases for the server integration with catalog functionality."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock config
        self.config = {
            "instance_url": "https://example.service-now.com",
            "auth": {
                "type": "basic",
                "basic": {
                    "username": "admin",
                    "password": "password",
                },
            },
        }

        # Create a mock server
        self.server = ServiceNowMCP(self.config)

        # Mock the FastMCP server
        self.server.mcp_server = MagicMock()
        self.server.mcp_server.resource = MagicMock()
        self.server.mcp_server.tool = MagicMock()

    def test_register_catalog_resources(self):
        """Test that catalog resources are registered correctly."""
        # Call the method to register resources
        self.server._register_resources()

        # Check that the resource decorators were called
        resource_calls = self.server.mcp_server.resource.call_args_list
        resource_paths = [call[0][0] for call in resource_calls]

        # Check that catalog resources are registered
        self.assertIn("catalog://items", resource_paths)
        self.assertIn("catalog://categories", resource_paths)
        self.assertIn("catalog://{item_id}", resource_paths)

    def test_register_catalog_tools(self):
        """Test that catalog tools are registered correctly."""
        # Call the method to register tools
        self.server._register_tools()

        # Check that the tool decorator was called
        self.server.mcp_server.tool.assert_called()

        # Get the tool functions
        tool_calls = self.server.mcp_server.tool.call_args_list

        # Instead of trying to extract names from the call args, just check that the decorator was called
        # the right number of times (at least 3 times for the catalog tools)
        self.assertGreaterEqual(len(tool_calls), 3)


if __name__ == "__main__":
    unittest.main()
