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
            self.tables.setdefault(table, []).append({"sys_scope": SCOPE, **row})
        # Mimics the Employee Center BR: inserting an action adds a blank
        # string parameter per name in its type's server_parameters.
        self.br_stub_names = []
        self.drop = set(drop_on_write)
        self.scope_lands = scope_lands
        self.fail_read = fail_read
        self.writes = []
        self.fail_delete = set()
        self.keep_on_delete = set()
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
            if table == "sn_ex_sp_action":
                for name in self.br_stub_names:
                    self.tables.setdefault("sn_ex_sp_action_parameter", []).append(
                        {
                            "sys_id": next(self._ids),
                            "name": name,
                            "action": row["sys_id"],
                            "parameter_type": "string",
                            "is_client": "false",
                            "sys_scope": self.scope_lands,
                        }
                    )
        elif method == "DELETE":
            if parts[1] in self.fail_delete:
                raise RuntimeError("403 delete denied")
            row = {}
            if parts[1] not in self.keep_on_delete:
                self.tables[table] = [r for r in self.tables[table] if r["sys_id"] != parts[1]]
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
        assert "preview_delete" in r["undo"] and r["sys_id"] in r["undo"]
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
        assert "preview_delete" in r["undo"]

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
        assert r["changes"][0]["changes"] == {"active": {"from": "true", "to": "false"}}

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


ACT_ID = "dddd4444eeee5555ffff6666aaaa1111"
PARAM_ID = "eeee5555ffff6666aaaa1111bbbb2222"
LINK_ID = "ffff6666aaaa1111bbbb2222cccc3333"


def _button_set():
    """type <- action <- parameter, action <- link -> group."""
    return [
        ("sn_ex_sp_action_type", {"sys_id": TYPE_ID, "name": "T"}),
        ("sn_ex_sp_action", {"sys_id": ACT_ID, "name": "A", "action_type": TYPE_ID}),
        ("sn_ex_sp_action_parameter", {"sys_id": PARAM_ID, "name": "p", "action": ACT_ID}),
        ("sn_ex_sp_action_group", {"sys_id": GROUP_ID, "name": "G"}),
        (
            "sn_ex_sp_m2m_action_group",
            {"sys_id": LINK_ID, "group": GROUP_ID, "action": ACT_ID},
        ),
    ]


_ALL = [
    {"kind": "type", "record_id": TYPE_ID},
    {"kind": "group", "record_id": GROUP_ID},
    {"kind": "action", "record_id": ACT_ID},
    {"kind": "link", "record_id": LINK_ID},
    {"kind": "parameter", "record_id": PARAM_ID},
]


def _deleted_ids(server):
    return [w[1].rsplit("/", 1)[1] for w in server.writes if w[0] == "DELETE"]


def _audit_rows(server, ids):
    for rid in ids:
        server.tables.setdefault("sys_audit_delete", []).append(
            {"sys_id": "aaaa9999" + rid[8:], "documentkey": rid}
        )


def _preview(server, cfg, **target):
    return _call(server, cfg, action="preview_delete", **target)


def _approved_delete(server, cfg, **target):
    """preview_delete, then delete with exactly what the preview returned."""
    p = _preview(server, cfg, **target)
    assert p["preview"] is True, p
    return _call(
        server,
        cfg,
        action="delete",
        preview_token=p["preview_token"],
        confirm_count=p["count"],
        **target,
    )


class TestDelete:
    def test_preview_writes_nothing_and_does_not_switch_scope(self, cfg):
        s = FakeServer(rows=_button_set())
        r = _preview(s, cfg, records=_ALL)
        assert r["count"] == 5 and s.writes == []
        assert [p["kind"] for p in r["plan"]] == ["link", "parameter", "action", "group", "type"]
        assert "explicit go-ahead" in r["next"] and r["preview_token"] in r["next"]
        r["_align"].assert_not_called()

    def test_delete_without_token_is_refused_by_the_schema(self):
        with pytest.raises(ValueError, match="preview_token"):
            ManagePortalActionParams(action="delete", kind="parameter", record_id=PARAM_ID)
        with pytest.raises(ValueError, match="preview_token"):
            ManagePortalActionParams(action="delete", records=_ALL, confirm_count=5)

    def test_single_delete_is_verified_and_reports_recovery(self, cfg):
        s = FakeServer(rows=_button_set())
        _audit_rows(s, [PARAM_ID])
        r = _approved_delete(s, cfg, kind="parameter", record_id=PARAM_ID)
        assert r["complete"] is True and _deleted_ids(s) == [PARAM_ID]
        assert r["deleted"][0]["recoverable"] is True
        assert "Undelete" in r["restore"]

    def test_missing_delete_audit_says_not_restorable(self, cfg):
        s = FakeServer(rows=_button_set())
        r = _approved_delete(s, cfg, kind="parameter", record_id=PARAM_ID)
        assert r["deleted"][0]["recoverable"] is False
        assert "NOT confirmed restorable" in r["restore"]

    def test_whole_set_deletes_children_first(self, cfg):
        s = FakeServer(rows=_button_set())
        _audit_rows(s, [LINK_ID, PARAM_ID, ACT_ID, GROUP_ID, TYPE_ID])
        r = _approved_delete(s, cfg, records=_ALL)
        assert r["complete"] is True, r["missing"]
        assert _deleted_ids(s) == [LINK_ID, PARAM_ID, ACT_ID, GROUP_ID, TYPE_ID]

    def test_wrong_token_deletes_nothing(self, cfg):
        s = FakeServer(rows=_button_set())
        r = _call(
            s,
            cfg,
            action="delete",
            records=_ALL,
            preview_token="0000000000000000",
            confirm_count=5,
        )
        assert r["error"] == "PREVIEW_STALE" and s.writes == []

    def test_wrong_count_deletes_nothing(self, cfg):
        s = FakeServer(rows=_button_set())
        p = _preview(s, cfg, records=_ALL)
        r = _call(
            s,
            cfg,
            action="delete",
            records=_ALL,
            preview_token=p["preview_token"],
            confirm_count=4,
        )
        assert r["error"] == "PREVIEW_STALE" and s.writes == []

    def test_record_edited_after_preview_deletes_nothing(self, cfg):
        s = FakeServer(rows=_button_set())
        p = _preview(s, cfg, records=_ALL)
        s.tables["sn_ex_sp_action_group"][0]["sys_mod_count"] = "7"
        r = _call(
            s,
            cfg,
            action="delete",
            records=_ALL,
            preview_token=p["preview_token"],
            confirm_count=5,
        )
        assert r["error"] == "PREVIEW_STALE" and s.writes == []

    def test_token_for_one_set_does_not_delete_another(self, cfg):
        s = FakeServer(rows=_button_set())
        p = _preview(s, cfg, kind="parameter", record_id=PARAM_ID)
        r = _call(
            s,
            cfg,
            action="delete",
            kind="link",
            record_id=LINK_ID,
            preview_token=p["preview_token"],
            confirm_count=1,
        )
        assert r["error"] == "PREVIEW_STALE" and s.writes == []

    def test_record_still_pointed_at_is_refused_even_in_preview(self, cfg):
        s = FakeServer(rows=_button_set())
        r = _preview(s, cfg, kind="type", record_id=TYPE_ID)
        assert r["success"] is False and r["dependents"][0]["record_id"] == ACT_ID

    def test_dependent_outside_the_request_blocks_all(self, cfg):
        s = FakeServer(rows=_button_set())
        partial = [r for r in _ALL if r["kind"] != "link"]
        r = _preview(s, cfg, records=partial)
        assert r["success"] is False
        assert {d["record_id"] for d in r["dependents"]} == {LINK_ID}

    def test_missing_record_is_refused(self, cfg):
        s = FakeServer(rows=_button_set())
        recs = _ALL + [{"kind": "group", "record_id": "aaaa0000bbbb0000cccc0000dddd0000"}]
        r = _preview(s, cfg, records=recs)
        assert r["success"] is False

    def test_unreadable_dependents_refuse(self, cfg):
        s = FakeServer(rows=_button_set(), fail_read="sn_ex_sp_m2m_action_group")
        r = _preview(s, cfg, kind="group", record_id=GROUP_ID)
        assert r["success"] is False

    def test_stops_at_first_failure_and_reports_remaining(self, cfg):
        s = FakeServer(rows=_button_set())
        s.fail_delete = {ACT_ID}
        r = _approved_delete(s, cfg, records=_ALL)
        assert r["complete"] is False
        assert [d["record_id"] for d in r["deleted"]] == [LINK_ID, PARAM_ID]
        assert [d["record_id"] for d in r["not_deleted"]] == [ACT_ID, GROUP_ID, TYPE_ID]

    def test_record_surviving_delete_is_not_confirmed(self, cfg):
        s = FakeServer(rows=_button_set())
        s.keep_on_delete = {PARAM_ID}
        r = _approved_delete(s, cfg, kind="parameter", record_id=PARAM_ID)
        assert r["complete"] is False and "still exists" in r["missing"][0]


class TestBulkUpdate:
    def _groups(self):
        return [
            ("sn_ex_sp_action_group", {"sys_id": GROUP_ID, "name": "G", "active": "true"}),
            ("sn_ex_sp_action_group", {"sys_id": TYPE_ID, "name": "H", "active": "true"}),
        ]

    _KW = dict(kind="group", record_ids=[GROUP_ID, TYPE_ID], fields={"active": False})

    def test_many_needs_a_preview_token(self):
        with pytest.raises(ValueError, match="preview_token"):
            ManagePortalActionParams(action="update", **self._KW)

    def test_preview_then_apply(self, cfg):
        s = FakeServer(rows=self._groups())
        p = _call(s, cfg, action="preview_update", **self._KW)
        assert p["count"] == 2 and s.writes == []
        r = _call(
            s,
            cfg,
            action="update",
            preview_token=p["preview_token"],
            confirm_count=2,
            **self._KW,
        )
        assert r["complete"] is True and r["updated"] == [GROUP_ID, TYPE_ID]

    def test_count_is_what_actually_changes(self, cfg):
        rows = self._groups()
        rows[1][1]["active"] = "false"
        s = FakeServer(rows=rows)
        p = _call(s, cfg, action="preview_update", **self._KW)
        assert p["count"] == 1

    def test_changed_after_preview_changes_nothing(self, cfg):
        s = FakeServer(rows=self._groups())
        p = _call(s, cfg, action="preview_update", **self._KW)
        s.tables["sn_ex_sp_action_group"][1]["active"] = "false"
        r = _call(
            s,
            cfg,
            action="update",
            preview_token=p["preview_token"],
            confirm_count=2,
            **self._KW,
        )
        assert r["error"] == "PREVIEW_STALE" and s.writes == []

    def test_single_update_needs_no_token(self, cfg):
        s = FakeServer(rows=self._groups())
        r = _call(
            s, cfg, action="update", kind="group", record_id=GROUP_ID, fields={"active": False}
        )
        assert r["complete"] is True


class TestBatchParams:
    def test_records_takes_nothing_else(self):
        with pytest.raises(ValueError, match="not both"):
            ManagePortalActionParams(action="preview_delete", kind="group", records=_ALL)

    def test_record_ids_is_not_for_delete(self):
        with pytest.raises(ValueError, match="nothing else"):
            ManagePortalActionParams(action="preview_delete", kind="group", record_ids=[GROUP_ID])

    def test_duplicates_rejected(self):
        with pytest.raises(ValueError, match="twice"):
            ManagePortalActionParams(
                action="preview_update",
                kind="group",
                record_ids=[GROUP_ID, GROUP_ID],
                fields={"active": False},
            )


class TestPlatformParameterStubs:
    def _create_action(self, s, cfg, params):
        return _call(
            s,
            cfg,
            action="create",
            kind="action",
            scope=SCOPE,
            fields={"name": "Do it", "table": "sc_req_item", "action_type": TYPE_ID},
            parameters=params,
        )

    def test_requested_parameter_fills_the_stub_instead_of_duplicating(self, cfg):
        s = FakeServer(rows=[_type_row()])
        s.br_stub_names = ["sys_id"]
        r = self._create_action(
            s,
            cfg,
            [
                {
                    "name": "sys_id",
                    "parameter_type": "table",
                    "table": "sc_req_item",
                    "field": "sys_id",
                }
            ],
        )
        assert r["complete"] is True, r["missing"]
        params = s.tables["sn_ex_sp_action_parameter"]
        assert len(params) == 1 and params[0]["parameter_type"] == "table"
        assert params[0]["field"] == "sys_id"
        assert "added_by_platform" not in r

    def test_unrequested_stub_is_reported_and_in_undo(self, cfg):
        s = FakeServer(rows=[_type_row()])
        s.br_stub_names = ["sys_id", "targetStage"]
        r = self._create_action(s, cfg, [{"name": "sys_id", "parameter_type": "string"}])
        assert [p["name"] for p in r["added_by_platform"]] == ["targetStage"]
        assert r["undo"].count("parameter") == 2


class TestScopeForChanges:
    def test_delete_reports_the_scope_switch(self, cfg):
        s = FakeServer(rows=[("sn_ex_sp_action_group", {"sys_id": GROUP_ID, "name": "G"})])
        switch = {"scope_switch": {"switched": True}}
        auth = MagicMock()
        auth.get_headers.return_value = {}
        auth.make_request.side_effect = s.request
        with (
            patch.object(pa, "sn_query_page", side_effect=s.query),
            patch.object(pa, "invalidate_query_cache"),
            patch.object(pa, "align_session_for_create", return_value=switch),
        ):
            target = dict(kind="group", record_id=GROUP_ID)
            p = manage_portal_action(
                cfg, auth, ManagePortalActionParams(action="preview_delete", **target)
            )
            r = manage_portal_action(
                cfg,
                auth,
                ManagePortalActionParams(
                    action="delete",
                    preview_token=p["preview_token"],
                    confirm_count=1,
                    **target,
                ),
            )
        assert r["complete"] is True and r["scope_switch"] == {"switched": True}

    def test_update_aligns_to_the_records_scope(self, cfg):
        s = FakeServer(rows=[("sn_ex_sp_action_group", {"sys_id": GROUP_ID, "active": "true"})])
        r = _call(
            s, cfg, action="update", kind="group", record_id=GROUP_ID, fields={"active": False}
        )
        assert r["_align"].call_args.kwargs == {"scope": SCOPE}

    def test_delete_across_scopes_is_refused(self, cfg):
        s = FakeServer(
            rows=[
                ("sn_ex_sp_action_parameter", {"sys_id": PARAM_ID, "name": "p"}),
                (
                    "sn_ex_sp_action_parameter",
                    {"sys_id": LINK_ID, "name": "q", "sys_scope": "global"},
                ),
            ]
        )
        r = _approved_delete(
            s,
            cfg,
            records=[
                {"kind": "parameter", "record_id": PARAM_ID},
                {"kind": "parameter", "record_id": LINK_ID},
            ],
        )
        assert r["success"] is False and "more than one scope" in r["message"]
        assert s.writes == []

    def test_dry_run_does_not_switch_scope(self, cfg):
        s = FakeServer(rows=[("sn_ex_sp_action_group", {"sys_id": GROUP_ID, "name": "G"})])
        r = _preview(s, cfg, kind="group", record_id=GROUP_ID)
        r["_align"].assert_not_called()
