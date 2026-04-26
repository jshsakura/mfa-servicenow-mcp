"""Tests for manage_user, manage_group — Phase 3d bundles.

These bundles include READ actions (list/get) which should bypass the
manage_* confirm gate via MANAGE_READ_ACTIONS.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.user_tools import (
    ManageGroupParams,
    ManageUserParams,
    manage_group,
    manage_user,
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
# manage_user
# ---------------------------------------------------------------------------


class TestManageUserValidation:
    def test_create_requires_user_name_and_names_and_email(self):
        with pytest.raises(ValidationError, match="user_name"):
            ManageUserParams(action="create", first_name="A", last_name="B", email="a@b.com")
        with pytest.raises(ValidationError, match="first_name"):
            ManageUserParams(action="create", user_name="x", last_name="B", email="a@b.com")
        with pytest.raises(ValidationError, match="email"):
            ManageUserParams(action="create", user_name="x", first_name="A", last_name="B")

    def test_update_requires_user_id_and_field(self):
        with pytest.raises(ValidationError, match="user_id"):
            ManageUserParams(action="update", email="a@b.com")
        with pytest.raises(ValidationError, match="at least one field"):
            ManageUserParams(action="update", user_id="abc")

    def test_get_requires_an_identifier(self):
        with pytest.raises(ValidationError, match="user_id"):
            ManageUserParams(action="get")

    def test_list_has_no_required_fields(self):
        ManageUserParams(action="list", limit=5)


class TestManageUserDispatch:
    def test_create(self):
        with patch("servicenow_mcp.services.user.create_user") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_user(
                _config(),
                MagicMock(),
                ManageUserParams(
                    action="create",
                    user_name="alice",
                    first_name="Alice",
                    last_name="Wonder",
                    email="a@w.com",
                ),
            )
            assert mock_fn.call_args.kwargs["user_name"] == "alice"

    def test_update(self):
        with patch("servicenow_mcp.services.user.update_user") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_user(
                _config(),
                MagicMock(),
                ManageUserParams(action="update", user_id="abc", title="Lead"),
            )
            assert mock_fn.call_args.kwargs["user_id"] == "abc"
            assert mock_fn.call_args.kwargs["title"] == "Lead"

    def test_get(self):
        with patch("servicenow_mcp.tools.user_tools.get_user") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_user(
                _config(),
                MagicMock(),
                ManageUserParams(action="get", user_name="alice"),
            )
            assert mock_fn.call_args[0][2].user_name == "alice"

    def test_list(self):
        with patch("servicenow_mcp.tools.user_tools.list_users") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_user(
                _config(),
                MagicMock(),
                ManageUserParams(action="list", department="eng", limit=20),
            )
            assert mock_fn.call_args[0][2].department == "eng"
            assert mock_fn.call_args[0][2].limit == 20


# ---------------------------------------------------------------------------
# manage_group
# ---------------------------------------------------------------------------


class TestManageGroupValidation:
    def test_create_requires_name(self):
        with pytest.raises(ValidationError, match="name"):
            ManageGroupParams(action="create")

    def test_update_requires_id_and_field(self):
        with pytest.raises(ValidationError, match="group_id"):
            ManageGroupParams(action="update", name="x")
        with pytest.raises(ValidationError, match="at least one field"):
            ManageGroupParams(action="update", group_id="abc")

    def test_add_remove_members_require_id_and_members(self):
        for action in ("add_members", "remove_members"):
            with pytest.raises(ValidationError, match="group_id"):
                ManageGroupParams(action=action, members=["u1"])  # type: ignore[arg-type]
            with pytest.raises(ValidationError, match="members"):
                ManageGroupParams(action=action, group_id="abc")  # type: ignore[arg-type]


class TestManageGroupDispatch:
    def test_create(self):
        with patch("servicenow_mcp.services.user.create_group") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_group(
                _config(),
                MagicMock(),
                ManageGroupParams(action="create", name="Devs", type="approval"),
            )
            assert mock_fn.call_args.kwargs["name"] == "Devs"

    def test_update(self):
        with patch("servicenow_mcp.services.user.update_group") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_group(
                _config(),
                MagicMock(),
                ManageGroupParams(action="update", group_id="abc", active=False),
            )
            assert mock_fn.call_args.kwargs["active"] is False

    def test_list(self):
        with patch("servicenow_mcp.tools.user_tools.list_groups") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_group(
                _config(),
                MagicMock(),
                ManageGroupParams(action="list", type="approval", limit=5),
            )
            inner = mock_fn.call_args[0][2]
            assert inner.type == "approval"
            assert inner.limit == 5

    def test_add_members(self):
        with patch("servicenow_mcp.services.user.add_members") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_group(
                _config(),
                MagicMock(),
                ManageGroupParams(action="add_members", group_id="abc", members=["u1", "u2"]),
            )
            assert mock_fn.call_args.kwargs["members"] == ["u1", "u2"]

    def test_remove_members(self):
        with patch("servicenow_mcp.services.user.remove_members") as mock_fn:
            mock_fn.return_value = {"success": True}
            manage_group(
                _config(),
                MagicMock(),
                ManageGroupParams(action="remove_members", group_id="abc", members=["u1"]),
            )
            assert mock_fn.call_args.kwargs["members"] == ["u1"]


# ---------------------------------------------------------------------------
# Read-action confirm exemption (MANAGE_READ_ACTIONS)
# ---------------------------------------------------------------------------


class TestReadActionExemption:
    """manage_user.action='get' / 'list' should NOT require confirm at the
    server.py call-time check, even though the prefix matches manage_."""

    def _server(self, tool_defs):
        from unittest.mock import patch as _patch

        from servicenow_mcp.server import ServiceNowMCP

        with (
            _patch("servicenow_mcp.server.AuthManager"),
            _patch("servicenow_mcp.server.get_tool_definitions") as gtd,
            _patch("servicenow_mcp.server.load_skills", return_value=[]),
            _patch("servicenow_mcp.server.build_tool_to_skills_map", return_value={}),
        ):
            gtd.return_value = tool_defs
            srv = ServiceNowMCP(_config())
            srv.tool_definitions = tool_defs
            srv.enabled_tool_names = list(tool_defs.keys())
            srv.current_package_name = "standard"
            return srv

    def test_manage_user_list_skips_confirm(self):
        import asyncio

        from servicenow_mcp.server import MANAGE_READ_ACTIONS

        assert "list" in MANAGE_READ_ACTIONS.get("manage_user", set())
        assert "get" in MANAGE_READ_ACTIONS.get("manage_user", set())

        def fake(_c, _a, _p):
            return {"ok": True}

        srv = self._server({"manage_user": (fake, ManageUserParams, dict, "desc", "raw_dict")})

        async def _check():
            result = await srv._call_tool_impl("manage_user", {"action": "list"})
            assert "ok" in result[0].text

        asyncio.run(_check())

    def test_manage_user_create_still_requires_confirm(self):
        import asyncio

        def fake(_c, _a, _p):
            return {"ok": True}

        srv = self._server({"manage_user": (fake, ManageUserParams, dict, "desc", "raw_dict")})

        async def _check():
            with pytest.raises(ValueError, match="modify or delete"):
                await srv._call_tool_impl(
                    "manage_user",
                    {
                        "action": "create",
                        "user_name": "x",
                        "first_name": "X",
                        "last_name": "Y",
                        "email": "a@b.com",
                    },
                )

        asyncio.run(_check())
