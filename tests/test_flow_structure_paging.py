"""A full page is not a finished read.

`_fetch_flow_structure` fetched each component family with limit=100 and no
total, so a flow with more actions (or logic nodes) than that returned a
SHORTER TREE and called it the structure: the steps past the cap carried no
marker of any kind, and the counts printed on top of them read as exact. The
flow this was measured on already carries 83 logic nodes.

So: page until a short page proves the end, and if the runaway ceiling is
reached anyway, say which family was cut instead of implying nothing was.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.flow_designer_tools import (
    _COMPONENT_CEILING,
    _COMPONENT_PAGE,
    _fetch_flow_structure,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

FLOW = "f" * 32
SNAP = "s" * 32


def _cfg():
    """Basic auth on purpose: this is the Table API path."""
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC, basic=BasicAuthConfig(username="alice", password="pw")
        ),
    )


def _action(i):
    return {
        "sys_id": f"{i:032d}",
        "ui_id": f"ui-{i}",
        "order": str(i),
        "display_text": "",
        "action_type": "Update Record",
    }


def _pager(action_count):
    """sn_query_page stub: the actions table holds `action_count` rows."""

    def _fn(config, auth_manager, *, table, query, fields, limit, offset, **_):
        if table == "sys_hub_flow":
            return ([{"sys_id": FLOW, "name": "F", "label_cache": ""}], None)
        if table != "sys_hub_action_instance_v2":
            return ([], None)
        page = [_action(i) for i in range(offset, min(offset + limit, action_count))]
        return (page, None)

    return _fn


def _structure(action_count):
    with (
        patch("servicenow_mcp.tools.flow_designer_tools._get_snapshot_id", return_value=SNAP),
        patch("servicenow_mcp.tools.flow_designer_tools.batch_get", return_value=None),
        patch(
            "servicenow_mcp.tools.flow_designer_tools.sn_query_page",
            side_effect=_pager(action_count),
        ),
    ):
        return _fetch_flow_structure(_cfg(), MagicMock(), FLOW)


def test_a_flow_larger_than_one_page_is_returned_whole():
    result = _structure(_COMPONENT_PAGE + 30)
    assert result["total_actions"] == _COMPONENT_PAGE + 30
    assert len(result["flat_summary"]) == _COMPONENT_PAGE + 30
    assert "components_truncated" not in result


def test_a_flow_that_exactly_fills_a_page_is_not_reported_as_cut():
    """An exact multiple costs one extra empty page — and must not be flagged."""
    result = _structure(_COMPONENT_PAGE)
    assert result["total_actions"] == _COMPONENT_PAGE
    assert "components_truncated" not in result


def test_a_short_flow_needs_no_second_request():
    result = _structure(7)
    assert result["total_actions"] == 7
    assert "components_truncated" not in result


def test_hitting_the_ceiling_is_reported_as_incomplete():
    result = _structure(_COMPONENT_CEILING + 200)
    assert result["total_actions"] == _COMPONENT_CEILING
    note = result["components_truncated"]
    assert "actions" in note and "INCOMPLETE" in note
    assert "lower bounds" in note, "capped counts must not read as totals"
