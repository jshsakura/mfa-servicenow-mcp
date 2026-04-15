"""Extended tests for sn_api.py — covers uncovered functions and error paths."""

import json
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.tools.sn_api import (
    AggregateParams,
    DiscoverParams,
    GenericQueryParams,
    HealthCheckParams,
    NaturalLanguageParams,
    SchemaParams,
    _safe_json,
    apply_payload_safety,
    sn_aggregate,
    sn_batch,
    sn_count,
    sn_discover,
    sn_health,
    sn_nl,
    sn_query,
    sn_query_all,
    sn_query_page,
    sn_schema,
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
    def test_heavy_table_no_fields(self):
        limit, fields, notice = apply_payload_safety("sp_widget", 50, None)
        assert fields == "sys_id,name,id,sys_scope"
        assert notice is not None

    def test_heavy_table_with_heavy_fields(self):
        limit, fields, notice = apply_payload_safety("sp_widget", 50, "name,script")
        assert limit == 5
        assert "heavy fields" in notice.lower()

    def test_heavy_table_with_safe_fields(self):
        limit, fields, notice = apply_payload_safety("sp_widget", 50, "name,sys_id")
        assert limit == 50
        assert notice is None

    def test_normal_table(self):
        limit, fields, notice = apply_payload_safety("incident", 50, None)
        assert limit == 50
        assert notice is None

    def test_limit_clamped_to_100(self):
        limit, fields, notice = apply_payload_safety("incident", 200, "name")
        assert limit == 100


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
# sn_batch
# ---------------------------------------------------------------------------


class TestSnBatch:
    def test_empty_requests(self):
        config = _make_config()
        auth = MagicMock()
        assert sn_batch(config, auth, requests=[]) == {}

    def test_successful_batch(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response(
            {
                "serviced_requests": [
                    {"id": "req1", "body": {"result": "ok"}, "status_code": 200},
                    {"id": "req2", "body": {"result": "ok2"}, "status_code": 200},
                ]
            }
        )
        auth.make_request.return_value = resp
        result = sn_batch(
            config,
            auth,
            requests=[
                {"id": "req1", "method": "GET", "url": "/api/now/table/incident"},
                {"id": "req2", "method": "GET", "url": "/api/now/table/task"},
            ],
        )
        assert "req1" in result
        assert "req2" in result

    def test_batch_sub_request_error(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response(
            {
                "serviced_requests": [
                    {"id": "req1", "body": {}, "status_code": 404},
                ]
            }
        )
        auth.make_request.return_value = resp
        result = sn_batch(
            config,
            auth,
            requests=[{"id": "req1", "method": "GET", "url": "/api/now/table/x"}],
        )
        assert "error" in result["req1"]

    def test_batch_exception(self):
        config = _make_config()
        auth = MagicMock()
        auth.make_request.side_effect = Exception("connection failed")
        result = sn_batch(
            config,
            auth,
            requests=[{"id": "req1", "method": "GET", "url": "/api/now/table/x"}],
        )
        assert "error" in result["req1"]


# ---------------------------------------------------------------------------
# sn_aggregate
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


# ---------------------------------------------------------------------------
# sn_nl (natural language)
# ---------------------------------------------------------------------------


class TestSnNl:
    def test_count_intent(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": {"stats": {"count": "10"}}})
        auth.make_request.return_value = resp
        params = NaturalLanguageParams(text="how many incidents are there?")
        result = sn_nl(config, auth, params)
        assert result["success"] is True

    def test_schema_intent(self):
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
                    }
                ]
            }
        )
        auth.make_request.return_value = resp
        params = NaturalLanguageParams(text="describe the fields of incident")
        result = sn_nl(config, auth, params)
        assert result["success"] is True

    def test_delete_blocked(self):
        config = _make_config()
        auth = MagicMock()
        params = NaturalLanguageParams(text="delete all incidents")
        result = sn_nl(config, auth, params)
        assert result["success"] is False
        assert "blocked" in result["message"].lower()

    def test_create_without_execute(self):
        config = _make_config()
        auth = MagicMock()
        params = NaturalLanguageParams(text="create a new incident", execute=False)
        result = sn_nl(config, auth, params)
        assert result["executed"] is False

    def test_query_with_priority(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": []}, headers={"X-Total-Count": "0"})
        auth.make_request.return_value = resp
        params = NaturalLanguageParams(text="show me p1 incidents")
        result = sn_nl(config, auth, params)
        assert result["success"] is True

    def test_query_with_closed(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": []}, headers={"X-Total-Count": "0"})
        auth.make_request.return_value = resp
        params = NaturalLanguageParams(text="show closed problems")
        result = sn_nl(config, auth, params)
        assert result["success"] is True

    def test_reference_number(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": []}, headers={"X-Total-Count": "0"})
        auth.make_request.return_value = resp
        params = NaturalLanguageParams(text="find inc0012345")
        result = sn_nl(config, auth, params)
        assert result["success"] is True

    def test_table_aliases(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": {"stats": {"count": "1"}}})
        auth.make_request.return_value = resp
        # "changes" should map to "change_request"
        params = NaturalLanguageParams(text="count changes")
        result = sn_nl(config, auth, params)
        assert result["table"] == "change_request"

    def test_unknown_table_defaults_to_incident(self):
        config = _make_config()
        auth = MagicMock()
        resp = _mock_response({"result": {"stats": {"count": "0"}}})
        auth.make_request.return_value = resp
        params = NaturalLanguageParams(text="count foobar")
        result = sn_nl(config, auth, params)
        assert result["table"] == "incident"


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
