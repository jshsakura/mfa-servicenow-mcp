"""Tests for portal developer productivity tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_dev_tools import (
    GetDeveloperChangesParams,
    GetDeveloperDailySummaryParams,
    GetProviderDependencyMapParams,
    GetUncommittedChangesParams,
    _compact_record,
    _escape_query,
    _extract_si_refs,
    _sn_get,
    get_developer_changes,
    get_developer_daily_summary,
    get_provider_dependency_map,
    get_uncommitted_changes,
)
from servicenow_mcp.tools.sn_api import invalidate_query_cache


@pytest.fixture(autouse=True)
def _clear_query_cache():
    """These tests pin exact make_request sequences, and the shared query cache
    is keyed by table+query+limit — so two tests that ask the same thing would
    otherwise let the second one pass on the first one's rows."""
    invalidate_query_cache()
    yield
    invalidate_query_cache()


@pytest.fixture(autouse=True)
def _stub_provider_m2m_resolver():
    """The provider junction table is discovered against the live instance at
    runtime; stub it to a fixed name in unit tests so discovery round-trips do
    not perturb exact make_request/_sn_get mock sequences. The resolver's own
    logic is covered in tests/test_provider_m2m_resolver.py."""
    import servicenow_mcp.tools.portal_dev_tools as _pdt

    _pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()
    with patch.object(_pdt, "resolve_angular_provider_m2m", return_value="m2m_sp_ng_pro_sp_widget"):
        yield
    _pdt._ANGULAR_PROVIDER_M2M_RESOLVED.clear()


def _make_config():
    config = MagicMock()
    config.instance_url = "https://test.service-now.com"
    config.timeout = 30
    return config


def _make_auth():
    return MagicMock()


def _mock_response(data, status=200, total_count=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.content = json.dumps(data).encode("utf-8")
    resp.raise_for_status.return_value = None
    resp.headers = {}
    if total_count is not None:
        resp.headers["X-Total-Count"] = str(total_count)
    return resp


def _mock_stats_response(count):
    return _mock_response({"result": {"stats": {"count": str(count)}}})


class TestHelpers:
    def test_escape_query(self):
        assert _escape_query("user@company.co.kr") == r"user\@company.co.kr"
        assert _escape_query("a^b=c") == r"a^^b\=c"

    def test_compact_record_strips_empty_and_flattens_display_value(self):
        record = {
            "sys_id": "abc123",
            "name": "MyWidget",
            "empty_field": "",
            "null_field": None,
            "sys_scope": {"display_value": "x_company_app", "value": "scope_id"},
        }
        result = _compact_record(record)
        assert result == {
            "sys_id": "abc123",
            "name": "MyWidget",
            "sys_scope": "x_company_app",
        }

    def test_compact_record_keeps_non_empty_values(self):
        record = {"a": "hello", "b": 0, "c": False}
        result = _compact_record(record)
        assert result == {"a": "hello", "b": 0, "c": False}

    def test_extract_si_refs(self):
        script = """
        var gr = new GlideRecord('incident');
        var helper = new MyCustomHelper();
        var util = new global.SomeUtil();
        """
        refs = _extract_si_refs(script)
        assert "MyCustomHelper" in refs
        assert "SomeUtil" in refs
        assert "GlideRecord" not in refs

    def test_extract_si_refs_empty(self):
        assert _extract_si_refs("") == []
        assert _extract_si_refs(None) == []

    def test_extract_si_refs_no_duplicates(self):
        script = "var a = new Foo(); var b = new Foo();"
        assert _extract_si_refs(script) == ["Foo"]


class TestGetDeveloperChanges:
    def test_repeated_fetch_reuses_shared_query_cache(self):
        config = _make_config()
        auth = _make_auth()
        invalidate_query_cache()

        widget_rows = [{"sys_id": "w1", "name": "Widget1", "sys_updated_on": "2026-03-31"}]
        # One page read serves the whole first call (its X-Total-Count is the
        # total); the second call is answered entirely from the query cache.
        auth.make_request.side_effect = [
            _mock_response({"result": widget_rows}, total_count=1),
        ]

        params = GetDeveloperChangesParams(
            developer="admin@example.com",
            source_types=["widget"],
            limit_per_table=5,
        )

        first = get_developer_changes(config, auth, params)
        second = get_developer_changes(config, auth, params)

        assert first["success"] is True
        assert second["success"] is True
        assert first["results"]["widget"]["items"] == second["results"]["widget"]["items"]
        assert first["results"]["widget"]["total_count"] == 1
        assert first["api_calls_made"] == 1
        assert auth.make_request.call_count == 1

    def test_count_only_mode(self):
        config = _make_config()
        auth = _make_auth()

        # Mock: 3 source types × 1 count call each = 3 API calls
        auth.make_request.side_effect = [
            _mock_stats_response(5),  # widget count
            _mock_stats_response(3),  # angular_provider count
            _mock_stats_response(10),  # script_include count
        ]

        params = GetDeveloperChangesParams(
            developer="admin@example.com",
            count_only=True,
        )
        result = get_developer_changes(config, auth, params)

        assert result["success"] is True
        assert result["total_items"] == 18  # 5 + 3 + 10
        assert result["api_calls_made"] == 3
        # In count_only mode, no "items" key should be present
        for stype_data in result["results"].values():
            assert "items" not in stype_data

    def test_fetch_mode_with_cost_warning(self):
        config = _make_config()
        auth = _make_auth()

        widget_rows = [
            {"sys_id": f"w{i}", "name": f"Widget{i}", "sys_updated_on": "2026-03-31"}
            for i in range(20)
        ]

        # One read per source type — the page's X-Total-Count carries the total,
        # so a table with more rows than the limit still warns without a count query.
        auth.make_request.side_effect = [
            _mock_response({"result": widget_rows}, total_count=100),  # 20 of 100
            _mock_response({"result": []}, total_count=0),  # angular_provider
            _mock_response({"result": [{"sys_id": "s1", "name": "SI1"}]}, total_count=2),
        ]

        params = GetDeveloperChangesParams(
            developer="admin@example.com",
            limit_per_table=20,
        )
        result = get_developer_changes(config, auth, params)

        assert result["success"] is True
        assert "cost_warnings" in result
        assert any("100 records found" in w for w in result["cost_warnings"])
        assert result["results"]["widget"]["total_count"] == 100
        assert result["results"]["angular_provider"]["items"] == []
        assert result["api_calls_made"] == 3
        assert auth.make_request.call_count == 3

    def test_a_full_page_without_the_header_falls_back_to_a_count(self):
        """Only the header-less instance pays for the extra round trip."""
        config = _make_config()
        auth = _make_auth()

        rows = [{"sys_id": f"w{i}", "name": f"Widget{i}"} for i in range(5)]
        auth.make_request.side_effect = [
            _mock_response({"result": rows}),  # full page, header suppressed
            _mock_stats_response(80),  # fallback count
        ]

        params = GetDeveloperChangesParams(
            developer="admin@example.com",
            source_types=["widget"],
            limit_per_table=5,
        )
        result = get_developer_changes(config, auth, params)

        assert result["success"] is True
        assert result["results"]["widget"]["total_count"] == 80
        assert result["results"]["widget"]["count"] == 5
        assert any("80 records found" in w for w in result["cost_warnings"])
        assert result["api_calls_made"] == 2

    def test_a_short_page_without_the_header_needs_no_count(self):
        """A page shorter than the limit IS the whole result — nothing to count."""
        config = _make_config()
        auth = _make_auth()

        auth.make_request.side_effect = [
            _mock_response({"result": [{"sys_id": "w1", "name": "Widget1"}]}),
        ]

        params = GetDeveloperChangesParams(
            developer="admin@example.com",
            source_types=["widget"],
            limit_per_table=5,
        )
        result = get_developer_changes(config, auth, params)

        assert result["success"] is True
        assert result["results"]["widget"]["total_count"] == 1
        assert result["api_calls_made"] == 1
        assert "cost_warnings" not in result

    def test_unknown_source_type_produces_error(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_stats_response(0)

        params = GetDeveloperChangesParams(
            developer="test@test.com",
            source_types=["nonexistent_type"],
            count_only=True,
        )
        result = get_developer_changes(config, auth, params)
        assert "errors" in result
        assert any("Unknown source_type" in e for e in result["errors"])

    def test_filter_by_created_by(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.side_effect = [
            _mock_stats_response(0),
            _mock_stats_response(0),
            _mock_stats_response(0),
        ]

        params = GetDeveloperChangesParams(
            developer="test@test.com",
            filter_by="created_by",
            count_only=True,
        )
        result = get_developer_changes(config, auth, params)
        assert result["filter_by"] == "sys_created_by"


class TestGetUncommittedChanges:
    def test_no_update_sets_found(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_response({"result": []}, total_count=0)

        params = GetUncommittedChangesParams(developer="test@test.com")
        result = get_uncommitted_changes(config, auth, params)

        assert result["success"] is True
        assert result["total_entries"] == 0

    def test_count_only_mode(self):
        config = _make_config()
        auth = _make_auth()

        us_data = [{"sys_id": "us1", "name": "My Update Set", "state": "in progress"}]
        auth.make_request.side_effect = [
            _mock_response({"result": us_data}, total_count=1),  # update sets
            _mock_stats_response(15),  # entry count
        ]

        params = GetUncommittedChangesParams(
            developer="test@test.com",
            count_only=True,
        )
        result = get_uncommitted_changes(config, auth, params)

        assert result["success"] is True
        assert result["total_entries"] == 15
        assert "entries_by_update_set" not in result  # count_only doesn't fetch details

    def test_full_fetch_groups_by_update_set(self):
        config = _make_config()
        auth = _make_auth()

        us_data = [{"sys_id": "us1", "name": "US-Portal-Fix", "state": "in progress"}]
        entries = [
            {
                "target_name": "MyWidget",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "update_set": {"display_value": "US-Portal-Fix", "value": "us1"},
                "sys_updated_on": "2026-03-31 10:00:00",
                "sys_created_by": "test@test.com",
            },
        ]

        # Two reads, not three: the entry fetch's X-Total-Count is the total, so
        # the listing path no longer pays for a separate count of the same query.
        auth.make_request.side_effect = [
            _mock_response({"result": us_data}, total_count=1),
            _mock_response({"result": entries}, total_count=1),
        ]

        params = GetUncommittedChangesParams(developer="test@test.com")
        result = get_uncommitted_changes(config, auth, params)

        assert result["success"] is True
        assert "US-Portal-Fix" in result["entries_by_update_set"]
        assert len(result["entries_by_update_set"]["US-Portal-Fix"]) == 1
        assert result["total_entries"] == 1
        assert result["api_calls_made"] == 2
        assert auth.make_request.call_count == 2

    def test_full_fetch_counts_a_full_page_when_the_header_is_missing(self):
        """An instance that suppresses X-Total-Count still gets a true total.

        len(rows) is a lower bound once the page is full, and reporting it as
        the total would hide the "there are more" warning entirely.
        """
        config = _make_config()
        auth = _make_auth()

        us_data = [{"sys_id": "us1", "name": "US-Portal-Fix", "state": "in progress"}]
        entries = [
            {
                "target_name": f"Widget{i}",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "update_set": {"display_value": "US-Portal-Fix", "value": "us1"},
                "sys_updated_on": "2026-03-31 10:00:00",
            }
            for i in range(2)
        ]

        auth.make_request.side_effect = [
            _mock_response({"result": us_data}, total_count=1),
            _mock_response({"result": entries}),  # full page, no header
            _mock_stats_response(40),
        ]

        params = GetUncommittedChangesParams(developer="test@test.com", limit=2)
        result = get_uncommitted_changes(config, auth, params)

        assert result["success"] is True
        assert result["total_entries"] == 40
        assert result["returned_entries"] == 2
        assert any("40 entries found" in w for w in result["cost_warnings"])
        assert result["api_calls_made"] == 3


class TestGetProviderDependencyMap:
    def test_requires_at_least_one_filter(self):
        config = _make_config()
        auth = _make_auth()

        params = GetProviderDependencyMapParams()
        result = get_provider_dependency_map(config, auth, params)

        assert result["success"] is False
        assert "required" in result["message"].lower()

    def test_no_widgets_found(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.side_effect = [
            _mock_response({"result": []}, total_count=0),  # widget fetch
        ]

        params = GetProviderDependencyMapParams(developer="test@test.com")
        result = get_provider_dependency_map(config, auth, params)

        assert result["success"] is True
        assert result["widget_count"] == 0
        assert result["api_calls_made"] == 1  # the fetch alone answers "none match"

    def test_maps_widget_to_providers(self):
        config = _make_config()
        auth = _make_auth()

        widgets = [
            {
                "sys_id": "w1",
                "name": "TestWidget",
                "id": "test-widget",
                "script": "var x = new MyHelper();",
            }
        ]
        m2m_rows = [{"sp_widget": {"value": "w1"}, "sp_angular_provider": {"value": "p1"}}]
        providers = [
            {"sys_id": "p1", "name": "TestProvider", "script": "var h = new AnotherHelper();"}
        ]
        si_rows = [
            {"sys_id": "si1", "name": "MyHelper", "api_name": "global.MyHelper"},
            {"sys_id": "si2", "name": "AnotherHelper", "api_name": "global.AnotherHelper"},
        ]

        # The widget fetch's X-Total-Count is the match count — no count query.
        auth.make_request.side_effect = [
            _mock_response({"result": widgets}, total_count=1),  # widget fetch
            _mock_response({"result": m2m_rows}, total_count=1),  # M2M
            _mock_response({"result": providers}, total_count=1),  # provider fetch
            _mock_response({"result": si_rows}, total_count=2),  # SI resolve
        ]

        params = GetProviderDependencyMapParams(
            widget_ids=["w1"],
            include_script_include_refs=True,
        )
        result = get_provider_dependency_map(config, auth, params)

        assert result["success"] is True
        assert result["summary"]["widgets"] == 1
        assert result["summary"]["providers"] == 1
        assert result["summary"]["script_include_refs"] == 2  # MyHelper + AnotherHelper
        assert result["summary"]["widgets_total"] == 1
        assert result["summary"]["api_calls"] == 4
        assert auth.make_request.call_count == 4

        dep = result["dependency_map"][0]
        assert dep["widget"]["name"] == "TestWidget"
        assert len(dep["providers"]) == 1
        assert dep["providers"][0]["name"] == "TestProvider"
        # Script bodies should be stripped from response
        assert "script" not in dep["widget"]

    def test_cost_warning_on_large_widget_set(self):
        config = _make_config()
        auth = _make_auth()

        widgets = [{"sys_id": f"w{i}", "name": f"W{i}"} for i in range(10)]
        auth.make_request.side_effect = [
            _mock_response({"result": widgets}, total_count=50),  # fetch 10 of 50
            _mock_response({"result": []}, total_count=0),  # M2M
        ]

        params = GetProviderDependencyMapParams(
            scope="x_company_app",
            max_widgets=10,
            include_script_include_refs=False,
        )
        result = get_provider_dependency_map(config, auth, params)

        assert result["success"] is True
        assert "cost_warnings" in result
        assert any("50 widgets" in w for w in result["cost_warnings"])
        assert result["summary"]["api_calls"] == 2


class TestGetDeveloperDailySummary:
    def test_jira_format_with_details(self):
        config = _make_config()
        auth = _make_auth()

        widget_rows = [
            {
                "sys_id": "w1",
                "name": "MyWidget",
                "id": "my-widget",
                "sys_scope": {"display_value": "x_app"},
                "sys_updated_on": "2026-03-31 10:30:00",
                "script": "function serverFn() {\n  var gr = new GlideRecord('incident');\n}",
                "client_script": "function clientFn() { console.log('hi'); }",
                "template": "<div>hello</div>",
                "css": "",
            },
        ]
        si_rows = [
            {
                "sys_id": "si1",
                "name": "MyHelper",
                "sys_scope": {"display_value": "x_app"},
                "sys_updated_on": "2026-03-31 14:00:00",
                "script": "var MyHelper = Class.create();\nMyHelper.prototype = {\n  doWork: function() {}\n};",
            },
        ]
        m2m_rows = [{"sp_widget": {"value": "w1"}, "sp_angular_provider": {"value": "p1"}}]
        provider_rows = [{"sys_id": "p1", "name": "myWidgetService"}]
        xml_rows = [
            {"target_name": "MyWidget", "action": "INSERT_OR_UPDATE", "name": "sp_widget"},
            {"target_name": "MyHelper", "action": "INSERT_OR_UPDATE", "name": "sys_script_include"},
        ]
        us_rows = [
            {
                "sys_id": "us1",
                "name": "US-Portal",
                "state": "in progress",
                "application": {"display_value": "x_app"},
            },
        ]

        auth.make_request.side_effect = [
            _mock_response({"result": widget_rows}, total_count=1),  # widget
            _mock_response({"result": []}, total_count=0),  # angular_provider
            _mock_response({"result": si_rows}, total_count=1),  # script_include
            _mock_response({"result": m2m_rows}, total_count=1),  # M2M
            _mock_response({"result": provider_rows}, total_count=1),  # provider names
            _mock_response({"result": xml_rows}, total_count=2),  # update_xml
            _mock_response({"result": us_rows}, total_count=1),  # update sets
        ]

        params = GetDeveloperDailySummaryParams(
            developer="admin@example.com",
            date="2026-03-31",
            output_format="jira",
            include_details=True,
        )
        result = get_developer_daily_summary(config, auth, params)

        assert result["success"] is True
        assert result["total_changes"] == 2
        md = result["jira_markdown"]
        assert "MyWidget" in md
        assert "MyHelper" in md
        assert "INSERT_OR_UPDATE" in md
        assert "myWidgetService" in md
        assert "script:" in md  # field line count

    def test_plain_format_no_details(self):
        config = _make_config()
        auth = _make_auth()

        auth.make_request.side_effect = [
            _mock_response(
                {
                    "result": [
                        {"sys_id": "w1", "name": "W1", "sys_updated_on": "2026-03-31 09:00:00"}
                    ]
                },
                total_count=1,
            ),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),  # update sets
        ]

        params = GetDeveloperDailySummaryParams(
            developer="test@test.com",
            date="2026-03-31",
            output_format="plain",
            include_details=False,
        )
        result = get_developer_daily_summary(config, auth, params)

        assert result["success"] is True
        assert "plain_text" in result
        assert "W1" in result["plain_text"]

    def test_structured_format_empty(self):
        config = _make_config()
        auth = _make_auth()

        auth.make_request.side_effect = [
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),  # update_xml (no items so skipped)
            _mock_response({"result": []}, total_count=0),  # update sets
        ]

        params = GetDeveloperDailySummaryParams(
            developer="test@test.com",
            date="2026-03-31",
            output_format="structured",
        )
        result = get_developer_daily_summary(config, auth, params)

        assert result["success"] is True
        assert "categories" in result
        assert result["total_changes"] == 0

    def test_no_update_sets_when_disabled(self):
        config = _make_config()
        auth = _make_auth()

        auth.make_request.side_effect = [
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
        ]

        params = GetDeveloperDailySummaryParams(
            developer="test@test.com",
            date="2026-03-31",
            include_update_sets=False,
            include_details=False,
            output_format="structured",
        )
        result = get_developer_daily_summary(config, auth, params)

        assert result["success"] is True
        assert result["api_calls_made"] == 3


class TestReferenceKeysAreReadRaw:
    """A reference used as a map KEY has to be a sys_id, not its label.

    `_sn_get` asks for display values, which most callers here want — they render
    names to a human. The widget↔provider join does not: it keys
    `widget_provider_map` by `sp_widget` and then looks it up by the widget's
    sys_id. With display values on, the key was 'myWidgetA' and the
    lookup was a sys_id, so every join missed.

    Live, that made `manage_widget_dependency` answer with `summary.providers: 9`
    and `providers: []` on the same widget in the same response — a count from the
    ids it collected, and an empty list from the join that could never match. The
    follow-up detail read then queried `sys_idIN<provider NAMES>`.

    No mock could see it: a fixture returns whatever shape it was written with, so
    both spellings of a reference look identical in tests. What is pinned here is
    the REQUEST — that this call asks for raw values — because that is the part
    the server's answer depends on.
    """

    def _call_kwargs(self, mock_page):
        return [c.kwargs for c in mock_page.call_args_list]

    @patch("servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared")
    def test_sn_get_still_defaults_to_display_values(self, mock_page):
        mock_page.return_value = ([], 0)
        _sn_get(MagicMock(), MagicMock(), "sp_widget", "", "sys_id,name")
        assert self._call_kwargs(mock_page)[0]["display_value"] is True

    @patch("servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared")
    def test_raw_values_are_requestable(self, mock_page):
        mock_page.return_value = ([], 0)
        _sn_get(MagicMock(), MagicMock(), "m2m", "", "sp_widget", display_value=False)
        assert self._call_kwargs(mock_page)[0]["display_value"] is False

    def test_both_widget_provider_joins_ask_for_raw_values(self):
        """Source-level: every m2m join selecting sp_widget must pass raw.

        Asserted on the source because the two joins sit behind live discovery
        and paging that a unit test would have to fake wholesale — and faking it
        is exactly what hid the bug.
        """
        import inspect

        from servicenow_mcp.tools import portal_dev_tools

        source = inspect.getsource(portal_dev_tools)
        joins = [
            block
            for block in source.split("_sn_get(")[1:]
            if "sp_angular_provider" in block[:400] and "sp_widget" in block[:400]
        ]
        assert joins, "no widget<->provider join found — did the helper get renamed?"
        for block in joins:
            # Cut at the call's OWN closing paren: nested calls like
            # '",".join(id_chunk)' carry one of their own, and stopping at the
            # first ')' truncated the call before its keyword arguments.
            depth, end = 1, len(block)
            for idx, ch in enumerate(block):
                depth += (ch == "(") - (ch == ")")
                if depth == 0:
                    end = idx
                    break
            call = block[:end]
            assert "display_value=False" in call, f"join reads display values:\n{call}"
