"""Tests for manage_incident — bundled CRUD via dispatch to legacy wrappers."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.services.incident import IncidentResponse
from servicenow_mcp.tools.incident_tools import ManageIncidentParams, manage_incident
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
    def test_create_dispatches_to_service(self):
        with patch("servicenow_mcp.services.incident.create") as mock_create:
            mock_create.return_value = IncidentResponse(
                success=True, message="ok", incident_id="abc", incident_number="INC1"
            )
            out = manage_incident(
                _config(),
                MagicMock(),
                ManageIncidentParams(action="create", short_description="x", priority="3"),
            )
            assert mock_create.call_count == 1
            kwargs = mock_create.call_args.kwargs
            assert kwargs["short_description"] == "x"
            assert kwargs["priority"] == "3"
            assert out.success is True

    def test_update_dispatches_to_service_with_id_and_dry_run(self):
        with patch("servicenow_mcp.services.incident.update") as mock_update:
            mock_update.return_value = IncidentResponse(success=True, message="ok")
            manage_incident(
                _config(),
                MagicMock(),
                ManageIncidentParams(action="update", incident_id="abc", state="2", dry_run=True),
            )
            kwargs = mock_update.call_args.kwargs
            assert kwargs["incident_id"] == "abc"
            assert kwargs["state"] == "2"
            assert kwargs["dry_run"] is True

    def test_comment_dispatches_to_service(self):
        with patch("servicenow_mcp.services.incident.add_comment") as mock_comment:
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
            kwargs = mock_comment.call_args.kwargs
            assert kwargs["incident_id"] == "abc"
            assert kwargs["comment"] == "checked"
            assert kwargs["is_work_note"] is True

    def test_resolve_dispatches_to_service(self):
        with patch("servicenow_mcp.services.incident.resolve") as mock_resolve:
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
            kwargs = mock_resolve.call_args.kwargs
            assert kwargs["incident_id"] == "abc"
            assert kwargs["resolution_code"] == "solved"
            assert kwargs["resolution_notes"] == "ok"


# ---------------------------------------------------------------------------
# Integration with the confirm gate (via _call_tool_impl)
# ---------------------------------------------------------------------------


class TestConfirmGate:
    def test_manage_incident_requires_confirm(self):
        from servicenow_mcp.server import ServiceNowMCP

        # Prefix "manage_" matches MUTATING_TOOL_PREFIXES
        assert ServiceNowMCP._is_blocked_mutating_tool("manage_incident") is True
        assert ServiceNowMCP._tool_requires_confirmation("manage_incident") is True
