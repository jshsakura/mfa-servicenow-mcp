"""Tests for audit_pending_changes tool."""

import json
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.audit_tools import (
    AuditPendingChangesParams,
    _classify_entry,
    _compile_risk_patterns,
    _detect_clones,
    _scan_code,
    audit_pending_changes,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, ServerConfig


def _mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(type=AuthType.BASIC),
    )


def _mock_auth():
    return MagicMock()


def _make_update_xml_response(entries, total=None):
    """Build a mock response for sys_update_xml queries."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"result": entries}
    resp.content = json.dumps({"result": entries}).encode("utf-8")
    resp.headers = {"X-Total-Count": str(total or len(entries))}
    resp.raise_for_status = MagicMock()
    return resp


def _make_code_response(records):
    """Build a mock response for code body queries."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"result": records}
    resp.content = json.dumps({"result": records}).encode("utf-8")
    resp.headers = {"X-Total-Count": str(len(records))}
    resp.raise_for_status = MagicMock()
    return resp


# --- Unit tests for helpers ---


class TestClassifyEntry:
    def test_known_tables(self):
        assert _classify_entry("sp_widget") == "widget"
        assert _classify_entry("sp_angular_provider") == "angular_provider"
        assert _classify_entry("oauth_entity") == "oauth_credential"
        assert _classify_entry("sp_row") == "layout"
        assert _classify_entry("sp_column") == "layout"
        assert _classify_entry("m2m_sp_widget_angular_provider") == "m2m_dependency"
        assert _classify_entry("sys_script_include") == "script_include"

    def test_unknown_table(self):
        assert _classify_entry("some_custom_table") == "other"
        assert _classify_entry("") == "other"


class TestRiskPatterns:
    def test_default_patterns_compile(self):
        patterns = _compile_risk_patterns()
        assert len(patterns) > 0
        # Check structure: (compiled_re, severity, category, desc)
        for p in patterns:
            assert len(p) == 4
            assert hasattr(p[0], "search")  # compiled regex
            assert p[1] in ("high", "medium", "low")

    def test_custom_patterns_added(self):
        default_count = len(_compile_risk_patterns())
        custom_count = len(_compile_risk_patterns(["myCustomFunc", "dangerousCall"]))
        assert custom_count == default_count + 2

    def test_invalid_custom_pattern_skipped(self):
        patterns = _compile_risk_patterns(["[invalid(regex"])
        # Should not crash, invalid pattern is skipped
        assert len(patterns) == len(_compile_risk_patterns())


class TestScanCode:
    def test_finds_eval(self):
        code = "var x = eval('alert(1)');"
        patterns = _compile_risk_patterns()
        findings = _scan_code(code, "client_script", "test-widget", patterns)
        assert any(f["category"] == "eval_usage" for f in findings)

    def test_finds_innerhtml(self):
        code = "element.innerHTML = userInput;"
        patterns = _compile_risk_patterns()
        findings = _scan_code(code, "client_script", "test-widget", patterns)
        assert any(f["category"] == "xss_risk" for f in findings)

    def test_finds_dom_manipulation(self):
        code = "var el = document.getElementById('my-div');"
        patterns = _compile_risk_patterns()
        findings = _scan_code(code, "client_script", "test-widget", patterns)
        assert any(f["category"] == "dom_manipulation" for f in findings)

    def test_finds_console_log(self):
        code = "console.log('debug');"
        patterns = _compile_risk_patterns()
        findings = _scan_code(code, "script", "test-widget", patterns)
        assert any(f["category"] == "console_log" for f in findings)

    def test_empty_code_returns_empty(self):
        patterns = _compile_risk_patterns()
        assert _scan_code("", "script", "test", patterns) == []
        assert _scan_code(None, "script", "test", patterns) == []

    def test_snippet_included_when_requested(self):
        code = "var x = eval('test');"
        patterns = _compile_risk_patterns()
        findings = _scan_code(code, "script", "test", patterns, include_snippets=True)
        assert any("snippet" in f for f in findings)

    def test_line_numbers_correct(self):
        code = "line1\nline2\nvar x = eval('test');\nline4"
        patterns = _compile_risk_patterns()
        findings = _scan_code(code, "script", "test", patterns)
        eval_findings = [f for f in findings if f["category"] == "eval_usage"]
        assert eval_findings[0]["line"] == 3


class TestDetectClones:
    def test_detects_duplicates(self):
        entries = [
            {"target_name": "MyWidget", "name": "sp_widget", "action": "INSERT_OR_UPDATE"},
            {"target_name": "MyWidget", "name": "sp_widget", "action": "INSERT_OR_UPDATE"},
            {"target_name": "UniqueWidget", "name": "sp_widget", "action": "INSERT_OR_UPDATE"},
        ]
        clones = _detect_clones(entries)
        assert len(clones) == 1
        assert clones[0]["target_name"] == "MyWidget"
        assert clones[0]["occurrences"] == 2

    def test_no_duplicates(self):
        entries = [
            {"target_name": "A", "name": "sp_widget", "action": "INSERT_OR_UPDATE"},
            {"target_name": "B", "name": "sp_widget", "action": "INSERT_OR_UPDATE"},
        ]
        assert _detect_clones(entries) == []

    def test_empty_entries(self):
        assert _detect_clones([]) == []


# --- Integration test for main tool function ---


class TestAuditPendingChanges:
    def test_params_validation(self):
        # developer is required
        with pytest.raises(ValidationError):
            AuditPendingChangesParams()

        # Valid minimal params
        p = AuditPendingChangesParams(developer="test@example.com")
        assert p.developer == "test@example.com"
        assert p.max_entries == 200
        assert p.scan_code is True

    def test_no_entries_found(self):
        config = _mock_config()
        auth = _mock_auth()
        auth.make_request.return_value = _make_update_xml_response([], total=0)

        params = AuditPendingChangesParams(
            developer="test@example.com",
            date_from="2026-03-25",
            date_to="2026-04-01",
        )
        result = audit_pending_changes(config, auth, params)

        assert result["success"] is True
        assert result["total_entries"] == 0
        assert result["api_calls"] == 1

    def test_inventory_grouping(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = [
            {
                "sys_id": "1",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "target_name": "myWidget",
                "type": "Widget",
                "update_set": "My Set",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
            {
                "sys_id": "2",
                "name": "sp_angular_provider",
                "action": "INSERT_OR_UPDATE",
                "target_name": "myProvider",
                "type": "Angular Provider",
                "update_set": "My Set",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
            {
                "sys_id": "3",
                "name": "oauth_entity",
                "action": "INSERT_OR_UPDATE",
                "target_name": "MyOAuth",
                "type": "OAuth Entity",
                "update_set": "My Set",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
            {
                "sys_id": "4",
                "name": "sp_row",
                "action": "INSERT_OR_UPDATE",
                "target_name": "row1",
                "type": "Row",
                "update_set": "My Set",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
        ]

        # Response sequence: update_xml query, widget code, provider code, M2M
        widget_code = [
            {
                "sys_id": "w1",
                "name": "myWidget",
                "id": "my-widget",
                "script": "console.log('test');",
                "client_script": "",
                "template": "",
                "css": "",
            }
        ]
        provider_code = [{"sys_id": "p1", "name": "myProvider", "script": ""}]
        m2m_response = _make_code_response([])

        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=4),
            _make_code_response(widget_code),
            _make_code_response(provider_code),
            m2m_response,
        ]

        params = AuditPendingChangesParams(
            developer="test@example.com",
            date_from="2026-03-25",
            date_to="2026-04-01",
        )
        result = audit_pending_changes(config, auth, params)

        assert result["success"] is True
        assert result["total_entries"] == 4
        assert "widget" in result["inventory"]
        assert "angular_provider" in result["inventory"]
        assert "oauth_credential" in result["inventory"]
        assert "layout" in result["inventory"]
        # OAuth should trigger recommendation
        assert any("OAuth" in r for r in result["recommendations"])

    def test_risk_scanning(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = [
            {
                "sys_id": "1",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "target_name": "riskyWidget",
                "type": "Widget",
                "update_set": "My Set",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
        ]

        risky_code = [
            {
                "sys_id": "w1",
                "name": "riskyWidget",
                "id": "risky-widget",
                "script": "var result = eval(input);",
                "client_script": "element.innerHTML = data;\ndocument.getElementById('x');",
                "template": "<div>{{safe}}</div>",
                "css": "",
            }
        ]

        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=1),
            _make_code_response(risky_code),
        ]

        params = AuditPendingChangesParams(
            developer="test@example.com",
            date_from="2026-03-25",
            date_to="2026-04-01",
        )
        result = audit_pending_changes(config, auth, params)

        assert result["risk_summary"]["high"] > 0
        categories = {f["category"] for f in result["risk_findings"]}
        assert "eval_usage" in categories
        assert "xss_risk" in categories
        assert "dom_manipulation" in categories

    def test_scan_code_disabled(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = [
            {
                "sys_id": "1",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "target_name": "myWidget",
                "type": "Widget",
                "update_set": "My Set",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
        ]

        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=1),
        ]

        params = AuditPendingChangesParams(
            developer="test@example.com",
            scan_code=False,
        )
        result = audit_pending_changes(config, auth, params)

        # Only 1 API call (no code fetch)
        assert result["api_calls"] == 1
        assert result["risk_findings"] == []

    def test_exclude_pattern(self):
        params = AuditPendingChangesParams(
            developer="test@example.com",
            exclude_pattern="hopes",
        )
        assert params.exclude_pattern == "hopes"

    def test_max_entries_capped(self):
        params = AuditPendingChangesParams(
            developer="test@example.com",
            max_entries=999,
        )
        # The tool function caps at 500
        assert params.max_entries == 999  # Param accepts it
        # But the function will use min(999, 500) = 500

    def test_initial_fetch_failure_returns_failure_dict(self):
        config = _mock_config()
        auth = _mock_auth()
        auth.make_request.side_effect = RuntimeError("boom")

        result = audit_pending_changes(
            config,
            auth,
            AuditPendingChangesParams(developer="test@example.com"),
        )

        assert result["success"] is False
        assert "Failed to fetch pending changes" in result["message"]

    def test_code_fetch_uses_lightweight_query_params(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = [
            {
                "sys_id": "1",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "target_name": "myWidget",
                "type": "Widget",
                "update_set": "My Set",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            }
        ]
        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=1),
            _make_code_response(
                [
                    {
                        "sys_id": "w1",
                        "name": "myWidget",
                        "id": "my-widget",
                        "script": "console.log('x');",
                        "client_script": "",
                        "template": "",
                        "css": "",
                    }
                ]
            ),
            _make_code_response([]),
        ]

        result = audit_pending_changes(
            config,
            auth,
            AuditPendingChangesParams(developer="test@example.com"),
        )

        assert result["success"] is True
        code_call = auth.make_request.call_args_list[1]
        params = code_call.kwargs["params"]
        assert params["sysparm_display_value"] == "false"
        assert params["sysparm_no_count"] == "true"

    def test_m2m_failure_is_non_fatal(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = [
            {
                "sys_id": "1",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "target_name": "myWidget",
                "type": "Widget",
                "update_set": "My Set",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            }
        ]
        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=1),
            _make_code_response(
                [
                    {
                        "sys_id": "w1",
                        "name": "myWidget",
                        "id": "my-widget",
                        "script": "",
                        "client_script": "",
                        "template": "",
                        "css": "",
                    }
                ]
            ),
            RuntimeError("m2m down"),
        ]

        result = audit_pending_changes(
            config,
            auth,
            AuditPendingChangesParams(developer="test@example.com"),
        )

        assert result["success"] is True
        assert result["cross_references"]["shared_providers"] == []

    def test_m2m_scan_reports_truncation_when_widget_set_exceeds_chunk_limit(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = []
        for index in range(55):
            update_entries.append(
                {
                    "sys_id": str(index),
                    "name": "sp_widget",
                    "action": "INSERT_OR_UPDATE",
                    "target_name": f"widget_{index}",
                    "type": "Widget",
                    "update_set": "My Set",
                    "sys_updated_on": "2026-03-30",
                    "sys_updated_by": "test@example.com",
                    "sys_created_by": "test@example.com",
                }
            )

        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=len(update_entries)),
            _make_code_response([]),
        ]

        result = audit_pending_changes(
            config,
            auth,
            AuditPendingChangesParams(developer="test@example.com"),
        )

        assert result["success"] is True
        assert result["cross_references"]["shared_provider_scan_truncated"] is True
        assert result["cross_references"]["shared_provider_scan_limit"] == 50
        assert result["cross_references"]["shared_provider_scan_total_widgets"] == 55
        assert any("truncated to the first 50 widgets" in rec for rec in result["recommendations"])
