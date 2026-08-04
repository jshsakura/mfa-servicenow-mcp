"""Performance / token-economy batch: script-body stubbing in the structure
tree (T1), parallel post-PUT save calls (L2), and the fused flow-structure read
(L3). These pin behavior that saves context tokens and round-trips without
losing information or weakening the safety guards.

The old L1 group covered `reorder_workflow_activities`, which was removed: it
PATCHed an `order` column `wf_activity` does not have. Its round-trip and
parallelism tests all passed against a mock that echoed the field back, while
the tool changed nothing on a real instance.
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.flow_designer_tools import (
    _SCRIPT_STUB_MIN_CHARS,
    GetFlowDetailsParams,
    _compact_triggers,
    get_flow_details,
    render_flow_compact,
)
from servicenow_mcp.tools.flow_edit_tools import ManageFlowEditParams, manage_flow_edit
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def _browser_cfg():
    return ServerConfig(
        instance_url="https://dev.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


# ---------------------------------------------------------------------------
# T1 — script-body stubbing in the compact structure tree
# ---------------------------------------------------------------------------

_BIG_SCRIPT = "var x = 1;\n" * 200  # ~2KB, well over the stub threshold


def _flow_with_script():
    return {
        "id": "f1",
        "name": "Scripted Flow",
        "scope": "sc",
        "actionInstances": [
            {
                "id": "a1",
                "uiUniqueIdentifier": "u-a1",
                "name": "Run Script",
                "type": "script",
                "order": 1,
                "inputs": [{"name": "script", "value": _BIG_SCRIPT}],
            }
        ],
        "flowLogicInstances": [],
        "subFlowInstances": [],
        "triggerInstances": [],
    }


def test_render_flow_compact_stubs_script_body_by_default():
    out = render_flow_compact(_flow_with_script())
    tree = out["tree"]
    assert _BIG_SCRIPT not in tree, "full script body must not be inlined by default"
    assert "«script:" in tree
    assert "201 lines" in tree  # 200 newlines + 1
    assert "read_action" in tree  # cites how to fetch the real body


def test_render_flow_compact_keeps_script_when_requested():
    out = render_flow_compact(_flow_with_script(), include_scripts=True)
    assert _BIG_SCRIPT in out["tree"]


def test_short_script_is_not_stubbed():
    flow = _flow_with_script()
    short = "gs.info('hi');"
    assert len(short) <= _SCRIPT_STUB_MIN_CHARS
    flow["actionInstances"][0]["inputs"][0]["value"] = short
    out = render_flow_compact(flow)
    assert short in out["tree"]
    assert "«script:" not in out["tree"]


def test_non_script_inputs_are_never_stubbed():
    flow = _flow_with_script()
    flow["actionInstances"][0]["inputs"] = [{"name": "table", "value": "incident"}]
    out = render_flow_compact(flow)
    assert "incident" in out["tree"]
    assert "«script:" not in out["tree"]


def test_checkout_path_stubs_scripts(tmp_path, monkeypatch):
    # manage_flow_edit action=checkout returns render_flow_compact — the common
    # read path — and must stub the script body, never inline it.
    import servicenow_mcp.tools.flow_edit_tools as fet

    monkeypatch.setattr(fet, "_CHECKOUT_DIR", tmp_path)
    flow = _flow_with_script()
    flow["security"] = {"can_write": True}

    def _mr(method, url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if "/api/now/table/" in url:
            resp.json.return_value = {"result": [{"sys_id": "f" * 32}]}
        else:
            resp.json.return_value = {"result": flow}
        return resp

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    result = manage_flow_edit(
        _browser_cfg(), auth, ManageFlowEditParams(action="checkout", flow_id="f" * 32)
    )
    assert result["success"] is True
    assert _BIG_SCRIPT not in result["summary"]["tree"]
    assert "«script:" in result["summary"]["tree"]


# ---------------------------------------------------------------------------
# T2 — trigger compaction (raw trigger rows -> {id,type,table,condition})
# ---------------------------------------------------------------------------

_RAW_TRIGGER = {
    "id": "trg1",
    "type": "RECORD",
    "sys_class_name": "sys_hub_trigger_instance",
    "some_verbose_field": "x" * 500,
    "inputs": [
        {"name": "table", "value": "incident", "displayValue": "Incident"},
        {"name": "condition", "value": "active=true"},
        {"name": "noise", "value": "y" * 500},
    ],
}


def test_compact_triggers_keeps_only_essential_fields():
    out = _compact_triggers([_RAW_TRIGGER])
    assert out == [
        {"id": "trg1", "type": "RECORD", "table": "Incident", "condition": "active is true"}
    ]
    # the 500-char noise fields are gone
    assert "noise" not in str(out)
    assert "some_verbose_field" not in str(out)


def test_render_flow_compact_uses_compacted_triggers():
    flow = _flow_with_script()
    flow["triggerInstances"] = [_RAW_TRIGGER]
    out = render_flow_compact(flow)
    assert out["triggers"] == [
        {"id": "trg1", "type": "RECORD", "table": "Incident", "condition": "active is true"}
    ]


def test_get_detail_compacts_triggers_by_default_raw_when_summary_off():
    def _mr(method, url, **kwargs):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"result": {"id": "flow1", "name": "F", "triggerInstances": []}}
        return resp

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)

    with patch(
        "servicenow_mcp.tools.flow_designer_tools._build_processflow_detail",
        return_value={"triggers": [_RAW_TRIGGER], "actions": []},
    ):
        compact = get_flow_details(
            _browser_cfg(),
            auth,
            GetFlowDetailsParams(flow_id="flow1", include_triggers=True, include_structure=False),
        )
        raw = get_flow_details(
            _browser_cfg(),
            auth,
            GetFlowDetailsParams(
                flow_id="flow1",
                include_triggers=True,
                include_structure=False,
                summary_format=False,
            ),
        )

    assert compact["triggers"] == [
        {"id": "trg1", "type": "RECORD", "table": "Incident", "condition": "active is true"}
    ]
    # summary_format=False keeps the full raw trigger row (escape hatch)
    assert raw["triggers"][0]["some_verbose_field"] == "x" * 500


def _config():
    return ServerConfig(
        instance_url="https://dev.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def test_save_verify_still_correct_with_parallel_version_row():
    calls = []

    def _mr(method, url, **kwargs):
        calls.append((method, url))
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if method == "GET" and "/processflow/flow/" in url:
            # verify re-read shows our value persisted
            resp.json.return_value = {
                "result": {
                    "actionInstances": [
                        {"id": "a1", "inputs": [{"name": "table", "value": "incident"}]}
                    ]
                }
            }
        else:
            resp.json.return_value = {"result": {}}
        return resp

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    checkout = {
        "id": "f1",
        "scope": "sc",
        "actionInstances": [{"id": "a1", "inputs": [{"name": "table", "value": "incident"}]}],
    }
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _browser_cfg(),
            auth,
            ManageFlowEditParams(action="save", flow_id="f" * 32, verify=True),
        )
    assert result["success"] is True
    assert result["verified"] is True
    # Both the version-row POST and the verify GET were issued.
    assert any(m == "POST" and "/versioning/" in u for m, u in calls)
    assert any(m == "GET" and "/processflow/flow/" in u for m, u in calls)


def test_save_without_verify_still_creates_version_row():
    calls = []

    def _mr(method, url, **kwargs):
        calls.append((method, url))
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"result": {}}
        return resp

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    checkout = {"id": "f1", "scope": "sc"}
    with (
        patch("servicenow_mcp.tools.flow_edit_tools._load_checkout", return_value=checkout),
        patch("servicenow_mcp.tools.flow_edit_tools._checkout_path"),
    ):
        result = manage_flow_edit(
            _browser_cfg(),
            auth,
            ManageFlowEditParams(action="save", flow_id="f" * 32, verify=False),
        )
    assert result["success"] is True
    assert any(m == "POST" and "/versioning/" in u for m, u in calls)
    # No verify re-read when verify=False.
    assert not any(m == "GET" and "/processflow/flow/" in u for m, u in calls)


# ---------------------------------------------------------------------------
# L3 — the flow-structure Table-API fallback fuses its three component reads
#
# actions / logic / subflows differ only by table and field list: same snapshot,
# same limit. Three sequential GETs on a 150-300ms link is most of the wall
# clock of a read that returns one tree. The round-trip counts below are the
# point of these tests — a regression that re-adds a trip fails here, not in
# review (#68 invariant).
# ---------------------------------------------------------------------------


def _served(rows_by_id):
    return {rid: {"status_code": 200, "body": {"result": rows}} for rid, rows in rows_by_id.items()}


def _component(sys_id, order):
    return {
        "sys_id": sys_id,
        "name": sys_id,
        "order": str(order),
        "position": str(order),
        "nesting_parent": "",
        "compilable_type": "",
    }


def _structure_under(batch_return, query_side_effect):
    """Run the fallback with the batch layer stubbed; report both call counts."""
    from servicenow_mcp.tools import flow_designer_tools as fdt

    with (
        patch.object(fdt, "_try_processflow_api", return_value=None),
        patch.object(fdt, "_get_snapshot_id", return_value="snap1"),
        patch.object(
            fdt,
            "_fetch_subflow_bindings",
            return_value={
                "subflow_bindings": [],
                "mismatch_summary": {"mismatch_count": 0, "mismatches": []},
            },
        ),
        patch.object(fdt, "batch_get", return_value=batch_return) as batch,
        patch.object(fdt, "sn_query_page", side_effect=query_side_effect) as page,
    ):
        result = fdt._fetch_flow_structure(_config(), MagicMock(spec=AuthManager), "flow1")
    return result, batch, page


_FLOW_ROW = ([{"sys_id": "flow1", "name": "Flow", "label_cache": ""}], 1)


def test_the_three_component_reads_ride_one_round_trip():
    served = _served(
        {
            "actions": [_component("a1", 100)],
            "logic": [_component("l1", 200)],
            "subflows": [_component("s1", 300)],
        }
    )

    result, batch, page = _structure_under(served, [_FLOW_ROW])

    assert (result["total_actions"], result["total_logic"], result["total_subflows"]) == (1, 1, 1)
    assert batch.call_count == 1
    # The only direct GET left is the flow record itself.
    assert page.call_count == 1
    # All three sub-requests carry display values — the tree shows labels, not sys_ids.
    urls = [url for _rid, url in batch.call_args[0][2]]
    assert len(urls) == 3
    assert all("sysparm_display_value=true" in url for url in urls)
    assert all("sysparm_query=flow%3Dsnap1" in url for url in urls)


def test_an_instance_without_the_batch_api_still_gets_the_whole_tree():
    # batch_get returns None when the endpoint is absent — every family falls
    # back to the GET it would have made anyway.
    result, batch, page = _structure_under(
        None,
        [
            _FLOW_ROW,
            ([_component("a1", 100)], 1),
            ([_component("l1", 200)], 1),
            ([_component("s1", 300)], 1),
        ],
    )

    assert (result["total_actions"], result["total_logic"], result["total_subflows"]) == (1, 1, 1)
    assert batch.call_count == 1
    assert page.call_count == 4


def test_a_sub_request_the_server_skipped_is_refetched_not_dropped():
    """A partly-served batch must not read as a flow with fewer steps."""
    served = _served({"actions": [_component("a1", 100)], "subflows": [_component("s1", 300)]})

    result, batch, page = _structure_under(served, [_FLOW_ROW, ([_component("l1", 200)], 1)])

    assert (result["total_actions"], result["total_logic"], result["total_subflows"]) == (1, 1, 1)
    assert batch.call_count == 1
    assert page.call_count == 2  # flow record + the one missing family
    assert page.call_args_list[-1].kwargs["table"] == "sys_hub_flow_logic_instance_v2"


def test_a_sub_request_that_failed_is_refetched_not_treated_as_empty():
    served = {
        "actions": {"status_code": 200, "body": {"result": [_component("a1", 100)]}},
        "logic": {"status_code": 403, "body": None},
        "subflows": {"status_code": 200, "body": {"result": []}},
    }

    result, _batch, page = _structure_under(served, [_FLOW_ROW, ([_component("l1", 200)], 1)])

    # 403 -> refetched; a genuinely empty 200 -> believed, not refetched.
    assert result["total_logic"] == 1
    assert result["total_subflows"] == 0
    assert page.call_count == 2
