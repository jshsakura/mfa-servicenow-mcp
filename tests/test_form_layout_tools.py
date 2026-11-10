"""manage_form_layout: previews first, writes only the named section, re-reads the form."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools import form_layout_tools as fl
from servicenow_mcp.tools.form_layout_tools import ManageFormLayoutParams, manage_form_layout

FORM = "aaaa1111bbbb2222cccc3333dddd0001"
MAIN = "aaaa1111bbbb2222cccc3333dddd0002"
NOTES = "aaaa1111bbbb2222cccc3333dddd0003"
OTHER_FORM = "aaaa1111bbbb2222cccc3333dddd0009"
SRC_FORM = "aaaa1111bbbb2222cccc3333dddd0021"
SRC_MAIN = "aaaa1111bbbb2222cccc3333dddd0022"
SRC_NOTES = "aaaa1111bbbb2222cccc3333dddd0023"
SRC_EXTRA = "aaaa1111bbbb2222cccc3333dddd0024"
SRC_OTHER = "aaaa1111bbbb2222cccc3333dddd0025"


class Store:
    """Tiny Table API: =, !=, IN filters joined by ^; dot-walk to sys_ui_section.caption."""

    def __init__(self):
        self.n = 100
        self.t = {
            "sys_ui_form": [
                {"sys_id": FORM, "name": "child_tbl", "view": "Default view"},
                {"sys_id": SRC_FORM, "name": "src_tbl", "view": "Default view"},
            ],
            "sys_ui_section": [
                {"sys_id": MAIN, "name": "child_tbl", "caption": ""},
                {"sys_id": NOTES, "name": "child_tbl", "caption": "Notes"},
                {"sys_id": SRC_MAIN, "name": "src_tbl", "caption": ""},
                {"sys_id": SRC_NOTES, "name": "src_tbl", "caption": "Notes"},
                {"sys_id": SRC_EXTRA, "name": "src_tbl", "caption": "Extra info"},
                {"sys_id": SRC_OTHER, "name": "src_tbl", "caption": "Other"},
            ],
            "sys_ui_form_section": [
                {"sys_id": "l1", "sys_ui_form": FORM, "sys_ui_section": MAIN, "position": "0"},
                {"sys_id": "l2", "sys_ui_form": FORM, "sys_ui_section": NOTES, "position": "1"},
                {
                    "sys_id": "s0",
                    "sys_ui_form": SRC_FORM,
                    "sys_ui_section": SRC_MAIN,
                    "position": "0",
                },
                {
                    "sys_id": "s1",
                    "sys_ui_form": SRC_FORM,
                    "sys_ui_section": SRC_NOTES,
                    "position": "1",
                },
                {
                    "sys_id": "s2",
                    "sys_ui_form": SRC_FORM,
                    "sys_ui_section": SRC_EXTRA,
                    "position": "2",
                },
                {
                    "sys_id": "s3",
                    "sys_ui_form": SRC_FORM,
                    "sys_ui_section": SRC_OTHER,
                    "position": "3",
                },
            ],
            "sys_ui_element": [
                self.el(MAIN, "number", 0),
                self.el(MAIN, "state", 1),
                self.el(MAIN, ".split", 2, ".split"),
                self.el(MAIN, "priority", 3),
                self.el(MAIN, ".end_split", 4, ".end_split"),
                self.el(NOTES, "comments", 0),
                self.el(SRC_MAIN, "number", 0),
                self.el(SRC_NOTES, "comments", 0),
                self.el(SRC_EXTRA, ".begin_split", 0, ".begin_split"),
                self.el(SRC_EXTRA, "u_a", 1),
                self.el(SRC_EXTRA, ".split", 2, ".split"),
                self.el(SRC_EXTRA, "u_b", 3),
                self.el(SRC_EXTRA, ".end_split", 4, ".end_split"),
                self.el(SRC_EXTRA, "activity.xml", 5, "formatter"),
                self.el(SRC_OTHER, "state", 0),
            ],
            "sys_dictionary": [
                {"name": "parent_tbl", "element": e}
                for e in ("number", "state", "priority", "comments", "u_a", "u_b", "u_c")
            ],
            "sys_update_xml": [],
            "sys_ui_view": [],
        }
        self.cache = {}
        self.writes = []
        self.auto_link = False
        self.ignore_patch = False
        self.fail_on = None
        # True: a platform that records each layout write in the update set. The real Table
        # API does NOT (sys_ui_section is update_synch_custom) — tests that set False pin that.
        self.capture = True

    def _stamp(self, name):
        self.n += 1
        xml = self.t["sys_update_xml"]
        row = next((r for r in xml if r["name"] == name), None)
        if row is None:
            row = {"sys_id": f"x{self.n}", "name": name}
            xml.append(row)
        row.update(
            {
                "sys_updated_on": f"t{self.n}",
                "update_set.name": "Sprint 12 fixes",
                "update_set.state": "in progress",
            }
        )

    def _captured_names(self, method, table, sid, json, new_id):
        def row(t, i):
            return next((r for r in self.t[t] if r["sys_id"] == i), {})

        if table == "sys_ui_element":
            sec = (json or {}).get("sys_ui_section") or row(table, sid).get("sys_ui_section")
            return [f"sys_ui_section_{sec}"]
        if table == "sys_ui_section":
            return [f"sys_ui_section_{new_id or sid}"]
        if table == "sys_ui_form_section":
            form = (json or {}).get("sys_ui_form") or row(table, sid).get("sys_ui_form")
            return [f"sys_ui_form_sections_{form}"]
        return []

    def el(self, sec, element, pos, etype=""):
        self.n += 1
        return {
            "sys_id": f"e{self.n}",
            "sys_ui_section": sec,
            "element": element,
            "type": etype,
            "position": str(pos),
        }

    def _match(self, table, row, query):
        for part in filter(None, query.split("^")):
            if "IN" in part and "=" not in part.split("IN")[0]:
                f, vals = part.split("IN", 1)
                if self._get(table, row, f) not in vals.split(","):
                    return False
            elif "!=" in part:
                f, v = part.split("!=", 1)
                if self._get(table, row, f) == v:
                    return False
            else:
                f, v = part.split("=", 1)
                if self._get(table, row, f) != v:
                    return False
        return True

    def _get(self, table, row, f):
        if f == "sys_ui_section.caption":
            sec = next(s for s in self.t["sys_ui_section"] if s["sys_id"] == row["sys_ui_section"])
            return sec["caption"]
        return str(row.get(f, ""))

    def query(self, config, auth, *, table, query, fields, **kw):
        key = (table, query, fields)
        if key not in self.cache:
            rows = [dict(r) for r in self.t[table] if self._match(table, r, query)]
            for r in rows:
                if "sys_ui_section.caption" in fields and table == "sys_ui_form_section":
                    r["sys_ui_section.caption"] = self._get(table, r, "sys_ui_section.caption")
            self.cache[key] = rows
        return [dict(r) for r in self.cache[key]], None

    def invalidate(self, *, table=None):
        self.cache = {k: v for k, v in self.cache.items() if table and k[0] != table}

    def request(self, method, url, json=None, **kw):
        table = url.split("/table/")[1].split("/")[0]
        sid = url.split(f"/table/{table}", 1)[1].lstrip("/")
        self.writes.append((method, table, json))
        if self.fail_on == (method, table):
            raise RuntimeError("HTTP 500")
        resp = MagicMock()
        rows = self.t[table]
        stamp = self._captured_names(method, table, sid, json, f"new{self.n + 1}")
        if method == "POST":
            self.n += 1
            row = {k: str(v) for k, v in json.items()}
            row["sys_id"] = f"new{self.n}"
            rows.append(row)
            if table == "sys_ui_section" and self.auto_link:
                rows2 = self.t["sys_ui_form_section"]
                rows2.append(
                    {
                        "sys_id": f"auto{self.n}",
                        "sys_ui_form": FORM,
                        "sys_ui_section": row["sys_id"],
                        "position": "99",
                    }
                )
            resp.json.return_value = {"result": {"sys_id": row["sys_id"]}}
        elif method == "PATCH":
            if not self.ignore_patch:
                for r in rows:
                    if r["sys_id"] == sid:
                        r.update({k: str(v) for k, v in json.items()})
        else:
            self.t[table] = [r for r in rows if r["sys_id"] != sid]
        if self.capture:
            for name in stamp:
                self._stamp(name)
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
        patch.object(fl, "invalidate_query_cache", side_effect=st.invalidate),
        patch.object(fl, "table_ancestry", side_effect=lambda c, a, t: ["child_tbl", "parent_tbl"]),
    ):
        yield st, lambda **kw: manage_form_layout(
            config, am, ManageFormLayoutParams(table="child_tbl", **kw)
        )


BEFORE = [
    {"section": "main", "fields": ["number", "state", ".split", "priority", ".end_split"]},
    {"section": "Notes", "fields": ["comments"]},
]


def test_get_reads_tabs_in_order_with_split_markers(env):
    _, call = env
    r = call(action="get")
    assert r["success"] is True and r["layout"] == BEFORE
    assert "sys_ui_form_sections_" + FORM in r["update_set_capture"]["entries"]


def test_add_section_without_approval_only_previews(env):
    st, call = env
    r = call(action="add_section", section="Extra", fields=["u_a", "u_b"])
    assert r["approval_required"] is True and st.writes == []
    assert r["before"] == BEFORE
    assert r["after"][-1] == {"section": "Extra", "fields": ["u_a", "u_b"]}
    assert "confirm_layout='child_tbl:Extra'" in r["message"]


def test_add_section_two_columns_is_written_and_verified(env):
    st, call = env
    r = call(
        action="add_section",
        section="Extra",
        fields=["u_a", "u_b", "u_c"],
        columns=2,
        confirm_layout="child_tbl:Extra",
    )
    assert r["success"] is True, r
    assert r["layout"][-1] == {
        "section": "Extra",
        "fields": [".begin_split", "u_a", "u_b", ".split", "u_c", ".end_split"],
    }


def test_add_section_at_a_position_shifts_later_tabs(env):
    st, call = env
    r = call(
        action="add_section",
        section="Extra",
        fields=["u_a"],
        position=1,
        confirm_layout="child_tbl:Extra",
    )
    assert r["success"] is True, r
    assert [s["section"] for s in r["layout"]] == ["main", "Extra", "Notes"]


def test_a_section_the_platform_links_itself_is_not_linked_twice(env):
    st, call = env
    st.auto_link = True
    r = call(
        action="add_section", section="Extra", fields=["u_a"], confirm_layout="child_tbl:Extra"
    )
    assert r["success"] is True, r
    assert not [w for w in st.writes if w[:2] == ("POST", "sys_ui_form_section")]


def test_unknown_field_is_refused(env):
    st, call = env
    r = call(
        action="add_section", section="Extra", fields=["u_nope"], confirm_layout="child_tbl:Extra"
    )
    assert r["success"] is False and r["unknown"] == ["u_nope"] and st.writes == []


def test_field_already_on_the_form_is_refused(env):
    st, call = env
    r = call(
        action="add_section",
        section="Extra",
        fields=["u_a", "state"],
        confirm_layout="child_tbl:Extra",
    )
    assert r["already_on_form"] == {"state": "main"} and st.writes == []


def test_existing_caption_is_refused(env):
    st, call = env
    r = call(
        action="add_section", section="notes", fields=["u_a"], confirm_layout="child_tbl:notes"
    )
    assert r["success"] is False and st.writes == []


def test_approval_for_another_section_does_not_write(env):
    st, call = env
    r = call(
        action="add_section", section="Extra", fields=["u_a"], confirm_layout="child_tbl:Notes"
    )
    assert r["approval_required"] is True and st.writes == []


def test_add_fields_after_a_field_keeps_the_rest_in_order(env):
    st, call = env
    r = call(
        action="add_fields",
        section="main",
        fields=["u_a", "u_b"],
        after="state",
        confirm_layout="child_tbl:main",
    )
    assert r["success"] is True, r
    assert r["layout"][0]["fields"] == [
        "number",
        "state",
        "u_a",
        "u_b",
        ".split",
        "priority",
        ".end_split",
    ]


def test_add_fields_after_split_starts_the_right_column(env):
    st, call = env
    r = call(
        action="add_fields",
        section="main",
        fields=["u_a"],
        after=".split",
        confirm_layout="child_tbl:main",
    )
    assert r["layout"][0]["fields"] == [
        "number",
        "state",
        ".split",
        "u_a",
        "priority",
        ".end_split",
    ]


def test_add_fields_after_a_field_not_in_the_section_is_refused(env):
    st, call = env
    r = call(
        action="add_fields",
        section="Notes",
        fields=["u_a"],
        after="state",
        confirm_layout="child_tbl:Notes",
    )
    assert r["success"] is False and st.writes == []


def test_remove_fields_only_takes_the_placement(env):
    st, call = env
    preview = call(action="remove_fields", section="main", fields=["state"])
    assert "values stay" in preview["data_note"] and st.writes == []
    r = call(
        action="remove_fields", section="main", fields=["state"], confirm_layout="child_tbl:main"
    )
    assert r["success"] is True
    assert r["layout"][0]["fields"] == ["number", ".split", "priority", ".end_split"]


def test_remove_fields_not_in_the_section_is_refused(env):
    st, call = env
    r = call(
        action="remove_fields", section="Notes", fields=["state"], confirm_layout="child_tbl:Notes"
    )
    assert r["missing"] == ["state"] and st.writes == []


def test_remove_section_removes_tab_and_placements(env):
    st, call = env
    r = call(action="remove_section", section="Notes", confirm_layout="child_tbl:Notes")
    assert r["success"] is True, r
    assert [s["section"] for s in r["layout"]] == ["main"]
    assert not [
        s for s in st.t["sys_ui_section"] if s["caption"] == "Notes" and s["name"] == "child_tbl"
    ]


def test_a_section_shared_with_another_form_is_not_removed(env):
    st, call = env
    st.t["sys_ui_form_section"].append(
        {"sys_id": "l9", "sys_ui_form": OTHER_FORM, "sys_ui_section": NOTES, "position": "0"}
    )
    r = call(action="remove_section", section="Notes", confirm_layout="child_tbl:Notes")
    assert r["success"] is False and "other form" in r["message"] and st.writes == []


def test_main_section_is_never_removed_or_added():
    with pytest.raises(ValidationError):
        ManageFormLayoutParams(action="remove_section", table="t", section="main")
    with pytest.raises(ValidationError):
        ManageFormLayoutParams(action="add_section", table="t", section="Main", fields=["a"])


def test_a_write_that_stops_part_way_is_not_success(env):
    st, call = env
    st.fail_on = ("POST", "sys_ui_element")
    r = call(
        action="add_section", section="Extra", fields=["u_a"], confirm_layout="child_tbl:Extra"
    )
    assert r["success"] is False and "Stopped part-way" in r["message"]


def test_a_server_that_ignores_the_reorder_fails_verification(env):
    st, call = env
    st.ignore_patch = True
    r = call(
        action="add_fields",
        section="main",
        fields=["u_a"],
        after="number",
        confirm_layout="child_tbl:main",
    )
    assert r["success"] is False and r["expected"] != r["layout"]


def test_get_is_the_only_read_action():
    from servicenow_mcp.policies.write_guards import MANAGE_READ_ACTIONS

    assert MANAGE_READ_ACTIONS["manage_form_layout"] == frozenset({"get"})


EXTRA = {
    "section": "Extra info",
    "fields": [".begin_split", "u_a", ".split", "u_b", ".end_split"],
}


def test_copy_previews_the_finished_target_form(env):
    st, call = env
    r = call(action="copy_from", source_table="src_tbl", sections=["Extra info"])
    assert r["approval_required"] is True and st.writes == []
    assert r["after"] == BEFORE + [EXTRA]
    assert r["not_copied"] == ["Extra info: activity.xml (formatter)"]
    assert "confirm_layout='child_tbl:src_tbl'" in r["message"]


def test_copy_writes_the_sections_and_verifies_them(env):
    st, call = env
    r = call(
        action="copy_from",
        source_table="src_tbl",
        sections=["Extra info"],
        confirm_layout="child_tbl:src_tbl",
    )
    assert r["success"] is True, r
    assert r["layout"] == BEFORE + [EXTRA]


def test_copy_of_everything_names_what_blocks_it(env):
    st, call = env
    r = call(action="copy_from", source_table="src_tbl", confirm_layout="child_tbl:src_tbl")
    assert r["success"] is False and r["already_on_target_form"] == {"state": "main"}
    assert st.writes == []


def test_exclude_unblocks_it_and_existing_sections_are_skipped(env):
    st, call = env
    r = call(
        action="copy_from",
        source_table="src_tbl",
        exclude=["state"],
        confirm_layout="child_tbl:src_tbl",
    )
    assert r["success"] is True, r
    assert r["layout"] == BEFORE + [EXTRA]  # Other had nothing left; Notes already there
    assert r["skipped_existing"] == ["Notes"]


def test_a_source_field_missing_on_the_target_stops_the_copy(env):
    st, call = env
    st.t["sys_ui_element"].append(st.el(SRC_EXTRA, "u_zz", 5))
    r = call(
        action="copy_from",
        source_table="src_tbl",
        sections=["Extra info"],
        confirm_layout="child_tbl:src_tbl",
    )
    assert r["not_columns_of_target"] == ["u_zz"] and st.writes == []


def test_unknown_source_section_is_refused(env):
    st, call = env
    r = call(action="copy_from", source_table="src_tbl", sections=["Nope"])
    assert r["success"] is False and "Extra info" in r["source_sections"]


def test_copy_needs_a_different_source():
    with pytest.raises(ValidationError):
        ManageFormLayoutParams(action="copy_from", table="t")
    with pytest.raises(ValidationError):
        ManageFormLayoutParams(action="copy_from", table="t", source_table="t")


# --- update-set capture -----------------------------------------------------
# Live (2026-11): a Table API write to sys_ui_section / sys_ui_element /
# sys_ui_form_section is NOT captured. The tool must never call that success.


def test_an_applied_but_uncaptured_section_is_not_success(env):
    st, call = env
    st.capture = False
    r = call(
        action="add_section", section="Extra", fields=["u_a"], confirm_layout="child_tbl:Extra"
    )
    assert r["layout"][-1] == {"section": "Extra", "fields": ["u_a"]}
    assert r["success"] is False and r["captured"] is False
    assert "sys_ui_form_sections_" + FORM in r["not_captured"]
    assert any(n.startswith("sys_ui_section_") for n in r["not_captured"])
    assert "Form Layout" in r["message"] and "Applied on this instance only" in r["message"]


def test_an_older_capture_of_the_section_does_not_count(env):
    st, call = env
    st.capture = False
    st._stamp(f"sys_ui_section_{MAIN}")
    r = call(
        action="remove_fields", section="main", fields=["state"], confirm_layout="child_tbl:main"
    )
    assert r["success"] is False and r["captured"] is False
    assert r["not_captured"] == [f"sys_ui_section_{MAIN}"]
    assert r["update_set_capture"]["entries"][f"sys_ui_section_{MAIN}"]


def test_a_captured_write_says_so(env):
    _, call = env
    r = call(
        action="remove_fields", section="main", fields=["state"], confirm_layout="child_tbl:main"
    )
    assert r["success"] is True and r["captured"] is True
    assert r["update_set_capture"]["entries"][f"sys_ui_section_{MAIN}"]


def test_an_unreadable_update_set_is_undetermined_not_success(env):
    st, call = env
    real = st.query

    def boom(config, auth, *, table, **kw):
        if table == "sys_update_xml":
            raise RuntimeError("HTTP 403")
        return real(config, auth, table=table, **kw)

    with patch.object(fl, "sn_query_page", side_effect=boom):
        r = call(
            action="remove_fields",
            section="main",
            fields=["state"],
            confirm_layout="child_tbl:main",
        )
    assert r["success"] is False and r["captured"] == "undetermined"
    assert r["update_set_capture"]["checked"] is False
