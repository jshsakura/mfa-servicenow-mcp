"""Portal / page -> the widgets it renders (services/portal_slice.py)."""

import pytest

from servicenow_mcp.services.portal_slice import resolve_slice


class FakeInstance:
    """Answers the walk's reads from fixed tables, recording each query."""

    def __init__(self, tables, fail=()):
        self.tables = tables
        self.fail = set(fail)
        self.calls = []

    def __call__(self, *, table, query, fields, max_records):
        self.calls.append((table, query))
        if table in self.fail:
            raise RuntimeError(f"{table} unreadable")
        rows = self.tables.get(table, [])
        out = []
        for row in rows:
            for clause in query.split("^OR"):
                field, _, values = (
                    clause.partition("IN") if "IN" in clause else clause.partition("=")
                )
                if str(row.get(field)) in values.split(","):
                    out.append(row)
                    break
        return out


def _instance(**overrides):
    tables = {
        "sp_portal": [
            {
                "sys_id": "portal1",
                "url_suffix": "esc",
                "title": "Employee Center",
                "homepage": "page_home",
                "login_page": "",
                "theme": "theme1",
                "dark_theme": "",
                "sp_rectangle_menu": "menu1",
            }
        ],
        "sp_theme": [
            {
                "sys_id": "theme1",
                "name": "Coral",
                "header": "hdr",
                "footer": "ftr",
                "sys_scope.scope": "sn_ex_sp",
            }
        ],
        "sp_instance_menu": [{"sys_id": "menu1", "sp_widget": "menu_w"}],
        "sp_page": [
            {"sys_id": "page_home", "id": "index"},
            {"sys_id": "page_faq", "id": "faq"},
        ],
        "sp_container": [
            {"sys_id": "c1", "sp_page": "page_home"},
            {"sys_id": "c2", "sp_page": "page_faq"},
        ],
        "sp_row": [
            {"sys_id": "r1", "sp_container": "c1", "sp_column": ""},
            {"sys_id": "r2", "sp_container": "c2", "sp_column": ""},
            # Nested: a row inside column col1 — no container of its own.
            {"sys_id": "r_nested", "sp_container": "", "sp_column": "col1"},
        ],
        "sp_column": [
            {"sys_id": "col1", "sp_row": "r1"},
            {"sys_id": "col2", "sp_row": "r2"},
            {"sys_id": "col_nested", "sp_row": "r_nested"},
        ],
        "sp_instance": [
            {"sp_widget": "w_top", "sp_column": "col1"},
            {"sp_widget": "w_faq", "sp_column": "col2"},
            {"sp_widget": "w_deep", "sp_column": "col_nested"},
        ],
    }
    tables.update(overrides)
    return tables


def test_a_portal_brings_its_chrome_and_the_pages_it_names():
    out = resolve_slice(FakeInstance(_instance()), portal="esc")

    assert out["complete"] is True
    assert {"hdr", "ftr", "menu_w", "w_top"} <= set(out["widget_sys_ids"])
    assert "w_faq" not in out["widget_sys_ids"], "a page the portal does not name"
    assert out["widget_source"]["hdr"] == "theme header"
    assert out["themes"][0]["scope"] == "sn_ex_sp"


def test_a_widget_in_a_nested_row_is_not_dropped():
    """One dot-walk to sp_page counts only top-level rows — measured: 28 nested
    rows on a real instance."""
    out = resolve_slice(FakeInstance(_instance()), page_ids=["index"])

    assert "w_deep" in out["widget_sys_ids"]
    assert out["widget_source"]["w_deep"] == "page index"


def test_pages_resolve_by_id_or_sys_id_and_a_miss_is_named():
    out = resolve_slice(FakeInstance(_instance()), page_ids=["faq", "page_home", "nope"])

    assert {"w_faq", "w_top", "w_deep"} <= set(out["widget_sys_ids"])
    assert out["unresolved"] == ["page:nope"]
    assert out["complete"] is False


def test_an_unreadable_level_marks_the_walk_incomplete_not_empty():
    out = resolve_slice(FakeInstance(_instance(), fail={"sp_instance"}), page_ids=["index"])

    assert out["complete"] is False
    assert any("sp_instance" in w for w in out["warnings"])


def test_an_unknown_portal_is_named():
    out = resolve_slice(FakeInstance(_instance()), portal="nope")

    assert out["widget_sys_ids"] == []
    assert out["unresolved"] == ["portal:nope"]
    assert out["complete"] is False


def test_a_login_failure_is_raised_not_scored_as_incomplete():
    def query(**_kw):
        raise ValueError("LOGIN_CANCELLED_BY_USER (x): timed out")

    with pytest.raises(ValueError, match="LOGIN_CANCELLED_BY_USER"):
        resolve_slice(query, portal="esc")
