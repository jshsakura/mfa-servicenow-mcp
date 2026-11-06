"""Export one legacy workflow version to disk, complete enough to rebuild it elsewhere.

A legacy workflow's logic is not on ``wf_activity``. What each activity does — the
Run Script body, the If condition, the approval's user script, the timer — sits in
``sys_variable_value`` rows keyed to the activity; the order it runs in is the
``wf_transition`` graph (activity -> condition -> activity), not a column; what
starts it is the version's table + condition. Reading the activity list alone
gives the boxes without the program, which is exactly the wrong input for a
migration to Flow Designer.

This writes, under ``<scope root>/wf_workflow/<workflow>/``:

- ``workflow.json``  — workflow, version, trigger, stages, every activity with
  its variables and exit conditions, every transition, and what each read PROVED
  (``complete`` per read; a capped or failed read is never presented as all).
- ``outline.md``     — the graph walked from Begin, one line per exit, so the
  shape can be read without opening the JSON.
- ``activities/<name>.<sys_id8>/<variable>.js`` — every script-typed value in
  full (script, script_plain, email_script), referenced from workflow.json.

Read-only, and a reference copy: there is no ``_sync_meta`` and nothing here is
pushable — a migration reads the old engine, it does not edit it.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import SYS_ID_IN_CHUNK, sn_count, sn_query_all, sn_query_page
from servicenow_mcp.utils.atomic_io import atomic_write_text
from servicenow_mcp.utils.config import ServerConfig

# Values of these variable types are programs; they go to files, in full.
_SCRIPT_TYPES = {"script", "script_plain", "email_script"}
_READ_CAP = 5000  # rows per read; a hit is reported as incomplete, never as all

_VERSION_FIELDS = (
    "sys_id,name,workflow,table,condition,run_multiple,active,published,"
    "after_business_rules,on_cancel,expected_time,description,sys_updated_on,sys_updated_by"
)
_ACTIVITY_FIELDS = (
    "sys_id,name,activity_definition,activity_definition.name,stage,x,y,timeout,"
    "out_of_date,is_parent"
)
_VARIABLE_FIELDS = (
    "document_key,variable,variable.element,variable.column_label,variable.internal_type,value"
)
_CONDITION_FIELDS = "sys_id,activity,name,condition,else_flag,order,short_description"
_TRANSITION_FIELDS = "sys_id,from,to,condition"
_STAGE_FIELDS = "sys_id,name,value,order"


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _chunks(ids: List[str]) -> List[List[str]]:
    return [ids[i : i + SYS_ID_IN_CHUNK] for i in range(0, len(ids), SYS_ID_IN_CHUNK)]


def _read(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    query: str,
    fields: str,
    proof: Dict[str, Any],
    key: str,
) -> List[Dict[str, Any]]:
    """One bounded read; records in *proof* whether it covered everything. Raises on failure."""
    rows = sn_query_all(
        config,
        auth_manager,
        table=table,
        query=query,
        fields=fields,
        page_size=100,
        max_records=_READ_CAP,
        display_value=False,
        fail_silently=False,
        parallel=False,
    )
    entry = proof.setdefault(key, {"rows": 0, "complete": True})
    entry["rows"] += len(rows)
    if len(rows) >= _READ_CAP:
        entry["complete"] = False
    return rows


def _read_by_ids(config, auth_manager, table, field, ids, extra, fields, proof, key):
    rows: List[Dict[str, Any]] = []
    proof.setdefault(key, {"rows": 0, "complete": True})
    for chunk in _chunks(sorted(set(ids))):
        q = f"{extra}^{field}IN{','.join(chunk)}" if extra else f"{field}IN{','.join(chunk)}"
        rows.extend(_read(config, auth_manager, table, q, fields, proof, key))
    return rows


def _pick_version(config, auth_manager, workflow_id: str, version_id: Optional[str]):
    if version_id:
        q = f"sys_id={version_id}^workflow={workflow_id}"
    else:
        q = f"workflow={workflow_id}^published=true"
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="wf_workflow_version",
        query=q,
        fields=_VERSION_FIELDS,
        limit=1,
        offset=0,
        orderby="-sys_created_on",
        display_value=False,
        fail_silently=False,
    )
    return rows[0] if rows else None


_OUTLINE_VALUE_CHARS = 160


def _short(value: Any) -> str:
    text = " ".join(str(value).split())
    if len(text) <= _OUTLINE_VALUE_CHARS:
        return text
    return text[:_OUTLINE_VALUE_CHARS] + " … (full value: workflow.json)"


def _outline(payload: Dict[str, Any]) -> str:
    """One file to analyse the workflow from: trigger, stages, then every activity in
    the order the graph reaches it — its settings, its script files, its exits.

    Walked breadth-first from Begin. Activities the walk never reaches are listed
    in their own section, never dropped; values over a line point at workflow.json
    rather than pretending to be whole.
    """
    activities: List[Dict[str, Any]] = payload["activities"]
    transitions: List[Dict[str, Any]] = payload["transitions"]
    by_id = {a["sys_id"]: a for a in activities}
    out_edges: Dict[str, List[Dict[str, Any]]] = {}
    for t in transitions:
        out_edges.setdefault(t["from"], []).append(t)

    starts = [a["sys_id"] for a in activities if a["definition"] == "Begin"]
    order: List[str] = []
    queue = list(starts)
    seen = set()
    while queue:
        aid = queue.pop(0)
        if aid in seen:
            continue
        seen.add(aid)
        order.append(aid)
        queue.extend(t["to"] for t in out_edges.get(aid, []) if t["to"] not in seen)
    orphans = [a["sys_id"] for a in activities if a["sys_id"] not in seen]
    number = {aid: i + 1 for i, aid in enumerate(order + orphans)}

    def label(aid: str) -> str:
        a = by_id.get(aid)
        if not a:
            return f"<not in this version: {aid}>"
        return f"#{number[aid]} {a['name'] or '(unnamed)'} [{a['definition']}]"

    def exit_conditions(a: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        return {e["sys_id"]: e for e in a.get("exits", [])}

    def block(aid: str) -> List[str]:
        a = by_id[aid]
        head = f"### {label(aid)}"
        if a.get("stage"):
            head += f" · stage {a['stage']}"
        out = [head]
        settings = []
        scripts = []
        for element, v in a.get("variables", {}).items():
            if "file" in v:
                scripts.append(
                    f"  - `{element}` ({v['type']}) → `{v['file']}` ({v['lines']} lines)"
                )
            elif str(v.get("value", "")).strip():
                settings.append(f"  - `{element}` = {_short(v['value'])}")
        if settings:
            out += ["- settings:"] + settings
        if scripts:
            out += ["- scripts:"] + scripts
        conds = exit_conditions(a)
        edges = out_edges.get(aid, [])
        if edges:
            out.append("- exits:")
            for t in edges:
                c = conds.get(t["condition"], {})
                gate = f" when `{_short(c['condition'])}`" if c.get("condition") else ""
                out.append(
                    f"  - on '{t['condition_name'] or '(no condition)'}'{gate} → {label(t['to'])}"
                )
        dangling = [e for e in conds.values() if e["sys_id"] not in {t["condition"] for t in edges}]
        for e in dangling:
            out.append(f"  - exit '{e['name']}' leads nowhere (no transition)")
        return out + [""]

    trig = payload["trigger"]
    version = payload["version"]
    lines = [
        f"# {payload['workflow'].get('name', '')} — legacy workflow outline",
        "",
        f"- version: {version.get('name', '')} (published={version.get('published', '')}, "
        f"active={version.get('active', '')})",
        f"- trigger: table `{trig['table'] or '-'}`; condition "
        + (
            f"`{_short(trig['condition'])}`"
            if trig["condition"]
            else "none (started by script/caller)"
        )
        + f"; run_multiple={trig['run_multiple'] or '-'}",
        f"- running contexts on the old engine: {payload['running_contexts']}",
        f"- export complete: {payload['complete']}"
        + ("" if payload["complete"] else " — SOME READS WERE CAPPED, see workflow.json `reads`"),
    ]
    if payload["stages"]:
        stages = ", ".join(f"{s.get('name', '')} ({s.get('value', '')})" for s in payload["stages"])
        lines.append(f"- stages: {stages}")
    lines += ["", f"## Flow (walked from Begin) — {len(order)} activities", ""]
    for aid in order:
        lines += block(aid)
    if orphans:
        lines += [f"## Not reachable from Begin — {len(orphans)} activities", ""]
        for aid in orphans:
            lines += block(aid)
    if not starts:
        lines += ["**No Begin activity in this version — the walk had no start.**", ""]
    return "\n".join(lines)


def _held_by_other(wf_dir, workflow_id: str) -> bool:
    """True when *wf_dir* already holds an export of a DIFFERENT workflow."""
    existing = wf_dir / "workflow.json"
    if not existing.exists():
        return False
    try:
        held = json.loads(existing.read_text(encoding="utf-8"))["workflow"]["sys_id"]
    except Exception:
        return True  # unreadable: not provably ours, so do not write over it
    return held != workflow_id


def export_workflow(
    config: ServerConfig,
    auth_manager: AuthManager,
    workflow_id: str,
    version_id: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    from servicenow_mcp.tools.source_tools import _resolve_scope_root, _safe_filename

    wf_rows, _ = sn_query_page(
        config,
        auth_manager,
        table="wf_workflow",
        query=f"sys_id={workflow_id}",
        fields="sys_id,name,description,template,sys_scope.scope",
        limit=1,
        offset=0,
        display_value=False,
        fail_silently=False,
    )
    if not wf_rows:
        return {"success": False, "error": f"No wf_workflow with sys_id {workflow_id}."}
    wf = wf_rows[0]
    version = _pick_version(config, auth_manager, workflow_id, version_id)
    if not version:
        which = f"version {version_id}" if version_id else "published version"
        return {"success": False, "error": f"No {which} for workflow {workflow_id}."}
    vid = version["sys_id"]

    proof: Dict[str, Any] = {}
    try:
        acts = _read(
            config,
            auth_manager,
            "wf_activity",
            f"workflow_version={vid}",
            _ACTIVITY_FIELDS,
            proof,
            "activities",
        )
        act_ids = [a["sys_id"] for a in acts]
        variables = _read_by_ids(
            config,
            auth_manager,
            "sys_variable_value",
            "document_key",
            act_ids,
            "document=wf_activity",
            _VARIABLE_FIELDS,
            proof,
            "variables",
        )
        conditions = _read_by_ids(
            config,
            auth_manager,
            "wf_condition",
            "activity",
            act_ids,
            "",
            _CONDITION_FIELDS,
            proof,
            "conditions",
        )
        transitions = _read_by_ids(
            config,
            auth_manager,
            "wf_transition",
            "from",
            act_ids,
            "",
            _TRANSITION_FIELDS,
            proof,
            "transitions",
        )
        stages = _read(
            config,
            auth_manager,
            "wf_stage",
            f"workflow_version={vid}",
            _STAGE_FIELDS,
            proof,
            "stages",
        )
    except Exception as exc:
        # A partial export would read as the whole workflow. Write nothing.
        return {
            "success": False,
            "error": f"Export read failed ({exc}); nothing written — a partial graph is not "
            "a smaller workflow, it is a wrong one. Retry.",
            "reads_done": proof,
        }

    scope = str(wf.get("sys_scope.scope") or "global")
    _, scope_root = _resolve_scope_root(config, scope, output_dir)
    wf_dir = scope_root / "wf_workflow" / _safe_filename(str(wf.get("name") or workflow_id))
    # Workflow names are not unique. Never overwrite another workflow's export.
    if _held_by_other(wf_dir, workflow_id):
        wf_dir = wf_dir.with_name(f"{wf_dir.name}.{workflow_id[:8]}")

    cond_name = {c["sys_id"]: c.get("name", "") for c in conditions}
    vars_by_act: Dict[str, List[Dict[str, Any]]] = {}
    for v in variables:
        vars_by_act.setdefault(v.get("document_key", ""), []).append(v)
    conds_by_act: Dict[str, List[Dict[str, Any]]] = {}
    for c in conditions:
        conds_by_act.setdefault(c.get("activity", ""), []).append(c)

    files_written = 0
    activities: List[Dict[str, Any]] = []
    for a in acts:
        aid = a["sys_id"]
        definition = a.get("activity_definition.name") or ""
        folder = f"{_safe_filename(a.get('name') or definition or 'activity')}.{aid[:8]}"
        values: Dict[str, Any] = {}
        for v in sorted(vars_by_act.get(aid, []), key=lambda r: r.get("variable.element") or ""):
            element = v.get("variable.element") or v.get("variable") or ""
            raw = v.get("value") or ""
            vtype = v.get("variable.internal_type") or ""
            if vtype in _SCRIPT_TYPES and raw:
                rel = f"activities/{folder}/{_safe_filename(element)}.js"
                atomic_write_text(wf_dir / rel, raw)
                files_written += 1
                values[element] = {
                    "type": vtype,
                    "file": rel,
                    "chars": len(raw),
                    "lines": raw.count("\n") + (0 if raw.endswith("\n") else 1),
                }
            else:
                values[element] = {"type": vtype, "value": raw}
        activities.append(
            {
                "sys_id": aid,
                "name": a.get("name") or "",
                "definition": definition,
                "stage": a.get("stage") or "",
                "position": {"x": a.get("x"), "y": a.get("y")},
                "timeout": a.get("timeout") or "",
                "out_of_date": a.get("out_of_date") or "",
                "variables": values,
                "exits": [
                    {
                        "sys_id": c["sys_id"],
                        "name": c.get("name") or "",
                        "condition": c.get("condition") or "",
                        "else": c.get("else_flag") or "",
                        "order": c.get("order") or "",
                        "short_description": c.get("short_description") or "",
                    }
                    for c in sorted(conds_by_act.get(aid, []), key=lambda r: _num(r.get("order")))
                ],
            }
        )
    edges = [
        {
            "from": t.get("from", ""),
            "to": t.get("to", ""),
            "condition": t.get("condition", ""),
            "condition_name": cond_name.get(t.get("condition", ""), ""),
        }
        for t in transitions
    ]

    # In-flight contexts keep running on the old engine after a cut-over; the
    # number decides whether the old version can be retired yet.
    try:
        running: Any = sn_count(
            config,
            auth_manager,
            "wf_context",
            f"workflow_version.workflow={workflow_id}^state=executing",
        )
    except Exception as exc:
        running = f"unread ({exc})"

    complete = all(p["complete"] for p in proof.values())
    payload = {
        "workflow": {k: wf.get(k, "") for k in ("sys_id", "name", "description", "template")},
        "scope": scope,
        "version": version,
        "trigger": {
            "table": version.get("table", ""),
            "condition": version.get("condition", ""),
            "run_multiple": version.get("run_multiple", ""),
            "after_business_rules": version.get("after_business_rules", ""),
        },
        "stages": sorted(stages, key=lambda s: _num(s.get("order"))),
        "activities": activities,
        "transitions": edges,
        "running_contexts": running,
        "reads": proof,
        "complete": complete,
    }
    atomic_write_text(wf_dir / "workflow.json", json.dumps(payload, indent=2, ensure_ascii=False))
    atomic_write_text(wf_dir / "outline.md", _outline(payload))

    result: Dict[str, Any] = {
        "success": True,
        "workflow": wf.get("name", ""),
        "version": {
            "sys_id": vid,
            "name": version.get("name", ""),
            "published": version.get("published", ""),
        },
        "output_dir": str(wf_dir),
        "counts": {
            "activities": len(activities),
            "variables": len(variables),
            "script_files": files_written,
            "exits": len(conditions),
            "transitions": len(edges),
            "stages": len(stages),
        },
        "trigger": payload["trigger"],
        "running_contexts": running,
        "complete": complete,
        "note": "Reference copy, not pushable. Read outline.md first, then workflow.json.",
    }
    if not complete:
        short = [k for k, p in proof.items() if not p["complete"]]
        result["warning"] = (
            f"INCOMPLETE: {short} hit the {_READ_CAP}-row read cap — rows beyond it are "
            "missing from this export. Do not migrate from it as if it were whole."
        )
    if version_id is None and str(version.get("published")) != "true":
        result["warning_version"] = "Exported version is not marked published."
    return result
