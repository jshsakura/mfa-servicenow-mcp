"""Tests for the per-instance table-availability cache in portal_tools.

Some Service Portal m2m tables (notably m2m_sp_widget_angular_provider) are
absent on certain ServiceNow releases and the Table API hard-fails them with
400 "Invalid table". The cache learns this from the first real query and lets
dependent reads skip the dead query for the rest of the process — without ever
issuing an extra probe request.
"""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.portal_tools import (
    _TABLE_AVAILABILITY,
    ANGULAR_PROVIDER_M2M_TABLE,
    GetWidgetBundleParams,
    _note_table_response,
    _table_known_absent,
    get_widget_bundle,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

INSTANCE = "https://test.service-now.com"
BAD_400 = {"success": False, "message": "Query failed: HTTP Error 400: Bad Request"}


@pytest.fixture(autouse=True)
def _clear_cache():
    """Isolate the process-global cache between tests."""
    _TABLE_AVAILABILITY.clear()
    yield
    _TABLE_AVAILABILITY.clear()


@pytest.fixture()
def cfg():
    return ServerConfig(
        instance_url=INSTANCE,
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


@pytest.fixture()
def auth():
    return MagicMock(spec=AuthManager)


# ---------------------------------------------------------------------------
# Unit: _table_known_absent / _note_table_response
# ---------------------------------------------------------------------------


def test_unknown_table_is_not_absent(cfg):
    # Default: no prior verdict -> run the real query.
    assert _table_known_absent(cfg, ANGULAR_PROVIDER_M2M_TABLE) is False


def test_success_marks_present(cfg):
    _note_table_response(cfg, ANGULAR_PROVIDER_M2M_TABLE, {"success": True, "results": []})
    assert _table_known_absent(cfg, ANGULAR_PROVIDER_M2M_TABLE) is False
    assert _TABLE_AVAILABILITY[(INSTANCE, ANGULAR_PROVIDER_M2M_TABLE)] is True


def test_400_marks_absent(cfg):
    _note_table_response(cfg, ANGULAR_PROVIDER_M2M_TABLE, BAD_400)
    assert _table_known_absent(cfg, ANGULAR_PROVIDER_M2M_TABLE) is True


def test_transient_failure_is_not_cached(cfg):
    # A 401/timeout (no '400' in the message) must NOT suppress the table.
    _note_table_response(
        cfg,
        ANGULAR_PROVIDER_M2M_TABLE,
        {"success": False, "message": "Query failed: HTTP Error 401: Unauthorized"},
    )
    assert (INSTANCE, ANGULAR_PROVIDER_M2M_TABLE) not in _TABLE_AVAILABILITY
    assert _table_known_absent(cfg, ANGULAR_PROVIDER_M2M_TABLE) is False


def test_cache_is_per_instance(cfg, auth):
    other = ServerConfig(
        instance_url="https://other.service-now.com",
        auth=cfg.auth,
    )
    _note_table_response(cfg, ANGULAR_PROVIDER_M2M_TABLE, BAD_400)
    assert _table_known_absent(cfg, ANGULAR_PROVIDER_M2M_TABLE) is True
    # A different instance is unaffected.
    assert _table_known_absent(other, ANGULAR_PROVIDER_M2M_TABLE) is False


# ---------------------------------------------------------------------------
# Integration: get_widget_bundle skips the m2m query after a 400
# ---------------------------------------------------------------------------


def _widget_ok():
    return {"success": True, "results": [{"sys_id": "w1", "name": "W1"}]}


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_bundle_caches_absent_and_skips_second_m2m(mock_q, cfg, auth):
    # Call 1: widget OK, then m2m 400 -> cache absent. Call 2: widget OK only;
    # the m2m query must be skipped entirely (no third sn_query for it).
    mock_q.side_effect = [_widget_ok(), BAD_400, _widget_ok()]

    params = GetWidgetBundleParams(
        widget_id="w1", include_providers=True, include_dependencies=False
    )

    first = get_widget_bundle(cfg, auth, params)
    assert first["angular_providers"] == []
    assert _table_known_absent(cfg, ANGULAR_PROVIDER_M2M_TABLE) is True

    second = get_widget_bundle(cfg, auth, params)
    assert second["angular_providers"] == []

    # 2 calls for the first bundle (widget + m2m-400) + 1 for the second
    # (widget only, m2m skipped) = 3. A 4th would mean the skip failed.
    assert mock_q.call_count == 3


@patch("servicenow_mcp.tools.portal_tools.sn_query")
def test_bundle_runs_m2m_when_table_present(mock_q, cfg, auth):
    # Healthy instance: m2m returns rows -> providers resolved, cache=present.
    mock_q.side_effect = [
        _widget_ok(),
        {"success": True, "results": [{"sp_angular_provider": "p1"}]},
        {"success": True, "results": [{"name": "ProvA", "sys_id": "p1", "type": "factory"}]},
        _widget_ok(),
        {"success": True, "results": [{"sp_angular_provider": "p1"}]},
        {"success": True, "results": [{"name": "ProvA", "sys_id": "p1", "type": "factory"}]},
    ]
    params = GetWidgetBundleParams(
        widget_id="w1", include_providers=True, include_dependencies=False
    )

    first = get_widget_bundle(cfg, auth, params)
    assert [p["name"] for p in first["angular_providers"]] == ["ProvA"]
    assert _TABLE_AVAILABILITY[(INSTANCE, ANGULAR_PROVIDER_M2M_TABLE)] is True

    # Present table is NOT skipped — the m2m query still runs the second time.
    second = get_widget_bundle(cfg, auth, params)
    assert [p["name"] for p in second["angular_providers"]] == ["ProvA"]
    assert mock_q.call_count == 6
