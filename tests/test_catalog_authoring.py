"""Authoring actions of manage_catalog: create_item, copy_item, sets, choices, scripts."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import catalog as svc
from servicenow_mcp.tools.catalog_tools import ManageCatalogParams, manage_catalog
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

ITEM = "aaaa1111bbbb2222cccc3333dddd4444"
VAR_A = "aaaa1111bbbb2222cccc3333dddd0001"
VAR_B = "aaaa1111bbbb2222cccc3333dddd0002"
SET1 = "aaaa1111bbbb2222cccc3333dddd0005"
POL = "aaaa1111bbbb2222cccc3333dddd0006"


def _config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


class Fake:
    """Tiny in-memory instance: reads by (table, query-substring), records writes."""

    def __init__(self, data=None, fail_on=None):
        self.data = data or {}
        self.writes = []
        self.fail_on = fail_on  # (table, nth) -> raise on that POST
        self.counts = {}
        self.auth = MagicMock(spec=AuthManager)
        self.auth.get_headers.return_value = {}
        self.auth.make_request.side_effect = self._request

    def _request(self, method, url, **kw):
        table = url.split("/table/")[1].split("/")[0]
        n = self.counts[table] = self.counts.get(table, 0) + 1
        if self.fail_on == (table, n):
            raise RuntimeError("boom")
        self.writes.append((method, table, kw.get("json"), url))
        r = MagicMock()
        r.json.return_value = {"result": {"sys_id": f"new{table[:6]}{n:02d}".ljust(32, "0")}}
        return r

    def read(self, config, auth, *, table, query, **kw):
        for (t, needle), rows in self.data.items():
            if t == table and needle in query:
                return rows, None
        return [], None


def _fake(data=None, **kw):
    f = Fake(data, **kw)
    p = patch.object(svc, "sn_query_page", side_effect=f.read)
    p.start()
    return f, p


@pytest.fixture(autouse=True)
def _no_cache():
    with patch.object(svc, "invalidate_query_cache"):
        yield


def _own(sys_id):
    return {"sys_id": sys_id, "sys_policy": "", "sys_package": "", "sys_scope": "global"}


def test_create_item_inactive_by_default_and_reread():
    f, p = _fake({("sc_cat_item", "sys_id=new"): [{"sys_id": "x", "name": "N", "active": "false"}]})
    try:
        out = svc.create_item(_config(), f.auth, name="N", short_description="s")
    finally:
        p.stop()
    assert out["success"] and out["verified"] and out["sys_id"]
    method, table, body, _ = f.writes[0]
    assert (method, table, body["active"]) == ("POST", "sc_cat_item", "false")


def test_create_item_refuses_both_engines_and_dry_run_writes_nothing():
    f, p = _fake()
    try:
        both = svc.create_item(_config(), f.auth, name="N", flow_designer_flow="f", workflow="w")
        dry = svc.create_item(_config(), f.auth, name="N", dry_run=True)
    finally:
        p.stop()
    assert both["success"] is False and dry["dry_run"] is True
    assert f.writes == []
    with pytest.raises(ValidationError):
        ManageCatalogParams(action="create_item", name="N", flow_designer_flow="f", workflow="w")


def _copy_data():
    return {
        ("sc_cat_item", f"sys_id={ITEM}"): [{"sys_id": ITEM, "short_description": "sd"}],
        ("item_option_new", f"cat_item={ITEM}"): [
            {"sys_id": VAR_A, "name": "a", "type": "6", "order": "100"},
            {"sys_id": VAR_B, "name": "b", "type": "5", "order": "200"},
        ],
        ("question_choice", "questionIN"): [
            {"sys_id": "c1", "question": VAR_B, "text": "T", "value": "1", "order": "100"}
        ],
        ("io_set_item", ITEM): [{"sys_id": "l1", "variable_set": SET1, "order": "10"}],
        ("catalog_ui_policy", f"catalog_item={ITEM}"): [
            {"sys_id": POL, "catalog_conditions": f"IO:{VAR_A}=yes^EQ", "active": "true"}
        ],
        ("catalog_ui_policy_action", "ui_policyIN"): [
            {
                "sys_id": "pa1",
                "ui_policy": POL,
                "catalog_variable": f"IO:{VAR_B}",
                "visible": "true",
            }
        ],
        ("catalog_script_client", f"cat_item={ITEM}"): [
            {
                "sys_id": "s1",
                "name": "sc",
                "type": "onChange",
                "script": "x",
                "cat_variable": f"IO:{VAR_A}",
            }
        ],
    }


def test_copy_item_remaps_io_ids_and_links_sets():
    f, p = _fake(_copy_data())
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy")
    finally:
        p.stop()
    assert out["success"], out
    tables = [w[1] for w in f.writes]
    assert tables == [
        "sc_cat_item",
        "item_option_new",
        "item_option_new",
        "question_choice",
        "io_set_item",
        "catalog_ui_policy",
        "catalog_ui_policy_action",
        "catalog_script_client",
    ]
    new_a = out["created"]["item_option_new"][0]["new"]
    new_b = out["created"]["item_option_new"][1]["new"]
    by = {w[1]: w[2] for w in f.writes}
    assert by["sc_cat_item"]["active"] == "false" and by["sc_cat_item"]["name"] == "Copy"
    assert by["question_choice"]["question"] == new_b
    assert by["io_set_item"]["variable_set"] == SET1  # linked, never copied
    assert by["catalog_ui_policy"]["catalog_conditions"] == f"IO:{new_a}=yes^EQ"
    assert by["catalog_ui_policy_action"]["catalog_variable"] == f"IO:{new_b}"
    assert by["catalog_script_client"]["cat_variable"] == f"IO:{new_a}"
    assert by["catalog_script_client"]["script"] == "x"
    assert not [w for w in f.writes if w[1] == "item_option_new_set"]


def test_copy_item_dry_run_makes_no_write():
    f, p = _fake(_copy_data())
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy", dry_run=True)
    finally:
        p.stop()
    assert out["dry_run"] and out["would_copy"]["item_option_new"] == 2
    assert f.writes == []


def test_copy_item_partial_failure_reports_created_and_does_not_roll_back():
    f, p = _fake(_copy_data(), fail_on=("item_option_new", 2))
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy")
    finally:
        p.stop()
    assert out["success"] is False and out["error"] == "COPY_INCOMPLETE"
    assert out["failed"]["table"] == "item_option_new" and out["failed"]["old_id"] == VAR_B
    assert len(out["created"]["sc_cat_item"]) == 1 and len(out["created"]["item_option_new"]) == 1
    assert out["new_item_id"]
    assert not [w for w in f.writes if w[0] == "DELETE"]


def test_copy_item_unreadable_source_writes_nothing():
    f, p = _fake({})
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy")
    finally:
        p.stop()
    assert out["success"] is False and f.writes == []


def test_variable_set_create_update_and_ootb_refusal():
    f, p = _fake({("item_option_new_set", f"sys_id={SET1}"): [_own(SET1)]})
    try:
        c = svc.create_variable_set(
            _config(), f.auth, title="T", internal_name="t_set", display_title=True
        )
        u = svc.update_variable_set(_config(), f.auth, variable_set=SET1, title="T2")
    finally:
        p.stop()
    assert c["success"] and u["success"]
    assert f.writes[0][2]["display_title"] == "true"
    assert (f.writes[1][0], f.writes[1][2]) == ("PATCH", {"title": "T2"})

    ootb = dict(_own(SET1), sys_policy="read")
    f, p = _fake({("item_option_new_set", f"sys_id={SET1}"): [ootb]})
    try:
        r = svc.update_variable_set(_config(), f.auth, variable_set=SET1, title="X", dry_run=True)
    finally:
        p.stop()
    assert r["error"] == "OOTB_PROTECTED" and f.writes == []


def test_ootb_package_and_unreadable_target_are_refused():
    row = dict(_own(ITEM), sys_package={"value": "pk", "display_value": "Service Catalog"})
    f, p = _fake({("sc_cat_item", f"sys_id={ITEM}"): [row]})
    try:
        r1 = svc.attach_variable_set(_config(), f.auth, catalog_item_id=ITEM, variable_set=SET1)
    finally:
        p.stop()
    assert r1["error"] == "OOTB_PACKAGE" and f.writes == []
    f, p = _fake({})
    try:
        r2 = svc.attach_variable_set(_config(), f.auth, catalog_item_id=ITEM, variable_set=SET1)
    finally:
        p.stop()
    assert r2["error"] == "TARGET_NOT_FOUND" and f.writes == []


def test_create_variable_in_set_and_exactly_one_parent():
    f, p = _fake({("item_option_new_set", f"sys_id={SET1}"): [_own(SET1)]})
    try:
        with patch.object(svc, "resolve_variable_type", return_value=("6", None)):
            ok = svc.create_variable(
                _config(), f.auth, variable_set=SET1, name="n", variable_type="6", label="L"
            )
            bad = svc.create_variable(
                _config(),
                f.auth,
                catalog_item_id=ITEM,
                variable_set=SET1,
                name="n",
                variable_type="6",
                label="L",
            )
            dry = svc.create_variable(
                _config(),
                f.auth,
                variable_set=SET1,
                name="n",
                variable_type="6",
                label="L",
                dry_run=True,
            )
    finally:
        p.stop()
    assert ok["success"] and bad["success"] is False and dry["dry_run"]
    assert len(f.writes) == 1 and f.writes[0][2]["variable_set"] == SET1
    assert "cat_item" not in f.writes[0][2]
    with pytest.raises(ValidationError):
        ManageCatalogParams(
            action="create_variable",
            variable_name="n",
            variable_type="6",
            label="L",
            catalog_item_id=ITEM,
            variable_set=SET1,
        )


def test_attach_is_idempotent_and_detach_deletes_only_link():
    base = {
        ("sc_cat_item", f"sys_id={ITEM}"): [_own(ITEM)],
        ("item_option_new_set", f"sys_id={SET1}"): [_own(SET1)],
    }
    f, p = _fake({**base, ("io_set_item", "sc_cat_item="): [{"sys_id": "l1"}]})
    try:
        again = svc.attach_variable_set(_config(), f.auth, catalog_item_id=ITEM, variable_set=SET1)
        dry = svc.detach_variable_set(
            _config(), f.auth, catalog_item_id=ITEM, variable_set=SET1, dry_run=True
        )
        det = svc.detach_variable_set(_config(), f.auth, catalog_item_id=ITEM, variable_set=SET1)
    finally:
        p.stop()
    assert again["already_attached"] is True and dry["would_delete"] == ["l1"]
    assert det["deleted"] == ["l1"]
    assert [(w[0], w[1]) for w in f.writes] == [("DELETE", "io_set_item")]

    f, p = _fake(base)
    try:
        new = svc.attach_variable_set(
            _config(), f.auth, catalog_item_id=ITEM, variable_set=SET1, order=5
        )
    finally:
        p.stop()
    assert new["already_attached"] is False
    assert f.writes[0][2] == {"sc_cat_item": ITEM, "variable_set": SET1, "order": "5"}


def _choice_data():
    return {
        ("item_option_new", f"sys_id={VAR_A}"): [
            {"sys_id": VAR_A, "cat_item": ITEM, "variable_set": ""}
        ],
        ("sc_cat_item", f"sys_id={ITEM}"): [_own(ITEM)],
        ("question_choice", f"question={VAR_A}"): [
            {"sys_id": "k1", "value": "a", "text": "A", "order": "100", "inactive": "false"},
            {"sys_id": "k2", "value": "b", "text": "Old", "order": "200", "inactive": "false"},
            {"sys_id": "k3", "value": "c", "text": "C", "order": "300", "inactive": "false"},
        ],
    }


DESIRED = [
    {"value": "a", "text": "A", "order": 100},
    {"value": "b", "text": "New", "order": 200},
    {"value": "d", "text": "D", "order": 400},
]


def test_set_choices_diff_dry_run_and_apply():
    f, p = _fake(_choice_data())
    try:
        dry = svc.set_choices(_config(), f.auth, variable_id=VAR_A, choices=DESIRED, dry_run=True)
        assert f.writes == []
        out = svc.set_choices(_config(), f.auth, variable_id=VAR_A, choices=DESIRED)
    finally:
        p.stop()
    d = dry["diff"]
    assert [a["value"] for a in d["add"]] == ["d"]
    assert d["update"][0]["changes"] == {"text": "New"}
    assert [x["value"] for x in d["deactivate"]] == ["c"]
    assert d["unchanged"] == 1
    assert out["success"]
    kinds = [(w[0], w[2]) for w in f.writes]
    assert ("PATCH", {"inactive": "true"}) in kinds and not any(w[0] == "DELETE" for w in f.writes)
    assert any(w[0] == "POST" and w[2]["question"] == VAR_A for w in f.writes)


def test_set_choices_refuses_ootb_parent_and_bad_input():
    data = _choice_data()
    data[("sc_cat_item", f"sys_id={ITEM}")] = [dict(_own(ITEM), sys_policy="protected")]
    f, p = _fake(data)
    try:
        r = svc.set_choices(_config(), f.auth, variable_id=VAR_A, choices=DESIRED)
        dup = svc.set_choices(
            _config(), f.auth, variable_id=VAR_A, choices=[{"value": "a", "text": "x"}] * 2
        )
    finally:
        p.stop()
    assert r["error"] == "OOTB_PROTECTED" and dup["success"] is False and f.writes == []


def test_create_client_script_rules():
    f, p = _fake({("sc_cat_item", f"sys_id={ITEM}"): [_own(ITEM)]})
    try:
        ok = svc.create_client_script(
            _config(),
            f.auth,
            name="n",
            script_type="onChange",
            script="s",
            catalog_item_id=ITEM,
            cat_variable=f"IO:{VAR_A}",
            applies_catalog=True,
        )
        no_var = svc.create_client_script(
            _config(), f.auth, name="n", script_type="onChange", script="s", catalog_item_id=ITEM
        )
        both = svc.create_client_script(
            _config(),
            f.auth,
            name="n",
            script_type="onLoad",
            script="s",
            catalog_item_id=ITEM,
            variable_set=SET1,
        )
        dry = svc.create_client_script(
            _config(),
            f.auth,
            name="n",
            script_type="onLoad",
            script="s",
            catalog_item_id=ITEM,
            dry_run=True,
        )
    finally:
        p.stop()
    assert ok["success"] and "update_remote_from_local" in ok["next_step"]
    assert no_var["success"] is False and both["success"] is False and dry["dry_run"]
    assert len(f.writes) == 1 and f.writes[0][2]["applies_catalog"] == "true"
    assert f.writes[0][2]["cat_item"] == ITEM


def test_tool_dispatch_and_narrowing():
    with patch.object(svc, "copy_item", return_value={"success": True}) as m:
        out = manage_catalog(
            _config(), MagicMock(), ManageCatalogParams(action="copy_item", item_id=ITEM, name="C")
        )
    assert out == {"success": True} and m.call_args.kwargs["item_id"] == ITEM
    for a in ManageCatalogParams._FIELDS_BY_ACTION:
        assert a in ManageCatalogParams.model_fields["action"].annotation.__args__
    assert "script" not in ManageCatalogParams._FIELDS_BY_ACTION["copy_item"]
    assert json.dumps(ManageCatalogParams._FIELDS_BY_ACTION["set_choices"], default=sorted)
