"""#1 read-response cache: flow get_detail is the corpus's heaviest read and is
re-fetched identically during migrations. A per-(instance, flow_id, options)
TTL cache serves the repeat for free; any write clears the namespace so a cached
tree never masks the caller's own edit. This is under-fetch-safe — it returns
the SAME body, never a narrowed one.
"""

from unittest.mock import MagicMock, patch

import pytest

import servicenow_mcp.tools.sn_api as sn_api
from servicenow_mcp.tools.flow_tools import (
    ManageFlowDesignerParams,
    _do_get_detail,
    _resolve_flow_id_by_name,
    manage_flow_designer,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    sn_api.invalidate_read_cache()  # isolate every test from module-global state
    yield
    sn_api.invalidate_read_cache()


def _cfg():
    cfg = MagicMock()
    cfg.instance_url = "https://a.example.com"
    return cfg


# --- generic read cache ----------------------------------------------------


def test_read_cache_roundtrip_and_miss():
    assert sn_api.read_cache_get("ns", ("k",)) is None
    sn_api.read_cache_put("ns", ("k",), {"v": 1})
    assert sn_api.read_cache_get("ns", ("k",)) == {"v": 1}


def test_read_cache_namespaces_are_isolated():
    sn_api.read_cache_put("a", ("k",), 1)
    assert sn_api.read_cache_get("b", ("k",)) is None
    assert sn_api.invalidate_read_cache("b") == 0
    assert sn_api.read_cache_get("a", ("k",)) == 1  # untouched


def test_read_cache_invalidate_one_namespace():
    sn_api.read_cache_put("a", ("k",), 1)
    sn_api.read_cache_put("b", ("k",), 2)
    assert sn_api.invalidate_read_cache("a") == 1
    assert sn_api.read_cache_get("a", ("k",)) is None
    assert sn_api.read_cache_get("b", ("k",)) == 2


def test_read_cache_ttl_expiry(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(sn_api.time, "monotonic", lambda: clock["t"])
    sn_api.read_cache_put("ns", ("k",), "v", ttl=10)
    clock["t"] = 1009.0
    assert sn_api.read_cache_get("ns", ("k",)) == "v"  # within TTL
    clock["t"] = 1011.0
    assert sn_api.read_cache_get("ns", ("k",)) is None  # expired


# --- flow get_detail wiring ------------------------------------------------


def test_get_detail_caches_successful_read():
    params = ManageFlowDesignerParams(action="get_detail", flow_id="F1")
    ok = {"success": True, "name": "Flow", "structure": {"nodes": 9}}
    with patch("servicenow_mcp.tools.flow_tools.get_flow_details", return_value=ok) as gfd:
        r1 = _do_get_detail(_cfg(), MagicMock(), params)
        r2 = _do_get_detail(_cfg(), MagicMock(), params)
    assert r1 == r2 == ok
    assert gfd.call_count == 1  # second read served from cache


def test_get_detail_does_not_cache_failure():
    params = ManageFlowDesignerParams(action="get_detail", flow_id="F1")
    err = {"success": False, "error": "boom"}
    with patch("servicenow_mcp.tools.flow_tools.get_flow_details", return_value=err) as gfd:
        _do_get_detail(_cfg(), MagicMock(), params)
        _do_get_detail(_cfg(), MagicMock(), params)
    assert gfd.call_count == 2  # a failure must never be cached


def test_get_detail_cache_keys_on_options():
    p_struct = ManageFlowDesignerParams(action="get_detail", flow_id="F1", include_structure=True)
    p_plain = ManageFlowDesignerParams(action="get_detail", flow_id="F1", include_structure=False)
    ok = {"success": True}
    with patch("servicenow_mcp.tools.flow_tools.get_flow_details", return_value=ok) as gfd:
        _do_get_detail(_cfg(), MagicMock(), p_struct)
        _do_get_detail(_cfg(), MagicMock(), p_plain)  # different options → not a hit
    assert gfd.call_count == 2


def test_write_action_invalidates_cached_detail():
    read_p = ManageFlowDesignerParams(action="get_detail", flow_id="F1")
    ok = {"success": True, "name": "Flow"}
    with (
        patch("servicenow_mcp.tools.flow_tools.get_flow_details", return_value=ok) as gfd,
        patch("servicenow_mcp.tools.flow_tools._do_edit", return_value={"success": True}),
    ):
        _do_get_detail(_cfg(), MagicMock(), read_p)  # prime cache (call 1)
        # A write action clears the flow_detail namespace...
        manage_flow_designer(
            _cfg(), MagicMock(), ManageFlowDesignerParams(action="publish", flow_id="F1")
        )
        _do_get_detail(_cfg(), MagicMock(), read_p)  # must re-fetch (call 2)
    assert gfd.call_count == 2


def test_read_action_does_not_invalidate():
    read_p = ManageFlowDesignerParams(action="get_detail", flow_id="F1")
    ok = {"success": True}
    # _DISPATCH holds the original _do_get_executions, so intercept the deeper
    # get_flow_executions it calls to keep the read-only action off the network.
    with (
        patch("servicenow_mcp.tools.flow_tools.get_flow_details", return_value=ok) as gfd,
        patch(
            "servicenow_mcp.tools.flow_tools.get_flow_executions", return_value={"success": True}
        ),
    ):
        _do_get_detail(_cfg(), MagicMock(), read_p)  # prime (call 1)
        # get_executions is read-only → must NOT clear the cache
        manage_flow_designer(
            _cfg(), MagicMock(), ManageFlowDesignerParams(action="get_executions", flow_id="F1")
        )
        _do_get_detail(_cfg(), MagicMock(), read_p)  # still cached
    assert gfd.call_count == 1


# --- RANK1: get_detail by name (server-side resolve, kills the list→pick→get hop)


def test_get_detail_accepts_flow_name_without_flow_id():
    # The whole point: no flow_id, just a name — validation must allow it.
    p = ManageFlowDesignerParams(action="get_detail", flow_name="My Flow")
    assert p.flow_id is None and p.flow_name == "My Flow"


def test_get_detail_requires_flow_id_or_name():
    with pytest.raises(ValueError, match="flow_id or flow_name"):
        ManageFlowDesignerParams(action="get_detail")


def test_resolve_name_unique_hit_returns_sys_id():
    rows = [{"sys_id": "F9", "name": "My Flow", "type": "flow", "active": "true"}]
    with patch("servicenow_mcp.tools.flow_tools.sn_query_page", return_value=(rows, None)) as q:
        out = _resolve_flow_id_by_name(_cfg(), MagicMock(), "My Flow")
    assert out == {"sys_id": "F9"}
    # exact match query is tried FIRST (name=), so one call suffices.
    assert q.call_args_list[0].kwargs["query"] == "name=My Flow"


def test_resolve_name_ambiguous_returns_candidates():
    rows = [
        {"sys_id": "A", "name": "Order Flow", "type": "flow", "active": "true"},
        {"sys_id": "B", "name": "Order Flow", "type": "subflow", "active": "false"},
    ]
    with patch("servicenow_mcp.tools.flow_tools.sn_query_page", return_value=(rows, None)):
        out = _resolve_flow_id_by_name(_cfg(), MagicMock(), "Order Flow")
    assert out["success"] is False
    assert "ambiguous" in out["error"] or "matched" in out["error"]
    assert {c["sys_id"] for c in out["candidates"]} == {"A", "B"}


def test_resolve_name_not_found():
    with patch("servicenow_mcp.tools.flow_tools.sn_query_page", return_value=([], None)):
        out = _resolve_flow_id_by_name(_cfg(), MagicMock(), "Nope")
    assert out["success"] is False
    assert "No flow found" in out["error"]


def test_get_detail_by_name_resolves_then_fetches_and_caches_by_sys_id():
    # get_detail(flow_name) resolves to a sys_id, fetches once, and a later
    # get_detail(flow_id=<that sys_id>) hits the SAME cache entry — no re-fetch.
    rows = [{"sys_id": "F9", "name": "My Flow", "type": "flow", "active": "true"}]
    ok = {"success": True, "name": "My Flow"}
    with (
        patch("servicenow_mcp.tools.flow_tools.sn_query_page", return_value=(rows, None)) as q,
        patch("servicenow_mcp.tools.flow_tools.get_flow_details", return_value=ok) as gfd,
    ):
        by_name = _do_get_detail(
            _cfg(), MagicMock(), ManageFlowDesignerParams(action="get_detail", flow_name="My Flow")
        )
        by_id = _do_get_detail(
            _cfg(), MagicMock(), ManageFlowDesignerParams(action="get_detail", flow_id="F9")
        )
    assert by_name == by_id == ok
    assert gfd.call_count == 1  # name + sys_id share one cache entry
    assert gfd.call_args.kwargs == {} and gfd.call_args.args[2].flow_id == "F9"
    q.assert_called_once()  # resolve happened exactly once (before the cache hit)


def test_get_detail_by_name_ambiguous_short_circuits_before_fetch():
    rows = [
        {"sys_id": "A", "name": "Dup", "type": "flow", "active": "true"},
        {"sys_id": "B", "name": "Dup", "type": "flow", "active": "true"},
    ]
    with (
        patch("servicenow_mcp.tools.flow_tools.sn_query_page", return_value=(rows, None)),
        patch("servicenow_mcp.tools.flow_tools.get_flow_details") as gfd,
    ):
        out = _do_get_detail(
            _cfg(), MagicMock(), ManageFlowDesignerParams(action="get_detail", flow_name="Dup")
        )
    assert out["success"] is False and out["candidates"]
    gfd.assert_not_called()  # never fetch on an ambiguous name
