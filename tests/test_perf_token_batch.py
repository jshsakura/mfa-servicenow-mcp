"""Performance / token-economy batch: script-body stubbing in the structure
tree (T1), parallel reorder concurrency (L1), and parallel post-PUT save calls
(L2). These pin behavior that saves context tokens and round-trips without
losing information or weakening the safety guards.
"""

import threading
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
from servicenow_mcp.tools.workflow_tools import _REORDER_MAX_PARALLEL, reorder_workflow_activities
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


# ---------------------------------------------------------------------------
# L1 — parallel reorder (wall-clock, order preserved, per-item report intact)
# ---------------------------------------------------------------------------


def _config():
    return ServerConfig(
        instance_url="https://dev.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def test_reorder_runs_patches_in_parallel_preserving_order():
    """Parallelism is proven by concurrency, not by a stopwatch.

    This assertion used to be `elapsed < 0.20` around six real 50ms sleeps. It
    passes alone and fails on a loaded machine — and it sits in the pre-push
    hook, so the way past it is `--no-verify`, which also switches off the
    identity guard. A gate that has to be bypassed is a hole in the gate beside
    it. The barrier below cannot be released unless `cap` PATCHes are genuinely
    in flight at the same moment, so a sequential implementation fails on
    evidence rather than on timing.
    """
    ids = [f"act{i}" for i in range(6)]
    cap = min(_REORDER_MAX_PARALLEL, len(ids))

    # Only the first `cap` arrivals wait: the executor has exactly `cap` workers,
    # so those `cap` tasks must overlap to release each other. The remaining
    # tasks run afterwards and must not wait on a barrier nobody else will reach.
    gate = threading.Barrier(cap, timeout=10)
    lock = threading.Lock()
    arrivals = 0
    in_flight = 0
    peak_in_flight = 0

    def _concurrent_patch(method, url, **kwargs):
        nonlocal arrivals, in_flight, peak_in_flight
        with lock:
            arrivals += 1
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)
            waits = arrivals <= cap
        try:
            if waits:
                gate.wait()  # BrokenBarrierError if the caller is sequential
        finally:
            with lock:
                in_flight -= 1
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        return resp

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_concurrent_patch)
    auth.get_headers = MagicMock(return_value={})

    result = reorder_workflow_activities(
        _config(), auth, {"workflow_id": "wf1", "activity_ids": ids}
    )

    # A sequential run never releases the barrier: every PATCH raises, and
    # _patch_one turns that into success=False.
    assert result["success"] is True, f"reorder did not parallelize: {result}"
    assert peak_in_flight == cap, f"expected {cap} concurrent PATCHes, saw {peak_in_flight}"
    # executor.map preserves order → results align to input ids with rising order.
    assert [r["activity_id"] for r in result["results"]] == ids
    assert [r["new_order"] for r in result["results"]] == [100, 200, 300, 400, 500, 600]


def test_reorder_partial_failure_still_reported_under_parallel():
    def _mr(method, url, **kwargs):
        resp = MagicMock()
        if "act2" in url:
            resp.raise_for_status.side_effect = RuntimeError("denied")
        else:
            resp.raise_for_status = MagicMock()
        return resp

    auth = MagicMock(spec=AuthManager)
    auth.make_request = MagicMock(side_effect=_mr)
    auth.get_headers = MagicMock(return_value={})
    result = reorder_workflow_activities(
        _config(), auth, {"workflow_id": "wf1", "activity_ids": ["act1", "act2", "act3"]}
    )
    assert result["success"] is False
    assert "INCOMPLETE" in result["message"]
    failed = [r for r in result["results"] if not r["success"]]
    assert len(failed) == 1 and failed[0]["activity_id"] == "act2"


# ---------------------------------------------------------------------------
# L2 — parallel post-PUT create_version + verify on save
# ---------------------------------------------------------------------------


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
