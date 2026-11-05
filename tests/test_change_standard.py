"""manage_change: list_templates, create_standard, and the `parent` link."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.change_tools import ManageChangeParams, manage_change
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

pytestmark = pytest.mark.usefixtures("live_choices")

TPL = "aaaa1111bbbb2222cccc3333dddd1111"
TPL2 = "aaaa1111bbbb2222cccc3333dddd2222"
CHG = "aaaa1111bbbb2222cccc3333dddd3333"
RITM = "aaaa1111bbbb2222cccc3333dddd4444"
GRP = "aaaa1111bbbb2222cccc3333dddd5555"


def cell(value, display=None):
    return {"value": value, "display_value": value if display is None else display}


def tpl_row(sys_id=TPL, name="Add switch"):
    return {
        "sys_id": cell(sys_id),
        "name": cell(name),
        "category": cell("cat1", "Network"),
        "current_version": cell("v1", "Add switch - 1"),
        "version": cell("1"),
    }


def cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )


def call(handlers, **kw):
    """handlers: table -> rows | Exception | callable(query) -> rows."""
    seen = []

    def fake_page(config, auth, *, table, query, **k):
        seen.append((table, query))
        h = handlers.get(table, [])
        h = h(query) if callable(h) else h
        if isinstance(h, Exception):
            raise h
        return h, len(h)

    auth = MagicMock()
    with (
        patch("servicenow_mcp.tools.change_tools.sn_query_page", fake_page),
        patch("servicenow_mcp.tools.change_tools.invalidate_query_cache"),
    ):
        out = manage_change(cfg(), auth, ManageChangeParams(**kw))
    return out, auth, seen


def post_response(result):
    resp = MagicMock()
    resp.json.return_value = {"result": result}
    return resp


# -- list_templates ----------------------------------------------------------


def test_list_templates_lean_rows_and_filters():
    out, _, seen = call({"std_change_record_producer": [tpl_row()]}, action="list_templates")
    assert out["success"] and out["total"] == 1 and out["complete"] is True
    assert out["templates"][0] == {
        "sys_id": TPL,
        "name": "Add switch",
        "category": "Network",
        "current_version": "Add switch - 1",
        "version": "1",
    }
    assert seen[0] == ("std_change_record_producer", "active=true^retired=false")


def test_list_templates_unreadable_is_an_error_not_empty():
    out, _, _ = call(
        {"std_change_record_producer": RuntimeError("HTTP 400")}, action="list_templates"
    )
    assert out["success"] is False and out["error"] == "TEMPLATES_UNREADABLE"


# -- create_standard ---------------------------------------------------------


def test_create_standard_requires_template():
    with pytest.raises(ValueError):
        ManageChangeParams(action="create_standard")


def test_create_standard_by_name_posts_to_documented_endpoint_and_rereads():
    created = {"sys_id": cell(CHG), "number": cell("CHG0000001")}
    reread = {
        "sys_id": cell(CHG),
        "number": cell("CHG0000001"),
        "type": cell("standard", "Standard"),
        "state": cell("-5", "New"),
        "short_description": cell("Swap port"),
        "assignment_group": cell(GRP, "Network Team"),
    }
    handlers = {"std_change_record_producer": [tpl_row()], "change_request": [reread]}
    auth = MagicMock()
    auth.make_request.return_value = post_response(created)
    with (
        patch(
            "servicenow_mcp.tools.change_tools.sn_query_page",
            lambda c, a, *, table, query, **k: (handlers[table], 1),
        ),
        patch("servicenow_mcp.tools.change_tools.invalidate_query_cache"),
    ):
        out = manage_change(
            cfg(),
            auth,
            ManageChangeParams(
                action="create_standard",
                template_id="Add switch",
                short_description="Swap port",
                assignment_group="Network Team",
                end_date="2030-01-01 10:00:00",
            ),
        )
    method, url = auth.make_request.call_args[0][:2]
    assert method == "POST"
    assert url == f"https://test.service-now.com/api/sn_chg_rest/change/standard/{TPL}"
    assert auth.make_request.call_args[1]["json"] == {
        "short_description": "Swap port",
        "assignment_group": "Network Team",
        "end_date": "2030-01-01 10:00:00",
    }
    assert out["number"] == "CHG0000001" and out["type"] == "Standard" and out["state"] == "New"
    assert out["applied"] == {
        "short_description": True,
        "assignment_group": True,
        "end_date": False,
    }
    assert out["overrides_not_applied"] == ["end_date"]


@pytest.mark.parametrize(
    "rows,code", [([], "TEMPLATE_NOT_FOUND"), ([tpl_row(), tpl_row(TPL2)], "TEMPLATE_AMBIGUOUS")]
)
def test_create_standard_zero_or_many_matches_refuse_without_post(rows, code):
    out, auth, _ = call(
        {"std_change_record_producer": rows}, action="create_standard", template_id="Add switch"
    )
    assert out["success"] is False and out["error"] == code
    if code == "TEMPLATE_AMBIGUOUS":
        assert [c["sys_id"] for c in out["candidates"]] == [TPL, TPL2]
    auth.make_request.assert_not_called()


def test_create_standard_template_read_failure_is_undetermined():
    out, auth, _ = call(
        {"std_change_record_producer": RuntimeError("boom")},
        action="create_standard",
        template_id=TPL,
    )
    assert out["error"] == "TEMPLATE_UNDETERMINED"
    auth.make_request.assert_not_called()


def test_create_standard_dry_run_writes_nothing():
    out, auth, _ = call(
        {"std_change_record_producer": [tpl_row()]},
        action="create_standard",
        template_id=TPL,
        short_description="Swap port",
        dry_run=True,
    )
    assert out["dry_run"] is True and out["template"]["sys_id"] == TPL
    assert out["proposed_record"] == {"short_description": "Swap port"}
    auth.make_request.assert_not_called()


def test_create_standard_without_sys_id_in_answer_is_not_claimed_verified():
    handlers = {"std_change_record_producer": [tpl_row()]}
    auth = MagicMock()
    auth.make_request.return_value = post_response({})
    with (
        patch(
            "servicenow_mcp.tools.change_tools.sn_query_page",
            lambda c, a, *, table, query, **k: (handlers[table], 1),
        ),
        patch("servicenow_mcp.tools.change_tools.invalidate_query_cache"),
    ):
        out = manage_change(
            cfg(), auth, ManageChangeParams(action="create_standard", template_id=TPL)
        )
    assert out["created"] is True and out["verified"] is False


def test_create_standard_parent_unresolved_refuses_before_post():
    out, auth, _ = call(
        {"std_change_record_producer": [tpl_row()], "task": []},
        action="create_standard",
        template_id=TPL,
        parent="RITM0000099",
    )
    assert out["error"] == "PARENT_NOT_FOUND" and "hidden by ACL" in out["message"]
    auth.make_request.assert_not_called()


# -- parent on create / update ----------------------------------------------


def task_row(cls="sc_req_item"):
    return {"sys_id": cell(RITM), "number": cell("RITM0000001"), "sys_class_name": cell(cls)}


def test_create_with_parent_number_resolves_to_sys_id():
    auth = MagicMock()
    auth.make_request.return_value = post_response({"sys_id": CHG})
    with (
        patch(
            "servicenow_mcp.tools.change_tools.sn_query_page", return_value=([task_row()], 1)
        ) as q,
        patch("servicenow_mcp.services.change.create", return_value={"success": True}) as create,
    ):
        out = manage_change(
            cfg(),
            auth,
            ManageChangeParams(
                action="create", short_description="x", type="normal", parent="ritm0000001"
            ),
        )
    assert q.call_args[1]["query"] == "number=RITM0000001" and q.call_args[1]["table"] == "task"
    assert out["success"] is True
    # The service writes it (same path as every create) — the tool only resolves it.
    assert create.call_args.kwargs["parent"] == RITM


def test_update_with_parent_sys_id_and_dry_run_preview_writes_nothing():
    auth = MagicMock()
    with (
        patch(
            "servicenow_mcp.tools.change_tools.sn_query_page",
            return_value=([task_row("sc_task")], 1),
        ),
        patch(
            "servicenow_mcp.services.change.build_update_preview", return_value={"dry_run": True}
        ) as prev,
    ):
        out = manage_change(
            cfg(),
            auth,
            ManageChangeParams(action="update", change_id=CHG, parent=RITM, dry_run=True),
        )
    assert out == {"dry_run": True}
    assert prev.call_args[1]["proposed"] == {"parent": RITM}
    auth.make_request.assert_not_called()


def test_update_parent_alone_satisfies_the_one_field_rule():
    ManageChangeParams(action="update", change_id=CHG, parent=RITM)


@pytest.mark.parametrize(
    "parent,rows,code",
    [
        ("INC0000001", [], "BAD_PARENT"),
        ("RITM0000001", [], "PARENT_NOT_FOUND"),
        ("RITM0000001", [task_row("incident")], "BAD_PARENT"),
        ("RITM0000001", RuntimeError("HTTP 500"), "PARENT_UNDETERMINED"),
    ],
)
def test_bad_parent_is_refused_and_nothing_written(parent, rows, code):
    out, auth, _ = call(
        {"task": rows}, action="create", short_description="x", type="normal", parent=parent
    )
    assert out["success"] is False and out["error"] == code
    auth.make_request.assert_not_called()


def test_create_dry_run_no_longer_writes():
    out, auth, _ = call({}, action="create", short_description="x", type="normal", dry_run=True)
    assert out["dry_run"] is True and out["operation"] == "create"
    auth.make_request.assert_not_called()


def test_field_narrowing_for_new_actions():
    f = ManageChangeParams._FIELDS_BY_ACTION
    assert "template_id" in f["create_standard"] and "type" not in f["create_standard"]
    assert "parent" in f["create"] and "parent" in f["update"]
    assert "template_id" not in f["list_templates"]
