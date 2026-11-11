"""Rows from a table straight into a workbook sheet — never through the conversation.

Making a spreadsheet used to mean reading rows into context (100 per call) and
then typing them back out as ``spec.rows``: every value paid for twice, and a
model re-typing a thousand rows can drop one or change one without anyone
noticing. Here the server reads and the file is written; the caller gets counts
and a per-column profile, which is what analysis needs first. Individual rows
are then a targeted ``manage_workbook(action='find'|'read')`` away.

Two server behaviours make a naive export lie, so both are checked first:

- an unknown field in the query has its condition DROPPED (the whole table comes
  back), so the condition goes through the same checks as manage_data_update;
- an unknown field in ``fields`` is simply absent, which would be an empty
  column that looks like "no values", so every field is verified too.

The sheet is only called complete when the rows read equal the server's count.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.services.data_update import _check_dotwalk, _count, check_condition
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.query_fields import near_matches, table_columns

DEFAULT_MAX_ROWS = 10_000
HARD_MAX_ROWS = 50_000
_PAGE = 1000
_TOP = 5
_TOP_CHARS = 60
_FIELD = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_]+)*$")


def _refuse(error: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "error": error, "message": message, **extra}


def _cell(value: Any) -> Any:
    if isinstance(value, dict):
        value = value.get("display_value", value.get("value", ""))
    return "" if value is None else value


def check_fields(
    config: Any, auth_manager: Any, table: str, fields: List[str]
) -> Optional[Dict[str, Any]]:
    columns = table_columns(config, auth_manager, table)
    if columns is None:
        return _refuse(
            "SCHEMA_UNVERIFIED",
            f"The columns of {table} could not be read, so the fields cannot be checked. "
            "Nothing was written.",
        )
    for f in fields:
        if not _FIELD.match(f):
            return _refuse("BAD_FIELD", f"{f!r} is not a field name.")
        if "." in f:
            refusal = _check_dotwalk(config, auth_manager, table, f)
            if refusal and refusal.get("error") == "UNKNOWN_QUERY_FIELDS":
                # same check as a condition, different consequence: an empty column
                what = str(refusal.get("message", "")).split(";")[0]
                return {
                    **refusal,
                    "error": "UNKNOWN_FIELD",
                    "message": f"{what}; the server would return an empty column for it.",
                }
            if refusal:
                return refusal
        elif f not in columns:
            return _refuse(
                "UNKNOWN_FIELD",
                f"{table} has no column {f!r}; the server would return an empty column for it.",
                did_you_mean=near_matches(f, sorted(columns)),
            )
    return None


def profile(header: List[str], rows: List[List[Any]]) -> Dict[str, Any]:
    """Per column: empties, distinct values, the most common few. Bounded."""
    out: Dict[str, Any] = {}
    for i, name in enumerate(header):
        values = [str(r[i]) for r in rows if str(r[i]) != ""]
        counts = Counter(values)
        col: Dict[str, Any] = {"empty": len(rows) - len(values), "distinct": len(counts)}
        common = [(v, n) for v, n in counts.most_common(_TOP) if n > 1]
        if common:
            col["top"] = [
                [v if len(v) <= _TOP_CHARS else v[:_TOP_CHARS] + "…", n] for v, n in common
            ]
        elif values:
            # every value once (an id, a number): listing some is just rows, and says nothing
            col["all_distinct"] = True
        out[name] = col
    return out


def fetch_sheet(
    config: Any, auth_manager: Any, source: Dict[str, Any]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(sheet data, refusal). Sheet data = header, rows, and what was proven."""
    table = str(source.get("table") or "").strip()
    query = str(source.get("query") or "").strip()
    raw_fields = source.get("fields") or []
    fields = [
        f.strip()
        for f in (raw_fields.split(",") if isinstance(raw_fields, str) else raw_fields)
        if str(f).strip()
    ]
    cap = min(int(source.get("max_rows") or DEFAULT_MAX_ROWS), HARD_MAX_ROWS)
    display = bool(source.get("display_value", True))
    if not table or not fields:
        return None, _refuse("BAD_SOURCE", "source needs table and fields (the columns to export).")

    refusal = check_fields(config, auth_manager, table, fields)
    if refusal:
        return None, refusal
    if query:
        refusal = check_condition(config, auth_manager, table, query)
        if refusal:
            return None, refusal

    invalidate_query_cache(table=table)  # count and pages must come from the same moment
    matched = _count(config, auth_manager, table, query)
    if matched is None:
        return None, _refuse(
            "COUNT_UNVERIFIED",
            "The server did not report how many rows match, so a complete export cannot be "
            "proven. Nothing was written.",
        )
    if matched > cap:
        return None, _refuse(
            "OVER_CAP",
            f"{matched} rows match; max_rows is {cap} (hard limit {HARD_MAX_ROWS}). Narrow the "
            "query or raise max_rows — an export is never silently cut to the first N.",
            matched=matched,
        )

    rows: List[List[Any]] = []
    offset = 0
    while offset < matched:
        page, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query,
            fields=",".join(fields),
            limit=_PAGE,
            offset=offset,
            display_value=display,
            no_count=True,
            orderby="sys_id",
            fail_silently=False,
        )
        rows.extend([_cell(r.get(f)) for f in fields] for r in page)
        if len(page) < _PAGE:
            break
        offset += _PAGE
    sheet = {
        "table": table,
        "header": fields,
        "rows": rows,
        "matched": matched,
        "complete": len(rows) == matched,
    }
    if len(rows) != matched:
        sheet["incomplete_note"] = (
            f"The server counted {matched} rows but returned {len(rows)} (ACL-hidden rows, or "
            "rows changed during the read). The sheet is NOT the full set — say so."
        )
    return sheet, None


def resolve_sources(
    config: Any, auth_manager: Any, spec: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Replace every ``source`` sheet with its rows. All sheets are read before any file
    is written: one refused sheet means no file."""
    sheets: List[Dict[str, Any]] = []
    proofs: List[Dict[str, Any]] = []
    for index, sheet_spec in enumerate(spec.get("sheets") or [], start=1):
        sheet = dict(sheet_spec)
        source = sheet.pop("source", None)
        title = str(sheet.get("title") or f"Sheet{index}")[:31]
        if source:
            if sheet.get("rows"):
                return (
                    spec,
                    [],
                    _refuse("BAD_SPEC", f"Sheet {title!r}: give rows OR source, not both."),
                )
            data, refusal = fetch_sheet(config, auth_manager, dict(source))
            if refusal:
                return spec, [], {**refusal, "sheet": title, "note": "No file was written."}
            assert data is not None
            sheet["rows"] = [data["header"], *data["rows"]]
            sheet.setdefault("header_row", 1)
            proof = {
                "sheet": title,
                "table": data["table"],
                "matched": data["matched"],
                "rows": len(data["rows"]),
                "complete": data["complete"],
                "columns": profile(data["header"], data["rows"]),
            }
            if "incomplete_note" in data:
                proof["incomplete_note"] = data["incomplete_note"]
            proofs.append(proof)
        sheets.append(sheet)
    return {**spec, "sheets": sheets}, proofs, None
