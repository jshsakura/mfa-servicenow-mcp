"""Tests for manage_ui_policy — Phase 3g bundle."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.ui_policy_tools import ManageUiPolicyParams, manage_ui_policy
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


class TestValidation:
    def test_create_requires_table_and_short_description(self):
        with pytest.raises(ValidationError, match="table"):
            ManageUiPolicyParams(action="create", short_description="x")
        with pytest.raises(ValidationError, match="short_description"):
            ManageUiPolicyParams(action="create", table="incident")

    def test_add_action_requires_ui_policy_and_field(self):
        with pytest.raises(ValidationError, match="ui_policy"):
            ManageUiPolicyParams(action="add_action", field="state")
        with pytest.raises(ValidationError, match="field"):
            ManageUiPolicyParams(action="add_action", ui_policy="abc")


class TestDispatch:
    def test_create(self):
        with patch("servicenow_mcp.tools.ui_policy_tools.create_ui_policy") as m:
            m.return_value = {"success": True}
            manage_ui_policy(
                _config(),
                MagicMock(),
                ManageUiPolicyParams(
                    action="create",
                    table="incident",
                    short_description="hide priority on close",
                    conditions="state=6",
                ),
            )
            inner = m.call_args[0][2]
            assert inner.table == "incident"
            assert inner.short_description == "hide priority on close"
            assert inner.conditions == "state=6"

    def test_add_action(self):
        with patch("servicenow_mcp.tools.ui_policy_tools.create_ui_policy_action") as m:
            m.return_value = {"success": True}
            manage_ui_policy(
                _config(),
                MagicMock(),
                ManageUiPolicyParams(
                    action="add_action",
                    ui_policy="p1",
                    field="priority",
                    visible="false",
                    mandatory="false",
                ),
            )
            inner = m.call_args[0][2]
            assert inner.ui_policy == "p1"
            assert inner.field == "priority"
            assert inner.visible == "false"
            assert inner.mandatory == "false"


class TestConfirmGate:
    def test_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._tool_requires_confirmation("manage_ui_policy") is True
