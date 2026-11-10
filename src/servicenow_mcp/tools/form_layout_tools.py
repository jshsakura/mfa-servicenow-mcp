"""manage_form_layout — which fields a form shows, in which section and order.

A form is ``sys_ui_form`` (table + view); its tabs are ``sys_ui_section`` rows
ordered by ``sys_ui_form_section``; a section's content is ``sys_ui_element``
rows by ``position``. Two columns are stored as ``.begin_split``, left fields,
``.split``, right fields, ``.end_split`` (read off live forms; older layouts may
omit ``.begin_split``). The Default view's
``sys_ui_view`` sys_id is literally ``Default view``.

Why every write previews first: a form change is captured as a WHOLE section
(``sys_ui_section_<id>``, type Form Layout) and the section order as
``sys_ui_form_sections_<form id>``. Importing either replaces the target's
section/order with this instance's — someone else's layout work included. So a
write runs every check, returns the before/after layout, and only a re-send
naming the section — ``confirm_layout='<table>:<section>'`` — changes it.

copy_from recreates another table's sections (caption, order, columns) on this
form — the usual "make it like the REQ form". Fields missing on this table or
already on this form stop it (name them in ``exclude`` or create them first);
related lists and formatters are listed as not copied, never dropped silently.

Capture: ``sys_ui_section`` is ``update_synch_custom`` — the platform writes the
Form Layout entry only when its own code saves the section (its SysSection
script calls the update manager explicitly), and a Table API write never does.
So a write diffs the update set before/after and is ``success`` only when every
rewritten record got a NEW entry; otherwise it says what is missing and how to
capture it. The capture is never faked by writing ``sys_update_xml``.
Measured live: adds, moves and removed fields are NOT captured; remove_section
IS (the platform's own delete rule writes a DELETE for the section and the
form's tab order), and the same diff reports both truthfully.

Out of scope: related lists, formatters, annotations, per-user layouts.
Removing a field from the form never touches the column or its data.
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

from .sn_api import invalidate_query_cache, sn_query_page

logger = logging.getLogger(__name__)

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_DEFAULT_VIEW = "Default view"
_MAIN = "main"  # how the caption-less first section is named in approvals
_BEGIN_SPLIT, _SPLIT, _END_SPLIT = ".begin_split", ".split", ".end_split"
_MARKERS = (_BEGIN_SPLIT, _SPLIT, _END_SPLIT)
_TABLES = ("sys_ui_form", "sys_ui_section", "sys_ui_form_section", "sys_ui_element")


class ManageFormLayoutParams(BaseModel):
    """Form layout (sys_ui_section / sys_ui_element)."""

    action: Literal[
        "get", "add_section", "add_fields", "remove_fields", "remove_section", "copy_from"
    ] = Field(...)
    table: str = Field(..., description="Table whose form it is, e.g. sc_req_item")
    view: str = Field(default=_DEFAULT_VIEW, description="Form view name")
    section: Optional[str] = Field(
        default=None, description="Section caption; 'main' is the first, caption-less section"
    )
    fields: Optional[List[str]] = Field(default=None, description="Column names, in order")
    columns: int = Field(default=1, description="add_section: 1 or 2 columns")
    after: Optional[str] = Field(
        default=None, description="add_fields: insert after this field (default: section end)"
    )
    position: Optional[int] = Field(
        default=None, description="add_section: tab position (default: last)"
    )
    source_table: Optional[str] = Field(
        default=None, description="copy_from: table whose form sections are copied, e.g. sc_request"
    )
    sections: Optional[List[str]] = Field(
        default=None, description="copy_from: source section captions (default: all but main)"
    )
    exclude: Optional[List[str]] = Field(
        default=None, description="copy_from: fields to leave out of the copy"
    )
    confirm_layout: Optional[str] = Field(
        default=None,
        description="'<table>:<section>' (copy_from: '<table>:<source_table>') after the preview",
    )

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "get": frozenset({"table", "view"}),
        "add_section": frozenset(
            {"table", "view", "section", "fields", "columns", "position", "confirm_layout"}
        ),
        "add_fields": frozenset({"table", "view", "section", "fields", "after", "confirm_layout"}),
        "remove_fields": frozenset({"table", "view", "section", "fields", "confirm_layout"}),
        "remove_section": frozenset({"table", "view", "section", "confirm_layout"}),
        "copy_from": frozenset(
            {"table", "view", "source_table", "sections", "exclude", "confirm_layout"}
        ),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageFormLayoutParams":
        if not _NAME.match(self.table):
            raise ValueError("table must be a table name")
        if not self.view.strip():
            raise ValueError("view must not be empty")
        a = self.action
        if a == "get":
            return self
        if a == "copy_from":
            if not self.source_table or not _NAME.match(self.source_table):
                raise ValueError("copy_from needs source_table")
            if self.source_table == self.table:
                raise ValueError("source_table is the same table")
            return self
        if not (self.section or "").strip():
            raise ValueError(f"{a} needs section (its caption, or 'main')")
        if a in ("add_section", "add_fields", "remove_fields"):
            if not self.fields:
                raise ValueError(f"{a} needs fields")
            bad = [f for f in self.fields if not _NAME.match(f)]
            if bad:
                raise ValueError(f"not column names: {bad}")
            if len(set(self.fields)) != len(self.fields):
                raise ValueError("fields lists a column twice")
        if a == "add_section":
            if (self.section or "").strip().lower() == _MAIN:
                raise ValueError("the main section already exists; use add_fields")
            if self.columns not in (1, 2):
                raise ValueError("columns must be 1 or 2")
        if a == "remove_section" and (self.section or "").strip().lower() == _MAIN:
            raise ValueError("the main section is never removed")
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


def _fresh() -> None:
    """Layout writes re-capture sections server-side; never answer from a cached page."""
    for t in (*_TABLES, "sys_update_xml"):
        invalidate_query_cache(table=t)


def _read(config, auth_manager, table: str, query: str, fields: str, limit: int = 500):
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
    if len(rows) >= limit:
        raise RuntimeError(f"{table} read hit its {limit}-row cap; the layout would be partial")
    return rows


def _call(config, auth_manager, method: str, table: str, sys_id: str = "", data=None) -> str:
    url = f"{config.api_url}/table/{table}" + (f"/{sys_id}" if sys_id else "")
    kwargs: Dict[str, Any] = {"headers": auth_manager.get_headers(), "timeout": config.timeout}
    if data is not None:
        kwargs["json"] = data
    resp = auth_manager.make_request(method, url, **kwargs)
    resp.raise_for_status()
    if method == "POST":
        return _s(resp.json().get("result", {}).get("sys_id"))
    return sys_id


def _view_id(config, auth_manager, view: str) -> Optional[str]:
    if view == _DEFAULT_VIEW:
        return _DEFAULT_VIEW
    rows = _read(config, auth_manager, "sys_ui_view", f"name={safe_value(view).value}", "sys_id", 5)
    return _s(rows[0].get("sys_id")) if len(rows) == 1 else None


def _layout(config, auth_manager, table: str, view: str) -> Dict[str, Any]:
    """The form as it stands: sections in tab order, each with its elements. Raises."""
    _fresh()
    view_id = _view_id(config, auth_manager, view)
    if view_id is None:
        raise LookupError(f"view {view!r} is not one sys_ui_view row on this instance")
    forms = _read(config, auth_manager, "sys_ui_form", f"name={table}^view={view_id}", "sys_id", 5)
    if len(forms) != 1:
        raise LookupError(
            f"{table} has {len(forms)} sys_ui_form rows for view {view!r}; this tool edits a "
            "form that exists exactly once (save its layout once in the UI first)"
        )
    form_id = _s(forms[0].get("sys_id"))
    links = _read(
        config,
        auth_manager,
        "sys_ui_form_section",
        f"sys_ui_form={form_id}",
        "sys_id,position,sys_ui_section,sys_ui_section.caption",
    )
    links.sort(key=lambda r: int(_s(r.get("position")) or 0))
    section_ids = [_s(r.get("sys_ui_section")) for r in links]
    elements = (
        _read(
            config,
            auth_manager,
            "sys_ui_element",
            "sys_ui_sectionIN" + ",".join(section_ids),
            "sys_id,sys_ui_section,element,type,position",
            5000,
        )
        if section_ids
        else []
    )
    by_section: Dict[str, List[Dict[str, Any]]] = {}
    for e in elements:
        by_section.setdefault(_s(e.get("sys_ui_section")), []).append(e)
    sections = []
    for link in links:
        sid = _s(link.get("sys_ui_section"))
        rows = sorted(by_section.get(sid, []), key=lambda r: int(_s(r.get("position")) or 0))
        sections.append(
            {
                "sys_id": sid,
                "caption": _s(link.get("sys_ui_section.caption")) or _MAIN,
                "link_id": _s(link.get("sys_id")),
                "position": int(_s(link.get("position")) or 0),
                "elements": [
                    {
                        "sys_id": _s(r.get("sys_id")),
                        "element": _s(r.get("element")),
                        "type": _s(r.get("type")),
                        "position": int(_s(r.get("position")) or 0),
                    }
                    for r in rows
                ],
            }
        )
    return {"form_id": form_id, "view_id": view_id, "sections": sections}


def _shape(layout: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Readable layout: caption + element names in order (split markers kept)."""
    return [
        {"section": s["caption"], "fields": [e["element"] for e in s["elements"]]}
        for s in layout["sections"]
    ]


def _find(layout: Dict[str, Any], caption: str) -> Tuple[Optional[Dict[str, Any]], str]:
    want = caption.strip().lower()
    hits = [s for s in layout["sections"] if s["caption"].lower() == want]
    if len(hits) > 1:
        return None, f"{len(hits)} sections are captioned {caption!r}; resolve that in the UI"
    return (hits[0], "") if hits else (None, "")


def _on_form(layout: Dict[str, Any]) -> Dict[str, str]:
    """field -> caption of the section already showing it."""
    return {
        e["element"]: s["caption"]
        for s in layout["sections"]
        for e in s["elements"]
        if not e["element"].startswith(".") and not e["type"]
    }


def _unknown_fields(config, auth_manager, table: str, fields: List[str]) -> List[str]:
    ancestry = table_ancestry(config, auth_manager, table)
    if not ancestry:
        raise LookupError(f"table {table!r} was not resolved")
    rows = _read(
        config,
        auth_manager,
        "sys_dictionary",
        "nameIN" + ",".join(ancestry) + "^elementIN" + ",".join(fields),
        "element",
    )
    known = {_s(r.get("element")) for r in rows}
    return [f for f in fields if f not in known]


def _capture_names(layout: Dict[str, Any], section_ids: List[str], form_order: bool):
    names = [f"sys_ui_section_{i}" for i in section_ids]
    return names + ([f"sys_ui_form_sections_{layout['form_id']}"] if form_order else [])


def _capture_rows(config, auth_manager, names: List[str]) -> Dict[str, List[Dict[str, str]]]:
    """name -> its sys_update_xml entries, in any update set. Raises."""
    found: Dict[str, List[Dict[str, str]]] = {n: [] for n in names}
    if not names:
        return found
    _fresh()
    for r in _read(
        config,
        auth_manager,
        "sys_update_xml",
        "nameIN" + ",".join(names),
        "sys_id,name,sys_updated_on,update_set.name,update_set.state",
    ):
        found.setdefault(_s(r.get("name")), []).append(
            {
                "key": f"{_s(r.get('sys_id'))}@{_s(r.get('sys_updated_on'))}",
                "label": f"{_s(r.get('update_set.name'))} ({_s(r.get('update_set.state'))}, "
                f"{_s(r.get('sys_updated_on'))})",
            }
        )
    return found


def _snapshot(config, auth_manager, names: List[str]) -> Optional[Dict[str, set]]:
    """Capture entries before a write; None when unreadable (then capture is undetermined)."""
    try:
        return {
            n: {e["key"] for e in es}
            for n, es in _capture_rows(config, auth_manager, names).items()
        }
    except Exception:
        return None


def _captures(config, auth_manager, names: List[str]) -> Dict[str, Any]:
    """Which update sets hold these layout records (read-only report)."""
    try:
        found = _capture_rows(config, auth_manager, names)
    except Exception as e:
        return {"checked": False, "error": str(e)}
    return {"checked": True, "entries": {n: sorted(e["label"] for e in found[n]) for n in names}}


def _settle_capture(
    config, auth_manager, names: List[str], before: Optional[Dict[str, set]], out, where: str
) -> Dict[str, Any]:
    """A layout write is done only when the update set holds it. Proven by a NEW entry per
    name since the pre-write snapshot — an old entry is an older copy of the layout."""
    found: Optional[Dict[str, List[Dict[str, str]]]] = None
    try:
        found = _capture_rows(config, auth_manager, names)
    except Exception as e:
        out["update_set_capture"] = {"checked": False, "error": str(e)}
    else:
        out["update_set_capture"] = {
            "checked": True,
            "entries": {n: sorted(e["label"] for e in found[n]) for n in names},
        }
    if found is None or before is None:
        out["captured"] = "undetermined"
        missing = names
        why = "the update set could not be read before and after the write"
    else:
        missing = [
            n for n in names if not any(e["key"] not in before.get(n, set()) for e in found[n])
        ]
        out["captured"] = not missing
        why = "no new update-set entry appeared"
    if out["captured"] is True:
        return out
    out["success"] = False
    out["not_captured"] = missing
    note = (
        f"Applied on this instance only; NOT shown to be in an update set ({why}): {missing}. "
        "This platform records layout tables (update_synch_custom) only when its own code saves "
        f"them, which a Table API write does not. To ship it: open {where} in the UI and Save, "
        "then call get; update_set_capture must name your update set with a newer time."
    )
    out["message"] = f"{out['message']} {note}" if out.get("message") else note
    return out


def _approval(p: ManageFormLayoutParams) -> str:
    if p.action == "copy_from":
        return f"{p.table}:{p.source_table}"
    return f"{p.table}:{(p.section or '').strip()}"


def _gate(p: ManageFormLayoutParams, preview: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Preview unless the exact section is named. None means: go ahead and write."""
    want = _approval(p)
    if (p.confirm_layout or "").strip().lower() == want.lower():
        return None
    wrong = f" ({p.confirm_layout!r} does not name it)" if p.confirm_layout else ""
    return {
        "success": False,
        "approval_required": True,
        "message": f"Nothing written{wrong}. Review the before/after, then re-send the same call "
        f"with confirm_layout={want!r}.",
        "note": "A layout change is captured as the WHOLE section (Form Layout) and the tab "
        "order; importing it replaces the target's section/order with this instance's.",
        **preview,
    }


def _verify(
    config,
    auth_manager,
    p,
    expect: List[Dict[str, Any]],
    touched: List[str],
    out,
    before_capture: Optional[Dict[str, set]],
    form_order: bool = False,
    gone_ids: Tuple[str, ...] = (),
):
    """Re-read the form; success only when it is exactly the layout the preview promised
    AND the update set holds every record the change rewrote."""
    try:
        after = _layout(config, auth_manager, p.table, p.view)
    except Exception as e:
        out.update(success=False, verified=False, message=f"Re-read failed ({e}); UNVERIFIED.")
        return out
    actual = _shape(after)
    out["layout"] = actual
    if actual != expect:
        mismatch = (
            "The form does not match the layout this call meant to produce; see expected vs "
            "layout. Nothing further was changed."
        )
        out["message"] = f"{out['message']} {mismatch}" if out.get("message") else mismatch
        out["success"] = False
        out["expected"] = expect
    live = {s["caption"].lower(): s["sys_id"] for s in after["sections"]}
    ids = [live[c.lower()] for c in touched if c.lower() in live] + list(gone_ids)
    names = _capture_names(after, ids, form_order)
    return _settle_capture(
        config,
        auth_manager,
        names,
        before_capture,
        out,
        f"Configure > Form Layout for {p.table} ({p.view})",
    )


def _rows_for(fields: List[str], columns: int) -> List[Tuple[str, str]]:
    """(element, type) rows for a new section, mirroring the platform's 2-column shape."""
    if columns == 1:
        return [(f, "") for f in fields]
    left = (len(fields) + 1) // 2
    return (
        [(_BEGIN_SPLIT, _BEGIN_SPLIT)]
        + [(f, "") for f in fields[:left]]
        + [(_SPLIT, _SPLIT)]
        + [(f, "") for f in fields[left:]]
        + [(_END_SPLIT, _END_SPLIT)]
    )


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


def _get(config, auth_manager, p: ManageFormLayoutParams) -> Dict[str, Any]:
    try:
        layout = _layout(config, auth_manager, p.table, p.view)
    except Exception as e:
        return _fail(f"Could not read the {p.table} form ({p.view}): {e}", determined=False)
    return {
        "success": True,
        "table": p.table,
        "view": p.view,
        "layout": _shape(layout),
        "update_set_capture": _captures(
            config,
            auth_manager,
            _capture_names(layout, [s["sys_id"] for s in layout["sections"]], True),
        ),
    }


def _context(config, auth_manager, p: ManageFormLayoutParams, check_fields: bool):
    try:
        layout = _layout(config, auth_manager, p.table, p.view)
        unknown = (
            _unknown_fields(config, auth_manager, p.table, p.fields or []) if check_fields else []
        )
    except Exception as e:
        return None, _fail(f"Could not read the form or its fields: {e}. Nothing written.")
    if unknown:
        return None, _fail(
            f"Not columns of {p.table} or the tables it extends: {unknown}. Nothing written.",
            unknown=unknown,
        )
    return layout, None


def _create_section(
    config,
    auth_manager,
    table: str,
    layout: Dict[str, Any],
    caption: str,
    rows: List[Tuple[str, str]],
    tab: int,
    out: Dict[str, Any],
) -> None:
    """Section + its elements + its tab at index *tab*. Raises; *out['done']* says how far."""
    sid = _call(
        config,
        auth_manager,
        "POST",
        "sys_ui_section",
        data={
            "name": table,
            "view": layout["view_id"],
            "caption": caption,
            "title": "false",
            "header": "false",
        },
    )
    out["done"].append(f"section {caption!r}")
    for i, (element, etype) in enumerate(rows):
        _call(
            config,
            auth_manager,
            "POST",
            "sys_ui_element",
            data={"sys_ui_section": sid, "element": element, "type": etype, "position": i},
        )
    out["done"].append(f"{len(rows)} elements in {caption!r}")
    later = layout["sections"][tab:]
    if later:
        new_pos = later[0]["position"]
    else:
        new_pos = layout["sections"][-1]["position"] + 1 if layout["sections"] else 0
    # Tabs after the new one move right by one, last first.
    for s in reversed(later):
        _call(
            config,
            auth_manager,
            "PATCH",
            "sys_ui_form_section",
            s["link_id"],
            {"position": s["position"] + 1},
        )
        s["position"] += 1
    _fresh()
    # The platform may link a new section to the form itself: never link twice, and put
    # the link it made where the preview said the tab goes.
    linked = _read(
        config, auth_manager, "sys_ui_form_section", f"sys_ui_section={sid}", "sys_id,position", 5
    )
    if linked:
        link_id = _s(linked[0].get("sys_id"))
        if _s(linked[0].get("position")) != str(new_pos):
            _call(
                config, auth_manager, "PATCH", "sys_ui_form_section", link_id, {"position": new_pos}
            )
    else:
        link_id = _call(
            config,
            auth_manager,
            "POST",
            "sys_ui_form_section",
            data={"sys_ui_form": layout["form_id"], "sys_ui_section": sid, "position": new_pos},
        )
    out["done"].append(f"tab {caption!r}")
    layout["sections"].insert(
        tab,
        {
            "sys_id": sid,
            "caption": caption,
            "link_id": link_id,
            "position": new_pos,
            "elements": [],
        },
    )


def _add_section(config, auth_manager, p: ManageFormLayoutParams) -> Dict[str, Any]:
    layout, refusal = _context(config, auth_manager, p, check_fields=True)
    if refusal:
        return refusal
    caption = (p.section or "").strip()
    existing, problem = _find(layout, caption)
    if problem or existing:
        return _fail(problem or f"A section {caption!r} is already on this form. Nothing written.")
    shown = _on_form(layout)
    dup = {f: shown[f] for f in p.fields or [] if f in shown}
    if dup:
        return _fail(
            f"Already on this form (a field shows once per form): {dup}. Nothing written.",
            already_on_form=dup,
        )
    before = _shape(layout)
    tab = len(before) if p.position is None else max(0, min(p.position, len(before)))
    rows = _rows_for(list(p.fields or []), p.columns)
    expect = before[:tab] + [{"section": caption, "fields": [e for e, _ in rows]}] + before[tab:]
    gate = _gate(p, {"before": before, "after": expect})
    if gate:
        return gate

    snap = _snapshot(config, auth_manager, _capture_names(layout, [], True))
    out: Dict[str, Any] = {"success": True, "done": []}
    try:
        _create_section(config, auth_manager, p.table, layout, caption, rows, tab, out)
    except Exception as e:
        out.update(success=False, message=f"Stopped part-way ({e}); see done and layout.")
    return _verify(config, auth_manager, p, expect, [caption], out, snap, form_order=True)


def _add_fields(config, auth_manager, p: ManageFormLayoutParams) -> Dict[str, Any]:
    layout, refusal = _context(config, auth_manager, p, check_fields=True)
    if refusal:
        return refusal
    section, problem = _find(layout, p.section or "")
    if problem or not section:
        return _fail(problem or f"No section {p.section!r} on this form. Nothing written.")
    shown = _on_form(layout)
    dup = {f: shown[f] for f in p.fields or [] if f in shown}
    if dup:
        return _fail(
            f"Already on this form (a field shows once per form): {dup}. Nothing written.",
            already_on_form=dup,
        )
    names = [e["element"] for e in section["elements"]]
    if p.after is not None and p.after not in names:
        return _fail(f"{p.after!r} is not in section {section['caption']!r}. Nothing written.")
    at = names.index(p.after) + 1 if p.after is not None else len(names)
    new_names = names[:at] + list(p.fields or []) + names[at:]
    before = _shape(layout)
    expect = [
        {
            "section": s["section"],
            "fields": new_names if s["section"] == section["caption"] else s["fields"],
        }
        for s in before
    ]
    gate = _gate(p, {"before": before, "after": expect})
    if gate:
        return gate

    snap = _snapshot(config, auth_manager, _capture_names(layout, [section["sys_id"]], False))
    out: Dict[str, Any] = {"success": True, "done": []}
    try:
        shift = len(p.fields or [])
        # Make room from the end backwards so no two rows ever share a position.
        for e in reversed(section["elements"][at:]):
            _call(
                config,
                auth_manager,
                "PATCH",
                "sys_ui_element",
                e["sys_id"],
                {"position": e["position"] + shift},
            )
        base = section["elements"][at - 1]["position"] + 1 if at else 0
        for i, f in enumerate(p.fields or []):
            _call(
                config,
                auth_manager,
                "POST",
                "sys_ui_element",
                data={
                    "sys_ui_section": section["sys_id"],
                    "element": f,
                    "type": "",
                    "position": base + i,
                },
            )
            out["done"].append(f)
    except Exception as e:
        out.update(success=False, message=f"Stopped part-way ({e}); see done and layout.")
    return _verify(config, auth_manager, p, expect, [section["caption"]], out, snap)


def _remove_fields(config, auth_manager, p: ManageFormLayoutParams) -> Dict[str, Any]:
    layout, refusal = _context(config, auth_manager, p, check_fields=False)
    if refusal:
        return refusal
    section, problem = _find(layout, p.section or "")
    if problem or not section:
        return _fail(problem or f"No section {p.section!r} on this form. Nothing written.")
    present = {e["element"]: e for e in section["elements"]}
    missing = [f for f in p.fields or [] if f not in present]
    if missing:
        return _fail(
            f"Not in section {section['caption']!r}: {missing}. Nothing written.",
            missing=missing,
        )
    before = _shape(layout)
    drop = set(p.fields or [])
    expect = [
        {
            "section": s["section"],
            "fields": (
                [f for f in s["fields"] if f not in drop]
                if s["section"] == section["caption"]
                else s["fields"]
            ),
        }
        for s in before
    ]
    gate = _gate(
        p,
        {
            "before": before,
            "after": expect,
            "data_note": "Only the form placement goes; the columns and their values stay.",
        },
    )
    if gate:
        return gate
    snap = _snapshot(config, auth_manager, _capture_names(layout, [section["sys_id"]], False))
    out: Dict[str, Any] = {"success": True, "done": []}
    try:
        for f in p.fields or []:
            _call(config, auth_manager, "DELETE", "sys_ui_element", present[f]["sys_id"])
            out["done"].append(f)
    except Exception as e:
        out.update(success=False, message=f"Stopped part-way ({e}); see done and layout.")
    return _verify(config, auth_manager, p, expect, [section["caption"]], out, snap)


def _remove_section(config, auth_manager, p: ManageFormLayoutParams) -> Dict[str, Any]:
    layout, refusal = _context(config, auth_manager, p, check_fields=False)
    if refusal:
        return refusal
    section, problem = _find(layout, p.section or "")
    if problem or not section:
        return _fail(problem or f"No section {p.section!r} on this form. Nothing written.")
    try:
        shared = _read(
            config,
            auth_manager,
            "sys_ui_form_section",
            f"sys_ui_section={section['sys_id']}^sys_ui_form!={layout['form_id']}",
            "sys_id",
            5,
        )
    except Exception as e:
        return _fail(f"Could not check where else the section is used: {e}. Nothing written.")
    if shared:
        return _fail(
            f"Section {section['caption']!r} is also on {len(shared)} other form(s); removing "
            "it would change those too. Remove it in the UI. Nothing written."
        )
    before = _shape(layout)
    expect = [s for s in before if s["section"] != section["caption"]]
    gate = _gate(
        p,
        {
            "before": before,
            "after": expect,
            "removes": [e["element"] for e in section["elements"]],
            "data_note": "Only the tab and its placements go; the columns and their values stay.",
        },
    )
    if gate:
        return gate
    snap = _snapshot(config, auth_manager, _capture_names(layout, [section["sys_id"]], True))
    out: Dict[str, Any] = {"success": True, "done": []}
    try:
        for el in section["elements"]:
            _call(config, auth_manager, "DELETE", "sys_ui_element", el["sys_id"])
        out["done"].append(f"{len(section['elements'])} elements")
        _call(config, auth_manager, "DELETE", "sys_ui_form_section", section["link_id"])
        out["done"].append("tab link")
        _call(config, auth_manager, "DELETE", "sys_ui_section", section["sys_id"])
        out["done"].append("section")
    except Exception as e:
        out.update(success=False, message=f"Stopped part-way ({e}); see done and layout.")
    return _verify(
        config,
        auth_manager,
        p,
        expect,
        [],
        out,
        snap,
        form_order=True,
        gone_ids=(section["sys_id"],),
    )


def _copy_from(config, auth_manager, p: ManageFormLayoutParams) -> Dict[str, Any]:
    """Recreate the source form's sections on this form: same captions, order, columns."""
    try:
        target = _layout(config, auth_manager, p.table, p.view)
        source = _layout(config, auth_manager, p.source_table or "", p.view)
    except Exception as e:
        return _fail(f"Could not read the forms: {e}. Nothing written.")
    candidates = [s for s in source["sections"] if s["caption"] != _MAIN]
    if p.sections:
        wanted = {c.strip().lower() for c in p.sections}
        unknown = sorted(wanted - {s["caption"].lower() for s in candidates})
        if unknown:
            return _fail(
                f"Not sections of the {p.source_table} form (main is never copied): {unknown}. "
                "Nothing written.",
                source_sections=[s["caption"] for s in candidates],
            )
        candidates = [s for s in candidates if s["caption"].lower() in wanted]
    excluded = set(p.exclude or [])
    have = {s["caption"].lower() for s in target["sections"]}
    plan: List[Tuple[str, List[Tuple[str, str]]]] = []
    skipped_existing, not_copied = [], []
    for s in candidates:
        if s["caption"].lower() in have:
            skipped_existing.append(s["caption"])
            continue
        rows = []
        for el in s["elements"]:
            if el["element"] in _MARKERS:
                rows.append((el["element"], el["type"]))
            elif el["type"]:
                not_copied.append(f"{s['caption']}: {el['element']} ({el['type']})")
            elif el["element"] not in excluded:
                rows.append((el["element"], ""))
        if any(not el.startswith(".") for el, _ in rows):
            plan.append((s["caption"], rows))
    if not plan:
        return _fail(
            "Nothing to copy: every chosen section is already on this form or has no fields "
            "left after exclude.",
            skipped_existing=skipped_existing,
        )
    fields = [el for _, rows in plan for el, t in rows if not t]
    try:
        unknown = _unknown_fields(config, auth_manager, p.table, sorted(set(fields)))
    except Exception as e:
        return _fail(f"Could not check the fields on {p.table}: {e}. Nothing written.")
    shown = _on_form(target)
    on_form = {f: shown[f] for f in fields if f in shown}
    if unknown or on_form:
        return _fail(
            "The copy cannot be made as is. Create the missing columns first, or leave fields "
            "out with exclude=[...]. Nothing written.",
            not_columns_of_target=unknown,
            already_on_target_form=on_form,
        )
    before = _shape(target)
    expect = before + [{"section": c, "fields": [el for el, _ in rows]} for c, rows in plan]
    preview: Dict[str, Any] = {"before": before, "after": expect}
    if skipped_existing:
        preview["skipped_existing"] = skipped_existing
    if not_copied:
        preview["not_copied"] = not_copied
    gate = _gate(p, preview)
    if gate:
        return gate
    snap = _snapshot(config, auth_manager, _capture_names(target, [], True))
    out: Dict[str, Any] = {
        "success": True,
        "done": [],
        **{k: v for k, v in preview.items() if k not in ("before", "after")},
    }
    try:
        for caption, rows in plan:
            _create_section(
                config, auth_manager, p.table, target, caption, rows, len(target["sections"]), out
            )
    except Exception as e:
        out.update(success=False, message=f"Stopped part-way ({e}); see done and layout.")
    return _verify(
        config, auth_manager, p, expect, [c for c, _ in plan], out, snap, form_order=True
    )


@register_tool(
    "manage_form_layout",
    params=ManageFormLayoutParams,
    description="Form layout (sections/fields of a table's form view): get, add_section, add_fields, remove_fields, remove_section, copy_from another table's form. Previews first.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_form_layout(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageFormLayoutParams,
) -> Dict[str, Any]:
    return {
        "get": _get,
        "add_section": _add_section,
        "add_fields": _add_fields,
        "remove_fields": _remove_fields,
        "remove_section": _remove_section,
        "copy_from": _copy_from,
    }[params.action](config, auth_manager, params)
