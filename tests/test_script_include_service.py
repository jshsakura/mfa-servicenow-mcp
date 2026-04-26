"""Unit tests for the script_include service module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services.script_include import (
    ScriptIncludeResponse,
    create,
    delete,
    execute,
    update,
)
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


@pytest.fixture
def config():
    return ServerConfig(
        instance_url="https://test.service-now.com",
        auth=AuthConfig(
            type=AuthType.BASIC,
            basic=BasicAuthConfig(username="u", password="p"),
        ),
    )


@pytest.fixture
def auth():
    m = MagicMock()
    m.get_headers.return_value = {"Authorization": "Basic xxx"}
    return m


def _op_resp(body=None):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    if body is not None:
        m.json.return_value = body
    return m


def _text_resp(text=""):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.text = text
    return m


_SI = {"sys_id": "si_001", "name": "MyUtil", "client_callable": "true"}


class TestCreate:
    def test_happy_path(self, config, auth):
        auth.make_request.return_value = _op_resp(
            {"result": {"sys_id": "si_001", "name": "MyUtil"}}
        )
        result = create(config, auth, name="MyUtil", script="var x = 1;")
        assert isinstance(result, ScriptIncludeResponse)
        assert result.success is True
        assert result.script_include_id == "si_001"
        assert result.script_include_name == "MyUtil"
        assert "Created" in result.message

    def test_missing_result_key(self, config, auth):
        auth.make_request.return_value = _op_resp({})
        result = create(config, auth, name="X", script="y")
        assert result.success is False

    def test_request_error(self, config, auth):
        auth.make_request.side_effect = RuntimeError("network error")
        result = create(config, auth, name="X", script="y")
        assert result.success is False
        assert "Error creating" in result.message

    def test_optional_fields_included_in_body(self, config, auth):
        auth.make_request.return_value = _op_resp(
            {"result": {"sys_id": "si_001", "name": "MyUtil"}}
        )
        create(
            config,
            auth,
            name="MyUtil",
            script="var x = 1;",
            description="Desc",
            api_name="global.MyUtil",
            client_callable=True,
            active=False,
            access="public",
        )
        _, kwargs = auth.make_request.call_args
        body = kwargs["json"]
        assert body["description"] == "Desc"
        assert body["api_name"] == "global.MyUtil"
        assert body["client_callable"] == "true"
        assert body["active"] == "false"
        assert body["access"] == "public"

    def test_invalidates_cache(self, config, auth):
        auth.make_request.return_value = _op_resp(
            {"result": {"sys_id": "si_001", "name": "MyUtil"}}
        )
        with patch("servicenow_mcp.services.script_include.invalidate_query_cache") as mock_inv:
            create(config, auth, name="MyUtil", script="x")
            mock_inv.assert_called_once_with(table="sys_script_include")


class TestUpdate:
    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_happy_path(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _op_resp(
            {"result": {"sys_id": "si_001", "name": "MyUtil"}}
        )
        result = update(config, auth, script_include_id="si_001", active=False)
        assert result.success is True
        assert result.script_include_id == "si_001"
        _, kwargs = auth.make_request.call_args
        assert kwargs["json"]["active"] == "false"

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_not_found(self, mock_qp, config, auth):
        mock_qp.return_value = ([], None)
        result = update(config, auth, script_include_id="missing", script="x")
        assert result.success is False
        assert "not found" in result.message

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_no_body_fields(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        result = update(config, auth, script_include_id="si_001")
        assert result.success is True
        assert "No changes" in result.message
        auth.make_request.assert_not_called()

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_request_error(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.side_effect = RuntimeError("PATCH failed")
        result = update(config, auth, script_include_id="si_001", script="new")
        assert result.success is False
        assert "Error updating" in result.message

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_missing_result_key(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _op_resp({})
        result = update(config, auth, script_include_id="si_001", script="new")
        assert result.success is False

    @patch("servicenow_mcp.services.script_include.invalidate_query_cache")
    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_invalidates_cache(self, mock_qp, mock_inv, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _op_resp(
            {"result": {"sys_id": "si_001", "name": "MyUtil"}}
        )
        update(config, auth, script_include_id="si_001", script="x")
        mock_inv.assert_called_once_with(table="sys_script_include")


class TestDelete:
    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_happy_path(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _op_resp()
        result = delete(config, auth, script_include_id="si_001")
        assert result.success is True
        assert result.script_include_id == "si_001"
        assert result.script_include_name == "MyUtil"
        assert "Deleted" in result.message

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_not_found(self, mock_qp, config, auth):
        mock_qp.return_value = ([], None)
        result = delete(config, auth, script_include_id="missing")
        assert result.success is False
        assert "not found" in result.message

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_request_error(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.side_effect = RuntimeError("DELETE failed")
        result = delete(config, auth, script_include_id="si_001")
        assert result.success is False
        assert "Error deleting" in result.message

    @patch("servicenow_mcp.services.script_include.invalidate_query_cache")
    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_invalidates_cache(self, mock_qp, mock_inv, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _op_resp()
        delete(config, auth, script_include_id="si_001")
        mock_inv.assert_called_once_with(table="sys_script_include")


class TestExecute:
    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_happy_path_json(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _text_resp('{"answer": "42"}')
        result = execute(config, auth, name="MyUtil", method="doWork")
        assert result["success"] is True
        assert result["result"] == {"answer": "42"}
        assert "Executed MyUtil.doWork" in result["message"]

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_happy_path_text(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _text_resp("<xml>hello</xml>")
        result = execute(config, auth, name="MyUtil")
        assert result["success"] is True
        assert result["result"] == "<xml>hello</xml>"

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_not_found(self, mock_qp, config, auth):
        mock_qp.return_value = ([], None)
        result = execute(config, auth, name="Missing")
        assert result["success"] is False
        assert "not found" in result["message"]

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_not_client_callable(self, mock_qp, config, auth):
        mock_qp.return_value = (
            [{**_SI, "client_callable": "false"}],
            1,
        )
        result = execute(config, auth, name="MyUtil")
        assert result["success"] is False
        assert "not client-callable" in result["message"]

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_request_error(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.side_effect = RuntimeError("timeout")
        result = execute(config, auth, name="MyUtil")
        assert result["success"] is False
        assert "Error executing" in result["message"]

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_params_forwarded(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _text_resp("{}")
        execute(config, auth, name="MyUtil", method="lookup", params={"table": "incident"})
        _, kwargs = auth.make_request.call_args
        assert kwargs["params"]["sysparm_table"] == "incident"
        assert kwargs["params"]["sysparm_ajax_processor"] == "MyUtil"
        assert kwargs["params"]["sysparm_name"] == "lookup"

    @patch("servicenow_mcp.services.script_include.sn_query_page")
    def test_default_method(self, mock_qp, config, auth):
        mock_qp.return_value = ([_SI], 1)
        auth.make_request.return_value = _text_resp("{}")
        execute(config, auth, name="MyUtil")
        _, kwargs = auth.make_request.call_args
        assert kwargs["params"]["sysparm_name"] == "execute"
