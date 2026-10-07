"""Oversized IN lists are split by the query layer; a missing table is named as such.

Both shapes came out of real session logs: a ~190-id provider read that 400'd
and was silenced into `total=0`, and sn_query answering a misspelled table with
a bare "HTTP Error 400: Bad Request" that the model then guessed around.
"""

import json
from unittest.mock import MagicMock

import pytest
import requests

from servicenow_mcp.tools.sn_api import (
    SYS_ID_IN_CHUNK,
    AggregateParams,
    GenericQueryParams,
    SchemaParams,
    invalidate_query_cache,
    sn_aggregate,
    sn_query,
    sn_query_all,
    sn_query_page,
    sn_schema,
    split_oversized_in,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig
from servicenow_mcp.utils.query_fields import forget_columns


def _ids(n):
    return [f"aaaa{i:04d}bbbb2222cccc3333dddd4444"[:32] for i in range(n)]


@pytest.fixture
def config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


@pytest.fixture(autouse=True)
def _clean_caches():
    invalidate_query_cache()
    forget_columns()
    yield
    invalidate_query_cache()
    forget_columns()


def _response(status=200, result=None, total=None, body=None):
    resp = MagicMock()
    resp.status_code = status
    payload = body if body is not None else {"result": result if result is not None else []}
    resp.content = json.dumps(payload).encode()
    resp.json.return_value = payload
    resp.text = resp.content.decode()
    resp.headers = {"X-Total-Count": str(total)} if total is not None else {}
    if status >= 400:
        err = requests.exceptions.HTTPError(f"{status} Client Error", response=resp)
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


def _in_server(table, max_in=SYS_ID_IN_CHUNK):
    """A fake Table API that 400s an IN list longer than the measured limit and
    otherwise returns one row per requested sys_id."""
    calls = []

    def handler(method, url, params=None, **_):
        params = params or {}
        if url.endswith(f"/{table}"):
            query = params.get("sysparm_query", "")
            calls.append(query)
            ids = (
                query.split("sys_idIN", 1)[1].split("^")[0].split(",")
                if "sys_idIN" in query
                else []
            )
            if len(ids) > max_in:
                return _response(400, body={})
            rows = [{"sys_id": i, "name": f"n{i[4:8]}"} for i in ids]
            offset = int(params.get("sysparm_offset", 0))
            limit = int(params.get("sysparm_limit", 100))
            return _response(200, rows[offset : offset + limit], total=len(rows))
        return _response(200, [])

    return handler, calls


class TestSplitOversizedIn:
    def test_short_list_is_left_alone(self):
        assert split_oversized_in("sys_idIN" + ",".join(_ids(SYS_ID_IN_CHUNK))) is None

    def test_long_list_is_split_and_other_clauses_kept(self):
        ids = _ids(SYS_ID_IN_CHUNK * 2 + 5)
        parts = split_oversized_in("active=true^sys_idIN" + ",".join(ids) + "^ORDERBYname")
        assert len(parts) == 3
        recovered = []
        for part in parts:
            clauses = part.split("^")
            assert clauses[0] == "active=true" and clauses[-1] == "ORDERBYname"
            recovered += clauses[1][len("sys_idIN") :].split(",")
        assert recovered == ids

    @pytest.mark.parametrize(
        "query",
        [
            "sys_idIN{ids}^ORnameINx",  # OR changes what a split means
            "sys_idIN{ids}^NQactive=true",
            "sys_idIN{ids}^nameIN{ids}",  # two oversized lists
            "sys_idNOT IN{ids}",  # NOT IN is an AND of the parts, not a union
        ],
    )
    def test_shapes_whose_split_is_not_exact_run_as_sent(self, query):
        assert split_oversized_in(query.format(ids=",".join(_ids(40)))) is None


class TestQueryLayerSplits:
    def test_sn_query_all_returns_every_row_of_an_oversized_list(self, config):
        handler, calls = _in_server("sp_angular_provider")
        auth = MagicMock()
        auth.make_request.side_effect = handler
        ids = _ids(190)

        rows = sn_query_all(
            config,
            auth,
            table="sp_angular_provider",
            query="sys_idIN" + ",".join(ids),
            fields="sys_id,name",
            page_size=100,
            max_records=1000,
        )

        assert sorted(r["sys_id"] for r in rows) == sorted(ids)
        assert all(len(q.split(",")) <= SYS_ID_IN_CHUNK for q in calls)

    def test_sn_query_page_merges_total_and_order(self, config):
        handler, _ = _in_server("sp_widget")
        auth = MagicMock()
        auth.make_request.side_effect = handler
        ids = _ids(70)

        rows, total = sn_query_page(
            config,
            auth,
            table="sp_widget",
            query="sys_idIN" + ",".join(reversed(ids)),
            fields="sys_id,name",
            limit=50,
            offset=10,
            orderby="sys_id",
            fail_silently=False,
        )

        assert total == 70
        assert [r["sys_id"] for r in rows] == sorted(ids)[10:60]

    def test_sn_query_tool_answers_an_oversized_list(self, config):
        handler, _ = _in_server("sp_widget")
        auth = MagicMock()
        auth.make_request.side_effect = handler

        result = sn_query(
            config,
            auth,
            GenericQueryParams(
                table="sp_widget",
                query="sys_idIN" + ",".join(_ids(45)),
                fields="sys_id,name",
                limit=100,
            ),
        )

        assert result["success"] is True
        assert result["count"] == 45


class TestUnknownTable:
    def _auth(self, table_registered, similar=()):
        def handler(method, url, params=None, **_):
            params = params or {}
            if url.endswith("/sys_db_object"):
                query = params.get("sysparm_query", "")
                if query.startswith("name="):
                    return _response(200, [{"name": query[5:]}] if table_registered else [])
                if "nameLIKE" in query:
                    return _response(200, [{"name": n} for n in similar])
            if url.endswith("/sys_dictionary"):
                return _response(200, [])
            return _response(400, body={})

        auth = MagicMock()
        auth.make_request.side_effect = handler
        return auth

    def test_missing_table_is_named_with_suggestions(self, config):
        auth = self._auth(False, similar=["x_myapp_rfq_entry", "x_myapp_rfq_line"])

        result = sn_query(config, auth, GenericQueryParams(table="rfq_entry", query="", limit=5))

        assert result["error"] == "unknown_table"
        assert result["did_you_mean"][0] == "x_myapp_rfq_entry"

    def test_registered_table_keeps_the_original_error(self, config):
        auth = self._auth(True)

        result = sn_query(config, auth, GenericQueryParams(table="incident", query="", limit=5))

        assert result.get("error") != "unknown_table"
        assert "Query failed" in result["message"]

    def test_lookup_that_fails_is_not_read_as_absence(self, config):
        def handler(method, url, params=None, **_):
            return _response(400, body={})

        auth = MagicMock()
        auth.make_request.side_effect = handler

        result = sn_query(config, auth, GenericQueryParams(table="incident", query="", limit=5))

        assert result.get("error") != "unknown_table"

    def test_aggregate_names_a_missing_table(self, config):
        auth = self._auth(False)

        result = sn_aggregate(
            config, auth, AggregateParams(table="x_myapp_nope", aggregate="COUNT")
        )

        assert result["error"] == "unknown_table"
        assert result["aggregate"] == "COUNT"

    def test_schema_does_not_claim_absence_when_lookup_failed(self, config):
        def handler(method, url, params=None, **_):
            if url.endswith("/sys_dictionary"):
                return _response(200, [])
            raise requests.exceptions.ConnectionError("down")

        auth = MagicMock()
        auth.make_request.side_effect = handler

        result = sn_schema(config, auth, SchemaParams(table="x_myapp_base_child"))

        assert result["success"] is True


class TestClippedFieldFingerprint:
    """A clipped body cannot be compared by its visible prefix; the full hash can."""

    def _auth(self, body):
        def handler(method, url, params=None, **_):
            if url.endswith("/sp_widget"):
                return _response(
                    200, [{"sys_id": "aaaa1111bbbb2222cccc3333dddd4444", "script": body}]
                )
            return _response(200, [])

        auth = MagicMock()
        auth.make_request.side_effect = handler
        return auth

    def _read(self, config, body):
        return sn_query(
            config,
            self._auth(body),
            GenericQueryParams(table="sp_widget", query="", fields="sys_id,script", limit=1),
        )

    def test_a_clipped_field_carries_its_whole_hash_and_length(self, config):
        from servicenow_mcp.utils.sync_anchor import field_sha

        body = "a" * 50000 + "b" * 17576
        result = self._read(config, body)

        clip = result["clipped_fields"][0]
        assert clip["field"] == "script"
        assert clip["full_length"] == 67576
        assert clip["full_sha256"] == field_sha(body)
        assert "compare_instances" in result["clipped_hint"]

    def test_bodies_that_differ_only_past_the_clip_hash_differently(self, config):
        invalidate_query_cache()
        first = self._read(config, "a" * 50000 + "tail-one")["clipped_fields"][0]
        invalidate_query_cache()
        second = self._read(config, "a" * 50000 + "tail-two")["clipped_fields"][0]

        assert first["full_sha256"] != second["full_sha256"]

    def test_an_unclipped_read_carries_no_fingerprint_block(self, config):
        assert "clipped_fields" not in self._read(config, "short")
