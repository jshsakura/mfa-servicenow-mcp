"""A field name the table does not have must be named, and a real one must not.

The second half is the load-bearing one. This module exists because a wrong
signpost cost three days; producing a wrong signpost of its own — "that column
does not exist" about a column that does — would be strictly worse than doing
nothing, because it is the same failure with more confidence behind it.

The parsing cases are pinned against shapes that actually appear in this repo's
queries. What the SERVER does with an unknown field is not pinned here and
cannot be: a mock answers with whatever key it was written with. That half was
measured on a live instance and is recorded in the module docstring.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from servicenow_mcp.utils import query_fields
from servicenow_mcp.utils.query_fields import (
    forget_columns,
    near_matches,
    query_field_names,
    table_ancestry,
    table_columns,
    unknown_query_fields,
)


@pytest.fixture(autouse=True)
def _clean_memo():
    forget_columns()
    yield
    forget_columns()


# ---------------------------------------------------------------------------
# Parsing — the half that must not invent a finding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected",
    [
        ("so_no=2011268774", ["so_no"]),
        ("active=true^priority=1", ["active", "priority"]),
        ("state=1^ORstate=7", ["state"]),
        ("short_descriptionLIKEvpn^ORdescriptionLIKEvpn", ["short_description", "description"]),
        ("nameSTARTSWITHfoo^categoryIN a,b^costISNOTEMPTY", ["name", "category", "cost"]),
        ("stateINError,Cancelled^ORerror_messageISNOTEMPTY", ["state", "error_message"]),
        ("", []),
    ],
)
def test_the_fields_a_query_filters_on_are_read_off_it(query, expected):
    assert query_field_names(query) == expected


def test_an_operator_inside_a_field_name_does_not_cut_the_name():
    """`main_index` contains `IN`. Searching for the operator finds it at index 2.

    That produced the field name `ma`, reported a real column as unknown, and
    would have sent someone chasing a schema problem that does not exist — this
    module's own version of the bug it was written to remove.
    """
    assert query_field_names("main_index=1") == ["main_index"]
    assert query_field_names("incident_state=2^ORinstance_name=x") == [
        "incident_state",
        "instance_name",
    ]
    assert query_field_names("sys_created_onONToday@x@y") == ["sys_created_on"]


def test_a_sort_clause_is_not_mistaken_for_the_OR_combinator():
    """`ORDERBY` starts with `OR`; stripping the combinator first ate the field."""
    assert query_field_names("active=true^ORDERBYnumber") == ["active", "number"]
    assert query_field_names("a=1^ORDERBYDESCsys_updated_on") == ["a", "sys_updated_on"]


def test_a_lowercase_field_is_not_mistaken_for_a_combinator():
    """`order_type` starts with the letters of `^OR` and `nqueue` with `^NQ`.

    Matching the combinator case-insensitively ate the first two letters, and
    the caller was told its own table has no column `der_type` — a valid read
    refused, on a field that is right there in the dictionary.
    """
    assert query_field_names("numberISNOTEMPTY^order_typeISNOTEMPTY") == [
        "number",
        "order_type",
    ]
    assert query_field_names("a=1^ORorder_type=2") == ["a", "order_type"]
    assert query_field_names("a=1^NQnqueue=2") == ["a", "nqueue"]


def test_EQ_and_NQ_end_a_condition_rather_than_start_a_field():
    """As prefixes they swallowed `equipment` and `nquery`, which then went
    unchecked — the quiet direction of the same bug."""
    assert query_field_names("equipment=1^EQ") == ["equipment"]
    assert query_field_names("state=1^ORstate=2^EQ") == ["state"]
    assert query_field_names("nquery_count=3^EQ") == ["nquery_count"]


def test_only_the_first_segment_of_a_dot_walk_is_claimed():
    """The far side of a dot-walk lives on another table and is not checkable."""
    assert query_field_names("sys_scope.scope=x_app") == ["sys_scope"]


def test_anything_unparseable_is_skipped_rather_than_guessed_at():
    assert query_field_names("123TEXTQUERY321=hello") == []
    assert query_field_names("^^^") == []
    assert query_field_names("javascript:gs.nowDateTime()") == []


# ---------------------------------------------------------------------------
# Resolving the table's columns
# ---------------------------------------------------------------------------


def _config():
    return SimpleNamespace(instance_url="https://test.service-now.com", timeout=15)


def _auth(pages):
    """An auth manager answering each request from `pages`, in order."""
    auth = MagicMock()
    responses = []
    for rows in pages:
        response = MagicMock()
        response.json.return_value = {"result": rows}
        responses.append(response)
    auth.make_request.side_effect = responses
    return auth


def test_inherited_columns_are_found_by_walking_super_class_by_sys_id():
    """`super_class` is a reference: raw is a sys_id, display is the LABEL.

    Measured live — `incident.super_class` displays as "Task", not "task". A walk
    on the display value finds no dictionary rows for the parent, and every
    inherited column then reports as unknown.
    """
    auth = _auth(
        [
            [{"name": "incident", "super_class": "fa50-sys-id"}],
            [{"name": "task", "super_class": ""}],
            [{"element": "short_description"}, {"element": "number"}],
        ]
    )

    assert table_ancestry(_config(), auth, "incident") == ["incident", "task"]
    forget_columns()

    auth = _auth(
        [
            [{"name": "incident", "super_class": "fa50-sys-id"}],
            [{"name": "task", "super_class": ""}],
            [{"element": "short_description"}, {"element": "number"}],
        ]
    )
    columns = table_columns(_config(), auth, "incident")

    assert columns is not None
    assert "short_description" in columns, "declared on task, present on incident"
    assert "sys_id" in columns, "always present, not always in sys_dictionary"


def test_a_walk_that_broke_answers_none_rather_than_a_partial_ancestry():
    """A partial ancestry produces exactly the false 'unknown field' to avoid."""
    auth = MagicMock()
    auth.make_request.side_effect = RuntimeError("connection reset")

    assert table_ancestry(_config(), auth, "incident") is None
    assert table_columns(_config(), auth, "incident") is None
    assert unknown_query_fields(_config(), auth, "incident", "active=true") is None


def test_a_table_with_no_dictionary_rows_answers_none_not_everything_is_unknown():
    auth = _auth([[{"name": "widget", "super_class": ""}], []])

    assert table_columns(_config(), auth, "widget") is None


def test_a_resolved_column_set_is_only_read_once():
    auth = _auth(
        [
            [{"name": "task", "super_class": ""}],
            [{"element": "number"}],
        ]
    )
    config = _config()

    first = table_columns(config, auth, "task")
    calls = auth.make_request.call_count
    second = table_columns(config, auth, "task")

    assert first == second
    assert auth.make_request.call_count == calls, "the column set does not change mid-session"


def test_a_failed_lookup_is_not_cached():
    """'Could not find out' has to stay retryable, or one blip silences the check."""
    auth = MagicMock()
    auth.make_request.side_effect = RuntimeError("blip")
    config = _config()

    assert table_columns(config, auth, "task") is None
    calls = auth.make_request.call_count
    assert table_columns(config, auth, "task") is None
    assert auth.make_request.call_count > calls, "it tried again"


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def _columns(monkeypatch, names):
    monkeypatch.setattr(query_fields, "table_columns", lambda *a, **k: set(names))


def test_a_column_the_table_does_not_have_is_named(monkeypatch):
    _columns(monkeypatch, {"billing_document", "sales_document"})

    assert unknown_query_fields(_config(), MagicMock(), "t", "so_no=1") == ["so_no"]


def test_real_columns_produce_no_finding(monkeypatch):
    _columns(monkeypatch, {"billing_document", "sales_document"})

    assert unknown_query_fields(_config(), MagicMock(), "t", "sales_document=1") == []


def test_a_query_with_nothing_to_check_never_costs_a_read():
    auth = MagicMock()

    assert unknown_query_fields(_config(), auth, "incident", "") == []
    assert auth.make_request.call_count == 0


def test_a_near_match_is_offered_when_there_is_one():
    assert "sales_document" in near_matches("sales_documnt", ["sales_document", "plant"])
    assert near_matches("zzzzz", ["sales_document", "plant"]) == []
