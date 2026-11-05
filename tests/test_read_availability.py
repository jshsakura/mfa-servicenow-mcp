"""Every shared read says what the TOOL established, so the model never interprets a 403.

Measured on a lab instance with an under-privileged session: a 403 on a table
looked the same as "plugin not installed", a role list counted 6 and returned 5
(the hidden row was not mentioned), and a lookup of one role by sys_id counted 1
and returned 0 — which read as "no such role". Each test below pins one state
of the verdict: present / empty / hidden / forbidden / undetermined / absent.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from servicenow_mcp.tools import sn_api
from servicenow_mcp.tools.sn_api import (
    AggregateParams,
    DiscoverParams,
    GenericQueryParams,
    SchemaParams,
    _row_visibility,
    invalidate_query_cache,
    sn_aggregate,
    sn_discover,
    sn_query,
    sn_schema,
)
from servicenow_mcp.utils.capabilities import _domains, domain_for_table, forget_features
from servicenow_mcp.utils.config import AuthConfig, AuthType, BrowserAuthConfig, ServerConfig
from servicenow_mcp.utils.query_fields import forget_columns

TABLE = "x_myapp_item"


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
    forget_features()
    yield
    invalidate_query_cache()
    forget_columns()
    forget_features()


def _response(status=200, result=None, total=None, body=None):
    resp = MagicMock()
    resp.status_code = status
    payload = body if body is not None else {"result": result if result is not None else []}
    resp.content = json.dumps(payload).encode()
    resp.json.return_value = payload
    resp.text = resp.content.decode()
    resp.headers = {"X-Total-Count": str(total)} if total is not None else {}
    if status >= 400:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"HTTP Error {status}", response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _server(*, read_status=200, rows=(), total=None, catalog="registered"):
    """A fake instance. ``catalog``: registered / missing / unreadable."""

    def handler(method, url, params=None, **_):
        params = params or {}
        if url.endswith("/sys_db_object"):
            if catalog == "unreadable":
                return _response(403, body={"error": {"message": "User Not Authorized"}})
            query = params.get("sysparm_query", "")
            if query.startswith("name="):
                return _response(200, [{"name": query[5:]}] if catalog == "registered" else [])
            return _response(200, [])
        if url.endswith(f"/{TABLE}") or url.endswith(f"/stats/{TABLE}"):
            if read_status != 200:
                return _response(read_status, body={"error": {"message": "denied"}})
            return _response(200, list(rows), total=total)
        return _response(200, [])

    auth = MagicMock()
    auth.make_request.side_effect = handler
    return auth


def _rows(n):
    return [{"sys_id": f"aaaa{i:04d}bbbb2222cccc3333dddd4444"[:32]} for i in range(n)]


def _query(config, auth, **kwargs):
    kwargs.setdefault("table", TABLE)
    kwargs.setdefault("fields", "sys_id")
    return sn_query(config, auth, GenericQueryParams(**kwargs))


class TestFailedRead:
    def test_403_on_a_real_table_with_real_fields_is_forbidden(self, config):
        auth = _server(read_status=403)
        with patch.object(sn_api, "unknown_query_fields", return_value=[]):
            result = _query(config, auth, query="active=true")
        assert result["availability"] == "forbidden"
        assert "fresh login" in result["because"]

    def test_403_with_unchecked_fields_is_not_called_acl(self, config):
        # On a scoped table a column it lacks also answers 403. With the field
        # check unable to run, "forbidden" would be a guess.
        auth = _server(read_status=403)
        with patch.object(sn_api, "unknown_query_fields", return_value=None):
            result = _query(config, auth, query="active=true")
        assert result["availability"] == "undetermined"
        assert "could not be checked" in result["because"]

    def test_unreadable_catalog_is_undetermined_never_absent(self, config):
        auth = _server(read_status=403, catalog="unreadable")
        result = _query(config, auth, query="")
        assert result["availability"] == "undetermined"
        assert result.get("error") != "unknown_table"
        assert "not installed, not permitted" in result["because"]

    def test_proven_absence_is_absent(self, config):
        auth = _server(read_status=400, catalog="missing")
        result = _query(config, auth, query="")
        assert result["error"] == "unknown_table"
        assert result["availability"] == "absent"

    def test_other_4xx_on_a_real_table_names_the_status(self, config):
        auth = _server(read_status=400)
        result = _query(config, auth, query="")
        assert result["availability"] == "undetermined"
        assert "HTTP 400" in result["because"]

    def test_401_is_left_to_the_reauth_path(self, config):
        auth = _server(read_status=401)
        result = _query(config, auth, query="")
        assert "availability" not in result

    def test_network_failure_carries_no_verdict(self, config):
        auth = MagicMock()
        auth.make_request.side_effect = requests.exceptions.ConnectionError("down")
        result = _query(config, auth, query="")
        assert result["success"] is False and "availability" not in result


class TestRowVisibility:
    def test_a_short_page_under_a_larger_count_names_the_hidden_rows(self, config):
        # The lab case: 6 counted, 5 returned.
        auth = _server(rows=_rows(5), total=6)
        result = _query(config, auth, include_count=True, limit=20)
        assert result["rows_hidden_by_acl"] == 1
        assert "empty" not in result

    def test_all_rows_hidden_says_they_exist(self, config):
        # The lab case: a role looked up by sys_id, 1 counted, 0 returned.
        auth = _server(rows=[], total=1)
        result = _query(config, auth, include_count=True, limit=20)
        assert result["rows_hidden_by_acl"] == 1
        assert "EXIST" in result["hint"]
        assert "empty" not in result

    def test_a_full_page_proves_nothing_about_hiding(self, config):
        auth = _server(rows=_rows(20), total=100)
        result = _query(config, auth, include_count=True, limit=20)
        assert "rows_hidden_by_acl" not in result

    def test_a_server_count_of_zero_is_empty(self, config):
        auth = _server(rows=[], total=0)
        result = _query(config, auth, include_count=True)
        assert result["availability"] == "present" and result["empty"] is True

    def test_zero_rows_without_a_count_is_not_called_empty(self, config):
        auth = _server(rows=[])
        result = _query(config, auth, include_count=False)
        assert result["hidden_rows"] == "not_checked"
        assert "empty" not in result

    def test_a_count_header_nobody_asked_for_is_not_a_server_count(self, config):
        # Measured: the header arrives under sysparm_no_count too, carrying the
        # page size rather than the total. Trusting it printed `empty` on a guess.
        auth = _server(rows=[], total=0)
        result = _query(config, auth, include_count=False)
        assert "empty" not in result
        assert result["hidden_rows"] == "not_checked"

    def test_a_normal_read_carries_no_extra_keys(self, config):
        auth = _server(rows=_rows(4), total=4)
        result = _query(config, auth, include_count=True)
        assert not {"availability", "empty", "rows_hidden_by_acl", "hidden_rows"} & set(result)

    @pytest.mark.parametrize(
        "total,offset,returned,limit,expected",
        [
            (30, 20, 10, 20, {}),  # last page, nothing hidden
            (5, 10, 0, 20, {}),  # offset past the end is not hiding
            (6, 0, 5, 5, {}),  # full page: the sixth may be the next page
            (None, 0, 3, 20, {}),  # no count, rows came back: nothing to say
            # The ACL is applied per page. Measured on sys_security_acl, total
            # 1,623, limit 30: pages of 29 and 28. Only the missing part of the
            # window is hidden; the rest is on pages nobody read.
            (1623, 0, 29, 30, {"rows_hidden_by_acl": 1, "later_pages": "not_checked"}),
            (1623, 30, 28, 30, {"rows_hidden_by_acl": 2, "later_pages": "not_checked"}),
            (35, 30, 4, 30, {"rows_hidden_by_acl": 1}),  # last page, short by one
        ],
    )
    def test_visibility_edges(self, total, offset, returned, limit, expected):
        assert _row_visibility(total, offset, returned, limit) == expected


class TestOtherReads:
    def test_aggregate_403_is_forbidden(self, config):
        auth = _server(read_status=403)
        with patch.object(sn_api, "unknown_query_fields", return_value=[]):
            result = sn_aggregate(config, auth, AggregateParams(table=TABLE, query="active=true"))
        assert result["availability"] == "forbidden"

    def test_aggregate_zero_is_present_but_not_empty(self, config):
        # Whether the stats API counts ACL-withheld rows is not measured.
        auth = MagicMock()
        auth.make_request.return_value = _response(200, body={"result": {"stats": {"count": "0"}}})
        with patch.object(sn_api, "unknown_query_fields", return_value=[]):
            result = sn_aggregate(config, auth, AggregateParams(table=TABLE))
        assert result["availability"] == "present"
        assert result["hidden_rows"] == "not_checked"
        assert "empty" not in result

    def test_discover_on_an_unreadable_catalog_is_undetermined(self, config):
        auth = _server(catalog="unreadable")
        result = sn_discover(config, auth, DiscoverParams(keyword="sn_hamp"))
        assert result["success"] is False
        assert result["availability"] == "undetermined"

    def test_schema_on_an_unreadable_dictionary_is_undetermined(self, config):
        auth = MagicMock()
        auth.make_request.return_value = _response(403, body={"error": {"message": "denied"}})
        result = sn_schema(config, auth, SchemaParams(table=TABLE))
        assert result["success"] is False
        assert result["availability"] == "undetermined"


def _feature_server(
    table,
    *,
    table_registered,
    read_rows=(),
    plugins=None,
    apps=None,
    catalog_status=200,
):
    """A fake instance for feature verdicts.

    ``plugins`` / ``apps``: {id: active-string}. ``catalog_status`` != 200 makes
    v_plugin and sys_store_app unreadable (a Basic-auth or under-roled session).
    """
    calls = []

    def handler(method, url, params=None, **_):
        params = params or {}
        calls.append(url.rsplit("/", 1)[-1])
        if url.endswith("/v_plugin") or url.endswith("/sys_store_app"):
            if catalog_status != 200:
                return _response(catalog_status, body={"error": {"message": "denied"}})
            source, key = (plugins, "id") if url.endswith("/v_plugin") else (apps, "scope")
            return _response(200, [{key: k, "active": v} for k, v in (source or {}).items()])
        if url.endswith("/sys_db_object"):
            query = params.get("sysparm_query", "")
            if query.startswith("name="):
                return _response(200, [{"name": table}] if table_registered else [])
            return _response(200, [{"name": "sysevent_alert"}])
        if url.endswith(f"/{table}"):
            if not table_registered:
                return _response(400, body={})
            return _response(200, list(read_rows), total=len(read_rows))
        return _response(200, [])

    auth = MagicMock()
    auth.make_request.side_effect = handler
    return auth, calls


class TestFeatureVerdict:
    """Not installed vs not permitted vs a typo — the tool decides, from what it read."""

    def test_missing_table_of_an_off_feature_is_not_installed_not_a_typo(self, config):
        # The lab case: em_alert, Event Management off, and the old answer
        # suggested sysevent_alert.
        auth, _ = _feature_server(
            "em_alert", table_registered=False, plugins={"com.snc.service-watch": "inactive"}
        )
        result = _query(config, auth, table="em_alert", fields="number")
        assert result["error"] == "feature_not_installed"
        assert result["availability"] == "not_installed"
        assert result["feature"]["state"] == "absent"
        assert "did_you_mean" not in result
        assert "Not a typo and not a permission problem" in result["message"]

    def test_unreadable_table_catalog_still_answers_from_the_plugin(self, config):
        # sys_db_object refused, v_plugin readable and off: the feature answers it.
        def handler(method, url, params=None, **_):
            if url.endswith("/v_plugin"):
                return _response(200, [{"id": "com.snc.service-watch", "active": "inactive"}])
            return _response(403, body={"error": {"message": "User Not Authorized"}})

        auth = MagicMock()
        auth.make_request.side_effect = handler
        result = _query(config, auth, table="em_alert", fields="number")
        assert result["availability"] == "not_installed"

    def test_not_installed_drops_row_level_qualifiers(self, config):
        auth = MagicMock()

        def handler(method, url, params=None, **_):
            if url.endswith("/v_plugin"):
                return _response(200, [{"id": "com.snc.service-mapping", "active": "inactive"}])
            return _response(200, body={"result": {"stats": {"count": "0"}}})

        auth.make_request.side_effect = handler
        with patch.object(sn_api, "unknown_query_fields", return_value=[]):
            result = sn_aggregate(config, auth, AggregateParams(table="sa_m2m_service_entry_point"))
        assert result["availability"] == "not_installed"
        assert "hidden_rows" not in result

    def test_unreadable_plugin_catalog_keeps_the_feature_open(self, config):
        auth, _ = _feature_server("em_alert", table_registered=False, catalog_status=403)
        result = _query(config, auth, table="em_alert", fields="number")
        assert result["error"] == "unknown_table"
        assert result["feature"]["state"] == "undetermined"
        assert "may simply not be installed" in result["hint"]

    def test_missing_table_of_an_installed_feature_is_a_typo(self, config):
        auth, _ = _feature_server(
            "em_alertz", table_registered=False, plugins={"com.snc.service-watch": "active"}
        )
        result = _query(config, auth, table="em_alertz", fields="number")
        assert result["error"] == "unknown_table"
        assert "feature" not in result

    def test_app_scoped_feature_reads_sys_store_app(self, config):
        auth, calls = _feature_server(
            "sn_hamp_nope", table_registered=False, apps={"sn_hamp": "true"}
        )
        result = _query(config, auth, table="sn_hamp_nope", fields="number")
        assert result["error"] == "unknown_table"
        assert "sys_store_app" in calls

    def test_present_table_of_an_off_feature_is_not_installed(self, config):
        # The lab case: discovery_status exists with Discovery off; the old
        # answer was `present, empty`.
        auth, _ = _feature_server(
            "discovery_status",
            table_registered=True,
            plugins={"com.snc.itom.discovery.license": "inactive"},
        )
        result = _query(config, auth, table="discovery_status", fields="number", include_count=True)
        assert result["success"] is True
        assert result["availability"] == "not_installed"
        assert "empty" not in result
        assert "say nothing about Discovery" in result["hint"]

    def test_present_table_of_an_on_feature_carries_nothing(self, config):
        auth, _ = _feature_server(
            "discovery_status",
            table_registered=True,
            read_rows=_rows(2),
            plugins={"com.snc.discovery": "active"},
        )
        result = _query(config, auth, table="discovery_status", fields="sys_id", include_count=True)
        assert "feature" not in result and "availability" not in result

    def test_a_table_no_feature_owns_costs_no_lookup(self, config):
        auth = _server(rows=_rows(2), total=2)
        _query(config, auth, include_count=True)
        urls = [c.args[1] for c in auth.make_request.call_args_list]
        assert not any("v_plugin" in u or "sys_store_app" in u for u in urls)

    def test_off_is_reread_every_time_on_is_remembered(self, config):
        off, off_calls = _feature_server(
            "em_alert", table_registered=False, plugins={"com.snc.service-watch": "inactive"}
        )
        _query(config, off, table="em_alert", fields="number")
        _query(config, off, table="em_alert", fields="number")
        assert off_calls.count("v_plugin") == 2

        on, on_calls = _feature_server(
            "em_alertz", table_registered=False, plugins={"com.snc.service-watch": "active"}
        )
        _query(config, on, table="em_alertz", fields="number")
        invalidate_query_cache()
        _query(config, on, table="em_alertz", fields="number")
        assert on_calls.count("v_plugin") == 1


class TestCapabilityMap:
    def test_every_domain_names_tables_and_a_way_to_check_them(self):
        domains = _domains()
        assert domains, "capabilities.yaml did not load"
        for key, spec in domains.items():
            assert spec.get("tables"), key
            assert spec.get("plugins") or spec.get("apps"), key

    @pytest.mark.parametrize(
        "table,domain",
        [
            ("em_alert", "event_management"),
            ("discovery_status", "discovery"),
            ("ecc_agent", "discovery"),
            ("ecc_queue", None),  # exact names do not act as prefixes
            ("sn_hamp_asset_audit", "ham_pro"),
            ("alm_hardware", None),  # base asset management is not an optional feature
        ],
    )
    def test_domain_for_table(self, table, domain):
        assert domain_for_table(table) == domain
