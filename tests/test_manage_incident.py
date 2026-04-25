"""Tests for manage_incident — bundled CRUD via dispatch to legacy wrappers."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.incident_tools import (
    IncidentResponse,
    ManageIncidentParams,
    manage_incident,
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


# ---------------------------------------------------------------------------
# Per-action validation (Pydantic model_validator)
# ---------------------------------------------------------------------------


class TestPerActionValidation:
    def test_create_requires_short_description(self):
        with pytest.raises(ValidationError, match="short_description"):
            ManageIncidentParams(action="create")

    def test_update_requires_incident_id(self):
        with pytest.raises(ValidationError, match="incident_id"):
            ManageIncidentParams(action="update", state="2")

    def test_update_requires_at_least_one_field(self):
        with pytest.raises(ValidationError, match="at least one field"):
            ManageIncidentParams(action="update", incident_id="abc")

    def test_comment_requires_incident_id(self):
        with pytest.raises(ValidationError, match="incident_id"):
            ManageIncidentParams(action="comment", comment="hello")

    def test_comment_requires_comment_text(self):
        with pytest.raises(ValidationError, match="comment is required"):
            ManageIncidentParams(action="comment", incident_id="abc")

    def test_resolve_requires_resolution_fields(self):
        with pytest.raises(ValidationError, match="resolution_code"):
            ManageIncidentParams(action="resolve", incident_id="abc")

    def test_invalid_action_rejected(self):
        with pytest.raises(ValidationError):
            ManageIncidentParams(action="archive")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Dispatch — manage_incident routes to the right legacy wrapper
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_create_dispatches_to_create_incident(self):
        with patch("servicenow_mcp.tools.incident_tools.create_incident") as mock_create:
            mock_create.return_value = IncidentResponse(
                success=True, message="ok", incident_id="abc", incident_number="INC1"
            )
            out = manage_incident(
                _config(),
                MagicMock(),
                ManageIncidentParams(action="create", short_description="x", priority="3"),
            )
            assert mock_create.call_count == 1
            inner_params = mock_create.call_args[0][2]
            assert inner_params.short_description == "x"
            assert inner_params.priority == "3"
            assert out.success is True

    def test_update_dispatches_to_update_incident_with_id_and_dry_run(self):
        with patch("servicenow_mcp.tools.incident_tools.update_incident") as mock_update:
            mock_update.return_value = IncidentResponse(success=True, message="ok")
            manage_incident(
                _config(),
                MagicMock(),
                ManageIncidentParams(action="update", incident_id="abc", state="2", dry_run=True),
            )
            inner_params = mock_update.call_args[0][2]
            assert inner_params.incident_id == "abc"
            assert inner_params.state == "2"
            assert inner_params.dry_run is True

    def test_comment_dispatches_to_add_comment(self):
        with patch("servicenow_mcp.tools.incident_tools.add_comment") as mock_comment:
            mock_comment.return_value = IncidentResponse(success=True, message="ok")
            manage_incident(
                _config(),
                MagicMock(),
                ManageIncidentParams(
                    action="comment",
                    incident_id="abc",
                    comment="checked",
                    is_work_note=True,
                ),
            )
            inner_params = mock_comment.call_args[0][2]
            assert inner_params.incident_id == "abc"
            assert inner_params.comment == "checked"
            assert inner_params.is_work_note is True

    def test_resolve_dispatches_to_resolve_incident(self):
        with patch("servicenow_mcp.tools.incident_tools.resolve_incident") as mock_resolve:
            mock_resolve.return_value = IncidentResponse(success=True, message="ok")
            manage_incident(
                _config(),
                MagicMock(),
                ManageIncidentParams(
                    action="resolve",
                    incident_id="abc",
                    resolution_code="solved",
                    resolution_notes="ok",
                ),
            )
            inner_params = mock_resolve.call_args[0][2]
            assert inner_params.incident_id == "abc"
            assert inner_params.resolution_code == "solved"
            assert inner_params.resolution_notes == "ok"


# ---------------------------------------------------------------------------
# Integration with the confirm gate (via _call_tool_impl)
# ---------------------------------------------------------------------------


class TestConfirmGate:
    def test_manage_incident_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        # Prefix "manage_" matches MUTATING_TOOL_PREFIXES
        assert ServiceNowMCP._is_blocked_mutating_tool("manage_incident") is True
        assert ServiceNowMCP._tool_requires_confirmation("manage_incident") is True
