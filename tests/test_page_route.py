"""manage_portal_layout create_route / update_route (sp_page_route_map)."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import portal_layout as pl
from servicenow_mcp.tools.portal_crud_tools import ManagePortalLayoutParams
from servicenow_mcp.utils.config import ServerConfig

PAGE_FROM = "aaaa1111bbbb2222cccc3333dddd4444"
PAGE_TO = "bbbb2222cccc3333dddd4444eeee5555"
PORTAL_A = "cccc3333dddd4444eeee5555ffff6666"
PORTAL_B = "dddd4444eeee5555ffff6666aaaa1111"
ROUTE = "eeee5555ffff6666aaaa1111bbbb2222"
NEW_ROUTE = "ffff6666aaaa1111bbbb2222cccc3333"
SCOPE = "scope-route-test"

PAGE_OOTB = "aaaa2222bbbb3333cccc4444dddd5555"
PAGES = {"page_one": PAGE_FROM, "page_two": PAGE_TO, "page_ootb": PAGE_OOTB}
PORTALS = {"alpha": PORTAL_A, "beta": PORTAL_B}


class FakeServer:
    """In-memory sp_page / sp_portal / sp_page_route_map behind sn_query_page."""

    def __init__(self, routes=None, fail_routes=False, drop_on_write=()):
        self.routes = {r["sys_id"]: dict(r) for r in (routes or [])}
        self.fail_routes = fail_routes
        self.drop_on_write = set(drop_on_write)  # fields the server "ignores"
        self.writes = []

    def query(self, config, auth, *, table, query, fields, **kw):
        col, _, val = query.partition("=")
        if table == "sp_page":
            for pid, sid in PAGES.items():
                if (col == "id" and val == pid) or (col == "sys_id" and val == sid):
                    return [{"sys_id": sid, "id": pid, "title": pid}], 1
            return [], 0
        if table == "sp_portal":
            for suffix, sid in PORTALS.items():
                if (col == "url_suffix" and val == suffix) or (col == "sys_id" and val == sid):
                    return [{"sys_id": sid, "url_suffix": suffix, "title": suffix}], 1
            return [], 0
        if table == pl.ROUTE_TABLE:
            if self.fail_routes:
                raise RuntimeError("403 Forbidden")
            rows = [r for r in self.routes.values() if r.get(col) == val]
            return [dict(r) for r in rows], len(rows)
        raise AssertionError(f"unexpected table {table}")

    def request(self, method, url, json=None, **kw):
        self.writes.append((method, url, json))
        body = {k: v for k, v in (json or {}).items() if k not in self.drop_on_write}
        if method == "POST":
            row = {"sys_id": NEW_ROUTE, "order": "100", "short_description": "", **body}
            self.routes[NEW_ROUTE] = row
        else:
            self.routes[url.rsplit("/", 1)[1]].update(body)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"result": self.routes.get(NEW_ROUTE, {})}
        return resp


def _route(**over):
    row = {
        "sys_id": ROUTE,
        "route_from_page": PAGE_FROM,
        "route_to_page": PAGE_TO,
        "portals": "",
        "roles": "",
        "order": "100",
        "active": "true",
        "short_description": "",
    }
    row.update(over)
    return row


@pytest.fixture
def cfg():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


def _run(server, cfg, fn, **kw):
    auth = MagicMock()
    auth.get_headers.return_value = {}
    auth.make_request.side_effect = server.request
    with (
        patch.object(pl, "sn_query_page", side_effect=server.query),
        patch.object(pl, "invalidate_query_cache"),
    ):
        return fn(cfg, auth, **kw)


def _create(server, cfg, **kw):
    args = dict(route_from_page="page_one", route_to_page="page_two", scope=SCOPE)
    args.update(kw)
    return _run(server, cfg, pl.create_route, **args)


class TestCreateRoute:
    def test_happy_path_resolves_ids_and_verifies(self, cfg):
        s = FakeServer()
        r = _create(s, cfg, portals="alpha")
        assert r["success"] and r["complete"] is True and r["route_id"] == NEW_ROUTE
        body = s.writes[0][2]
        assert body["route_from_page"] == PAGE_FROM and body["route_to_page"] == PAGE_TO
        assert body["portals"] == PORTAL_A and body["sys_scope"] == SCOPE
        assert "active=false" in r["undo"]

    def test_dry_run_writes_nothing(self, cfg):
        s = FakeServer()
        r = _create(s, cfg, portals="alpha", dry_run=True)
        assert r["dry_run"] and s.writes == []

    def test_unknown_page_is_refused(self, cfg):
        s = FakeServer()
        r = _create(s, cfg, route_to_page="no_such_page")
        assert r["success"] is False and "no_such_page" in r["message"] and s.writes == []

    def test_unknown_portal_is_refused(self, cfg):
        s = FakeServer()
        r = _create(s, cfg, portals="alpha,gamma")
        assert r["success"] is False and "gamma" in r["message"] and s.writes == []

    def test_same_page_is_refused(self, cfg):
        r = _create(FakeServer(), cfg, route_to_page="page_one")
        assert r["success"] is False

    @pytest.mark.parametrize("existing_portals", ["", PORTAL_A])
    def test_overlapping_route_is_refused(self, cfg, existing_portals):
        s = FakeServer(routes=[_route(portals=existing_portals, active="false")])
        r = _create(s, cfg, portals="alpha")
        assert r["success"] is False and s.writes == []
        assert r["existing_routes"][0]["sys_id"] == ROUTE
        assert "update_route" in r["message"]

    def test_disjoint_portal_is_allowed(self, cfg):
        s = FakeServer(routes=[_route(portals=PORTAL_B)])
        r = _create(s, cfg, portals="alpha")
        assert r["success"] and r["other_routes_from_page"][0]["sys_id"] == ROUTE
        assert r["overrides"] == []

    def test_disjoint_roles_do_not_compete(self, cfg):
        s = FakeServer(routes=[_route(route_to_page=PAGE_OOTB, roles="admin")])
        r = _create(s, cfg, roles="itil")
        assert r["success"] and r["overrides"] == [] and r["order_chosen_to_win"] is False

    def test_empty_roles_compete_with_role_limited_route(self, cfg):
        """No roles means every user, so it overlaps a role-limited route."""
        s = FakeServer(routes=[_route(route_to_page=PAGE_OOTB, roles="admin", order="10")])
        r = _create(s, cfg, dry_run=True)
        assert r["overrides"][0]["sys_id"] == ROUTE

    def test_omitted_order_is_chosen_to_win_over_active_route(self, cfg):
        s = FakeServer(routes=[_route(route_to_page=PAGE_OOTB, order="10")])
        r = _create(s, cfg, portals="alpha")
        assert r["complete"] is True, r["missing"]
        assert r["order"] == 9 and r["order_chosen_to_win"] is True
        assert r["overrides"][0]["sys_id"] == ROUTE
        assert s.writes[0][2]["order"] == "9"

    @pytest.mark.parametrize("order", [10, 11])
    def test_explicit_order_that_loses_is_refused(self, cfg, order):
        """Lowest order wins and the older record wins a tie — 10 vs 10 never applies."""
        s = FakeServer(routes=[_route(route_to_page=PAGE_OOTB, order="10")])
        r = _create(s, cfg, order=order)
        assert r["success"] is False and "order 9" in r["message"] and s.writes == []

    def test_no_lower_order_left_is_refused(self, cfg):
        s = FakeServer(routes=[_route(route_to_page=PAGE_OOTB, order="0")])
        r = _create(s, cfg)
        assert r["success"] is False and s.writes == []

    def test_inactive_rival_does_not_compete(self, cfg):
        s = FakeServer(routes=[_route(route_to_page=PAGE_OOTB, order="10", active="false")])
        r = _create(s, cfg, dry_run=True)
        assert r["overrides"] == [] and r["order"] is None

    def test_unreadable_route_list_refuses_instead_of_creating(self, cfg):
        """An unread list must never read as 'no existing route'."""
        s = FakeServer(fail_routes=True)
        r = _create(s, cfg)
        assert r["success"] is False and "403" in r["message"] and s.writes == []

    def test_dropped_field_is_reported_not_confirmed(self, cfg):
        s = FakeServer(drop_on_write={"portals"})
        r = _create(s, cfg, portals="alpha")
        assert r["success"] and r["complete"] is False
        assert any("portals" in p for p in r["missing"])


class TestUpdateRoute:
    def _update(self, server, cfg, **kw):
        return _run(server, cfg, pl.update_route, route_id=ROUTE, **kw)

    def test_deactivate(self, cfg):
        s = FakeServer(routes=[_route()])
        r = self._update(s, cfg, active=False)
        assert r["complete"] is True and s.writes[0][2] == {"active": "false"}
        assert r["changes"]["active"] == {"from": True, "to": False}

    def test_dry_run(self, cfg):
        s = FakeServer(routes=[_route()])
        r = self._update(s, cfg, active=False, dry_run=True)
        assert r["dry_run"] and s.writes == []

    def test_not_found(self, cfg):
        r = self._update(FakeServer(), cfg, active=False)
        assert r["success"] is False and ROUTE in r["message"]

    def test_empty_portals_means_every_portal(self, cfg):
        s = FakeServer(routes=[_route(portals=PORTAL_A)])
        r = self._update(s, cfg, portals="")
        assert r["complete"] is True and s.writes[0][2] == {"portals": ""}

    def test_unconfirmed_write_is_flagged(self, cfg):
        s = FakeServer(routes=[_route()], drop_on_write={"active"})
        r = self._update(s, cfg, active=False)
        assert r["complete"] is False and "NOT confirmed" in r["message"]


class TestParams:
    @pytest.mark.parametrize("missing", ["route_from_page", "route_to_page", "scope"])
    def test_create_required(self, missing):
        kw = dict(action="create_route", route_from_page="a", route_to_page="b", scope="s")
        kw.pop(missing)
        with pytest.raises(ValueError, match=missing):
            ManagePortalLayoutParams(**kw)

    def test_update_needs_id_and_field(self):
        with pytest.raises(ValueError, match="route_id"):
            ManagePortalLayoutParams(action="update_route", active=False)
        with pytest.raises(ValueError, match="route field"):
            ManagePortalLayoutParams(action="update_route", route_id=ROUTE)
        ManagePortalLayoutParams(action="update_route", route_id=ROUTE, active=False)

    def test_tool_dispatches_update_in_the_routes_scope(self, cfg):
        from servicenow_mcp.tools import portal_crud_tools as pct

        with (
            patch.object(pl, "update_route", return_value={"success": True}) as up,
            patch.object(
                pct, "sn_query_page", return_value=([{"sys_id": ROUTE, "sys_scope": SCOPE}], 1)
            ),
            patch.object(pct, "align_session_for_create", return_value={}) as align,
        ):
            pct.manage_portal_layout(
                cfg,
                MagicMock(),
                ManagePortalLayoutParams(action="update_route", route_id=ROUTE, active=False),
            )
        assert up.call_args.kwargs == {"route_id": ROUTE, "dry_run": False, "active": False}
        assert align.call_args.kwargs == {"scope": SCOPE}

    def test_unreadable_route_scope_changes_nothing(self, cfg):
        from servicenow_mcp.tools import portal_crud_tools as pct

        with (
            patch.object(pl, "update_route") as up,
            patch.object(pct, "sn_query_page", side_effect=RuntimeError("403")),
        ):
            r = pct.manage_portal_layout(
                cfg,
                MagicMock(),
                ManagePortalLayoutParams(action="update_route", route_id=ROUTE, active=False),
            )
        assert r["success"] is False
        up.assert_not_called()


class TestCreateRouteScope:
    def test_route_landing_in_another_scope_is_not_confirmed(self, cfg):
        """ServiceNow takes the scope from the session, not the body."""
        s = FakeServer(drop_on_write={"sys_scope"})
        r = _create(s, cfg)
        assert r["success"] and r["complete"] is False
        assert any("sys_scope" in p for p in r["missing"])

    def test_tool_aligns_scope_before_create_but_not_on_dry_run(self, cfg):
        from servicenow_mcp.tools import portal_crud_tools as pct

        args = dict(
            action="create_route", route_from_page="page_one", route_to_page="page_two", scope=SCOPE
        )
        with (
            patch.object(pct, "align_session_for_create", return_value={}) as align,
            patch.object(pl, "create_route", return_value={"success": True}),
        ):
            pct.manage_portal_layout(cfg, MagicMock(), ManagePortalLayoutParams(**args))
            assert align.call_args.kwargs == {"scope": SCOPE}
            align.reset_mock()
            pct.manage_portal_layout(
                cfg, MagicMock(), ManagePortalLayoutParams(**args, dry_run=True)
            )
            align.assert_not_called()

    def test_tool_aborts_when_scope_switch_fails(self, cfg):
        from servicenow_mcp.tools import portal_crud_tools as pct

        err = {"success": False, "error": "scope_switch_failed"}
        with (
            patch.object(pct, "align_session_for_create", return_value={"error": err}),
            patch.object(pl, "create_route") as create,
        ):
            r = pct.manage_portal_layout(
                cfg,
                MagicMock(),
                ManagePortalLayoutParams(
                    action="create_route",
                    route_from_page="page_one",
                    route_to_page="page_two",
                    scope=SCOPE,
                ),
            )
        assert r == err
        create.assert_not_called()
