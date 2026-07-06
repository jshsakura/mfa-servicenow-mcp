"""Extended tests for sn_api.py — covers uncovered functions and error paths."""

import json
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.tools.sn_api import (
    AggregateParams,
    DiscoverParams,
    GenericQueryParams,
    HealthCheckParams,
    SchemaParams,
    _safe_json,
    apply_payload_safety,
    sn_aggregate,
    sn_count,
    sn_discover,
    sn_health,
    sn_query,
    sn_query_all,
    sn_query_page,
    sn_schema,
    strip_empty_fields,
    truncate_results,
)
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    ServerConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(auth_type="browser"):
    if auth_type == "browser":
        return ServerConfig(
            instance_url="https://test.service-now.com",
            auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
        )
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="admin", password="password"),
        ),
    )


def _mock_response(data, status_code=200, headers=None):
    resp = MagicMock()
    resp.json.return_value = data
    resp.status_code = status_code
    resp.content = json.dumps(data).encode("utf-8")
    resp.text = json.dumps(data)
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    resp.url = "https://test.service-now.com/api/now/table/incident"
    resp.is_redirect = False
    return resp


# ---------------------------------------------------------------------------
# truncate_results
# ---------------------------------------------------------------------------


class TestTruncateResults:
    def test_truncates_long_string_values(self):
        row = {"field": "x" * 60000}
        safe, notice = truncate_results([row], max_len=100)
        assert len(safe) == 1
        assert len(safe[0]["field"]) < 60000
        assert "truncated" in safe[0]["field"]

    def test_non_string_values_counted(self):
        row = {"num": 12345}
        safe, notice = truncate_results([row])
        assert len(safe) == 1
        assert notice is None

    def test_total_budget_truncation(self):
        rows = [{"data": "a" * 1000} for _ in range(300)]
        safe, notice = truncate_results(rows, max_total=5000)
        assert len(safe) < 300
        assert notice is not None
        assert "truncated" in notice.lower()

    def test_empty_input(self):
        safe, notice = truncate_results([])
        assert safe == []
        assert notice is None


# ---------------------------------------------------------------------------
# apply_payload_safety
# ---------------------------------------------------------------------------


class TestApplyPayloadSafety:
    def test_no_fields_defaults_universal_safe(self):
        limit, fields, notice = apply_payload_safety("sp_widget", 50, None)
        field_set = set(fields.split(","))
        assert "sys_id" in field_set
        assert "script" not in field_set
        assert "template" not in field_set
        assert notice is not None

    def test_heavy_fields_clamp_limit(self):
        limit, fields, notice = apply_payload_safety("sp_widget", 50, "name,script")
        assert limit == 5
        assert "heavy fields" in notice.lower()

    def test_explicit_safe_fields_passthrough(self):
        limit, fields, notice = apply_payload_safety("sp_widget", 50, "name,sys_id")
        assert limit == 50
        assert notice is None

    def test_custom_table_no_fields_also_defaults(self):
        # Critical: non-heavy/custom tables must also get safe defaults.
        limit, fields, notice = apply_payload_safety("x_app_custom_table", 50, None)
        assert "sys_id" in fields
        assert notice is not None

    def test_normal_table_explicit_fields_passthrough(self):
        limit, fields, notice = apply_payload_safety("incident", 50, "number,state")
        assert limit == 50
        assert fields == "number,state"
        assert notice is None

    def test_limit_clamped_to_100(self):
        limit, fields, notice = apply_payload_safety("incident", 200, "name")
        assert limit == 100


# ---------------------------------------------------------------------------
# strip_empty_fields — token saver
# ---------------------------------------------------------------------------


class TestStripEmptyFields:
    def test_drops_none_and_empty_string(self):
        record = {"sys_id": "abc", "name": "", "parent": None, "active": True}
        assert strip_empty_fields(record) == {"sys_id": "abc", "active": True}

    def test_keeps_zero_and_false(self):
        # Meaningful falsy values must NOT be dropped.
        record = {"sys_id": "abc", "count": 0, "active": False, "code": "0"}
        assert strip_empty_fields(record) == record

    def test_drops_empty_collections(self):
        record = {"sys_id": "abc", "tags": [], "meta": {}, "x": "y"}
        assert strip_empty_fields(record) == {"sys_id": "abc", "x": "y"}

    def test_empty_record(self):
        assert strip_empty_fields({}) == {}


# ---------------------------------------------------------------------------
# sn_query_page error path
# ---------------------------------------------------------------------------


class TestSnQueryPage:
    def test_fail_silently_returns_empty(self):
        config = _make_config()
        auth = MagicMock()
        auth.make_request.side_effect = Exception("network error")
        rows, total = sn_query_page(
            config,
            auth,
            table="incident",
            query="",
            fields="",
            limit=10,
            offset=0,
            fail_silently=True,
        )
        assert rows == []
        assert total is None

    def test_fail_silently_false_raises(self):
        config = _make_config()
        auth = MagicMock()
        auth.make_request.side_effect = Exception("network error")
        with pytest.raises(Exception, match="network error"):
            sn_query_page(
                config,
                auth,
                table="incident",
                query="",
                fields="",
                limit=10,
                offset=0,
                fail_silently=False,
            )

    def test_orderby_desc(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": [{"sys_id": "1"}]}, headers={"X-Total-Count": "1"})
        auth.make_request.return_value = resp
        rows, total = sn_query_page(
            config,
            auth,
            table="incident",
            query="",
            fields="",
            limit=10,
            offset=0,
            orderby="-created_on",
        )
        assert rows == [{"sys_id": "1"}]
        call_kwargs = auth.make_request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params")
        assert "sysparm_orderby_desc" in params

    def test_no_count_mode(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": []}, headers={})
        auth.make_request.return_value = resp
        rows, total = sn_query_page(
            config,
            auth,
            table="incident",
            query="",
            fields="",
            limit=10,
            offset=0,
            no_count=True,
        )
        assert rows == []


# ---------------------------------------------------------------------------
# sn_query_all
# ---------------------------------------------------------------------------


class TestSnQueryAll:
    def test_empty_first_page(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": []}, headers={"X-Total-Count": "0"})
        auth.make_request.return_value = resp
        result = sn_query_all(
            config,
            auth,
            table="incident",
            query="",
            fields="",
            page_size=10,
            max_records=50,
        )
        assert result == []

    def test_sequential_fallback(self):
        config = _make_config()
        auth = MagicMock()
        # First page: unknown total
        resp1 = _mock_response(
            {"result": [{"sys_id": str(i)} for i in range(10)]},
            headers={},
        )
        # Second page: partial
        resp2 = _mock_response(
            {"result": [{"sys_id": str(i)} for i in range(10, 15)]},
            headers={},
        )
        auth.make_request.side_effect = [resp1, resp2]
        result = sn_query_all(
            config,
            auth,
            table="incident",
            query="",
            fields="",
            page_size=10,
            max_records=50,
            parallel=False,
        )
        assert len(result) == 15

    def test_parallel_fetch(self):
        config = _make_config()
        auth = MagicMock()
        # First page with total count
        resp1 = _mock_response(
            {"result": [{"sys_id": str(i)} for i in range(10)]},
            headers={"X-Total-Count": "20"},
        )
        # Second page
        resp2 = _mock_response(
            {"result": [{"sys_id": str(i)} for i in range(10, 20)]},
            headers={},
        )
        auth.make_request.side_effect = [resp1, resp2]
        result = sn_query_all(
            config,
            auth,
            table="incident",
            query="",
            fields="",
            page_size=10,
            max_records=50,
            parallel=True,
        )
        assert len(result) == 20

    def test_first_page_partial(self):
        """When first page returns fewer than requested, no more pages fetched."""
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response(
            {"result": [{"sys_id": "1"}]},
            headers={"X-Total-Count": "1"},
        )
        auth.make_request.return_value = resp
        result = sn_query_all(
            config,
            auth,
            table="incident",
            query="",
            fields="",
            page_size=10,
            max_records=50,
        )
        assert len(result) == 1
        assert auth.make_request.call_count == 1

    def test_cap_respected(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response(
            {"result": [{"sys_id": str(i)} for i in range(10)]},
            headers={"X-Total-Count": "100"},
        )
        auth.make_request.return_value = resp
        result = sn_query_all(
            config,
            auth,
            table="incident",
            query="",
            fields="",
            page_size=10,
            max_records=5,
        )
        assert len(result) <= 5


# ---------------------------------------------------------------------------
# sn_count
# ---------------------------------------------------------------------------


class TestSnCount:
    def test_success(self):
        config = _make_config()
        auth = MagicMock()
        resp = MagicMock()
        resp.json.return_value = {"result": {"stats": {"count": "42"}}}
        auth.make_request.return_value = resp
        assert sn_count(config, auth, "incident") == 42

    def test_with_query(self):
        config = _make_config()
        auth = MagicMock()
        resp = MagicMock()
        resp.json.return_value = {"result": {"stats": {"count": "10"}}}
        auth.make_request.return_value = resp
        assert sn_count(config, auth, "incident", query="active=true") == 10

    def test_error_returns_zero(self):
        config = _make_config()
        auth = MagicMock()
        auth.make_request.side_effect = Exception("fail")
        assert sn_count(config, auth, "incident") == 0


# ---------------------------------------------------------------------------
class TestSnAggregate:
    def test_count_aggregate(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": {"stats": {"count": "5"}}})
        auth.make_request.return_value = resp
        params = AggregateParams(table="incident", aggregate="COUNT")
        result = sn_aggregate(config, auth, params)
        assert result["success"] is True

    def test_sum_without_field(self):
        config = _make_config()
        auth = MagicMock()
        params = AggregateParams(table="incident", aggregate="SUM")
        result = sn_aggregate(config, auth, params)
        assert result["success"] is False
        assert "field is required" in result["message"]

    def test_sum_with_field(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": {"stats": {"sum": {"value": "100"}}}})
        auth.make_request.return_value = resp
        params = AggregateParams(table="incident", aggregate="SUM", field="priority")
        result = sn_aggregate(config, auth, params)
        assert result["success"] is True

    def test_aggregate_with_group_by(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": [{"group_by": "p1", "count": "3"}]})
        auth.make_request.return_value = resp
        params = AggregateParams(table="incident", aggregate="COUNT", group_by="priority")
        result = sn_aggregate(config, auth, params)
        assert result["success"] is True

    def test_aggregate_exception(self):
        config = _make_config()
        auth = MagicMock()
        auth.make_request.side_effect = Exception("timeout")
        params = AggregateParams(table="incident", aggregate="COUNT")
        result = sn_aggregate(config, auth, params)
        assert result["success"] is False
        assert "Aggregate failed" in result["message"]


# ---------------------------------------------------------------------------
# sn_schema
# ---------------------------------------------------------------------------


class TestSnSchema:
    def test_success(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response(
            {
                "result": [
                    {
                        "element": "number",
                        "column_label": "Number",
                        "internal_type": "string",
                        "max_length": "40",
                        "mandatory": "true",
                        "reference": "",
                    },
                    {"element": "", "column_label": "Empty"},  # should be filtered out
                ]
            }
        )
        auth.make_request.return_value = resp
        params = SchemaParams(table="incident")
        result = sn_schema(config, auth, params)
        assert result["success"] is True
        assert result["count"] == 1
        assert result["fields"][0]["field"] == "number"

    def test_exception(self):
        config = _make_config()
        auth = MagicMock()
        auth.make_request.side_effect = Exception("fail")
        params = SchemaParams(table="incident")
        result = sn_schema(config, auth, params)
        assert result["success"] is False

    def test_editable_table_surfaces_write_path(self):
        # P2 discoverability: a code-bearing table editable via
        # manage_portal_component must advertise that write path in its schema.
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response(
            {
                "result": [
                    {
                        "element": "script",
                        "column_label": "Script",
                        "internal_type": "script",
                        "max_length": "8000",
                        "mandatory": "false",
                        "reference": "",
                    }
                ]
            }
        )
        auth.make_request.return_value = resp
        result = sn_schema(config, auth, SchemaParams(table="sys_script_include"))
        assert result["success"] is True
        assert result["editable_via"]["tool"] == "manage_portal_component"
        assert result["editable_via"]["by"] == "sys_id"
        assert "script" in result["editable_via"]["fields"]

    def test_non_editable_table_has_no_write_path(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": [{"element": "number", "column_label": "Number"}]})
        auth.make_request.return_value = resp
        # cmdb_ci is not in PORTAL_COMPONENT_EDITABLE_FIELDS — no write path claim.
        result = sn_schema(config, auth, SchemaParams(table="cmdb_ci"))
        assert result["success"] is True
        assert "editable_via" not in result


# ---------------------------------------------------------------------------
# sn_discover
# ---------------------------------------------------------------------------


class TestSnDiscover:
    def test_success(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": [{"name": "incident", "label": "Incident"}]})
        auth.make_request.return_value = resp
        params = DiscoverParams(keyword="incident")
        result = sn_discover(config, auth, params)
        assert result["success"] is True
        assert result["count"] == 1

    def test_exception(self):
        config = _make_config()
        auth = MagicMock()
        auth.make_request.side_effect = Exception("fail")
        params = DiscoverParams(keyword="test")
        result = sn_discover(config, auth, params)
        assert result["success"] is False

    def test_concept_alias_surfaces_real_tables(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": []})
        auth.make_request.return_value = resp
        # UI phrase that does not substring-match any table name.
        params = DiscoverParams(keyword="page dependency")
        result = sn_discover(config, auth, params)

        assert result["success"] is True
        assert result["matched_concept_tables"] == [
            "m2m_sp_widget_dependency",
            "sp_dependency",
        ]
        sent_query = auth.make_request.call_args.kwargs["params"]["sysparm_query"]
        assert "ORnameINm2m_sp_widget_dependency,sp_dependency" in sent_query

    def test_no_alias_for_plain_keyword(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": [{"name": "incident"}]})
        auth.make_request.return_value = resp
        params = DiscoverParams(keyword="incident_unique_kw")
        result = sn_discover(config, auth, params)
        assert "matched_concept_tables" not in result


# ---------------------------------------------------------------------------
# sn_health
# ---------------------------------------------------------------------------


class TestSnHealth:
    def test_health_success(self):
        config = _make_config("basic")
        auth = MagicMock()
        resp = _mock_response({"result": [{"sys_id": "1"}]})
        auth.make_request.return_value = resp
        result = sn_health(config, auth, HealthCheckParams())
        assert result["ok"] is True

    def test_health_exception(self):
        config = _make_config("basic")
        auth = MagicMock()
        auth.make_request.side_effect = Exception("connection refused")
        result = sn_health(config, auth, HealthCheckParams())
        assert result["ok"] is False
        assert "error" in result

    def test_health_non_browser_failure(self):
        config = _make_config("basic")
        auth = MagicMock()
        resp = _mock_response({"error": "forbidden"}, status_code=403)
        resp.headers = {"Location": ""}
        resp.url = "https://test.service-now.com/api/now/table/sys_user"
        resp.is_redirect = False
        auth.make_request.return_value = resp
        result = sn_health(config, auth, HealthCheckParams())
        assert result["ok"] is False
        assert result["status_code"] == 403

    def test_health_probe_without_query_string(self):
        config = ServerConfig(
            instance_url="https://test.service-now.com",
            auth=AuthConfig(
                type=AuthType.BROWSER,
                browser=BrowserAuthConfig(probe_path="/api/now/table/sys_user"),
            ),
        )
        auth = MagicMock()
        resp = _mock_response({"result": []})
        auth.make_request.return_value = resp
        result = sn_health(config, auth, HealthCheckParams())
        assert result["ok"] is True

    def test_health_login_redirect_non_browser(self):
        """Non-browser auth with login redirect in Location header."""
        config = _make_config("basic")
        auth = MagicMock()
        resp = _mock_response({}, status_code=401)
        resp.headers = {"Location": "https://test.service-now.com/login.do"}
        resp.url = "https://test.service-now.com/login.do"
        resp.is_redirect = True
        auth.make_request.return_value = resp
        result = sn_health(config, auth, HealthCheckParams())
        assert result["ok"] is False
        assert result["diagnostics"]["looks_like_login_redirect"] is True

    def test_health_returns_running_version(self):
        """Every sn_health response carries the running MCP server version so
        the LLM can diagnose stale-uvx-cache symptoms without log access."""
        from servicenow_mcp.version import __version__

        scenarios = [
            # success
            lambda auth: auth.make_request.__setattr__(
                "return_value", _mock_response({"result": []})
            ),
            # exception
            lambda auth: auth.make_request.__setattr__("side_effect", Exception("boom")),
        ]
        for setup in scenarios:
            config = _make_config("basic")
            auth = MagicMock()
            setup(auth)
            result = sn_health(config, auth, HealthCheckParams())
            assert result["version"] == __version__


# ---------------------------------------------------------------------------
# _safe_json
# ---------------------------------------------------------------------------


class TestSafeJson:
    def test_normal_response(self):
        resp = _mock_response({"key": "value"})
        result = _safe_json(resp)
        assert result["key"] == "value"

    def test_unparseable_falls_back(self):
        resp = MagicMock()
        resp.content = b"not json"
        resp.text = "not json"
        resp.json.side_effect = Exception("bad json")
        result = _safe_json(resp)
        assert "raw" in result


# ---------------------------------------------------------------------------
# sn_query error path
# ---------------------------------------------------------------------------


class TestSnQueryErrors:
    def test_query_exception(self):
        config = _make_config()
        auth = MagicMock()
        auth.make_request.side_effect = Exception("server error")
        params = GenericQueryParams(table="incident")
        result = sn_query(config, auth, params)
        assert result["success"] is False
        assert "Query failed" in result["message"]


# ---------------------------------------------------------------------------
# Scope namespace canonicalization — accept display name / sys_id, always
# resolve to the namespace so download folders/queries are deterministic.
# ---------------------------------------------------------------------------


class TestResolveScopeNamespace:
    def _patch_rows(self, rows):
        from unittest.mock import patch

        return patch("servicenow_mcp.tools.sn_api.sn_query_all", return_value=rows)

    def test_display_name_resolves_to_namespace(self):
        from servicenow_mcp.tools.sn_api import resolve_scope_namespace

        rows = [{"sys_id": "s1", "scope": "x_acme_hbpm", "name": "BPM"}]
        with self._patch_rows(rows):
            ns, rec = resolve_scope_namespace(_make_config(), MagicMock(), "BPM")
        assert ns == "x_acme_hbpm"
        assert rec["name"] == "BPM"

    def test_namespace_input_returns_itself(self):
        from servicenow_mcp.tools.sn_api import resolve_scope_namespace

        rows = [{"sys_id": "s1", "scope": "x_app", "name": "My App"}]
        with self._patch_rows(rows):
            ns, _ = resolve_scope_namespace(_make_config(), MagicMock(), "x_app")
        assert ns == "x_app"

    def test_prefers_exact_scope_over_name_match(self):
        from servicenow_mcp.tools.sn_api import resolve_scope_namespace

        # Ambiguous: one row matches by name, one by scope. Scope wins.
        rows = [
            {"sys_id": "s1", "scope": "x_other", "name": "x_app"},
            {"sys_id": "s2", "scope": "x_app", "name": "Real App"},
        ]
        with self._patch_rows(rows):
            ns, rec = resolve_scope_namespace(_make_config(), MagicMock(), "x_app")
        assert ns == "x_app"
        assert rec["sys_id"] == "s2"

    def test_no_match_falls_back_to_input(self):
        from servicenow_mcp.tools.sn_api import resolve_scope_namespace

        with self._patch_rows([]):
            ns, rec = resolve_scope_namespace(_make_config(), MagicMock(), "Unknown")
        assert ns == "Unknown"
        assert rec is None

    def test_empty_scope_short_circuits(self):
        from unittest.mock import patch

        from servicenow_mcp.tools.sn_api import resolve_scope_namespace

        with patch("servicenow_mcp.tools.sn_api.sn_query_all") as q:
            ns, rec = resolve_scope_namespace(_make_config(), MagicMock(), "")
        assert ns == ""
        assert rec is None
        q.assert_not_called()  # no network for an empty token


class TestApplyScopeNamespace:
    def test_rebinds_scope_and_reports_resolution(self):
        from unittest.mock import patch

        from pydantic import BaseModel

        from servicenow_mcp.tools.sn_api import apply_scope_namespace

        class P(BaseModel):
            scope: str

        rows = [{"sys_id": "s1", "scope": "x_acme_hbpm", "name": "BPM"}]
        original = P(scope="BPM")
        with patch("servicenow_mcp.tools.sn_api.sn_query_all", return_value=rows):
            new, resolution = apply_scope_namespace(_make_config(), MagicMock(), original)
        assert new.scope == "x_acme_hbpm"
        assert original.scope == "BPM"  # immutable: original untouched
        assert "x_acme_hbpm" in resolution and "BPM" in resolution

    def test_not_found_keeps_scope_and_warns(self):
        from unittest.mock import patch

        from pydantic import BaseModel

        from servicenow_mcp.tools.sn_api import apply_scope_namespace

        class P(BaseModel):
            scope: str

        with patch("servicenow_mcp.tools.sn_api.sn_query_all", return_value=[]):
            new, resolution = apply_scope_namespace(_make_config(), MagicMock(), P(scope="BPM"))
        assert new.scope == "BPM"
        assert "not found" in resolution
