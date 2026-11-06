"""Prove whether a locally edited legacy-workflow script reached the server.

Legacy activity scripts are not edited through this MCP. A Table API write to
``sys_variable_value`` would change the PUBLISHED version in place (running
contexts pick it up mid-flight) and, measured on a live instance, workflow work is
captured in update sets only as one whole ``wf_workflow_<sys_id>`` record — never
as variable rows — so such a write would report success and never travel. The
edit is applied in the Workflow Editor (checkout → paste → publish), which owns
that format; this module is the other half: it reads the server and says, per
edited script, whether the edit is there.

A checkout copies every activity under new sys_ids, so an activity is matched by
what survives the copy — its name and definition, then its canvas position — and
an ambiguous or missing match is reported as such, never guessed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import sn_query_page
from servicenow_mcp.tools.workflow_export import _sha, read_live_graph
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.source_layout import normalize_source_eol

Key = Tuple[str, str]


def live_script_index(
    activities: List[Dict[str, Any]], variables: List[Dict[str, Any]]
) -> Dict[Key, List[Dict[str, Any]]]:
    """(activity name, definition) -> live activities with their variable values.

    Values are LF-normalized like the exported files: the editor's textarea may
    store CRLF, and an applied edit must not read as ``differs`` over line endings.
    """
    values: Dict[str, Dict[str, str]] = {}
    for v in variables:
        element = str(v.get("variable.element") or v.get("variable") or "")
        values.setdefault(str(v.get("document_key") or ""), {})[element] = normalize_source_eol(
            str(v.get("value") or "")
        )
    index: Dict[Key, List[Dict[str, Any]]] = {}
    for a in activities:
        key = (str(a.get("name") or ""), str(a.get("activity_definition.name") or ""))
        index.setdefault(key, []).append(
            {
                "sys_id": a.get("sys_id", ""),
                "position": (str(a.get("x") or ""), str(a.get("y") or "")),
                "values": values.get(str(a.get("sys_id") or ""), {}),
            }
        )
    return index


def _match(
    index: Dict[Key, List[Dict[str, Any]]], name: str, definition: str, position: Tuple[str, str]
) -> Tuple[Optional[Dict[str, Any]], str]:
    candidates = index.get((name, definition), [])
    if len(candidates) == 1:
        return candidates[0], ""
    if not candidates:
        return None, "activity_not_found"
    at = [c for c in candidates if c["position"] == position]
    if len(at) == 1:
        return at[0], ""
    return None, "ambiguous"


def local_scripts(wf_dir: Path, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every script file the export wrote, with whether it was edited since.

    ``edited`` is None when the export predates per-file hashes: then an edit
    cannot be told apart from an untouched file, and nobody may claim either.
    """
    out: List[Dict[str, Any]] = []
    for a in payload.get("activities", []):
        pos = a.get("position") or {}
        position = (str(pos.get("x") or ""), str(pos.get("y") or ""))
        for element, v in (a.get("variables") or {}).items():
            if "file" not in v:
                continue
            path = wf_dir / v["file"]
            text = (
                normalize_source_eol(path.read_bytes().decode("utf-8")) if path.exists() else None
            )
            recorded = v.get("sha256")
            if text is None:
                edited: Optional[bool] = None
            elif recorded:
                edited = _sha(text) != recorded
            else:
                edited = None
            out.append(
                {
                    "file": v["file"],
                    "activity": a.get("name") or "",
                    "definition": a.get("definition") or "",
                    "position": position,
                    "variable": element,
                    "recorded_sha": recorded,
                    "text": text,
                    "edited": edited,
                    "missing": text is None,
                }
            )
    return out


def pending_local_edits(
    scripts: List[Dict[str, Any]], index: Dict[Key, List[Dict[str, Any]]]
) -> List[str]:
    """Files whose content is NOT on the server and may be someone's edit.

    Used before a re-export replaces the snapshot: an edit already applied
    (local == live) is safe to replace; anything else would be destroyed.
    """
    pending = []
    for s in scripts:
        if s["missing"] or s["edited"] is False:
            continue
        live, _ = _match(index, s["activity"], s["definition"], s["position"])
        live_text = live["values"].get(s["variable"]) if live else None
        if live_text != s["text"]:
            pending.append(s["file"])
    return pending


def _capture_record(config, auth_manager, workflow_id: str) -> Dict[str, Any]:
    """The update-set record a publish writes for this workflow, newest first."""
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="sys_update_xml",
            query=f"name=wf_workflow_{workflow_id}",
            fields="sys_id,update_set,update_set.name,update_set.state,sys_updated_on,sys_updated_by",
            limit=1,
            offset=0,
            orderby="-sys_updated_on",
            display_value=False,
            fail_silently=False,
        )
    except Exception as exc:
        return {"checked": False, "error": str(exc)}
    if not rows:
        return {"checked": True, "found": False}
    r = rows[0]
    return {
        "checked": True,
        "found": True,
        "update_set": r.get("update_set.name", ""),
        "update_set_state": r.get("update_set.state", ""),
        "captured_on": r.get("sys_updated_on", ""),
        "captured_by": r.get("sys_updated_by", ""),
    }


def verify_workflow(
    config: ServerConfig,
    auth_manager: AuthManager,
    workflow_id: str,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    from servicenow_mcp.tools.source_tools import _resolve_scope_root, _safe_filename

    graph = read_live_graph(config, auth_manager, workflow_id)
    if "error" in graph:
        return {"success": False, **graph}
    wf, version = graph["workflow"], graph["version"]
    scope = str(wf.get("sys_scope.scope") or "global")
    _, scope_root = _resolve_scope_root(config, scope, output_dir)
    base = scope_root / "wf_workflow" / _safe_filename(str(wf.get("name") or workflow_id))
    wf_dir = None
    for candidate in (base, base.with_name(f"{base.name}.{workflow_id[:8]}")):
        try:
            held = json.loads((candidate / "workflow.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        if held.get("workflow", {}).get("sys_id") == workflow_id:
            wf_dir, payload = candidate, held
            break
    if wf_dir is None:
        return {
            "success": False,
            "error": "NO_EXPORT",
            "message": f"No export of this workflow under {base.parent}. Run action='export' "
            "first, edit its script files, apply them in the Workflow Editor, then verify.",
        }

    if not all(p.get("complete") for p in graph["proof"].values()):
        return {
            "success": False,
            "error": "LIVE_READ_INCOMPLETE",
            "message": "A live read hit its cap; a verdict on a partial read would be a guess.",
            "reads": graph["proof"],
        }

    index = live_script_index(graph["activities"], graph["variables"])
    scripts = local_scripts(wf_dir, payload)
    edited_results: List[Dict[str, Any]] = []
    elsewhere: List[str] = []
    unknown: List[str] = []
    for s in scripts:
        live, problem = _match(index, s["activity"], s["definition"], s["position"])
        live_text = live["values"].get(s["variable"]) if live else None
        if s["missing"]:
            unknown.append(f"{s['file']} (file deleted locally)")
            continue
        if s["edited"] is None:
            if live_text != s["text"]:
                unknown.append(f"{s['file']} (export predates hashes — re-export to track edits)")
            continue
        if not s["edited"]:
            if live is not None and live_text is not None and _sha(live_text) != s["recorded_sha"]:
                elsewhere.append(s["file"])
            continue
        if problem:
            verdict = problem
        elif live_text is None:
            verdict = "variable_not_found"
        elif live_text == s["text"]:
            verdict = "applied"
        elif _sha(live_text) == s["recorded_sha"]:
            verdict = "not_applied"
        else:
            verdict = "differs"  # neither your edit nor the exported body
        edited_results.append(
            {
                "file": s["file"],
                "activity": s["activity"] or "(unnamed)",
                "variable": s["variable"],
                "verdict": verdict,
            }
        )

    capture = _capture_record(config, auth_manager, workflow_id)
    exported_at = str(payload.get("exported_at") or "").replace(" UTC", "")
    if capture.get("found") and exported_at:
        capture["after_export"] = capture["captured_on"] > exported_at

    applied = [r for r in edited_results if r["verdict"] == "applied"]
    all_applied = bool(edited_results) and len(applied) == len(edited_results)
    result: Dict[str, Any] = {
        "success": True,
        "workflow": wf.get("name", ""),
        "export": {"dir": str(wf_dir), "exported_at": payload.get("exported_at", "")},
        "live_version": {
            "sys_id": version.get("sys_id", ""),
            "changed_since_export": version.get("sys_id")
            != (payload.get("version") or {}).get("sys_id"),
        },
        "edited": edited_results,
        "update_set_capture": capture,
    }
    if elsewhere:
        result["server_changed_unedited"] = elsewhere
    if unknown:
        result["undetermined"] = unknown
    if not edited_results:
        result["verdict"] = "NO_LOCAL_EDITS — nothing to verify."
    elif not all_applied:
        result["verdict"] = (
            f"NOT ALL APPLIED: {len(applied)}/{len(edited_results)} edited script(s) are live."
        )
    elif not capture.get("checked"):
        result["verdict"] = "APPLIED, but the update-set capture could not be read."
    elif not capture.get("found") or not capture.get("after_export"):
        result["verdict"] = (
            "APPLIED on this instance, but no update-set capture of the workflow after the "
            "export — it will not travel. Publish it with the right update set selected."
        )
    elif not capture.get("update_set"):
        result["verdict"] = (
            "APPLIED, but the capture record names no readable update set (deleted, or not "
            "visible to this session) — do not count it as shipped."
        )
    else:
        result["verdict"] = (
            f"APPLIED and captured in update set '{capture['update_set']}' "
            f"(state: {capture.get('update_set_state') or 'unread'})."
        )
    return result
