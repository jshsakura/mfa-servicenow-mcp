"""manage_portal_action — Employee Center action records, one per call, read back."""

import itertools
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools import portal_action_tools as pa
from servicenow_mcp.tools.portal_action_tools import ManagePortalActionParams, manage_portal_action
from servicenow_mcp.utils.config import ServerConfig

SCOPE = "aaaa1111bbbb2222cccc3333dddd4444"
TYPE_ID = "bbbb2222cccc3333dddd4444eeee5555"
GROUP_ID = "cccc3333dddd4444eeee5555ffff6666"
_NEW_IDS = [f"{c * 4}{d * 4}" * 4 for c, d in zip("0123456789", "fedcba9876", strict=True)]


class FakeServer:
    """Tables of rows behind sn_query_page; POST/PATCH write into them."""

    def __init__(self, rows=None, drop_on_write=(), scope_lands=SCOPE, fail_read=None):
        self.tables = {}
        for table, row in rows or []:
            self.tables.setdefault(table, []).append(dict(row))
        self.drop = set(drop_on_write)
        self.scope_lands = scope_lands
        self.fail_read = fail_read
        self.writes = []
        self._ids = itertools.cycle(_NEW_IDS)

    def query(self, config, auth, *, table, query, fields, **kw):
        if self.fail_read == table:
            raise RuntimeError("403 Forbidden")
        conds = [c.partition("=") for c in query.split("^") if c]
        rows = [
            r
            for r in self.tables.get(table, [])
            if all(str(r.get(k, "")) == v for k, _, v in conds)
        ]
        return [dict(r) for r in rows], len(rows)

    def request(self, method, url, json=None, **kw):
        self.writes.append((method, url, json))
        body = {k: v for k, v in (json or {}).items() if k not in self.drop}
        parts = url.split("/api/now/table/")[1].split("/")
        table = parts[0]
        if method == "POST":
            row = {"sys_id": next(self._ids), "sys_scope": self.scope_lands, **body}
            self.tables.setdefault(table, []).append(row)
        else:
            row = next(r for r in self.tables[table] if r["sys_id"] == parts[1])
            row.update(body)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"result": row}
        return resp


@pytest.fixture
def cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


def _call(server, cfg, **kw):
    auth = MagicMock()
    auth.get_headers.return_value = {}
    auth.make_request.side_effect = server.request
    with (
        patch.object(pa, "sn_query_page", side_effect=server.query),
        patch.object(pa, "invalidate_query_cache"),
        patch.object(pa, "align_session_for_create", return_value={}) as align,
    ):
        result = manage_portal_action(cfg, auth, ManagePortalActionParams(**kw))
    result["_align"] = align
    return result


def _type_row():
    return ("sn_ex_sp_action_type", {"sys_id": TYPE_ID, "name": "Sample type"})


class TestCreate:
    def test_type_created_active_and_verified(self, cfg):
        s = FakeServer()
        r = _call(
            s,
            cfg,
            action="create",
            kind="type",
            scope=SCOPE,
            fields={"name": "Sample type", "server_script": "(function(){\r\n})();"},
        )
        assert r["complete"] is True, r["missing"]
        assert s.writes[0][2]["active"] == "true"
        assert "active" in r["undo"]
        assert r["_align"].call_args.kwargs["scope"] == SCOPE

    def test_action_with_parameters_resolves_type_by_name(self, cfg):
        s = FakeServer(rows=[_type_row()])
        r = _call(
            s,
            cfg,
            action="create",
            kind="action",
            scope=SCOPE,
            fields={"name": "Do it", "table": "sc_req_item", "action_type": "Sample type"},
            parameters=[
                {
                    "name": "sys_id",
                    "parameter_type": "table",
                    "table": "sc_req_item",
                    "field": "sys_id",
                },
                {"name": "targetStage", "parameter_type": "string", "text": "complete"},
            ],
        )
        assert r["complete"] is True, r["missing"]
        assert s.writes[0][2]["action_type"] == TYPE_ID
        params = [w[2] for w in s.writes[1:]]
        assert [p["name"] for p in params] == ["sys_id", "targetStage"]
        assert all(p["action"] == r["sys_id"] for p in params)
        assert len(r["created"]) == 3

    def test_dry_run_writes_nothing_and_does_not_switch_scope(self, cfg):
        s = FakeServer()
        r = _call(
            s, cfg, action="create", kind="group", scope=SCOPE, fields={"name": "G"}, dry_run=True
        )
        assert r["dry_run"] and s.writes == []
        r["_align"].assert_not_called()

    def test_duplicate_is_refused(self, cfg):
        s = FakeServer(rows=[_type_row()])
        r = _call(s, cfg, action="create", kind="type", scope=SCOPE, fields={"name": "Sample type"})
        assert r["success"] is False and r["existing_sys_ids"] == [TYPE_ID] and s.writes == []

    def test_unreadable_duplicate_check_refuses(self, cfg):
        """An unread table must never read as 'no duplicate'."""
        s = FakeServer(fail_read="sn_ex_sp_action_group")
        r = _call(s, cfg, action="create", kind="group", scope=SCOPE, fields={"name": "G"})
        assert r["success"] is False and "403" in r["message"] and s.writes == []

    def test_unknown_reference_name_is_refused(self, cfg):
        s = FakeServer()
        r = _call(
            s,
            cfg,
            action="create",
            kind="link",
            scope=SCOPE,
            fields={"group": "Nope", "action": "X", "order": 100, "action_visibility": "adv"},
        )
        assert r["success"] is False and "Nope" in r["message"] and s.writes == []

    def test_record_landing_in_another_scope_is_not_confirmed(self, cfg):
        s = FakeServer(scope_lands="global")
        r = _call(s, cfg, action="create", kind="group", scope=SCOPE, fields={"name": "G"})
        assert r["success"] and r["complete"] is False
        assert any("sys_scope" in p for p in r["missing"])

    def test_dropped_field_is_reported(self, cfg):
        s = FakeServer(drop_on_write={"script"})
        s.tables["sn_ex_sp_action_group"] = [{"sys_id": GROUP_ID, "name": "G"}]
        s.tables["sn_ex_sp_action"] = [{"sys_id": TYPE_ID, "name": "A"}]
        r = _call(
            s,
            cfg,
            action="create",
            kind="link",
            scope=SCOPE,
            fields={
                "group": "G",
                "action": "A",
                "order": 100,
                "action_visibility": "adv",
                "primary": True,
                "script": "answer = true;",
            },
        )
        assert r["complete"] is False and any("script" in p for p in r["missing"])
        assert "delete" in r["undo"]  # links have no active flag

    def test_align_failure_aborts_before_write(self, cfg):
        s = FakeServer()
        auth = MagicMock()
        auth.make_request.side_effect = s.request
        err = {"success": False, "error": "scope_switch_failed"}
        with (
            patch.object(pa, "sn_query_page", side_effect=s.query),
            patch.object(pa, "invalidate_query_cache"),
            patch.object(pa, "align_session_for_create", return_value={"error": err}),
        ):
            r = manage_portal_action(
                cfg,
                auth,
                ManagePortalActionParams(
                    action="create", kind="group", scope=SCOPE, fields={"name": "G"}
                ),
            )
        assert r == err and s.writes == []


class TestUpdate:
    def test_deactivate_reports_change(self, cfg):
        s = FakeServer(rows=[("sn_ex_sp_action_group", {"sys_id": GROUP_ID, "active": "true"})])
        r = _call(
            s, cfg, action="update", kind="group", record_id=GROUP_ID, fields={"active": False}
        )
        assert r["complete"] is True
        assert r["changes"] == {"active": {"from": "true", "to": "false"}}

    def test_no_change_writes_nothing(self, cfg):
        s = FakeServer(rows=[("sn_ex_sp_action_group", {"sys_id": GROUP_ID, "active": "true"})])
        r = _call(
            s, cfg, action="update", kind="group", record_id=GROUP_ID, fields={"active": True}
        )
        assert r["message"] == "Nothing to change" and s.writes == []

    def test_not_found(self, cfg):
        r = _call(
            FakeServer(),
            cfg,
            action="update",
            kind="group",
            record_id=GROUP_ID,
            fields={"name": "x"},
        )
        assert r["success"] is False

    def test_dry_run(self, cfg):
        s = FakeServer(rows=[("sn_ex_sp_action_group", {"sys_id": GROUP_ID, "name": "G"})])
        r = _call(
            s,
            cfg,
            action="update",
            kind="group",
            record_id=GROUP_ID,
            fields={"name": "H"},
            dry_run=True,
        )
        assert r["dry_run"] and s.writes == []


class TestParams:
    def test_unknown_field_is_refused(self):
        with pytest.raises(ValueError, match="unknown field"):
            ManagePortalActionParams(
                action="create", kind="group", scope=SCOPE, fields={"name": "G", "nmae": "x"}
            )

    def test_create_needs_required_fields_and_scope(self):
        with pytest.raises(ValueError, match="action_type"):
            ManagePortalActionParams(
                action="create", kind="action", scope=SCOPE, fields={"name": "A"}
            )
        with pytest.raises(ValueError, match="scope"):
            ManagePortalActionParams(action="create", kind="group", fields={"name": "G"})

    def test_parameters_only_on_action_create(self):
        with pytest.raises(ValueError, match="parameters"):
            ManagePortalActionParams(
                action="create",
                kind="group",
                scope=SCOPE,
                fields={"name": "G"},
                parameters=[{"name": "a", "parameter_type": "string"}],
            )

    def test_update_needs_record_id(self):
        with pytest.raises(ValueError, match="record_id"):
            ManagePortalActionParams(action="update", kind="group", fields={"active": False})
