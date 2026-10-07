"""manage_rest_message — outbound REST message methods and their parameter lists."""

from unittest.mock import MagicMock

import pytest

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.policies.write_guards import MANAGE_READ_ACTIONS
from servicenow_mcp.tools.rest_message_tools import ManageRestMessageParams, manage_rest_message
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig

SVC = "servicenow_mcp.services.rest_message"
MSG = "aaaa1111bbbb2222cccc3333dddd0001"
FN = "aaaa1111bbbb2222cccc3333dddd0002"
QP = "aaaa1111bbbb2222cccc3333dddd0003"
SCOPE = "aaaa1111bbbb2222cccc3333dddd0009"
OTHER_SCOPE = "aaaa1111bbbb2222cccc3333dddd0008"


def _f(value, display=None):
    return {"value": value, "display_value": display if display is not None else value}


class FakeTables:
    """In-memory Table API: sn_query_page reads, make_request writes."""

    def __init__(self):
        self.rows = {
            "sys_rest_message": [
                {
                    "sys_id": _f(MSG),
                    "name": _f("Sample API"),
                    "rest_endpoint": _f("https://api.example.com/base"),
                    "sys_scope": _f(SCOPE, "My App"),
                    "sys_updated_on": _f("2026-07-22 07:00:00"),
                }
            ],
            "sys_rest_message_fn": [
                {
                    "sys_id": _f(FN),
                    "function_name": _f("Get Items"),
                    "http_method": _f("get"),
                    "rest_endpoint": _f(""),
                    "content": _f(""),
                    "rest_message": _f(MSG, "Sample API"),
                    "sys_scope": _f(SCOPE, "My App"),
                    "sys_mod_count": _f("0"),
                    "sys_updated_on": _f("2026-07-22 07:47:44"),
                }
            ],
            "sys_rest_message_fn_param_defs": [
                {
                    "sys_id": _f(QP),
                    "name": _f("Timestamp"),
                    "value": _f("${Timestamp}"),
                    "order": _f("100"),
                    "rest_message_function": _f(FN),
                    "sys_updated_on": _f("2026-07-22 07:47:44"),
                }
            ],
            "sys_rest_message_fn_headers": [],
            "sys_rest_message_fn_parameters": [],
            "sys_rest_message_headers": [],
        }
        self.writes = []
        self.insert_scope = SCOPE

    def query(self, config, auth, *, table, query, fields, limit, offset, **_):
        rows = self.rows.get(table, [])
        for clause in [c for c in query.split("^") if c]:
            key, _, want = clause.partition("=")
            rows = [r for r in rows if str((r.get(key) or {}).get("value", "")) == want]
        return rows[offset : offset + limit], len(rows)

    def request(self, method, url, json=None, **_):
        path = url.split("/api/now/table/", 1)[1]
        table, _, sys_id = path.partition("/")
        self.writes.append((method, table, sys_id, json))
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        if method == "POST":
            new_id = "aaaa1111bbbb2222cccc3333dddd00ff"
            row = {k: _f(str(v)) for k, v in json.items()}
            row["sys_id"] = _f(new_id)
            self.rows[table].append(row)
            resp.json.return_value = {
                "result": {**json, "sys_id": new_id, "sys_scope": {"value": self.insert_scope}}
            }
        elif method == "PATCH":
            row = next(r for r in self.rows[table] if r["sys_id"]["value"] == sys_id)
            row.update({k: _f(str(v)) for k, v in json.items()})
            resp.json.return_value = {"result": {**json, "sys_id": sys_id}}
        else:
            self.rows[table] = [r for r in self.rows[table] if r["sys_id"]["value"] != sys_id]
            resp.json.return_value = {}
        return resp


@pytest.fixture
def env(monkeypatch):
    invalidate_query_cache()
    fake = FakeTables()
    monkeypatch.setattr(f"{SVC}.sn_query_page", fake.query)
    auth = MagicMock(spec=AuthManager)
    auth.get_headers.return_value = {}
    auth.make_request.side_effect = fake.request
    config = ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC, basic=BasicAuthConfig(username="u", password="p")),
    )

    def run(**kw):
        return manage_rest_message(config, auth, ManageRestMessageParams(**kw))

    return fake, run


class TestRead:
    def test_get_method_returns_every_list_and_the_inherited_endpoint(self, env):
        _, run = env
        out = run(action="get_method", sys_id=FN)

        assert out["success"] is True
        assert out["method"]["http_method"] == "GET"
        assert out["method"]["effective_endpoint"] == "https://api.example.com/base"
        assert out["method"]["endpoint_inherited_from_message"] is True
        assert [p["name"] for p in out["query_params"]] == ["Timestamp"]
        assert out["headers"] == [] and out["variables"] == []
        assert out["referenced_variables"] == ["Timestamp"]

    def test_get_method_not_found(self, env):
        _, run = env
        out = run(action="get_method", sys_id="aaaa1111bbbb2222cccc3333dddd0abc")
        assert out["success"] is False and out["error"] == "not_found"

    def test_get_message_lists_its_methods(self, env):
        _, run = env
        out = run(action="get", sys_id=MSG)
        assert [m["name"] for m in out["methods"]] == ["Get Items"]

    def test_read_actions_need_no_confirm(self):
        assert MANAGE_READ_ACTIONS["manage_rest_message"] == {"list", "get", "get_method"}


class TestAddParam:
    def test_adds_a_query_param_after_the_last_order(self, env):
        fake, run = env
        out = run(action="add_param", method_sys_id=FN, name="Offset", value="${Offset}")

        assert out["success"] is True
        method, table, _, body = fake.writes[-1]
        assert (method, table) == ("POST", "sys_rest_message_fn_param_defs")
        assert body == {
            "name": "Offset",
            "value": "${Offset}",
            "order": 200,
            "rest_message_function": FN,
        }
        assert "warning" not in out

    def test_a_duplicate_name_is_refused_without_writing(self, env):
        fake, run = env
        out = run(action="add_param", method_sys_id=FN, name="Timestamp", value="x")
        assert out["error"] == "duplicate_name"
        assert out["existing"]["sys_id"] == QP
        assert fake.writes == []

    def test_header_goes_to_the_header_table(self, env):
        fake, run = env
        run(action="add_param", method_sys_id=FN, param_type="header", name="Accept", value="a")
        assert fake.writes[-1][1] == "sys_rest_message_fn_headers"
        assert "order" not in fake.writes[-1][3]

    def test_a_row_landing_in_another_scope_is_reported(self, env):
        fake, run = env
        fake.insert_scope = OTHER_SCOPE
        out = run(action="add_param", method_sys_id=FN, name="Limit", value="${Limit}")
        assert out["success"] is True
        assert OTHER_SCOPE in out["warning"]

    def test_dry_run_writes_nothing(self, env):
        fake, run = env
        out = run(action="add_param", method_sys_id=FN, name="Limit", dry_run=True)
        assert out["dry_run"] is True
        assert fake.writes == []


class TestUpdateAndRemove:
    def test_update_param_returns_before_and_after(self, env):
        fake, run = env
        out = run(action="update_param", param_sys_id=QP, value="${Ts}")
        assert out["before"]["value"] == "${Timestamp}"
        assert out["after"]["value"] == "${Ts}"
        assert fake.writes[-1][0] == "PATCH"

    def test_pinned_version_blocks_a_moved_record(self, env):
        fake, run = env
        out = run(
            action="update_param",
            param_sys_id=QP,
            value="x",
            expected_updated_on="2026-01-01 00:00:00",
        )
        assert out["error"] == "record_changed"
        assert fake.writes == []

    def test_wrong_param_type_is_not_found_not_a_write(self, env):
        fake, run = env
        out = run(action="remove_param", param_sys_id=QP, param_type="header")
        assert out["error"] == "not_found"
        assert fake.writes == []

    def test_remove_param_reports_what_it_removed(self, env):
        fake, run = env
        out = run(action="remove_param", param_sys_id=QP)
        assert out["removed"]["name"] == "Timestamp"
        assert fake.writes[-1][0] == "DELETE"

    def test_update_method_lowercases_the_verb(self, env):
        fake, run = env
        out = run(action="update_method", sys_id=FN, http_method="post")
        assert out["success"] is True
        assert fake.writes[-1][3] == {"http_method": "post"}


class TestValidation:
    @pytest.mark.parametrize(
        "kw",
        [
            {"action": "get_method"},
            {"action": "add_param", "method_sys_id": FN},
            {"action": "update_param", "param_sys_id": QP},
            {"action": "update_method", "sys_id": FN},
        ],
    )
    def test_missing_required_fields_raise(self, kw):
        with pytest.raises(ValueError):
            ManageRestMessageParams(**kw)
