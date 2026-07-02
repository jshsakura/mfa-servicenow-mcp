"""Pin the core safety invariant of the processflow write surface: every
manage_flow_edit action must be rejected under basic auth BEFORE any network
call — the /api/now/processflow API is session-only and undocumented.
"""

from typing import get_args
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_edit_tools import ManageFlowEditParams, manage_flow_edit
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

_ALL_ACTIONS = list(get_args(ManageFlowEditParams.model_fields["action"].annotation))


def _basic_cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


@pytest.mark.parametrize("action", _ALL_ACTIONS)
def test_every_action_rejected_under_basic_auth(action):
    auth = MagicMock(spec=AuthManager)
    result = manage_flow_edit(
        _basic_cfg(),
        auth,
        ManageFlowEditParams(action=action, flow_id="a" * 32),
    )
    assert result["success"] is False
    assert "browser auth" in result["error"]
    auth.make_request.assert_not_called()


def test_action_literal_covers_known_surface():
    # If a new action is added, the parametrized gate test above picks it up
    # automatically; this pins that the surface is non-trivial.
    assert "save" in _ALL_ACTIONS and "checkout" in _ALL_ACTIONS
