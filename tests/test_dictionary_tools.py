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
        if table == "sys_update_xml":
            return list(self.capture), None
        raise AssertionError(table)

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
        patch.object(dt, "sn_query_page", side_effect=fake.query),
        patch.object(dt, "sn_count", side_effect=fake.count),
        patch.object(dt, "table_ancestry", side_effect=lambda c, a, t: ANC.get(t, [])),
        patch.object(dt, "invalidate_query_cache"),
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
