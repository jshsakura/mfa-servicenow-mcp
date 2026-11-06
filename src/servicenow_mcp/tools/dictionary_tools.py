"""manage_dictionary — add a column to a table, label it, adjust it. Never deletes.

A field is a ``sys_dictionary`` row; inserting one makes the platform create the
physical column, the same as saving the Dictionary form. Its label lives apart,
in ``sys_documentation`` — one row per (table, element, language). Both are
captured in the session's current update set, which is why every write here
passes the shared confirm + update-set gates first.

A new column is hard to take back (it ships in the update set and every
instance it lands on grows it), so create_field never writes on the first call:
it runs every check and returns a preview, and only a re-send naming the exact
column — ``confirm_column='<table>.<element>'`` — creates it.

Out of scope on purpose: changing a column's type, deleting a column, creating
a table. Each can destroy data already stored and is a human decision.

Every write is re-read. The dictionary row alone does not prove a column — an
unknown field in a query is DROPPED, not rejected — so the column is proven by
the ISEMPTY/ISNOTEMPTY split (the two counts add up to the table only when the
condition was applied), and reported ``undetermined`` on an empty table.
"""

import logging
import re
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value
from servicenow_mcp.utils.query_fields import table_ancestry
from servicenow_mcp.utils.registry import register_tool

from .sn_api import invalidate_query_cache, sn_count, sn_query_page

logger = logging.getLogger(__name__)

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_LANG = re.compile(r"^[a-z]{2}(_[A-Z]{2})?$")
_DICT_FIELDS = (
    "sys_id,name,element,internal_type,column_label,max_length,default_value,mandatory,"
    "read_only,active,reference,choice,comments"
)
_DOC_FIELDS = "sys_id,name,element,language,label,plural,hint"
_SETTABLE = ("max_length", "default_value", "mandatory", "read_only", "comments")


class ManageDictionaryParams(BaseModel):
    """Table columns (sys_dictionary) and their labels (sys_documentation)."""

    action: Literal["get", "create_field", "set_label", "update_field"] = Field(...)
    table: str = Field(..., description="Table, e.g. sc_req_item")
    element: str = Field(..., description="Column name; a new one on a non-x_ table starts u_")

    internal_type: Optional[str] = Field(
        default=None, description="create_field: type, e.g. string, integer, reference, choice"
    )
    column_label: Optional[str] = Field(default=None, description="create_field: label (en)")
    labels: Optional[Dict[str, str]] = Field(
        default=None, description="create_field: other languages, e.g. {'ko': '요청 사유'}"
    )
    reference: Optional[str] = Field(default=None, description="create_field: referenced table")
    choice: Optional[int] = Field(
        default=None, description="create_field: 1 dropdown, 2 dropdown with -- None --, 3 suggest"
    )
    max_length: Optional[int] = Field(default=None, description="Column length (never shrunk)")
    default_value: Optional[str] = Field(default=None, description="Default value")
    mandatory: Optional[bool] = Field(default=None)
    read_only: Optional[bool] = Field(default=None)
    comments: Optional[str] = Field(default=None, description="Field description (Comments)")
    add_to_form: bool = Field(
        default=False,
        description="create_field: keep the form placement the platform adds (default: undo it)",
    )

    language: str = Field(default="en", description="set_label: language code")
    label: Optional[str] = Field(default=None, description="set_label: label text")
    plural: Optional[str] = Field(default=None, description="set_label: plural label")
    hint: Optional[str] = Field(default=None, description="set_label: hover hint")
    confirm_column: Optional[str] = Field(
        default=None,
        description="create_field: '<table>.<element>' after reading the preview; approves it",
    )
    confirm_inherited: Optional[str] = Field(
        default=None,
        description="update_field: table the column is defined on when not `table`; approves it",
    )

    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "get": frozenset({"table", "element"}),
        "create_field": frozenset(
            {
                "table",
                "element",
                "internal_type",
                "column_label",
                "labels",
                "reference",
                "choice",
                "max_length",
                "default_value",
                "mandatory",
                "read_only",
                "comments",
                "add_to_form",
                "confirm_column",
                "dry_run",
            }
        ),
        "set_label": frozenset(
            {"table", "element", "language", "label", "plural", "hint", "dry_run"}
        ),
        "update_field": frozenset(
            {
                "table",
                "element",
                "max_length",
                "default_value",
                "mandatory",
                "read_only",
                "comments",
                "confirm_inherited",
                "dry_run",
            }
        ),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageDictionaryParams":
        if not _NAME.match(self.table) or not _NAME.match(self.element):
            raise ValueError("table and element must be lowercase table/column names")
        if self.max_length is not None and self.max_length < 1:
            raise ValueError("max_length must be positive")
        a = self.action
        if a == "create_field":
            if not self.table.startswith("x_") and not self.element.startswith(("u_", "x_")):
                raise ValueError(
                    "a new column on a table outside your own scoped app starts with u_ "
                    "(or x_<scope>_), like the Dictionary form names it"
                )
            if not self.internal_type or not _NAME.match(self.internal_type):
                raise ValueError("create_field needs internal_type, e.g. string")
            if not (self.column_label or "").strip():
                raise ValueError("create_field needs column_label")
            if (self.internal_type == "reference") != bool(self.reference):
                raise ValueError("reference is required for, and only for, internal_type=reference")
            if self.reference and not _NAME.match(self.reference):
                raise ValueError("reference must be a table name")
            if self.choice is not None and self.choice not in (0, 1, 2, 3):
                raise ValueError("choice must be 0-3")
            for lang, text in (self.labels or {}).items():
                if not _LANG.match(lang) or not str(text).strip():
                    raise ValueError("labels maps a language code to a non-empty label")
        elif a == "set_label":
            if not _LANG.match(self.language):
                raise ValueError("language must look like 'en' or 'pt_BR'")
            if all(x is None for x in (self.label, self.plural, self.hint)):
                raise ValueError("set_label needs label, plural or hint")
        elif a == "update_field":
            if all(getattr(self, f) is None for f in _SETTABLE):
                raise ValueError(f"update_field needs one of {', '.join(_SETTABLE)}")
        return self


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _raw(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def _s(value: Any) -> str:
    v = _raw(value)
    return "" if v is None else str(v)


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "message": message, **extra}


def _read(config, auth_manager, table: str, query: str, fields: str, limit: int = 50):
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        limit=limit,
        offset=0,
        display_value=False,
        no_count=True,
        fail_silently=False,
    )
    return rows


def _write(config, auth_manager, method: str, table: str, sys_id: Optional[str], data) -> str:
    url = f"{config.api_url}/table/{table}" + (f"/{sys_id}" if sys_id else "")
    resp = auth_manager.make_request(
        method, url, json=data, headers=auth_manager.get_headers(), timeout=config.timeout
    )
    resp.raise_for_status()
    invalidate_query_cache(table=table)
    if sys_id:
        return sys_id
    return _s(resp.json().get("result", {}).get("sys_id"))


def _definition(
    config, auth_manager, table: str, element: str
) -> Tuple[List[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """(ancestry, nearest dictionary row or None, refusal). Raises nothing."""
    try:
        ancestry = table_ancestry(config, auth_manager, table)
    except Exception as e:
        return [], None, _fail(f"Could not read the hierarchy of {table}: {e}. Nothing written.")
    if not ancestry:
        return (
            [],
            None,
            _fail(
                f"Table {table!r} was not resolved (sys_db_object): absent, hidden from this "
                "account, or the read failed. Nothing written.",
                determined=False,
            ),
        )
    try:
        rows = _read(
            config,
            auth_manager,
            "sys_dictionary",
            "nameIN" + ",".join(ancestry) + f"^element={element}",
            _DICT_FIELDS,
        )
    except Exception as e:
        return ancestry, None, _fail(f"Could not read sys_dictionary: {e}. Nothing written.")
    for name in ancestry:
        for r in rows:
            if _s(r.get("name")) == name:
                return ancestry, r, None
    return ancestry, None, None


def _child_clash(
    config, auth_manager, table: str, element: str, ancestry: List[str]
) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """Tables extending *table* that already hold *element*. ([], refusal) when unprovable."""
    try:
        rows = _read(config, auth_manager, "sys_dictionary", f"element={element}", "name", 200)
        others = sorted({_s(r.get("name")) for r in rows} - set(ancestry) - {""})
        if len(rows) >= 200:
            raise RuntimeError("the read hit its 200-row cap")
        clash = [t for t in others if table in (table_ancestry(config, auth_manager, t) or [])]
    except Exception as e:
        return [], _fail(
            f"Could not prove no table extending {table} already holds {element} ({e}). "
            "Nothing written.",
            determined=False,
        )
    return clash, None


def _labels(config, auth_manager, tables: List[str], element: str) -> List[Dict[str, Any]]:
    return _read(
        config,
        auth_manager,
        "sys_documentation",
        "nameIN" + ",".join(tables) + f"^element={element}",
        _DOC_FIELDS,
        200,
    )


def _shape_def(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {f: _s(row.get(f)) for f in _DICT_FIELDS.split(",") if f != "sys_id"}
    out["defined_on"] = out.pop("name")
    return {k: v for k, v in out.items() if v != ""}


def _shape_label(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {f: _s(row.get(f)) for f in ("name", "language", "label", "plural", "hint")}
    return {k: v for k, v in out.items() if v != ""}


def _column_proof(config, auth_manager, table: str, element: str) -> Dict[str, Any]:
    """Whether a query condition on the column is APPLIED — i.e. the column exists."""
    try:
        total = sn_count(config, auth_manager, table, "")
        empty = sn_count(config, auth_manager, table, f"{element}ISEMPTY")
        filled = sn_count(config, auth_manager, table, f"{element}ISNOTEMPTY")
    except Exception as e:
        return {"proven": None, "reason": f"count read failed: {e}"}
    if total == 0:
        return {"proven": None, "reason": "table has no rows; a dropped condition looks the same"}
    return {"proven": empty + filled == total, "rows": total}


def _capture(config, auth_manager, table: str, element: str) -> Dict[str, Any]:
    """Newest update-set record of this column's dictionary entry."""
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_update_xml",
            query=f"name=sys_dictionary_{table}_{element}",
            fields="update_set.name,update_set.state,sys_updated_on",
            limit=1,
            offset=0,
            orderby="-sys_updated_on",
            display_value=False,
            fail_silently=False,
        )
    except Exception as e:
        return {"checked": False, "error": str(e)}
    if not rows:
        return {"checked": True, "found": False}
    r = rows[0]
    return {
        "checked": True,
        "found": True,
        "update_set": _s(r.get("update_set.name")),
        "update_set_state": _s(r.get("update_set.state")),
        "captured_on": _s(r.get("sys_updated_on")),
    }


def _form_side_effect(config, auth_manager, table: str, element: str) -> Dict[str, Any]:
    """Form sections the platform appended the new column to, and their update-set entry.

    Measured on live instances: inserting a sys_dictionary row (script or REST)
    appends the column to a section of the table's Default view and captures that
    WHOLE section as a Form Layout record — importing it replaces the target's
    section with this instance's. Never silent.
    """
    try:
        rows = _read(
            config,
            auth_manager,
            "sys_ui_element",
            f"element={element}^sys_ui_section.name={table}",
            "sys_id,position,sys_ui_section,sys_ui_section.view",
            20,
        )
        sections = []
        for r in rows:
            sid = _s(r.get("sys_ui_section"))
            cap = _read(
                config,
                auth_manager,
                "sys_update_xml",
                f"name=sys_ui_section_{sid}",
                "update_set.name",
                5,
            )
            sections.append(
                {
                    "section": sid,
                    "view": _s(r.get("sys_ui_section.view")),
                    "position": _s(r.get("position")),
                    "form_layout_in_sets": sorted({_s(c.get("update_set.name")) for c in cap}),
                }
            )
    except Exception as e:
        return {"checked": False, "error": str(e)}
    return {"checked": True, "added_to_form": bool(sections), "sections": sections}


_SECTION_CAP = 500


def _form_entries(config, auth_manager, table: str) -> Tuple[List[str], set]:
    """(this table's form section ids, sys_ids of their Form Layout update records). Raises."""
    sections = _read(
        config, auth_manager, "sys_ui_section", f"name={table}", "sys_id", _SECTION_CAP
    )
    if len(sections) >= _SECTION_CAP:
        raise RuntimeError(f"{table} has {_SECTION_CAP}+ form sections; snapshot would be partial")
    ids = [_s(r.get("sys_id")) for r in sections if _s(r.get("sys_id"))]
    if not ids:
        return [], set()
    names = ",".join(f"sys_ui_section_{i}" for i in ids)
    entries = _read(config, auth_manager, "sys_update_xml", f"nameIN{names}", "sys_id", 1000)
    return ids, {_s(e.get("sys_id")) for e in entries}


def _undo_form_placement(
    config, auth_manager, table: str, element: str, before: set
) -> Dict[str, Any]:
    """Remove what the platform added to the form for the new column, and only that.

    Order matters: deleting the element re-captures its section, so the element
    goes first and the Form Layout record second. Only a record that did not exist
    before this call is removed — one already in a set holds someone's form work,
    and it falls back to the pre-create layout by the re-capture alone.
    """
    out: Dict[str, Any] = {"elements_removed": 0, "entries_removed": 0}
    try:
        elements = _read(
            config,
            auth_manager,
            "sys_ui_element",
            f"element={element}^sys_ui_section.name={table}",
            "sys_id",
            20,
        )
        for e in elements:
            url = f"{config.api_url}/table/sys_ui_element/{_s(e.get('sys_id'))}"
            auth_manager.make_request(
                "DELETE", url, headers=auth_manager.get_headers(), timeout=config.timeout
            ).raise_for_status()
            out["elements_removed"] += 1
        invalidate_query_cache(table="sys_ui_element")
        _, after = _form_entries(config, auth_manager, table)
        for sys_id in sorted(after - before):
            url = f"{config.api_url}/table/sys_update_xml/{sys_id}"
            auth_manager.make_request(
                "DELETE", url, headers=auth_manager.get_headers(), timeout=config.timeout
            ).raise_for_status()
            out["entries_removed"] += 1
        invalidate_query_cache(table="sys_update_xml")
        _, final = _form_entries(config, auth_manager, table)
        left = sorted(final - before)
    except Exception as e:
        return {**out, "undone": False, "error": str(e)}
    out["undone"] = not left
    if left:
        out["entries_left"] = left
    return out


def _mismatch(row: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        k: {"requested": v, "actual": _s(row.get(k))}
        for k, v in data.items()
        if str(v).lower() != _s(row.get(k)).lower()
    }


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


def _get(config, auth_manager, p: ManageDictionaryParams) -> Dict[str, Any]:
    ancestry, row, refusal = _definition(config, auth_manager, p.table, p.element)
    if refusal:
        return refusal
    if row is None:
        return _fail(
            f"{p.element!r} was not returned for {p.table} or the tables it extends: absent, "
            "or hidden from this account.",
            determined=False,
        )
    try:
        labels = [_shape_label(r) for r in _labels(config, auth_manager, ancestry, p.element)]
    except Exception as e:
        labels, label_error = [], str(e)
    else:
        label_error = ""
    out: Dict[str, Any] = {"success": True, "table": p.table, "field": _shape_def(row)}
    out["labels"] = labels if not label_error else f"unread: {label_error}"
    return out


def _create_field(config, auth_manager, p: ManageDictionaryParams) -> Dict[str, Any]:
    ancestry, existing, refusal = _definition(config, auth_manager, p.table, p.element)
    if refusal:
        return refusal
    if existing is not None:
        owner = _s(existing.get("name"))
        where = owner if owner == p.table else f"{owner} (which {p.table} inherits)"
        return _fail(
            f"{p.element} already exists on {where}. Nothing written.",
            field=_shape_def(existing),
        )
    try:
        known = _read(
            config,
            auth_manager,
            "sys_glide_object",
            f"name={safe_value(p.internal_type or '').value}",
            "name",
            1,
        )
        if p.reference and not table_ancestry(config, auth_manager, p.reference):
            return _fail(f"Reference table {p.reference!r} was not resolved. Nothing written.")
    except Exception as e:
        return _fail(f"Could not check the type/reference: {e}. Nothing written.")
    if not known:
        return _fail(
            f"internal_type {p.internal_type!r} is not a field type on this instance "
            "(sys_glide_object). Nothing written.",
            determined=False,
        )
    clash, refusal = _child_clash(config, auth_manager, p.table, p.element, ancestry)
    if refusal:
        return refusal
    if clash:
        return _fail(
            f"{p.element} already exists on {', '.join(clash)}, which extend {p.table}; a "
            f"column on {p.table} would collide with it. Nothing written.",
            conflicts=clash,
        )

    data: Dict[str, Any] = {
        "name": p.table,
        "element": p.element,
        "internal_type": p.internal_type,
        "column_label": (p.column_label or "").strip(),
    }
    if p.reference:
        data["reference"] = p.reference
    if p.choice is not None:
        data["choice"] = str(p.choice)
    if p.max_length is not None:
        data["max_length"] = str(p.max_length)
    if p.default_value is not None:
        data["default_value"] = p.default_value
    if p.comments is not None:
        data["comments"] = p.comments
    for f in ("mandatory", "read_only"):
        if getattr(p, f) is not None:
            data[f] = "true" if getattr(p, f) else "false"
    wanted = {"en": data["column_label"], **{k: v.strip() for k, v in (p.labels or {}).items()}}
    approval = f"{p.table}.{p.element}"
    if p.dry_run or p.confirm_column != approval:
        try:
            rows: Any = sn_count(config, auth_manager, p.table, "")
        except Exception as e:
            rows = f"unread: {e}"
        preview: Dict[str, Any] = {
            "would_create": {"sys_dictionary": data, "labels": wanted},
            "table_rows": rows,
            "checks": [
                f"{p.element} is on neither {p.table}, the tables it extends, nor any table "
                "extending it",
                f"type {p.internal_type} exists"
                + (f"; {p.reference} exists" if p.reference else ""),
            ],
            "note": "Every table extending this one gets the column too. It is captured in "
            "your current update set and travels with it. The platform also appends it to "
            f"a section of {p.table}'s Default view form and captures that whole section "
            "(Form Layout) in the same set; "
            + (
                "add_to_form=true keeps that."
                if p.add_to_form
                else "this call undoes that placement right after the create."
            ),
        }
        if p.dry_run:
            return {"success": True, "dry_run": True, **preview}
        wrong = f" ({p.confirm_column!r} does not name it)" if p.confirm_column else ""
        return {
            "success": False,
            "approval_required": True,
            "message": f"Nothing written{wrong}. Review the preview, then re-send the same call "
            f"with confirm_column={approval!r} to create the column.",
            **preview,
        }

    form_before: Optional[set] = None
    form_snapshot_error = ""
    if not p.add_to_form:
        try:
            _, form_before = _form_entries(config, auth_manager, p.table)
        except Exception as e:
            form_snapshot_error = str(e)
    try:
        sys_id = _write(config, auth_manager, "POST", "sys_dictionary", None, data)
    except Exception as e:
        return _fail(f"Failed to create the field: {e}")
    out: Dict[str, Any] = {"success": True, "sys_id": sys_id}
    if form_before is not None:
        out["form_placement_undo"] = _undo_form_placement(
            config, auth_manager, p.table, p.element, form_before
        )
    elif form_snapshot_error:
        out["form_placement_undo"] = {
            "undone": False,
            "error": f"not attempted — the pre-create snapshot failed ({form_snapshot_error})",
        }

    # Labels: the platform writes the en row from column_label; add what is missing.
    label_results: Dict[str, str] = {}
    try:
        have = {
            _s(r.get("language")): r
            for r in _labels(config, auth_manager, [p.table], p.element)
            if _s(r.get("name")) == p.table
        }
        for lang, text in wanted.items():
            row = have.get(lang)
            if row is None:
                _write(
                    config,
                    auth_manager,
                    "POST",
                    "sys_documentation",
                    None,
                    {"name": p.table, "element": p.element, "language": lang, "label": text},
                )
                label_results[lang] = "created"
            elif _s(row.get("label")) != text:
                _write(
                    config,
                    auth_manager,
                    "PATCH",
                    "sys_documentation",
                    _s(row.get("sys_id")),
                    {"label": text},
                )
                label_results[lang] = "updated"
            else:
                label_results[lang] = "present"
    except Exception as e:
        out["success"] = False
        out["label_error"] = f"{e} — the field exists; finish labels with set_label."
    out["labels_written"] = label_results
    return _finish(config, auth_manager, p, data, wanted, out)


def _finish(config, auth_manager, p, data, wanted, out) -> Dict[str, Any]:
    """Re-read everything a create claims, and say what each read proved."""
    try:
        rows = _read(
            config,
            auth_manager,
            "sys_dictionary",
            f"name={p.table}^element={p.element}",
            _DICT_FIELDS,
            2,
        )
    except Exception as e:
        rows, out["verified"] = [], False
        out["message"] = f"Write sent but the re-read failed ({e}); UNVERIFIED."
    if rows:
        bad = _mismatch(rows[0], data)
        out["field"] = _shape_def(rows[0])
        if bad:
            out["success"] = False
            out["not_applied"] = bad
    elif "message" not in out:
        out["success"] = False
        out["message"] = "The dictionary row was not returned on re-read; UNVERIFIED."
    try:
        labels = {
            _s(r.get("language")): _s(r.get("label"))
            for r in _labels(config, auth_manager, [p.table], p.element)
            if _s(r.get("name")) == p.table
        }
        missing = {k: v for k, v in wanted.items() if labels.get(k) != v}
        out["labels"] = labels
        if missing:
            out["success"] = False
            out["labels_not_applied"] = missing
    except Exception as e:
        out["labels"] = f"unread: {e}"
    form = _form_side_effect(config, auth_manager, p.table, p.element)
    out["form_layout"] = form
    if not form.get("checked"):
        out["form_layout_note"] = (
            "Could not check whether the platform added the field to a form; look at "
            f"{p.table}'s form layout and the update set for a Form Layout entry."
        )
    elif form["added_to_form"] and p.add_to_form:
        out["form_layout_note"] = (
            f"{p.element} is on {p.table}'s form as asked (add_to_form=true); that section's "
            "Form Layout is in the update set and replaces the target's section on import."
        )
    elif form["added_to_form"]:
        out["success"] = False
        out["form_layout_note"] = (
            f"The platform added {p.element} to {p.table}'s form and captured that whole "
            "section (Form Layout) in the update set, and undoing it did not finish — "
            "importing it replaces the target's section with this one. Remove the element "
            "and its new Form Layout entry, or keep them only if the layout is part of the task."
        )
    out["column"] = _column_proof(config, auth_manager, p.table, p.element)
    if out["column"]["proven"] is False:
        out["success"] = False
    cap = _capture(config, auth_manager, p.table, p.element)
    out["update_set_capture"] = cap
    if not cap.get("checked"):
        out["capture_note"] = "Update-set capture could not be read — do not count it as shipped."
    elif not cap.get("found") or not cap.get("update_set"):
        out["capture_note"] = (
            "No update set holds this field's dictionary entry — it will not travel."
        )
    return out


def _set_label(config, auth_manager, p: ManageDictionaryParams) -> Dict[str, Any]:
    _, row, refusal = _definition(config, auth_manager, p.table, p.element)
    if refusal:
        return refusal
    if row is None:
        return _fail(
            f"{p.element!r} was not returned for {p.table} or its parents. Nothing written.",
            determined=False,
        )
    data = {f: getattr(p, f).strip() for f in ("label", "plural", "hint") if getattr(p, f)}
    lang = safe_value(p.language).value
    try:
        mine = _read(
            config,
            auth_manager,
            "sys_documentation",
            f"name={p.table}^element={p.element}^language={lang}",
            _DOC_FIELDS,
            5,
        )
    except Exception as e:
        return _fail(f"Could not read sys_documentation: {e}. Nothing written.")
    if len(mine) > 1:
        return _fail(
            f"{len(mine)} {p.language} label rows exist for {p.table}.{p.element}; resolve the "
            "duplicate by hand. Nothing written."
        )
    defined_on = _s(row.get("name"))
    note = (
        f"{p.element} is defined on {defined_on}; this label applies to {p.table} only "
        f"(an override), not to {defined_on} or its other children."
        if defined_on != p.table
        else ""
    )
    if p.dry_run:
        out = {
            "success": True,
            "dry_run": True,
            "operation": "update" if mine else "create",
            "would_write": data,
        }
        return {**out, "note": note} if note else out
    try:
        if mine:
            sys_id = _write(
                config,
                auth_manager,
                "PATCH",
                "sys_documentation",
                _s(mine[0].get("sys_id")),
                data,
            )
        else:
            sys_id = _write(
                config,
                auth_manager,
                "POST",
                "sys_documentation",
                None,
                {"name": p.table, "element": p.element, "language": p.language, **data},
            )
        back = _read(config, auth_manager, "sys_documentation", f"sys_id={sys_id}", _DOC_FIELDS, 1)
    except Exception as e:
        return _fail(f"Label write or re-read failed: {e}; UNVERIFIED.")
    if not back:
        return _fail("The label row was not returned on re-read; UNVERIFIED.")
    bad = _mismatch(back[0], data)
    out = {"success": not bad, "sys_id": sys_id, "label": _shape_label(back[0])}
    if bad:
        out["not_applied"] = bad
    if note:
        out["note"] = note
    return out


def _update_field(config, auth_manager, p: ManageDictionaryParams) -> Dict[str, Any]:
    _, row, refusal = _definition(config, auth_manager, p.table, p.element)
    if refusal:
        return refusal
    if row is None:
        return _fail(
            f"{p.element!r} was not returned for {p.table} or its parents. Nothing written.",
            determined=False,
        )
    owner = _s(row.get("name"))
    if owner != p.table and p.confirm_inherited != owner:
        return _fail(
            f"{p.element} is defined on {owner}; a change there applies to every table that "
            f"extends it. Re-send with confirm_inherited={owner!r} to approve. Nothing written.",
            defined_on=owner,
        )
    current = _s(row.get("max_length"))
    if p.max_length is not None and current.isdigit() and p.max_length < int(current):
        return _fail(
            f"max_length {p.max_length} is below the current {current}; shrinking a column can "
            "truncate stored values and is a human decision. Nothing written."
        )
    data: Dict[str, Any] = {}
    if p.max_length is not None:
        data["max_length"] = str(p.max_length)
    if p.default_value is not None:
        data["default_value"] = p.default_value
    if p.comments is not None:
        data["comments"] = p.comments
    for f in ("mandatory", "read_only"):
        if getattr(p, f) is not None:
            data[f] = "true" if getattr(p, f) else "false"
    if p.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "defined_on": owner,
            "current": _shape_def(row),
            "would_write": data,
        }
    sys_id = _s(row.get("sys_id"))
    previous = {k: _s(row.get(k)) for k in data}
    try:
        _write(config, auth_manager, "PATCH", "sys_dictionary", sys_id, data)
        back = _read(config, auth_manager, "sys_dictionary", f"sys_id={sys_id}", _DICT_FIELDS, 1)
    except Exception as e:
        return _fail(f"Field write or re-read failed: {e}; UNVERIFIED.")
    if not back:
        return _fail("The dictionary row was not returned on re-read; UNVERIFIED.")
    bad = _mismatch(back[0], data)
    out: Dict[str, Any] = {
        "success": not bad,
        "sys_id": sys_id,
        "previous": previous,
        "field": _shape_def(back[0]),
        "update_set_capture": _capture(config, auth_manager, owner, p.element),
    }
    if bad:
        out["not_applied"] = bad
    return out


@register_tool(
    "manage_dictionary",
    params=ManageDictionaryParams,
    description="Table columns (sys_dictionary) + labels: get, create_field (with en/other labels), set_label, update_field. No type change/delete.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_dictionary(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageDictionaryParams,
) -> Dict[str, Any]:
    action = {
        "get": _get,
        "create_field": _create_field,
        "set_label": _set_label,
        "update_field": _update_field,
    }[params.action]
    return action(config, auth_manager, params)
