"""Columnar encoding for multi-row sn_query results.

On real usage ~28.7% of a multi-row payload's bytes are the field-name keys
repeated once per row. Columnar mode emits the keys once as `columns` and each
record as a positional array in `data`. It is the DEFAULT above
_COLUMNAR_MIN_ROWS rows; small results stay as dicts (columnar only pays on many
rows, and a one-off record reads more naturally as a dict).
"""

from unittest.mock import MagicMock, patch

from servicenow_mcp.tools.sn_api import (
    _COLUMNAR_MIN_ROWS,
    GenericQueryParams,
    sn_query,
    to_columnar,
)

# --- pure helper -----------------------------------------------------------


def test_to_columnar_orders_by_preferred_then_first_seen():
    rows = [
        {"sys_id": "1", "number": "INC001", "state": "1"},
        {"sys_id": "2", "number": "INC002", "state": "2"},
    ]
    out = to_columnar(rows, ["sys_id", "number", "state"])
    assert out["columns"] == ["sys_id", "number", "state"]
    assert out["data"] == [["1", "INC001", "1"], ["2", "INC002", "2"]]


def test_to_columnar_ragged_rows_fill_missing_with_none():
    # strip_empty_fields drops empty keys, so rows are ragged; a missing key
    # must become None in that row's array (read as "empty for this record").
    rows = [
        {"sys_id": "1", "number": "INC001", "state": "1"},
        {"sys_id": "2", "number": "INC002"},  # no state
    ]
    out = to_columnar(rows, ["sys_id", "number", "state"])
    assert out["columns"] == ["sys_id", "number", "state"]
    assert out["data"][1] == ["2", "INC002", None]


def test_to_columnar_drops_preferred_columns_absent_from_every_row():
    # queried_fields may name columns the table never returned — they must not
    # appear as all-None columns.
    rows = [{"sys_id": "1"}, {"sys_id": "2"}]
    out = to_columnar(rows, ["sys_id", "name", "cost"])
    assert out["columns"] == ["sys_id"]
    assert out["data"] == [["1"], ["2"]]


def test_to_columnar_includes_extra_keys_after_preferred():
    rows = [{"sys_id": "1", "extra": "x"}]
    out = to_columnar(rows, ["sys_id"])
    assert out["columns"] == ["sys_id", "extra"]


# --- sn_query integration (columnar is the DEFAULT above the row threshold) --


def _rows(n):
    return [{"sys_id": str(i), "number": f"INC{i:03d}", "state": "1"} for i in range(n)]


def test_sn_query_columnar_by_default_when_enough_rows():
    rows = _rows(_COLUMNAR_MIN_ROWS)
    with patch(
        "servicenow_mcp.tools.sn_api.sn_query_page", return_value=(rows, _COLUMNAR_MIN_ROWS)
    ):
        result = sn_query(MagicMock(), MagicMock(), GenericQueryParams(table="incident"))
    assert result["format"] == "columnar"
    assert set(result["results"]["columns"]) >= {"sys_id", "number", "state"}
    assert len(result["results"]["data"]) == _COLUMNAR_MIN_ROWS
    # No per-row key repetition — each row is a positional array.
    assert all(isinstance(r, list) for r in result["results"]["data"])


def test_sn_query_stays_dict_below_row_threshold():
    rows = _rows(_COLUMNAR_MIN_ROWS - 1)
    with patch(
        "servicenow_mcp.tools.sn_api.sn_query_page",
        return_value=(rows, _COLUMNAR_MIN_ROWS - 1),
    ):
        result = sn_query(MagicMock(), MagicMock(), GenericQueryParams(table="incident"))
    assert "format" not in result
    assert isinstance(result["results"], list)


def test_columnar_roundtrips_to_original_records():
    # A caller can always rebuild the dict form from columns+data — proving the
    # encoding loses nothing (under-fetch-safe: same fields, different shape).
    rows = _rows(4)
    with patch("servicenow_mcp.tools.sn_api.sn_query_page", return_value=(rows, 4)):
        result = sn_query(MagicMock(), MagicMock(), GenericQueryParams(table="incident"))
    cols = result["results"]["columns"]
    rebuilt = [
        {c: v for c, v in zip(cols, row, strict=True) if v is not None}
        for row in result["results"]["data"]
    ]
    assert rebuilt == rows
