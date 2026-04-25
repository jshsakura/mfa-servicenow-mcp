"""Tests for manage_script_include — Phase 3b bundle."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.script_include_tools import (
    ManageScriptIncludeParams,
    manage_script_include,
)
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
    def test_create_requires_name_and_script(self):
        with pytest.raises(ValidationError, match="name"):
            ManageScriptIncludeParams(action="create", script="x")
        with pytest.raises(ValidationError, match="script"):
            ManageScriptIncludeParams(action="create", name="X")

    def test_update_requires_script_include_id(self):
        with pytest.raises(ValidationError, match="script_include_id"):
            ManageScriptIncludeParams(action="update", script="x")

    def test_update_requires_at_least_one_field(self):
        with pytest.raises(ValidationError, match="at least one field"):
            ManageScriptIncludeParams(action="update", script_include_id="abc")

    def test_delete_requires_script_include_id(self):
        with pytest.raises(ValidationError, match="script_include_id"):
            ManageScriptIncludeParams(action="delete")

    def test_execute_requires_name(self):
        with pytest.raises(ValidationError, match="name"):
            ManageScriptIncludeParams(action="execute", method="run")


class TestDispatch:
    def test_create(self):
        with patch("servicenow_mcp.tools.script_include_tools.create_script_include") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_script_include(
                _config(),
                MagicMock(),
                ManageScriptIncludeParams(
                    action="create",
                    name="MyUtil",
                    script="var x = 1;",
                    api_name="x_acme.MyUtil",
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.name == "MyUtil"
            assert inner.api_name == "x_acme.MyUtil"

    def test_update(self):
        with patch("servicenow_mcp.tools.script_include_tools.update_script_include") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_script_include(
                _config(),
                MagicMock(),
                ManageScriptIncludeParams(action="update", script_include_id="abc", active=False),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.script_include_id == "abc"
            assert inner.active is False

    def test_delete(self):
        with patch("servicenow_mcp.tools.script_include_tools.delete_script_include") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_script_include(
                _config(),
                MagicMock(),
                ManageScriptIncludeParams(action="delete", script_include_id="abc"),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.script_include_id == "abc"

    def test_execute(self):
        with patch("servicenow_mcp.tools.script_include_tools.execute_script_include") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_script_include(
                _config(),
                MagicMock(),
                ManageScriptIncludeParams(
                    action="execute",
                    name="MyUtil",
                    method="getStuff",
                    exec_params={"id": "abc"},
                ),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.name == "MyUtil"
            assert inner.method == "getStuff"
            assert inner.params == {"id": "abc"}


class TestConfirmGate:
    def test_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        assert ServiceNowMCP._tool_requires_confirmation("manage_script_include") is True
