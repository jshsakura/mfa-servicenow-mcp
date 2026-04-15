"""Tests for servicenow_mcp.resources.changesets module."""

import asyncio
import json
from unittest.mock import patch

import requests
from conftest import make_mock_response

from servicenow_mcp.resources.changesets import ChangesetListParams, ChangesetResource

# ---------------------------------------------------------------------------
# ChangesetResource.list_changesets
# ---------------------------------------------------------------------------


@patch("servicenow_mcp.resources.changesets.requests.get")
def test_list_changesets_success(mock_get, mock_config, mock_auth):
    mock_resp = make_mock_response({"result": [{"sys_id": "cs1"}]})
    mock_resp.text = '{"result": [{"sys_id": "cs1"}]}'
    mock_get.return_value = mock_resp
    resource = ChangesetResource(mock_config, mock_auth)
    result = asyncio.run(resource.list_changesets(ChangesetListParams()))
    assert '"cs1"' in result


@patch("servicenow_mcp.resources.changesets.requests.get")
def test_list_changesets_with_filters(mock_get, mock_config, mock_auth):
    mock_resp = make_mock_response({"result": []})
    mock_resp.text = '{"result": []}'
    mock_get.return_value = mock_resp
    resource = ChangesetResource(mock_config, mock_auth)
    params = ChangesetListParams(state="open", application="myapp", developer="admin")
    asyncio.run(resource.list_changesets(params))
    call_args = mock_get.call_args
    query = call_args.kwargs.get("params", call_args[1].get("params", {}))
    assert "state=open" in query["sysparm_query"]
    assert "application=myapp" in query["sysparm_query"]
    assert "developer=admin" in query["sysparm_query"]


@patch("servicenow_mcp.resources.changesets.requests.get")
def test_list_changesets_exception(mock_get, mock_config, mock_auth):
    mock_get.side_effect = requests.RequestException("timeout")
    resource = ChangesetResource(mock_config, mock_auth)
    result = asyncio.run(resource.list_changesets(ChangesetListParams()))
    parsed = json.loads(result)
    assert "error" in parsed


# ---------------------------------------------------------------------------
# ChangesetResource.get_changeset
# ---------------------------------------------------------------------------


@patch("servicenow_mcp.resources.changesets.requests.get")
def test_get_changeset_success(mock_get, mock_config, mock_auth):
    changeset_resp = make_mock_response({"result": {"sys_id": "cs1", "name": "Update Set"}})
    changes_resp = make_mock_response(
        {"result": [{"sys_id": "ch1", "name": "Change 1"}, {"sys_id": "ch2", "name": "Change 2"}]}
    )
    mock_get.side_effect = [changeset_resp, changes_resp]
    resource = ChangesetResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_changeset("cs1"))
    parsed = json.loads(result)
    assert parsed["changeset"]["sys_id"] == "cs1"
    assert parsed["change_count"] == 2
    assert len(parsed["changes"]) == 2


@patch("servicenow_mcp.resources.changesets.requests.get")
def test_get_changeset_exception(mock_get, mock_config, mock_auth):
    mock_get.side_effect = requests.RequestException("not found")
    resource = ChangesetResource(mock_config, mock_auth)
    result = asyncio.run(resource.get_changeset("cs1"))
    parsed = json.loads(result)
    assert "error" in parsed
