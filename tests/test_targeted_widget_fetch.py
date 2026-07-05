"""Targeted widget fetch (download_portal_sources widget_ids=...) invariants.

Pins the fix for the "widget_ids ignored → 20 arbitrary scope widgets" bug:
1. Encoded queries carry NO parentheses (ServiceNow has no grouping syntax;
   "(sys_id=X" parses as an invalid field and can collapse the OR-group into
   match-everything on lenient instances).
2. Rows matching no requested token are DROPPED, never passed through.
3. Unmatched tokens are reported, with a cross-scope probe that distinguishes
   "wrong scope" from "absent on this instance" (wrong-instance/multi-session).
"""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    _fetch_targeted_widget_rows,
    _locate_missing_widget_tokens,
)
from servicenow_mcp.utils.config import ServerConfig

SYS_ID_A = "a" * 32
SYS_ID_B = "b" * 32
WIDGET_FIELDS = "sys_id,name,id,script"


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth_manager():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_targeted_query_has_no_parentheses_and_ors_all_tokens(
    mock_query, mock_config, mock_auth_manager
):
    mock_query.return_value = []

    _fetch_targeted_widget_rows(
        mock_config,
        mock_auth_manager,
        widget_tokens=[SYS_ID_A],
        widget_base_query="sys_scope.scope=x_app",
        widget_fields=WIDGET_FIELDS,
        page_size=50,
    )

    query = mock_query.call_args.kwargs["query"]
    assert "(" not in query and ")" not in query
    assert query == (f"sys_id={SYS_ID_A}^ORid={SYS_ID_A}^ORname={SYS_ID_A}^sys_scope.scope=x_app")


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_rows_matching_no_token_are_dropped(mock_query, mock_config, mock_auth_manager):
    # Server returns one real match plus parser-noise rows (the historical
    # failure: lenient instances matched arbitrary scope widgets).
    mock_query.return_value = [
        {"sys_id": "noise1" + "0" * 26, "id": "other-widget", "name": "Other Widget"},
        {"sys_id": SYS_ID_A, "id": "so-widget", "name": "SO Widget"},
        {"sys_id": "noise2" + "0" * 26, "id": "another", "name": "Another"},
    ]

    rows, unmatched = _fetch_targeted_widget_rows(
        mock_config,
        mock_auth_manager,
        widget_tokens=[SYS_ID_A],
        widget_base_query="",
        widget_fields=WIDGET_FIELDS,
        page_size=50,
    )

    assert [r["sys_id"] for r in rows] == [SYS_ID_A]
    assert unmatched == []


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_unmatched_tokens_are_reported(mock_query, mock_config, mock_auth_manager):
    mock_query.return_value = [
        {"sys_id": SYS_ID_A, "id": "so-widget", "name": "SO Widget"},
    ]

    rows, unmatched = _fetch_targeted_widget_rows(
        mock_config,
        mock_auth_manager,
        widget_tokens=["so-widget", SYS_ID_B, "vo-widget"],
        widget_base_query="sys_scope.scope=x_app",
        widget_fields=WIDGET_FIELDS,
        page_size=50,
    )

    assert [r["sys_id"] for r in rows] == [SYS_ID_A]
    assert unmatched == [SYS_ID_B, "vo-widget"]


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_locate_missing_distinguishes_wrong_scope_from_absent(
    mock_query, mock_config, mock_auth_manager
):
    # No-filter probe finds SYS_ID_B in another scope; "ghost" exists nowhere.
    mock_query.return_value = [
        {"sys_id": SYS_ID_B, "id": "vo-widget", "name": "VO Widget", "sys_scope.scope": "x_other"},
    ]

    messages = _locate_missing_widget_tokens(
        mock_config,
        mock_auth_manager,
        missing_tokens=[SYS_ID_B, "ghost"],
        requested_scope="x_app",
        page_size=50,
    )

    wrong_scope = [m for m in messages if "NOT DOWNLOADED" in m]
    absent = [m for m in messages if "NOT FOUND" in m]
    assert len(wrong_scope) == 1
    assert "x_other" in wrong_scope[0] and SYS_ID_B in wrong_scope[0]
    assert "scope='x_other'" in wrong_scope[0]  # actionable retry command
    assert len(absent) == 1
    assert "ghost" in absent[0]
    assert "https://test.service-now.com" in absent[0]  # wrong-instance diagnostic


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_locate_missing_probe_failure_is_fail_safe(mock_query, mock_config, mock_auth_manager):
    mock_query.side_effect = RuntimeError("network down")

    messages = _locate_missing_widget_tokens(
        mock_config,
        mock_auth_manager,
        missing_tokens=[SYS_ID_B],
        requested_scope="x_app",
        page_size=50,
    )

    assert len(messages) == 1
    assert "NOT FOUND" in messages[0] and SYS_ID_B in messages[0]


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_locate_missing_without_scope_skips_probe(mock_query, mock_config, mock_auth_manager):
    messages = _locate_missing_widget_tokens(
        mock_config,
        mock_auth_manager,
        missing_tokens=["ghost"],
        requested_scope=None,
        page_size=50,
    )

    mock_query.assert_not_called()
    assert len(messages) == 1 and "NOT FOUND" in messages[0]


class TestWrongInstanceLocalTreeHint:
    """Offline anti-wander: a token absent on the current instance but present
    in ANOTHER instance's downloaded tree gets a WRONG INSTANCE hint instead of
    a bare NOT FOUND — zero network (a live sibling probe could pop a login
    window from inside a download)."""

    def _make_tree(self, tmp_path, instance, scope, widget_map):
        import json

        scope_root = tmp_path / instance / scope
        (scope_root / "sp_widget").mkdir(parents=True)
        (scope_root / "sp_widget" / "_map.json").write_text(json.dumps(widget_map))
        return scope_root

    def test_token_in_other_instance_tree_gets_hint(self, tmp_path, monkeypatch):
        from servicenow_mcp.tools import portal_tools

        other_root = self._make_tree(tmp_path, "devinst", "x_app", {"so-widget": SYS_ID_B})
        monkeypatch.setattr(portal_tools, "known_download_roots", lambda: [other_root])

        messages, hinted = portal_tools._locate_tokens_in_other_local_trees(
            [SYS_ID_B, "ghost"], current_instance_name="prodinst"
        )

        assert hinted == {SYS_ID_B}
        assert len(messages) == 1
        assert "WRONG INSTANCE?" in messages[0]
        assert "devinst" in messages[0] and SYS_ID_B in messages[0]

    def test_same_instance_tree_is_skipped(self, tmp_path, monkeypatch):
        from servicenow_mcp.tools import portal_tools

        own_root = self._make_tree(tmp_path, "prodinst", "x_app", {"so-widget": SYS_ID_B})
        monkeypatch.setattr(portal_tools, "known_download_roots", lambda: [own_root])

        messages, hinted = portal_tools._locate_tokens_in_other_local_trees(
            [SYS_ID_B], current_instance_name="prodinst"
        )

        assert messages == [] and hinted == set()

    def test_missing_or_corrupt_map_yields_no_hint(self, tmp_path, monkeypatch):
        from servicenow_mcp.tools import portal_tools

        bare_root = tmp_path / "devinst" / "x_app"
        bare_root.mkdir(parents=True)  # no _map.json at all
        corrupt_root = tmp_path / "devinst2" / "x_app"
        (corrupt_root / "sp_widget").mkdir(parents=True)
        (corrupt_root / "sp_widget" / "_map.json").write_text("not json{{")
        monkeypatch.setattr(portal_tools, "known_download_roots", lambda: [bare_root, corrupt_root])

        messages, hinted = portal_tools._locate_tokens_in_other_local_trees(
            [SYS_ID_B], current_instance_name="prodinst"
        )

        assert messages == [] and hinted == set()

    def test_hinted_token_replaces_bare_not_found(self, tmp_path, monkeypatch):
        # End-to-end through _locate_missing_widget_tokens: the hinted token
        # must NOT also produce the generic NOT FOUND line.
        from unittest.mock import patch as _patch

        from servicenow_mcp.tools import portal_tools

        other_root = self._make_tree(tmp_path, "devinst", "x_app", {"vo": SYS_ID_B})
        monkeypatch.setattr(portal_tools, "known_download_roots", lambda: [other_root])

        config = ServerConfig(
            instance_url="https://prodinst.service-now.com",
            auth={"type": "basic", "basic": {"username": "u", "password": "p"}},
        )
        with _patch.object(portal_tools, "_sn_query_all", return_value=[]):
            messages = portal_tools._locate_missing_widget_tokens(
                config,
                None,
                missing_tokens=[SYS_ID_B],
                requested_scope="x_app",
                page_size=50,
            )

        assert len(messages) == 1
        assert "WRONG INSTANCE?" in messages[0]
        assert not any("NOT FOUND" in m for m in messages)
