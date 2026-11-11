"""Bulk data updates with a preview the tool itself guarantees, and a way back.

Why this exists
---------------
Real sessions wrote Background Scripts for data fixes again and again, each
guarded by a ``DRY_RUN = true`` flag. That flag is the script's own claim: a
branch that forgot the ``if``, a Script Include that writes, an event that
fires a notification — nothing outside the script can prove it wrote nothing.
Here the preview path issues GET requests only, so "dry run" is a property of
this code, not of a promise.

The gates, all of which run on preview AND again on apply
----------------------------------------------------------
1. **Table.** Never ``sys_*``, never a table on ``SN_WRITE_DENY_TABLES``, never
   a table extending ``sys_metadata`` (configuration — that has its own tools
   and travels in update sets). An ancestry that cannot be read refuses.
2. **Condition.** Required, and every condition in it must name a column this
   table really has. ServiceNow DROPS a condition on an unknown column and runs
   the rest — an update scoped by a typo is an update of the whole table. A
   condition the parser cannot read is refused, not skipped.
3. **Whole table.** If the condition matches every row of the table, that is
   either a dropped condition or a real whole-table change; either way it takes
   ``confirm_whole_table=<table>``. Counts that cannot be read refuse.
4. **Cap.** ``max_rows`` (default 100, hard limit 1000). Over it: refused with
   the count, never truncated to the first N.
5. **Values.** Every field must exist; ``sys_*`` fields are refused; a choice
   takes a known value or label; a reference must point at a real record.
6. **Exactly what was reviewed.** The preview returns a token over every row,
   its current values and its new values. Apply recomputes the plan and runs
   only if the token AND ``confirm_count`` both match — a row that changed, was
   added or disappeared since the preview stops it.
7. **A way back.** Before the first write, a snapshot of every row's current
   values is written to disk; if it cannot be written, nothing is written.
   Apply stops at the first failed row. ``preview_revert``/``revert`` restore
   from the snapshot, skipping (and naming) rows someone has changed since.

What it does NOT do: insert, delete, per-row computed logic, or suppressing
business rules (``setWorkflow(false)`` has no Table API equivalent — every row
fires the table's update rules and notifications, and the preview says how
many there are).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from servicenow_mcp.services.choices import resolve_choice
from servicenow_mcp.tools.sn_api import (
    SN_WRITE_DENY_TABLES,
    _is_auth_error,
    invalidate_query_cache,
    sn_query_page,
)
from servicenow_mcp.utils.atomic_io import atomic_write_text
from servicenow_mcp.utils.query_fields import (
    near_matches,
    query_field_names,
    table_ancestry,
    table_columns,
)
from servicenow_mcp.utils.state_dir import state_dir

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROWS = 100
HARD_MAX_ROWS = 1000
_PAGE = 200
_SAMPLE = 20
# What a caller SEES is bounded whatever the row count or value length: a value
# is clipped (with a hash, so two different long values never read as one), a
# row shows at most _VIEW_FIELDS fields, and the whole result is fitted to
# _VIEW_BUDGET bytes. The snapshot on disk keeps every full value.
_VALUE_CHARS = 80
_VIEW_FIELDS = 10
_DIST_KEYS = 10
_VIEW_BUDGET = 24_000
_SAMPLED = (
    "sample",
    "also_changed",
    "server_changed",
    "side_not_restored",
    "changed_since",
    "missing",
)
_DISTS = ("changes_by_field", "also_changed_by_field")
_SYS_ID = re.compile(r"^[0-9a-f]{32}$")
_ORDER_PREFIXES = ("ORDERBYDESC", "ORDERBY")
_DENY_PREFIXES = ("sys", "ecc_", "v_")
_COMBINATOR = re.compile(r"^(?:OR|NQ)(?=[a-z])")
_FULL_FIELD = re.compile(r"^([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)")
# sys_dictionary.choice: 1 = dropdown with -- None --, 3 = dropdown without.
# 2 is "suggestion" — free text with hints — so it is not checked.
_STRICT_CHOICE = ("1", "3")
# Columns that name a record (shown next to its sys_id in the preview), in order.
_LABEL_COLUMNS = ("number", "name", "short_description", "u_name")


def _refuse(error: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "error": error, "message": message + " Nothing was written.", **extra}


def _text(value: Any) -> str:
    """A value as the Table API stores it: booleans lowercase, None empty."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _raw(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("value")
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# Gate 1 — the table
# ---------------------------------------------------------------------------


def check_table(
    config: Any, auth_manager: Any, table: str
) -> Tuple[Optional[List[str]], Optional[Dict[str, Any]]]:
    """``(ancestry, None)`` when this table may be bulk-updated, else ``(None, refusal)``."""
    name = (table or "").strip()
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        return None, _refuse("BAD_TABLE", f"{table!r} is not a table name.")
    # "sys" not "sys_": sysapproval_approver (approving for someone else, which
    # manage_approval gates by name), syslog*, sysevent* are system records too.
    # ecc_* is the MID Server queue; v_* are views and cannot be written.
    if name.startswith(_DENY_PREFIXES) or name in SN_WRITE_DENY_TABLES:
        return None, _refuse(
            "TABLE_NOT_ALLOWED",
            f"{name} is a system table. Bulk data updates are for data tables; system "
            "records go through their own manage_* tool.",
        )
    ancestry = table_ancestry(config, auth_manager, name)
    if not ancestry:
        return None, _refuse(
            "TABLE_UNVERIFIED",
            f"Could not read the table hierarchy of {name}, so it cannot be checked.",
        )
    if "sys_metadata" in ancestry:
        return None, _refuse(
            "TABLE_NOT_ALLOWED",
            f"{name} extends sys_metadata: it is configuration (captured in update sets), "
            "not data. Use the matching manage_* tool.",
        )
    return ancestry, None


# ---------------------------------------------------------------------------
# Gate 2 — the condition
# ---------------------------------------------------------------------------


def check_condition(
    config: Any, auth_manager: Any, table: str, query: str
) -> Optional[Dict[str, Any]]:
    """Every condition must be readable and name a real column. None = passed."""
    q = (query or "").strip()
    if not q:
        return _refuse(
            "CONDITION_REQUIRED",
            "A condition is required. For a deliberate whole-table change, pass a condition "
            "that is true for every row (e.g. sys_idISNOTEMPTY) with confirm_whole_table.",
        )
    if "javascript:" in q.lower():
        return _refuse(
            "CONDITION_NOT_DETERMINISTIC",
            "The condition runs a script (javascript:), so the rows it selects can differ "
            "between the preview and the update. Use literal values.",
        )
    unreadable: List[str] = []
    dotted: List[str] = []
    for piece in q.split("^"):
        p = piece.strip()
        if not p or p == "EQ" or p.upper().startswith(_ORDER_PREFIXES):
            continue
        if not query_field_names(p):
            unreadable.append(p)
            continue
        m = _FULL_FIELD.match(_COMBINATOR.sub("", p, count=1))
        if m and "." in m.group(1) and m.group(1) not in dotted:
            dotted.append(m.group(1))
    if unreadable:
        return _refuse(
            "CONDITION_UNVERIFIABLE",
            "These conditions could not be read as field<operator>value, so it cannot be "
            "proven that the server applies them: " + ", ".join(repr(u) for u in unreadable) + ".",
        )
    columns = table_columns(config, auth_manager, table)
    if columns is None:
        return _refuse(
            "SCHEMA_UNVERIFIED", f"Could not read the columns of {table} to check the condition."
        )
    missing = [n for n in query_field_names(q) if n not in columns]
    if missing:
        return _refuse(
            "UNKNOWN_QUERY_FIELDS",
            f"{table} has no column " + ", ".join(repr(m) for m in missing) + ". ServiceNow "
            "would drop that condition and match far more rows than intended.",
            did_you_mean={m: near_matches(m, sorted(columns)) for m in missing},
        )
    for path in dotted:
        refusal = _check_dotwalk(config, auth_manager, table, path)
        if refusal:
            return refusal
    return None


def _check_dotwalk(
    config: Any, auth_manager: Any, table: str, path: str
) -> Optional[Dict[str, Any]]:
    """Every hop of ``a.b.c`` must be a reference, and the last name a real column.

    The root was checked with the rest of the condition; the far side is the
    trap — ``caller_id.nmae=x`` is dropped by the server just like an unknown
    root, leaving the remaining conditions to select the rows.
    """
    segments = path.split(".")
    current = table
    for i, segment in enumerate(segments[:-1]):
        ancestry = table_ancestry(config, auth_manager, current)
        if not ancestry:
            return _refuse(
                "SCHEMA_UNVERIFIED", f"Could not read the hierarchy of {current} to check {path}."
            )
        try:
            meta = _dictionary(config, auth_manager, ancestry, [segment]).get(segment)
        except Exception as e:  # noqa: BLE001
            if _is_auth_error(e):
                raise
            return _refuse(
                "SCHEMA_UNVERIFIED", f"Could not read sys_dictionary to check {path}: {e}."
            )
        if not meta:
            return _refuse(
                "UNKNOWN_QUERY_FIELDS",
                f"{current} has no column {segment!r} (in {path}); the server would drop the condition.",
            )
        if meta.get("internal_type") != "reference" or not meta.get("reference"):
            return _refuse(
                "CONDITION_UNVERIFIABLE",
                f"{'.'.join(segments[: i + 1])} is not a reference, so {path} cannot be walked.",
            )
        current = meta["reference"]
    columns = table_columns(config, auth_manager, current)
    if columns is None:
        return _refuse(
            "SCHEMA_UNVERIFIED", f"Could not read the columns of {current} to check {path}."
        )
    if segments[-1] not in columns:
        return _refuse(
            "UNKNOWN_QUERY_FIELDS",
            f"{current} has no column {segments[-1]!r} (in {path}); the server would drop that "
            "condition and match more rows than intended.",
            did_you_mean={segments[-1]: near_matches(segments[-1], sorted(columns))},
        )
    return None


# ---------------------------------------------------------------------------
# Gate 5 — the values
# ---------------------------------------------------------------------------


def _dictionary(
    config: Any, auth_manager: Any, ancestry: Sequence[str], fields: Sequence[str]
) -> Dict[str, Dict[str, str]]:
    """element → {internal_type, reference, choice}; the nearest declaring table wins."""
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_dictionary",
        query="nameIN" + ",".join(ancestry) + "^elementIN" + ",".join(fields),
        fields="name,element,internal_type,reference,choice",
        limit=500,
        offset=0,
        no_count=True,
        fail_silently=False,
    )
    rank = {t: i for i, t in enumerate(ancestry)}
    best: Dict[str, Tuple[int, Dict[str, str]]] = {}
    for r in rows:
        el, tbl = _raw(r.get("element")), _raw(r.get("name"))
        if not el or tbl not in rank:
            continue
        info = {
            "internal_type": _raw(r.get("internal_type")),
            "reference": _raw(r.get("reference")),
            "choice": _raw(r.get("choice")),
        }
        if el not in best or rank[tbl] < best[el][0]:
            best[el] = (rank[tbl], info)
    return {k: v for k, (_, v) in best.items()}


def check_values(
    config: Any,
    auth_manager: Any,
    table: str,
    ancestry: Sequence[str],
    targets: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Resolve choice labels to codes in place; refuse unknown fields/values/references."""
    fields = sorted({f for t in targets for f in t})
    if not fields:
        return _refuse("NOTHING_TO_SET", "No field values were given.")
    bad = [f for f in fields if f.startswith("sys_") or f == "sys_id"]
    if bad:
        return _refuse(
            "SYSTEM_FIELD", "System fields are not written here: " + ", ".join(bad) + "."
        )
    columns = table_columns(config, auth_manager, table)
    if columns is None:
        return _refuse("SCHEMA_UNVERIFIED", f"Could not read the columns of {table}.")
    missing = [f for f in fields if f not in columns]
    if missing:
        return _refuse(
            "UNKNOWN_COLUMN",
            f"{table} has no column " + ", ".join(missing) + "; the server would drop it "
            "silently and answer 200.",
            did_you_mean={m: near_matches(m, sorted(columns)) for m in missing},
        )
    try:
        meta = _dictionary(config, auth_manager, ancestry, fields)
    except Exception as e:  # noqa: BLE001
        if _is_auth_error(e):
            raise
        return _refuse("SCHEMA_UNVERIFIED", f"Could not read sys_dictionary for {table}: {e}.")

    for t in targets:
        for f, v in list(t.items()):
            t[f] = _text(v)
    for field in fields:
        info = meta.get(field) or {}
        values = sorted({t[field] for t in targets if t.get(field)})
        if info.get("choice") in _STRICT_CHOICE:
            resolved: Dict[str, str] = {}
            for v in values:
                code, refusal = resolve_choice(
                    config, auth_manager, table=table, element=field, requested=v
                )
                if refusal is not None:
                    return refusal
                resolved[v] = str(code)
            for t in targets:
                if field in t and str(t[field]) in resolved:
                    t[field] = resolved[str(t[field])]
        kind = info.get("internal_type")
        ref_table = info.get("reference") if kind in ("reference", "glide_list") else ""
        if kind == "glide_list":
            values = sorted({x.strip() for v in values for x in v.split(",") if x.strip()})
        if ref_table and values:
            not_ids = [v for v in values if not _SYS_ID.match(v)]
            if not_ids:
                return _refuse(
                    "REFERENCE_NOT_SYS_ID",
                    f"{field} references {ref_table}; pass sys_ids (look them up with "
                    f"sn_query). Not sys_ids: {', '.join(not_ids[:5])}.",
                )
            try:
                found, _ = sn_query_page(
                    config,
                    auth_manager,
                    table=ref_table,
                    query="sys_idIN" + ",".join(values),
                    fields="sys_id",
                    limit=len(values),
                    offset=0,
                    no_count=True,
                    fail_silently=False,
                )
            except Exception as e:  # noqa: BLE001
                if _is_auth_error(e):
                    raise
                return _refuse(
                    "REFERENCE_UNVERIFIED", f"Could not read {ref_table} to check {field}: {e}."
                )
            have = {_raw(r.get("sys_id")) for r in found}
            absent = [v for v in values if v not in have]
            if absent:
                return _refuse(
                    "REFERENCE_NOT_FOUND",
                    f"{field}: no {ref_table} record with sys_id {', '.join(absent[:5])}.",
                )
    return None


# ---------------------------------------------------------------------------
# Reading the rows, gates 3 and 4
# ---------------------------------------------------------------------------


def _count(config: Any, auth_manager: Any, table: str, query: str) -> Optional[int]:
    _, total = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=query,
        fields="sys_id",
        limit=1,
        offset=0,
        fail_silently=False,
    )
    return total


def _label_column(config: Any, auth_manager: Any, table: str) -> Optional[str]:
    columns = table_columns(config, auth_manager, table) or set()
    return next((c for c in _LABEL_COLUMNS if c in columns), None)


def _read_rows(
    config: Any,
    auth_manager: Any,
    table: str,
    query: str,
    fields: Optional[Sequence[str]],
    cap: int,
) -> List[Dict[str, Any]]:
    """Paged read; ``fields=None`` reads every column the session can see."""
    out: List[Dict[str, Any]] = []
    offset = 0
    while len(out) <= cap:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table=table,
            query=query,
            fields="" if fields is None else ",".join(["sys_id", *fields]),
            limit=_PAGE,
            offset=offset,
            no_count=True,
            orderby="sys_id",
            fail_silently=False,
        )
        out.extend(rows)
        if len(rows) < _PAGE:
            break
        offset += _PAGE
    return out


def _token(instance: str, table: str, plan: List[Dict[str, Any]]) -> str:
    canon = json.dumps(
        {
            "instance": instance,
            "table": table,
            "rows": [
                [p["sys_id"], p["before"], p["after"]]
                for p in sorted(plan, key=lambda p: p["sys_id"])
            ],
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def build_plan(
    config: Any,
    auth_manager: Any,
    *,
    table: str,
    query: Optional[str] = None,
    set_values: Optional[Dict[str, Any]] = None,
    rows: Optional[List[Dict[str, Any]]] = None,
    max_rows: int = DEFAULT_MAX_ROWS,
    confirm_whole_table: Optional[str] = None,
) -> Dict[str, Any]:
    """Run every gate and return the plan (or a refusal). Reads only."""
    cap = min(max(int(max_rows or DEFAULT_MAX_ROWS), 1), HARD_MAX_ROWS)
    ancestry, refusal = check_table(config, auth_manager, table)
    if refusal:
        return refusal
    assert ancestry is not None
    invalidate_query_cache(table=table)

    if rows is not None:
        if query or set_values:
            return _refuse("MODE_CONFLICT", "Pass either query+set or rows, not both.")
        targets: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            sid = str((r or {}).get("sys_id") or "").strip()
            if not _SYS_ID.match(sid):
                return _refuse("BAD_ROW", f"Every row needs a sys_id; got {r!r:.120}.")
            if sid in targets:
                return _refuse("DUPLICATE_ROW", f"sys_id {sid} appears twice.")
            targets[sid] = {k: v for k, v in r.items() if k != "sys_id"}
        if not targets:
            return _refuse("NOTHING_TO_SET", "rows is empty.")
        if len(targets) > cap:
            return _refuse(
                "OVER_CAP",
                f"{len(targets)} rows exceed max_rows={cap} (hard limit {HARD_MAX_ROWS}).",
            )
        refusal = check_values(config, auth_manager, table, ancestry, list(targets.values()))
        if refusal:
            return refusal
        fields = sorted({f for t in targets.values() for f in t})
        label = _label_column(config, auth_manager, table)
        read_fields = fields + ([label] if label and label not in fields else [])
        current = _read_rows(
            config, auth_manager, table, "sys_idIN" + ",".join(targets), read_fields, cap
        )
        by_id = {_raw(r.get("sys_id")): r for r in current}
        absent = [s for s in targets if s not in by_id]
        if absent:
            return _refuse(
                "ROWS_NOT_FOUND",
                f"{len(absent)} sys_id(s) are not {table} records: {', '.join(absent[:5])}.",
            )
        matched_total = len(targets)
    else:
        refusal = check_condition(config, auth_manager, table, query or "")
        if refusal:
            return refusal
        data = dict(set_values or {})
        refusal = check_values(config, auth_manager, table, ancestry, [data])
        if refusal:
            return refusal
        matched = _count(config, auth_manager, table, query or "")
        whole = _count(config, auth_manager, table, "")
        if matched is None or whole is None:
            return _refuse(
                "COUNT_UNVERIFIED",
                "The server did not report how many rows match (or how many the table has), "
                "so the scope cannot be proven.",
            )
        if matched == 0:
            return _refuse("NO_MATCH", f"No {table} row matches the condition.", matched=0)
        if matched == whole and whole > 1 and confirm_whole_table != table:
            return _refuse(
                "WHOLE_TABLE",
                f"The condition matches every row of {table} ({whole}). Either a condition "
                "was dropped or this really is a whole-table change: re-check it, and only "
                f"if it is intended pass confirm_whole_table='{table}'.",
                matched=matched,
            )
        if matched > cap:
            return _refuse(
                "OVER_CAP",
                f"{matched} rows match; max_rows is {cap} (hard limit {HARD_MAX_ROWS}). Narrow "
                "the condition or raise max_rows — rows are never silently cut to the first N.",
                matched=matched,
            )
        fields = sorted(data)
        label = _label_column(config, auth_manager, table)
        read_fields = fields + ([label] if label and label not in fields else [])
        current = _read_rows(config, auth_manager, table, query or "", read_fields, cap)
        if len(current) != matched:
            return _refuse(
                "COUNT_MISMATCH",
                f"The server counted {matched} matching rows but returned {len(current)} "
                "(ACL-hidden rows or a concurrent change). The scope is not proven.",
            )
        targets = {_raw(r.get("sys_id")): dict(data) for r in current}
        by_id = {_raw(r.get("sys_id")): r for r in current}
        matched_total = matched

    plan: List[Dict[str, Any]] = []
    unchanged = 0
    for sid, want in targets.items():
        row = by_id[sid]
        before = {f: _raw(row.get(f)) for f in want}
        after = {f: _text(v) for f, v in want.items()}
        if before == after:
            unchanged += 1
            continue
        entry = {"sys_id": sid, "before": before, "after": after}
        if label:
            entry["label"] = _raw(row.get(label))
        plan.append(entry)

    return {
        "success": True,
        "table": table,
        "ancestry": list(ancestry),
        "fields": fields,
        "matched": matched_total,
        "unchanged": unchanged,
        "plan": plan,
        "token": _token(config.instance_url, table, plan),
    }


# ---------------------------------------------------------------------------
# Side effects (what each row's update will fire) — reported, never claimed clean
# ---------------------------------------------------------------------------


def side_effects(
    config: Any, auth_manager: Any, table: str, ancestry: Sequence[str]
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    collections = ",".join(ancestry)
    for key, tbl in (("business_rules", "sys_script"), ("notifications", "sysevent_email_action")):
        try:
            out[key] = _count(
                config,
                auth_manager,
                tbl,
                f"collectionIN{collections}^active=true^action_update=true",
            )
        except Exception as e:  # noqa: BLE001
            if _is_auth_error(e):
                raise
            out[key] = None
    out["flows"] = "not counted"
    out["note"] = (
        "Every row's update fires these (counts of active on-update rules/notifications on "
        f"{table} and its parents; None = could not read). Flows are not counted: "
        f"get_table_automation(table='{table}', operation='update') lists everything."
    )
    return out


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------


def _snapshot_dir(instance_url: str) -> Path:
    host = urlparse(instance_url).hostname or "unknown"
    return state_dir() / "data_update" / host


def snapshot_path(instance_url: str, snapshot_id: str) -> Path:
    if not re.match(r"^[A-Za-z0-9_.-]+$", snapshot_id or ""):
        raise ValueError("bad snapshot id")
    return _snapshot_dir(instance_url) / f"{snapshot_id}.json"


def write_review(instance_url: str, name: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every row and field as a CSV a PERSON opens (Excel) when the response was shortened.

    It is not for reading back into the conversation — that would undo the trim.
    One line per row and field: what was set, and what the server changed on its own.
    """
    if not re.match(r"^[A-Za-z0-9_.-]+$", name or ""):
        raise ValueError("bad review name")
    path = _snapshot_dir(instance_url) / "review" / f"{name}.csv"
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["sys_id", "label", "field", "kind", "before", "after", "applied"])
    lines = 0
    for r in rows:
        applied = "" if "applied" not in r else ("yes" if r["applied"] else "no")
        stored = r.get("stored") or {}
        for f, after in (r.get("after") or {}).items():
            w.writerow(
                [
                    r["sys_id"],
                    r.get("label", ""),
                    f,
                    "set",
                    (r.get("before") or {}).get(f, ""),
                    stored.get(f, after),
                    applied,
                ]
            )
            lines += 1
        for f, v in (r.get("side") or {}).items():
            w.writerow(
                [r["sys_id"], r.get("label", ""), f, "server", v["before"], v["after"], applied]
            )
            lines += 1
    try:
        atomic_write_text(path, "\ufeff" + buf.getvalue())  # BOM: Excel reads it as UTF-8
    except Exception as e:  # noqa: BLE001
        return {"full_list_error": f"The full list could not be written ({e})."}
    return {
        "full_list": str(path),
        "full_list_lines": lines,
        "full_list_note": "For the user to open (Excel/CSV). Give them the path; do not read it "
        "back into the conversation.",
    }


def list_snapshots(instance_url: str, limit: int = 20) -> List[Dict[str, Any]]:
    d = _snapshot_dir(instance_url)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json"), reverse=True)[:limit]:
        try:
            s = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            out.append({"snapshot": p.stem, "unreadable": True})
            continue
        out.append(
            {
                "snapshot": p.stem,
                "table": s.get("table"),
                "rows": len(s.get("rows") or []),
                "status": s.get("status"),
                "created_at": s.get("created_at"),
                "reverts": s.get("reverts"),
            }
        )
    return out


def load_snapshot(
    instance_url: str, snapshot_id: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    try:
        path = snapshot_path(instance_url, snapshot_id)
    except ValueError:
        return None, _refuse("BAD_SNAPSHOT", f"{snapshot_id!r} is not a snapshot id.")
    if not path.is_file():
        return None, _refuse(
            "SNAPSHOT_NOT_FOUND",
            f"No snapshot {snapshot_id} for this instance. list_snapshots shows the ones there are.",
        )
    try:
        snap = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, _refuse(
            "SNAPSHOT_UNREADABLE", f"Snapshot {snapshot_id} could not be read: {e}."
        )
    if snap.get("instance") != instance_url:
        return None, _refuse(
            "SNAPSHOT_OTHER_INSTANCE",
            f"Snapshot {snapshot_id} was taken on another instance.",
        )
    return snap, None


# ---------------------------------------------------------------------------
# Revert planning
# ---------------------------------------------------------------------------


def build_revert_plan(config: Any, auth_manager: Any, snap: Dict[str, Any]) -> Dict[str, Any]:
    """Rows whose CURRENT values are still what the update left — the only safe ones to restore."""
    table = str(snap.get("table") or "")
    ancestry, refusal = check_table(config, auth_manager, table)
    if refusal:
        return refusal
    applied = [r for r in (snap.get("rows") or []) if r.get("applied")]
    if not applied:
        return _refuse("NOTHING_TO_REVERT", "The snapshot records no applied rows.")
    fields = sorted({f for r in applied for f in r.get("before", {})})
    invalidate_query_cache(table=table)
    current = _read_rows(
        config,
        auth_manager,
        table,
        "sys_idIN" + ",".join(r["sys_id"] for r in applied),
        fields,
        HARD_MAX_ROWS,
    )
    by_id = {_raw(r.get("sys_id")): r for r in current}
    plan: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    already = 0
    missing: List[str] = []
    for r in applied:
        sid = r["sys_id"]
        row = by_id.get(sid)
        if row is None:
            missing.append(sid)
            continue
        now = {f: _raw(row.get(f)) for f in r["before"]}
        left = r.get("stored") or r["after"]
        if now == r["before"]:
            already += 1
        elif now == {f: str(left.get(f, "")) for f in r["before"]}:
            entry = {
                "sys_id": sid,
                "before": now,
                "after": dict(r["before"]),
                "label": r.get("label", ""),
            }
            if r.get("side"):
                entry["restore_side"] = {f: v["before"] for f, v in r["side"].items()}
            plan.append(entry)
        else:
            conflicts.append(
                {"sys_id": sid, "label": r.get("label", ""), "now": now, "update_left": left}
            )
    return {
        "success": True,
        "table": table,
        "ancestry": list(ancestry or []),
        "fields": fields,
        "matched": len(applied),
        "unchanged": already,
        "plan": plan,
        "conflicts": conflicts,
        "missing": missing,
        "token": _token(config.instance_url, table, plan),
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute(
    config: Any,
    auth_manager: Any,
    plan_result: Dict[str, Any],
    *,
    reverts: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the snapshot, then PATCH row by row; stop at the first failure."""
    table = plan_result["table"]
    plan = plan_result["plan"]
    # Every column of every row, read right before the write: the PATCH response
    # is the whole row after, so the difference outside the sent fields is what a
    # business rule changed on its own. Unread means unknown, so no write.
    try:
        full = _read_rows(
            config,
            auth_manager,
            table,
            "sys_idIN" + ",".join(p["sys_id"] for p in plan),
            None,
            HARD_MAX_ROWS,
        )
    except Exception as e:  # noqa: BLE001
        if _is_auth_error(e):
            raise
        return _refuse(
            "ROWS_UNREADABLE",
            f"The rows could not be read in full before the update ({e}), so what else the "
            "server changes could not be recorded. Nothing was written.",
        )
    full_before = {_raw(r.get("sys_id")): r for r in full}
    gone = [p["sys_id"] for p in plan if p["sys_id"] not in full_before]
    if gone:
        return _refuse(
            "PREVIEW_STALE",
            f"{len(gone)} planned row(s) are no longer readable. Nothing was written. Preview again.",
            missing=gone[:_SAMPLE],
        )
    now = datetime.now(timezone.utc)
    snapshot_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{table}-{plan_result['token'][:8]}"
    snap: Dict[str, Any] = {
        "instance": config.instance_url,
        "table": table,
        "created_at": now.isoformat(),
        "token": plan_result["token"],
        "status": "started",
        "reverts": reverts,
        "rows": [dict(p, applied=False) for p in plan],
    }
    try:
        path = snapshot_path(config.instance_url, snapshot_id)
        atomic_write_text(path, json.dumps(snap, ensure_ascii=False, indent=1))
    except Exception as e:  # noqa: BLE001
        return _refuse(
            "SNAPSHOT_FAILED", f"The snapshot could not be written ({e}), so no row was touched."
        )

    base = f"{config.instance_url}/api/now/table/{table}"
    failed: Optional[Dict[str, Any]] = None
    server_changed: List[Dict[str, Any]] = []
    also_changed: List[Dict[str, Any]] = []
    not_restored: List[Dict[str, Any]] = []
    done = 0
    for entry in snap["rows"]:
        try:
            resp = auth_manager.make_request(
                "PATCH",
                f"{base}/{entry['sys_id']}",
                json=entry["after"],
                params={"sysparm_exclude_reference_link": "true"},
                headers=auth_manager.get_headers(),
                timeout=config.timeout,
            )
            resp.raise_for_status()
            result = (resp.json() or {}).get("result") or {}
        except Exception as e:  # noqa: BLE001
            if _is_auth_error(e):
                failed = {"sys_id": entry["sys_id"], "error": f"session: {e}"}
            else:
                failed = {"sys_id": entry["sys_id"], "error": str(e)[:300]}
            break
        stored = {f: _raw(result.get(f)) for f in entry["after"]}
        entry["applied"] = True
        entry["stored"] = stored
        done += 1
        diff = {
            f: {"sent": entry["after"][f], "stored": stored[f]}
            for f in entry["after"]
            if stored[f] != entry["after"][f]
        }
        if diff:
            server_changed.append(
                {"sys_id": entry["sys_id"], "label": entry.get("label", ""), "fields": diff}
            )
        prior = full_before[entry["sys_id"]]
        restore = entry.get("restore_side") or {}
        side = {
            f: {"before": _raw(prior.get(f)), "after": _raw(result.get(f))}
            for f in result
            if f not in entry["after"]
            and not f.startswith("sys_")
            and f in prior
            and _raw(prior.get(f)) != _raw(result.get(f))
            and restore.get(f)
            != _raw(result.get(f))  # a revert's side field coming back is the point
        }
        if side:
            entry["side"] = side
            also_changed.append(
                {"sys_id": entry["sys_id"], "label": entry.get("label", ""), "fields": side}
            )
        missed = {
            f: {"expected": want, "now": _raw(result.get(f))}
            for f, want in restore.items()
            if f in result and _raw(result.get(f)) != want
        }
        if missed:
            not_restored.append(
                {"sys_id": entry["sys_id"], "label": entry.get("label", ""), "fields": missed}
            )

    snap["status"] = "failed" if failed else "complete"
    snap["finished_at"] = datetime.now(timezone.utc).isoformat()
    write_note = None
    try:
        atomic_write_text(path, json.dumps(snap, ensure_ascii=False, indent=1))
    except Exception as e:  # noqa: BLE001
        write_note = (
            f"The final snapshot could not be saved ({e}); the one written before the update "
            "still holds every row's previous values."
        )
    invalidate_query_cache(table=table)

    out: Dict[str, Any] = {
        "success": failed is None,
        "table": table,
        "updated": done,
        "planned": len(plan),
        "snapshot": snapshot_id,
        "revert": f"manage_data_update(action='preview_revert', snapshot='{snapshot_id}')",
    }
    if failed:
        out["error"] = "STOPPED_AT_FAILURE"
        out["failed_row"] = failed
        out["not_attempted"] = len(plan) - done - 1
        out["message"] = (
            f"Row {failed['sys_id']} failed; {done} row(s) before it were updated and the rest "
            "were not attempted. The snapshot covers the updated rows."
        )
    if server_changed:
        out["server_changed"] = brief(server_changed[:_SAMPLE])
        out["server_changed_count"] = len(server_changed)
        out["server_changed_note"] = (
            "A business rule stored a different value than was sent on these rows — they "
            "did NOT take the value. Report them; do not call the update done for them."
        )
    if also_changed:
        out["also_changed"] = brief(also_changed[:_SAMPLE])
        out["also_changed_count"] = len(also_changed)
        out["also_changed_by_field"] = _side_distribution(also_changed)
        out["also_changed_note"] = (
            "The server changed these fields on its own (business rules, calculations) — they "
            "were not sent. Tell the user. The snapshot records them; a revert writes back only "
            "the sent fields and reports whether these came back."
        )
    if not_restored:
        out["side_not_restored"] = brief(not_restored[:_SAMPLE])
        out["side_not_restored_count"] = len(not_restored)
        out["side_not_restored_note"] = (
            "The update had also changed these fields through the server; reverting the sent "
            "fields did not bring them back. They are NOT restored — tell the user."
        )
    if write_note:
        out["snapshot_note"] = write_note
    return out


def _side_distribution(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    dist: Dict[str, Dict[str, int]] = {}
    for r in rows:
        for f, v in r["fields"].items():
            key = _dist_key(v["before"], v["after"])
            dist.setdefault(f, {})
            dist[f][key] = dist[f].get(key, 0) + 1
    return _top(dist)


def preview_view(plan_result: Dict[str, Any]) -> Dict[str, Any]:
    """What the caller sees: counts, a sample, and per-field value distributions."""
    plan = plan_result["plan"]
    dist: Dict[str, Dict[str, int]] = {}
    for p in plan:
        for f, v in p["before"].items():
            key = _dist_key(v, p["after"][f])
            dist.setdefault(f, {})
            dist[f][key] = dist[f].get(key, 0) + 1
    view: Dict[str, Any] = {
        "success": True,
        "dry_run": True,
        "table": plan_result["table"],
        "matched": plan_result["matched"],
        "will_change": len(plan),
        "already_at_value": plan_result["unchanged"],
        "changes_by_field": _top(dist),
        "sample": brief(plan[:_SAMPLE]),
        "preview_token": plan_result["token"],
    }
    if len(plan) > _SAMPLE:
        view["sample_note"] = f"First {_SAMPLE} of {len(plan)} rows; changes_by_field covers all."
    return view


def _clip(value: Any) -> Any:
    if not isinstance(value, str) or len(value) <= _VALUE_CHARS:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:6]
    return f"{value[:_VALUE_CHARS]}…(+{len(value) - _VALUE_CHARS} chars #{digest})"


def brief(obj: Any) -> Any:
    """Display copy: long values clipped, at most _VIEW_FIELDS keys per mapping."""
    if isinstance(obj, str):
        return _clip(obj)
    if isinstance(obj, list):
        return [brief(x) for x in obj]
    if isinstance(obj, dict):
        items = list(obj.items())
        out = {k: brief(v) for k, v in items[:_VIEW_FIELDS]}
        if len(items) > _VIEW_FIELDS:
            out["…"] = f"+{len(items) - _VIEW_FIELDS} more field(s)"
        return out
    return obj


def _dist_key(before: Any, after: Any) -> str:
    return f"{_clip(before or '') or '(empty)'} -> {_clip(after or '') or '(empty)'}"


def _top(dist: Dict[str, Dict[str, int]]) -> Dict[str, Any]:
    return brief(
        {f: dict(sorted(d.items(), key=lambda kv: -kv[1])[:_DIST_KEYS]) for f, d in dist.items()}
    )


def _size(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str))


def fit(view: Dict[str, Any], budget: Optional[int] = None) -> Dict[str, Any]:
    """Shrink samples, then distributions, until the result fits. Counts are never touched."""
    budget = budget or _VIEW_BUDGET
    if _size(view) <= budget:
        return view
    trimmed = False
    while _size(view) > budget:
        lists = [k for k in _SAMPLED if isinstance(view.get(k), list) and len(view[k]) > 1]
        if not lists:
            break
        k = max(lists, key=lambda k: _size(view[k]))
        view[k] = view[k][: len(view[k]) // 2]
        trimmed = True
    for keep in (3, 1):
        if _size(view) <= budget:
            break
        for k in _DISTS:
            if isinstance(view.get(k), dict):
                view[k] = {
                    f: (dict(list(d.items())[:keep]) if isinstance(d, dict) else d)
                    for f, d in view[k].items()
                }
                trimmed = True
    if _size(view) > budget:
        for k in _SAMPLED + _DISTS:
            if k in view and _size(view) > budget:
                view[k] = f"withheld ({_size(view[k])} bytes) to fit the response"
                trimmed = True
    if trimmed:
        view["trimmed_note"] = (
            "Samples/distributions were shortened to fit; every count above is complete. "
            "full_list is every row and field, for the user to open."
        )
    return view
