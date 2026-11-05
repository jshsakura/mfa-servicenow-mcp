"""clone_widget / clone_header_footer (portal component) and replace_widget (layout)."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import portal_component as pc
from servicenow_mcp.services import portal_layout as pl
from servicenow_mcp.tools.portal_crud_tools import (
    ManagePortalComponentParams,
    ManagePortalLayoutParams,
)
from servicenow_mcp.utils.config import ServerConfig

SRC = "aaaa1111bbbb2222cccc3333dddd4444"
NEW = "bbbb2222cccc3333dddd4444eeee5555"
DEP1 = "cccc3333dddd4444eeee5555ffff6666"
PRV1 = "dddd4444eeee5555ffff6666aaaa1111"
INST = "eeee5555ffff6666aaaa1111bbbb2222"
OLD_W = "ffff6666aaaa1111bbbb2222cccc3333"
SCOPE = "scope-clone-test"
PROVIDER_M2M = "m2m_sp_ng_pro_sp_widget"

SOURCE_ROW = {
    "sys_id": SRC,
    "id": "sample_widget",
    "name": "Sample Widget",
    "sys_scope": SCOPE,
    "template": "<div>\r\nhi</div>",
    "script": "(function(){})();",
    "client_script": "function c(){}",
    "link": "",
    "css": ".a{}",
    "option_schema": "[]",
    "demo_data": "",
    "data_table": "sp_instance",
    "field_list": "",
    "controller_as": "c",
    "public": "false",
    "roles": "",
    "has_preview": "false",
    "description": "d",
    "category": "custom",
    "internal": "false",
}


@pytest.fixture
def cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def auth():
    a = MagicMock()
    a.get_headers.return_value = {}
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    a.make_request.return_value = resp
    return a


class FakeServer:
    """In-memory sn_query_page + POST: answers by table and query text."""

    def __init__(self, dep_rows=1, prov_rows=1, drop_field=None, drop_m2m=False):
        self.rows = {PROVIDER_M2M: [], pc._DEPENDENCY_M2M: []}
        self.src_deps = [DEP1] * 0 + [DEP1][:dep_rows]
        self.src_provs = [PRV1][:prov_rows]
        self.clone = None
        self.drop_field = drop_field
        self.drop_m2m = drop_m2m
        self.existing_id = None
        self.source_rows = [dict(SOURCE_ROW)]
        self.posts = []

    def query(self, config, auth, *, table, query, fields, **kw):
        if table in ("sp_widget", "sp_header_footer"):
            if query.startswith(f"sys_id={NEW}"):
                return ([self.clone] if self.clone else []), 1
            if query.startswith("id=new_one") or query.startswith("name=Clone"):
                return ([{"sys_id": "x"}] if self.existing_id else []), 0
            return list(self.source_rows), len(self.source_rows)
        if table == PROVIDER_M2M or table == pc._DEPENDENCY_M2M:
            ref = "sp_dependency" if table == pc._DEPENDENCY_M2M else "sp_angular_provider"
            if f"sp_widget={SRC}" in query:
                src = self.src_deps if ref == "sp_dependency" else self.src_provs
                return [{ref: v} for v in src], len(src)
            if f"sp_widget={NEW}" in query:
                got = [] if self.drop_m2m else [r for r in self.rows[table]]
                return [{ref: r} for r in got], len(got)
        return [], 0

    def create(self, config, auth, table, body, timeout=30):
        self.posts.append((table, dict(body)))
        if table in ("sp_widget", "sp_header_footer"):
            rec = {k: v for k, v in body.items() if k != "sys_scope"}
            if self.drop_field:
                rec.pop(self.drop_field, None)
            rec["sys_id"] = NEW
            self.clone = rec
            return {
                "success": True,
                "result": {"sys_id": NEW, "id": body["id"], "name": body["name"]},
            }
        self.rows[table].append(body.get("sp_dependency") or body.get("sp_angular_provider"))
        return {"success": True, "result": {}}


def _run(server, cfg, auth, **kw):
    args = dict(
        table="sp_widget", source="sample_widget", new_id="new_one", name="Clone One", scope=SCOPE
    )
    args.update(kw)
    with (
        patch.object(pc, "sn_query_page", side_effect=server.query),
        patch.object(pc, "_create_record", side_effect=server.create),
        patch.object(pc, "invalidate_query_cache"),
        patch(
            "servicenow_mcp.tools.portal_dev_tools.resolve_angular_provider_m2m",
            return_value=PROVIDER_M2M,
        ),
    ):
        return pc.clone_component(cfg, auth, **args)


class TestCloneWidget:
    def test_happy_path_is_complete(self, cfg, auth):
        s = FakeServer()
        r = _run(s, cfg, auth)
        assert r["success"] and r["complete"] is True
        assert r["m2m"]["dependency"]["expected"] == 1 and r["m2m"]["dependency"]["created"] == 1
        assert r["m2m"]["provider"]["created"] == 1
        body = s.posts[0][1]
        assert "docs" not in body and "servicenow" not in body
        assert body["template"] == SOURCE_ROW["template"]
        assert "link" not in body  # empty in source, not sent
        assert all(r["applied"].values())
        # relations are referenced, never copied
        assert [p[0] for p in s.posts[1:]] == [pc._DEPENDENCY_M2M, PROVIDER_M2M]

    def test_dry_run_writes_nothing(self, cfg, auth):
        s = FakeServer()
        r = _run(s, cfg, auth, dry_run=True)
        assert r["dry_run"] and s.posts == []
        assert "template" in r["would_copy_fields"] and "link" in r["empty_in_source"]
        assert r["would_create_m2m"]["dependency"]["rows"] == 1

    def test_missing_field_is_incomplete(self, cfg, auth):
        r = _run(FakeServer(drop_field="script"), cfg, auth)
        assert r["success"] and r["complete"] is False
        assert r["applied"]["script"] is False
        assert "script" in r["message"]

    def test_missing_m2m_is_incomplete(self, cfg, auth):
        r = _run(FakeServer(drop_m2m=True), cfg, auth)
        assert r["complete"] is False
        assert r["m2m"]["dependency"]["missing_ids"] == [DEP1]

    def test_existing_id_refused(self, cfg, auth):
        s = FakeServer()
        s.existing_id = True
        r = _run(s, cfg, auth)
        assert r["success"] is False and "already exists" in r["message"] and s.posts == []

    def test_source_not_found_and_ambiguous(self, cfg, auth):
        s = FakeServer()
        s.source_rows = []
        assert _run(s, cfg, auth)["success"] is False
        s.source_rows = [dict(SOURCE_ROW), dict(SOURCE_ROW, sys_id=NEW)]
        r = _run(s, cfg, auth)
        assert r["success"] is False and len(r["candidates"]) == 2 and s.posts == []

    def test_unreadable_relations_refused(self, cfg, auth):
        s = FakeServer()
        orig = s.query

        def boom(config, auth, **kw):
            if kw["table"] == pc._DEPENDENCY_M2M:
                raise RuntimeError("403")
            return orig(config, auth, **kw)

        s.query = boom
        r = _run(s, cfg, auth)
        assert r["success"] is False and s.posts == []

    def test_header_footer_has_no_m2m(self, cfg, auth):
        s = FakeServer()
        r = _run(s, cfg, auth, table="sp_header_footer")
        assert r["complete"] is True and r["m2m"] == {}
        assert [p[0] for p in s.posts] == ["sp_header_footer"]


class TestCloneParams:
    @pytest.mark.parametrize("missing", ["source", "new_id", "name", "scope"])
    def test_required(self, missing):
        kw = dict(action="clone_widget", source="w", new_id="n", name="N", scope="s")
        kw.pop(missing)
        with pytest.raises(ValueError, match=missing):
            ManagePortalComponentParams(**kw)


class TestReplaceWidget:
    def _server(self, after_widget=NEW, after_params="p"):
        state = {"n": 0}

        def query(config, auth, *, table, query, fields, **kw):
            if table == "sp_instance":
                state["n"] += 1
                w = OLD_W if state["n"] == 1 else after_widget
                return [
                    {
                        "sp_widget": w,
                        "widget_parameters": "p" if state["n"] == 1 else after_params,
                        "css": "",
                        "sp_column": "c",
                        "order": "1",
                    }
                ], 1
            if query == f"sys_id={OLD_W}":
                return [{"sys_id": OLD_W, "id": "old_w", "name": "Old"}], 1
            if query.startswith(("id=", "sys_id=")):
                return [{"sys_id": NEW, "id": "new_w", "name": "New", "sys_scope": SCOPE}], 1
            return [], 0

        return query

    def _call(self, cfg, auth, q, **kw):
        with (
            patch.object(pl, "sn_query_page", side_effect=q),
            patch.object(pl, "invalidate_query_cache"),
        ):
            return pl.replace_widget(cfg, auth, instance_id=INST, sp_widget="new_w", **kw)

    def test_dry_run(self, cfg, auth):
        r = self._call(cfg, auth, self._server(), dry_run=True)
        assert (
            r["dry_run"] and r["old_widget"]["id"] == "old_w" and r["new_widget"]["id"] == "new_w"
        )
        auth.make_request.assert_not_called()

    def test_replace_verified(self, cfg, auth):
        r = self._call(cfg, auth, self._server())
        assert r["complete"] is True
        assert auth.make_request.call_args.kwargs["json"] == {"sp_widget": NEW}

    def test_not_confirmed_when_widget_unchanged(self, cfg, auth):
        r = self._call(cfg, auth, self._server(after_widget=OLD_W))
        assert r["complete"] is False and "sp_widget did not change" in r["missing"]

    def test_params_changed_is_flagged(self, cfg, auth):
        r = self._call(cfg, auth, self._server(after_params="other"))
        assert r["complete"] is False

    def test_validator(self):
        with pytest.raises(ValueError, match="sp_widget"):
            ManagePortalLayoutParams(action="replace_widget", instance_id=INST)
