"""manage_catalog action='collect_structure': a catalog's records as update names.

The fake server below honours the queries it is sent (``col=x``, ``colINa,b``,
``state=current^nameIN..``), so a walk that asks the wrong column finds nothing
instead of being handed the answer. The shapes mirror facts measured on a live
instance: an item listed in a catalog by its link row while its ``sc_catalogs``
column is empty, an item placed in another catalog's category, a record
producer keyed by its own class, and never-customized records with no update
version.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.services import catalog_structure as cs
from servicenow_mcp.tools.catalog_tools import ManageCatalogParams, manage_catalog
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

CAT = "aaaa0000000000000000000000000001"
OTHER_CAT = "aaaa0000000000000000000000000002"
TOP = "bbbb0000000000000000000000000001"
CHILD = "bbbb0000000000000000000000000002"
FOREIGN_CATEGORY = "bbbb0000000000000000000000000009"
ITEM = "cccc0000000000000000000000000001"
PRODUCER = "cccc0000000000000000000000000002"
BY_COLUMN_ONLY = "cccc0000000000000000000000000003"
SET = "dddd0000000000000000000000000001"
VAR_ITEM = "eeee0000000000000000000000000001"
VAR_SET = "eeee0000000000000000000000000002"
CHOICE = "ffff0000000000000000000000000001"
POLICY = "aaaa1111000000000000000000000001"
ACTION = "aaaa1111000000000000000000000002"
SCRIPT = "aaaa1111000000000000000000000003"
UC = "aaaa2222000000000000000000000001"
UC_LINK = "aaaa2222000000000000000000000002"
FLOW = "aaaa3333000000000000000000000001"


def _link(sid: str, **cols: str) -> Dict[str, str]:
    return {"sys_id": sid, **cols}


def _instance() -> Dict[str, List[Dict[str, str]]]:
    return {
        "sc_catalog": [{"sys_id": CAT, "title": "Test"}],
        "sc_category": [
            {"sys_id": CHILD, "title": "Child", "parent": TOP, "sc_catalog": CAT},
            {"sys_id": TOP, "title": "Top", "parent": "", "sc_catalog": CAT},
            {
                "sys_id": FOREIGN_CATEGORY,
                "title": "Elsewhere",
                "parent": "",
                "sc_catalog": OTHER_CAT,
            },
        ],
        "sc_cat_item": [
            # Listed in the catalog by link row; its sc_catalogs column is empty.
            {
                "sys_id": ITEM,
                "name": "Item",
                "sys_class_name": "sc_cat_item",
                "category": TOP,
                "sc_catalogs": "",
                "flow_designer_flow": FLOW,
                "workflow": "",
            },
            {
                "sys_id": PRODUCER,
                "name": "Producer",
                "sys_class_name": "sc_cat_item_producer",
                "category": CHILD,
                "sc_catalogs": CAT,
                "flow_designer_flow": "",
                "workflow": "",
            },
            # In a category by its column only: no link row was ever written.
            {
                "sys_id": BY_COLUMN_ONLY,
                "name": "Column only",
                "sys_class_name": "sc_cat_item",
                "category": CHILD,
                "sc_catalogs": "",
                "flow_designer_flow": "",
                "workflow": "",
            },
        ],
        "sc_cat_item_catalog": [
            _link("aaaa4444000000000000000000000001", sc_cat_item=ITEM, sc_catalog=CAT),
            _link("aaaa4444000000000000000000000002", sc_cat_item=PRODUCER, sc_catalog=CAT),
            # The item also lives in another catalog: reported, not carried.
            _link("aaaa4444000000000000000000000003", sc_cat_item=ITEM, sc_catalog=OTHER_CAT),
        ],
        "sc_cat_item_category": [
            _link("aaaa5555000000000000000000000001", sc_cat_item=ITEM, sc_category=TOP),
            _link("aaaa5555000000000000000000000002", sc_cat_item=PRODUCER, sc_category=CHILD),
            _link(
                "aaaa5555000000000000000000000003", sc_cat_item=ITEM, sc_category=FOREIGN_CATEGORY
            ),
        ],
        "io_set_item": [
            _link("aaaa6666000000000000000000000001", sc_cat_item=ITEM, variable_set=SET)
        ],
        "item_option_new_set": [{"sys_id": SET, "title": "Set"}],
        "item_option_new": [
            {"sys_id": VAR_ITEM, "name": "v_item", "cat_item": ITEM, "variable_set": ""},
            {"sys_id": VAR_SET, "name": "v_set", "cat_item": "", "variable_set": SET},
        ],
        "question_choice": [{"sys_id": CHOICE, "question": VAR_SET}],
        "catalog_ui_policy": [
            {
                "sys_id": POLICY,
                "short_description": "p",
                "catalog_item": PRODUCER,
                "variable_set": "",
            }
        ],
        "catalog_ui_policy_action": [{"sys_id": ACTION, "ui_policy": POLICY}],
        "catalog_script_client": [
            {"sys_id": SCRIPT, "name": "s", "cat_item": "", "variable_set": SET}
        ],
        "sc_cat_item_user_criteria_mtom": [_link(UC_LINK, sc_cat_item=ITEM, user_criteria=UC)],
        "sc_cat_item_user_criteria_no_mtom": [],
        "sc_category_user_criteria_mtom": [],
        "sc_category_user_criteria_no_mtom": [],
        "sys_update_version": [],
    }


def _matches(row: Dict[str, str], term: str) -> bool:
    if "IN" in term and "=" not in term:
        col, vals = term.split("IN", 1)
        return str(row.get(col, "")) in vals.split(",")
    col, val = term.split("=", 1)
    return str(row.get(col, "")) == val


class FakeServer:
    def __init__(self, tables: Dict[str, List[Dict[str, str]]], fail: str = "") -> None:
        self.tables = tables
        self.fail = fail
        self.queries: List[str] = []

    def __call__(self, config, auth_manager, *, table, query, fields, limit, offset, **kw):
        self.queries.append(f"{table}:{query}")
        if table == self.fail:
            raise RuntimeError(f"403 on {table}")
        assert "^OR" not in query, "one IN per query: an OR chain can drop its filter"
        rows = [
            r for r in self.tables.get(table, []) if all(_matches(r, t) for t in query.split("^"))
        ]
        wanted = fields.split(",")
        return [{k: r.get(k, "") for k in wanted} for r in rows[offset : offset + limit]], None


def _versions_for_everything(tables: Dict[str, List[Dict[str, str]]], names: List[str]) -> None:
    tables["sys_update_version"] = [{"name": n, "state": "current"} for n in names]


@pytest.fixture()
def config() -> ServerConfig:
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def _run(monkeypatch, config, server: FakeServer, **root: str) -> Dict[str, Any]:
    monkeypatch.setattr(cs, "sn_query_page", server)
    return cs.collect_structure(config, MagicMock(), **root)


def _all_names(monkeypatch, config, **root: str) -> List[str]:
    """Names a walk reaches, read with every record versioned."""
    tables = _instance()
    first = _run(monkeypatch, config, FakeServer(tables), **root)
    return [n["name"] for n in first.get("no_version", [])]


def test_a_catalog_is_walked_into_every_record_a_move_needs(monkeypatch, config):
    tables = _instance()
    _versions_for_everything(tables, _all_names(monkeypatch, config, catalog_id=CAT))

    res = _run(monkeypatch, config, FakeServer(tables), catalog_id=CAT)

    assert res["complete"] is True and res["versions_checked"] is True
    names = res["names"]
    for expected in (
        f"sc_catalog_{CAT}",
        f"sc_category_{TOP}",
        f"sc_category_{CHILD}",
        f"sc_cat_item_{ITEM}",
        f"sc_cat_item_producer_{PRODUCER}",  # keyed by its class, not sc_cat_item
        f"sc_cat_item_{BY_COLUMN_ONLY}",
        f"item_option_new_set_{SET}",
        "io_set_item_aaaa6666000000000000000000000001",
        f"item_option_new_{VAR_ITEM}",
        f"item_option_new_{VAR_SET}",
        f"question_choice_{CHOICE}",
        f"catalog_ui_policy_{POLICY}",
        f"catalog_ui_policy_action_{ACTION}",
        f"catalog_script_client_{SCRIPT}",
        "sc_cat_item_catalog_aaaa4444000000000000000000000001",
        "sc_cat_item_category_aaaa5555000000000000000000000002",
        f"sc_cat_item_user_criteria_mtom_{UC_LINK}",
    ):
        assert expected in names, expected
    assert f"sc_cat_item_producer_{PRODUCER}".replace("_producer", "") not in names
    assert "no_version" not in res
    assert res["next"].startswith("export_record_xml(names=names)")


def test_parents_come_before_what_points_at_them(monkeypatch, config):
    tables = _instance()
    _versions_for_everything(tables, _all_names(monkeypatch, config, catalog_id=CAT))

    names = _run(monkeypatch, config, FakeServer(tables), catalog_id=CAT)["names"]

    pos = {n: i for i, n in enumerate(names)}
    assert pos[f"sc_catalog_{CAT}"] < pos[f"sc_category_{TOP}"] < pos[f"sc_category_{CHILD}"]
    assert pos[f"sc_category_{CHILD}"] < pos[f"sc_cat_item_producer_{PRODUCER}"]
    assert pos[f"catalog_ui_policy_{POLICY}"] < pos[f"catalog_ui_policy_action_{ACTION}"]


def test_links_to_another_catalog_are_reported_not_carried(monkeypatch, config):
    res = _run(monkeypatch, config, FakeServer(_instance()), catalog_id=CAT)

    outside = {(o["table"], o["sys_id"]) for o in res["outside_links"]}
    assert outside == {
        ("sc_cat_item_catalog", "aaaa4444000000000000000000000003"),
        ("sc_cat_item_category", "aaaa5555000000000000000000000003"),
    }
    every = [n["name"] for n in res["no_version"]]
    assert "sc_cat_item_catalog_aaaa4444000000000000000000000003" not in every


def test_shared_records_are_referenced_not_exported(monkeypatch, config):
    res = _run(monkeypatch, config, FakeServer(_instance()), catalog_id=CAT)

    refs = {(r["table"], r["sys_id"]) for r in res["referenced"]}
    assert ("user_criteria", UC) in refs
    assert ("sys_hub_flow", FLOW) in refs
    assert not any(n["name"].startswith("user_criteria_") for n in res["no_version"])


def test_never_customized_records_are_split_out_not_offered(monkeypatch, config):
    tables = _instance()
    tables["sys_update_version"] = [{"name": f"sc_cat_item_{ITEM}", "state": "current"}]

    res = _run(monkeypatch, config, FakeServer(tables), catalog_id=CAT)

    assert res["names"] == [f"sc_cat_item_{ITEM}"]
    assert res["tables"]["sc_category"] == {"records": 2, "no_version": 2}
    assert "cannot travel by update XML" in res["next"]


def test_nothing_versioned_never_says_export(monkeypatch, config):
    res = _run(monkeypatch, config, FakeServer(_instance()), catalog_id=CAT)

    assert res["names"] == []
    assert "export_record_xml" not in res["next"]
    assert "Nothing here can travel" in res["next"]


def test_a_failed_read_is_incomplete_never_a_short_clean_list(monkeypatch, config):
    tables = _instance()
    _versions_for_everything(tables, _all_names(monkeypatch, config, catalog_id=CAT))

    res = _run(monkeypatch, config, FakeServer(tables, fail="catalog_ui_policy"), catalog_id=CAT)

    assert res["complete"] is False
    assert res["unread"][0]["table"] == "catalog_ui_policy"
    assert res["next"].startswith("INCOMPLETE")


def test_a_failed_version_check_offers_every_name_and_says_so(monkeypatch, config):
    res = _run(
        monkeypatch, config, FakeServer(_instance(), fail="sys_update_version"), catalog_id=CAT
    )

    assert res["versions_checked"] is False
    assert f"sc_catalog_{CAT}" in res["names"]
    assert "no_version" not in res
    assert "unknown" in res["next"]


def test_one_item_carries_its_links_and_names_where_they_point(monkeypatch, config):
    res = _run(monkeypatch, config, FakeServer(_instance()), item_id=ITEM)

    assert res["root"] == {"table": "sc_cat_item", "sys_id": ITEM, "label": "Item"}
    every = [n["name"] for n in res["no_version"]]
    assert "sc_cat_item_category_aaaa5555000000000000000000000003" in every
    assert "sc_cat_item_catalog_aaaa4444000000000000000000000003" in every
    assert "outside_links" not in res
    refs = {(r["table"], r["sys_id"]) for r in res["referenced"]}
    assert {("sc_category", FOREIGN_CATEGORY), ("sc_catalog", OTHER_CAT)} <= refs
    assert not any(n.startswith("sc_category_") for n in every)


def test_a_category_takes_its_subcategories_and_names_its_catalog(monkeypatch, config):
    res = _run(monkeypatch, config, FakeServer(_instance()), category_id=TOP)

    every = [n["name"] for n in res["no_version"]]
    assert f"sc_category_{TOP}" in every and f"sc_category_{CHILD}" in every
    assert f"sc_cat_item_producer_{PRODUCER}" in every
    assert f"sc_catalog_{CAT}" not in every
    assert ("sc_catalog", CAT) in {(r["table"], r["sys_id"]) for r in res["referenced"]}


def test_an_unknown_root_is_not_found_not_an_empty_structure(monkeypatch, config):
    res = _run(
        monkeypatch, config, FakeServer(_instance()), item_id="cccc9999000000000000000000000000"
    )

    assert res["success"] is False and "No sc_cat_item" in res["message"]


def test_exactly_one_root_is_required(config):
    with pytest.raises(ValueError):
        ManageCatalogParams(action="collect_structure", catalog_id=CAT, item_id=ITEM)
    with pytest.raises(ValueError):
        ManageCatalogParams(action="collect_structure")


def test_the_action_is_routed(monkeypatch, config):
    server = FakeServer(_instance())
    monkeypatch.setattr(cs, "sn_query_page", server)

    res = manage_catalog(
        config, MagicMock(), ManageCatalogParams(action="collect_structure", catalog_id=CAT)
    )

    assert res["success"] is True and res["root"]["label"] == "Test"


def test_a_large_never_versioned_set_is_counted_not_dumped(monkeypatch, config):
    tables = _instance()
    tables["item_option_new"] += [
        {"sys_id": f"eeee1111{i:024x}", "name": f"v{i}", "cat_item": ITEM, "variable_set": ""}
        for i in range(80)
    ]

    res = _run(monkeypatch, config, FakeServer(tables), catalog_id=CAT)

    assert len(res["no_version"]) == cs._NO_VERSION_LISTED
    total = sum(t.get("no_version", 0) for t in res["tables"].values())
    assert res["no_version_more"] == total - cs._NO_VERSION_LISTED
