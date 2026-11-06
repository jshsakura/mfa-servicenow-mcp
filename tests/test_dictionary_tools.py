"""manage_dictionary: a column is created, labelled and re-read; nothing claimed unproven."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools import dictionary_tools as dt
from servicenow_mcp.tools.dictionary_tools import ManageDictionaryParams, manage_dictionary

ANC = {
    "child_tbl": ["child_tbl", "parent_tbl"],
    "parent_tbl": ["parent_tbl"],
    "ref_tbl": ["ref_tbl"],
}


def _id(n):
    return f"aaaa{n:04d}bbbb2222cccc3333dddd4444"


class Fake:
    def __init__(self):
        self.dictionary = [
            {
                "sys_id": _id(1),
                "name": "parent_tbl",
                "element": "u_old",
                "internal_type": "string",
                "max_length": "100",
                "column_label": "Old",
            },
        ]
        self.docs = [
            {
                "sys_id": _id(2),
                "name": "parent_tbl",
                "element": "u_old",
                "language": "en",
                "label": "Old",
            }
        ]
        self.types = {"string", "integer", "reference"}
        self.writes = []
        self.auto_en = True  # the platform writes the en label from column_label
        self.column_real = True
        self.form = True  # the platform appends a new column to the form
        self.ui_elements = []
        self.layout_entries = []
        self.fail_delete = False
        self.entries_stick = False
        self.cache = {}
        self.rows = 5
        self.capture = [
            {
                "update_set.name": "Sprint 12 fixes",
                "update_set.state": "in progress",
                "sys_updated_on": "2026-01-01 00:00:00",
            }
        ]

    @staticmethod
    def _q(query):
        out = {}
        for part in query.split("^"):
            if part.startswith("nameIN"):
                out["names"] = part[6:].split(",")
            elif "=" in part:
                k, v = part.split("=", 1)
                out[k] = v
        return out

    def cached_query(self, config, auth, *, table, query, fields, **kw):
        """Like sn_query_page: a page is served from cache until its table is invalidated."""
        key = (table, query, fields)
        if key not in self.cache:
            self.cache[key] = self.query(config, auth, table=table, query=query, fields=fields)
        rows, total = self.cache[key]
        return [dict(r) for r in rows], total

    def invalidate(self, *, table=None):
        self.cache = {k: v for k, v in self.cache.items() if table and k[0] != table}

    def query(self, config, auth, *, table, query, fields, **kw):
        q = self._q(query)
        names = q.get("names") or ([q["name"]] if "name" in q else None)

        def keep(r):
            if "sys_id" in q and r["sys_id"] != q["sys_id"]:
                return False
            if names is not None and r["name"] not in names:
                return False
            if "element" in q and r["element"] != q["element"]:
                return False
            return "language" not in q or r["language"] == q["language"]

        if table == "sys_dictionary":
            return [r for r in self.dictionary if keep(r)], None
        if table == "sys_documentation":
            return [r for r in self.docs if keep(r)], None
        if table == "sys_glide_object":
            return ([{"name": q["name"]}] if q["name"] in self.types else []), None
        if table == "sys_ui_section":
            return [{"sys_id": "sec1"}], None
        if table == "sys_update_xml":
            if query.startswith("name=sys_ui_section_") or query.startswith(
                "nameINsys_ui_section_"
            ):
                return [dict(e) for e in self.layout_entries], None
            return list(self.capture), None
        if table == "sys_ui_element":
            el = query.split("element=")[1].split("^")[0]
            return [dict(e) for e in self.ui_elements if e["element"] == el], None
        raise AssertionError(table)

    def _recapture(self):
        """The platform rewrites the section's Form Layout record in the current set."""
        if not any(e["update_set.name"] == "Sprint 12 fixes" for e in self.layout_entries):
            self.layout_entries.append(
                {"sys_id": f"new{len(self.layout_entries)}", "update_set.name": "Sprint 12 fixes"}
            )

    def count(self, config, auth, table, query=""):
        if not query:
            return self.rows
        if not self.column_real:
            return self.rows  # condition dropped: whole table both times
        return 2 if query.endswith("ISEMPTY") else self.rows - 2

    def request(self, method, url, json=None, **kw):
        table = url.split("/table/")[1].split("/")[0]
        self.writes.append((method, table, json))
        resp = MagicMock()
        store = self.dictionary if table == "sys_dictionary" else self.docs
        if method == "DELETE":
            sid = url.rsplit("/", 1)[1]
            if self.fail_delete:
                raise RuntimeError("HTTP 403")
            if table == "sys_ui_element":
                self.ui_elements = [e for e in self.ui_elements if e["sys_id"] != sid]
                self._recapture()
            elif not self.entries_stick:
                self.layout_entries = [e for e in self.layout_entries if e["sys_id"] != sid]
            return resp
        if method == "POST" and table == "sys_dictionary" and self.form:
            self.ui_elements.append(
                {
                    "sys_id": "el1",
                    "element": json["element"],
                    "sys_ui_section": "sec1",
                    "sys_ui_section.view": "Default view",
                    "position": "22",
                }
            )
            self._recapture()
        if method == "POST":
            row = {**json, "sys_id": _id(50 + len(self.writes))}
            store.append(row)
            if table == "sys_dictionary" and self.auto_en:
                self.docs.append(
                    {
                        "sys_id": _id(80 + len(self.writes)),
                        "name": json["name"],
                        "element": json["element"],
                        "language": "en",
                        "label": json["column_label"],
                    }
                )
            resp.json.return_value = {"result": {"sys_id": row["sys_id"]}}
        else:
            sid = url.rsplit("/", 1)[1]
            for r in store:
                if r["sys_id"] == sid:
                    r.update(json)
            resp.json.return_value = {"result": {}}
        return resp


@pytest.fixture
def env():
    fake = Fake()
    config = MagicMock()
    config.api_url = "https://test.service-now.com/api/now"
    am = MagicMock()
    am.make_request.side_effect = fake.request
    with (
        patch.object(dt, "sn_query_page", side_effect=fake.cached_query),
        patch.object(dt, "sn_count", side_effect=fake.count),
        patch.object(dt, "table_ancestry", side_effect=lambda c, a, t: ANC.get(t, [])),
        patch.object(dt, "invalidate_query_cache", side_effect=fake.invalidate),
    ):
        yield fake, lambda **kw: manage_dictionary(config, am, ManageDictionaryParams(**kw))


NEW = dict(
    confirm_column="child_tbl.u_reason",
    action="create_field",
    table="child_tbl",
    element="u_reason",
    internal_type="string",
    column_label="Reason",
    max_length=200,
    labels={"ko": "사유"},
)


def test_create_writes_field_and_missing_labels_then_proves_them(env):
    fake, call = env
    r = call(**NEW)
    assert r["success"] is True, r
    assert [(m, t) for m, t, _ in fake.writes] == [
        ("POST", "sys_dictionary"),
        ("DELETE", "sys_ui_element"),  # undo the platform's form placement first
        ("DELETE", "sys_update_xml"),
        ("POST", "sys_documentation"),
    ]
    assert r["labels_written"] == {"en": "present", "ko": "created"}
    assert r["labels"] == {"en": "Reason", "ko": "사유"}
    assert r["field"]["max_length"] == "200"
    assert r["column"] == {"proven": True, "rows": 5}
    assert r["update_set_capture"]["update_set"] == "Sprint 12 fixes"


def test_en_label_is_written_when_the_platform_did_not(env):
    fake, call = env
    fake.auto_en = False
    r = call(**NEW)
    assert r["labels_written"]["en"] == "created" and r["success"] is True


def test_dry_run_writes_nothing(env):
    fake, call = env
    r = call(**NEW, dry_run=True)
    assert r["dry_run"] is True and fake.writes == []
    assert r["would_create"]["labels"] == {"en": "Reason", "ko": "사유"}


def test_field_already_on_a_parent_is_refused(env):
    fake, call = env
    r = call(**{**NEW, "element": "u_old"})
    assert r["success"] is False and "parent_tbl" in r["message"] and fake.writes == []


def test_unknown_type_is_refused(env):
    fake, call = env
    r = call(**{**NEW, "internal_type": "strng"})
    assert r["success"] is False and "sys_glide_object" in r["message"] and fake.writes == []


def test_missing_reference_table_is_refused(env):
    fake, call = env
    r = call(**{**NEW, "internal_type": "reference", "reference": "nope_tbl"})
    assert r["success"] is False and fake.writes == []


def test_a_dropped_column_condition_is_not_a_created_column(env):
    fake, call = env
    fake.column_real = False
    r = call(**NEW)
    assert r["column"]["proven"] is False and r["success"] is False


def test_empty_table_leaves_the_column_undetermined(env):
    fake, call = env
    fake.rows = 0
    r = call(**NEW)
    assert r["column"]["proven"] is None


def test_no_capture_says_it_will_not_travel(env):
    fake, call = env
    fake.capture = []
    r = call(**NEW)
    assert "will not travel" in r["capture_note"]


def test_new_column_on_a_global_table_needs_u_prefix():
    with pytest.raises(ValidationError):
        ManageDictionaryParams(**{**NEW, "element": "reason"})
    ManageDictionaryParams(**{**NEW, "table": "x_myapp_tbl", "element": "reason"})


def test_reference_only_with_reference_type():
    with pytest.raises(ValidationError):
        ManageDictionaryParams(**{**NEW, "internal_type": "reference"})
    with pytest.raises(ValidationError):
        ManageDictionaryParams(**{**NEW, "reference": "ref_tbl"})


def test_update_never_shrinks_a_column(env):
    fake, call = env
    r = call(action="update_field", table="parent_tbl", element="u_old", max_length=50)
    assert r["success"] is False and "truncate" in r["message"] and fake.writes == []


def test_update_of_an_inherited_column_needs_the_owner_named(env):
    fake, call = env
    r = call(action="update_field", table="child_tbl", element="u_old", max_length=300)
    assert r["success"] is False and r["defined_on"] == "parent_tbl"
    r = call(
        action="update_field",
        table="child_tbl",
        element="u_old",
        max_length=300,
        confirm_inherited="parent_tbl",
    )
    assert r["success"] is True and r["field"]["max_length"] == "300"


def test_set_label_on_a_child_says_it_is_an_override(env):
    fake, call = env
    r = call(action="set_label", table="child_tbl", element="u_old", language="ko", label="옛")
    assert r["success"] is True and "override" in r["note"]
    assert ("POST", "sys_documentation") == fake.writes[0][:2]


def test_set_label_updates_the_existing_row(env):
    fake, call = env
    r = call(action="set_label", table="parent_tbl", element="u_old", label="Older")
    assert r["success"] is True and fake.writes[0][0] == "PATCH"


def test_get_returns_definition_and_labels(env):
    _, call = env
    r = call(action="get", table="child_tbl", element="u_old")
    assert r["field"]["defined_on"] == "parent_tbl" and r["labels"][0]["label"] == "Old"


def test_get_is_the_only_read_action():
    from servicenow_mcp.policies.write_guards import MANAGE_READ_ACTIONS

    assert MANAGE_READ_ACTIONS["manage_dictionary"] == frozenset({"get"})


def test_create_without_the_named_approval_only_previews(env):
    fake, call = env
    r = call(**{**NEW, "confirm_column": None})
    assert r["success"] is False and r["approval_required"] is True and fake.writes == []
    assert "confirm_column='child_tbl.u_reason'" in r["message"]
    assert r["table_rows"] == 5 and r["would_create"]["sys_dictionary"]["element"] == "u_reason"


def test_approval_naming_another_column_does_not_create(env):
    fake, call = env
    r = call(**{**NEW, "confirm_column": "child_tbl.u_other"})
    assert r["approval_required"] is True and fake.writes == []
    assert "does not name it" in r["message"]


def test_same_column_on_a_child_table_is_refused(env):
    fake, call = env
    ANC["grandchild_tbl"] = ["grandchild_tbl", "child_tbl", "parent_tbl"]
    fake.dictionary.append({"sys_id": _id(9), "name": "grandchild_tbl", "element": "u_reason"})
    try:
        r = call(**NEW)
    finally:
        del ANC["grandchild_tbl"]
    assert r["success"] is False and r["conflicts"] == ["grandchild_tbl"] and fake.writes == []


def test_same_column_on_an_unrelated_table_is_fine(env):
    fake, call = env
    fake.dictionary.append({"sys_id": _id(9), "name": "ref_tbl", "element": "u_reason"})
    assert call(**NEW)["success"] is True


def test_update_changes_the_description_and_shows_what_it_replaced(env):
    fake, call = env
    fake.dictionary[0]["comments"] = "old text"
    r = call(action="update_field", table="parent_tbl", element="u_old", comments="new text")
    assert r["success"] is True and r["field"]["comments"] == "new text"
    assert r["previous"] == {"comments": "old text"}
    assert r["update_set_capture"]["update_set"] == "Sprint 12 fixes"


def test_form_placement_is_undone_by_default(env):
    fake, call = env
    r = call(**NEW)
    assert r["success"] is True, r
    assert r["form_placement_undo"] == {"elements_removed": 1, "entries_removed": 1, "undone": True}
    assert fake.ui_elements == [] and fake.layout_entries == []
    assert r["form_layout"]["added_to_form"] is False


def test_undo_keeps_a_form_layout_record_that_was_already_in_a_set(env):
    fake, call = env
    fake.layout_entries = [{"sys_id": "old0", "update_set.name": "Sprint 12 fixes"}]
    r = call(**NEW)
    assert r["form_placement_undo"]["entries_removed"] == 0
    assert [e["sys_id"] for e in fake.layout_entries] == ["old0"]
    assert r["success"] is True


def test_add_to_form_keeps_the_placement_and_says_so(env):
    fake, call = env
    r = call(**NEW, add_to_form=True)
    assert "form_placement_undo" not in r
    assert r["form_layout"]["added_to_form"] is True and "as asked" in r["form_layout_note"]
    assert r["success"] is True


def test_failed_undo_is_never_success(env):
    fake, call = env
    fake.fail_delete = True
    r = call(**NEW)
    assert r["form_placement_undo"]["undone"] is False
    assert r["success"] is False and "did not finish" in r["form_layout_note"]


def test_no_form_side_effect_is_said_plainly(env):
    fake, call = env
    fake.form = False
    r = call(**NEW)
    assert r["form_layout"] == {"checked": True, "added_to_form": False, "sections": []}
    assert "form_layout_note" not in r


def test_preview_warns_about_the_form_layout(env):
    _, call = env
    r = call(**{**NEW, "confirm_column": None})
    assert "Form Layout" in r["note"]


def test_element_removed_but_record_left_is_never_success(env):
    fake, call = env
    fake.entries_stick = True  # the new Form Layout record survives its delete
    r = call(**NEW)
    assert r["form_placement_undo"]["undone"] is False
    assert r["form_placement_undo"]["entries_left"]
    assert r["form_layout"]["added_to_form"] is False  # element gone, record not
    assert r["success"] is False and "remove_file" in r["form_undo_note"]


def test_reads_after_a_write_bypass_the_query_cache(env, monkeypatch):
    """A cached pre-write page hid the new Form Layout record from the undo (lab)."""
    fake, call = env
    monkeypatch.setattr(dt, "_fresh", lambda: None)  # the bug: no invalidation
    broken = call(**NEW)
    assert broken["form_placement_undo"]["entries_removed"] == 0  # reproduces it
