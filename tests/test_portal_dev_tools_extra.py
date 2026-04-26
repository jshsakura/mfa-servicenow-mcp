"""Extra tests for portal_dev_tools.py — targeting uncovered branches."""

import json
from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.portal_dev_tools import (
    GetDeveloperChangesParams,
    GetDeveloperDailySummaryParams,
    GetProviderDependencyMapParams,
    GetUncommittedChangesParams,
    _compact_record,
    _extract_script_profile,
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
    resp.content = json.dumps(data).encode("utf-8")
    resp.raise_for_status.return_value = None
    resp.headers = {}
    if total_count is not None:
        resp.headers["X-Total-Count"] = str(total_count)
    return resp


def _mock_stats_response(count):
    return _mock_response({"result": {"stats": {"count": str(count)}}})


class TestGetDeveloperChangesScopeAndFilters:
    def test_with_scope_filter(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_stats_response(0)

        result = get_developer_changes(
            config,
            auth,
            GetDeveloperChangesParams(
                developer="admin",
                scope="x_app",
                count_only=True,
            ),
        )
        assert result["success"] is True
        _, kwargs = auth.make_request.call_args
        assert "x_app" in kwargs["params"]["sysparm_query"]

    def test_with_date_range(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_stats_response(0)

        result = get_developer_changes(
            config,
            auth,
            GetDeveloperChangesParams(
                developer="admin",
                updated_after="2026-01-01",
                updated_before="2026-12-31",
                count_only=True,
            ),
        )
        assert result["success"] is True
        _, kwargs = auth.make_request.call_args
        assert "2026-01-01" in kwargs["params"]["sysparm_query"]

    def test_unknown_source_type(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_stats_response(0)

        result = get_developer_changes(
            config,
            auth,
            GetDeveloperChangesParams(
                developer="admin",
                source_types=["nonexistent"],
                count_only=True,
            ),
        )
        assert result["success"] is True
        assert len(result.get("errors", [])) == 1

    def test_fetch_exception(self):
        config = _make_config()
        auth = _make_auth()

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
            side_effect=Exception("API error"),
        ):
            result = get_developer_changes(
                config,
                auth,
                GetDeveloperChangesParams(
                    developer="admin",
                    source_types=["widget"],
                ),
            )
        assert result["success"] is True
        assert len(result.get("errors", [])) > 0

    def test_large_result_set_warning(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.side_effect = [
            _mock_stats_response(500),
            _mock_response({"result": [{"sys_id": "w1"}]}, total_count=500),
        ]

        result = get_developer_changes(
            config,
            auth,
            GetDeveloperChangesParams(
                developer="admin",
                source_types=["widget"],
            ),
        )
        assert result["success"] is True
        assert len(result.get("cost_warnings", [])) > 0

    def test_zero_results(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_stats_response(0)

        result = get_developer_changes(
            config,
            auth,
            GetDeveloperChangesParams(
                developer="admin",
                source_types=["widget"],
            ),
        )
        assert result["success"] is True
        assert result["results"]["widget"]["count"] == 0

    def test_filter_by_created_by(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_stats_response(0)

        result = get_developer_changes(
            config,
            auth,
            GetDeveloperChangesParams(
                developer="admin",
                filter_by="created_by",
                source_types=["widget"],
                count_only=True,
            ),
        )
        assert result["success"] is True
        assert result["filter_by"] == "sys_created_by"

    def test_multiple_source_types(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_stats_response(0)

        result = get_developer_changes(
            config,
            auth,
            GetDeveloperChangesParams(
                developer="admin",
                source_types=["widget", "angular_provider"],
                count_only=True,
            ),
        )
        assert result["success"] is True
        assert "widget" in result["results"]
        assert "angular_provider" in result["results"]

    def test_with_offset_and_limit_per_table(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.side_effect = [
            _mock_stats_response(2),
            _mock_response(
                {"result": [{"sys_id": "w1"}, {"sys_id": "w2"}]},
                total_count=2,
            ),
        ]

        result = get_developer_changes(
            config,
            auth,
            GetDeveloperChangesParams(
                developer="admin",
                source_types=["widget"],
                limit_per_table=5,
                offset=2,
            ),
        )
        assert result["success"] is True


class TestGetUncommittedChangesFilters:
    def test_with_scope_and_name(self):
        config = _make_config()
        auth = _make_auth()

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
            return_value=([], 0),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(
                    developer="admin",
                    scope="x_app",
                    update_set_name="My Set",
                ),
            )
        assert result["success"] is True

    def test_no_update_sets_found(self):
        config = _make_config()
        auth = _make_auth()

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
            return_value=([], 0),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(developer="admin"),
            )
        assert result["success"] is True
        assert result["total_entries"] == 0

    def test_update_set_query_error(self):
        config = _make_config()
        auth = _make_auth()

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
            side_effect=Exception("US query error"),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(developer="admin"),
            )
        assert result["success"] is False

    def test_count_only(self):
        config = _make_config()
        auth = _make_auth()

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                return_value=([{"sys_id": "us1", "name": "Test Set"}], 1),
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=5,
            ),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(
                    developer="admin",
                    count_only=True,
                ),
            )
        assert result["success"] is True
        assert result["total_entries"] == 5

    def test_zero_entries(self):
        config = _make_config()
        auth = _make_auth()

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                return_value=([{"sys_id": "us1", "name": "Test Set"}], 1),
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=0,
            ),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(developer="admin"),
            )
        assert result["success"] is True
        assert result["total_entries"] == 0

    def test_count_query_error(self):
        config = _make_config()
        auth = _make_auth()

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                return_value=([{"sys_id": "us1", "name": "Test Set"}], 1),
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                side_effect=Exception("count error"),
            ),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(developer="admin"),
            )
        assert result["success"] is False

    def test_with_multiple_update_sets(self):
        config = _make_config()
        auth = _make_auth()

        sets = [
            {"sys_id": "us1", "name": "Set 1"},
            {"sys_id": "us2", "name": "Set 2"},
        ]

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                return_value=(sets, 2),
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=3,
            ),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(
                    developer="admin",
                    count_only=True,
                ),
            )
        assert result["success"] is True
        assert result["total_entries"] == 3

    def test_count_only_with_cost_warning(self):
        """Lines 427, 442: cost_warnings when entry_count > safe_limit in count_only mode."""
        config = _make_config()
        auth = _make_auth()

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                return_value=([{"sys_id": "us1", "name": "Set1"}], 1),
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=5000,
            ),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(
                    developer="admin",
                    count_only=True,
                ),
            )
        assert result["success"] is True
        assert "cost_warnings" in result
        assert any("5000 entries" in w for w in result["cost_warnings"])

    def test_entry_fetch_exception(self):
        """Lines 468-469: exception during entry XML fetch."""
        config = _make_config()
        auth = _make_auth()
        call_count = [0]

        def _query_page_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ([{"sys_id": "us1", "name": "Set1"}], 1)
            raise Exception("XML fetch error")

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                side_effect=_query_page_side_effect,
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=5,
            ),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(developer="admin"),
            )
        assert result["success"] is False
        assert "Failed to fetch update XML entries" in result["message"]

    def test_entry_with_non_dict_update_set_ref(self):
        """Line 481: update_set as plain string (not dict)."""
        config = _make_config()
        auth = _make_auth()

        us_data = [{"sys_id": "us1", "name": "Set1"}]
        entries = [
            {
                "target_name": "MyWidget",
                "name": "sp_widget",
                "action": "INSERT",
                "update_set": "us1",
                "sys_updated_on": "2026-03-31 10:00:00",
            },
        ]

        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (us_data, 1)
            return (entries, 1)

        call_count = [0]

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                side_effect=_query_side_effect,
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=1,
            ),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(developer="admin"),
            )
        assert result["success"] is True
        assert "Set1" in result["entries_by_update_set"]

    def test_full_fetch_with_cost_warning(self):
        """Line 503: cost_warnings after grouping entries."""
        config = _make_config()
        auth = _make_auth()

        us_data = [{"sys_id": "us1", "name": "BigSet"}]
        entries = [
            {
                "target_name": f"Widget{i}",
                "name": "sp_widget",
                "action": "INSERT",
                "update_set": {"display_value": "BigSet", "value": "us1"},
                "sys_updated_on": "2026-03-31 10:00:00",
            }
            for i in range(3)
        ]

        call_count = [0]

        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (us_data, 1)
            return (entries, len(entries))

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                side_effect=_query_side_effect,
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=5000,
            ),
        ):
            result = get_uncommitted_changes(
                config,
                auth,
                GetUncommittedChangesParams(developer="admin"),
            )
        assert result["success"] is True
        assert "cost_warnings" in result


class TestGetProviderDependencyMap:
    def test_with_scope(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_response({"result": []}, total_count=0)

        result = get_provider_dependency_map(
            config,
            auth,
            GetProviderDependencyMapParams(
                widget_ids=["wid1"],
                scope="x_app",
            ),
        )
        assert result["success"] is True

    def test_no_widget_ids_with_developer_filter(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_response({"result": []}, total_count=0)

        result = get_provider_dependency_map(
            config,
            auth,
            GetProviderDependencyMapParams(
                widget_ids=[],
                developer="admin",
            ),
        )
        assert result["success"] is True

    def test_fetch_widgets_error(self):
        config = _make_config()
        auth = _make_auth()

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
            side_effect=Exception("fetch error"),
        ):
            result = get_provider_dependency_map(
                config,
                auth,
                GetProviderDependencyMapParams(
                    widget_ids=["wid1"],
                ),
            )
        assert result["success"] is False

    def test_with_include_script_include_refs_false(self):
        config = _make_config()
        auth = _make_auth()
        auth.make_request.return_value = _mock_response({"result": []}, total_count=0)

        result = get_provider_dependency_map(
            config,
            auth,
            GetProviderDependencyMapParams(
                widget_ids=["wid1"],
                include_script_include_refs=False,
            ),
        )
        assert result["success"] is True

    def test_widget_fetch_exception(self):
        """Lines 620-621: exception when fetching widgets."""
        config = _make_config()
        auth = _make_auth()

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=1,
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                side_effect=Exception("widget fetch boom"),
            ),
        ):
            result = get_provider_dependency_map(
                config,
                auth,
                GetProviderDependencyMapParams(widget_ids=["w1"]),
            )
        assert result["success"] is False
        assert "Failed to fetch widgets" in result["message"]

    def test_m2m_fetch_exception(self):
        """Lines 637-639: exception during M2M widget-provider fetch."""
        config = _make_config()
        auth = _make_auth()
        widgets = [{"sys_id": "w1", "name": "W1"}]
        call_count = [0]

        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (widgets, 1)
            raise Exception("M2M fetch boom")

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=1,
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                side_effect=_query_side_effect,
            ),
        ):
            result = get_provider_dependency_map(
                config,
                auth,
                GetProviderDependencyMapParams(
                    widget_ids=["w1"],
                    include_script_include_refs=False,
                ),
            )
        assert result["success"] is True
        # M2M failure should be logged as warning, not fatal

    def test_provider_fetch_exception(self):
        """Lines 676-677: exception when fetching provider chunk."""
        config = _make_config()
        auth = _make_auth()
        widgets = [{"sys_id": "w1", "name": "W1"}]
        m2m_rows = [{"sp_widget": {"value": "w1"}, "sp_angular_provider": {"value": "p1"}}]
        call_count = [0]

        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (widgets, 1)
            if call_count[0] == 2:
                return (m2m_rows, 1)
            raise Exception("provider fetch boom")

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=1,
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                side_effect=_query_side_effect,
            ),
        ):
            result = get_provider_dependency_map(
                config,
                auth,
                GetProviderDependencyMapParams(
                    widget_ids=["w1"],
                    include_script_include_refs=False,
                ),
            )
        assert result["success"] is True

    def test_si_resolve_exception(self):
        """Lines 724-725: exception when resolving script includes."""
        config = _make_config()
        auth = _make_auth()
        widgets = [
            {"sys_id": "w1", "name": "W1", "script": "var x = new MyHelper();"},
        ]
        call_count = [0]

        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (widgets, 1)
            if call_count[0] == 2:
                return ([], 0)
            raise Exception("SI resolve boom")

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=1,
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                side_effect=_query_side_effect,
            ),
        ):
            result = get_provider_dependency_map(
                config,
                auth,
                GetProviderDependencyMapParams(
                    widget_ids=["w1"],
                    include_script_include_refs=True,
                ),
            )
        assert result["success"] is True

    def test_unresolved_script_includes(self):
        """Line 779: unresolved_script_includes in response."""
        config = _make_config()
        auth = _make_auth()
        widgets = [
            {"sys_id": "w1", "name": "W1", "script": "var x = new GhostHelper();"},
        ]
        call_count = [0]

        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (widgets, 1)
            if call_count[0] == 2:
                return ([], 0)
            return ([], 0)

        with (
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
                return_value=1,
            ),
            patch(
                "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
                side_effect=_query_side_effect,
            ),
        ):
            result = get_provider_dependency_map(
                config,
                auth,
                GetProviderDependencyMapParams(
                    widget_ids=["w1"],
                    include_script_include_refs=True,
                ),
            )
        assert result["success"] is True
        assert "unresolved_script_includes" in result
        assert "GhostHelper" in result["unresolved_script_includes"]


class TestExtractScriptProfile:
    def test_empty_content(self):
        """Line 880: empty/whitespace content returns {}."""
        assert _extract_script_profile("") == {}
        assert _extract_script_profile("   ") == {}
        assert _extract_script_profile(None) == {}

    def test_with_function_names(self):
        profile = _extract_script_profile(
            "function myFunc() { return 1; }\nfunction helper() { return 2; }"
        )
        assert profile["lines"] == 2
        assert "myFunc" in profile["functions"]
        assert "helper" in profile["functions"]


class TestGetDeveloperDailySummary:
    def test_with_scope_and_details(self):
        config = _make_config()
        auth = _make_auth()

        auth.make_request.return_value = _mock_response({"result": []}, total_count=0)

        result = get_developer_daily_summary(
            config,
            auth,
            GetDeveloperDailySummaryParams(
                developer="admin",
                date="2026-04-25",
                scope="x_app",
                include_details=True,
            ),
        )
        assert result["success"] is True

    def test_fetch_error_continues(self):
        config = _make_config()
        auth = _make_auth()

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
            side_effect=Exception("daily error"),
        ):
            result = get_developer_daily_summary(
                config,
                auth,
                GetDeveloperDailySummaryParams(
                    developer="admin",
                    date="2026-04-25",
                ),
            )
        assert result["success"] is True

    def test_without_details(self):
        config = _make_config()
        auth = _make_auth()

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_count_shared",
            return_value=3,
        ):
            result = get_developer_daily_summary(
                config,
                auth,
                GetDeveloperDailySummaryParams(
                    developer="admin",
                    date="2026-04-25",
                    include_details=False,
                ),
            )
        assert result["success"] is True

    def test_unknown_source_type_continues(self):
        """Line 953: unknown source_type skipped with continue."""
        config = _make_config()
        auth = _make_auth()

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
            return_value=([], 0),
        ):
            result = get_developer_daily_summary(
                config,
                auth,
                GetDeveloperDailySummaryParams(
                    developer="admin",
                    date="2026-04-25",
                    source_types=["nonexistent_type", "widget"],
                    output_format="structured",
                    include_details=False,
                    include_update_sets=False,
                ),
            )
        assert result["success"] is True

    def test_jira_format_without_details(self):
        """Lines 1203-1206: jira format without include_details."""
        config = _make_config()
        auth = _make_auth()

        widget_rows = [
            {"sys_id": "w1", "name": "W1", "sys_updated_on": "2026-03-31 09:00:00"},
        ]

        auth.make_request.side_effect = [
            _mock_response({"result": widget_rows}, total_count=1),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
        ]

        result = get_developer_daily_summary(
            config,
            auth,
            GetDeveloperDailySummaryParams(
                developer="admin",
                date="2026-03-31",
                output_format="jira",
                include_details=False,
                include_update_sets=False,
            ),
        )
        assert result["success"] is True
        md = result["jira_markdown"]
        assert "W1" in md
        assert "| Name | Scope | Updated |" in md

    def test_plain_format_with_action_and_scope_and_fields(self):
        """Lines 1239, 1241, 1244-1247, 1249: plain format with action, scope, fields, providers."""
        config = _make_config()
        auth = _make_auth()

        widget_rows = [
            {
                "sys_id": "w1",
                "name": "W1",
                "sys_scope": {"display_value": "x_app"},
                "sys_updated_on": "2026-03-31 09:00:00",
                "script": "function myFn() { return 1; }",
                "client_script": "function clFn() { return 2; }",
                "template": "<div>hi</div>",
                "css": "",
            },
        ]
        m2m_rows = [{"sp_widget": {"value": "w1"}, "sp_angular_provider": {"value": "p1"}}]
        provider_rows = [{"sys_id": "p1", "name": "myProvider"}]
        xml_rows = [{"target_name": "W1", "action": "INSERT_OR_UPDATE", "name": "sp_widget"}]

        auth.make_request.side_effect = [
            _mock_response({"result": widget_rows}, total_count=1),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": m2m_rows}, total_count=1),
            _mock_response({"result": provider_rows}, total_count=1),
            _mock_response({"result": xml_rows}, total_count=1),
            _mock_response({"result": []}, total_count=0),
        ]

        result = get_developer_daily_summary(
            config,
            auth,
            GetDeveloperDailySummaryParams(
                developer="admin",
                date="2026-03-31",
                output_format="plain",
                include_details=True,
                include_update_sets=True,
            ),
        )
        assert result["success"] is True
        text = result["plain_text"]
        assert "W1" in text
        assert "[INSERT_OR_UPDATE]" in text  # line 1239: action
        assert "(x_app)" in text  # line 1241: scope
        assert "script:" in text  # line 1244-1247: fields
        assert "myProvider" in text  # line 1249: providers

    def test_plain_format_with_update_sets(self):
        """Lines 1253-1255: plain format with update sets section."""
        config = _make_config()
        auth = _make_auth()

        widget_rows = [
            {"sys_id": "w1", "name": "W1", "sys_updated_on": "2026-03-31 09:00:00"},
        ]
        us_rows = [
            {
                "sys_id": "us1",
                "name": "US-Fix",
                "state": "in progress",
                "application": {"display_value": "x_app"},
            },
        ]

        auth.make_request.side_effect = [
            _mock_response({"result": widget_rows}, total_count=1),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": []}, total_count=0),
            _mock_response({"result": us_rows}, total_count=1),
        ]

        result = get_developer_daily_summary(
            config,
            auth,
            GetDeveloperDailySummaryParams(
                developer="admin",
                date="2026-03-31",
                output_format="plain",
                include_details=False,
                include_update_sets=True,
            ),
        )
        assert result["success"] is True
        text = result["plain_text"]
        assert "US-Fix" in text
        assert "Update Sets" in text

    def test_provider_resolve_exception(self):
        """Lines 1082-1083: exception during provider resolution."""
        config = _make_config()
        auth = _make_auth()

        widget_rows = [
            {
                "sys_id": "w1",
                "name": "W1",
                "sys_updated_on": "2026-03-31 09:00:00",
                "script": "function test() {}",
            },
        ]
        call_count = [0]

        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (widget_rows, 1)
            if call_count[0] == 2:
                return ([], 0)
            if call_count[0] == 3:
                return ([], 0)
            if call_count[0] == 4:
                raise Exception("provider resolve boom")
            return ([], 0)

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
            side_effect=_query_side_effect,
        ):
            result = get_developer_daily_summary(
                config,
                auth,
                GetDeveloperDailySummaryParams(
                    developer="admin",
                    date="2026-03-31",
                    output_format="structured",
                    include_details=True,
                    include_update_sets=False,
                ),
            )
        assert result["success"] is True

    def test_update_xml_action_mapping_exception(self):
        """Lines 1123-1124: exception during update XML action mapping."""
        config = _make_config()
        auth = _make_auth()

        widget_rows = [
            {"sys_id": "w1", "name": "W1", "sys_updated_on": "2026-03-31 09:00:00"},
        ]
        call_count = [0]

        def _query_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (widget_rows, 1)
            if call_count[0] == 2:
                return ([], 0)
            if call_count[0] == 3:
                return ([], 0)
            raise Exception("xml action boom")

        with patch(
            "servicenow_mcp.tools.portal_dev_tools._sn_query_page_shared",
            side_effect=_query_side_effect,
        ):
            result = get_developer_daily_summary(
                config,
                auth,
                GetDeveloperDailySummaryParams(
                    developer="admin",
                    date="2026-03-31",
                    output_format="structured",
                    include_details=True,
                    include_update_sets=False,
                ),
            )
        assert result["success"] is True


class TestCompactRecord:
    def test_strips_display_value_dicts(self):
        record = {
            "sys_id": "abc",
            "name": {"display_value": "My Widget", "value": "my_widget"},
            "scope": {"display_value": "", "value": "x_app"},
        }
        result = _compact_record(record)
        assert result["name"] == "My Widget"
        assert "scope" not in result

    def test_strips_none_and_empty(self):
        record = {"sys_id": "abc", "name": None, "desc": ""}
        result = _compact_record(record)
        assert result == {"sys_id": "abc"}

    def test_preserves_scalar_values(self):
        record = {"sys_id": "abc", "name": "short", "count": 5}
        result = _compact_record(record)
        assert result == record

    def test_empty_record(self):
        result = _compact_record({})
        assert result == {}
