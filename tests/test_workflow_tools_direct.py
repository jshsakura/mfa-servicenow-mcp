#!/usr/bin/env python
"""
Test script for workflow_tools module.
This script directly tests the workflow_tools functions with proper authentication.
"""

import json
import logging
import os

import pytest
from dotenv import load_dotenv

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.workflow_tools import get_workflow_details, list_workflows
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


@pytest.fixture(scope="module")
def server_config():
    instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
    username = os.getenv("SERVICENOW_USERNAME")
    password = os.getenv("SERVICENOW_PASSWORD")

    if not all([instance_url, username, password]):
        pytest.skip(
            "Direct workflow tests require SERVICENOW_INSTANCE_URL, SERVICENOW_USERNAME, and SERVICENOW_PASSWORD."
        )

    auth_config = AuthConfig(
        type=AuthType.BASIC,
        basic=BasicAuthConfig(username=username, password=password),
    )
    return ServerConfig(instance_url=instance_url, auth=auth_config)


@pytest.fixture(scope="module")
def auth_manager(server_config):
    return AuthManager(server_config.auth, server_config.instance_url)


@pytest.fixture(scope="module")
def workflow_id(auth_manager, server_config):
    result = list_workflows(server_config, auth_manager, {})
    workflows = result.get("workflows", [])
    if not workflows:
        pytest.skip("No workflows available in the target ServiceNow instance.")
    return workflows[0]["sys_id"]


def setup_auth_and_config():
    """Set up authentication and server configuration."""
    instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
    username = os.getenv("SERVICENOW_USERNAME")
    password = os.getenv("SERVICENOW_PASSWORD")

    if not all([instance_url, username, password]):
        logger.error(
            "Missing required environment variables. "
            "Please set SERVICENOW_INSTANCE_URL, SERVICENOW_USERNAME, "
            "and SERVICENOW_PASSWORD."
        )

    # Create authentication configuration
    auth_config = AuthConfig(
        type=AuthType.BASIC,
        basic=BasicAuthConfig(username=username, password=password),
    )

    # Create server configuration
    server_config = ServerConfig(
        instance_url=instance_url,
        auth=auth_config,
    )

    # Create authentication manager
    auth_manager = AuthManager(auth_config, instance_url)

    return auth_manager, server_config


def print_result(name, result):
    """Print the result of a function call."""
    logger.info(f"=== Result of {name} ===")
    if "error" in result:
        logger.error(f"Error: {result['error']}")
    else:
        logger.info(json.dumps(result, indent=2))


def test_list_workflows(auth_manager, server_config):
    """Test the list_workflows function."""
    logger.info("Testing list_workflows...")

    # Test with default parameters
    result = list_workflows(server_config, auth_manager, {})
    print_result("list_workflows (default)", result)

    # Test with active=True
    result = list_workflows(server_config, auth_manager, {"active": True})
    print_result("list_workflows (active=True)", result)

    return result


def test_get_workflow_details(auth_manager, server_config, workflow_id):
    """Test the get_workflow_details function."""
    logger.info(f"Testing get_workflow_details for workflow {workflow_id}...")

    result = get_workflow_details(server_config, auth_manager, {"workflow_id": workflow_id})
    print_result("get_workflow_details", result)

    return result


def test_list_workflow_versions(auth_manager, server_config, workflow_id):
    """Test workflow details with include_versions flag."""
    logger.info(f"Testing get_workflow_details(include_versions) for workflow {workflow_id}...")

    result = get_workflow_details(
        auth_manager, server_config, {"workflow_id": workflow_id, "include_versions": True}
    )
    print_result("get_workflow_details(include_versions)", result)

    return result


def test_get_workflow_activities(auth_manager, server_config, workflow_id):
    """Test workflow details with include_activities flag."""
    logger.info(f"Testing get_workflow_details(include_activities) for workflow {workflow_id}...")

    result = get_workflow_details(
        auth_manager, server_config, {"workflow_id": workflow_id, "include_activities": True}
    )
    print_result("get_workflow_details(include_activities)", result)

    return result


def test_with_swapped_params(auth_manager, server_config):
    """Test functions with swapped parameters to verify our fix works."""
    logger.info("Testing with swapped parameters...")

    # Test list_workflows with swapped parameters
    result = list_workflows(server_config, auth_manager, {})
    print_result("list_workflows (swapped params)", result)

    return result


if __name__ == "__main__":
    logger.info("Testing workflow_tools module...")

    # Set up authentication and server configuration
    cli_auth_manager, cli_server_config = setup_auth_and_config()

    # Test list_workflows
    workflows_result = test_list_workflows(cli_auth_manager, cli_server_config)

    # If we got any workflows, test the other functions
    if "workflows" in workflows_result and workflows_result["workflows"]:
        cli_workflow_id = workflows_result["workflows"][0]["sys_id"]

        # Test get_workflow_details
        test_get_workflow_details(cli_auth_manager, cli_server_config, cli_workflow_id)

        # Test list_workflow_versions
        test_list_workflow_versions(cli_auth_manager, cli_server_config, cli_workflow_id)

        # Test get_workflow_activities
        test_get_workflow_activities(cli_auth_manager, cli_server_config, cli_workflow_id)
    else:
        logger.warning("No workflows found, skipping detail tests.")

    # Test with swapped parameters
    test_with_swapped_params(cli_auth_manager, cli_server_config)

    logger.info("Tests completed.")
