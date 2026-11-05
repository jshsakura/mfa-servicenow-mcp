"""manage_incident link/hold fields: resolved, gated before the write, re-read per field."""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools import incident_tools as it
from servicenow_mcp.tools.incident_tools import ManageIncidentParams, manage_incident

INC = "aaaa1111bbbb2222cccc3333dddd4444"
PRB = "bbbb1111cccc2222dddd3333eeee4444"
CHG = "cccc1111dddd2222eeee3333ffff4444"
CHG2 = "cccc5555dddd6666eeee7777ffff8888"
PARENT = "dddd1111eeee2222ffff3333aaaa4444"


class Fake:
    def __init__(self):
        self.store = {
            "incident": {
                INC: {"sys_id": INC, "number": "INC0001"},
                PARENT: {"sys_id": PARENT, "number": "INC0002"},
            },
            "problem": {PRB: {"sys_id": PRB, "number": "PRB0001"}},
            "change_request": {
                CHG: {"sys_id": CHG, "number": "CHG0001"},
                CHG2: {"sys_id": CHG2, "number": "CHG0002"},
            },
        }
        self.patches, self.posts = [], []
        self.revert = set()

    def query(self, config, auth, *, table, query, fields, **kw):
        rows = list(self.store.get(table, {}).values())
        if query.startswith("sys_id="):
            rows = [r for r in rows if r["sys_id"] == query[7:]]
        elif query.startswith("number="):
            rows = [r for r in rows if r["number"] == query[7:]]
        return [
            {k: {"value": v, "display_value": f"disp:{v}"} for k, v in r.items()} for r in rows
        ], len(rows)

    def request(self, method, url, json=None, **kw):
        resp = MagicMock()
        if method == "PATCH":
            _, table, sid = url.rsplit("/", 2)
            self.patches.append((table, sid, json))
            for k, v in json.items():
                if k not in self.revert:
                    self.store[table][sid][k] = v
            resp.json.return_value = {"result": self.store[table][sid]}
        else:
            self.posts.append(json)
            new = {"sys_id": INC, "number": "INC0009", **json}
            self.store["incident"][INC].update(new)
            resp.json.return_value = {"result": new}
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
    labels = {
        "state": {"3": "On Hold", "2": "In Progress"},
        "hold_reason": {"1": "Awaiting Caller", "4": "Awaiting Vendor"},
    }

    def choices(config, auth, *, table, data, elements):
        for el in elements:
            if el in data and el in labels:
                for v, lab in labels[el].items():
                    if str(data[el]) in (v, lab):
                        data[el] = v
                        break
                else:
                    return {"success": False, "error": "UNKNOWN_CHOICE", "message": "no"}
        return None

    with (
        patch.object(it, "sn_query_page", side_effect=fake.query),
        patch("servicenow_mcp.tools.problem_tools.sn_query_page", side_effect=fake.query),
        patch.object(it, "resolve_payload_choices", side_effect=choices),
        patch.object(it, "build_update_preview", side_effect=lambda *a, **k: {"dry_run": True}),
    ):
        yield fake, config, auth


def run(env, **kw):
    _, config, auth = env
    return manage_incident(config, auth, ManageIncidentParams(**kw))


def test_update_resolves_numbers_and_reports_applied(env):
    fake = env[0]
    out = run(
        env,
        action="update",
        incident_id=INC,
        parent_incident="INC0002",
        problem_id="PRB0001",
        rfc="CHG0001",
        caused_by="CHG0002",
    )
    assert fake.patches[0][2] == {
        "parent_incident": PARENT,
        "problem_id": PRB,
        "rfc": CHG,
        "caused_by": CHG2,
    }
    assert out["success"] and out["verified"]
    assert out["applied"] == dict.fromkeys(fake.patches[0][2], True)


def test_update_by_number_of_incident(env):
    out = run(env, action="update", incident_id="INC0001", problem_id=PRB)
    assert out["success"] and env[0].patches[0][1] == INC


def test_unreadable_number_writes_nothing(env):
    out = run(env, action="update", incident_id=INC, rfc="CHG4040")
    assert out["success"] is False and out["determined"] is False
    assert "not readable" in out["message"] and not env[0].patches


def test_wrong_prefix_refused_before_any_read(env):
    out = run(env, action="update", incident_id=INC, caused_by="INC0002")
    assert out["success"] is False and "CHG number" in out["message"]
    assert not env[0].patches


def test_reverted_field_is_not_applied(env):
    env[0].revert.add("problem_id")
    out = run(env, action="update", incident_id=INC, problem_id=PRB, rfc=CHG)
    assert out["success"] is False
    assert out["applied"] == {"problem_id": False, "rfc": True}
    assert out["not_applied"]["problem_id"]["requested"] == PRB


def test_on_hold_without_reason_refused(env):
    out = run(env, action="update", incident_id=INC, state="On Hold")
    assert out["success"] is False and out["field"] == "hold_reason"
    assert not env[0].patches


def test_on_hold_with_reason_label(env):
    out = run(env, action="update", incident_id=INC, state="On Hold", hold_reason="Awaiting Vendor")
    assert env[0].patches[0][2] == {"state": "3", "hold_reason": "4"}
    assert out["success"] and out["applied"] == {"state": True, "hold_reason": True}


def test_unknown_hold_reason_refused(env):
    out = run(env, action="update", incident_id=INC, state="3", hold_reason="Bored")
    assert out["success"] is False and not env[0].patches


def test_create_with_links(env):
    out = run(env, action="create", short_description="s", parent_incident="INC0002", rfc=CHG)
    assert env[0].posts[0]["parent_incident"] == PARENT
    assert out["success"] and out["applied"]["rfc"] is True


def test_dry_run_writes_nothing(env):
    out = run(env, action="update", incident_id=INC, problem_id="PRB0001", dry_run=True)
    assert out["dry_run"] and not env[0].patches
    out = run(env, action="create", short_description="s", rfc="CHG0001", dry_run=True)
    assert out["would_write"]["rfc"] == CHG and not env[0].posts


def test_work_notes_listed_unverifiable(env):
    out = run(env, action="update", incident_id=INC, problem_id=PRB, work_notes="n")
    assert out["unverifiable"] == ["work_notes"] and out["applied"] == {"problem_id": True}


def test_plain_update_is_verified_too(env):
    # No link fields: same write path, same re-read proof — no second, unverified shape.
    with patch("servicenow_mcp.tools.incident_tools._write") as write:
        write.return_value = {"success": True, "verified": True}
        manage_incident(
            env[1], env[2], ManageIncidentParams(action="update", incident_id=INC, impact="1")
        )
    write.assert_called_once()
