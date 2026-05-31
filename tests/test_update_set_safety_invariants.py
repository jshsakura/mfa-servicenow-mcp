"""Safety invariants for update-set handling — the contracts that must NEVER break.

This file is intentionally adversarial. It does not test "does feature X work";
it asserts the guarantees a production instance depends on:

  I1. The MCP never creates an update set without explicit confirm='approve'.
  I2. Renaming / re-stating an update set never happens without confirm.
  I3. Publish/commit needs DOUBLE confirmation (confirm + confirm_publish).
  I4. A blocked write reaches NO network — the block happens before any request.
  I5. There is exactly ONE module that POSTs a new update set
      (services/changeset.py); no tool silently spawns one.
  I6. Portal create does NOT touch the session's update set unless the caller
      explicitly passed update_set.
  I7. update_code blocks when the record's last set differs from the current
      session set, until confirm_update_set='approve'.
  I8. Switching the update set by a name that does not exist NEVER creates it —
      it returns not_found and issues no PUT/POST.

If any of these fail, an LLM (or a careless refactor) could create stray update
sets or capture changes into the wrong one. Treat a failure here as a release
blocker, not a flaky test.
"""

import asyncio
import pathlib
from unittest.mock import MagicMock, patch

import pytest

import servicenow_mcp.server as server_module
from servicenow_mcp.server import ServiceNowMCP
from servicenow_mcp.tools.portal_crud_tools import (
    ManagePortalComponentParams,
    manage_portal_component,
)
from servicenow_mcp.tools.session_context_tools import (
    ManageSessionContextParams,
    manage_session_context,
)
from servicenow_mcp.utils.config import ServerConfig

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "servicenow_mcp"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _server(monkeypatch, tmp_path):
    """Build a server whose package exposes manage_changeset (the create/rename/
    publish surface these invariants guard). Package is read only from the env."""
    config_path = tmp_path / "tool_packages.yaml"
    config_path.write_text("\n".join(["none: []", "cs_only:", "  - manage_changeset"]))
    monkeypatch.setenv("TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("MCP_TOOL_PACKAGE", "cs_only")
    monkeypatch.setattr(server_module, "TOOL_PACKAGE_CONFIG_PATH", str(config_path))
    return ServiceNowMCP(
        {
            "instance_url": "https://test.service-now.com",
            "auth": {"type": "basic", "basic": {"username": "admin", "password": "pw"}},
        }
    )


def _call(server, name, arguments):
    return asyncio.new_event_loop().run_until_complete(server._call_tool_impl(name, arguments))


def _browser_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={
            "type": "browser",
            "browser": {"username": "u", "instance_url": "https://test.service-now.com"},
        },
    )


def _resp(payload):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    r.text = ""
    r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# I1 — create needs confirm; the block raises before any network (I4)
# ---------------------------------------------------------------------------
class TestNoUnconfirmedCreation:
    def test_create_without_confirm_is_blocked_and_hits_no_network(self, monkeypatch, tmp_path):
        server = _server(monkeypatch, tmp_path)
        with patch.object(server.auth_manager, "make_request") as mr:
            mr.side_effect = AssertionError("network reached during a blocked create")
            with pytest.raises(ValueError, match="confirm='approve'"):
                _call(
                    server,
                    "manage_changeset",
                    {"action": "create", "name": "Stray Set", "application": "app"},
                )
        mr.assert_not_called()

    def test_create_with_confirm_proceeds_to_exactly_one_post(self, monkeypatch, tmp_path):
        # With confirm, creation IS allowed — but it must be a deliberate, single
        # POST the caller asked for, not a silent loop.
        server = _server(monkeypatch, tmp_path)
        with patch.object(server.auth_manager, "make_request") as mr:
            mr.return_value = _resp({"result": {"sys_id": "us-new", "name": "Stray Set"}})
            _call(
                server,
                "manage_changeset",
                {
                    "action": "create",
                    "name": "Stray Set",
                    "application": "app",
                    "confirm": "approve",
                },
            )
        posts = [c for c in mr.call_args_list if c.args and c.args[0] == "POST"]
        assert len(posts) == 1, f"expected exactly one POST, got {len(posts)}"


# ---------------------------------------------------------------------------
# I2 — rename / re-state needs confirm
# ---------------------------------------------------------------------------
class TestNoUnconfirmedMutation:
    def test_rename_without_confirm_is_blocked(self, monkeypatch, tmp_path):
        server = _server(monkeypatch, tmp_path)
        with patch.object(server.auth_manager, "make_request") as mr:
            mr.side_effect = AssertionError("network reached during a blocked rename")
            with pytest.raises(ValueError, match="confirm='approve'"):
                _call(
                    server,
                    "manage_changeset",
                    {"action": "update", "changeset_id": "abc", "name": "renamed"},
                )
        mr.assert_not_called()


# ---------------------------------------------------------------------------
# I3 — publish/commit need DOUBLE confirmation (confirm + confirm_publish)
# ---------------------------------------------------------------------------
class TestPublishDoubleConfirm:
    def test_publish_with_single_confirm_is_blocked(self, monkeypatch, tmp_path):
        server = _server(monkeypatch, tmp_path)
        with patch.object(server.auth_manager, "make_request") as mr:
            mr.side_effect = AssertionError("network reached during a blocked publish")
            # confirm='approve' alone is NOT enough — G7 demands confirm_publish too.
            with pytest.raises(ValueError, match="confirm_publish"):
                _call(
                    server,
                    "manage_changeset",
                    {"action": "publish", "changeset_id": "abc", "confirm": "approve"},
                )
        mr.assert_not_called()

    def test_commit_with_single_confirm_is_blocked(self, monkeypatch, tmp_path):
        server = _server(monkeypatch, tmp_path)
        with patch.object(server.auth_manager, "make_request") as mr:
            mr.side_effect = AssertionError("network reached during a blocked commit")
            with pytest.raises(ValueError, match="confirm_publish"):
                _call(
                    server,
                    "manage_changeset",
                    {"action": "commit", "changeset_id": "abc", "confirm": "approve"},
                )
        mr.assert_not_called()


# ---------------------------------------------------------------------------
# I5 — STATIC: exactly one module POSTs a new update set
# ---------------------------------------------------------------------------
class TestSingleCreationSite:
    def test_only_changeset_service_posts_a_new_update_set(self):
        """Across the whole package, the only module that both issues a POST and
        targets the sys_update_set create URL is services/changeset.py. A new
        creation site must be a conscious, reviewed change — not something that
        slips in via a refactor or a new tool."""
        offenders = []
        for path in SRC.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if '"POST"' in text and "table/sys_update_set" in text:
                if path.name != "changeset.py":
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        assert offenders == [], (
            f"update-set POST found outside services/changeset.py: {offenders}. "
            "New creation sites must be reviewed."
        )

    def test_session_context_module_never_posts(self):
        """session_context_tools switches context (GET/PUT only); it must never
        POST — POST is how records get created, and this module must not create."""
        text = (SRC / "tools" / "session_context_tools.py").read_text(encoding="utf-8")
        assert '"POST"' not in text, "session_context_tools must not issue any POST"


# ---------------------------------------------------------------------------
# I6 — portal create leaves the session update set alone unless asked
# ---------------------------------------------------------------------------
class TestPortalCreateDoesNotTouchUpdateSet:
    def test_create_without_update_set_never_calls_ensure_current_update_set(self):
        cfg = ServerConfig(
            instance_url="https://t.service-now.com",
            auth={"type": "basic", "basic": {"username": "a", "password": "p"}},
        )
        auth = MagicMock()
        with (
            patch("servicenow_mcp.tools.portal_crud_tools.ensure_current_update_set") as mock_us,
            patch("servicenow_mcp.tools.portal_crud_tools.ensure_current_app") as mock_app,
            patch(
                "servicenow_mcp.services.portal_component.create_angular_provider"
            ) as mock_create,
        ):
            mock_app.return_value = {"switched": False, "skipped": "not_browser_auth"}
            mock_create.return_value = {"success": True, "sys_id": "ap1"}
            params = ManagePortalComponentParams(
                action="create_provider", name="svc", script="x", scope="scope-1"
            )
            manage_portal_component(cfg, auth, params)
        mock_us.assert_not_called()  # update set left untouched


# ---------------------------------------------------------------------------
# I7 — update_code blocks on update-set drift until explicitly confirmed
# ---------------------------------------------------------------------------
class TestUpdateCodeDriftGate:
    def _cfg_auth(self):
        cfg = ServerConfig(
            instance_url="https://t.service-now.com",
            auth={"type": "basic", "basic": {"username": "a", "password": "p"}},
        )
        return cfg, MagicMock()

    def test_drift_blocks_and_does_not_write(self):
        cfg, auth = self._cfg_auth()
        with (
            patch(
                "servicenow_mcp.tools.portal_crud_tools.get_last_update_set_for_record",
                return_value={"sys_id": "us-old", "name": "Old"},
            ),
            patch(
                "servicenow_mcp.tools.portal_crud_tools.get_current_update_set",
                return_value={"sys_id": "us-new", "name": "New"},
            ),
            patch("servicenow_mcp.tools.portal_crud_tools.update_portal_component") as mock_update,
        ):
            params = ManagePortalComponentParams(
                action="update_code",
                table="sp_widget",
                sys_id="w1",
                update_data={"script": "x"},
            )
            result = manage_portal_component(cfg, auth, params)
        assert result["success"] is False
        assert result["error"] == "update_set_mismatch"
        mock_update.assert_not_called()

    def test_drift_proceeds_only_with_explicit_confirm(self):
        cfg, auth = self._cfg_auth()
        with (
            patch(
                "servicenow_mcp.tools.portal_crud_tools.get_last_update_set_for_record"
            ) as mock_last,
            patch(
                "servicenow_mcp.tools.portal_crud_tools.update_portal_component",
                return_value={"success": True},
            ) as mock_update,
        ):
            params = ManagePortalComponentParams(
                action="update_code",
                table="sp_widget",
                sys_id="w1",
                update_data={"script": "x"},
                confirm_update_set="approve",
            )
            result = manage_portal_component(cfg, auth, params)
        assert result["success"] is True
        mock_update.assert_called_once()
        # When confirmed, the drift lookup is skipped entirely — no second-guessing.
        mock_last.assert_not_called()


# ---------------------------------------------------------------------------
# I8 — switching to a non-existent set by name never creates it
# ---------------------------------------------------------------------------
class TestSwitchByNameNeverCreates:
    def test_unknown_name_returns_not_found_without_any_put_or_post(self):
        auth = MagicMock()
        # The only network the resolver does is the read (sn_query_page, patched
        # here). It must NOT fall through to a PUT switch or a POST create.
        with patch(
            "servicenow_mcp.tools.session_context_tools.sn_query_page",
            return_value=([], 0),
        ):
            result = manage_session_context(
                _browser_config(),
                auth,
                ManageSessionContextParams(
                    action="set_update_set", update_set_name="Does Not Exist"
                ),
            )
        assert result["success"] is False
        assert result["error"] == "not_found"
        auth.make_request.assert_not_called()  # no PUT to switch, no POST to create
