"""manage_problem: every write is re-read; unreadable numbers are never 'absent'."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools import problem_tools as pt
from servicenow_mcp.tools.problem_tools import ManageProblemParams, manage_problem

PRB = "aaaa1111bbbb2222cccc3333dddd4444"
PRB2 = "aaaa5555bbbb6666cccc7777dddd8888"
INC1 = "bbbb1111cccc2222dddd3333eeee4444"
INC2 = "bbbb5555cccc6666dddd7777eeee8888"
INC3 = "bbbb9999cccc0000dddd1111eeee2222"
CHG = "cccc1111dddd2222eeee3333ffff4444"
PTASK = "eeee1111ffff2222aaaa3333bbbb4444"


class Fake:
    """In-memory instance: sn_query_page + make_request over a dict store."""

    def __init__(self):
        self.store = {
            "problem": {
                PRB: {"sys_id": PRB, "number": "PRB0001", "state": "101", "workaround": "abc"},
                PRB2: {"sys_id": PRB2, "number": "PRB0002", "state": "101"},
            },
            "incident": {
                INC1: {"sys_id": INC1, "number": "INC0001", "problem_id": ""},
                INC2: {"sys_id": INC2, "number": "INC0002", "problem_id": PRB},
                INC3: {"sys_id": INC3, "number": "INC0003", "problem_id": PRB2},
            },
            "change_request": {CHG: {"sys_id": CHG, "number": "CHG0001"}},
        }
        self.patches = []
        self.posts = []
        self.revert_fields = set()

    def query(self, config, auth, *, table, query, fields, **kw):
        rows = list(self.store.get(table, {}).values())
        if query.startswith("sys_id="):
            rows = [r for r in rows if r["sys_id"] == query[7:]]
        elif query.startswith("numberIN"):
            nums = query[8:].split(",")
            rows = [r for r in rows if r["number"] in nums]
        elif query.startswith("number="):
            rows = [r for r in rows if r["number"] == query[7:]]
        return [
            {k: {"value": v, "display_value": f"disp:{v}" if v else ""} for k, v in r.items()}
            for r in rows
        ], len(rows)

    def request(self, method, url, json=None, **kw):
        resp = MagicMock()
        if method == "PATCH":
            _, table, sid = url.rsplit("/", 2)
            self.patches.append((table, sid, json))
            for k, v in json.items():
                if k not in self.revert_fields:
                    self.store[table][sid][k] = v
            resp.json.return_value = {"result": self.store[table][sid]}
        elif url.endswith("/problem_task"):
            self.posts.append(json)
            new = {"sys_id": PTASK, "number": "PTASK0001", **json}
            self.store.setdefault("problem_task", {})[PTASK] = new
            resp.json.return_value = {"result": new}
        else:
            self.posts.append(json)
            resp.json.return_value = {"result": {"sys_id": PRB, "number": "PRB0009"}}
        return resp


@pytest.fixture
def env():
    fake = Fake()
    config = MagicMock()
    config.api_url = "https://test.service-now.com/api/now"
    config.timeout = 30
    auth = MagicMock()
    auth.make_request.side_effect = fake.request
    auth.get_headers.return_value = {}

    def choice(config, auth, *, table, element, requested, **kw):
        labels = {"101": "New", "103": "Root Cause Analysis", "106": "Resolved", "rca": "RCA type"}
        for v, lab in labels.items():
            if requested in (v, lab):
                return v, None
        return None, {"success": False, "error": "UNKNOWN_CHOICE", "message": "no"}

    with (
        patch.object(pt, "sn_query_page", side_effect=fake.query),
        patch.object(pt, "resolve_choice", side_effect=choice),
        patch.object(pt, "resolve_payload_choices", return_value=None),
        patch.object(pt, "build_update_preview", side_effect=lambda *a, **k: {"dry_run": True}),
    ):
        yield fake, config, auth


def run(env, **kw):
    fake, config, auth = env
    return manage_problem(config, auth, ManageProblemParams(**kw))


def test_validation():
    with pytest.raises(ValidationError, match="short_description"):
        ManageProblemParams(action="create")
    with pytest.raises(ValidationError, match="problem_id"):
        ManageProblemParams(action="update", short_description="x")
    with pytest.raises(ValidationError, match="at least one"):
        ManageProblemParams(action="update", problem_id="PRB0001")
    with pytest.raises(ValidationError, match="incidents"):
        ManageProblemParams(action="link_incidents", problem_id="PRB0001")


def test_get_compact_and_full(env):
    out = run(env, action="get", problem_id="PRB0001")
    assert out["number"] == "PRB0001" and out["workaround_length"] == 3
    assert "workaround" not in out
    assert run(env, action="get", problem_id=PRB, full=True)["workaround"] == "abc"


def test_get_not_readable(env):
    out = run(env, action="get", problem_id="PRB9999")
    assert out["success"] is False and out["determined"] is False
    assert "not readable" in out["message"]


def test_create_resolves_inc_number(env):
    out = run(
        env, action="create", short_description="s", first_reported_by_task="INC0001", impact="1"
    )
    assert out["number"] == "PRB0009"
    assert env[0].posts[0]["first_reported_by_task"] == INC1


def test_create_unreadable_task_writes_nothing(env):
    out = run(env, action="create", short_description="s", first_reported_by_task="INC4040")
    assert out["success"] is False and not env[0].posts


def test_create_dry_run(env):
    out = run(env, action="create", short_description="s", dry_run=True)
    assert out["dry_run"] and not env[0].posts


def test_update_verified_and_not_applied(env):
    out = run(env, action="update", problem_id="PRB0001", cause_notes="why")
    assert out["applied"] is True and env[0].patches[0][2] == {"cause_notes": "why"}
    env[0].revert_fields.add("fix_notes")
    out = run(env, action="update", problem_id="PRB0001", fix_notes="x")
    assert out["success"] is False and "fix_notes" in out["not_applied"]


def test_update_dry_run_no_write(env):
    out = run(env, action="update", problem_id="PRB0001", cause_notes="why", dry_run=True)
    assert out["dry_run"] and not env[0].patches


def test_update_duplicate_of_resolves(env):
    run(env, action="update", problem_id="PRB0001", duplicate_of="PRB0002")
    assert env[0].patches[0][2] == {"duplicate_of": PRB2}


def test_update_number_not_readable(env):
    out = run(env, action="update", problem_id="PRB7777", cause_notes="x")
    assert out["success"] is False and not env[0].patches


def test_link_incidents_statuses(env):
    out = run(
        env,
        action="link_incidents",
        problem_id="PRB0001",
        incidents=["INC0001", "INC0002", "INC0003", "INC0404"],
    )
    st = {r["number"]: r["status"] for r in out["incidents"]}
    assert st == {
        "INC0001": "linked",
        "INC0002": "already_linked_here",
        "INC0003": "linked_elsewhere",
        "INC0404": "not_readable",
    }
    assert out["success"] is False
    assert [p[1] for p in env[0].patches] == [INC1]
    assert env[0].store["incident"][INC3]["problem_id"] == PRB2


def test_link_incidents_force_relink(env):
    out = run(
        env, action="link_incidents", problem_id="PRB0001", incidents=["INC0003"], force_relink=True
    )
    assert out["incidents"][0]["status"] == "linked"
    assert env[0].store["incident"][INC3]["problem_id"] == PRB


def test_link_incidents_reverted_is_not_applied(env):
    env[0].revert_fields.add("problem_id")
    out = run(env, action="link_incidents", problem_id="PRB0001", incidents=["INC0001"])
    assert out["incidents"][0]["status"] == "not_applied" and out["success"] is False


def test_link_incidents_dry_run(env):
    out = run(
        env, action="link_incidents", problem_id="PRB0001", incidents=["INC0001"], dry_run=True
    )
    assert out["incidents"][0]["status"] == "would_linked" and not env[0].patches


def test_unlink_incidents(env):
    out = run(
        env, action="unlink_incidents", problem_id="PRB0001", incidents=["INC0002", "INC0003"]
    )
    st = {r["number"]: r["status"] for r in out["incidents"]}
    assert st == {"INC0002": "unlinked", "INC0003": "not_linked_here"}
    assert env[0].store["incident"][INC2]["problem_id"] == ""
    assert env[0].store["incident"][INC3]["problem_id"] == PRB2


def test_link_change(env):
    out = run(env, action="link_change", problem_id="PRB0001", change="CHG0001")
    assert out["applied"] is True and env[0].patches[0][2] == {"rfc": CHG}


def test_link_change_unreadable(env):
    out = run(env, action="link_change", problem_id="PRB0001", change="CHG0404")
    assert out["success"] is False and not env[0].patches


def test_mark_known_error(env):
    out = run(env, action="mark_known_error", problem_id="PRB0001", workaround="restart")
    assert out["applied"] is True
    assert env[0].patches[0][2] == {"known_error": "true", "workaround": "restart"}


def test_set_state_applied_true(env):
    out = run(env, action="set_state", problem_id="PRB0001", state="Root Cause Analysis")
    assert out["applied"] is True and env[0].patches[0][2] == {"state": "103"}


def test_set_state_applied_false_reports_actual(env):
    env[0].revert_fields.add("state")
    out = run(env, action="set_state", problem_id="PRB0001", state="106")
    assert out["applied"] is False and out["actual_state"] == "101"
    assert "UI actions" in out["message"] and out["success"] is False


def test_set_state_unknown_label_writes_nothing(env):
    out = run(env, action="set_state", problem_id="PRB0001", state="Bogus")
    assert out["success"] is False and not env[0].patches


def test_set_state_dry_run(env):
    out = run(env, action="set_state", problem_id="PRB0001", state="106", dry_run=True)
    assert out["dry_run"] and not env[0].patches


def test_add_task_validation():
    with pytest.raises(ValidationError, match="short_description"):
        ManageProblemParams(action="add_task", problem_id="PRB0001")
    with pytest.raises(ValidationError, match="problem_id"):
        ManageProblemParams(action="add_task", short_description="x")


def test_add_task_created_and_verified(env):
    fake = env[0]
    out = run(
        env,
        action="add_task",
        problem_id="PRB0001",
        short_description="Find cause",
        description="d",
        problem_task_type="rca",
    )
    assert fake.posts[0] == {
        "problem": PRB,
        "short_description": "Find cause",
        "description": "d",
        "problem_task_type": "rca",
    }
    assert out["success"] and out["verified"] and out["applied"] is True
    assert out["number"] == "PTASK0001" and out["problem"] == PRB


def test_add_task_field_not_held_is_reported(env):
    fake = env[0]
    orig = fake.request

    def reverting(method, url, json=None, **kw):
        resp = orig(method, url, json=json, **kw)
        if method == "POST" and url.endswith("/problem_task"):
            fake.store["problem_task"][PTASK]["short_description"] = "changed by rule"
        return resp

    env[2].make_request.side_effect = reverting
    out = run(env, action="add_task", problem_id=PRB, short_description="orig")
    assert out["success"] is False and out["applied"] is False
    assert out["not_applied"]["short_description"]["requested"] == "orig"


def test_add_task_unreadable_problem_writes_nothing(env):
    out = run(env, action="add_task", problem_id="PRB9999", short_description="x")
    assert out["success"] is False and not env[0].posts


def test_add_task_unknown_type_refused(env):
    out = run(
        env, action="add_task", problem_id=PRB, short_description="x", problem_task_type="zzz"
    )
    assert out["success"] is False and not env[0].posts


def test_add_task_dry_run(env):
    out = run(env, action="add_task", problem_id=PRB, short_description="x", dry_run=True)
    assert out["dry_run"] and out["would_write"]["problem"] == PRB and not env[0].posts
