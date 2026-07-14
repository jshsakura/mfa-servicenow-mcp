"""Export records as importable ``<unload>`` XML to local disk.

Verified against a live instance (do NOT "simplify" back to a record-table
export — that path was tested and rejected):

  * ``<table>.do?XML`` / ``<table>_list.do?XML`` return an ``<xml>`` *field dump*
    (root ``<xml>``, no ``action="INSERT_OR_UPDATE"``). NOT importable. Dead end.
  * ``sys_update_xml`` (update-set snapshot) is *stale* — empty/old the moment a
    record is edited outside an active update set.
  * ``sys_update_version`` with ``state=current`` holds the CURRENT importable
    payload for every tracked record, rewritten on every save. Its ``<payload>``
    field is exactly ``<?xml…?><record_update table="…"><TABLE action=…>…`` —
    the importable unload fragment.

So we fetch ``sys_update_version_list.do?XML`` (state=current, filtered by
``nameIN <table>_<sys_id>,…``), pull each ``<payload>``, strip its prolog +
``<record_update>`` wrapper, and assemble one ``<unload>`` document written
straight to disk. This sidesteps three failure modes at once: stale snapshots,
context-budget truncation of large fields, and per-record round-trips.

Escaping note (correctness-critical): the HTTP response escapes the payload
once; ElementTree decodes it once on parse, so ``payload.text`` is already the
exact original payload string. Do NOT ``html.unescape`` it again — a real
``&lt;`` living inside a field value would be corrupted into ``<`` (verified: a
second unescape changes real payloads).
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.atomic_io import atomic_write_bytes
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

_TABLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SYS_ID_RE = re.compile(r"^[0-9a-zA-Z_]{16,40}$")
# sys_update_version.name = "<table>_<sys_id>" for tracked records.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-zA-Z_.]{8,}$")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RECORD_UPDATE_RE = re.compile(r"<record_update\b[^>]*>(.*)</record_update>\s*$", re.S)
_PROLOG_RE = re.compile(r"^\s*<\?xml[^>]*\?>\s*", re.S)


class ExportRecordXmlParams(BaseModel):
    table: Optional[str] = Field(
        default=None, description="Record table (e.g. sys_script, sp_widget). With sys_ids."
    )
    sys_ids: Optional[List[str]] = Field(
        default=None, description="sys_ids to export. Combined with table into update names."
    )
    names: Optional[List[str]] = Field(
        default=None, description="Advanced: raw <table>_<sys_id> names, for a cross-table file."
    )
    output_path: Optional[str] = Field(
        default=None, description="Exact .xml file to write. Overrides output_dir."
    )
    output_dir: Optional[str] = Field(
        default=None, description="Save dir (auto filename). Default: ./temp/<instance>/xml/"
    )


def _xml_dir(config: ServerConfig, output_dir: Optional[str]) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    instance_name = (urlparse(config.instance_url).hostname or "instance").split(".")[0]
    return Path.cwd() / "temp" / instance_name / "xml"


def _safe_name(name: str, fallback: str) -> str:
    base = Path((name or "").strip()).name
    cleaned = _INVALID_FILENAME_CHARS.sub("_", base).strip().strip(".")
    return cleaned or fallback


def _resolve_names(params: ExportRecordXmlParams) -> tuple[List[str], Optional[str]]:
    """Build the ordered, de-duplicated list of sys_update_version names to fetch."""
    names: List[str] = []
    if params.names:
        names.extend(n.strip() for n in params.names if n and n.strip())
    if params.sys_ids:
        table = (params.table or "").strip().lower()
        if not _TABLE_RE.match(table):
            return (
                [],
                f"table is required (and must be a valid table name) with sys_ids: '{params.table}'.",
            )
        for sid in params.sys_ids:
            sid = (sid or "").strip()
            if not sid:
                continue
            if not _SYS_ID_RE.match(sid):
                return [], f"Invalid sys_id '{sid}'."
            names.append(f"{table}_{sid}")
    # De-dup, preserve order.
    seen: set[str] = set()
    ordered: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    if not ordered:
        return [], "Provide table+sys_ids or names — nothing to export."
    bad = [n for n in ordered if not _NAME_RE.match(n)]
    if bad:
        return [], f"Invalid update name(s): {bad}. Expected '<table>_<sys_id>'."
    return ordered, None


def _payload_to_inner(payload_text: str) -> Optional[str]:
    """<?xml?><record_update ...><TABLE ...>…</record_update>  ->  the inner <TABLE …>…."""
    p = _PROLOG_RE.sub("", (payload_text or "").strip())
    m = _RECORD_UPDATE_RE.search(p)
    inner = (m.group(1) if m else p).strip()
    return inner or None


@register_tool(
    "export_record_xml",
    params=ExportRecordXmlParams,
    description="Export records as importable <unload> XML to disk (current sys_update_version). Read saved_path.",
    serialization="raw_dict",
    return_type=dict,
)
def export_record_xml(
    config: ServerConfig, auth_manager: AuthManager, params: ExportRecordXmlParams
) -> Dict[str, Any]:
    names, err = _resolve_names(params)
    if err:
        return {"success": False, "message": err}

    query = "state=current^nameIN" + ",".join(names)
    url = (
        f"{config.instance_url}/sys_update_version_list.do?XML"
        f"&sysparm_query={quote(query, safe='')}"
    )
    try:
        resp = auth_manager.make_request("GET", url, timeout=180)
    except Exception as exc:  # noqa: BLE001 — surfaced in the result
        return {"success": False, "message": f"XML export request failed: {exc}"}

    if resp.status_code >= 400:
        return {
            "success": False,
            "status_code": resp.status_code,
            "message": f"XML export failed ({resp.status_code}).",
        }

    content = resp.content or b""
    head = content[:240].decode("utf-8", errors="replace")
    looks_html = "<html" in head.lower() or "<!doctype html" in head.lower()
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        hint = " (looks like an HTML/login page — re-auth and retry.)" if looks_html else ""
        return {
            "success": False,
            "message": f"Response was not parseable XML{hint}.",
            "preview": head,
        }
    # Parsed, but the export dump must be rooted at <xml>. An <html> root (or any
    # other) means an auth/login redirect or an error page slipped through.
    if root.tag.lower() != "xml":
        hint = (
            " — looks like an HTML/login page; re-auth and retry."
            if looks_html or root.tag.lower() == "html"
            else ""
        )
        return {
            "success": False,
            "message": f"Unexpected response root <{root.tag}>{hint}",
            "preview": head,
        }

    # Collect current payloads, keyed by name (state=current is unique per name).
    found: Dict[str, str] = {}
    for row in root.iter("sys_update_version"):
        nm = (row.findtext("name") or "").strip()
        payload = row.findtext("payload")  # already entity-decoded once by ET
        if not nm or nm in found or payload is None:
            continue
        inner = _payload_to_inner(payload)
        if inner:
            found[nm] = inner

    missing = [n for n in names if n not in found]
    if not found:
        return {
            "success": False,
            "requested": names,
            "missing": missing,
            "message": (
                "No current version found for any requested record. Check the table/sys_id, "
                "or the record may never have been customized (no sys_update_version row)."
            ),
        }

    # Assemble one <unload> in the requested order (found ones only).
    unload_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    blocks = [found[n] for n in names if n in found]
    unload = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<unload unload_date="{unload_date}">\n' + "\n".join(blocks) + "\n</unload>\n"
    ).encode("utf-8")

    if params.output_path:
        out_path = Path(params.output_path).expanduser().resolve()
    else:
        out_dir = _xml_dir(config, params.output_dir)
        stem = names[0] if len(found) == 1 else f"export_{len(found)}records"
        out_path = out_dir / _safe_name(f"{stem}.xml", fallback="export.xml")

    try:
        atomic_write_bytes(out_path, unload)
    except Exception as exc:  # noqa: BLE001 — surfaced in the result
        return {"success": False, "message": f"Failed to write to disk: {exc}"}

    result: Dict[str, Any] = {
        "success": True,
        "saved_path": str(out_path),
        "record_count": len(found),
        "size_bytes": len(unload),
        "message": (
            f"Exported {len(found)} record(s) → {out_path} ({len(unload)} bytes), "
            "importable <unload>. Read the file to use for import."
        ),
    }
    if missing:
        result["missing"] = missing
        result["warning"] = (
            f"{len(missing)} requested record(s) had no current version and were skipped: {missing}"
        )
    return result
