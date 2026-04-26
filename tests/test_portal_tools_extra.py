"""Extra tests for portal_tools.py — covering missed branches and helper functions."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    DetectAngularImplicitGlobalsParams,
    DownloadPortalSourcesParams,
    GetPortalComponentParams,
    GetWidgetBundleParams,
    ResolvePageDependenciesParams,
    ResolveWidgetChainParams,
    RoutePortalComponentEditParams,
    SearchPortalRegexMatchesParams,
    TracePortalRouteTargetsParams,
    UpdatePortalComponentParams,
    _as_bool,
    _as_display_text,
    _as_int,
    _build_dep_map,
    _build_diff_preview,
    _build_field_change_summary,
    _build_portal_update_risks,
    _chunked,
    _classify_portal_update_risk,
    _collect_declared_identifiers,
    _compile_search_pattern,
    _dedupe_fields,
    _dedupe_preserve_order,
    _dedupe_preserve_order_strings,
    _escape_query,
    _extract_click_handlers,
    _extract_implicit_global_hits,
    _extract_pattern_hits,
    _extract_portal_route_details,
    _extract_ref_candidates,
    _fetch_linked_script_include_rows,
    _find_latest_function_context,
    _json_or_raw_string,
    _looks_like_regex,
    _match_location,
    _normalize_portal_component_table,
    _parse_attributes,
    _read_portal_component_snapshot,
    _resolve_fixed_output_mode,
    _resolve_match_mode,
    _resolve_output_mode,
    _resolve_snapshot_fields,
    _route_target_summary,
    _safe_name,
    _shape_route_trace,
    _shape_trace_hit,
    _slice_one_line_snippet,
    _split_param_names,
    _summarize_text_preview,
    _to_one_line,
    _validate_portal_component_update_data,
    detect_angular_implicit_globals,
    download_portal_sources,
    get_portal_component_code,
    get_widget_bundle,
    resolve_page_dependencies,
    resolve_widget_chain,
    route_portal_component_edit,
    search_portal_regex_matches,
    trace_portal_route_targets,
    update_portal_component,
)
from servicenow_mcp.utils.config import ServerConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth_manager():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


# ---------------------------------------------------------------------------
# _normalize_portal_component_table — line 218-219
# ---------------------------------------------------------------------------


class TestNormalizePortalComponentTable:
    def test_invalid_table_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported table 'bad_table'"):
            _normalize_portal_component_table("bad_table")


# ---------------------------------------------------------------------------
# _validate_portal_component_update_data — lines 227, 242
# ---------------------------------------------------------------------------


class TestValidatePortalComponentUpdateData:
    def test_empty_update_data_raises(self):
        with pytest.raises(ValueError, match="at least one field"):
            _validate_portal_component_update_data("sp_widget", {})

    def test_non_string_value_raises(self):
        with pytest.raises(ValueError, match="must be a string"):
            _validate_portal_component_update_data("sp_widget", {"script": 123})


# ---------------------------------------------------------------------------
# _summarize_text_preview — lines 275-276
# ---------------------------------------------------------------------------


class TestSummarizeTextPreview:
    def test_long_text_is_truncated(self):
        long_text = "a" * 300
        result = _summarize_text_preview(long_text, 100)
        assert "TRUNCATED" in result
        assert len(result) < 300


# ---------------------------------------------------------------------------
# _build_diff_preview — line 291, 293
# ---------------------------------------------------------------------------


class TestBuildDiffPreview:
    def test_identical_content_returns_empty(self):
        result = _build_diff_preview("hello", "hello")
        assert result == ""

    def test_large_diff_is_truncated(self):
        before = "\n".join(f"line {i}" for i in range(500))
        after = "\n".join(f"changed {i}" for i in range(500))
        result = _build_diff_preview(before, after)
        assert "TRUNCATED" in result


# ---------------------------------------------------------------------------
# _build_portal_update_risks — lines 318, 333, 343, 350, 355
# ---------------------------------------------------------------------------


class TestBuildPortalUpdateRisks:
    def test_no_effective_change(self):
        risks = _build_portal_update_risks("sp_widget", [{"field": "script", "changed": False}])
        assert risks == ["No effective change detected against the current record."]

    def test_css_risk(self):
        risks = _build_portal_update_risks(
            "sp_widget",
            [{"field": "css", "changed": True, "delta_length": 10}],
        )
        assert any("CSS" in r for r in risks)

    def test_high_risk_classification(self):
        assert _classify_portal_update_risk(["a", "b", "c", "d"], 4) == "high"

    def test_medium_risk_classification(self):
        assert _classify_portal_update_risk(["a", "b"], 2) == "medium"

    def test_large_content_change_risk(self):
        risks = _build_portal_update_risks(
            "sp_widget",
            [{"field": "script", "changed": True, "delta_length": 3000}],
        )
        assert any("large content change" in r.lower() for r in risks)


# ---------------------------------------------------------------------------
# _resolve_snapshot_fields — lines 562, 566-567
# ---------------------------------------------------------------------------


class TestResolveSnapshotFields:
    def test_none_fields_returns_all_allowed(self):
        result = _resolve_snapshot_fields("sp_widget", None)
        assert len(result) > 0

    def test_invalid_fields_raises(self):
        with pytest.raises(ValueError, match="Unsupported snapshot fields"):
            _resolve_snapshot_fields("sp_widget", ["nonexistent_field"])


# ---------------------------------------------------------------------------
# _read_portal_component_snapshot — lines 614, 625, 630, 635
# ---------------------------------------------------------------------------


class TestReadPortalComponentSnapshot:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Snapshot file not found"):
            _read_portal_component_snapshot(str(tmp_path / "nonexistent.json"))

    def test_invalid_snapshot_format_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"component": "not a dict"}))
        with pytest.raises(ValueError, match="Invalid snapshot format"):
            _read_portal_component_snapshot(str(bad))

    def test_missing_table_sys_id_raises(self, tmp_path):
        snap = tmp_path / "snap.json"
        snap.write_text(
            json.dumps(
                {
                    "component": {"table": "", "sys_id": ""},
                    "values": {},
                    "fields": [],
                }
            )
        )
        with pytest.raises(ValueError, match="Invalid snapshot component metadata"):
            _read_portal_component_snapshot(str(snap))

    def test_non_string_value_raises(self, tmp_path):
        snap = tmp_path / "snap.json"
        snap.write_text(
            json.dumps(
                {
                    "component": {"table": "sp_widget", "sys_id": "abc"},
                    "values": {"script": 123},
                    "fields": ["script"],
                }
            )
        )
        with pytest.raises(ValueError, match="must be a string"):
            _read_portal_component_snapshot(str(snap))


# ---------------------------------------------------------------------------
# _chunked — line 936
# ---------------------------------------------------------------------------


class TestChunked:
    def test_zero_size_returns_single_chunk(self):
        assert _chunked(["a", "b", "c"], 0) == [["a", "b", "c"]]


# ---------------------------------------------------------------------------
# _dedupe_preserve_order_strings — line 999
# ---------------------------------------------------------------------------


class TestDedupePreserveOrderStrings:
    def test_empty_strings_are_dropped(self):
        assert _dedupe_preserve_order_strings(["a", "", "b"]) == ["a", "b"]


# ---------------------------------------------------------------------------
# _fetch_linked_script_include_rows — lines 1018, 1039, 1041, 1043
# ---------------------------------------------------------------------------


class TestFetchLinkedScriptIncludeRows:
    @patch("servicenow_mcp.tools.portal_tools._sn_query_all")
    def test_empty_candidates_returns_empty(self, mock_qa):
        result = _fetch_linked_script_include_rows(
            MagicMock(), MagicMock(), candidates=[], page_size=50
        )
        assert result == []
        mock_qa.assert_not_called()

    @patch("servicenow_mcp.tools.portal_tools._sn_query_all")
    def test_filters_by_updated_by_and_dates(self, mock_qa):
        mock_qa.return_value = []
        _fetch_linked_script_include_rows(
            MagicMock(),
            MagicMock(),
            candidates=["MySI"],
            page_size=50,
            updated_by="admin",
            updated_after="2026-01-01",
            updated_before="2026-12-31",
        )
        query = mock_qa.call_args.kwargs["query"]
        assert "sys_updated_by=" in query
        assert "sys_updated_on>=" in query
        assert "sys_updated_on<=" in query


# ---------------------------------------------------------------------------
# _extract_pattern_hits — lines 1299, 1304
# ---------------------------------------------------------------------------


class TestExtractPatternHits:
    def test_empty_content_returns_empty(self):
        import re

        regex = re.compile(r"test")
        result = _extract_pattern_hits(
            source_type="widget",
            source_sys_id="abc",
            source_name="w",
            field_name="script",
            content="",
            regex=regex,
            snippet_length=200,
            max_matches=5,
        )
        assert result == []

    def test_max_matches_zero_returns_empty(self):
        import re

        regex = re.compile(r"test")
        result = _extract_pattern_hits(
            source_type="widget",
            source_sys_id="abc",
            source_name="w",
            field_name="script",
            content="test test test",
            regex=regex,
            snippet_length=200,
            max_matches=0,
        )
        assert result == []

    def test_max_matches_limits_results(self):
        import re

        regex = re.compile(r"test")
        result = _extract_pattern_hits(
            source_type="widget",
            source_sys_id="abc",
            source_name="w",
            field_name="script",
            content="test test test",
            regex=regex,
            snippet_length=200,
            max_matches=1,
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _extract_portal_route_details — line 1332
# ---------------------------------------------------------------------------


class TestExtractPortalRouteDetails:
    def test_non_slash_returns_empty(self):
        assert _extract_portal_route_details("not_a_route") == {}

    def test_custom_portal_route(self):
        details = _extract_portal_route_details("/custom?id=page1")
        assert details["route_family"] == "custom_portal"
        assert details["route_id"] == "page1"

    def test_empty_path_returns_empty(self):
        # Testing the parsed.path empty case
        details = _extract_portal_route_details("/")
        assert "route_family" in details


# ---------------------------------------------------------------------------
# _match_location — line 1360
# ---------------------------------------------------------------------------


class TestMatchLocation:
    def test_unknown_source_type(self):
        result = _match_location("custom_type", "MyWidget", "field1")
        assert result == "custom_type/MyWidget/field1"


# ---------------------------------------------------------------------------
# _resolve_output_mode — line 1406
# ---------------------------------------------------------------------------


class TestResolveOutputMode:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="output_mode must be one of"):
            _resolve_output_mode("invalid", True)


# ---------------------------------------------------------------------------
# _resolve_fixed_output_mode — line 1413
# ---------------------------------------------------------------------------


class TestResolveFixedOutputMode:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="output_mode must be one of"):
            _resolve_fixed_output_mode("bad_mode")


# ---------------------------------------------------------------------------
# _resolve_match_mode — line 1249
# ---------------------------------------------------------------------------


class TestResolveMatchMode:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="match_mode must be one of"):
            _resolve_match_mode("invalid")


# ---------------------------------------------------------------------------
# _find_latest_function_context — line 1452
# ---------------------------------------------------------------------------


class TestFindLatestFunctionContext:
    def test_finds_named_function(self):
        content = "function myFunc() { var x = 1; }"
        result = _find_latest_function_context(content, 10)
        assert result == "myFunc"

    def test_no_match_returns_none(self):
        result = _find_latest_function_context("var x = 1;", 3)
        assert result is None


# ---------------------------------------------------------------------------
# _route_target_summary — lines 1463, 1464
# ---------------------------------------------------------------------------


class TestRouteTargetSummary:
    def test_with_query_id(self):
        result = _route_target_summary("/sp?id=my_page")
        assert result["page_id"] == "my_page"

    def test_plain_name_as_page_id(self):
        result = _route_target_summary("my_simple_page")
        assert result["page_id"] == "my_simple_page"


# ---------------------------------------------------------------------------
# _shape_trace_hit — compact vs full
# ---------------------------------------------------------------------------


class TestShapeTraceHit:
    def test_minimal_shape(self):
        hit = {
            "source_type": "widget",
            "source_name": "w",
            "field": "script",
            "line": 1,
            "match": "/sp",
        }
        result = _shape_trace_hit(hit, output_mode="minimal")
        assert "snippet" not in result
        assert "provider" not in result

    def test_full_shape_with_context_and_provider(self):
        hit = {
            "source_type": "angular_provider",
            "source_name": "p",
            "field": "script",
            "line": 5,
            "column": 10,
            "match": "/sp",
            "snippet": "code",
            "context_name": "myFunc",
            "provider": {"sys_id": "p1", "name": "prov"},
        }
        result = _shape_trace_hit(hit, output_mode="full")
        assert result["context_name"] == "myFunc"
        assert result["provider"] == {"sys_id": "p1", "name": "prov"}


# ---------------------------------------------------------------------------
# _shape_route_trace — compact vs full
# ---------------------------------------------------------------------------


class TestShapeRouteTrace:
    def _base_trace(self):
        return {
            "widget": {"sys_id": "w1", "name": "w"},
            "route_targets": [],
            "service_names": [],
            "button_handlers": [],
            "branch_names": [],
            "evidence": [],
            "matched_provider_count": 2,
            "matched_widget_field_count": 1,
            "provider_matches": [{"a": 1}],
            "widget_matches": [{"b": 2}],
            "linked_providers": [{"sys_id": "p1", "name": "prov"}],
        }

    def test_minimal_excludes_counts(self):
        result = _shape_route_trace(self._base_trace(), output_mode="minimal")
        assert "matched_provider_count" not in result
        assert "provider_matches" not in result

    def test_compact_includes_counts(self):
        result = _shape_route_trace(self._base_trace(), output_mode="compact")
        assert result["matched_provider_count"] == 2
        assert "provider_matches" not in result

    def test_full_includes_everything(self):
        result = _shape_route_trace(self._base_trace(), output_mode="full")
        assert result["provider_matches"] == [{"a": 1}]
        assert result["linked_providers"] == [{"sys_id": "p1", "name": "prov"}]


# ---------------------------------------------------------------------------
# _split_param_names, _collect_declared_identifiers — lines 1527, 1538, 1540, 1542
# ---------------------------------------------------------------------------


class TestDeclarationHelpers:
    def test_split_param_names_extracts_names(self):
        result = _split_param_names("a, b=1, c")
        assert result == {"a", "b", "c"}

    def test_split_param_names_ignores_invalid(self):
        result = _split_param_names("123, valid")
        assert result == {"valid"}

    def test_collect_declared_identifiers_catches_var_let_const(self):
        script = "var x = 1; let y = 2; const z = 3;"
        result = _collect_declared_identifiers(script)
        assert {"x", "y", "z"} <= result

    def test_collect_declared_identifiers_catches_function_params(self):
        script = "function foo(a, b) {}"
        result = _collect_declared_identifiers(script)
        assert {"a", "b"} <= result

    def test_collect_declared_identifiers_catches_arrow_params(self):
        script = "var fn = (d, e) => {};"
        result = _collect_declared_identifiers(script)
        assert "d" in result
        assert "e" in result

    def test_collect_declared_identifiers_catches_catch_param(self):
        script = "try {} catch(err) {}"
        result = _collect_declared_identifiers(script)
        assert "err" in result

    def test_collect_declared_identifiers_catches_function_expression_params(self):
        script = "var bar = function(baz) {};"
        result = _collect_declared_identifiers(script)
        assert "baz" in result


# ---------------------------------------------------------------------------
# _extract_implicit_global_hits — line 1555, 1562, 1566
# ---------------------------------------------------------------------------


class TestExtractImplicitGlobalHits:
    def test_empty_script_returns_empty(self):
        result = _extract_implicit_global_hits(
            source_sys_id="p1",
            source_name="prov",
            script="",
            snippet_length=200,
            max_matches=5,
        )
        assert result == []

    def test_max_matches_zero_returns_empty(self):
        result = _extract_implicit_global_hits(
            source_sys_id="p1",
            source_name="prov",
            script="x = 1;",
            snippet_length=200,
            max_matches=0,
        )
        assert result == []

    def test_declared_var_not_reported(self):
        result = _extract_implicit_global_hits(
            source_sys_id="p1",
            source_name="prov",
            script="var myVar = 1; myVar = 2;",
            snippet_length=200,
            max_matches=10,
        )
        variables = [h["variable"] for h in result]
        assert "myVar" not in variables

    def test_max_matches_limits_output(self):
        script = "a = 1; b = 2; c = 3;"
        result = _extract_implicit_global_hits(
            source_sys_id="p1",
            source_name="prov",
            script=script,
            snippet_length=200,
            max_matches=1,
        )
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _as_display_text — lines 1622-1626
# ---------------------------------------------------------------------------


class TestAsDisplayText:
    def test_dict_with_display_value(self):
        assert _as_display_text({"display_value": "Hello"}) == "Hello"

    def test_dict_with_displayValue(self):
        assert _as_display_text({"displayValue": "World"}) == "World"

    def test_dict_with_value(self):
        assert _as_display_text({"value": "Val"}) == "Val"

    def test_dict_with_empty_value_returns_empty(self):
        assert _as_display_text({"display_value": ""}) == ""

    def test_non_dict_non_string_returns_empty(self):
        assert _as_display_text(123) == ""


# ---------------------------------------------------------------------------
# _as_bool, _as_int — lines 1634, 1636
# ---------------------------------------------------------------------------


class TestAsBool:
    def test_bool_true(self):
        assert _as_bool(True) is True

    def test_string_yes(self):
        assert _as_bool("yes") is True

    def test_string_1(self):
        assert _as_bool("1") is True

    def test_string_false(self):
        assert _as_bool("false") is False


class TestAsInt:
    def test_valid_int(self):
        assert _as_int("42") == 42

    def test_invalid_returns_default(self):
        assert _as_int("not_int", 7) == 7


# ---------------------------------------------------------------------------
# _parse_attributes — lines 1650-1660
# ---------------------------------------------------------------------------


class TestParseAttributes:
    def test_empty_returns_empty(self):
        assert _parse_attributes("") == {}

    def test_none_returns_empty(self):
        assert _parse_attributes(None) == {}

    def test_key_value_pairs(self):
        result = _parse_attributes("ref=auto,ornament=comments")
        assert result == {"ref": "auto", "ornament": "comments"}

    def test_flag_without_value(self):
        result = _parse_attributes("is_list")
        assert result == {"is_list": "true"}

    def test_empty_token_skipped(self):
        result = _parse_attributes("a=1,,b=2")
        assert result == {"a": "1", "b": "2"}


# ---------------------------------------------------------------------------
# _json_or_raw_string — lines 1727-1728
# ---------------------------------------------------------------------------


class TestJsonOrRawString:
    def test_invalid_json_returns_raw(self):
        result = _json_or_raw_string("{invalid json")
        assert result == "{invalid json"

    def test_array_string_parsed(self):
        result = _json_or_raw_string('[{"a":1}]')
        assert result == [{"a": 1}]

    def test_non_string_returns_as_is(self):
        assert _json_or_raw_string(42) == 42


# ---------------------------------------------------------------------------
# _fetch_portal_component_record — line 266
# ---------------------------------------------------------------------------


class TestFetchPortalComponentRecord:
    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_not_found_raises(self, mock_q, mock_config, mock_auth_manager):
        mock_q.return_value = {"success": False}
        from servicenow_mcp.tools.portal_tools import _fetch_portal_component_record

        with pytest.raises(ValueError, match="Component not found"):
            _fetch_portal_component_record(
                mock_config, mock_auth_manager, "sp_widget", "missing", ["script"]
            )


# ---------------------------------------------------------------------------
# get_widget_bundle — line 1761 (not found)
# ---------------------------------------------------------------------------


class TestGetWidgetBundle:
    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_widget_not_found(self, mock_q, mock_config, mock_auth_manager):
        mock_q.return_value = {"success": False}
        result = get_widget_bundle(
            mock_config, mock_auth_manager, GetWidgetBundleParams(widget_id="missing")
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# get_portal_component_code — lines 1827, 1839, 1844-1851
# ---------------------------------------------------------------------------


class TestGetPortalComponentCode:
    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_not_found(self, mock_q, mock_config, mock_auth_manager):
        mock_q.return_value = {"success": False}
        result = get_portal_component_code(
            mock_config,
            mock_auth_manager,
            GetPortalComponentParams(table="sp_widget", sys_id="missing"),
        )
        assert "error" in result

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_budget_exhausted_field(self, mock_q, mock_config, mock_auth_manager):
        """When remaining budget is 0, subsequent fields get empty content with metadata."""
        # First field uses all budget, second field gets budget_exhausted treatment
        large_field = "x" * 8000
        mock_q.return_value = {
            "success": True,
            "results": [
                {
                    "script": large_field,
                    "template": "short",
                    "sys_id": "s1",
                    "name": "Test",
                }
            ],
        }
        params = GetPortalComponentParams(
            table="sp_widget",
            sys_id="s1",
            fields=["script", "template"],
            script_max_length=8000,
        )
        result = get_portal_component_code(mock_config, mock_auth_manager, params)
        # script consumed all budget
        assert result["script"] != ""
        # template should have total_length metadata
        assert result.get("_template_total_length") is not None

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_non_string_value_skipped(self, mock_q, mock_config, mock_auth_manager):
        mock_q.return_value = {
            "success": True,
            "results": [{"script": 12345, "sys_id": "s1", "name": "Test"}],
        }
        result = get_portal_component_code(
            mock_config,
            mock_auth_manager,
            GetPortalComponentParams(table="sp_widget", sys_id="s1", fields=["script"]),
        )
        # Non-string value should be skipped in budget tracking
        assert result["script"] == 12345


# ---------------------------------------------------------------------------
# route_portal_component_edit — lines 2066-2067 (invalid table)
# ---------------------------------------------------------------------------


class TestRoutePortalComponentEdit:
    def test_rollback_with_snapshot_path_in_target(self):
        result = route_portal_component_edit(
            MagicMock(),
            MagicMock(),
            RoutePortalComponentEditParams(
                instruction="rollback the changes",
                table="sp_widget",
                snapshot_path="/tmp/snap.json",
            ),
        )
        assert result["detected_action"] == "rollback"
        assert result["target"]["table"] == "sp_widget"
        assert result["target"]["snapshot_path"] == "/tmp/snap.json"

    def test_snapshot_action_with_suggested_fields(self):
        result = route_portal_component_edit(
            MagicMock(),
            MagicMock(),
            RoutePortalComponentEditParams(
                instruction="take a snapshot of the widget template",
                table="sp_widget",
                sys_id="abc123",
            ),
        )
        assert result["detected_action"] == "snapshot"
        assert result["tool_plan"]["tool_name"] == "create_portal_component_snapshot"
        assert "template" in result["suggested_fields"]

    def test_snapshot_action_without_table(self):
        result = route_portal_component_edit(
            MagicMock(),
            MagicMock(),
            RoutePortalComponentEditParams(
                instruction="take a snapshot backup",
            ),
        )
        assert result["detected_action"] == "snapshot"
        assert result["tool_plan"]["missing_requirements"] == ["table", "sys_id"]

    def test_rollback_missing_snapshot_path(self):
        result = route_portal_component_edit(
            MagicMock(),
            MagicMock(),
            RoutePortalComponentEditParams(
                instruction="rollback the changes",
            ),
        )
        assert result["detected_action"] == "rollback"
        assert "snapshot_path" in result["tool_plan"]["missing_requirements"]


# ---------------------------------------------------------------------------
# search_portal_regex_matches — error paths (lines 2106-2107, 2111-2112, 2133)
# ---------------------------------------------------------------------------


class TestSearchPortalRegexMatchesErrors:
    def test_invalid_regex_returns_error(self, mock_config, mock_auth_manager):
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(regex="[invalid"),
        )
        assert result["success"] is False
        assert "Invalid regex" in result["message"]

    def test_invalid_output_mode_returns_error(self, mock_config, mock_auth_manager):
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                output_mode="bad_mode",
            ),
        )
        assert result["success"] is False

    def test_unsupported_source_type_returns_error(self, mock_config, mock_auth_manager):
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                source_types=["widget", "nonexistent_type"],
            ),
        )
        assert result["success"] is False
        assert "Unsupported source_types" in result["message"]


# ---------------------------------------------------------------------------
# search_portal_regex_matches — query filter branches (lines 2144, 2146, 2148, 2176)
# ---------------------------------------------------------------------------


class TestSearchPortalRegexMatchesFilters:
    @patch("servicenow_mcp.tools.portal_tools._sn_query_all")
    def test_scope_and_date_filters_applied(self, mock_qa, mock_config, mock_auth_manager):
        mock_qa.return_value = []
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                scope="x_app",
                updated_after="2026-01-01",
                updated_before="2026-12-31",
            ),
        )
        assert result["success"] is True
        query = mock_qa.call_args.kwargs["query"]
        assert "sys_scope.scope=" in query
        assert "sys_updated_on>=" in query
        assert "sys_updated_on<=" in query

    @patch("servicenow_mcp.tools.portal_tools._sn_query_all")
    def test_include_linked_si_adds_script_fields(self, mock_qa, mock_config, mock_auth_manager):
        mock_qa.return_value = []
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                source_types=["widget", "script_include"],
                include_linked_script_includes=True,
                include_widget_fields=["template"],
            ),
        )
        assert result["success"] is True
        fields = mock_qa.call_args.kwargs["fields"]
        assert "script" in fields
        assert "client_script" in fields


# ---------------------------------------------------------------------------
# search_portal_regex_matches — match loop boundary (lines 2193, 2216)
# ---------------------------------------------------------------------------


class TestSearchPortalRegexMatchesMatchLoop:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_max_matches_stops_widget_loop(self, mock_qa, mock_config, mock_auth_manager):
        """When max_matches reached, widget loop breaks (line 2193)."""
        mock_qa.return_value = [
            {
                "sys_id": "w1",
                "name": "W",
                "id": "w1",
                "script": "test test test",
                "template": "test test test",
                "client_script": "",
                "link": "",
                "css": "",
            }
        ]
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                max_matches=2,
                max_widgets=5,
                include_widget_fields=["script", "template"],
            ),
        )
        assert result["success"] is True
        # Should find at most 2 matches from first field then break
        assert result["scan_summary"]["match_count"] <= 2


# ---------------------------------------------------------------------------
# search_portal_regex_matches — provider + script_include scanning (lines 2236-2238, 2319, 2322)
# ---------------------------------------------------------------------------


class TestSearchPortalRegexMatchesProviderAndSI:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_direct_provider_ids_filter(self, mock_qa, mock_config, mock_auth_manager):
        """Lines 2236-2238: provider_ids filter bypasses M2M lookup."""
        mock_qa.side_effect = [
            # widget query
            [],
            # provider query
            [
                {
                    "sys_id": "prov1",
                    "name": "myProv",
                    "script": "var x = 'test match';",
                }
            ],
        ]
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                source_types=["angular_provider"],
                provider_ids=["prov1"],
            ),
        )
        assert result["success"] is True
        assert result["scan_summary"]["linked_angular_providers_scanned"] == 1

    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    @patch("servicenow_mcp.tools.portal_tools._fetch_linked_script_include_rows")
    def test_script_include_scanning_with_empty_content(
        self, mock_fetch_si, mock_qa, mock_config, mock_auth_manager
    ):
        """Lines 2322: empty SI content is skipped."""
        mock_qa.return_value = [
            {
                "sys_id": "w1",
                "name": "W",
                "id": "w1",
                "script": "var si = new MySI();",
                "template": "",
                "client_script": "",
                "link": "",
                "css": "",
            }
        ]
        mock_fetch_si.return_value = [{"sys_id": "si1", "name": "MySI", "script": ""}]
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                source_types=["widget", "script_include"],
                include_linked_script_includes=True,
                include_widget_fields=["script"],
            ),
        )
        assert result["success"] is True
        # SI had empty script so no SI matches added
        assert result["scan_summary"]["linked_script_includes_scanned"] == 1

    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    @patch("servicenow_mcp.tools.portal_tools._fetch_linked_script_include_rows")
    def test_script_include_max_matches_break(
        self, mock_fetch_si, mock_qa, mock_config, mock_auth_manager
    ):
        """Lines 2319: break when remaining <= 0 in SI loop."""
        mock_qa.return_value = [
            {
                "sys_id": "w1",
                "name": "W",
                "id": "w1",
                "script": "test",
                "template": "",
                "client_script": "",
                "link": "",
                "css": "",
            }
        ]
        mock_fetch_si.return_value = [
            {"sys_id": "si1", "name": "SI1", "script": "test match"},
            {"sys_id": "si2", "name": "SI2", "script": "test match"},
        ]
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                source_types=["widget", "script_include"],
                include_linked_script_includes=True,
                include_widget_fields=["script"],
                max_matches=2,
                max_widgets=5,
            ),
        )
        assert result["success"] is True
        assert result["scan_summary"]["match_count"] <= 2


# ---------------------------------------------------------------------------
# search_portal_regex_matches — full output mode (line 2344)
# ---------------------------------------------------------------------------


class TestSearchPortalRegexMatchesFullOutput:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_full_output_mode_returns_trimmed_matches(
        self, mock_qa, mock_config, mock_auth_manager
    ):
        mock_qa.return_value = [
            {
                "sys_id": "w1",
                "name": "W",
                "id": "w1",
                "script": "test",
                "template": "",
                "client_script": "",
                "link": "",
                "css": "",
            }
        ]
        result = search_portal_regex_matches(
            mock_config,
            mock_auth_manager,
            SearchPortalRegexMatchesParams(
                regex="test",
                output_mode="full",
                max_widgets=5,
                max_matches=5,
            ),
        )
        assert result["success"] is True
        assert result["scan_summary"]["output_mode"] == "full"
        # Full mode items should have extra keys like snippet, column
        if result["matches"]:
            assert "snippet" in result["matches"][0]


# ---------------------------------------------------------------------------
# trace_portal_route_targets — error paths (lines 2401-2402, 2406-2407)
# ---------------------------------------------------------------------------


class TestTracePortalRouteTargetsErrors:
    def test_invalid_regex_returns_error(self, mock_config, mock_auth_manager):
        result = trace_portal_route_targets(
            mock_config,
            mock_auth_manager,
            TracePortalRouteTargetsParams(regex="[invalid"),
        )
        assert result["success"] is False
        assert "Invalid regex" in result["message"]

    def test_invalid_output_mode_returns_error(self, mock_config, mock_auth_manager):
        result = trace_portal_route_targets(
            mock_config,
            mock_auth_manager,
            TracePortalRouteTargetsParams(regex="test", output_mode="bad"),
        )
        assert result["success"] is False


# ---------------------------------------------------------------------------
# trace_portal_route_targets — filter branches (lines 2425, 2427)
# ---------------------------------------------------------------------------


class TestTracePortalRouteTargetsFilters:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_updated_by_and_scope_filters(self, mock_qa, mock_config, mock_auth_manager):
        mock_qa.side_effect = [[], [], []]
        result = trace_portal_route_targets(
            mock_config,
            mock_auth_manager,
            TracePortalRouteTargetsParams(
                regex="test",
                updated_by="admin",
                scope="x_app",
            ),
        )
        assert result["success"] is True
        widget_query = mock_qa.call_args_list[0].kwargs["query"]
        assert "sys_updated_by=" in widget_query
        assert "sys_scope.scope=" in widget_query


# ---------------------------------------------------------------------------
# trace_portal_route_targets — provider_id based lookup (lines 2437-2471)
# ---------------------------------------------------------------------------


class TestTracePortalRouteTargetsProviderLookup:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_provider_ids_filter_triggers_provider_to_widget_lookup(
        self, mock_qa, mock_config, mock_auth_manager
    ):
        """Lines 2437-2471: provider_ids triggers provider lookup then M2M widget resolution."""
        mock_qa.side_effect = [
            # provider lookup
            [{"sys_id": "prov1", "name": "myProv", "id": "myProv"}],
            # M2M relation lookup
            [{"sp_widget": {"value": "wid1"}, "sp_angular_provider": {"value": "prov1"}}],
            # widget query with resolved IDs
            [
                {
                    "sys_id": "wid1",
                    "name": "MyWidget",
                    "id": "my_widget",
                    "template": '<a href="/sp?id=test">link</a>',
                    "script": "",
                    "client_script": "",
                    "link": "",
                }
            ],
            # provider for widget map
            [{"sp_widget": {"value": "wid1"}, "sp_angular_provider": {"value": "prov1"}}],
            # provider detail query
            [
                {
                    "sys_id": "prov1",
                    "name": "myProv",
                    "id": "myProv",
                    "script": "",
                }
            ],
        ]
        result = trace_portal_route_targets(
            mock_config,
            mock_auth_manager,
            TracePortalRouteTargetsParams(
                regex="/sp",
                provider_ids=["prov1"],
                output_mode="compact",
            ),
        )
        assert result["success"] is True
        assert result["summary"]["widgets_scanned"] == 1


# ---------------------------------------------------------------------------
# trace_portal_route_targets — max_traces and match capping (lines 2566, 2622, 2636)
# ---------------------------------------------------------------------------


class TestTracePortalRouteTargetsMaxTraces:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_max_traces_caps_results(self, mock_qa, mock_config, mock_auth_manager):
        mock_qa.side_effect = [
            [
                {
                    "sys_id": "w1",
                    "name": "W1",
                    "id": "w1",
                    "template": "/sp?id=a",
                    "script": "",
                    "client_script": "",
                    "link": "",
                },
                {
                    "sys_id": "w2",
                    "name": "W2",
                    "id": "w2",
                    "template": "/sp?id=b",
                    "script": "",
                    "client_script": "",
                    "link": "",
                },
            ],
            [],
            [],
        ]
        result = trace_portal_route_targets(
            mock_config,
            mock_auth_manager,
            TracePortalRouteTargetsParams(
                regex="/sp",
                max_traces=1,
            ),
        )
        assert result["success"] is True
        assert result["summary"]["trace_count"] == 1


# ---------------------------------------------------------------------------
# detect_angular_implicit_globals — filter branches (lines 2733, 2735, 2737, 2739, 2741-2747)
# ---------------------------------------------------------------------------


class TestDetectAngularImplicitGlobalsFilters:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_all_query_filters_applied(self, mock_qa, mock_config, mock_auth_manager):
        mock_qa.return_value = []
        result = detect_angular_implicit_globals(
            mock_config,
            mock_auth_manager,
            DetectAngularImplicitGlobalsParams(
                updated_by="admin",
                scope="x_app",
                updated_after="2026-01-01",
                updated_before="2026-12-31",
                provider_ids=["prov1"],
                max_matches=5,
            ),
        )
        assert result["success"] is True
        query = mock_qa.call_args.kwargs["query"]
        assert "sys_updated_by=" in query
        assert "sys_scope.scope=" in query
        assert "sys_updated_on>=" in query
        assert "sys_updated_on<=" in query
        # provider_ids should add sys_id/id/name clauses
        assert "sys_id=" in query or "prov1" in query

    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_max_findings_caps_results(self, mock_qa, mock_config, mock_auth_manager):
        """Lines 2771, 2774: max_findings caps and skips empty scripts."""
        mock_qa.return_value = [
            {"sys_id": "p1", "name": "prov1", "script": "x = 1; y = 2;"},
            {"sys_id": "p2", "name": "prov2", "script": ""},
        ]
        result = detect_angular_implicit_globals(
            mock_config,
            mock_auth_manager,
            DetectAngularImplicitGlobalsParams(max_matches=1, output_mode="full"),
        )
        assert result["success"] is True
        assert result["scan_summary"]["finding_count"] == 1


# ---------------------------------------------------------------------------
# detect_angular_implicit_globals — compact output mode (line 2790)
# ---------------------------------------------------------------------------


class TestDetectAngularImplicitGlobalsCompact:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_compact_output_shape(self, mock_qa, mock_config, mock_auth_manager):
        mock_qa.return_value = [
            {"sys_id": "p1", "name": "prov1", "script": "x = 1;"},
        ]
        result = detect_angular_implicit_globals(
            mock_config,
            mock_auth_manager,
            DetectAngularImplicitGlobalsParams(output_mode="compact", max_matches=5),
        )
        assert result["success"] is True
        assert "location" in result["findings"][0]
        assert "snippet" in result["findings"][0]


# ---------------------------------------------------------------------------
# update_portal_component — line 2860, 2880, 2921
# ---------------------------------------------------------------------------


class TestUpdatePortalComponentExtra:
    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    @patch("servicenow_mcp.tools.portal_tools.invalidate_query_cache")
    def test_large_payload_warning(self, mock_invalidate, mock_q, mock_config, mock_auth_manager):
        """Line 2860: large field triggers size_warning."""
        big_val = "x" * 600_000
        mock_q.side_effect = [
            {"success": True, "results": [{"sys_id": "s1", "name": "T", "script": "old"}]},
            {"success": True, "results": [{"sys_id": "s1", "name": "T", "script": big_val}]},
        ]
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_auth_manager.make_request.return_value = mock_response

        result = update_portal_component(
            mock_config,
            mock_auth_manager,
            UpdatePortalComponentParams(
                table="sp_widget", sys_id="s1", update_data={"script": big_val}
            ),
        )
        assert "size_warnings" in result
        assert len(result["size_warnings"]) > 0

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_update_failure_returns_error(self, mock_q, mock_config, mock_auth_manager):
        """Line 2880: server error returns error response."""
        mock_q.return_value = {
            "success": True,
            "results": [{"sys_id": "s1", "name": "T", "script": "old"}],
        }
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_auth_manager.make_request.return_value = mock_response

        result = update_portal_component(
            mock_config,
            mock_auth_manager,
            UpdatePortalComponentParams(
                table="sp_widget", sys_id="s1", update_data={"script": "new"}
            ),
        )
        assert "error" in result
        assert result["status"] == 500


# ---------------------------------------------------------------------------
# resolve_widget_chain — lines 3346-3347, 3382-3385, 3409-3412, 3454-3459
# ---------------------------------------------------------------------------


class TestResolveWidgetChain:
    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_fetch_widget_exception(self, mock_q, mock_config, mock_auth_manager):
        """Lines 3346-3347: sn_query exception returns error."""
        mock_q.side_effect = Exception("Network error")
        result = resolve_widget_chain(
            mock_config,
            mock_auth_manager,
            ResolveWidgetChainParams(widget_id="w1"),
        )
        assert result["success"] is False
        assert "Failed to fetch widget" in result["error"]

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_widget_not_found(self, mock_q, mock_config, mock_auth_manager):
        mock_q.return_value = {"success": False}
        result = resolve_widget_chain(
            mock_config,
            mock_auth_manager,
            ResolveWidgetChainParams(widget_id="missing"),
        )
        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_depth_1_returns_widget_only(self, mock_q, mock_config, mock_auth_manager):
        mock_q.return_value = {
            "success": True,
            "results": [{"sys_id": "w1", "name": "W", "id": "w1", "script": "code"}],
        }
        result = resolve_widget_chain(
            mock_config,
            mock_auth_manager,
            ResolveWidgetChainParams(widget_id="w1", depth=1),
        )
        assert result["success"] is True
        assert result["providers"] == []
        assert result["script_includes"] == []

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_provider_m2m_exception_returns_warning(self, mock_q, mock_config, mock_auth_manager):
        """Lines 3382-3385: M2M fetch exception returns warning."""
        mock_q.side_effect = [
            {"success": True, "results": [{"sys_id": "w1", "name": "W", "id": "w1"}]},
            Exception("M2M error"),
        ]
        result = resolve_widget_chain(
            mock_config,
            mock_auth_manager,
            ResolveWidgetChainParams(widget_id="w1", depth=2),
        )
        assert result["success"] is True
        assert "Failed to fetch provider M2M" in result["warnings"][0]

    @patch("servicenow_mcp.tools.portal_tools.sn_query")
    def test_si_fetch_exception_returns_warning(self, mock_q, mock_config, mock_auth_manager):
        mock_q.side_effect = [
            {
                "success": True,
                "results": [
                    {"sys_id": "w1", "name": "W", "id": "w1", "script": "var x = new MySI();"}
                ],
            },
            {"success": True, "results": [{"sp_angular_provider": {"value": "p1"}}]},
            {
                "success": True,
                "results": [
                    {
                        "sys_id": "p1",
                        "name": "P1",
                        "type": "factory",
                        "script": "var y = new OtherSI();",
                    }
                ],
            },
            Exception("SI error"),
        ]
        result = resolve_widget_chain(
            mock_config,
            mock_auth_manager,
            ResolveWidgetChainParams(widget_id="w1", depth=3),
        )
        assert result["success"] is True
        assert "Failed to fetch script includes" in result["warnings"][0]


# ---------------------------------------------------------------------------
# resolve_page_dependencies — lines 3575-3576, 3591-3598, 3639-3640, 3659-3660,
#                              3681-3683, 3710-3712, 3725, 3735-3737, 3755-3757,
#                              3775, 3791-3794, 3799-3802
# ---------------------------------------------------------------------------


class TestResolvePageDependencies:
    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_get_page_exception_returns_error(self, mock_gp, mock_config, mock_auth_manager):
        mock_gp.side_effect = Exception("Page fetch failed")
        result = resolve_page_dependencies(
            mock_config,
            mock_auth_manager,
            ResolvePageDependenciesParams(page_id="missing"),
        )
        assert result["success"] is False
        assert "Failed to get page" in result["error"]

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_layout_walk_extracts_widget_ids(self, mock_gp, mock_config, mock_auth_manager):
        """Lines 3591-3598: nested layout tree walk."""
        mock_gp.return_value = {
            "success": True,
            "page": {
                "layout": {
                    "containers": [
                        {
                            "rows": [
                                {
                                    "columns": [
                                        {
                                            "widget_sys_id": "w1",
                                            "widget_name": "Widget1",
                                        },
                                        {
                                            "widget": {"sys_id": "w2", "name": "Widget2"},
                                        },
                                    ]
                                }
                            ]
                        }
                    ]
                }
            },
            "instances": [],
        }
        with patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q:
            mock_q.return_value = {
                "success": True,
                "results": [
                    {"sys_id": "w1", "name": "Widget1", "id": "w1"},
                    {"sys_id": "w2", "name": "Widget2", "id": "w2"},
                ],
            }
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(page_id="test_page", depth=1),
            )
        assert result["success"] is True
        assert len(result["widgets"]) == 2

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_no_widgets_returns_empty(self, mock_gp, mock_config, mock_auth_manager):
        mock_gp.return_value = {"success": True, "page": {"layout": {}}, "instances": []}
        result = resolve_page_dependencies(
            mock_config,
            mock_auth_manager,
            ResolvePageDependenciesParams(page_id="empty_page"),
        )
        assert result["success"] is True
        assert result["widgets"] == []

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_widget_fetch_exception_returns_error(self, mock_gp, mock_config, mock_auth_manager):
        """Lines 3639-3640: widget fetch exception."""
        mock_gp.return_value = {
            "success": True,
            "page": {"layout": {"widget_sys_id": "w1"}},
            "instances": [],
        }
        with patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q:
            mock_q.side_effect = Exception("Widget fetch failed")
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(page_id="test", depth=1),
            )
        assert result["success"] is False
        assert "Failed to fetch widgets" in result["error"]

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_depth_1_returns_no_providers(self, mock_gp, mock_config, mock_auth_manager):
        """Lines 3659-3660: depth < 2 returns without providers."""
        mock_gp.return_value = {
            "success": True,
            "page": {"layout": {"widget_sys_id": "w1"}},
            "instances": [],
        }
        with patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q:
            mock_q.return_value = {
                "success": True,
                "results": [{"sys_id": "w1", "name": "W", "id": "w1"}],
            }
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(page_id="test", depth=1),
            )
        assert result["success"] is True
        assert result["providers"] == []

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_m2m_fetch_exception_adds_warning(self, mock_gp, mock_config, mock_auth_manager):
        """Lines 3681-3683: M2M fetch exception adds warning."""
        mock_gp.return_value = {
            "success": True,
            "page": {"layout": {"widget_sys_id": "w1"}},
            "instances": [],
        }
        with patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q:
            mock_q.side_effect = [
                {"success": True, "results": [{"sys_id": "w1", "name": "W", "id": "w1"}]},
                Exception("M2M error"),
            ]
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(page_id="test", depth=2),
            )
        assert result["success"] is True
        assert any("Failed to fetch provider M2M" in w for w in result.get("warnings", []))

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_provider_fetch_exception_adds_warning(self, mock_gp, mock_config, mock_auth_manager):
        """Lines 3710-3712: provider fetch exception adds warning."""
        mock_gp.return_value = {
            "success": True,
            "page": {"layout": {"widget_sys_id": "w1"}},
            "instances": [],
        }
        with patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q:
            mock_q.side_effect = [
                {"success": True, "results": [{"sys_id": "w1", "name": "W", "id": "w1"}]},
                {
                    "success": True,
                    "results": [
                        {"sp_widget": {"value": "w1"}, "sp_angular_provider": {"value": "p1"}}
                    ],
                },
                Exception("Provider fetch error"),
            ]
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(page_id="test", depth=2),
            )
        assert result["success"] is True
        assert any("Failed to fetch providers" in w for w in result.get("warnings", []))

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_depth_2_returns_dep_map_no_si(self, mock_gp, mock_config, mock_auth_manager):
        """Line 3725: depth < 3 returns with dependency_map."""
        mock_gp.return_value = {
            "success": True,
            "page": {"layout": {"widget_sys_id": "w1"}},
            "instances": [],
        }
        with patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q:
            mock_q.side_effect = [
                {"success": True, "results": [{"sys_id": "w1", "name": "W", "id": "w1"}]},
                {"success": True, "results": []},
            ]
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(page_id="test", depth=2),
            )
        assert result["success"] is True
        assert "dependency_map" in result

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_si_scan_from_widget_and_provider_scripts(
        self, mock_gp, mock_config, mock_auth_manager
    ):
        """Lines 3735-3737: SI names extracted from widget and provider scripts."""
        mock_gp.return_value = {
            "success": True,
            "page": {"layout": {"widget_sys_id": "w1"}},
            "instances": [],
        }
        with patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q:
            mock_q.side_effect = [
                # widget fetch
                {
                    "success": True,
                    "results": [
                        {
                            "sys_id": "w1",
                            "name": "W",
                            "id": "w1",
                            "script": "var x = new MyHelper();",
                        }
                    ],
                },
                # M2M
                {
                    "success": True,
                    "results": [
                        {"sp_widget": {"value": "w1"}, "sp_angular_provider": {"value": "p1"}}
                    ],
                },
                # provider detail
                {
                    "success": True,
                    "results": [
                        {
                            "sys_id": "p1",
                            "name": "prov1",
                            "type": "factory",
                            "script": "var y = new AnotherSI();",
                        }
                    ],
                },
                # SI fetch
                {
                    "success": True,
                    "results": [
                        {
                            "sys_id": "si1",
                            "name": "MyHelper",
                            "api_name": "MyHelper",
                            "script": "help()",
                            "client_callable": "false",
                        },
                        {
                            "sys_id": "si2",
                            "name": "AnotherSI",
                            "api_name": "AnotherSI",
                            "script": "doit()",
                            "client_callable": "false",
                        },
                    ],
                },
            ]
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(page_id="test", depth=3),
            )
        assert result["success"] is True
        assert len(result["script_includes"]) == 2
        assert result["summary"] is not None

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_si_fetch_exception_adds_warning(self, mock_gp, mock_config, mock_auth_manager):
        """Lines 3755-3757: SI fetch exception adds warning."""
        mock_gp.return_value = {
            "success": True,
            "page": {"layout": {"widget_sys_id": "w1"}},
            "instances": [],
        }
        with patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q:
            mock_q.side_effect = [
                {
                    "success": True,
                    "results": [
                        {"sys_id": "w1", "name": "W", "id": "w1", "script": "var x = new MySI();"}
                    ],
                },
                {
                    "success": True,
                    "results": [
                        {"sp_widget": {"value": "w1"}, "sp_angular_provider": {"value": "p1"}}
                    ],
                },
                {
                    "success": True,
                    "results": [
                        {
                            "sys_id": "p1",
                            "name": "P1",
                            "type": "factory",
                            "script": "var y = new OtherHelper();",
                        }
                    ],
                },
                Exception("SI error"),
            ]
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(page_id="test", depth=3),
            )
        assert result["success"] is True
        assert any("Failed to fetch script includes" in w for w in result.get("warnings", []))

    @patch("servicenow_mcp.tools.portal_management_tools.get_page")
    def test_save_to_disk_creates_files(self, mock_gp, mock_config, mock_auth_manager, tmp_path):
        """Lines 3775, 3791-3794, 3799-3802: save_to_disk writes files."""
        mock_gp.return_value = {
            "success": True,
            "page": {"id": "test_page", "title": "Test Page", "layout": {"widget_sys_id": "w1"}},
            "instances": [],
        }
        with (
            patch("servicenow_mcp.tools.portal_tools.sn_query") as mock_q,
            patch("pathlib.Path.cwd", return_value=tmp_path),
        ):
            mock_q.side_effect = [
                {
                    "success": True,
                    "results": [
                        {
                            "sys_id": "w1",
                            "name": "W",
                            "id": "w1",
                            "script": "var x = new MySI();",
                            "template": "<div>hi</div>",
                        }
                    ],
                },
                {
                    "success": True,
                    "results": [
                        {"sp_widget": {"value": "w1"}, "sp_angular_provider": {"value": "p1"}}
                    ],
                },
                {
                    "success": True,
                    "results": [
                        {
                            "sys_id": "p1",
                            "name": "prov1",
                            "type": "factory",
                            "script": "angular.module('x').factory('prov1', function(){});",
                        }
                    ],
                },
                {
                    "success": True,
                    "results": [
                        {
                            "sys_id": "si1",
                            "name": "MySI",
                            "api_name": "MySI",
                            "script": "function help(){}",
                            "client_callable": "false",
                        }
                    ],
                },
            ]
            result = resolve_page_dependencies(
                mock_config,
                mock_auth_manager,
                ResolvePageDependenciesParams(
                    page_id="test_page",
                    depth=3,
                    save_to_disk=True,
                    include_fields=["script", "template"],
                ),
            )
        assert result["success"] is True
        assert "saved_to" in result
        saved_dir = Path(result["saved_to"])
        assert saved_dir.exists()
        # Check that widget, provider, and SI files were written
        assert (saved_dir / "_dependency_map.json").exists()


# ---------------------------------------------------------------------------
# _build_dep_map — shared provider detection
# ---------------------------------------------------------------------------


class TestBuildDepMap:
    def test_shared_provider_detected(self):
        widgets = [
            {"sys_id": "w1", "name": "W1", "id": "w1"},
            {"sys_id": "w2", "name": "W2", "id": "w2"},
        ]
        widget_to_providers = {"w1": ["p1"], "w2": ["p1"]}
        providers = [{"sys_id": "p1", "name": "sharedProv"}]
        result = _build_dep_map(widgets, widget_to_providers, providers)
        assert "sharedProv" in result["shared_providers"]
        assert result["shared_providers"]["sharedProv"]["used_by_widgets"] == 2

    def test_with_script_includes(self):
        widgets = [{"sys_id": "w1", "name": "W1", "id": "w1"}]
        widget_to_providers = {"w1": []}
        providers = []
        script_includes = [{"sys_id": "si1", "name": "MySI"}]
        result = _build_dep_map(widgets, widget_to_providers, providers, script_includes)
        assert "MySI" in result["script_includes"]


# ---------------------------------------------------------------------------
# download_portal_sources — edge cases (lines 3067-3068, 3200-3201)
# ---------------------------------------------------------------------------


class TestDownloadPortalSourcesEdgeCases:
    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    @patch("servicenow_mcp.tools.portal_tools.sn_query_page")
    def test_provider_script_exception_skipped(
        self, mock_page, mock_qa, mock_config, mock_auth_manager, tmp_path
    ):
        """Lines 3200-3201: provider script fetch exception is silently caught."""
        mock_qa.side_effect = [
            # widgets
            [
                {
                    "sys_id": "wid1",
                    "name": "W",
                    "id": "w",
                    "sys_scope": "x_app",
                    "template": "",
                    "script": "",
                    "client_script": "",
                    "link": "",
                    "css": "",
                    "option_schema": "",
                    "demo_data": "",
                }
            ],
            # M2M
            [{"sp_widget": {"value": "wid1"}, "sp_angular_provider": {"value": "prov1"}}],
            # provider metadata
            [{"sys_id": "prov1", "name": "prov1", "type": "factory", "sys_scope": "global"}],
        ]
        mock_page.side_effect = Exception("Script fetch failed")
        result = download_portal_sources(
            mock_config,
            mock_auth_manager,
            DownloadPortalSourcesParams(
                output_dir=str(tmp_path),
                scope="x_app",
                include_linked_angular_providers=True,
            ),
        )
        assert result["success"] is True
        # Provider script file should NOT exist since fetch failed
        assert not (tmp_path / "x_app" / "sp_angular_provider" / "prov1.script.js").exists()

    @patch("servicenow_mcp.tools.portal_tools.sn_query_all")
    def test_widget_with_no_ref_candidates(self, mock_qa, mock_config, mock_auth_manager, tmp_path):
        """Lines 3067-3068: widget with no SI refs in script/client_script."""
        mock_qa.return_value = [
            {
                "sys_id": "wid1",
                "name": "Simple Widget",
                "id": "simple_widget",
                "sys_scope": "x_app",
                "template": "<div>hello</div>",
                "script": "var x = 1;",
                "client_script": "",
                "link": "",
                "css": "",
                "option_schema": "",
                "demo_data": "",
            }
        ]
        result = download_portal_sources(
            mock_config,
            mock_auth_manager,
            DownloadPortalSourcesParams(
                output_dir=str(tmp_path),
                scope="x_app",
                include_linked_script_includes=True,
            ),
        )
        assert result["success"] is True
        # No script include candidates from simple script
        assert result["summary"]["script_includes"] == 0


# ---------------------------------------------------------------------------
# Helper: _safe_name, _extract_ref_candidates, _to_one_line, _slice_one_line_snippet
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_safe_name_handles_special_chars(self):
        assert "/" not in _safe_name("widget/with/slashes")
        assert " " not in _safe_name("widget with spaces")

    def test_extract_ref_candidates_ignores_known_constructors(self):
        result = _extract_ref_candidates("var x = new GlideRecord('task');")
        assert result == []

    def test_extract_ref_candidates_finds_custom_si(self):
        result = _extract_ref_candidates("var x = new CustomHelper();")
        assert "CustomHelper" in result

    def test_to_one_line_collapses_whitespace(self):
        assert _to_one_line("  hello\n  world  ") == "hello world"

    def test_slice_one_line_snippet(self):
        source = "prefix MATCH_CONTENT suffix and more text after"
        idx = source.index("MATCH_CONTENT")
        result = _slice_one_line_snippet(source, idx, idx + 14, 50)
        assert "MATCH_CONTENT" in result

    def test_deduplicate_fields_preserves_order(self):
        assert _dedupe_fields(["a", "b", "a", "c"]) == ["a", "b", "c"]

    def test_deduplicate_preserve_order(self):
        assert _dedupe_preserve_order(["z", "a", "z", "b"]) == ["z", "a", "b"]

    def test_looks_like_regex(self):
        assert _looks_like_regex(r"\d+") is True
        assert _looks_like_regex("simple_text") is False

    def test_escape_query(self):
        assert "^^" in _escape_query("test^value")
        assert "\\=" in _escape_query("test=val")
        assert "\\@" in _escape_query("test@val")

    def test_extract_click_handlers(self):
        template = '<button ng-click="doSave()">Save</button>'
        result = _extract_click_handlers(template)
        assert "doSave()" in result
        assert "doSave" in result

    def test_extract_click_handlers_empty(self):
        assert _extract_click_handlers("") == []

    def test_compile_search_pattern_literal(self):
        pat, resolved, mode = _compile_search_pattern("hello", "literal")
        assert mode == "literal"
        assert pat.search("hello") is not None

    def test_compile_search_pattern_auto(self):
        pat, resolved, mode = _compile_search_pattern("hello", "auto")
        assert mode == "literal"
        pat2, _, mode2 = _compile_search_pattern(r"\d+", "auto")
        assert mode2 == "regex"

    def test_as_ref_sys_id(self):
        from servicenow_mcp.tools.portal_tools import _as_ref_sys_id

        assert _as_ref_sys_id({"value": "abc"}) == "abc"
        assert _as_ref_sys_id("xyz") == "xyz"
        assert _as_ref_sys_id({"value": ""}) is None
        assert _as_ref_sys_id(123) is None

    def test_field_change_summary_changed(self):
        result = _build_field_change_summary("script", "old", "new")
        assert result["changed"] is True
        assert result["delta_length"] == len("new") - len("old")

    def test_field_change_summary_unchanged(self):
        result = _build_field_change_summary("script", "same", "same")
        assert result["changed"] is False
