"""A filter the server DROPS must never come back as an answer.

ServiceNow does not refuse a condition naming a column the table does not have,
and it has no grouping syntax: `(sys_id=X^ORid=X)` parses `(sys_id` as an
unknown field. Either way the condition is discarded, the read returns the WHOLE
TABLE, and the response says `success: true` — so "the 1 widget you targeted"
and "all 1159 widgets on the instance" are the same shape.

Both were live on this repo at once, and both were found by hand from the
outside, not by the suite:

- `search_portal_regex_matches(widget_ids=[...])` scanned every widget in the
  instance, because its filter was parenthesised.
- `search_server_code(source_type='all')` answered EVERY query with the same 5
  `sys_transform_script` rows, because `search_fields` named a `name` column
  that table does not have — and one type "finding" something ends the sweep, so
  the types after it were never searched either.

A mock cannot catch that: it returns whatever the fixture says. What the tests
below pin is what the code can check without the server — the query never
carries syntax the server silently discards, and a returned row is not treated
as a hit until it is matched locally against the term that was searched.
"""

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.tools.portal_tools import (
    SearchPortalRegexMatchesParams,
    search_portal_regex_matches,
)
from servicenow_mcp.tools.source_tools import (
    SOURCE_CONFIG,
    SearchServerCodeParams,
    search_server_code,
)
from servicenow_mcp.utils.config import ServerConfig

WIDGET_A = "aaaa1111bbbb2222cccc3333dddd4444"
WIDGET_B = "bbbb2222cccc3333dddd4444eeee5555"


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


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_widget_ids_filter_is_sent_without_parentheses(mock_query, mock_config, mock_auth_manager):
    """The targeted filter must reach the server as syntax it actually honours."""
    mock_query.return_value = [
        {"sys_id": WIDGET_A, "name": "Target Widget", "id": "target-widget", "script": "hit"}
    ]

    search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            regex="hit",
            widget_ids=[WIDGET_A],
            scope="x_myapp",
            source_types=["widget"],
            include_widget_fields=["script"],
            include_linked_script_includes=False,
            include_linked_angular_providers=False,
        ),
    )

    queries = [call.kwargs.get("query", "") for call in mock_query.call_args_list]
    assert queries, "no query was issued"
    for query in queries:
        assert "(" not in query and ")" not in query
    assert any(f"sys_id={WIDGET_A}" in query for query in queries)


@patch("servicenow_mcp.tools.portal_tools._sn_query_all")
def test_widget_ids_filter_drops_rows_the_server_should_not_have_returned(
    mock_query, mock_config, mock_auth_manager
):
    """A lenient instance returning the whole table must not read as a hit list."""
    mock_query.return_value = [
        {"sys_id": WIDGET_A, "name": "Target Widget", "id": "target-widget", "script": "hit"},
        {"sys_id": WIDGET_B, "name": "Unrelated", "id": "unrelated", "script": "hit"},
    ]

    result = search_portal_regex_matches(
        mock_config,
        mock_auth_manager,
        SearchPortalRegexMatchesParams(
            regex="hit",
            widget_ids=[WIDGET_A],
            source_types=["widget"],
            include_widget_fields=["script"],
            include_linked_script_includes=False,
            include_linked_angular_providers=False,
        ),
    )

    blob = repr(result["matches"])
    assert "Target_Widget" in blob
    assert "Unrelated" not in blob and WIDGET_B not in blob


def test_every_searched_field_is_also_fetched():
    """Client-side verification is only exact while it can see the field.

    `search_server_code` re-checks each row against the fields it searched. A
    search field that is never fetched would look like "matched nothing" on
    every row, and real hits would be discarded — the guard has to stay
    verifiable, so the two lists are pinned together.
    """
    for source_type, cfg in SOURCE_CONFIG.items():
        fetched = set(cfg["summary_fields"]) | set(cfg["source_fields"])
        unfetched = [field for field in cfg["search_fields"] if field not in fetched]
        assert not unfetched, f"{source_type}: searched but never fetched: {unfetched}"


@patch("servicenow_mcp.tools.source_tools.sn_query_page")
def test_rows_matching_no_searched_field_are_discarded_and_reported(
    mock_page, mock_config, mock_auth_manager
):
    """The whole-table symptom: rows come back that contain the term nowhere."""
    mock_page.return_value = (
        [
            {"sys_id": "1" * 32, "name": "Unrelated One", "script": "nothing here"},
            {"sys_id": "2" * 32, "name": "Unrelated Two", "script": "nor here"},
        ],
        None,
    )

    result = search_server_code(
        mock_config,
        mock_auth_manager,
        SearchServerCodeParams(query="landing_marker", source_type="script_include"),
    )

    assert result["success"] is True
    assert result["results"] == []
    assert result["count"] == 0
    # And it must not read as "checked, nothing there".
    assert result["unfiltered_types"][0]["source_type"] == "script_include"
    assert result["unfiltered_types"][0]["rows_discarded"] == 2
    assert "UNCHECKED" in result["warning"]


@patch("servicenow_mcp.tools.source_tools.sn_query_page")
def test_a_type_that_filtered_nothing_does_not_end_the_all_sweep(
    mock_page, mock_config, mock_auth_manager
):
    """One bogus type used to consume the whole `source_type='all'` search."""
    real_hit = {
        "sys_id": "3" * 32,
        "name": "RealHit",
        "api_name": "x_myapp.RealHit",
        "script": "var x = 'landing_marker';",
    }
    calls = {"n": 0}

    def _pages(*_args, **kwargs):
        calls["n"] += 1
        if kwargs.get("table") == "sys_script_include":
            # First type in the sweep answers with rows that match nothing.
            return ([{"sys_id": "9" * 32, "name": "Noise", "script": "unrelated"}], None)
        if kwargs.get("table") == "sp_widget":
            return ([{**real_hit, "id": "real-hit"}], None)
        return ([], None)

    mock_page.side_effect = _pages

    result = search_server_code(
        mock_config,
        mock_auth_manager,
        SearchServerCodeParams(query="landing_marker", source_type="all"),
    )

    assert [row["source_type"] for row in result["results"]] == ["widget"]
    assert "script_include" in [row["source_type"] for row in result["unfiltered_types"]]
