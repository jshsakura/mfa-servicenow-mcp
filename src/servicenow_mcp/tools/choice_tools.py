"""manage_choice — the option list of a choice field (sys_choice), never deleted.

A choice list is keyed by (name=table, element=field, language). Lists inherit:
``incident.priority`` is stored under ``task``, while ``incident.state`` has its
own rows under ``incident`` that shadow ``task``'s. The nearest table in the
ancestry that holds rows for the field owns the list, so ``list`` says which
table the rows came from and ``set`` writes there — and only after the caller
names that table when it is not the one asked about, because adding one row to
a child table silently replaces the parent's whole list for that child.
"""

import logging
import re
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services.choices import resolve_choice
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.encoded_query import safe_value
from servicenow_mcp.utils.query_fields import table_ancestry
from servicenow_mcp.utils.registry import register_tool

from .sn_api import invalidate_query_cache, sn_query_page

logger = logging.getLogger(__name__)

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_LANG = re.compile(r"^[a-z]{2}(_[A-Z]{2})?$")
_CHOICE_FIELDS = "sys_id,name,element,value,label,sequence,dependent_value,inactive,language"
_ROW_LIMIT = 1000

# sys_dictionary.choice: 0 none, 1 dropdown w/o none, 2 dropdown with none, 3 suggestion
_CHOICE_TYPES = {"1", "2", "3"}


class ManageChoiceParams(BaseModel):
    """Choice lists (sys_choice)."""

    action: Literal["list", "set", "deactivate"] = Field(..., description="Operation")
    table: str = Field(..., description="Table the field is asked about, e.g. incident")
    field: str = Field(..., description="Choice field, e.g. category")
    language: str = Field(default="en", description="Language code")
    include_inactive: bool = Field(default=False, description="list: also show inactive options")

    value: Optional[str] = Field(default=None, description="Stored value of the option")
    label: Optional[str] = Field(default=None, description="set: label shown to users")
    sequence: Optional[int] = Field(default=None, description="set: display order")
    dependent_value: Optional[str] = Field(
        default=None, description="set: parent field's value this option belongs to"
    )
    inactive: bool = Field(default=True, description="deactivate: false re-activates")
    confirm_inherited: Optional[str] = Field(
        default=None,
        description="Table that holds the list when it is not `table`; naming it approves the write",
    )

    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset({"table", "field", "language", "include_inactive"}),
        "set": frozenset(
            {
                "table",
                "field",
                "language",
                "value",
                "label",
                "sequence",
                "dependent_value",
                "confirm_inherited",
                "dry_run",
            }
        ),
        "deactivate": frozenset(
            {"table", "field", "language", "value", "inactive", "confirm_inherited", "dry_run"}
        ),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageChoiceParams":
        if not _NAME.match(self.table) or not _NAME.match(self.field):
            raise ValueError("table and field must be lowercase column/table names")
        if not _LANG.match(self.language):
            raise ValueError("language must look like 'en' or 'pt_BR'")
        if self.action in ("set", "deactivate") and not (self.value or "").strip():
            raise ValueError(f"value is required for action='{self.action}'")
        if self.action == "set" and all(
            x is None for x in (self.label, self.sequence, self.dependent_value)
        ):
            raise ValueError("set needs a label, sequence or dependent_value")
        return self


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _raw(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def _fail(message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "message": message, **extra}


def _read(config, auth_manager, table: str, query: str, fields: str, limit: int):
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


def _seq_key(row: Dict[str, Any]) -> Tuple[int, str]:
    try:
        return (int(str(row.get("sequence"))), str(row.get("value")))
    except ValueError:
        return (10**9, str(row.get("value")))


def _dictionary(
    config, auth_manager, ancestry: List[str], field: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Nearest sys_dictionary row for the field, walking the ancestry. (row, refusal)."""
    try:
        rows = _read(
            config,
            auth_manager,
            "sys_dictionary",
            "nameIN" + ",".join(ancestry) + f"^element={field}",
            "name,element,internal_type,choice,dependent,active",
            50,
        )
    except Exception as e:
        return None, _fail(f"Could not read sys_dictionary for {field}: {e}. Nothing was written.")
    for name in ancestry:
        for r in rows:
            if str(_raw(r.get("name"))) == name:
                return r, None
    return None, _fail(
        f"Field {field!r} was not returned for {ancestry[0]} or the tables it extends "
        "(sys_dictionary): it does not exist, or is hidden from this account. "
        "Nothing was written.",
        determined=False,
    )


def _choice_rows(
    config, auth_manager, ancestry: List[str], field: str, language: str
) -> Tuple[Optional[str], List[Dict[str, Any]], bool]:
    """(owner table, its rows incl. inactive, truncated). Nearest table with any row owns the list."""
    rows = _read(
        config,
        auth_manager,
        "sys_choice",
        "nameIN" + ",".join(ancestry) + f"^element={field}^language={safe_value(language).value}",
        _CHOICE_FIELDS,
        _ROW_LIMIT,
    )
    for name in ancestry:
        own = [r for r in rows if str(_raw(r.get("name"))) == name]
        if own:
            return name, own, len(rows) >= _ROW_LIMIT
    return None, [], len(rows) >= _ROW_LIMIT


def _shape(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "value": _raw(row.get("value")),
        "label": _raw(row.get("label")),
        "sequence": _raw(row.get("sequence")),
        "inactive": str(_raw(row.get("inactive"))).lower() == "true",
    }
    dep = _raw(row.get("dependent_value"))
    if dep:
        out["dependent_value"] = dep
    return out


def _context(
    config, auth_manager, params: ManageChoiceParams
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Verify table + field and read the list. (context, refusal)."""
    try:
        ancestry = table_ancestry(config, auth_manager, params.table)
    except Exception as e:
        return None, _fail(f"Could not read the hierarchy of {params.table}: {e}.")
    if not ancestry:
        return None, _fail(
            f"Table {params.table!r} was not resolved (sys_db_object): absent, hidden from this "
            "account, or the read failed. Nothing was written.",
            determined=False,
        )
    dic, refusal = _dictionary(config, auth_manager, ancestry, params.field)
    if refusal:
        return None, refusal
    assert dic
    try:
        owner, rows, truncated = _choice_rows(
            config, auth_manager, ancestry, params.field, params.language
        )
    except Exception as e:
        return None, _fail(f"Could not read sys_choice for {params.table}.{params.field}: {e}.")
    return {
        "ancestry": ancestry,
        "dictionary": dic,
        "owner": owner,
        "rows": rows,
        "truncated": truncated,
        "choice_type": str(_raw(dic.get("choice")) or "0"),
        "parent_field": str(_raw(dic.get("dependent")) or ""),
        "dictionary_table": str(_raw(dic.get("name"))),
    }, None


# ---------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------


def _list(config, auth_manager, params: ManageChoiceParams) -> Dict[str, Any]:
    ctx, refusal = _context(config, auth_manager, params)
    if refusal:
        return refusal
    assert ctx
    rows = sorted(ctx["rows"], key=_seq_key)
    shown = [_shape(r) for r in rows if params.include_inactive or _shape(r)["inactive"] is False]
    out: Dict[str, Any] = {
        "success": True,
        "table": params.table,
        "field": params.field,
        "language": params.language,
        "choice_type": ctx["choice_type"],
        "defined_on": ctx["dictionary_table"],
        "rows_from": ctx["owner"],
        "count": len(shown),
        "choices": shown,
    }
    if ctx["owner"] and ctx["owner"] != params.table:
        out["inherited"] = True
        out["note"] = (
            f"The list is stored under {ctx['owner']}, not {params.table}; set/deactivate edit "
            f"it there and need confirm_inherited={ctx['owner']}."
        )
    if ctx["parent_field"]:
        out["depends_on_field"] = ctx["parent_field"]
    if ctx["truncated"]:
        out["truncated"] = True
        out["note"] = f"Read hit the {_ROW_LIMIT}-row cap; the list may be incomplete."
    if ctx["choice_type"] not in _CHOICE_TYPES:
        out["warning"] = f"{params.field} is not a choice field (dictionary choice=0)."
    elif not ctx["owner"]:
        out["note"] = (
            f"No {params.language} rows were returned for {params.table}.{params.field}: the "
            "list is empty, or those rows are not readable by this account (the two look the same)."
        )
    return out


def _target(
    config, auth_manager, params: ManageChoiceParams, creating: bool
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Context plus the table to write under and the matching row. (ctx, refusal)."""
    ctx, refusal = _context(config, auth_manager, params)
    if refusal:
        return None, refusal
    assert ctx
    if ctx["choice_type"] not in _CHOICE_TYPES:
        return None, _fail(
            f"{params.table}.{params.field} is not a choice field (dictionary choice=0, type "
            f"{_raw(ctx['dictionary'].get('internal_type'))}); changing its dictionary is a human "
            "decision. Nothing was written."
        )
    owner = ctx["owner"] or params.table
    if ctx["owner"] and owner != params.table and params.confirm_inherited != owner:
        return None, _fail(
            f"The list for {params.table}.{params.field} is stored under {owner}; a change there "
            f"applies to every table that extends it. Re-send with confirm_inherited={owner!r} "
            "to approve. Nothing was written.",
            rows_from=owner,
        )
    ctx["write_table"] = owner
    wanted = str(params.value).strip()
    matches = [r for r in ctx["rows"] if str(_raw(r.get("value"))) == wanted]
    if len(matches) > 1:
        return None, _fail(
            f"{len(matches)} sys_choice rows hold value {wanted!r} under {owner}.{params.field}; "
            "resolve the duplicate by hand. Nothing was written.",
            candidates=[str(_raw(r.get("sys_id"))) for r in matches],
        )
    ctx["match"] = matches[0] if matches else None
    return ctx, None


def _check_dependent(
    config, auth_manager, params: ManageChoiceParams, ctx: Dict[str, Any], creating: bool
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    parent = ctx["parent_field"]
    given = params.dependent_value
    if not parent:
        if given:
            return None, _fail(
                f"{params.field} has no dependent field, so dependent_value does not apply. "
                "Nothing was written."
            )
        return None, None
    if given is None:
        if creating:
            return None, _fail(
                f"{params.field} depends on {parent}: a new option needs dependent_value (a "
                f"{parent} value). Nothing was written."
            )
        return None, None
    resolved, refusal = resolve_choice(
        config,
        auth_manager,
        table=params.table,
        element=parent,
        requested=given,
    )
    if refusal:
        refusal["field"] = "dependent_value"
        return None, refusal
    return resolved, None


def _write(
    config, auth_manager, method: str, table: str, sys_id: Optional[str], data: Dict[str, Any]
) -> Optional[str]:
    url = f"{config.api_url}/table/sys_choice" + (f"/{sys_id}" if sys_id else "")
    try:
        resp = auth_manager.make_request(
            method, url, json=data, headers=auth_manager.get_headers(), timeout=config.timeout
        )
        resp.raise_for_status()
        invalidate_query_cache(table="sys_choice")
        if not sys_id:
            return str(_raw(resp.json().get("result", {}).get("sys_id")) or "")
        return sys_id
    except Exception as e:
        logger.error(f"Failed to write sys_choice: {e}")
        raise


def _verify(config, auth_manager, sys_id: str, data: Dict[str, Any], what: str) -> Dict[str, Any]:
    try:
        rows = _read(config, auth_manager, "sys_choice", f"sys_id={sys_id}", _CHOICE_FIELDS, 1)
    except Exception as e:
        return {
            "success": True,
            "sys_id": sys_id,
            "verified": False,
            "applied": None,
            "message": f"Write sent but the re-read failed ({e}); the result is UNVERIFIED.",
        }
    if not rows:
        return {
            "success": True,
            "sys_id": sys_id,
            "verified": False,
            "applied": None,
            "message": "Write sent but the row was not returned on re-read; UNVERIFIED.",
        }
    row = rows[0]
    not_applied = {
        f: {"requested": v, "actual": _raw(row.get(f))}
        for f, v in data.items()
        if str(v).lower() != str(_raw(row.get(f)) if _raw(row.get(f)) is not None else "").lower()
    }
    out: Dict[str, Any] = {
        "success": not not_applied,
        "sys_id": sys_id,
        "verified": True,
        "applied": not not_applied,
        "choice": _shape(row),
    }
    if not_applied:
        out["not_applied"] = not_applied
        out["message"] = "The write was accepted but these fields do not hold the requested value."
    else:
        out["message"] = f"Choice {what} and confirmed by re-read."
    return out


def _set(config, auth_manager, params: ManageChoiceParams) -> Dict[str, Any]:
    ctx, refusal = _target(config, auth_manager, params, creating=True)
    if refusal:
        return refusal
    assert ctx
    match = ctx["match"]
    creating = match is None
    if creating and not (params.label or "").strip():
        return _fail("A new option needs a label. Nothing was written.")
    try:
        dep, refusal = _check_dependent(config, auth_manager, params, ctx, creating)
    except Exception as e:
        return _fail(f"Could not check dependent_value: {e}. Nothing was written.")
    if refusal:
        return refusal
    data: Dict[str, Any] = {}
    if params.label is not None:
        data["label"] = params.label.strip()
    if params.sequence is not None:
        data["sequence"] = str(params.sequence)
    if dep is not None:
        data["dependent_value"] = dep
    if creating:
        data.update(
            name=ctx["write_table"],
            element=params.field,
            value=str(params.value).strip(),
            language=params.language,
            inactive="false",
        )
        if ctx["owner"] is None and ctx["write_table"] == params.table:
            ctx["created_list"] = True
    if params.dry_run:
        out: Dict[str, Any] = {
            "success": True,
            "dry_run": True,
            "operation": "create" if creating else "update",
            "write_table": ctx["write_table"],
            "would_write": data,
        }
        if not creating:
            out["current"] = _shape(match)
        if ctx.get("created_list"):
            out["note"] = "No list exists yet for this field; this creates its first option."
        return out
    try:
        if creating:
            sys_id = _write(config, auth_manager, "POST", "sys_choice", None, data)
        else:
            sys_id = _write(
                config, auth_manager, "PATCH", "sys_choice", str(_raw(match.get("sys_id"))), data
            )
    except Exception as e:
        return _fail(f"Failed to write the choice: {e}")
    if not sys_id:
        return _fail("The create was accepted but returned no sys_id; UNVERIFIED.", applied=None)
    out = _verify(config, auth_manager, sys_id, data, "created" if creating else "updated")
    out["rows_from"] = ctx["write_table"]
    if ctx.get("created_list"):
        out["note"] = "No list existed for this field; its first option was created."
    return out


def _deactivate(config, auth_manager, params: ManageChoiceParams) -> Dict[str, Any]:
    ctx, refusal = _target(config, auth_manager, params, creating=False)
    if refusal:
        return refusal
    assert ctx
    match = ctx["match"]
    if match is None:
        return _fail(
            f"Value {params.value!r} is not in the {params.language} list of "
            f"{ctx['write_table']}.{params.field}: absent, or hidden from this account by ACL. "
            "Nothing was written.",
            determined=False,
        )
    flag = "true" if params.inactive else "false"
    data = {"inactive": flag}
    if str(_raw(match.get("inactive"))).lower() == flag:
        return {
            "success": True,
            "applied": True,
            "no_op": True,
            "choice": _shape(match),
            "message": f"Already inactive={flag}; nothing written.",
        }
    if params.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "operation": "update",
            "write_table": ctx["write_table"],
            "current": _shape(match),
            "would_write": data,
        }
    try:
        _write(config, auth_manager, "PATCH", "sys_choice", str(_raw(match.get("sys_id"))), data)
    except Exception as e:
        return _fail(f"Failed to write the choice: {e}")
    out = _verify(
        config,
        auth_manager,
        str(_raw(match.get("sys_id"))),
        data,
        "deactivated" if params.inactive else "re-activated",
    )
    out["rows_from"] = ctx["write_table"]
    return out


@register_tool(
    "manage_choice",
    params=ManageChoiceParams,
    description="Choice-field options (sys_choice): list with inheritance shown, set/relabel a value, deactivate. Never deletes.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_choice(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageChoiceParams,
) -> Dict[str, Any]:
    if params.action == "list":
        return _list(config, auth_manager, params)
    if params.action == "set":
        return _set(config, auth_manager, params)
    return _deactivate(config, auth_manager, params)
