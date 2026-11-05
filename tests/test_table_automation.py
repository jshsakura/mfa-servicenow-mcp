"""get_table_automation: parent chain, ordering, operation filter, flow join, guards."""

from unittest.mock import MagicMock, patch

import requests

from servicenow_mcp.tools import table_automation_tools as ta
from servicenow_mcp.tools.table_automation_tools import (
    TableAutomationParams,
    get_table_automation,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

CLS_INC = "aaaa1111bbbb2222cccc3333dddd1111"
CLS_TASK = "aaaa1111bbbb2222cccc3333dddd2222"
TRIG = "aaaa1111bbbb2222cccc3333dddd3333"
TRIG2 = "aaaa1111bbbb2222cccc3333dddd4444"
FLOW = "aaaa1111bbbb2222cccc3333dddd5555"


def cell(value, display=None):
    return {"value": value, "display_value": value if display is None else display}


def row(**kw):
    return {k: (v if isinstance(v, dict) else cell(v)) for k, v in kw.items()}


class Fake:
    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    def __call__(self, config, auth, *, table, query, fields, limit, offset, **kw):
        self.calls.append((table, query))
        handler = self.handlers.get(table)
        if handler is None:
            return [], 0
        out = handler(query) if callable(handler) else handler
        if isinstance(out, Exception):
            raise out
        return out


def db_object(query):
    if query == "name=incident":
        return [row(name="incident", super_class=CLS_TASK)], 1
    if query == "name=ghost":
        return [], 0
    if query == f"sys_id={CLS_TASK}":
        return [row(name="task", super_class="")], 1
    return [], 0


def cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def run(handlers, **kw):
    fake = Fake({"sys_db_object": db_object, **handlers})
    with (
        patch.object(ta, "_page", wraps=ta._page) as _p,
        patch("servicenow_mcp.tools.record_context_tools.sn_query_page", fake),
    ):
        del _p
        out = get_table_automation(
            cfg(), MagicMock(), TableAutomationParams(**{"table": "incident", **kw})
        )
    return out, fake


def br(name, when, order, **kw):
    base = dict(
        name=name,
        collection="incident",
        when=when,
        order=str(order),
        active="true",
        action_insert="true",
        action_update="false",
        action_delete="false",
        action_query="false",
        abort_action="false",
    )
    base.update(kw)
    return row(**base)


def test_parent_chain_resolved_and_queried():
    out, fake = run({})
    assert out["success"] and out["tables_covered"] == ["incident", "task"]
    sys_script = [q for t, q in fake.calls if t == "sys_script"][0]
    assert sys_script.startswith("collectionINincident,task")
    # one read per level: incident row, then task row
    assert [q for t, q in fake.calls if t == "sys_db_object"] == [
        "name=incident",
        f"sys_id={CLS_TASK}",
    ]


def test_no_inheritance_skips_parent_reads():
    out, fake = run({}, include_inherited=False)
    assert out["tables_covered"] == ["incident"]
    assert len([c for c in fake.calls if c[0] == "sys_db_object"]) == 1


def test_chain_capped_at_six_levels():
    def chain(query):
        if query == "name=incident":
            return [row(name="incident", super_class="aaaa1111bbbb2222cccc3333dddd0001")], 1
        n = int(query[-4:])
        return [row(name=f"lvl{n}", super_class=f"aaaa1111bbbb2222cccc3333dddd{n + 1:04d}")], 1

    out, _ = run({"sys_db_object": chain})
    assert len(out["tables_covered"]) == 7
    assert out["parent_chain"]["complete"] is False


def test_business_rules_ordered_and_origin_and_operation_filter():
    rows = [
        br("async one", "async", 100, sys_scope=cell("global")),
        br("after one", "after", 50),
        br("before late", "before", 300, condition="current.active==true"),
        br("before early", "before", 100, action_update="true", sys_policy="read"),
    ]
    out, fake = run({"sys_script": (rows, 4)})
    names = [r["name"] for r in out["business_rules"]["rows"]]
    assert names == ["before early", "before late", "after one", "async one"]
    first = out["business_rules"]["rows"][0]
    assert first["fires_on"] == ["insert", "update"]
    assert out["business_rules"]["rows"][1]["condition"] == "current.active==true"
    assert out["business_rules"]["rows"][3]["origin"] == {"scope": "global"}
    assert out["summary"]["business_rules"] == 4

    _, fake = run({"sys_script": (rows, 4)}, operation="update")
    q = [q for t, q in fake.calls if t == "sys_script"][0]
    assert "action_update=true" in q and "active=true" in q


def test_inactive_included_drops_active_filter():
    _, fake = run({}, include_inactive=True)
    q = [q for t, q in fake.calls if t == "sys_script"][0]
    assert "active=true" not in q


def test_inherited_rows_are_labelled():
    rows = [br("task rule", "before", 10, collection="task")]
    out, _ = run({"sys_script": (rows, 1)})
    assert out["business_rules"]["rows"][0]["inherited_from"] == "task"


def test_flow_trigger_joins_flow():
    trig = [
        row(
            sys_id=TRIG,
            table="incident",
            condition="priority=1",
            on_insert="true",
            on_update="false",
            run_on_extended="false",
            run_flow_in="background",
        ),
        row(
            sys_id=TRIG2,
            table="task",
            on_insert="true",
            on_update="true",
            run_on_extended="true",
            run_flow_in="foreground",
        ),
    ]
    flows = [
        row(
            sys_id=FLOW,
            name="Notify on P1",
            active="true",
            status="Published",
            remote_trigger_id=TRIG,
        )
    ]
    out, fake = run({"sys_flow_record_trigger": (trig, 2), "sys_hub_flow": (flows, 1)})
    rows = out["flow_triggers"]["rows"]
    assert rows[0]["flow"] == {"name": "Notify on P1", "active": True, "status": "Published"}
    assert rows[0]["condition"] == "priority=1" and rows[0]["fires_on"] == ["insert"]
    assert rows[1]["flow"] is None and rows[1]["inherited_from"] == "task"
    q = [q for t, q in fake.calls if t == "sys_hub_flow"][0]
    assert q == f"remote_trigger_idIN{TRIG},{TRIG2}"


def test_inactive_flow_dropped_by_default():
    trig = [row(sys_id=TRIG, table="incident", on_insert="true", on_update="true")]
    flows = [row(sys_id=FLOW, name="Old", active="false", status="Draft", remote_trigger_id=TRIG)]
    out, _ = run({"sys_flow_record_trigger": (trig, 1), "sys_hub_flow": (flows, 1)})
    assert out["flow_triggers"]["rows"] == []
    out, _ = run(
        {"sys_flow_record_trigger": (trig, 1), "sys_hub_flow": (flows, 1)}, include_inactive=True
    )
    assert out["flow_triggers"]["rows"][0]["flow"]["active"] is False


def test_delete_operation_flow_triggers_not_applicable():
    out, _ = run({}, operation="delete")
    assert "not_applicable" in out["flow_triggers"]


def test_catalog_policies_excluded_by_class():
    _, fake = run({})
    q = [q for t, q in fake.calls if t == "sys_ui_policy"][0]
    assert "sys_class_name=sys_ui_policy" in q


def test_failed_category_is_unchecked_not_empty():
    err = requests.exceptions.ConnectionError("boom")
    out, _ = run({"sys_ui_action": err})
    assert out["ui_actions"]["checked"] is False and "because" in out["ui_actions"]
    assert out["summary"]["ui_actions"] == "unread"
    assert out["summary"]["business_rules"] == 0


def test_capped_category_reports_incomplete():
    rows = [br(f"r{i}", "before", i) for i in range(50)]
    out, _ = run({"sys_script": (rows, 73)})
    assert out["business_rules"]["complete"] is False
    assert out["business_rules"]["total"] == 73


def test_unknown_table_verdict():
    verdict = {
        "success": False,
        "error": "unknown_table",
        "availability": "absent",
        "table": "ghost",
    }
    with patch.object(ta, "_read_failure_verdict", return_value=verdict):
        out, _ = run({}, table="ghost")
    assert out["error"] == "unknown_table" and out["availability"] == "absent"


def test_unknown_table_without_verdict_is_undetermined():
    with patch.object(ta, "_read_failure_verdict", return_value=None):
        out, _ = run({}, table="ghost")
    assert out["success"] is False and out["availability"] == "undetermined"


def test_bad_operation():
    out, _ = run({}, operation="merge")
    assert out["error"] == "bad_operation"


def test_parent_rows_follow_measured_inheritance_flags():
    # Measured columns: sys_script_client.applies_extended, sys_ui_policy.inherit,
    # sys_flow_record_trigger.run_on_extended. Off on a parent row → not for children.
    handlers = {
        "sys_script_client": (
            [
                row(name="own", table="incident", active="true", applies_extended="false"),
                row(name="parent_on", table="task", active="true", applies_extended="true"),
                row(name="parent_off", table="task", active="true", applies_extended="false"),
            ],
            3,
        ),
        "sys_ui_policy": (
            [row(short_description="p_off", table="task", active="true", inherit="false")],
            1,
        ),
        "sysevent_email_action": (
            [row(name="n_task", collection="task", active="true", action_insert="true")],
            1,
        ),
        "sys_flow_record_trigger": (
            [
                row(sys_id=TRIG, table="task", on_insert="true", run_on_extended="false"),
                row(sys_id=TRIG2, table="task", on_insert="true", run_on_extended="true"),
            ],
            2,
        ),
    }
    out, _ = run(handlers)
    names = [r["name"] for r in out["client_scripts"]["rows"]]
    assert sorted(names) == ["own", "parent_on"]
    assert out["client_scripts"]["parent_rows_not_inherited"] == 1
    assert out["ui_policies"]["rows"] == [] and out["ui_policies"]["parent_rows_not_inherited"] == 1
    assert out["notifications"]["rows"][0]["applies_here"] == "not_verified"
    assert len(out["flow_triggers"]["rows"]) == 1
    assert out["flow_triggers"]["parent_rows_not_inherited"] == 1


# ---------------------------------------------------------------------------
# change_request: change models and approval policies
# ---------------------------------------------------------------------------


def chg_db_object(query):
    if query == "name=change_request":
        return [row(name="change_request", super_class=CLS_TASK)], 1
    return db_object(query)


def run_change(handlers, **kw):
    return run({"sys_db_object": chg_db_object, **handlers}, table="change_request", **kw)


def model(name, default="false", table="change_request", **kw):
    return row(
        name=name,
        table_name=table,
        active="true",
        default_change_model=default,
        state_field="state",
        **kw,
    )


def test_change_categories_only_on_change_request():
    out, fake = run({})
    assert "change_models" not in out and "approval_policies" not in out
    assert not [t for t, _ in fake.calls if t in ("chg_model", "chg_policy_approval")]


def test_change_models_and_policies_for_change_request():
    models = [model("Normal", default="true"), model("Emergency", sys_scope=cell("global"))]
    pols = [
        row(
            name="Emergency Policy",
            active="true",
            execution=cell("all", "Run all decisions that match"),
            answer_table="chg_approval_def",
            label="",
        )
    ]
    out, fake = run_change({"chg_model": (models, 2), "chg_policy_approval": (pols, 1)})
    assert out["summary"]["change_models"] == 2 and out["summary"]["approval_policies"] == 1
    rows = out["change_models"]["rows"]
    assert rows[0]["default_change_model"] is True and rows[0]["state_field"] == "state"
    assert rows[1]["origin"] == {"scope": "global"} and out["change_models"]["complete"] is True
    pol = out["approval_policies"]["rows"][0]
    assert pol["applies_to"] == "not_verified" and pol["answer_table"] == "chg_approval_def"
    assert pol["execution"] == "Run all decisions that match"
    assert "not_verified" in out["approval_policies"]
    q = [q for t, q in fake.calls if t == "chg_model"][0]
    assert q == "table_nameINchange_request,task^active=true"
    assert [q for t, q in fake.calls if t == "chg_policy_approval"] == ["active=true"]


def test_change_model_on_parent_table_is_labelled_and_inactive_filter_drops():
    models = [model("Task wide", table="task")]
    out, fake = run_change({"chg_model": (models, 1)}, include_inactive=True)
    assert out["change_models"]["rows"][0]["inherited_from"] == "task"
    assert "active=true" not in [q for t, q in fake.calls if t == "chg_model"][0]
    assert [q for t, q in fake.calls if t == "chg_policy_approval"] == [""]


def test_change_categories_capped_and_unreadable_are_stated():
    models = [model(f"m{i}") for i in range(50)]
    out, _ = run_change(
        {
            "chg_model": (models, 80),
            "chg_policy_approval": ServiceError(),
        }
    )
    assert out["change_models"]["complete"] is False and out["change_models"]["total"] == 80
    assert out["approval_policies"]["checked"] is False
    assert out["summary"]["approval_policies"] == "unread"


class ServiceError(Exception):
    def __init__(self):
        super().__init__("HTTP 403")
