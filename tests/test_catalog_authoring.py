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

    def __init__(self, data=None, fail_on=None, drops=None):
        self.data = data or {}
        self.writes = []
        self.fail_on = fail_on  # (table, nth) -> raise on that POST
        # {(table, field)}: the Table API answers 200 and stores the field empty
        # (measured: an action's ui_policy, a script's cat_variable). JSONv2 stores it,
        # except ("*jsonv2", field): dropped there too.
        self.drops = set(drops or ())
        self.counts = {}
        self.store = {}  # (table, sys_id) -> stored row, served to sys_id reads
        self.auth = MagicMock(spec=AuthManager)
        self.auth.get_headers.return_value = {}
        self.auth.make_request.side_effect = self._request

    def _request(self, method, url, **kw):
        body = kw.get("json")
        r = MagicMock()
        if ".do?JSONv2" in url:
            table = url.split("/")[-1].split(".do")[0]
            sys_id = url.split("sys_id=")[1]
            self.writes.append(("JSONV2", table, body, url))
            row = self.store.setdefault((table, sys_id), {"sys_id": sys_id})
            for k, v in body.items():
                row[k] = "" if ("*jsonv2", k) in self.drops else v
            return r
        table = url.split("/table/")[1].split("/")[0]
        if method == "DELETE":
            self.writes.append((method, table, None, url))
            self.store.pop((table, url.rsplit("/", 1)[1]), None)
            return r
        n = self.counts[table] = self.counts.get(table, 0) + 1
        if self.fail_on == (table, n):
            raise RuntimeError("boom")
        self.writes.append((method, table, body, url))
        sys_id = f"new{table[:6]}{n:02d}".ljust(32, "0")
        stored = {k: ("" if (table, k) in self.drops else v) for k, v in (body or {}).items()}
        self.store[(table, sys_id)] = {"sys_id": sys_id, **stored}
        r.json.return_value = {"result": {"sys_id": sys_id}}
        return r

    def read(self, config, auth, *, table, query, **kw):
        for (t, needle), rows in self.data.items():
            if t == table and needle in query:
                if isinstance(rows, Exception):
                    raise rows
                return rows, None
        if query.startswith("sys_id=") or query.startswith("sys_idIN"):
            ids = query.split("=", 1)[1] if query.startswith("sys_id=") else query[8:]
            rows = [self.store[(table, i)] for i in ids.split(",") if (table, i) in self.store]
            return [dict(r) for r in rows], None
        return [], None


def _fake(data=None, **kw):
    f = Fake(data, **kw)
    p = patch.object(svc, "sn_query_page", side_effect=f.read)
    p2 = patch("servicenow_mcp.services.dropped_writes.sn_query_page", side_effect=f.read)
    p3 = patch("servicenow_mcp.services.dropped_writes.invalidate_query_cache")
    p4 = patch("servicenow_mcp.services.ui_policy_manage.sn_query_page", side_effect=f.read)
    for x in (p, p2, p3, p4):
        x.start()
    return f, _Stops(p, p2, p3, p4)


class _Stops:
    def __init__(self, *patches):
        self.patches = patches

    def stop(self):
        for x in self.patches:
            x.stop()


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


TOPIC = "aaaa1111bbbb2222cccc3333dddd0007"
UC = "aaaa1111bbbb2222cccc3333dddd0008"
CAT = "aaaa1111bbbb2222cccc3333dddd0009"
CAT2 = "aaaa1111bbbb2222cccc3333dddd000a"


def _full_copy_data():
    data = _copy_data()
    data[("sc_cat_item", f"sys_id={ITEM}")] = [
        {
            "sys_id": ITEM,
            "sys_class_name": "sc_cat_item",
            "short_description": "sd",
            "roles": "snc_internal",
            "category": CAT,
            "taxonomy_topic": TOPIC,
            "picture": "abc.iix",
            "no_search": "true",
            "preview": "JavaScript: popupOpenStandard()",
        }
    ]
    data[("sys_dictionary", "nameINsc_cat_item")] = [
        {"element": e, "internal_type": t, "read_only": ro, "virtual": str(e == "preview").lower()}
        for e, t, ro in (
            ("short_description", "string", "false"),
            ("roles", "user_roles", "false"),
            ("category", "reference", "false"),
            ("taxonomy_topic", "reference", "false"),
            ("picture", "user_image", "false"),
            ("no_search", "boolean", "false"),
            ("cc_render_type", "glide_list", "true"),
            ("preview", "catalog_preview", "false"),
            ("name", "string", "false"),
            ("sys_scope", "reference", "false"),
        )
    ]
    data[("sys_db_object", "nameIN")] = [
        {"name": t}
        for t in (
            "m2m_connected_content",
            "sc_cat_item_user_criteria_mtom",
            "sc_cat_item_category",
        )
    ]
    data[("m2m_connected_content", f"catalog_item={ITEM}")] = [
        {"sys_id": "t1", "topic": TOPIC, "content_type": "ct", "order": "100"}
    ]
    data[("sc_cat_item_user_criteria_mtom", f"sc_cat_item={ITEM}")] = [
        {"sys_id": "u1", "user_criteria": UC}
    ]
    data[("sc_cat_item_category", f"sc_cat_item={ITEM}")] = [
        {"sys_id": "k1", "sc_category": CAT},
        {"sys_id": "k2", "sc_category": CAT2},
    ]
    return data


def test_copy_item_takes_every_writable_field_and_the_topic_links():
    # Live: a copy came out without roles and topic, so it showed to another audience.
    f, p = _fake(_full_copy_data())
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy")
    finally:
        p.stop()
    assert out["success"], out
    by = {}
    for _m, table, body, _u in f.writes:
        by.setdefault(table, []).append(body)
    item = by["sc_cat_item"][0]
    assert item["roles"] == "snc_internal" and item["no_search"] == "true"
    assert item["name"] == "Copy" and item["active"] == "false"
    # Derived (measured: written directly it comes back empty), an attachment of the
    # source, and a read-only column are not copied.
    assert not {"taxonomy_topic", "picture", "cc_render_type", "sys_scope", "preview"} & set(item)
    new_item = out["new_item_id"]
    assert by["m2m_connected_content"] == [
        {"topic": TOPIC, "content_type": "ct", "order": "100", "catalog_item": new_item}
    ]
    assert by["sc_cat_item_user_criteria_mtom"] == [{"user_criteria": UC, "sc_cat_item": new_item}]
    # The primary category's row comes from writing the field; only the other is a row.
    assert by["sc_cat_item_category"] == [{"sc_category": CAT2, "sc_cat_item": new_item}]
    assert "sc_cat_item_user_criteria_no_mtom" not in by  # table absent here
    assert any("update set" in n for n in out["notes"])


def test_copy_item_with_an_unreadable_dictionary_says_it_copied_less():
    data = _full_copy_data()
    del data[("sys_dictionary", "nameINsc_cat_item")]
    f, p = _fake(data)
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy", dry_run=True)
    finally:
        p.stop()
    assert out["narrowed"].startswith("Dictionary not readable for sc_cat_item")
    assert out["proposed_record"]["roles"] == "snc_internal"


def test_update_item_names_why_taxonomy_topic_cannot_be_written():
    f, p = _fake({})
    try:
        out = svc.update_item(
            _config(), f.auth, item_id=ITEM, item_options={"taxonomy_topic": TOPIC}
        )
    finally:
        p.stop()
    assert out["error"] == "DERIVED_ITEM_FIELD" and "m2m_connected_content" in out["message"]
    assert f.writes == []


def test_update_item_takes_roles():
    body = {}
    assert svc._item_option_body(_config(), None, {"roles": ["admin", "itil"]}, body) is None
    assert body == {"roles": "admin,itil"}


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
    f, p = _fake(
        {
            ("sc_cat_item", f"sys_id={ITEM}"): [_own(ITEM)],
            ("item_option_new", f"cat_item={ITEM}"): [{"sys_id": VAR_A, "name": "a"}],
        }
    )
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


def _dict_rows(*elements):
    return [{"element": e, "internal_type": "string", "read_only": "false"} for e in elements]


def test_child_rows_copy_every_field_their_table_has_and_point_at_the_copy():
    # Live: a copied variable lost list_table/show_help and a client script its
    # target — fields no hand-written list had.
    data = _full_copy_data()
    data[("item_option_new", f"cat_item={ITEM}")] = [
        {
            "sys_id": VAR_A,
            "name": "watch",
            "type": "21",
            "list_table": "sys_user",
            "show_help": "true",
        }
    ]
    data[("sys_dictionary", "nameINitem_option_new")] = _dict_rows(
        "name", "type", "list_table", "show_help", "cat_item"
    )
    data[("sys_dictionary", "nameINcatalog_script_client")] = _dict_rows(
        "name", "type", "script", "cat_variable", "cat_item"
    )
    new_var = "newitem_o01".ljust(32, "0")
    # Read back: the server kept show_help as something else.
    data[("item_option_new", "sys_idIN")] = [
        {
            "sys_id": new_var,
            "name": "watch",
            "type": "21",
            "list_table": "sys_user",
            "show_help": "false",
            "cat_item": "x",
        }
    ]
    data[("catalog_script_client", "sys_idIN")] = RuntimeError("403")
    f, p = _fake(data)
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy")
    finally:
        p.stop()
    assert out["success"], out
    by = {}
    for _m, table, body, _u in f.writes:
        by.setdefault(table, []).append(body)
    var = by["item_option_new"][0]
    assert var["list_table"] == "sys_user" and var["show_help"] == "true"
    assert var["cat_item"] == out["new_item_id"]
    script = by["catalog_script_client"][0]
    assert script["cat_variable"] == f"IO:{new_var}" and script["cat_item"] == out["new_item_id"]
    check = out["copy_check"]
    assert check["differences"] >= 1
    assert {
        "table": "item_option_new",
        "field": "show_help",
        "sent": "true",
        "stored": "false",
    }.items() <= next(d for d in check["listed"] if d["field"] == "show_help").items()
    # A table that cannot be read back is named, never counted as matching.
    assert check["checked"] is False and check["unread"] == ["catalog_script_client"]
    assert out["complete"] is False and "INCOMPLETE" in out["message"]


# --- values the Table API answers 200 for and does not store ------------------
# Measured live: an action's ui_policy (deny ACL, role nobody), a script's
# cat_variable and an action's catalog_variable come back empty; JSONv2 stores
# the last two. A copy that reported them as copied was the bug.


def _two_actions():
    data = _copy_data()
    data[("catalog_ui_policy_action", "ui_policyIN")] = [
        {"sys_id": "pa1", "ui_policy": POL, "catalog_variable": f"IO:{VAR_B}", "visible": "true"},
        {"sys_id": "pa2", "ui_policy": POL, "catalog_variable": f"IO:{VAR_A}", "visible": "false"},
    ]
    return data


def test_copy_item_does_not_leave_actions_the_instance_would_not_link():
    f, p = _fake(_two_actions(), drops={("catalog_ui_policy_action", "ui_policy")})
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy")
    finally:
        p.stop()
    posted = [w for w in f.writes if w[1] == "catalog_ui_policy_action"]
    # One probe, removed again; the second is never written.
    assert [w[0] for w in posted] == ["POST", "DELETE"]
    assert "catalog_ui_policy_action" not in out["created"]
    assert out["complete"] is False and "2 UI policy action(s) not copied" in out["message"]
    assert any("2 UI policy action(s) NOT copied" in n and "nobody" not in n for n in out["notes"])
    assert any("related list" in n for n in out["notes"])


def test_copy_item_resends_through_jsonv2_what_the_table_api_dropped():
    f, p = _fake(
        _copy_data(),
        drops={("catalog_script_client", "cat_variable"), ("item_option_new", "type")},
    )
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy")
    finally:
        p.stop()
    jsonv2 = {(w[1], tuple(sorted(w[2]))) for w in f.writes if w[0] == "JSONV2"}
    assert ("catalog_script_client", ("cat_variable",)) in jsonv2
    assert ("item_option_new", ("type",)) in jsonv2
    check = out["copy_check"]
    assert check["differences"] == 0 and check["rewritten_via_jsonv2"] == 3
    assert out["complete"] is True and "INCOMPLETE" not in out["message"]


def test_copy_item_reports_what_neither_api_stored():
    f, p = _fake(
        _copy_data(),
        drops={("catalog_script_client", "cat_variable"), ("*jsonv2", "cat_variable")},
    )
    try:
        out = svc.copy_item(_config(), f.auth, item_id=ITEM, name="Copy")
    finally:
        p.stop()
    check = out["copy_check"]
    assert check["differences"] == 1 and "rewritten_via_jsonv2" not in check
    assert check["listed"][0]["field"] == "cat_variable" and check["listed"][0]["stored"] == ""
    assert out["complete"] is False


def _script(f, **kw):
    return svc.create_client_script(
        _config(),
        f.auth,
        name="n",
        script_type="onChange",
        script="s",
        catalog_item_id=ITEM,
        **kw,
    )


_SCRIPT_DATA = {
    ("sc_cat_item", f"sys_id={ITEM}"): [_own(ITEM)],
    ("item_option_new", f"cat_item={ITEM}"): [{"sys_id": VAR_A, "name": "a"}],
}


def test_create_client_script_stores_the_variable_by_name_as_io_reference():
    f, p = _fake(_SCRIPT_DATA, drops={("catalog_script_client", "cat_variable")})
    try:
        out = _script(f, cat_variable="a")
    finally:
        p.stop()
    assert f.writes[0][2]["cat_variable"] == f"IO:{VAR_A}"
    assert f.writes[1][0] == "JSONV2" and f.writes[1][2] == {"cat_variable": f"IO:{VAR_A}"}
    assert out["success"] and out["record"]["cat_variable"] == f"IO:{VAR_A}"


def test_create_client_script_never_reports_a_script_with_no_variable_as_created():
    f, p = _fake(
        _SCRIPT_DATA,
        drops={("catalog_script_client", "cat_variable"), ("*jsonv2", "cat_variable")},
    )
    try:
        out = _script(f, cat_variable="a")
        unknown = _script(f, cat_variable="zzz")
    finally:
        p.stop()
    assert out["success"] is False and out["error"] == "TARGET_VARIABLE_NOT_STORED"
    assert f.writes[-1][0] == "DELETE" and "was removed" in out["message"]
    assert unknown["success"] is False and "unknown variable" in unknown["message"]
