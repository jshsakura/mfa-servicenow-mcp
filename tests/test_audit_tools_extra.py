"""Extra tests for audit_tools.py — covering missed lines 165, 167-169, 189-190, 246,
349-351, 353, 355, 524-527, 536-538, 559-560."""

import json
from unittest.mock import MagicMock

from servicenow_mcp.tools.audit_tools import (
    AuditPendingChangesParams,
    _compact_record,
    _compile_risk_patterns,
    _detect_clones,
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
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"result": entries}
    resp.content = json.dumps({"result": entries}).encode("utf-8")
    resp.headers = {"X-Total-Count": str(total or len(entries))}
    resp.raise_for_status = MagicMock()
    return resp


def _make_code_response(records):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"result": records}
    resp.content = json.dumps({"result": records}).encode("utf-8")
    resp.headers = {"X-Total-Count": str(len(records))}
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# Lines 165, 167-169: _compact_record dict branch with display_value
# ---------------------------------------------------------------------------


class TestCompactRecord:
    def test_dict_with_display_value_preserved(self):
        row = {
            "name": {"display_value": "My Widget", "value": "abc123"},
            "active": "true",
        }
        result = _compact_record(row)
        assert result["name"] == "My Widget"
        assert result["active"] == "true"

    def test_dict_with_empty_display_value_skipped(self):
        row = {
            "name": {"display_value": "", "value": "abc123"},
            "active": "true",
        }
        result = _compact_record(row)
        assert "name" not in result
        assert result["active"] == "true"

    def test_none_values_skipped(self):
        row = {"name": None, "active": "true"}
        result = _compact_record(row)
        assert "name" not in result

    def test_empty_string_skipped(self):
        row = {"name": "", "active": "true"}
        result = _compact_record(row)
        assert "name" not in result

    def test_non_dict_values_pass_through(self):
        row = {"count": 5, "flag": True}
        result = _compact_record(row)
        assert result["count"] == 5
        assert result["flag"] is True


# ---------------------------------------------------------------------------
# Lines 189-190: invalid default risk pattern
# ---------------------------------------------------------------------------


class TestInvalidDefaultPattern:
    def test_invalid_default_pattern_logged(self):
        """Simulate an invalid default pattern by patching DEFAULT_RISK_PATTERNS."""
        from unittest.mock import patch

        bad_patterns = {"high": [("[invalid(regex", "test_cat", "bad pattern")]}
        with patch("servicenow_mcp.tools.audit_tools.DEFAULT_RISK_PATTERNS", bad_patterns):
            patterns = _compile_risk_patterns()
            assert len(patterns) == 0


# ---------------------------------------------------------------------------
# Line 246: _detect_clones with empty target_name
# ---------------------------------------------------------------------------


class TestDetectClonesEmptyTarget:
    def test_empty_target_name_skipped(self):
        entries = [
            {"target_name": "", "name": "sp_widget", "action": "INSERT"},
            {"target_name": "ValidWidget", "name": "sp_widget", "action": "INSERT"},
        ]
        clones = _detect_clones(entries)
        assert len(clones) == 0

    def test_missing_target_name_skipped(self):
        entries = [
            {"name": "sp_widget", "action": "INSERT"},
            {"target_name": "ValidWidget", "name": "sp_widget", "action": "INSERT"},
        ]
        clones = _detect_clones(entries)
        assert len(clones) == 0


# ---------------------------------------------------------------------------
# Lines 349-351, 353, 355: exclude_pattern, scope, update_set filters
# ---------------------------------------------------------------------------


class TestAuditQueryFilters:
    def test_exclude_pattern_and_scope_and_update_set(self):
        config = _mock_config()
        auth = _mock_auth()
        auth.make_request.return_value = _make_update_xml_response([], total=0)

        params = AuditPendingChangesParams(
            developer="test@example.com",
            exclude_pattern="test_exclude",
            scope="x_my_app",
            update_set="My Update Set",
            date_from="2026-03-01",
            date_to="2026-04-01",
        )
        result = audit_pending_changes(config, auth, params)

        assert result["success"] is True
        call_args = auth.make_request.call_args
        query = call_args.kwargs.get("params", {}).get("sysparm_query", "")
        assert "NOT LIKE" in query
        assert "x_my_app" in query
        assert "My Update Set" in query

    def test_scope_filter_only(self):
        config = _mock_config()
        auth = _mock_auth()
        auth.make_request.return_value = _make_update_xml_response([], total=0)

        params = AuditPendingChangesParams(
            developer="test@example.com",
            scope="x_my_app",
        )
        result = audit_pending_changes(config, auth, params)
        assert result["success"] is True

    def test_update_set_filter_only(self):
        config = _mock_config()
        auth = _mock_auth()
        auth.make_request.return_value = _make_update_xml_response([], total=0)

        params = AuditPendingChangesParams(
            developer="test@example.com",
            update_set="My Set",
        )
        result = audit_pending_changes(config, auth, params)
        assert result["success"] is True


# ---------------------------------------------------------------------------
# Lines 524-527: M2M shared providers (actual shared providers found)
# ---------------------------------------------------------------------------


class TestM2MSharedProviders:
    def test_shared_providers_detected(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = [
            {
                "sys_id": "1",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "target_name": "WidgetA",
                "type": "Widget",
                "update_set": "Set1",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
            {
                "sys_id": "2",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "target_name": "WidgetB",
                "type": "Widget",
                "update_set": "Set1",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
        ]

        widget_code = [
            {
                "sys_id": "w1",
                "name": "WidgetA",
                "id": "widget-a",
                "script": "",
                "client_script": "",
                "template": "",
                "css": "",
            },
            {
                "sys_id": "w2",
                "name": "WidgetB",
                "id": "widget-b",
                "script": "",
                "client_script": "",
                "template": "",
                "css": "",
            },
        ]

        m2m_records = [
            {"sys_id": "m1", "sp_widget": "WidgetA", "sp_angular_provider": "SharedProv"},
            {"sys_id": "m2", "sp_widget": "WidgetB", "sp_angular_provider": "SharedProv"},
        ]

        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=2),
            _make_code_response(widget_code),
            _make_code_response(m2m_records),
        ]

        params = AuditPendingChangesParams(
            developer="test@example.com",
            date_from="2026-03-25",
            date_to="2026-04-01",
        )
        result = audit_pending_changes(config, auth, params)

        assert result["success"] is True
        assert len(result["cross_references"]["shared_providers"]) == 1
        assert result["cross_references"]["shared_providers"][0]["provider"] == "SharedProv"
        assert len(result["cross_references"]["shared_providers"][0]["used_by_widgets"]) == 2


# ---------------------------------------------------------------------------
# Lines 536-538: M2M query failure in cross-reference phase
# (Already tested in test_audit_tools.py::test_m2m_failure_is_non_fatal, but ensure lines)
# ---------------------------------------------------------------------------


class TestM2MQueryException:
    def test_m2m_exception_with_widget_entries(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = [
            {
                "sys_id": "1",
                "name": "sp_widget",
                "action": "INSERT_OR_UPDATE",
                "target_name": "WidgetA",
                "type": "Widget",
                "update_set": "Set1",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
        ]

        widget_code = [
            {
                "sys_id": "w1",
                "name": "WidgetA",
                "id": "widget-a",
                "script": "",
                "client_script": "",
                "template": "",
                "css": "",
            },
        ]

        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=1),
            _make_code_response(widget_code),
            RuntimeError("M2M query failed"),
        ]

        params = AuditPendingChangesParams(
            developer="test@example.com",
        )
        result = audit_pending_changes(config, auth, params)

        assert result["success"] is True
        assert result["cross_references"]["shared_providers"] == []


# ---------------------------------------------------------------------------
# Lines 559-560: clone candidates recommendation
# ---------------------------------------------------------------------------


class TestCloneRecommendation:
    def test_clones_generate_recommendation(self):
        config = _mock_config()
        auth = _mock_auth()

        update_entries = [
            {
                "sys_id": "1",
                "name": "sys_script",
                "action": "INSERT_OR_UPDATE",
                "target_name": "CloneScript",
                "type": "Business Rule",
                "update_set": "Set1",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
            {
                "sys_id": "2",
                "name": "sys_script",
                "action": "INSERT_OR_UPDATE",
                "target_name": "CloneScript",
                "type": "Business Rule",
                "update_set": "Set1",
                "sys_updated_on": "2026-03-30",
                "sys_updated_by": "test@example.com",
                "sys_created_by": "test@example.com",
            },
        ]

        auth.make_request.side_effect = [
            _make_update_xml_response(update_entries, total=2),
        ]

        params = AuditPendingChangesParams(
            developer="test@example.com",
            scan_code=False,
        )
        result = audit_pending_changes(config, auth, params)

        assert result["success"] is True
        assert len(result["clone_candidates"]) == 1
        assert any("duplicate" in r.lower() for r in result["recommendations"])
