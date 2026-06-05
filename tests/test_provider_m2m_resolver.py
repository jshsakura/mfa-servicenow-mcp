"""Tests for resolve_angular_provider_m2m — the widget<->Angular-provider
junction table is discovered from sys_dictionary (no hardcoded name), because
m2m table names differ across ServiceNow instances. Covers discovery, the
candidate-probe fallback, display-value coercion, and per-instance caching.
"""

from unittest.mock import MagicMock, patch

import servicenow_mcp.tools.portal_dev_tools as pdt


def _cfg(url="https://x.service-now.com"):
    c = MagicMock()
    c.instance_url = url
    return c


def test_discovers_table_referencing_both_widget_and_provider():
    pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()
    # 1st _sn_get: tables with a reference column to sp_angular_provider.
    # 2nd _sn_get: confirm that table also references sp_widget.
    with patch.object(
        pdt,
        "_sn_get",
        side_effect=[
            ([{"name": "m2m_sp_ng_pro_sp_widget"}, {"name": "x_other_ref"}], None),
            ([{"element": "sp_widget"}], None),
        ],
    ):
        table = pdt.resolve_angular_provider_m2m(_cfg(), MagicMock())
    assert table == "m2m_sp_ng_pro_sp_widget"


def test_discovery_coerces_display_value_dict_name():
    pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()
    with patch.object(
        pdt,
        "_sn_get",
        side_effect=[
            ([{"name": {"value": "m2m_sp_ng_pro_sp_widget", "display_value": "x"}}], None),
            ([{"element": "sp_widget"}], None),
        ],
    ):
        table = pdt.resolve_angular_provider_m2m(_cfg(), MagicMock())
    assert table == "m2m_sp_ng_pro_sp_widget"


def test_falls_back_to_candidate_probe_when_dictionary_yields_nothing():
    pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()

    def fake(config, auth, table, query, fields, limit=20):
        if table == "sys_dictionary":
            return ([], None)  # discovery finds no junction
        if table == "m2m_sp_ng_pro_sp_widget":
            raise RuntimeError("400 Invalid table")  # absent on this instance
        if table == "m2m_sp_widget_angular_provider":
            return ([], None)  # this name exists here
        raise AssertionError(f"unexpected probe: {table}")

    with patch.object(pdt, "_sn_get", side_effect=fake):
        table = pdt.resolve_angular_provider_m2m(_cfg(), MagicMock())
    assert table == "m2m_sp_widget_angular_provider"


def test_result_is_cached_per_instance():
    pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()
    with patch.object(
        pdt,
        "_sn_get",
        side_effect=[
            ([{"name": "m2m_sp_ng_pro_sp_widget"}], None),
            ([{"element": "sp_widget"}], None),
        ],
    ) as mock_get:
        first = pdt.resolve_angular_provider_m2m(_cfg(), MagicMock())
        second = pdt.resolve_angular_provider_m2m(_cfg(), MagicMock())
    assert first == second == "m2m_sp_ng_pro_sp_widget"
    # Second call served from cache — no extra dictionary round-trips.
    assert mock_get.call_count == 2


def test_dictionary_unreadable_falls_back_without_crashing():
    pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()

    def fake(config, auth, table, query, fields, limit=20):
        if table == "sys_dictionary":
            raise RuntimeError("dictionary blocked")
        if table == "m2m_sp_ng_pro_sp_widget":
            return ([], None)  # first candidate exists
        raise AssertionError(f"unexpected probe: {table}")

    with patch.object(pdt, "_sn_get", side_effect=fake):
        table = pdt.resolve_angular_provider_m2m(_cfg(), MagicMock())
    assert table == "m2m_sp_ng_pro_sp_widget"
