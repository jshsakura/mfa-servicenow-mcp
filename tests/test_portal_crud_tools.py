"""Tests for portal_crud_tools.py — Phase 1-3 create/layout tools with safety features."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from servicenow_mcp.tools.portal_crud_tools import (
    ScaffoldPageParams,
    ScaffoldRowDef,
    _check_duplicate,
    _create_record,
    scaffold_page,
)
from servicenow_mcp.utils.config import ServerConfig

SCOPE = "scope-test-1"


@pytest.fixture
def mock_config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth={"type": "basic", "basic": {"username": "admin", "password": "password"}},
    )


@pytest.fixture
def mock_auth():
    auth = MagicMock()
    auth.get_headers.return_value = {"Authorization": "Basic ..."}
    return auth


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None if status_code < 400 else _raise_http()
    return resp


def _raise_http():
    from requests.exceptions import HTTPError

    raise HTTPError("Server error")


# ---------------------------------------------------------------------------
# _create_record helper
# ---------------------------------------------------------------------------
class TestCreateRecordHelper:
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_success(self, mock_cache, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response(
            {"result": {"sys_id": "abc", "name": "Test"}}
        )
        result = _create_record(mock_config, mock_auth, "sp_widget", {"name": "Test"})
        assert result["success"] is True
        assert result["result"]["sys_id"] == "abc"
        mock_cache.assert_called_once_with(table="sp_widget")

    def test_no_result_key(self, mock_config, mock_auth):
        mock_auth.make_request.return_value = _mock_response({"error": "bad"})
        result = _create_record(mock_config, mock_auth, "sp_widget", {"name": "Test"})
        assert result["success"] is False
        assert "No result" in result["message"]

    def test_exception(self, mock_config, mock_auth):
        mock_auth.make_request.side_effect = Exception("Connection failed")
        result = _create_record(mock_config, mock_auth, "sp_widget", {"name": "Test"})
        assert result["success"] is False
        assert "Connection failed" in result["message"]


# ---------------------------------------------------------------------------
# _check_duplicate helper
# ---------------------------------------------------------------------------
class TestCheckDuplicate:
    @patch("servicenow_mcp.tools.portal_crud_tools.sn_query_page")
    def test_found(self, mock_query, mock_config, mock_auth):
        mock_query.return_value = ([{"sys_id": "existing-1", "name": "Foo"}], 1)
        result = _check_duplicate(mock_config, mock_auth, "sp_widget", "name", "Foo", SCOPE)
        assert result is not None
        assert result["sys_id"] == "existing-1"

    @patch("servicenow_mcp.tools.portal_crud_tools.sn_query_page")
    def test_not_found(self, mock_query, mock_config, mock_auth):
        mock_query.return_value = ([], 0)
        result = _check_duplicate(mock_config, mock_auth, "sp_widget", "name", "NewWidget", SCOPE)
        assert result is None

    @patch("servicenow_mcp.tools.portal_crud_tools.sn_query_page")
    def test_exception_returns_none(self, mock_query, mock_config, mock_auth):
        mock_query.side_effect = Exception("API error")
        result = _check_duplicate(mock_config, mock_auth, "sp_widget", "name", "X", SCOPE)
        assert result is None


# ---------------------------------------------------------------------------
# Scope required validation
# ---------------------------------------------------------------------------
class TestScopeRequired:
    def test_scaffold_page_requires_scope(self):
        with pytest.raises(ValidationError):
            ScaffoldPageParams(page_id="x", title="X", rows=[ScaffoldRowDef(columns=[12])])


# ---------------------------------------------------------------------------
# scaffold_page
# ---------------------------------------------------------------------------
class TestScaffoldPage:
    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_full_success_no_widgets(self, mock_cache, mock_dup, mock_config, mock_auth):
        seq = 0

        def mock_post(method, url, **kwargs):
            nonlocal seq
            seq += 1
            table = url.split("/table/")[1]
            return _mock_response({"result": {"sys_id": f"{table}-{seq}"}})

        mock_auth.make_request.side_effect = mock_post

        params = ScaffoldPageParams(
            page_id="landing",
            title="Landing",
            scope=SCOPE,
            rows=[
                ScaffoldRowDef(columns=[6, 6]),
                ScaffoldRowDef(columns=[12]),
            ],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is True
        assert result["summary"]["rows"] == 2
        assert result["summary"]["columns"] == 3
        assert result["summary"]["widget_instances"] == 0
        assert result.get("errors") is None

    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_full_success_with_widgets(self, mock_cache, mock_dup, mock_config, mock_auth):
        seq = 0

        def mock_post(method, url, **kwargs):
            nonlocal seq
            seq += 1
            table = url.split("/table/")[1]
            return _mock_response({"result": {"sys_id": f"{table}-{seq}"}})

        mock_auth.make_request.side_effect = mock_post

        params = ScaffoldPageParams(
            page_id="dash",
            title="Dashboard",
            description="Main dashboard",
            css=".dash{}",
            public=True,
            scope=SCOPE,
            rows=[
                ScaffoldRowDef(
                    columns=[8, 4],
                    widgets=["wid-1", "wid-2"],
                    widget_params=['{"limit":5}', None],
                ),
            ],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is True
        assert result["summary"]["widget_instances"] == 2

    def test_invalid_column_sum(self, mock_config, mock_auth):
        params = ScaffoldPageParams(
            page_id="bad",
            title="Bad",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[6, 5])],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert "sum to 11" in result["message"]

    def test_widgets_length_mismatch(self, mock_config, mock_auth):
        params = ScaffoldPageParams(
            page_id="bad",
            title="Bad",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[6, 6], widgets=["w1"])],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert "widgets list length" in result["message"]

    def test_widget_params_length_mismatch(self, mock_config, mock_auth):
        params = ScaffoldPageParams(
            page_id="bad",
            title="Bad",
            scope=SCOPE,
            rows=[
                ScaffoldRowDef(columns=[6, 6], widget_params=['{"a":1}']),
            ],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert "widget_params length" in result["message"]

    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_page_creation_fails(self, mock_cache, mock_dup, mock_config, mock_auth):
        mock_auth.make_request.side_effect = Exception("Page fail")
        params = ScaffoldPageParams(
            page_id="fail",
            title="Fail",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[12])],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert "Failed to create page" in result["message"]

    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_container_creation_fails(self, mock_cache, mock_dup, mock_config, mock_auth):
        call_count = 0

        def mock_post(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_response({"result": {"sys_id": "pg-1"}})
            raise Exception("Container fail")

        mock_auth.make_request.side_effect = mock_post
        params = ScaffoldPageParams(
            page_id="cf",
            title="CF",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[12])],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert "Failed after page creation" in result["message"]
        assert len(result["errors"]) > 0
        assert "cleanup_hint" in result

    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_row_creation_fails_continues(self, mock_cache, mock_dup, mock_config, mock_auth):
        call_count = 0

        def mock_post(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                table = url.split("/table/")[1]
                return _mock_response({"result": {"sys_id": f"{table}-{call_count}"}})
            if "sp_row" in url:
                raise Exception("Row fail")
            table = url.split("/table/")[1]
            return _mock_response({"result": {"sys_id": f"{table}-{call_count}"}})

        mock_auth.make_request.side_effect = mock_post
        params = ScaffoldPageParams(
            page_id="rf",
            title="RF",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[12])],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert len(result["errors"]) > 0
        assert result["summary"]["rows"] == 0

    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_column_creation_fails_continues(self, mock_cache, mock_dup, mock_config, mock_auth):
        call_count = 0

        def mock_post(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "sp_column" in url:
                raise Exception("Col fail")
            table = url.split("/table/")[1]
            return _mock_response({"result": {"sys_id": f"{table}-{call_count}"}})

        mock_auth.make_request.side_effect = mock_post
        params = ScaffoldPageParams(
            page_id="colf",
            title="ColF",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[12])],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert result["summary"]["columns"] == 0

    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_widget_instance_creation_fails(self, mock_cache, mock_dup, mock_config, mock_auth):
        call_count = 0

        def mock_post(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "sp_instance" in url:
                raise Exception("Instance fail")
            table = url.split("/table/")[1]
            return _mock_response({"result": {"sys_id": f"{table}-{call_count}"}})

        mock_auth.make_request.side_effect = mock_post
        params = ScaffoldPageParams(
            page_id="wf",
            title="WF",
            scope=SCOPE,
            rows=[
                ScaffoldRowDef(columns=[12], widgets=["wid-1"]),
            ],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert result["summary"]["widget_instances"] == 0
        assert len(result["errors"]) > 0

    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_container_width_fluid(self, mock_cache, mock_dup, mock_config, mock_auth):
        def mock_post(method, url, **kwargs):
            table = url.split("/table/")[1]
            return _mock_response({"result": {"sys_id": f"{table}-1"}})

        mock_auth.make_request.side_effect = mock_post
        params = ScaffoldPageParams(
            page_id="fluid",
            title="Fluid",
            container_width="container-fluid",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[12])],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is True
        container_call = [
            c for c in mock_auth.make_request.call_args_list if "sp_container" in str(c)
        ][0]
        assert container_call[1]["json"]["width"] == "container-fluid"

    @patch("servicenow_mcp.tools.portal_crud_tools._check_duplicate", return_value=None)
    @patch("servicenow_mcp.tools.portal_crud_tools.invalidate_query_cache")
    def test_row_css_class(self, mock_cache, mock_dup, mock_config, mock_auth):
        def mock_post(method, url, **kwargs):
            table = url.split("/table/")[1]
            return _mock_response({"result": {"sys_id": f"{table}-1"}})

        mock_auth.make_request.side_effect = mock_post
        params = ScaffoldPageParams(
            page_id="rcss",
            title="RCSS",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[12], css_class="row-eq-height")],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is True
        row_call = [c for c in mock_auth.make_request.call_args_list if "sp_row" in str(c)][0]
        assert row_call[1]["json"]["css_class"] == "row-eq-height"

    @patch(
        "servicenow_mcp.tools.portal_crud_tools._check_duplicate",
        return_value={"sys_id": "dup-pg", "sys_scope": "s1"},
    )
    def test_duplicate_page_blocked(self, mock_dup, mock_config, mock_auth):
        params = ScaffoldPageParams(
            page_id="existing",
            title="Dup",
            scope=SCOPE,
            rows=[ScaffoldRowDef(columns=[12])],
        )
        result = scaffold_page(mock_config, mock_auth, params)
        assert result["success"] is False
        assert "already exists" in result["message"]
