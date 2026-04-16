"""Tests for servicenow_mcp.resources.script_includes module."""

import asyncio
import json
from unittest.mock import MagicMock

from conftest import make_mock_response
from requests import RequestException

from servicenow_mcp.resources.script_includes import ScriptIncludeListParams, ScriptIncludeResource

# ---------------------------------------------------------------------------
# ScriptIncludeResource.list_script_includes
# ---------------------------------------------------------------------------


def test_list_script_includes_success(mock_config, mock_auth):
    mock_resp = make_mock_response({"result": [{"sys_id": "si1"}]})
    mock_resp.text = '{"result": [{"sys_id": "si1"}]}'
    mock_auth.make_request.return_value = mock_resp
    resource = ScriptIncludeResource(mock_config, mock_auth)
    result = asyncio.run(resource.list_script_includes(ScriptIncludeListParams()))
    assert '"si1"' in result


def test_list_script_includes_with_filters(mock_config, mock_auth):
    mock_resp = make_mock_response({"result": []})
    mock_resp.text = '{"result": []}'
    mock_auth.make_request.return_value = mock_resp
    resource = ScriptIncludeResource(mock_config, mock_auth)
    params = ScriptIncludeListParams(active=True, client_callable=False, query="Utils")
    asyncio.run(resource.list_script_includes(params))
    call_args = mock_auth.make_request.call_args
    query_params = call_args.kwargs.get("params", {})
    q = query_params["sysparm_query"]
    assert "active=true" in q
    assert "client_callable=false" in q
    assert "nameLIKEUtils" in q


def test_list_script_includes_http_error(mock_config, mock_auth):
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_auth.make_request.return_value = mock_resp
    resource = ScriptIncludeResource(mock_config, mock_auth)
    result = asyncio.run(resource.list_script_includes(ScriptIncludeListParams()))
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Error listing script includes" in parsed["error"]


def test_list_script_includes_request_exception(mock_config, mock_auth):
    mock_auth.make_request.side_effect = RequestException("connection error")
    resource = ScriptIncludeResource(mock_config, mock_auth)
    result = asyncio.run(resource.list_script_includes(ScriptIncludeListParams()))
    parsed = json.loads(result)
    assert "error" in parsed


# ---------------------------------------------------------------------------
# ScriptIncludeResource.get_script_include
# ---------------------------------------------------------------------------


def test_get_script_include_by_sys_id(mock_config, mock_auth):
    mock_resp = make_mock_response({"result": {"sys_id": "abc123", "name": "Utils"}})
    mock_resp.text = '{"result": {"sys_id": "abc123", "name": "Utils"}}'
    mock_auth.make_request.return_value = mock_resp
    resource = ScriptIncludeResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_script_include("sys_id:abc123"))
    assert "abc123" in result
    # Verify correct URL used (direct sys_id lookup)
    url = mock_auth.make_request.call_args[0][1]
    assert url.endswith("/abc123")


def test_get_script_include_by_name(mock_config, mock_auth):
    mock_resp = make_mock_response({"result": [{"sys_id": "abc", "name": "Utils"}]})
    mock_resp.text = '{"result": [{"sys_id": "abc", "name": "Utils"}]}'
    mock_auth.make_request.return_value = mock_resp
    resource = ScriptIncludeResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_script_include("Utils"))
    assert "Utils" in result
    # Verify query param used (name lookup)
    call_args = mock_auth.make_request.call_args
    params = call_args.kwargs.get("params", {})
    assert params["sysparm_query"] == "name=Utils"


def test_get_script_include_http_error(mock_config, mock_auth):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_auth.make_request.return_value = mock_resp
    resource = ScriptIncludeResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_script_include("sys_id:missing"))
    parsed = json.loads(result)
    assert "error" in parsed
    assert "Error getting script include" in parsed["error"]


def test_get_script_include_exception(mock_config, mock_auth):
    mock_auth.make_request.side_effect = RequestException("fail")
    resource = ScriptIncludeResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_script_include("Utils"))
    parsed = json.loads(result)
    assert "error" in parsed
