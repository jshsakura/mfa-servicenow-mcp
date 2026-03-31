"""Tests for portal developer productivity tools."""

from unittest.mock import MagicMock

from servicenow_mcp.tools.portal_dev_tools import (
    GetDeveloperChangesParams,
    GetDeveloperDailySummaryParams,
    GetProviderDependencyMapParams,
    GetUncommittedChangesParams,
    _compact_record,
    _escape_query,
    _extract_si_refs,
    get_developer_changes,
    get_developer_daily_summary,
    get_provider_dependency_map,
    get_uncommitted_changes,
)


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
            developer="jeongsh@sorin.co.kr",
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

        auth.make_request.side_effect = [
            _mock_stats_response(100),  # widget count (large!)
            _mock_response({"result": widget_rows}, total_count=100),  # widget fetch
            _mock_stats_response(0),  # angular_provider count
            _mock_stats_response(2),  # script_include count
            _mock_response({"result": [{"sys_id": "s1", "name": "SI1"}]}, total_count=2),
        ]

        params = GetDeveloperChangesParams(
            developer="jeongsh@sorin.co.kr",
            limit_per_table=20,
        )
        result = get_developer_changes(config, auth, params)

        assert result["success"] is True
        assert "cost_warnings" in result
        assert any("100 records found" in w for w in result["cost_warnings"])

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

        auth.make_request.side_effect = [
            _mock_response({"result": us_data}, total_count=1),
            _mock_stats_response(1),
            _mock_response({"result": entries}, total_count=1),
        ]

        params = GetUncommittedChangesParams(developer="test@test.com")
        result = get_uncommitted_changes(config, auth, params)

        assert result["success"] is True
        assert "US-Portal-Fix" in result["entries_by_update_set"]
        assert len(result["entries_by_update_set"]["US-Portal-Fix"]) == 1


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
            _mock_stats_response(0),  # widget count
        ]

        params = GetProviderDependencyMapParams(developer="test@test.com")
        result = get_provider_dependency_map(config, auth, params)

        assert result["success"] is True
        assert result["widget_count"] == 0

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

        auth.make_request.side_effect = [
            _mock_stats_response(1),  # widget count
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
            _mock_stats_response(50),  # 50 widgets match
            _mock_response({"result": widgets}, total_count=50),  # fetch 10
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
            developer="jeongsh@sorin.co.kr",
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
