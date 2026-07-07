from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.sn_api import (
    _CACHE_MAX_ENTRIES,
    _CACHE_TTL_SECONDS,
    GenericQueryParams,
    HealthCheckParams,
    _authenticated_user,
    _cache_get,
    _cache_put,
    invalidate_query_cache,
    sn_health,
    sn_query,
)
from servicenow_mcp.utils.config import (
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    ServerConfig,
)


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


def _browser_cfg():
    return ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def _basic_cfg(username="admin"):
    return ServerConfig(
        instance_url="https://example.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username=username, password="pw"),
        ),
    )


def test_authenticated_user_basic_from_config_no_network():
    am = MagicMock()
    assert _authenticated_user(_basic_cfg("svc_prod"), am, allow_live=False) == "svc_prod"
    am.make_request.assert_not_called()  # identity is the configured user, no call


def test_authenticated_user_browser_live_asks_current_user():
    import servicenow_mcp.tools.sn_api as api

    api._LIVE_USER_CACHE.clear()
    am = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"result": {"user_name": "alice"}}
    am.make_request.return_value = resp
    assert _authenticated_user(_browser_cfg(), am, allow_live=True) == "alice"
    called_url = am.make_request.call_args[0][1]
    assert called_url.endswith("/api/now/ui/user/current_user")


def test_authenticated_user_browser_not_live_never_calls():
    # A dead session must not trigger a re-login from a health check.
    am = MagicMock()
    assert _authenticated_user(_browser_cfg(), am, allow_live=False) is None
    am.make_request.assert_not_called()


def test_authenticated_user_browser_live_failure_is_best_effort():
    import servicenow_mcp.tools.sn_api as api

    api._LIVE_USER_CACHE.clear()
    am = MagicMock()
    am.make_request.side_effect = RuntimeError("boom")
    assert _authenticated_user(_browser_cfg(), am, allow_live=True) is None


def test_sn_health_surfaces_browser_authenticated_user():
    import servicenow_mcp.tools.sn_api as api

    invalidate_query_cache()
    api._LIVE_USER_CACHE.clear()
    config = _browser_cfg()
    am = MagicMock()
    probe = MagicMock()
    probe.status_code = 200
    probe.headers = {}
    probe.url = "https://example.service-now.com/api/now/table/sys_user_preference"
    probe.is_redirect = False
    probe.json.return_value = {"result": [{"sys_id": "1"}]}
    current = MagicMock()
    current.json.return_value = {"result": {"user_name": "alice"}}
    am.make_request.side_effect = [probe, current]

    result = sn_health(config, am, HealthCheckParams())

    assert result["ok"] is True
    assert result["authenticated_user"] == "alice"


def _browser_cfg_for(url):
    return ServerConfig(
        instance_url=url,
        auth=AuthConfig(type=AuthType.BROWSER, browser=BrowserAuthConfig()),
    )


def test_resolve_live_username_caches_within_ttl():
    import servicenow_mcp.tools.sn_api as api

    api._LIVE_USER_CACHE.clear()
    cfg = _browser_cfg_for("https://cache.service-now.com")
    am = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"result": {"user_name": "alice"}}
    am.make_request.return_value = resp

    assert api.resolve_live_username(cfg, am) == "alice"
    assert api.resolve_live_username(cfg, am) == "alice"
    assert am.make_request.call_count == 1  # second call served from cache


def test_resolve_live_username_refetches_after_ttl(monkeypatch):
    import servicenow_mcp.tools.sn_api as api

    api._LIVE_USER_CACHE.clear()
    cfg = _browser_cfg_for("https://ttl.service-now.com")
    am = MagicMock()
    first = MagicMock()
    first.json.return_value = {"result": {"user_name": "alice"}}
    second = MagicMock()
    second.json.return_value = {"result": {"user_name": "bob"}}
    am.make_request.side_effect = [first, second]

    t = {"now": 1000.0}
    monkeypatch.setattr(api.time, "monotonic", lambda: t["now"])
    assert api.resolve_live_username(cfg, am) == "alice"
    t["now"] += api._LIVE_USER_TTL_SECONDS + 1  # expire
    assert api.resolve_live_username(cfg, am) == "bob"  # user switch reflected
    assert am.make_request.call_count == 2


def test_resolve_live_username_failure_returns_empty_uncached():
    import servicenow_mcp.tools.sn_api as api

    api._LIVE_USER_CACHE.clear()
    cfg = _browser_cfg_for("https://fail.service-now.com")
    am = MagicMock()
    am.make_request.side_effect = RuntimeError("down")
    assert api.resolve_live_username(cfg, am) == ""
    assert "https://fail.service-now.com" not in api._LIVE_USER_CACHE


def test_sync_resolve_current_user_delegates_to_shared():
    # sync_tools keeps its symbol but must route through the shared helper.
    import servicenow_mcp.tools.sn_api as api
    from servicenow_mcp.tools.sync_tools import _resolve_current_user

    api._LIVE_USER_CACHE.clear()
    cfg = _browser_cfg_for("https://deleg.service-now.com")
    am = MagicMock()
    resp = MagicMock()
    resp.json.return_value = {"result": {"user_name": "carol"}}
    am.make_request.return_value = resp
    assert _resolve_current_user(cfg, am) == "carol"
    assert api._LIVE_USER_CACHE["https://deleg.service-now.com"][0] == "carol"


# ---------------------------------------------------------------------------
# Auth failures must never be silenced into empty results (flow-list 0-rows bug):
# fail_silently=True may swallow transient/network errors, but "not logged in"
# and "0 rows" are different answers — auth errors always propagate.
# ---------------------------------------------------------------------------

_AUTH_ERROR_MESSAGES = [
    "Browser session expired — NOT authenticated for instance=x profile=y.",
    "LOGIN_CANCELLED_BY_USER (instance=x profile=y): window closed.",
    "LOGIN_COOLDOWN: previous browser login attempted 5.0s ago.",
]


def test_sn_query_page_raises_auth_errors_even_when_fail_silently():
    import pytest

    from servicenow_mcp.tools.sn_api import sn_query_page

    invalidate_query_cache()
    cfg = _browser_cfg_for("https://authfail.service-now.com")
    for msg in _AUTH_ERROR_MESSAGES:
        am = MagicMock()
        am.make_request.side_effect = ValueError(msg)
        with pytest.raises(ValueError, match="NOT authenticated|LOGIN_"):
            sn_query_page(cfg, am, table="incident", query="", fields="sys_id", limit=1, offset=0)


def test_sn_query_page_still_silences_non_auth_errors():
    from servicenow_mcp.tools.sn_api import sn_query_page

    invalidate_query_cache()
    cfg = _browser_cfg_for("https://neterr.service-now.com")
    am = MagicMock()
    am.make_request.side_effect = RuntimeError("connection reset")
    rows, total = sn_query_page(
        cfg, am, table="incident", query="", fields="sys_id", limit=1, offset=0
    )
    assert rows == [] and total is None


def test_sn_count_raises_auth_errors_but_returns_zero_otherwise():
    import pytest

    from servicenow_mcp.tools.sn_api import sn_count

    cfg = _browser_cfg_for("https://countfail.service-now.com")
    am = MagicMock()
    am.make_request.side_effect = ValueError(_AUTH_ERROR_MESSAGES[0])
    with pytest.raises(ValueError, match="NOT authenticated"):
        sn_count(cfg, am, "incident")

    am_net = MagicMock()
    am_net.make_request.side_effect = RuntimeError("timeout")
    assert sn_count(cfg, am_net, "incident") == 0
