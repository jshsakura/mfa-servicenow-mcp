"""Extra tests for sn_api.py — cover missed branches (96% → ~100%)."""

import json
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.tools.sn_api import (
    _FIELD_NORM_CACHE,
    AggregateParams,
    GenericQueryParams,
    _generate_query_hint,
    _normalize_fields,
    _safe_json,
    invalidate_query_cache,
    sn_aggregate,
    sn_query,
    sn_query_all,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Bearer token"}
    return auth


class TestNormalizeFieldsCaching:
    def test_cache_hit_returns_same_object(self):
        invalidate_query_cache()
        _FIELD_NORM_CACHE.clear()
        result1 = _normalize_fields("sys_id,name")
        result2 = _normalize_fields("sys_id,name")
        assert result1 is result2
        assert result1 == ["sys_id", "name"]


class TestGenerateQueryHint:
    def test_in_with_ampersand(self):
        hint = _generate_query_hint("nameINa&b&c", "error")
        assert "&" in hint
        assert "IN" in hint

    def test_namein_with_quotes(self):
        hint = _generate_query_hint("nameIN'value'", "error")
        assert "quotes" in hint

    def test_very_long_like_query(self):
        hint = _generate_query_hint("descriptionLIKE" + "x" * 501, "error")
        assert hint

    def test_timeout_hint(self):
        hint = _generate_query_hint("active=true", "Request timed out after 30s")
        assert "timed out" in hint.lower() or "timeout" in hint.lower()

    def test_unauthorized_hint(self):
        hint = _generate_query_hint("active=true", "401 Unauthorized")
        assert "Authentication" in hint or "401" in hint

    def test_no_hint_for_clean_query(self):
        hint = _generate_query_hint("active=true", "Unknown error")
        assert hint is None


class TestSafeJson:
    def test_with_content(self):
        resp = MagicMock()
        resp.content = b'{"result": []}'
        resp.json.return_value = {"result": []}
        result = _safe_json(resp)
        assert result == {"result": []}

    def test_empty_content_falls_back_to_json(self):
        resp = MagicMock()
        resp.content = b""
        resp.json.return_value = {"result": []}
        result = _safe_json(resp)
        assert result == {"result": []}

    def test_invalid_content_returns_raw(self):
        resp = MagicMock()
        resp.content = b"not-json"
        resp.json.side_effect = ValueError("bad json")
        resp.text = "not-json"
        result = _safe_json(resp)
        assert result == {"raw": "not-json"}


class TestSnQueryErrorWithHint:
    def test_query_failure_with_hint(self, mock_config, mock_auth):
        invalidate_query_cache()
        mock_resp = MagicMock()
        mock_resp.content = b""
        mock_resp.json.side_effect = ValueError("bad json")
        mock_resp.text = "Request timed out"
        mock_resp.headers = {}
        mock_resp.raise_for_status.side_effect = Exception("Request timed out after 30s")
        mock_auth.make_request.return_value = mock_resp

        result = sn_query(mock_config, mock_auth, GenericQueryParams(table="incident"))
        assert result["success"] is False
        assert "hint" in result


class TestSnQueryParallelServerRemainingZero:
    def test_parallel_returns_early_when_remaining_zero(self, mock_config, mock_auth):
        invalidate_query_cache()
        response1 = MagicMock()
        response1.content = b'{"result": [{"sys_id": "1"}]}'
        response1.headers = {"X-Total-Count": "1"}
        response1.raise_for_status.return_value = None
        response1.json.return_value = {"result": [{"sys_id": "1"}]}
        mock_auth.make_request.return_value = response1

        result = sn_query_all(
            mock_config,
            mock_auth,
            table="incident",
            query="",
            fields="",
            max_records=1,
        )
        assert len(result) == 1
        assert result[0]["sys_id"] == "1"


class TestSnQuerySequentialFallback:
    def test_sequential_empty_chunk_breaks(self, mock_config, mock_auth):
        invalidate_query_cache()
        response1 = MagicMock()
        response1.content = b'{"result": [{"sys_id": "1"}]}'
        response1.headers = {"X-Total-Count": "1"}
        response1.raise_for_status.return_value = None
        response1.json.return_value = {"result": [{"sys_id": "1"}]}

        response2 = MagicMock()
        response2.content = b"not-json"
        response2.json.side_effect = ValueError("bad")
        response2.text = "error"
        response2.headers = {}
        response2.raise_for_status.side_effect = Exception("fail")

        mock_auth.make_request.side_effect = [response1, response2]
        result = sn_query_all(
            mock_config,
            mock_auth,
            table="incident",
            query="",
            fields="",
            max_records=100,
        )
        assert result == [{"sys_id": "1"}]


class TestSnAggregateFieldRequired:
    def test_sum_without_field_returns_error(self, mock_config, mock_auth):
        invalidate_query_cache()
        result = sn_aggregate(
            mock_config,
            mock_auth,
            AggregateParams(table="incident", aggregate="SUM"),
        )
        assert result["success"] is False
        assert "field is required" in result["message"]


class TestSnQuerySafetyNotice:
    def test_query_with_safety_notice(self, mock_config, mock_auth):
        invalidate_query_cache()
        mock_resp = MagicMock()
        mock_resp.content = json.dumps({"result": [{"sys_id": str(i)} for i in range(1)]}).encode()
        mock_resp.headers = {"X-Total-Count": "1"}
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"result": [{"sys_id": "1"}]}
        mock_auth.make_request.return_value = mock_resp

        result = sn_query(
            mock_config,
            mock_auth,
            GenericQueryParams(table="sys_metadata", limit=10),
        )
        assert result["success"] is True
