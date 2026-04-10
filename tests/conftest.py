"""Shared pytest fixtures for ServiceNow MCP tests.

Provides common mock objects (config, auth_manager, mock_response) used across
40+ test files, eliminating per-file boilerplate.
"""

import json
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

# ---------------------------------------------------------------------------
# Autouse: clear query cache between tests to prevent cross-test pollution
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_query_cache():
    """Clear the sn_api query cache before and after every test."""
    invalidate_query_cache()
    yield
    invalidate_query_cache()


# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_config() -> ServerConfig:
    """A valid ServerConfig with basic auth for unit tests."""
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def mock_auth(mock_config) -> MagicMock:
    """A MagicMock specced to AuthManager with basic-auth headers."""
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {
        "Authorization": "Basic YWRtaW46cGFzc3dvcmQ=",
        "Content-Type": "application/json",
    }
    return auth


# ---------------------------------------------------------------------------
# Helper function (importable, not a fixture)
# ---------------------------------------------------------------------------


def make_mock_response(data, *, status_code=200, headers=None):
    """Create a mock ``requests.Response``-like object.

    Importable helper for tests that need to build responses inline:

        from conftest import make_mock_response
    """
    mock = MagicMock()
    mock.json.return_value = data
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    mock.content = json.dumps(data).encode("utf-8")
    mock.headers = headers or {}
    return mock
