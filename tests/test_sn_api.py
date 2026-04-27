from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.sn_api import (
    _CACHE_MAX_ENTRIES,
    _CACHE_TTL_SECONDS,
    GenericQueryParams,
    HealthCheckParams,
    _cache_get,
    _cache_put,
    invalidate_query_cache,
    sn_health,
    sn_query,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig


def test_sn_query_uses_auth_manager_make_request():
    invalidate_query_cache()
    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )
    auth_manager = MagicMock()
    response = MagicMock()
    response.content = b'{"result": [{"sys_id": "1"}]}'
    response.headers = {"X-Total-Count": "1"}
    response.raise_for_status.return_value = None
    response.json.return_value = {"result": [{"sys_id": "1"}]}
    auth_manager.make_request.return_value = response

    result = sn_query(config, auth_manager, GenericQueryParams(table="incident"))

    assert result["success"] is True
    assert result["count"] == 1
    assert auth_manager.make_request.call_count == 1


def test_sn_query_reuses_cached_page_for_identical_requests():
    invalidate_query_cache()
    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )
    auth_manager = MagicMock()
    response = MagicMock()
    response.content = b'{"result": [{"sys_id": "1"}]}'
    response.headers = {"X-Total-Count": "1"}
    response.raise_for_status.return_value = None
    auth_manager.make_request.return_value = response

    params = GenericQueryParams(table="incident", query="active=true", orderby="number")

    first = sn_query(config, auth_manager, params)
    second = sn_query(config, auth_manager, params)

    assert first["success"] is True
    assert second["success"] is True
    assert auth_manager.make_request.call_count == 1


def test_sn_query_cache_key_keeps_orderby_distinct():
    invalidate_query_cache()
    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )
    auth_manager = MagicMock()

    first_response = MagicMock()
    first_response.content = b'{"result": [{"sys_id": "1"}]}'
    first_response.headers = {"X-Total-Count": "1"}
    first_response.raise_for_status.return_value = None

    second_response = MagicMock()
    second_response.content = b'{"result": [{"sys_id": "2"}]}'
    second_response.headers = {"X-Total-Count": "1"}
    second_response.raise_for_status.return_value = None

    auth_manager.make_request.side_effect = [first_response, second_response]

    asc = sn_query(config, auth_manager, GenericQueryParams(table="incident", orderby="number"))
    desc = sn_query(config, auth_manager, GenericQueryParams(table="incident", orderby="-number"))

    assert asc["results"][0]["sys_id"] == "1"
    assert desc["results"][0]["sys_id"] == "2"
    assert auth_manager.make_request.call_count == 2


def test_invalidate_query_cache_clears_matching_table_entries():
    invalidate_query_cache()
    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )
    auth_manager = MagicMock()

    incident_response = MagicMock()
    incident_response.content = b'{"result": [{"sys_id": "1"}]}'
    incident_response.headers = {"X-Total-Count": "1"}
    incident_response.raise_for_status.return_value = None

    task_response = MagicMock()
    task_response.content = b'{"result": [{"sys_id": "2"}]}'
    task_response.headers = {"X-Total-Count": "1"}
    task_response.raise_for_status.return_value = None

    replacement_incident_response = MagicMock()
    replacement_incident_response.content = b'{"result": [{"sys_id": "3"}]}'
    replacement_incident_response.headers = {"X-Total-Count": "1"}
    replacement_incident_response.raise_for_status.return_value = None

    auth_manager.make_request.side_effect = [
        incident_response,
        task_response,
        replacement_incident_response,
    ]

    first_incident = sn_query(config, auth_manager, GenericQueryParams(table="incident"))
    first_task = sn_query(config, auth_manager, GenericQueryParams(table="task"))
    removed = invalidate_query_cache(table="incident")
    second_incident = sn_query(config, auth_manager, GenericQueryParams(table="incident"))
    second_task = sn_query(config, auth_manager, GenericQueryParams(table="task"))

    assert first_incident["results"][0]["sys_id"] == "1"
    assert first_task["results"][0]["sys_id"] == "2"
    assert removed >= 1
    assert second_incident["results"][0]["sys_id"] == "3"
    assert second_task["results"][0]["sys_id"] == "2"
    assert auth_manager.make_request.call_count == 3


# ---------------------------------------------------------------------------
# OrderedDict LRU cache tests
# ---------------------------------------------------------------------------


def test_cache_evicts_oldest_when_full():
    """When cache reaches capacity, the oldest (least-recently-inserted) entry is evicted."""
    invalidate_query_cache()
    # Fill cache to capacity
    for i in range(_CACHE_MAX_ENTRIES):
        _cache_put(f"key_{i}", f"value_{i}")
    # All entries should be present
    assert _cache_get("key_0") == "value_0"
    assert _cache_get(f"key_{_CACHE_MAX_ENTRIES - 1}") == f"value_{_CACHE_MAX_ENTRIES - 1}"

    # Insert one more — oldest that wasn't recently accessed should be evicted.
    # key_0 was accessed by _cache_get above (moved to end), so key_1 is the oldest.
    _cache_put("key_new", "value_new")
    assert _cache_get("key_new") == "value_new"
    assert _cache_get("key_1") is None  # evicted


def test_cache_ttl_expires_entries():
    """Entries older than _CACHE_TTL_SECONDS should be treated as cache misses."""
    invalidate_query_cache()
    _cache_put("ttl_key", "ttl_value")
    assert _cache_get("ttl_key") == "ttl_value"

    # Simulate time advancing past TTL
    import time as _time

    with patch("servicenow_mcp.tools.sn_api.time") as mock_time:
        mock_time.monotonic.return_value = _time.monotonic() + _CACHE_TTL_SECONDS + 1
        assert _cache_get("ttl_key") is None  # expired


def test_cache_move_to_end_on_access():
    """Accessing a cached entry should move it to the end (most-recently-used)."""
    invalidate_query_cache()
    _cache_put("first", 1)
    _cache_put("second", 2)
    # Access "first" — moves it to end
    _cache_get("first")
    # Now "second" is oldest; fill until eviction
    for i in range(_CACHE_MAX_ENTRIES - 2):
        _cache_put(f"fill_{i}", i)
    _cache_put("trigger_evict", "x")
    # "second" should be evicted (it was oldest), "first" survives
    assert _cache_get("first") == 1
    assert _cache_get("second") is None


def test_cache_update_existing_key():
    """Updating an existing key should refresh its value and position."""
    invalidate_query_cache()
    _cache_put("key_a", "old_value")
    _cache_put("key_a", "new_value")
    assert _cache_get("key_a") == "new_value"


# ---------------------------------------------------------------------------
# json_fast serialization tests
# ---------------------------------------------------------------------------


def test_json_fast_loads_and_dumps():
    from servicenow_mcp.utils import json_fast

    data = {"key": "value", "nested": [1, 2, 3]}
    serialized = json_fast.dumps(data)
    deserialized = json_fast.loads(serialized)
    assert deserialized == data
    # Compact: no spaces after separators
    assert " " not in serialized or json_fast.BACKEND == "json"


def test_json_fast_backend_available():
    from servicenow_mcp.utils import json_fast

    # Backend must be either orjson (preferred) or json (fallback)
    assert json_fast.BACKEND in ("orjson", "json")


def test_serialize_tool_output_compact_string_passthrough():
    from servicenow_mcp.server import serialize_tool_output

    compact = '{"key":"value","count":1}'
    result = serialize_tool_output(compact, "test_tool")
    assert result == compact  # no re-parse needed


def test_serialize_tool_output_recompacts_whitespace_json():
    from servicenow_mcp.server import serialize_tool_output

    spaced = '{ "key" : "value" ,\n "count" : 1}'
    result = serialize_tool_output(spaced, "test_tool")
    assert "\n" not in result
    assert " : " not in result


def test_sn_health_treats_browser_probe_acl_failure_as_authenticated_warning():
    invalidate_query_cache()
    config = ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(
            type=AuthType.BROWSER,
            browser=BrowserAuthConfig(probe_path="/api/now/table/incident?sysparm_limit=1"),
        ),
    )
    auth_manager = MagicMock()
    response = MagicMock()
    response.status_code = 403
    response.headers = {}
    response.url = "https://example.service-now.com/api/now/table/incident"
    response.is_redirect = False
    response.json.return_value = {"error": {"message": "forbidden"}}
    auth_manager.make_request.return_value = response

    result = sn_health(config, auth_manager, HealthCheckParams())

    assert result["ok"] is True
    assert result["status_code"] == 403
    assert "warning" in result
