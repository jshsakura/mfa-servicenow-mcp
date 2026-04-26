"""Tests for _preview.py — build_delete_preview and build_update_preview uncovered paths."""

from unittest.mock import MagicMock, patch

from servicenow_mcp.tools._preview import build_delete_preview, build_update_preview


def _mock_config():
    return MagicMock()


def _mock_auth():
    return MagicMock()


class TestBuildDeletePreview:
    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_target_not_found(self, mock_query):
        mock_query.side_effect = Exception("connection failed")
        result = build_delete_preview(
            _mock_config(),
            _mock_auth(),
            table="incident",
            sys_id="nonexistent",
        )
        assert result["target_found"] is False
        assert any("not found" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_target_found_no_deps(self, mock_query):
        mock_query.return_value = ([{"sys_id": "abc123", "sys_scope": "global"}], 1)
        result = build_delete_preview(
            _mock_config(),
            _mock_auth(),
            table="incident",
            sys_id="abc123",
        )
        assert result["target_found"] is True
        assert result["target_record"]["sys_id"] == "abc123"
        assert result["dependencies"] == {}

    @patch("servicenow_mcp.tools._preview.sn_count")
    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_dependency_count_positive(self, mock_query, mock_count):
        mock_query.return_value = (
            [{"sys_id": "wf001", "sys_scope": "global", "name": "My Workflow"}],
            1,
        )
        mock_count.return_value = 5
        result = build_delete_preview(
            _mock_config(),
            _mock_auth(),
            table="wf_workflow",
            sys_id="wf001",
            identifier_fields=["name"],
            dependency_checks=[
                {"table": "wf_activity", "field": "workflow", "label": "activities"}
            ],
        )
        assert result["dependencies"]["activities"] == 5
        assert any("5 activities" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools._preview.sn_count")
    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_dependency_count_zero(self, mock_query, mock_count):
        mock_query.return_value = ([{"sys_id": "wf001", "sys_scope": "global"}], 1)
        mock_count.return_value = 0
        result = build_delete_preview(
            _mock_config(),
            _mock_auth(),
            table="wf_workflow",
            sys_id="wf001",
            dependency_checks=[
                {"table": "wf_activity", "field": "workflow", "label": "activities"}
            ],
        )
        assert result["dependencies"]["activities"] == 0
        assert not any("activities" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools._preview.sn_count")
    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_dependency_count_fails(self, mock_query, mock_count):
        mock_query.return_value = ([{"sys_id": "wf001", "sys_scope": "global"}], 1)
        mock_count.side_effect = Exception("timeout")
        result = build_delete_preview(
            _mock_config(),
            _mock_auth(),
            table="wf_workflow",
            sys_id="wf001",
            dependency_checks=[
                {"table": "wf_activity", "field": "workflow", "label": "activities"}
            ],
        )
        assert result["dependencies"]["activities"] is None
        assert any("count failed" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_empty_rows_returned(self, mock_query):
        mock_query.return_value = ([], 0)
        result = build_delete_preview(
            _mock_config(),
            _mock_auth(),
            table="incident",
            sys_id="nonexistent",
        )
        assert result["target_found"] is False

    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_target_record_filters_empty_values(self, mock_query):
        mock_query.return_value = ([{"sys_id": "abc", "sys_scope": "", "name": None}], 1)
        result = build_delete_preview(
            _mock_config(),
            _mock_auth(),
            table="incident",
            sys_id="abc",
            identifier_fields=["name"],
        )
        assert result["target_found"] is True
        assert "sys_scope" not in result["target_record"]
        assert "name" not in result["target_record"]


class TestBuildUpdatePreview:
    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_target_not_found(self, mock_query):
        mock_query.side_effect = Exception("connection failed")
        result = build_update_preview(
            _mock_config(),
            _mock_auth(),
            table="incident",
            sys_id="nonexistent",
            proposed={"state": "3"},
        )
        assert result["target_found"] is False
        assert any("not found" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_all_no_op_fields(self, mock_query):
        mock_query.return_value = ([{"sys_id": "inc001", "sys_scope": "global", "state": "3"}], 1)
        result = build_update_preview(
            _mock_config(),
            _mock_auth(),
            table="incident",
            sys_id="inc001",
            proposed={"state": "3"},
        )
        assert result["no_op_fields"] == ["state"]
        assert result["proposed_changes"] == {}
        assert any("no effective changes" in w for w in result["warnings"])

    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_mixed_changes_and_no_ops(self, mock_query):
        mock_query.return_value = (
            [
                {
                    "sys_id": "inc001",
                    "sys_scope": "global",
                    "state": "1",
                    "priority": "2",
                    "short_description": "old",
                }
            ],
            1,
        )
        result = build_update_preview(
            _mock_config(),
            _mock_auth(),
            table="incident",
            sys_id="inc001",
            proposed={"state": "3", "priority": "2"},
            identifier_fields=["short_description"],
        )
        assert "state" in result["proposed_changes"]
        assert result["proposed_changes"]["state"]["before"] == "1"
        assert result["proposed_changes"]["state"]["after"] == "3"
        assert "priority" in result["no_op_fields"]

    @patch("servicenow_mcp.tools._preview.sn_query_page")
    def test_empty_rows_returned(self, mock_query):
        mock_query.return_value = ([], 0)
        result = build_update_preview(
            _mock_config(),
            _mock_auth(),
            table="incident",
            sys_id="nonexistent",
            proposed={"state": "3"},
        )
        assert result["target_found"] is False
