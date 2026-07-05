"""G10 session-identity guard + sn_health declared-owner surfacing.

Multi-user setups run each instance under a known person, declared via the
browser auth ``username``. A reconnect can adopt a session that belongs to a
DIFFERENT user (shared per-instance disk cache) — writes would then be
recorded under that user and captured into THEIR active update set. G10 makes
that impossible deterministically; sn_health surfaces the mismatch for reads.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from servicenow_mcp.policies.write_guards import PolicyViolation, _g10_session_identity


def _browser_ctx(declared_username):
    auth_cfg = SimpleNamespace(
        type=SimpleNamespace(value="browser"),
        browser=SimpleNamespace(username=declared_username),
    )
    config = SimpleNamespace(instance_url="https://x.service-now.com", auth=auth_cfg)
    server = SimpleNamespace(config=config, auth_manager=SimpleNamespace())
    return SimpleNamespace(server=server, tool_name="sn_write", arguments={})


def _basic_ctx():
    auth_cfg = SimpleNamespace(
        type=SimpleNamespace(value="basic"),
        browser=None,
    )
    config = SimpleNamespace(instance_url="https://x.service-now.com", auth=auth_cfg)
    server = SimpleNamespace(config=config, auth_manager=SimpleNamespace())
    return SimpleNamespace(server=server, tool_name="sn_write", arguments={})


class TestG10SessionIdentity:
    @patch("servicenow_mcp.tools.sn_api.resolve_live_username", return_value="user_b")
    def test_mismatch_blocks_write(self, _mock_resolve) -> None:
        with pytest.raises(PolicyViolation) as exc:
            _g10_session_identity(_browser_ctx("user_a"))
        message = str(exc.value)
        assert "[G10]" in message
        assert "user_b" in message and "user_a" in message
        assert "update set" in message  # says WHY it matters, plainly

    @patch("servicenow_mcp.tools.sn_api.resolve_live_username", return_value="User_A")
    def test_match_is_case_insensitive(self, _mock_resolve) -> None:
        _g10_session_identity(_browser_ctx("user_a"))  # no raise

    @patch("servicenow_mcp.tools.sn_api.resolve_live_username", return_value="user_b")
    def test_no_declared_username_is_a_noop(self, mock_resolve) -> None:
        _g10_session_identity(_browser_ctx(None))
        _g10_session_identity(_browser_ctx(""))
        mock_resolve.assert_not_called()

    @patch("servicenow_mcp.tools.sn_api.resolve_live_username", return_value="user_b")
    def test_non_browser_auth_is_a_noop(self, mock_resolve) -> None:
        # basic/oauth identity IS the configured credential — nothing to verify.
        _g10_session_identity(_basic_ctx())
        mock_resolve.assert_not_called()

    @patch("servicenow_mcp.tools.sn_api.resolve_live_username", return_value="")
    def test_unresolvable_identity_fails_open_by_default(self, _mock_resolve, monkeypatch) -> None:
        monkeypatch.delenv("SERVICENOW_WRITE_GUARDS_FAIL", raising=False)
        _g10_session_identity(_browser_ctx("user_a"))  # no raise

    @patch("servicenow_mcp.tools.sn_api.resolve_live_username", return_value="")
    def test_unresolvable_identity_blocks_when_fail_closed(
        self, _mock_resolve, monkeypatch
    ) -> None:
        monkeypatch.setenv("SERVICENOW_WRITE_GUARDS_FAIL", "closed")
        with pytest.raises(PolicyViolation) as exc:
            _g10_session_identity(_browser_ctx("user_a"))
        assert "[G10]" in str(exc.value)

    @patch(
        "servicenow_mcp.tools.sn_api.resolve_live_username",
        side_effect=RuntimeError("boom"),
    )
    def test_resolver_exception_fails_open_by_default(self, _mock_resolve, monkeypatch) -> None:
        monkeypatch.delenv("SERVICENOW_WRITE_GUARDS_FAIL", raising=False)
        _g10_session_identity(_browser_ctx("user_a"))  # no raise


class TestSnHealthIdentityMismatch:
    def _run_sn_health(self, authenticated_user, declared):
        from servicenow_mcp.tools import sn_api

        auth_cfg = SimpleNamespace(
            type=SimpleNamespace(value="browser"),
            browser=SimpleNamespace(username=declared),
        )
        config = SimpleNamespace(
            instance_url="https://x.service-now.com", auth=auth_cfg, timeout=30
        )
        params = SimpleNamespace(deep=False)
        with (
            patch.object(sn_api, "_sn_health_impl", return_value={"ok": True}),
            patch.object(sn_api, "_chromium_health_fields", return_value={}),
            patch.object(sn_api, "_auth_identity_fields", return_value={}),
            patch.object(sn_api, "_authenticated_user", return_value=authenticated_user),
            patch.object(sn_api, "_workspace_snapshot", return_value=None),
        ):
            return sn_api.sn_health(config, SimpleNamespace(), params)

    def test_mismatch_sets_flag_and_warning(self) -> None:
        result = self._run_sn_health("user_b", "user_a")
        assert result["declared_user"] == "user_a"
        assert result["identity_mismatch"] is True
        assert any("G10" in w for w in result["warnings"])

    def test_match_has_no_mismatch_flag(self) -> None:
        result = self._run_sn_health("user_a", "user_a")
        assert result["declared_user"] == "user_a"
        assert "identity_mismatch" not in result

    def test_no_declared_user_adds_nothing(self) -> None:
        result = self._run_sn_health("user_b", None)
        assert "declared_user" not in result
        assert "identity_mismatch" not in result
