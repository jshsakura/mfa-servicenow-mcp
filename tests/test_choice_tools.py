"""manage_choice: list says where rows came from; writes are gated, verified, never deletes."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools import choice_tools as ct
from servicenow_mcp.tools.choice_tools import ManageChoiceParams, manage_choice

ANC = ["child_tbl", "parent_tbl"]


def _id(n):
    return f"aaaa{n:04d}bbbb2222cccc3333dddd4444"


class Fake:
    def __init__(self):
        self.dictionary = {
            "pri": {"name": "parent_tbl", "choice": "1", "dependent": ""},
            "cat": {"name": "child_tbl", "choice": "1", "dependent": ""},
            "sub": {"name": "child_tbl", "choice": "1", "dependent": "cat"},
            "txt": {"name": "parent_tbl", "choice": "0", "dependent": ""},
        }
        self.choices = [
            self.row(1, "parent_tbl", "pri", "1", "Critical", "1"),
            self.row(2, "parent_tbl", "pri", "2", "High", "2"),
            self.row(3, "child_tbl", "cat", "hw", "Hardware", "1"),
            self.row(4, "child_tbl", "cat", "sw", "Software", "2", inactive="true"),
            self.row(5, "child_tbl", "sub", "cpu", "CPU", "", dep="hw"),
        ]
        self.writes = []
        self.drop = set()

    @staticmethod
    def row(n, name, el, value, label, seq, dep="", inactive="false", lang="en"):
        return {
            "sys_id": _id(n),
            "name": name,
            "element": el,
            "value": value,
            "label": label,
            "sequence": seq,
            "dependent_value": dep,
            "inactive": inactive,
            "language": lang,
        }

    def query(self, config, auth, *, table, query, fields, **kw):
        if table == "sys_dictionary":
            el = query.split("^element=")[1]
            d = self.dictionary.get(el)
            return ([{**d, "element": el, "internal_type": "string"}] if d else []), None
        if table == "sys_choice" and query.startswith("sys_id="):
            return [r for r in self.choices if r["sys_id"] == query[7:]], None
        el = query.split("^element=")[1].split("^")[0]
        return [r for r in self.choices if r["element"] == el], None

    def request(self, method, url, json=None, **kw):
        resp = MagicMock()
        if method == "POST":
            row = {**json, "sys_id": _id(90 + len(self.writes))}
            self.writes.append((method, json))
            self.choices.append(row)
            resp.json.return_value = {"result": {"sys_id": row["sys_id"]}}
        else:
            sid = url.rsplit("/", 1)[1]
            self.writes.append((method, sid, json))
            for r in self.choices:
                if r["sys_id"] == sid:
                    r.update({k: v for k, v in json.items() if k not in self.drop})
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

    def resolve(config, auth, *, table, element, requested, **kw):
        if requested in ("hw", "Hardware"):
            return "hw", None
        return None, {"success": False, "error": "UNKNOWN_CHOICE", "message": "no"}

    with (
        patch.object(ct, "sn_query_page", side_effect=fake.query),
        patch.object(ct, "table_ancestry", return_value=ANC),
        patch.object(ct, "resolve_choice", side_effect=resolve),
    ):
        yield fake, config, auth


def run(env, **kw):
    fake, config, auth = env
    kw.setdefault("table", "child_tbl")
    return manage_choice(config, auth, ManageChoiceParams(**kw))


def test_validation():
    with pytest.raises(ValidationError, match="value is required"):
        ManageChoiceParams(action="set", table="t", field="f", label="x")
    with pytest.raises(ValidationError, match="label, sequence"):
        ManageChoiceParams(action="set", table="t", field="f", value="v")
    with pytest.raises(ValidationError, match="lowercase"):
        ManageChoiceParams(action="list", table="T t", field="f")
    with pytest.raises(ValidationError, match="language"):
        ManageChoiceParams(action="list", table="t", field="f", language="english")


def test_list_hides_inactive_and_names_source(env):
    out = run(env, action="list", field="cat")
    assert out["rows_from"] == "child_tbl" and not out.get("inherited")
    assert [c["value"] for c in out["choices"]] == ["hw"]
    out = run(env, action="list", field="cat", include_inactive=True)
    assert [c["value"] for c in out["choices"]] == ["hw", "sw"]


def test_list_inherited_says_where_rows_live(env):
    out = run(env, action="list", field="pri")
    assert out["inherited"] and out["rows_from"] == "parent_tbl"
    assert "confirm_inherited=parent_tbl" in out["note"]


def test_list_shows_dependency(env):
    out = run(env, action="list", field="sub")
    assert out["depends_on_field"] == "cat"
    assert out["choices"][0]["dependent_value"] == "hw"


def test_unknown_field_is_not_determined(env):
    out = run(env, action="list", field="nope")
    assert out["success"] is False and out["determined"] is False
    assert "hidden from this account" in out["message"]


def test_unresolved_table_refuses(env):
    with patch.object(ct, "table_ancestry", return_value=None):
        out = run(env, action="set", field="cat", value="x", label="X")
    assert out["success"] is False and not env[0].writes


def test_set_creates_and_rereads(env):
    out = run(env, action="set", field="cat", value="net", label="Network", sequence=3)
    assert out["success"] and out["applied"] and out["verified"]
    assert out["choice"]["label"] == "Network"
    method, body = env[0].writes[0]
    assert method == "POST" and body["name"] == "child_tbl" and body["language"] == "en"


def test_set_relabels_existing(env):
    out = run(env, action="set", field="cat", value="hw", label="Hardware Fix")
    assert out["applied"] and env[0].writes[0][0] == "PATCH"
    assert env[0].writes[0][2] == {"label": "Hardware Fix"}


def test_set_new_needs_label(env):
    out = run(env, action="set", field="cat", value="net", sequence=3)
    assert out["success"] is False and not env[0].writes


def test_set_reports_not_applied(env):
    env[0].drop = {"label"}
    out = run(env, action="set", field="cat", value="hw", label="Other")
    assert out["success"] is False and out["applied"] is False
    assert out["not_applied"]["label"]["actual"] == "Hardware"


def test_inherited_write_needs_named_approval(env):
    out = run(env, action="set", field="pri", value="9", label="Odd")
    assert out["success"] is False and out["rows_from"] == "parent_tbl"
    assert not env[0].writes
    out = run(
        env, action="set", field="pri", value="9", label="Odd", confirm_inherited="parent_tbl"
    )
    assert out["applied"] and env[0].writes[0][1]["name"] == "parent_tbl"
    bad = run(env, action="set", field="pri", value="8", label="Odd", confirm_inherited="child_tbl")
    assert bad["success"] is False


def test_non_choice_field_refused(env):
    out = run(env, action="set", field="txt", value="a", label="A")
    assert out["success"] is False and "not a choice field" in out["message"]
    assert not env[0].writes


def test_dependent_value_rules(env):
    out = run(env, action="set", field="sub", value="ram", label="RAM")
    assert out["success"] is False and "needs dependent_value" in out["message"]
    out = run(env, action="set", field="sub", value="ram", label="RAM", dependent_value="zzz")
    assert out["success"] is False and out["field"] == "dependent_value"
    out = run(env, action="set", field="sub", value="ram", label="RAM", dependent_value="Hardware")
    assert out["applied"] and env[0].writes[-1][1]["dependent_value"] == "hw"
    out = run(env, action="set", field="cat", value="x", label="X", dependent_value="hw")
    assert out["success"] is False and "no dependent field" in out["message"]


def test_duplicate_rows_refuse(env):
    env[0].choices.append(Fake.row(7, "child_tbl", "cat", "hw", "Dup", "9"))
    out = run(env, action="set", field="cat", value="hw", label="X")
    assert out["success"] is False and len(out["candidates"]) == 2 and not env[0].writes


def test_dry_run_writes_nothing(env):
    out = run(env, action="set", field="cat", value="net", label="N", dry_run=True)
    assert out["dry_run"] and out["would_write"]["value"] == "net" and not env[0].writes
    out = run(env, action="deactivate", field="cat", value="hw", dry_run=True)
    assert out["dry_run"] and not env[0].writes


def test_deactivate_and_reactivate(env):
    out = run(env, action="deactivate", field="cat", value="hw")
    assert out["applied"] and out["choice"]["inactive"] is True
    assert env[0].writes[0][2] == {"inactive": "true"}
    out = run(env, action="deactivate", field="cat", value="hw", inactive=False)
    assert out["applied"] and out["choice"]["inactive"] is False


def test_deactivate_noop_and_absent(env):
    out = run(env, action="deactivate", field="cat", value="sw")
    assert out["no_op"] and not env[0].writes
    out = run(env, action="deactivate", field="cat", value="zz")
    assert out["success"] is False and out["determined"] is False


def test_no_delete_path(env):
    assert not any(w[0] == "DELETE" for w in env[0].writes)
    with pytest.raises(ValidationError):
        ManageChoiceParams(action="delete", table="t", field="f", value="v")
