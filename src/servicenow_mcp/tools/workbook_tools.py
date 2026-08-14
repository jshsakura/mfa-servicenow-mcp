"""manage_workbook — the Excel legwork behind test sign-offs and trackers.

Built from measured repetition, not speculation: real sessions hand-wrote
seven openpyxl snippets to query one tracking workbook, and every sign-off
document started with the same thirty lines of styling boilerplate before a
single row of content. This tool keeps the boilerplate server-side; the
caller sends and receives only data.

Read results are capped and the caps are NAMED (`truncated`) — a partial
read must never look like the whole sheet. Writes go through
utils/workbook_io.py's house style; `fill` writes a COPY of an existing form
and refuses to overwrite the form itself.
"""

import logging
from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from ..utils.workbook_io import (
    OpenpyxlUnavailable,
    fill_workbook,
    find_rows,
    list_sheets,
    read_rows,
    write_workbook,
)

logger = logging.getLogger(__name__)


class ManageWorkbookParams(BaseModel):
    action: Literal["sheets", "read", "find", "write", "fill"] = Field(
        ..., description="sheets | read | find | write | fill"
    )
    path: Optional[str] = Field(
        default=None, description="Workbook to read, or the form to fill (fill)"
    )
    sheet: Optional[str] = Field(default=None, description="Sheet name; default first/active")

    # read/find
    min_row: int = Field(default=1, description="First row to read (1-based)")
    limit: int = Field(default=20, description="Max rows returned (cap 100)")
    columns: Optional[str] = Field(
        default=None, description="Project these columns only, e.g. 'A,C,F' or '1,3,6'"
    )
    query: Optional[str] = Field(default=None, description="Regex to find rows (find)")
    column: Optional[str] = Field(
        default=None, description="Restrict the find query to these columns, e.g. 'B'"
    )

    # write/fill
    spec: Optional[Dict[str, Any]] = Field(
        default=None,
        description="write: {sheets:[{title,rows,header_row,widths,label_col,images:[{path,cell}]}]}",
    )
    output_file: Optional[str] = Field(default=None, description="The .xlsx to create")
    cells: Optional[Dict[str, Any]] = Field(
        default=None, description="fill: cell→value, e.g. {'B3':'통과'}"
    )
    rows_at: Optional[Dict[str, Any]] = Field(
        default=None, description="fill: {start_row, rows:[[...]], start_col}"
    )
    images: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="fill: [{path, cell}] screenshots to embed"
    )

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "sheets": frozenset({"path"}),
        "read": frozenset({"path", "sheet", "min_row", "limit", "columns"}),
        "find": frozenset({"path", "sheet", "query", "column", "min_row", "limit", "columns"}),
        "write": frozenset({"spec", "output_file"}),
        "fill": frozenset({"path", "sheet", "output_file", "cells", "rows_at", "images"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageWorkbookParams":
        if self.action in ("sheets", "read", "find", "fill") and not (self.path or "").strip():
            raise ValueError(f"{self.action} needs path (the .xlsx to open)")
        if self.action == "find" and not (self.query or "").strip():
            raise ValueError("find needs query (a regex)")
        if self.action in ("write", "fill") and not (self.output_file or "").strip():
            raise ValueError(f"{self.action} needs output_file (the .xlsx to create)")
        if self.action == "write" and not self.spec:
            raise ValueError("write needs spec — {sheets:[{title, rows, ...}]}")
        if self.action == "fill" and not (self.cells or self.rows_at or self.images):
            raise ValueError("fill needs at least one of cells / rows_at / images")
        return self


@register_tool(
    name="manage_workbook",
    params=ManageWorkbookParams,
    description=(
        "Excel without boilerplate: list/read/regex-find rows; write styled sheets from a "
        "data spec; fill a copy of an existing form (screenshots embeddable)."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def manage_workbook(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageWorkbookParams,
) -> Dict[str, Any]:
    try:
        if params.action == "sheets":
            return list_sheets(str(params.path))
        if params.action == "read":
            return read_rows(
                str(params.path),
                params.sheet,
                min_row=params.min_row,
                limit=params.limit,
                columns=params.columns,
            )
        if params.action == "find":
            return find_rows(
                str(params.path),
                str(params.query),
                params.sheet,
                column=params.column,
                min_row=params.min_row,
                limit=params.limit,
                columns=params.columns,
            )
        if params.action == "write":
            return write_workbook(dict(params.spec or {}), str(params.output_file))
        return fill_workbook(
            str(params.path),
            str(params.output_file),
            sheet=params.sheet,
            cells=params.cells,
            rows_at=params.rows_at,
            images=params.images,
        )
    except OpenpyxlUnavailable as exc:
        return {"success": False, "error": str(exc)}
    except KeyError as exc:
        return {"success": False, "error": str(exc.args[0]) if exc.args else str(exc)}
    except OSError as exc:
        return {"success": False, "error": f"Workbook I/O failed: {exc}"}
    except Exception as exc:  # noqa: BLE001 - a bad regex/spec must answer, not raise
        logger.warning("manage_workbook %s failed: %s", params.action, exc)
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
