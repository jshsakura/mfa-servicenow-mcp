"""Item options, Container layout, user criteria, and what get_item full claims.

Every write here is read back: the Table API ignores a column it does not have
without an error, so "saved" is only ever what the read-back shows.
"""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.services import catalog as svc
from servicenow_mcp.tools.catalog_tools import ManageCatalogParams, manage_catalog
from tests.test_catalog_authoring import _config, _fake, _own

ITEM = "aaaa1111bbbb2222cccc3333dddd4444"
CAT = "aaaa1111bbbb2222cccc3333dddd0010"
UC = "aaaa1111bbbb2222cccc3333dddd0011"
GROUP = "aaaa1111bbbb2222cccc3333dddd0012"
ROLE = "aaaa1111bbbb2222cccc3333dddd0013"
FLOW = "aaaa1111bbbb2222cccc3333dddd0014"
VAR = "aaaa1111bbbb2222cccc3333dddd0015"


@pytest.fixture(autouse=True)
def _no_cache():
    with patch.object(svc, "invalidate_query_cache"):
        yield


def _choices(table, element, requested, **_):
    known = {
        ("sc_cat_item", "request_method"): {"order": "NULL_OVERRIDE", "submit": "submit"},
        ("question", "layout"): {"2across": "2across", "normal": "normal"},
    }[(table, element)]
    value = known.get(str(requested).lower())
    if value is None:
        return None, {"success": False, "error": "BAD", "message": "not a value"}
    return value, None


def _resolve():
    return patch.object(
        svc,
        "resolve_choice",
        side_effect=lambda c, a, **kw: _choices(kw["table"], kw["element"], kw["requested"]),
    )


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------


def test_update_item_writes_portal_options_and_proves_them():
    row = {
        **_own(ITEM),
        "name": "N",
        "no_quantity_v2": "true",
        "no_cart_v2": "true",
        "request_method": "",
        "flow_designer_flow": FLOW,
        "workflow": "",
    }
    f, p = _fake({("sc_cat_item", f"sys_id={ITEM}"): [row]})
    try:
        with _resolve():
            out = svc.update_item(
                _config(),
                f.auth,
                item_id=ITEM,
                flow_designer_flow=FLOW,
                item_options={
                    "no_quantity_v2": True,
                    "no_cart_v2": "true",
                    "request_method": "Order",
                },
            )
    finally:
        p.stop()
    method, table, body, _ = f.writes[0]
    assert (method, table) == ("PATCH", "sc_cat_item")
    # "Order" is the NULL_OVERRIDE choice: stored empty, not as the word.
    assert body == {
        "flow_designer_flow": FLOW,
        "no_quantity_v2": "true",
        "no_cart_v2": "true",
        "request_method": "",
    }
    assert out["success"] and out["applied"] is True


def test_update_item_reports_a_column_the_instance_dropped():
    """Accepted, ignored, absent from the read-back: never reported as applied."""
    row = {**_own(ITEM), "name": "N", "no_quantity_v2": "false"}
    f, p = _fake({("sc_cat_item", f"sys_id={ITEM}"): [row]})
    try:
        out = svc.update_item(
            _config(),
            f.auth,
            item_id=ITEM,
            item_options={"no_quantity_v2": True, "no_save_as_draft": True},
        )
    finally:
        p.stop()
    assert out["applied"] is False
    assert out["not_applied"] == {"no_quantity_v2": {"wanted": "true", "now": "false"}}
    assert out["not_returned"] == ["no_save_as_draft"]


def test_update_item_unread_write_is_not_scored_as_applied():
    f, p = _fake({("sc_cat_item", "sys_policy"): []})
    try:
        with patch.object(svc, "_writable_target", return_value=None):
            out = svc.update_item(_config(), f.auth, item_id=ITEM, name="N")
    finally:
        p.stop()
    assert out["success"] and out["applied"] is None and "could not be read" in out["because"]


@pytest.mark.parametrize(
    "options, code",
    [
        ({"no_quantity": True, "hide_everything": True}, "UNKNOWN_ITEM_OPTION"),
        ({"no_quantity_v2": "maybe"}, "BAD_ITEM_OPTION"),
    ],
)
def test_update_item_refuses_bad_options_before_any_read(options, code):
    f, p = _fake()
    try:
        out = svc.update_item(_config(), f.auth, item_id=ITEM, item_options=options)
    finally:
        p.stop()
    assert out["success"] is False and out["error"] == code and f.writes == []


def test_update_item_refuses_an_ootb_item():
    row = {"sys_id": ITEM, "sys_policy": "read", "sys_package": "", "sys_scope": "global"}
    f, p = _fake({("sc_cat_item", f"sys_id={ITEM}"): [row]})
    try:
        out = svc.update_item(
            _config(), f.auth, item_id=ITEM, item_options={"no_quantity_v2": True}
        )
    finally:
        p.stop()
    assert out["error"] == "OOTB_PROTECTED" and f.writes == []


def test_update_item_warns_when_both_engines_end_up_set():
    row = {**_own(ITEM), "name": "N", "flow_designer_flow": FLOW, "workflow": "wf"}
    f, p = _fake({("sc_cat_item", f"sys_id={ITEM}"): [row]})
    try:
        out = svc.update_item(_config(), f.auth, item_id=ITEM, flow_designer_flow=FLOW)
    finally:
        p.stop()
    assert out["applied"] is True and "both a flow and a workflow" in out["warning"]


def test_update_item_params():
    ok = ManageCatalogParams(
        action="update_item", item_id=ITEM, item_options={"no_quantity_v2": True}
    )
    assert ok.item_options == {"no_quantity_v2": True}
    with pytest.raises(ValidationError):
        ManageCatalogParams(
            action="update_item", item_id=ITEM, flow_designer_flow=FLOW, workflow="w"
        )
    assert "item_options" in ManageCatalogParams._FIELDS_BY_ACTION["update_item"]
    assert "flow_designer_flow" in ManageCatalogParams._FIELDS_BY_ACTION["update_item"]


# ---------------------------------------------------------------------------
# Container variables
# ---------------------------------------------------------------------------


def test_container_start_takes_a_checked_layout_and_title():
    f, p = _fake()
    try:
        with _resolve(), patch.object(svc, "resolve_variable_type", return_value=("19", None)):
            ok = svc.create_variable(
                _config(),
                f.auth,
                catalog_item_id=ITEM,
                name="box",
                variable_type="Container Start",
                label="Box",
                layout="2across",
                display_title=True,
            )
            bad = svc.create_variable(
                _config(),
                f.auth,
                catalog_item_id=ITEM,
                name="box2",
                variable_type="Container Start",
                label="Box",
                layout="3 columns",
            )
    finally:
        p.stop()
    assert ok["success"] and bad["success"] is False
    assert len(f.writes) == 1
    body = f.writes[0][2]
    assert body["type"] == "19" and body["layout"] == "2across" and body["display_title"] == "true"


def test_container_fields_reach_both_variable_actions():
    for action in ("create_variable", "update_variable"):
        fields = ManageCatalogParams._FIELDS_BY_ACTION[action]
        assert {"layout", "display_title"} <= fields
    with patch.object(svc, "update_variable", return_value={"success": True}) as m:
        manage_catalog(
            _config(),
            MagicMock(),
            ManageCatalogParams(action="update_variable", variable_id=VAR, layout="2down"),
        )
    assert m.call_args.kwargs["layout"] == "2down"


# ---------------------------------------------------------------------------
# User criteria
# ---------------------------------------------------------------------------


def test_create_user_criteria_checks_every_id_and_reads_back():
    proof = {
        "sys_id": "new",
        "name": "Approvers",
        "match_all": "false",
        "advanced": "false",
        "group": GROUP,
        "role": ROLE,
    }
    f, p = _fake(
        {
            ("sys_user_group", "sys_idIN"): [{"sys_id": GROUP}],
            ("sys_user_role", "sys_idIN"): [{"sys_id": ROLE}],
            ("user_criteria", "sys_id=new"): [proof],
        }
    )
    try:
        out = svc.create_user_criteria(
            _config(), f.auth, name="Approvers", conditions={"group": [GROUP], "role": ROLE}
        )
    finally:
        p.stop()
    method, table, body, _ = f.writes[0]
    assert (method, table) == ("POST", "user_criteria")
    assert body == {
        "name": "Approvers",
        "match_all": "false",
        "advanced": "false",
        "group": GROUP,
        "role": ROLE,
    }
    assert out["success"] and out["sys_id"]


@pytest.mark.parametrize(
    "conditions, code",
    [
        ({"team": [GROUP]}, "UNKNOWN_CONDITION"),
        ({"group": ["Service Desk"]}, "NOT_A_SYS_ID"),
        ({"group": [GROUP, ROLE]}, "CONDITION_NOT_FOUND"),
        ({"group": []}, "NO_CONDITIONS"),
    ],
)
def test_create_user_criteria_refuses_what_it_cannot_prove(conditions, code):
    f, p = _fake({("sys_user_group", "sys_idIN"): [{"sys_id": GROUP}]})
    try:
        out = svc.create_user_criteria(_config(), f.auth, name="X", conditions=conditions)
    finally:
        p.stop()
    assert out["success"] is False and out["error"] == code and f.writes == []


def test_attach_user_criteria_to_an_item_and_warn_about_the_other_list():
    f, p = _fake(
        {
            ("sc_cat_item", f"sys_id={ITEM}"): [_own(ITEM)],
            ("user_criteria", f"sys_id={UC}"): [{"sys_id": UC, "name": "Approvers"}],
            ("sc_cat_item_user_criteria_no_mtom", f"sc_cat_item={ITEM}"): [{"sys_id": "x"}],
        }
    )
    try:
        out = svc.attach_user_criteria(
            _config(), f.auth, user_criteria=UC, access="available", catalog_item_id=ITEM
        )
    finally:
        p.stop()
    method, table, body, _ = f.writes[0]
    assert (method, table) == ("POST", "sc_cat_item_user_criteria_mtom")
    assert body == {"sc_cat_item": ITEM, "user_criteria": UC}
    assert out["success"] and "Not Available For wins" in out["warning"]


def test_attach_user_criteria_to_a_category_is_idempotent():
    f, p = _fake(
        {
            ("sc_category", f"sys_id={CAT}"): [_own(CAT)],
            ("user_criteria", f"sys_id={UC}"): [{"sys_id": UC, "name": "Approvers"}],
            ("sc_category_user_criteria_no_mtom", f"sc_category={CAT}"): [{"sys_id": "link"}],
        }
    )
    try:
        out = svc.attach_user_criteria(
            _config(), f.auth, user_criteria=UC, access="not_available", category_id=CAT
        )
    finally:
        p.stop()
    assert out["already_attached"] and f.writes == []


def test_attach_user_criteria_refuses_a_missing_criteria_and_an_ootb_item():
    f, p = _fake({("sc_cat_item", f"sys_id={ITEM}"): [_own(ITEM)]})
    try:
        missing = svc.attach_user_criteria(
            _config(), f.auth, user_criteria=UC, access="available", catalog_item_id=ITEM
        )
    finally:
        p.stop()
    ootb = {"sys_id": ITEM, "sys_policy": "protected", "sys_package": "", "sys_scope": "g"}
    g, q = _fake({("sc_cat_item", f"sys_id={ITEM}"): [ootb]})
    try:
        protected = svc.attach_user_criteria(
            _config(), g.auth, user_criteria=UC, access="available", catalog_item_id=ITEM
        )
    finally:
        q.stop()
    assert missing["error"] == "CRITERIA_NOT_FOUND" and protected["error"] == "OOTB_PROTECTED"
    assert f.writes == [] and g.writes == []


def test_detach_user_criteria_deletes_only_the_link():
    f, p = _fake(
        {
            ("sc_cat_item", f"sys_id={ITEM}"): [_own(ITEM)],
            ("sc_cat_item_user_criteria_mtom", f"sc_cat_item={ITEM}"): [{"sys_id": "link1"}],
        }
    )
    try:
        out = svc.detach_user_criteria(
            _config(), f.auth, user_criteria=UC, access="available", catalog_item_id=ITEM
        )
    finally:
        p.stop()
    assert out["deleted"] == ["link1"]
    assert [(m, t) for m, t, _, _ in f.writes] == [("DELETE", "sc_cat_item_user_criteria_mtom")]


def test_user_criteria_params():
    with pytest.raises(ValidationError):
        ManageCatalogParams(action="attach_user_criteria", user_criteria=UC, access="available")
    with pytest.raises(ValidationError):
        ManageCatalogParams(
            action="attach_user_criteria",
            user_criteria=UC,
            access="available",
            catalog_item_id=ITEM,
            category_id=CAT,
        )
    with pytest.raises(ValidationError):
        ManageCatalogParams(action="create_user_criteria", name="X")
    with patch.object(svc, "detach_user_criteria", return_value={"success": True}) as m:
        manage_catalog(
            _config(),
            MagicMock(),
            ManageCatalogParams(
                action="detach_user_criteria",
                user_criteria=UC,
                access="not_available",
                category_id=CAT,
            ),
        )
    assert m.call_args.kwargs == {
        "user_criteria": UC,
        "access": "not_available",
        "catalog_item_id": None,
        "category_id": CAT,
        "dry_run": False,
    }


# ---------------------------------------------------------------------------
# get_item detail=full: what it claims
# ---------------------------------------------------------------------------


def _full(extra=None, item_row=None):
    data = {
        ("sc_cat_item", f"sys_id={ITEM}"): [
            item_row or {"sys_id": ITEM, "sys_class_name": "sc_cat_item", "category": CAT}
        ],
        ("item_option_new", f"cat_item={ITEM}"): [
            # A text variable still carrying a reference from an earlier type.
            {"sys_id": "v1", "name": "phone", "type": "6", "reference": "sys_user", "order": "1"},
            {
                "sys_id": "v2",
                "name": "who",
                "type": "8",
                "reference": "sys_user",
                "order": "2",
                "default_value": "Service Desk",
            },
            {
                "sys_id": "v3",
                "name": "many",
                "type": "21",
                "list_table": "sys_user_group",
                "reference": "sys_user",
                "order": "3",
                "default_value": GROUP,
            },
        ],
        ("sc_cat_item_user_criteria_mtom", f"sc_cat_item={ITEM}"): [{"user_criteria": UC}],
        ("sc_category_user_criteria_no_mtom", f"sc_category={CAT}"): [{"user_criteria": UC}],
        ("user_criteria", "sys_idIN"): [
            {
                "sys_id": UC,
                "name": "Approvers",
                "active": "true",
                "match_all": "false",
                "advanced": "false",
                "group": GROUP,
            }
        ],
    }
    data.update(extra or {})
    f, p = _fake(data)
    try:
        return svc._item_full(_config(), f.auth, ITEM)
    finally:
        p.stop()


def test_full_shows_a_variable_table_only_where_its_type_uses_one():
    out = _full()
    by = {v["name"]: v for v in out["variables"]}
    assert "reference" not in by["phone"]
    assert by["phone"]["unused_by_type"] == {"reference": "sys_user"}
    assert by["who"]["reference"] == "sys_user" and "unused_by_type" not in by["who"]
    assert by["many"]["list_table"] == "sys_user_group"
    assert by["many"]["unused_by_type"] == {"reference": "sys_user"}
    codes = {w["code"]: w["message"] for w in out["warnings"]}
    assert "UNUSED_TABLE_VALUES" in codes
    # A label as a reference default resolves to nothing; a sys_id is fine.
    assert "who" in codes["DEFAULT_NOT_SYS_ID"] and "many" not in codes["DEFAULT_NOT_SYS_ID"]


def test_full_lists_user_criteria_of_the_item_and_its_category():
    uc = _full()["user_criteria"]
    assert [c["name"] for c in uc["item"]["available_for"]] == ["Approvers"]
    assert uc["item"]["not_available_for"] == []
    assert [c["sys_id"] for c in uc["category"]["not_available_for"]] == [UC]
    assert uc["item"]["available_for"][0]["conditions"] == {"group": GROUP}
    assert "not that everyone can see" in uc["note"]


def test_full_points_a_record_producer_at_its_target_table_automation():
    row = {"sys_id": ITEM, "sys_class_name": "sc_cat_item_producer", "category": ""}
    out = _full(
        {
            ("sc_cat_item_producer", f"sys_id={ITEM}"): [
                {"sys_id": ITEM, "table_name": "sc_request"}
            ]
        },
        item_row=row,
    )
    assert "get_table_automation(table='sc_request', operation='insert')" in (
        out["engine"]["after_submit"]
    )
    assert out["user_criteria"]["category"] is None


def test_full_user_criteria_read_failure_is_not_an_empty_list():
    with patch.object(svc, "_rows", side_effect=RuntimeError("acl")):
        block = svc._user_criteria_block(_config(), MagicMock(), ITEM, CAT, [])
    assert block == {"checked": False, "because": "acl"}


def test_a_servicenow_store_app_named_like_its_package_is_still_ootb():
    """Package and scope both 'Asset Management Common', scope code sn_itam_common."""
    row = {
        "sys_id": ITEM,
        "sys_policy": "",
        "sys_package": {"value": "pkg", "display_value": "Asset Management Common"},
        "sys_scope": {"value": "scope", "display_value": "Asset Management Common"},
        "sys_scope.scope": "sn_itam_common",
    }
    f, p = _fake({("sc_cat_item", f"sys_id={ITEM}"): [row]})
    try:
        out = svc.update_item(_config(), f.auth, item_id=ITEM, item_options={"hide_sp": True})
    finally:
        p.stop()
    assert out["error"] == "OOTB_PACKAGE" and f.writes == []
    # A customer app named like its package is still writable, and an unread
    # scope code leaves the earlier judgement exactly as it was.
    assert svc._is_customer_package("pkg", "My App", "My App", "x_acme_my_app")
    assert svc._is_customer_package("pkg", "My App", "My App", "")
