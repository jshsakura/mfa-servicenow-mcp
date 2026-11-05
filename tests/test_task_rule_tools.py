"""manage_task_rule: no scripts, OOTB refused, party names resolved or refused, writes re-read."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools import task_rule_tools as tr
from servicenow_mcp.tools.task_rule_tools import (
    ManageTaskRuleParams,
    manage_task_rule,
    readable_condition,
)

RULE = "aaaa1111bbbb2222cccc3333dddd4444"
OOTB = "aaaa5555bbbb6666cccc7777dddd8888"
GRP = "bbbb1111cccc2222dddd3333eeee4444"
GRP2 = "bbbb5555cccc6666dddd7777eeee8888"
USR = "cccc1111dddd2222eeee3333ffff4444"


class Fake:
    def __init__(self):
        self.store = {
            "sysrule_assignment": {
                RULE: {
                    "sys_id": RULE,
                    "name": "My Rule",
                    "table": "incident",
                    "condition": "category=hw^EQ",
                    "group": GRP,
                    "active": "true",
                    "order": "100",
                    "script": "",
                    "sys_package": "",
                },
                OOTB: {
                    "sys_id": OOTB,
                    "name": "Shipped Rule",
                    "table": "incident",
                    "condition": "",
                    "group": GRP,
                    "active": "true",
                    "order": "100",
                    "script": "gs.info(1)",
                    "sys_package": "pkg1",
                    "sys_package_label": "Assignment Rules",
                },
            },
            "sysrule_approvals": {},
            "sys_user_group": {
                GRP: {"sys_id": GRP, "name": "Group One"},
                GRP2: {"sys_id": GRP2, "name": "Group Two"},
            },
            "sys_user": {USR: {"sys_id": USR, "user_name": "alice", "name": "Alice A"}},
            "sys_db_object": {"x": {"name": "incident"}, "y": {"name": "sc_request"}},
        }
        self.writes = []
        self.drop = set()

    def _wrap(self, row):
        out = {}
        for k, v in row.items():
            if k.endswith("_label"):
                continue
            label = row.get(f"{k}_label", v)
            if k == "group" and v in self.store["sys_user_group"]:
                label = self.store["sys_user_group"][v]["name"]
            out[k] = {"value": v, "display_value": label}
        return out

    def query(self, config, auth, *, table, query, fields, **kw):
        rows = list(self.store.get(table, {}).values())
        first = query.split("^")[0]
        if first.startswith("sys_id="):
            rows = [r for r in rows if r["sys_id"] == first[7:]]
        elif first.startswith("name="):
            rows = [r for r in rows if r.get("name") == first[5:]]
        elif first.startswith("user_name="):
            rows = [r for r in rows if r.get("user_name") == first[10:]]
        elif first.startswith("nameLIKE"):
            rows = [r for r in rows if first[8:].lower() in r.get("name", "").lower()]
        return [self._wrap(r) for r in rows], len(rows)

    def request(self, method, url, json=None, **kw):
        resp = MagicMock()
        table = url.split("/table/")[1].split("/")[0]
        if method == "POST":
            sid = "dddd1111eeee2222ffff3333aaaa4444"
            self.store[table][sid] = {"sys_id": sid, "script": "", "sys_package": "", **json}
            self.writes.append((method, table, json))
            resp.json.return_value = {"result": {"sys_id": sid}}
        else:
            sid = url.rsplit("/", 1)[1]
            self.writes.append((method, table, sid, json))
            self.store[table][sid].update({k: v for k, v in json.items() if k not in self.drop})
            resp.json.return_value = {"result": {}}
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
    state = {"missing": []}

    def writable(config, auth, table, sys_id):
        if sys_id == OOTB:
            return {"success": False, "error": "OOTB_PACKAGE", "message": "OOTB"}
        return None

    def choice(config, auth, *, table, element, requested, **kw):
        for v, lab in (("approved", "Approved"), ("requested", "Requested")):
            if requested in (v, lab):
                return v, None
        return None, {"success": False, "error": "UNKNOWN_CHOICE", "message": "no"}

    with (
        patch.object(tr, "sn_query_page", side_effect=fake.query),
        patch.object(tr, "_writable_target", side_effect=writable),
        patch.object(tr, "resolve_choice", side_effect=choice),
        patch.object(tr, "unknown_query_fields", side_effect=lambda *a: list(state["missing"])),
        patch.object(tr, "table_columns", return_value={"category", "state"}),
    ):
        yield fake, config, auth, state


def run(env, **kw):
    fake, config, auth, _ = env
    kw.setdefault("kind", "assignment")
    return manage_task_rule(config, auth, ManageTaskRuleParams(**kw))


def test_validation():
    with pytest.raises(ValidationError, match="name and table"):
        ManageTaskRuleParams(action="create", kind="assignment", group="g")
    with pytest.raises(ValidationError, match="group or a user"):
        ManageTaskRuleParams(action="create", kind="assignment", name="n", table="incident")
    with pytest.raises(ValidationError, match="only apply to kind='approval'"):
        ManageTaskRuleParams(action="update", kind="assignment", rule_id="x", set_state="approved")
    with pytest.raises(ValidationError, match="rule_id"):
        ManageTaskRuleParams(action="get", kind="approval")
    with pytest.raises(ValidationError, match="at least one"):
        ManageTaskRuleParams(action="update", kind="approval", rule_id="x")
    with pytest.raises(ValidationError):
        ManageTaskRuleParams(action="delete", kind="approval", rule_id="x")
    assert "script" not in ManageTaskRuleParams.model_fields


def test_readable_condition():
    assert readable_condition("") == "(always)"
    assert readable_condition("a=1^b=2^ORc=3^EQ") == "a=1 AND b=2 OR c=3"


def test_list_lean_with_editable_flag(env):
    out = run(env, action="list")
    rules = {r["name"]: r for r in out["rules"]}
    assert rules["My Rule"]["editable"] is True and rules["My Rule"]["group"] == "Group One"
    assert rules["Shipped Rule"]["editable"] is False and rules["Shipped Rule"]["has_script"]
    assert "script" not in rules["Shipped Rule"]


def test_list_empty_is_not_a_negative(env):
    out = run(env, action="list", kind="approval")
    assert out["success"] and out["rules"] == [] and "cannot read" in out["note"]


def test_get_by_name_and_script_withheld(env):
    out = run(env, action="get", rule_id="Shipped Rule")
    assert out["rule"]["has_script"] and "script" not in out
    out = run(env, action="get", rule_id="Shipped Rule", full=True)
    assert out["script"] == "gs.info(1)"


def test_get_absent_wording(env):
    out = run(env, action="get", rule_id="Nope")
    assert out["success"] is False and "hidden from this account by ACL" in out["message"]


def test_get_ambiguous_name_lists_candidates(env):
    env[0].store["sysrule_assignment"]["x"] = {"sys_id": "x" * 32, "name": "My Rule"}
    out = run(env, action="get", rule_id="My Rule")
    assert out["success"] is False and len(out["candidates"]) == 2


def test_create_resolves_names_and_rereads(env):
    out = run(
        env,
        action="create",
        name="N",
        table="incident",
        condition="category=hw",
        group="Group Two",
        user="alice",
    )
    assert out["success"] and out["applied"] and out["verified"]
    body = env[0].writes[0][2]
    assert body["group"] == GRP2 and body["user"] == USR
    assert "script" not in body


def test_create_dry_run_writes_nothing(env):
    out = run(env, action="create", name="N", table="incident", group="Group One", dry_run=True)
    assert out["dry_run"] and out["would_write"]["group"] == GRP and not env[0].writes


def test_group_zero_or_many_matches_refuse(env):
    out = run(env, action="create", name="N", table="incident", group="Missing")
    assert out["success"] is False and not env[0].writes
    env[0].store["sys_user_group"]["z"] = {"sys_id": "z" * 32, "name": "Group One"}
    out = run(env, action="create", name="N", table="incident", group="Group One")
    assert out["success"] is False and len(out["candidates"]) == 2 and not env[0].writes


def test_unknown_table_and_condition_field_refuse(env):
    out = run(env, action="create", name="N", table="nosuch", group="Group One")
    assert out["field"] == "table" and not env[0].writes
    env[3]["missing"] = ["categoryy"]
    out = run(
        env,
        action="create",
        name="N",
        table="incident",
        condition="categoryy=hw",
        group="Group One",
    )
    assert out["field"] == "condition" and "categoryy" in out["did_you_mean"]
    assert not env[0].writes


def test_condition_unverifiable_refuses(env):
    with patch.object(tr, "unknown_query_fields", return_value=None):
        out = run(
            env, action="create", name="N", table="incident", condition="a=1", group="Group One"
        )
    assert out["success"] is False and "cannot be checked" in out["message"]


def test_update_ootb_refused(env):
    out = run(env, action="update", rule_id=OOTB, active=False)
    assert out["error"] == "OOTB_PACKAGE" and not env[0].writes


def test_update_applies_and_clears(env):
    out = run(env, action="update", rule_id=RULE, active=False, user="", order=50)
    assert out["applied"] and out["rule"]["active"] is False
    assert env[0].writes[0][3] == {"active": "false", "user": "", "order": "50"}


def test_update_reports_not_applied(env):
    env[0].drop = {"order"}
    out = run(env, action="update", rule_id=RULE, order=7)
    assert out["success"] is False and out["applied"] is False and "order" in out["not_applied"]


def test_update_dry_run_diffs(env):
    out = run(env, action="update", rule_id=RULE, active=True, order=5, dry_run=True)
    assert out["proposed_changes"] == {"order": {"from": "100", "to": "5"}}
    assert out["no_op_fields"] == ["active"] and not env[0].writes


def test_update_checks_existing_condition_against_new_table(env):
    env[3]["missing"] = ["category"]
    out = run(env, action="update", rule_id=RULE, table="sc_request")
    assert out["field"] == "condition" and not env[0].writes


def test_approval_state_resolved_and_warned(env):
    out = run(
        env, action="create", kind="approval", name="A", table="sc_request", group="Group One"
    )
    assert out["applied"] and "never moves" in out["warning"]
    out = run(
        env,
        action="create",
        kind="approval",
        name="B",
        table="sc_request",
        set_state="Approved",
        optional_group="Group Two",
    )
    assert env[0].writes[-1][2]["set_state"] == "approved" and "warning" not in out
    out = run(
        env, action="create", kind="approval", name="C", table="sc_request", set_state="Bogus"
    )
    assert out["success"] is False
