"""sn_query must turn a missing `table` into a helpful, recoverable error
instead of an opaque framework rejection — so the agent fixes it in one shot,
while a present table still flows through to the query unchanged."""

from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.sn_api import GenericQueryParams, sn_query


def _no_network_mocks():
    config = MagicMock()
    auth = MagicMock()
    return config, auth


def test_missing_table_returns_helpful_error():
    config, auth = _no_network_mocks()
    result = sn_query(config, auth, GenericQueryParams(query="active=true"))
    assert result["success"] is False
    assert result["error"] == "table_required"
    assert result["example"]["table"] == "incident"
    assert "sn_schema" in result["hint"]
    # Never touched the network.
    auth.get_headers.assert_not_called()


def test_blank_table_returns_helpful_error():
    config, auth = _no_network_mocks()
    result = sn_query(config, auth, GenericQueryParams(table="   "))
    assert result["error"] == "table_required"


def test_table_optional_in_schema():
    # The field must be optional so the call reaches our in-handler guard.
    field = GenericQueryParams.model_fields["table"]
    assert field.is_required() is False


def test_present_table_runs_query():
    # A present table must flow past the guard into sn_query_page and succeed —
    # guards the Optional-table change against a regression that rejects valid input.
    config, auth = _no_network_mocks()
    rows = [{"sys_id": "1", "number": "INC001"}]
    with patch("servicenow_mcp.tools.sn_api.sn_query_page", return_value=(rows, 1)) as page:
        result = sn_query(config, auth, GenericQueryParams(table="incident", query="active=true"))
    assert result["success"] is True
    assert result["table"] == "incident"
    assert result["results"] == rows
    assert page.call_count == 1
    assert page.call_args.kwargs["table"] == "incident"
