"""manage_data_update: every gate refuses before a single write, and apply writes
exactly what the preview showed. Each refusal test also asserts NO PATCH went out."""

import json
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.policies.write_guards import _is_read_only
from servicenow_mcp.services import data_update as svc
from servicenow_mcp.tools.data_update_tools import ManageDataUpdateParams, manage_data_update
from servicenow_mcp.utils.config import ServerConfig

A = "aaaa1111bbbb2222cccc3333dddd0001"
B = "aaaa1111bbbb2222cccc3333dddd0002"
C = "aaaa1111bbbb2222cccc3333dddd0003"
USER = "eeee5555ffff6666aaaa7777bbbb8888"


class Fake:
    """A tiny instance: rows per table, a dictionary, a choice list, PATCH log."""

    def __init__(self):
        self.tables: Dict[str, List[Dict[str, str]]] = {
            "x_myapp_order": [
                {
                    "sys_id": A,
                    "number": "ORD1",
                    "state": "1",
                    "owner": "",
                    "active": "true",
                    "region": "east",
                },
                {
                    "sys_id": B,
                    "number": "ORD2",
                    "state": "1",
                    "owner": "",
                    "active": "true",
                    "region": "west",
                },
                {
                    "sys_id": C,
                    "number": "ORD3",
                    "state": "2",
                    "owner": "",
                    "active": "false",
                    "region": "east",
                },
            ],
            "sys_user": [{"sys_id": USER, "name": "alice", "user_name": "alice"}],
        }
        self.ancestry = {
            "x_myapp_order": ["x_myapp_order"],
            "sys_user": ["sys_user"],
            "x_myapp_cfg": ["x_myapp_cfg", "sys_metadata"],
        }
        self.columns = {
            "x_myapp_order": {
                "sys_id",
                "number",
                "state",
                "owner",
                "active",
                "region",
                "sys_updated_on",
            },
            "sys_user": {"sys_id", "name", "user_name"},
        }
        self.dictionary = {
            ("x_myapp_order", "state"): {
                "internal_type": "integer",
                "reference": "",
                "choice": "3",
            },
            ("x_myapp_order", "owner"): {
                "internal_type": "reference",
                "reference": "sys_user",
                "choice": "0",
            },
            ("x_myapp_order", "active"): {
                "internal_type": "boolean",
                "reference": "",
                "choice": "0",
            },
            ("x_myapp_order", "region"): {
                "internal_type": "string",
                "reference": "",
                "choice": "0",
            },
            ("sys_user", "name"): {"internal_type": "string", "reference": "", "choice": "0"},
        }
        self.patches: List[Dict[str, Any]] = []
        self.report_count = True
        self.fail_patch_on: str = ""
        self.rewrite: Dict[str, str] = {}
        self.acl_hidden = 0
        self.derive = None  # a business rule: called with the row after each PATCH

    @staticmethod
    def _match(row: Dict[str, str], query: str) -> bool:
        if not query:
            return True
        for cond in query.split("^"):
            if cond.startswith("ORDERBY") or not cond:
                continue
            if "IN" in cond and "=" not in cond:
                f, vals = cond.split("IN", 1)
                if row.get(f) not in vals.split(","):
                    return False
            elif "=" in cond:
                f, v = cond.split("=", 1)
                if f not in row:
                    continue  # the server DROPS an unknown-field condition
                if row.get(f) != v:
                    return False
        return True

    def query_page(
        self, config, auth, *, table, query, fields, limit, offset, no_count=False, **kw
    ):
        if table == "sys_dictionary":
            parts = dict(p.split("IN", 1) for p in query.split("^"))
            names, els = parts["name"].split(","), parts["element"].split(",")
            out = []
            for (t, e), info in self.dictionary.items():
                if t in names and e in els:
                    out.append({"name": t, "element": e, **info})
            return out, None
        if table in ("sys_script", "sysevent_email_action"):
            return [], 2
        # copies, as a server sends: a later PATCH must not reach into a read already returned
        rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, query)]
        total = len(rows) if self.report_count else None
        if self.acl_hidden and fields != "sys_id":
            rows = rows[self.acl_hidden :]
        return rows[offset : offset + limit], total

    def make_request(self, method, url, **kw):
        assert method == "PATCH", method
        sid = url.rsplit("/", 1)[-1]
        self.patches.append({"sys_id": sid, "json": dict(kw["json"])})
        resp = MagicMock()
        if sid == self.fail_patch_on:
            resp.raise_for_status.side_effect = RuntimeError("403 data policy")
            return resp
        row = next(r for r in self.tables["x_myapp_order"] if r["sys_id"] == sid)
        row.update(kw["json"])
        for f, v in self.rewrite.items():
            if f in kw["json"]:
                row[f] = v
        if self.derive:
            self.derive(row)
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"result": dict(row)}
        return resp


@pytest.fixture
def fake(monkeypatch, tmp_path):
    f = Fake()
    monkeypatch.setattr(svc, "sn_query_page", f.query_page)
    monkeypatch.setattr(svc, "table_ancestry", lambda c, a, t: f.ancestry.get(t))
    monkeypatch.setattr(svc, "table_columns", lambda c, a, t: f.columns.get(t))
    monkeypatch.setattr(svc, "state_dir", lambda: tmp_path)

    def choice(config, auth, *, table, element, requested, **kw):
        codes = {"1": "1", "Open": "1", "2": "2", "Closed": "2"}
        if requested in codes:
            return codes[requested], None
        return None, {"success": False, "error": "UNKNOWN_CHOICE", "message": "no"}

    monkeypatch.setattr(svc, "resolve_choice", choice)
    return f


@pytest.fixture
def config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def auth(fake):
    m = MagicMock()
    m.make_request.side_effect = fake.make_request
    m.get_headers.return_value = {}
    return m


def run(config, auth, **kw):
    return manage_data_update(config, auth, ManageDataUpdateParams(**kw))


def preview(config, auth, **kw):
    return run(config, auth, action="preview", **kw)


# --- Gate 1: tables ----------------------------------------------------------


@pytest.mark.parametrize(
    "table", ["sys_user", "sysapproval_approver", "syslog", "ecc_queue", "v_plugin", "x_myapp_cfg"]
)
def test_system_and_config_tables_are_refused(fake, config, auth, table):
    r = preview(config, auth, table=table, query="active=true", set={"region": "x"})
    assert r["success"] is False and r["error"] == "TABLE_NOT_ALLOWED"
    assert fake.patches == []


# --- Gate 2: the condition ---------------------------------------------------


def test_an_unknown_field_in_the_condition_is_refused_not_dropped(fake, config, auth):
    r = preview(config, auth, table="x_myapp_order", query="statee=1", set={"region": "x"})
    assert r["error"] == "UNKNOWN_QUERY_FIELDS"
    assert "state" in r["did_you_mean"]["statee"]


def test_an_unreadable_condition_is_refused_not_skipped(fake, config, auth):
    r = preview(
        config, auth, table="x_myapp_order", query="state=1^123TEXTQUERY321foo", set={"region": "x"}
    )
    assert r["error"] == "CONDITION_UNVERIFIABLE"


def test_a_script_condition_is_refused(fake, config, auth):
    r = preview(
        config,
        auth,
        table="x_myapp_order",
        query="owner=javascript:gs.getUserID()",
        set={"region": "x"},
    )
    assert r["error"] == "CONDITION_NOT_DETERMINISTIC"


def test_a_dotwalk_with_an_unknown_far_field_is_refused(fake, config, auth):
    # state=1^owner.nmae=alice: the server would drop the second condition and
    # update every state=1 row — not the whole table, so only this check stops it.
    r = preview(
        config, auth, table="x_myapp_order", query="state=1^owner.nmae=alice", set={"region": "x"}
    )
    assert r["error"] == "UNKNOWN_QUERY_FIELDS"
    assert "nmae" in r["message"]


def test_a_dotwalk_through_a_non_reference_is_refused(fake, config, auth):
    r = preview(config, auth, table="x_myapp_order", query="region.name=x", set={"region": "x"})
    assert r["error"] == "CONDITION_UNVERIFIABLE"


def test_a_valid_dotwalk_passes(fake, config, auth):
    fake.tables["x_myapp_order"][0]["owner.name"] = "alice"
    r = preview(
        config, auth, table="x_myapp_order", query="state=1^owner.name=alice", set={"region": "x"}
    )
    assert r["success"] is True


# --- Gates 3 and 4: scope ----------------------------------------------------


def test_a_condition_matching_the_whole_table_needs_a_named_approval(fake, config, auth):
    r = preview(config, auth, table="x_myapp_order", query="sys_idISNOTEMPTY", set={"region": "x"})
    assert r["error"] == "WHOLE_TABLE"
    ok = preview(
        config,
        auth,
        table="x_myapp_order",
        query="sys_idISNOTEMPTY",
        set={"region": "x"},
        confirm_whole_table="x_myapp_order",
    )
    assert ok["success"] is True and ok["will_change"] == 3


def test_over_the_cap_is_refused_with_the_count_never_cut(fake, config, auth):
    r = preview(
        config, auth, table="x_myapp_order", query="state=1", set={"region": "x"}, max_rows=1
    )
    assert r["error"] == "OVER_CAP" and r["matched"] == 2


def test_an_unreported_count_refuses(fake, config, auth):
    fake.report_count = False
    r = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "x"})
    assert r["error"] == "COUNT_UNVERIFIED"


def test_rows_the_server_counts_but_withholds_refuse(fake, config, auth):
    # X-Total-Count says 2, the ACL returns 1: the scope the user reviews would not
    # be the scope the condition selects.
    fake.acl_hidden = 1
    r = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "x"})
    assert r["error"] == "COUNT_MISMATCH"


# --- Gate 5: values ----------------------------------------------------------


def test_system_fields_and_unknown_columns_are_refused(fake, config, auth):
    assert (
        preview(config, auth, table="x_myapp_order", query="state=1", set={"sys_updated_on": "x"})[
            "error"
        ]
        == "SYSTEM_FIELD"
    )
    assert (
        preview(config, auth, table="x_myapp_order", query="state=1", set={"regoin": "x"})["error"]
        == "UNKNOWN_COLUMN"
    )


def test_a_choice_label_resolves_and_an_unknown_value_is_refused(fake, config, auth):
    ok = preview(config, auth, table="x_myapp_order", query="state=1", set={"state": "Closed"})
    assert ok["sample"][0]["after"] == {"state": "2"}
    assert (
        preview(config, auth, table="x_myapp_order", query="state=1", set={"state": "Nope"})[
            "error"
        ]
        == "UNKNOWN_CHOICE"
    )


def test_references_must_be_existing_sys_ids(fake, config, auth):
    assert (
        preview(config, auth, table="x_myapp_order", query="state=1", set={"owner": "alice"})[
            "error"
        ]
        == "REFERENCE_NOT_SYS_ID"
    )
    missing = "aaaa1111bbbb2222cccc3333dddd9999"
    assert (
        preview(config, auth, table="x_myapp_order", query="state=1", set={"owner": missing})[
            "error"
        ]
        == "REFERENCE_NOT_FOUND"
    )
    assert (
        preview(config, auth, table="x_myapp_order", query="state=1", set={"owner": USER})[
            "success"
        ]
        is True
    )


def test_booleans_are_compared_as_the_server_stores_them(fake, config, auth):
    r = preview(config, auth, table="x_myapp_order", query="state=1", set={"active": True})
    assert r["will_change"] == 0 and r["already_at_value"] == 2


# --- Preview is read-only; apply writes exactly the preview -------------------


def test_preview_never_writes_and_reports_side_effects(fake, config, auth):
    r = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "north"})
    assert r["dry_run"] is True and r["will_change"] == 2
    assert r["changes_by_field"] == {"region": {"east -> north": 1, "west -> north": 1}}
    assert r["side_effects"]["business_rules"] == 2
    assert fake.patches == []


def test_apply_with_a_wrong_token_or_count_writes_nothing(fake, config, auth):
    p = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "north"})
    bad_token = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="state=1",
        set={"region": "north"},
        preview_token="0" * 16,
        confirm_count=2,
    )
    bad_count = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="state=1",
        set={"region": "north"},
        preview_token=p["preview_token"],
        confirm_count=3,
    )
    assert bad_token["error"] == bad_count["error"] == "PREVIEW_STALE"
    assert fake.patches == []


def test_apply_refuses_when_a_row_changed_after_the_preview(fake, config, auth):
    p = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "north"})
    fake.tables["x_myapp_order"][1]["region"] = "south"  # someone else, in between
    r = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="state=1",
        set={"region": "north"},
        preview_token=p["preview_token"],
        confirm_count=2,
    )
    assert r["error"] == "PREVIEW_STALE"
    assert fake.patches == []


def test_apply_snapshots_first_then_writes_and_reports_server_rewrites(
    fake, config, auth, tmp_path
):
    seen_snapshot_before_patch = []
    original = fake.make_request

    def spy(method, url, **kw):
        seen_snapshot_before_patch.append(any((tmp_path / "data_update").rglob("*.json")))
        return original(method, url, **kw)

    auth.make_request.side_effect = spy
    fake.rewrite = {"region": "north-adjusted"}
    p = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "north"})
    r = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="state=1",
        set={"region": "north"},
        preview_token=p["preview_token"],
        confirm_count=2,
    )
    assert r["success"] is True and r["updated"] == 2
    assert all(seen_snapshot_before_patch)
    assert sorted(x["sys_id"] for x in fake.patches) == [A, B]
    assert r["server_changed_count"] == 2
    snap = json.loads(next((tmp_path / "data_update").rglob("*.json")).read_text())
    assert snap["status"] == "complete"
    assert {row["sys_id"]: row["before"] for row in snap["rows"]} == {
        A: {"region": "east"},
        B: {"region": "west"},
    }


def test_apply_stops_at_the_first_failed_row(fake, config, auth):
    fake.fail_patch_on = A
    p = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "north"})
    r = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="state=1",
        set={"region": "north"},
        preview_token=p["preview_token"],
        confirm_count=2,
    )
    assert r["success"] is False and r["error"] == "STOPPED_AT_FAILURE"
    assert r["updated"] == 0 and r["not_attempted"] == 1
    assert len(fake.patches) == 1


def test_no_snapshot_means_no_write(fake, config, auth, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(svc, "atomic_write_text", boom)
    p = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "north"})
    r = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="state=1",
        set={"region": "north"},
        preview_token=p["preview_token"],
        confirm_count=2,
    )
    assert r["error"] == "SNAPSHOT_FAILED"
    assert fake.patches == []


# --- Rows mode ---------------------------------------------------------------


def test_rows_mode_refuses_unknown_and_duplicate_sys_ids(fake, config, auth):
    ghost = "aaaa1111bbbb2222cccc3333dddd7777"
    assert (
        preview(config, auth, table="x_myapp_order", rows=[{"sys_id": ghost, "region": "x"}])[
            "error"
        ]
        == "ROWS_NOT_FOUND"
    )
    assert (
        preview(
            config,
            auth,
            table="x_myapp_order",
            rows=[{"sys_id": A, "region": "x"}, {"sys_id": A, "region": "y"}],
        )["error"]
        == "DUPLICATE_ROW"
    )


def test_rows_mode_previews_per_row_values(fake, config, auth):
    r = preview(
        config,
        auth,
        table="x_myapp_order",
        rows=[{"sys_id": A, "region": "n1"}, {"sys_id": C, "region": "n3"}],
    )
    assert r["will_change"] == 2
    assert {s["sys_id"]: s["after"]["region"] for s in r["sample"]} == {A: "n1", C: "n3"}


# --- Revert --------------------------------------------------------------------


def test_revert_restores_only_rows_nobody_changed_since(fake, config, auth):
    p = preview(config, auth, table="x_myapp_order", query="state=1", set={"region": "north"})
    done = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="state=1",
        set={"region": "north"},
        preview_token=p["preview_token"],
        confirm_count=2,
    )
    fake.tables["x_myapp_order"][1]["region"] = "edited-by-bob"
    fake.patches.clear()

    rp = run(config, auth, action="preview_revert", snapshot=done["snapshot"])
    assert rp["will_change"] == 1 and rp["changed_since_count"] == 1
    assert fake.patches == []
    r = run(
        config,
        auth,
        action="revert",
        snapshot=done["snapshot"],
        preview_token=rp["preview_token"],
        confirm_count=1,
    )
    assert r["success"] is True and r["not_reverted_changed_since"] == 1
    assert fake.patches == [{"sys_id": A, "json": {"region": "east"}}]
    assert fake.tables["x_myapp_order"][1]["region"] == "edited-by-bob"


def test_a_snapshot_from_another_instance_is_refused(fake, config, auth, tmp_path):
    d = tmp_path / "data_update" / "test.service-now.com"
    d.mkdir(parents=True)
    (d / "s1.json").write_text(
        json.dumps(
            {"instance": "https://other.service-now.com", "table": "x_myapp_order", "rows": []}
        )
    )
    assert (
        run(config, auth, action="preview_revert", snapshot="s1")["error"]
        == "SNAPSHOT_OTHER_INSTANCE"
    )


# --- Classification and parameter gates ----------------------------------------


def test_only_preview_actions_are_reads():
    for a in ("preview", "list_snapshots", "preview_revert"):
        assert _is_read_only("manage_data_update", {"action": a})
    for a in ("apply", "revert"):
        assert not _is_read_only("manage_data_update", {"action": a})


def test_apply_without_the_preview_token_is_rejected_at_the_schema():
    with pytest.raises(ValueError, match="preview_token"):
        ManageDataUpdateParams(
            action="apply", table="x_myapp_order", query="state=1", set={"region": "x"}
        )


# --- what the server changed on its own -------------------------------------


def _preview_apply(config, auth, **kw):
    p = run(config, auth, action="preview", **kw)
    return run(
        config,
        auth,
        action="apply",
        preview_token=p["preview_token"],
        confirm_count=p["will_change"],
        **kw,
    )


def test_a_field_a_business_rule_changed_is_reported_and_snapshotted(fake, config, auth):
    fake.derive = lambda row: row.update(region="north" if row["state"] == "2" else "east")
    out = _preview_apply(
        config, auth, table="x_myapp_order", query="active=true", set={"state": "2"}
    )
    assert out["success"] and out["also_changed_count"] == 2
    assert out["also_changed_by_field"] == {"region": {"east -> north": 1, "west -> north": 1}}
    snap = json.loads(svc.snapshot_path(config.instance_url, out["snapshot"]).read_text())
    assert {r["sys_id"]: r["side"]["region"]["before"] for r in snap["rows"]} == {
        A: "east",
        B: "west",
    }


def test_nothing_else_changed_reports_nothing(fake, config, auth):
    out = _preview_apply(
        config, auth, table="x_myapp_order", query="active=true", set={"state": "2"}
    )
    assert out["success"] and "also_changed" not in out


def test_revert_says_which_side_change_did_not_come_back(fake, config, auth):
    # the rule sets region on the way in but never resets it
    fake.derive = lambda row: row.update(region="north") if row["state"] == "2" else None
    out = _preview_apply(
        config, auth, table="x_myapp_order", query="active=true", set={"state": "2"}
    )
    pr = run(config, auth, action="preview_revert", snapshot=out["snapshot"])
    assert pr["side_fields"] == ["region"]
    rv = run(
        config,
        auth,
        action="revert",
        snapshot=out["snapshot"],
        preview_token=pr["preview_token"],
        confirm_count=pr["will_change"],
    )
    assert rv["success"] and rv["side_not_restored_count"] == 2
    assert rv["side_not_restored"][0]["fields"]["region"]["now"] == "north"


def test_a_side_change_that_comes_back_is_not_reported_as_lost(fake, config, auth):
    fake.derive = lambda row: row.update(region="north" if row["state"] == "2" else "east")
    fake.tables["x_myapp_order"][1]["region"] = "east"
    out = _preview_apply(
        config, auth, table="x_myapp_order", query="active=true", set={"state": "2"}
    )
    pr = run(config, auth, action="preview_revert", snapshot=out["snapshot"])
    rv = run(
        config,
        auth,
        action="revert",
        snapshot=out["snapshot"],
        preview_token=pr["preview_token"],
        confirm_count=pr["will_change"],
    )
    assert rv["success"] and "side_not_restored" not in rv
    assert "also_changed" not in rv  # region coming back is the revert working, not news


def test_rows_unreadable_in_full_means_no_write(fake, config, auth, monkeypatch):
    p = run(
        config,
        auth,
        action="preview",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
    )
    real = fake.query_page

    def broken(config, auth, *, fields, **kw):
        if fields == "":
            raise RuntimeError("read timed out")
        return real(config, auth, fields=fields, **kw)

    monkeypatch.setattr(svc, "sn_query_page", broken)
    out = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
        preview_token=p["preview_token"],
        confirm_count=p["will_change"],
    )
    assert out["error"] == "ROWS_UNREADABLE" and fake.patches == []


def test_a_row_gone_from_the_full_read_means_no_write(fake, config, auth, monkeypatch):
    p = run(
        config,
        auth,
        action="preview",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
    )
    real = fake.query_page

    def racing(config, auth, *, fields, **kw):
        rows, total = real(config, auth, fields=fields, **kw)
        return ([r for r in rows if r["sys_id"] != B] if fields == "" else rows), total

    monkeypatch.setattr(svc, "sn_query_page", racing)
    out = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
        preview_token=p["preview_token"],
        confirm_count=p["will_change"],
    )
    assert out["error"] == "PREVIEW_STALE" and out["missing"] == [B] and fake.patches == []


# --- what reaches the caller is bounded, whatever the rows hold ----------------


def _big_plan(n, chars, fields=8):
    return [
        {
            "sys_id": f"aaaa{i:028x}",
            "label": f"ORD{i}",
            "before": {f"u_f{k}": "a" * chars + str(i) for k in range(fields)},
            "after": {f"u_f{k}": "b" * chars + str(i) for k in range(fields)},
        }
        for i in range(n)
    ]


def test_a_bulk_preview_of_long_values_fits_the_budget_and_keeps_its_counts():
    plan = _big_plan(1000, 4000)
    view = svc.fit(
        svc.preview_view(
            {"plan": plan, "table": "x", "matched": 1000, "unchanged": 0, "token": "t"}
        )
    )
    assert len(json.dumps(view, ensure_ascii=False)) <= svc._VIEW_BUDGET
    assert view["will_change"] == 1000 and view["matched"] == 1000
    assert view["sample"] and "trimmed_note" in view


def test_two_long_values_sharing_a_prefix_stay_distinct_when_clipped():
    a, b = "x" * 500 + "1", "x" * 500 + "2"
    assert svc._clip(a) != svc._clip(b)
    assert len(svc._clip(a)) < 120


def test_a_small_preview_is_not_trimmed(fake, config, auth):
    out = run(
        config,
        auth,
        action="preview",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
    )
    assert "trimmed_note" not in out and len(out["sample"]) == 2


def test_a_row_with_many_side_fields_shows_a_bounded_number():
    side = {f"u_s{k}": {"before": "1", "after": "2"} for k in range(40)}
    shown = svc.brief({"fields": side})["fields"]
    assert len(shown) == svc._VIEW_FIELDS + 1 and shown["…"] == "+30 more field(s)"


def _rows_csv(path):
    import csv

    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def test_a_shortened_preview_hands_the_user_every_row_as_a_file(fake, config, auth, monkeypatch):
    monkeypatch.setattr(svc, "_VIEW_BUDGET", 600)
    out = run(
        config,
        auth,
        action="preview",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
    )
    assert "trimmed_note" in out and out["will_change"] == 2
    lines = _rows_csv(out["full_list"])
    assert out["full_list_lines"] == 2 == len(lines)
    assert {(r["sys_id"], r["field"], r["before"], r["after"]) for r in lines} == {
        (A, "state", "1", "2"),
        (B, "state", "1", "2"),
    }


def test_a_shortened_apply_lists_what_the_server_changed_too(fake, config, auth, monkeypatch):
    fake.derive = lambda row: row.update(region="north")
    p = run(
        config,
        auth,
        action="preview",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
    )
    monkeypatch.setattr(svc, "_VIEW_BUDGET", 600)
    out = run(
        config,
        auth,
        action="apply",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
        preview_token=p["preview_token"],
        confirm_count=p["will_change"],
    )
    lines = _rows_csv(out["full_list"])
    assert {(r["sys_id"], r["field"], r["kind"], r["applied"]) for r in lines} == {
        (A, "state", "set", "yes"),
        (B, "state", "set", "yes"),
        (A, "region", "server", "yes"),
        (B, "region", "server", "yes"),
    }


def test_a_response_that_fits_writes_no_file(fake, config, auth):
    out = run(
        config,
        auth,
        action="preview",
        table="x_myapp_order",
        query="active=true",
        set={"state": "2"},
    )
    assert "full_list" not in out
