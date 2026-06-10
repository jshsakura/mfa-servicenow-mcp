"""Tests for query_local_graph — the offline-first analysis headline (v1.16).

The wow: once sources are downloaded + audited, dependency/impact questions are
answered from the on-disk graph files (_cross_references.json, _page_graph.json,
_source_index.json) with ZERO ServiceNow API calls, instantly, token-cheap.

Contract pinned here:
- Reads ONLY local files — never touches the network (no config/auth use).
- Emits a visible "offline / api_calls=0" signal so the magic is observable.
- When no local analysis exists, fails gracefully with a next_step that guides a
  first-time user to download_app_sources + audit_local_sources (no exception).
"""

import json
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.tools.local_graph_tools import QueryLocalGraphParams, query_local_graph
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def auth() -> MagicMock:
    # A MagicMock so ANY accidental network/auth use is detectable: the tool must
    # never call it. Asserted in test_makes_zero_api_calls.
    return MagicMock()


@pytest.fixture()
def audited_root(tmp_path):
    """A scope root that looks like a completed download + audit."""
    (tmp_path / "_manifest.json").write_text(
        json.dumps({"scope": "x_app", "instance": "https://test.service-now.com"}),
        encoding="utf-8",
    )
    (tmp_path / "_source_index.json").write_text(
        json.dumps(
            [
                {
                    "source_type": "widget",
                    "table": "sp_widget",
                    "sys_id": "w1",
                    "name": "WidgetA",
                    "path": "sp_widget/WidgetA",
                    "active": True,
                },
                {
                    "source_type": "script_include",
                    "table": "sys_script_include",
                    "sys_id": "s1",
                    "name": "UtilSI",
                    "path": "sys_script_include/UtilSI",
                    "active": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "_cross_references.json").write_text(
        json.dumps(
            {
                "outgoing": {
                    "WidgetA": {
                        "providers": ["ProvX"],
                        "script_includes": ["UtilSI"],
                    }
                },
                "incoming": {
                    "UtilSI": [{"name": "WidgetA", "type": "widget"}],
                    "ProvX": [{"name": "WidgetA", "type": "widget"}],
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "_page_graph.json").write_text(
        json.dumps({"Home": ["WidgetA", "WidgetB"]}),
        encoding="utf-8",
    )
    return tmp_path


class TestQueryLocalGraph:
    def test_uses_returns_outgoing_refs(self, config, auth, audited_root):
        result = query_local_graph(
            config,
            auth,
            QueryLocalGraphParams(source_root=str(audited_root), action="uses", name="WidgetA"),
        )
        assert result["success"] is True
        assert "UtilSI" in result["result"]["script_includes"]
        assert "ProvX" in result["result"]["providers"]

    def test_used_by_returns_incoming_callers(self, config, auth, audited_root):
        result = query_local_graph(
            config,
            auth,
            QueryLocalGraphParams(source_root=str(audited_root), action="used_by", name="UtilSI"),
        )
        assert result["success"] is True
        callers = {c["name"] for c in result["result"]}
        assert "WidgetA" in callers

    def test_page_returns_widget_placements(self, config, auth, audited_root):
        result = query_local_graph(
            config,
            auth,
            QueryLocalGraphParams(source_root=str(audited_root), action="page", name="Home"),
        )
        assert result["success"] is True
        assert result["result"] == ["WidgetA", "WidgetB"]

    def test_emits_offline_zero_api_signal(self, config, auth, audited_root):
        # The magic must be visible: every offline answer states it cost 0 API.
        result = query_local_graph(
            config,
            auth,
            QueryLocalGraphParams(source_root=str(audited_root), action="uses", name="WidgetA"),
        )
        assert result["offline"] is True
        assert result["api_calls"] == 0

    def test_makes_zero_api_calls(self, config, auth, audited_root):
        # The auth manager (a MagicMock) must be untouched — proof of zero network.
        query_local_graph(
            config,
            auth,
            QueryLocalGraphParams(source_root=str(audited_root), action="used_by", name="UtilSI"),
        )
        assert auth.mock_calls == []

    def test_missing_analysis_guides_first_time_user(self, config, auth, tmp_path):
        # No _cross_references.json present → graceful failure that tells a
        # newcomer exactly which two tools to run first. Never raises.
        result = query_local_graph(
            config,
            auth,
            QueryLocalGraphParams(source_root=str(tmp_path), action="uses", name="WidgetA"),
        )
        assert result["success"] is False
        assert result["api_calls"] == 0
        assert "audit_local_sources" in result["next_step"]
        assert "download_app_sources" in result["next_step"]

    def test_unknown_name_is_graceful_not_error(self, config, auth, audited_root):
        # Asking about something not in the graph returns an empty, honest answer
        # (the source may simply not reference anything) — not a hard error.
        result = query_local_graph(
            config,
            auth,
            QueryLocalGraphParams(source_root=str(audited_root), action="uses", name="Ghost"),
        )
        assert result["success"] is True
        assert result["result"] == {}
        assert result["found"] is False
