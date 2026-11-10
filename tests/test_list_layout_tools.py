"""manage_list_layout: previews first, never forks an inherited list, re-reads the columns."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools import form_layout_tools as fl
from servicenow_mcp.tools import list_layout_tools as ll
from servicenow_mcp.tools.list_layout_tools import ManageListLayoutParams, manage_list_layout

LIST = "aaaa1111bbbb2222cccc3333dddd0011"


class Store:
    def __init__(self):
        self.n = 0
        self.lists = [{"sys_id": LIST}]
        self.cols = [self.col("number", 0), self.col("state", 1), self.col("priority", 2)]
        self.writes = []
        self.cache = {}
        self.fail_on = None
        self.capture = True  # False = the real Table API: sys_ui_list writes are not captured
        self.xml = []

    def stamp(self):
        self.n += 1
        self.xml = [
            {
                "sys_id": "x1",
                "name": "sys_ui_list_child_tbl_null",
                "sys_updated_on": f"t{self.n}",
                "update_set.name": "Sprint 12 fixes",
                "update_set.state": "in progress",
            }
        ]

    def col(self, element, pos):
        self.n += 1
        return {"sys_id": f"c{self.n}", "element": element, "position": str(pos)}

    def query(self, config, auth, *, table, query, fields, **kw):
        key = (table, query, fields)
        if key not in self.cache:
            if table == "sys_ui_list":
                rows = list(self.lists)
            elif table == "sys_ui_list_element":
                rows = self.cols
            elif table == "sys_dictionary":
                rows = [
                    {"element": e}
                    for e in ("number", "state", "priority", "caller_id", "u_a", "u_b")
                ]
            elif table == "sys_update_xml":
                names = query.split("nameIN", 1)[1].split(",")
                rows = [r for r in self.xml if r["name"] in names]
            else:
                raise AssertionError(table)
            self.cache[key] = [dict(r) for r in rows]
        return [dict(r) for r in self.cache[key]], None

    def invalidate(self, *, table=None):
        self.cache = {k: v for k, v in self.cache.items() if table and k[0] != table}

    def request(self, method, url, json=None, **kw):
        table = url.split("/table/")[1].split("/")[0]
        sid = url.split(f"/table/{table}", 1)[1].lstrip("/")
        self.writes.append((method, table, json))
        if self.fail_on == method:
            raise RuntimeError("HTTP 500")
        resp = MagicMock()
        if method == "POST":
            self.n += 1
            self.cols.append(
                {
                    "sys_id": f"c{self.n}",
                    "element": json["element"],
                    "position": str(json["position"]),
                }
            )
            resp.json.return_value = {"result": {"sys_id": f"c{self.n}"}}
        elif method == "PATCH":
            for c in self.cols:
                if c["sys_id"] == sid:
                    c["position"] = str(json["position"])
        else:
            self.cols = [c for c in self.cols if c["sys_id"] != sid]
        if self.capture:
            self.stamp()
        return resp


@pytest.fixture
def env():
    st = Store()
    config = MagicMock()
    config.api_url = "https://test.service-now.com/api/now"
    am = MagicMock()
    am.make_request.side_effect = st.request
    with (
        patch.object(fl, "sn_query_page", side_effect=st.query),
        patch.object(ll, "invalidate_query_cache", side_effect=st.invalidate),
        patch.object(fl, "invalidate_query_cache", side_effect=st.invalidate),
        patch.object(fl, "table_ancestry", side_effect=lambda c, a, t: ["child_tbl", "parent_tbl"]),
    ):
        yield st, lambda **kw: manage_list_layout(
            config, am, ManageListLayoutParams(table="child_tbl", **kw)
        )


APPROVE = "child_tbl:Default view"


def test_get_lists_columns_in_order(env):
    _, call = env
    r = call(action="get")
    assert r["columns"] == ["number", "state", "priority"]
    assert r["update_set_capture"]["checked"] is True


def test_add_without_approval_only_previews(env):
    st, call = env
    r = call(action="add_columns", columns=["u_a"])
    assert r["approval_required"] is True and st.writes == []
    assert r["after"] == ["number", "state", "priority", "u_a"]


def test_add_after_a_column_is_written_and_verified(env):
    st, call = env
    r = call(
        action="add_columns",
        columns=["u_a", "caller_id.email"],
        after="number",
        confirm_list=APPROVE,
    )
    assert r["success"] is True, r
    assert r["columns"] == ["number", "u_a", "caller_id.email", "state", "priority"]


def test_unknown_column_is_refused(env):
    st, call = env
    r = call(action="add_columns", columns=["u_nope"], confirm_list=APPROVE)
    assert r["unknown"] == ["u_nope"] and st.writes == []


def test_duplicate_column_is_refused(env):
    st, call = env
    r = call(action="add_columns", columns=["state"], confirm_list=APPROVE)
    assert r["already_in_list"] == ["state"] and st.writes == []


def test_inherited_list_is_never_forked(env):
    st, call = env
    st.lists = []
    r = call(action="add_columns", columns=["u_a"], confirm_list=APPROVE)
    assert r["success"] is False and "parent's list" in r["message"] and st.writes == []


def test_remove_keeps_data_and_order(env):
    st, call = env
    r = call(action="remove_columns", columns=["state"], confirm_list=APPROVE)
    assert r["success"] is True and r["columns"] == ["number", "priority"]


def test_removing_every_column_is_refused(env):
    st, call = env
    r = call(action="remove_columns", columns=["number", "state", "priority"], confirm_list=APPROVE)
    assert r["success"] is False and st.writes == []


def test_part_way_failure_is_not_success(env):
    st, call = env
    st.fail_on = "POST"
    r = call(action="add_columns", columns=["u_a"], confirm_list=APPROVE)
    assert r["success"] is False and "Stopped part-way" in r["message"]


def test_bad_column_names_are_rejected():
    with pytest.raises(ValidationError):
        ManageListLayoutParams(action="add_columns", table="t", columns=["Bad Name"])


def test_get_is_the_only_read_action():
    from servicenow_mcp.policies.write_guards import MANAGE_READ_ACTIONS

    assert MANAGE_READ_ACTIONS["manage_list_layout"] == frozenset({"get"})


def test_capture_is_looked_up_under_the_platform_name(env):
    st, call = env
    st.stamp()
    r = call(action="get")
    assert r["update_set_capture"]["entries"]["sys_ui_list_child_tbl_null"]


def test_an_applied_but_uncaptured_list_is_not_success(env):
    st, call = env
    st.capture = False
    st.stamp()  # an older capture of the list is not this change
    r = call(action="remove_columns", columns=["state"], confirm_list=APPROVE)
    assert r["columns"] == ["number", "priority"]
    assert r["success"] is False and r["captured"] is False
    assert r["not_captured"] == ["sys_ui_list_child_tbl_null"]
    assert "List Layout" in r["message"]


def test_a_captured_list_write_says_so(env):
    _, call = env
    r = call(action="remove_columns", columns=["state"], confirm_list=APPROVE)
    assert r["success"] is True and r["captured"] is True
