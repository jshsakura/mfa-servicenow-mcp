"""Tests for the Batch API fusion (sn_batch) and its verdict-scan integration.

Pinned invariants:
- One POST serves many GET sub-requests; bodies are base64-decoded and headers
  lower-cased.
- Structural rejections (404/405/400/501) cache 'unsupported' per instance so
  later calls skip the probe; transient failures (5xx, network) do NOT cache.
- Callers fall back per-chunk to direct queries for anything the batch didn't
  serve — same results, old latency, never an error.
"""

import base64
import json
from unittest.mock import MagicMock, patch
from urllib.parse import unquote

import pytest

from servicenow_mcp.tools.sn_batch import (
    batch_get,
    batch_rows,
    reset_batch_support_cache,
    table_query_url,
)
from servicenow_mcp.utils.config import ServerConfig


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


def _batch_response(serviced):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"batch_request_id": "1", "serviced_requests": serviced}
    return resp


def _sub(rid, payload, status=200, headers=()):
    return {
        "id": rid,
        "status_code": status,
        "body": base64.b64encode(json.dumps(payload).encode()).decode(),
        "headers": [{"name": n, "value": v} for n, v in headers],
    }


class TestBatchGet:
    def test_parses_bodies_no_headers(self, mock_config):
        auth = MagicMock()
        auth.make_request.return_value = _batch_response(
            [_sub("0", {"result": [{"sys_id": "a"}]}, headers=[("X-Total-Count", "3")])]
        )
        out = batch_get(mock_config, auth, [("0", "/api/now/table/incident?sysparm_limit=1")])
        assert out["0"]["status_code"] == 200
        assert out["0"]["body"]["result"] == [{"sys_id": "a"}]
        # Sub-response headers are NOT echoed — no caller reads them, so a
        # per-sub-request header dict was pure context weight.
        assert "headers" not in out["0"]
        # One POST carried the whole thing.
        auth.make_request.assert_called_once()
        assert auth.make_request.call_args[0][0] == "POST"
        assert auth.make_request.call_args[0][1].endswith("/api/now/v1/batch")

    def test_structural_404_caches_unsupported(self, mock_config):
        auth = MagicMock()
        auth.make_request.return_value = MagicMock(status_code=404)
        assert batch_get(mock_config, auth, [("0", "/x")]) is None
        # Second call must not even try the network.
        assert batch_get(mock_config, auth, [("0", "/x")]) is None
        auth.make_request.assert_called_once()

    def test_transient_500_is_not_cached(self, mock_config):
        auth = MagicMock()
        auth.make_request.return_value = MagicMock(status_code=500)
        assert batch_get(mock_config, auth, [("0", "/x")]) is None
        assert batch_get(mock_config, auth, [("0", "/x")]) is None
        assert auth.make_request.call_count == 2  # retried — verdict not cached

    def test_network_error_returns_none(self, mock_config):
        auth = MagicMock()
        auth.make_request.side_effect = ConnectionError("boom")
        assert batch_get(mock_config, auth, [("0", "/x")]) is None

    def test_unparsable_sub_body_yields_none_body(self, mock_config):
        auth = MagicMock()
        auth.make_request.return_value = _batch_response(
            [{"id": "0", "status_code": 200, "body": "!!!not-base64-json!!!", "headers": []}]
        )
        out = batch_get(mock_config, auth, [("0", "/x")])
        assert out["0"]["body"] is None  # caller falls back for this id

    def test_empty_input_is_free(self, mock_config):
        auth = MagicMock()
        assert batch_get(mock_config, auth, []) == {}
        auth.make_request.assert_not_called()

    def test_reset_cache_reprobes(self, mock_config):
        auth = MagicMock()
        auth.make_request.return_value = MagicMock(status_code=404)
        batch_get(mock_config, auth, [("0", "/x")])
        reset_batch_support_cache()
        batch_get(mock_config, auth, [("0", "/x")])
        assert auth.make_request.call_count == 2


class TestVerdictScanFusion:
    """The whole directory verdict scan rides ONE Batch API round trip."""

    @pytest.fixture
    def widget_root(self, tmp_path):
        from servicenow_mcp.utils.sync_anchor import field_sha

        root = tmp_path / "output"
        root.mkdir()
        (root / "_settings.json").write_text(
            json.dumps({"name": "test", "url": "https://test.service-now.com", "g_ck": ""}),
            encoding="utf-8",
        )
        widget_dir = root / "global" / "sp_widget" / "my-widget"
        widget_dir.mkdir(parents=True)
        script = widget_dir / "script.js"
        script.write_text("var x = 1;", encoding="utf-8")
        (root / "global" / "sp_widget" / "_map.json").write_text(
            json.dumps({"my-widget": "wid-1"}), encoding="utf-8"
        )
        # Anchor: local == server at last sync -> field-sha of the clean body.
        (root / "global" / "sp_widget" / "_sync_meta.json").write_text(
            json.dumps(
                {
                    "my-widget": {
                        "sys_id": "wid-1",
                        "sys_updated_on": "2025-01-10 10:00:00",
                        "field_shas": {"script": field_sha("var x = 1;")},
                    }
                }
            ),
            encoding="utf-8",
        )
        return root

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_scan_uses_single_batch_round_trip(self, mock_query, mock_config, widget_root):
        from servicenow_mcp.tools.sync_tools import DiffLocalComponentParams, diff_local_component

        auth = MagicMock()
        auth.make_request.return_value = _batch_response(
            [
                _sub(
                    "0",
                    {
                        "result": [
                            {
                                "sys_id": "wid-1",
                                "script": "var x = 2; // server moved",
                                "sys_updated_on": "2025-01-12 10:00:00",
                                "sys_updated_by": "alice",
                                "sys_mod_count": "9",
                            }
                        ]
                    },
                )
            ]
        )
        result = diff_local_component(
            mock_config,
            auth,
            DiffLocalComponentParams(path=str(widget_root / "global"), verdict=True),
        )
        assert result["http_requests"] == 1  # the whole scan = one round trip
        assert result["needs_attention"][0]["verdict"] == "remote_ahead"
        assert "took_ms" in result
        mock_query.assert_not_called()  # no per-chunk fallback needed

    @patch("servicenow_mcp.tools.sync_tools.sn_query")
    def test_scan_falls_back_per_chunk_when_batch_unavailable(
        self, mock_query, mock_config, widget_root
    ):
        from servicenow_mcp.tools.sync_tools import DiffLocalComponentParams, diff_local_component

        # Batch API POST is unavailable (404) → the scan falls back to a per-chunk
        # DIRECT GET. That fallback reads RAW/untruncated (make_request), NOT via
        # sn_query, so a >50k body is never clipped by truncate_results.
        get_rows = [
            {
                "sys_id": "wid-1",
                "script": "var x = 1;",
                "sys_updated_on": "2025-01-10 10:00:00",
                "sys_updated_by": "admin",
                "sys_mod_count": "1",
            }
        ]

        def _side(method, url, **kwargs):
            resp = MagicMock()
            if method == "GET":  # per-chunk fallback fetch
                resp.status_code = 200
                resp.json.return_value = {"result": get_rows}
            else:  # Batch API POST → unavailable
                resp.status_code = 404
                resp.text = "no batch api"
            return resp

        auth = MagicMock()
        auth.make_request.side_effect = _side
        result = diff_local_component(
            mock_config,
            auth,
            DiffLocalComponentParams(path=str(widget_root / "global"), verdict=True),
        )
        assert result["in_sync"] == 1
        assert result["http_requests"] == 1  # one fallback chunk GET
        mock_query.assert_not_called()  # fallback no longer routes through sn_query
        assert any(c.args and c.args[0] == "GET" for c in auth.make_request.call_args_list)


# ---------------------------------------------------------------------------
# table_query_url / batch_rows — the general sub-request builder and reader
# ---------------------------------------------------------------------------


class TestTableQueryUrl:
    def test_builds_a_relative_table_url(self):
        url = table_query_url("sys_script", "collection=x_app_t", "sys_id,name", limit=100)

        assert url.startswith("/api/now/table/sys_script?")
        assert "sysparm_query=collection%3Dx_app_t" in url
        assert "sysparm_fields=sys_id%2Cname" in url
        assert "sysparm_limit=100" in url
        assert "sysparm_display_value=false" in url

    def test_display_values_are_opt_in(self):
        assert "sysparm_display_value=true" in table_query_url(
            "t", "q=1", "sys_id", limit=1, display_value=True
        )

    def test_ordering_travels_inside_the_query_not_as_a_parameter(self):
        # There is no sysparm_orderby on this API; one would be accepted and
        # ignored, which is how ordered reads came back unordered before
        # v1.22.26. An ORDERBY clause is just another encoded-query term.
        url = table_query_url("t", "active=true^ORDERBYDESCsys_created_on", "sys_id", limit=5)

        assert "ORDERBYDESCsys_created_on" in unquote(url)
        assert "sysparm_orderby" not in url


class TestBatchRows:
    def test_returns_the_result_rows(self):
        assert batch_rows({"status_code": 200, "body": {"result": [{"sys_id": "1"}]}}) == [
            {"sys_id": "1"}
        ]

    def test_an_empty_result_is_believed(self):
        # A genuine 200 with no rows means "nothing matched" — refetching it
        # would double the cost of every legitimately empty family.
        assert batch_rows({"status_code": 200, "body": {"result": []}}) == []

    @pytest.mark.parametrize(
        "served",
        [
            None,  # id absent from the response
            {"status_code": 403, "body": None},  # denied
            {"status_code": 500, "body": None},  # server error
            {"status_code": 200, "body": None},  # unparsable body
            {"status_code": 200, "body": {"error": "x"}},  # error payload, no result
            {"status_code": 200, "body": {"result": "not a list"}},
        ],
    )
    def test_anything_unusable_is_none_so_the_caller_refetches(self, served):
        # None and [] must stay distinguishable: "did not come back" is not
        # "came back empty", and only the first one earns a second request.
        assert batch_rows(served) is None


def _cut_sub(rid):
    """A sub-request the server was streaming when the POST hit its output cap.

    Shape copied from a live response: the rows stop mid-value and the error
    object is appended after them, under a 500 — so the body is not JSON.
    """
    partial = (
        '{"result":[{"sys_id":"a","script":"var x = Float(list[0][[[_m"'
        ',"error":{"message":"Transaction cancelled: Max output size reached for '
        'current BatchRest transaction","detail":"Transaction cancelled: Max output '
        'size reached for current BatchRest transaction"},"status":"failure"}'
    )
    return {
        "id": rid,
        "status_code": 500,
        "body": base64.b64encode(partial.encode()).decode(),
        "headers": [],
    }


class TestOutputCap:
    """One batch POST has an output cap (~10MB of base64). Each sub-request is
    fine alone, so the ones it cut go into the NEXT post, not a per-id GET."""

    def test_cut_sub_requests_ride_a_second_post(self, mock_config):
        auth = MagicMock()
        auth.make_request.side_effect = [
            _batch_response([_sub("0", {"result": [{"sys_id": "a"}]}), _cut_sub("1")]),
            _batch_response([_sub("1", {"result": [{"sys_id": "b"}]})]),
        ]
        out = batch_get(mock_config, auth, [("0", "/u0"), ("1", "/u1")])

        assert batch_rows(out["0"]) == [{"sys_id": "a"}]
        assert batch_rows(out["1"]) == [{"sys_id": "b"}]
        second = auth.make_request.call_args_list[1][1]["json"]["rest_requests"]
        assert [r["id"] for r in second] == ["1"]

    def test_ids_never_serviced_after_the_cut_are_re_batched_too(self, mock_config):
        auth = MagicMock()
        auth.make_request.side_effect = [
            # "0" fit, "1" was cut, "2" never came back at all.
            _batch_response([_sub("0", {"result": []}), _cut_sub("1")]),
            _batch_response([_sub("1", {"result": []}), _sub("2", {"result": []})]),
        ]
        out = batch_get(mock_config, auth, [("0", "/u0"), ("1", "/u1"), ("2", "/u2")])

        second = auth.make_request.call_args_list[1][1]["json"]["rest_requests"]
        assert sorted(r["id"] for r in second) == ["1", "2"]
        assert batch_rows(out["2"]) == []

    def test_a_sub_request_over_the_cap_alone_is_left_to_the_direct_get(self, mock_config):
        auth = MagicMock()
        auth.make_request.side_effect = [
            _batch_response([_sub("0", {"result": []}), _cut_sub("1")]),
            _batch_response([_cut_sub("1")]),  # no progress
        ]
        out = batch_get(mock_config, auth, [("0", "/u0"), ("1", "/u1")])

        assert auth.make_request.call_count == 2
        # Still reported as failed, so the caller's per-id fallback runs.
        assert batch_rows(out["1"]) is None

    def test_a_failed_re_batch_keeps_what_the_first_post_returned(self, mock_config):
        auth = MagicMock()
        auth.make_request.side_effect = [
            _batch_response([_sub("0", {"result": [{"sys_id": "a"}]}), _cut_sub("1")]),
            RuntimeError("network"),
        ]
        out = batch_get(mock_config, auth, [("0", "/u0"), ("1", "/u1")])

        assert batch_rows(out["0"]) == [{"sys_id": "a"}]
        assert batch_rows(out["1"]) is None

    def test_an_ordinary_bad_body_is_not_mistaken_for_the_cap(self, mock_config):
        auth = MagicMock()
        bad = {"id": "0", "status_code": 200, "body": base64.b64encode(b"<html>").decode()}
        auth.make_request.return_value = _batch_response([bad])

        out = batch_get(mock_config, auth, [("0", "/u0")])

        auth.make_request.assert_called_once()
        assert batch_rows(out["0"]) is None


def test_a_cut_with_no_error_text_is_recognised_by_the_unserviced_list(mock_config):
    # The other live shape: the cut body just stops (no error appended), and
    # every later sub-request is listed as unserviced.
    stopped = {
        "id": "1",
        "status_code": 500,
        "body": base64.b64encode(b'{"result":[{"sys_id":"a","script":"var j""],""}').decode(),
    }
    first = _batch_response([_sub("0", {"result": []}), stopped])
    first.json.return_value["unserviced_requests"] = ["2", "3"]
    auth = MagicMock()
    auth.make_request.side_effect = [
        first,
        _batch_response([_sub(r, {"result": [{"sys_id": r}]}) for r in ("1", "2", "3")]),
    ]

    out = batch_get(mock_config, auth, [(r, f"/u{r}") for r in ("0", "1", "2", "3")])

    second = auth.make_request.call_args_list[1][1]["json"]["rest_requests"]
    assert sorted(r["id"] for r in second) == ["1", "2", "3"]
    assert all(batch_rows(out[r]) for r in ("1", "2", "3"))
