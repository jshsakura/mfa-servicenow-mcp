"""ServiceNow Attachment API download tool.

Downloads the actual file content behind a ``sys_attachment`` record via the
documented Attachment REST API and writes it to local disk, returning only a
summary (path + metadata) to context — never the raw bytes (a 5MB xlsx would
blow the LLM context budget). The caller then Reads the file from ``saved_path``.

Intelligent resolution: accept an explicit ``attachment_sys_id``, OR a parent
``table`` + ``record`` (sys_id or display number, e.g. INC0010023) and resolve
the record's attachments automatically. Attachments live on any table — task
records, knowledge articles, catalog items — so the parent table is generic.

Works with every auth type: ``/api/now/attachment`` is a documented Now Platform
REST API (metadata is read through the Table API on ``sys_attachment``), so no
browser-only gate is needed.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools.sn_api import _safe_json, sn_query_page
from servicenow_mcp.utils.atomic_io import atomic_write_bytes
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTACHMENT_MB = 100
MAX_ATTACHMENTS_LISTED = 50
_ATTACH_FIELDS = "sys_id,file_name,content_type,size_bytes,table_name,table_sys_id"
_SYS_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# Reject path separators / reserved chars so a hostile or odd file_name can
# never escape the output dir or break the filesystem.
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class DownloadAttachmentParams(BaseModel):
    attachment_sys_id: Optional[str] = Field(
        default=None, description="sys_attachment sys_id. Omit to resolve via table+record."
    )
    table: Optional[str] = Field(
        default=None, description="Parent table (e.g. incident, kb_knowledge) when no sys_id."
    )
    record: Optional[str] = Field(
        default=None, description="Parent record: sys_id or display number (e.g. INC0010023)."
    )
    download_all: bool = Field(
        default=False, description="If the record has many attachments, fetch all (else list them)."
    )
    output_dir: Optional[str] = Field(
        default=None, description="Save dir. Default: ./temp/<instance>/attachments/"
    )
    filename: Optional[str] = Field(
        default=None, description="Override saved name (single file only). Default: real file_name."
    )
    max_size_mb: int = Field(
        default=DEFAULT_MAX_ATTACHMENT_MB,
        description="Refuse files larger than this (MB). Guards against huge pulls.",
    )


def _is_sys_id(value: str) -> bool:
    return bool(_SYS_ID_RE.match((value or "").strip().lower()))


def _safe_attachment_name(name: Optional[str], fallback: str) -> str:
    """Strip any path components and reserved chars → a safe basename."""
    base = Path((name or "").strip()).name
    cleaned = _INVALID_FILENAME_CHARS.sub("_", base).strip().strip(".")
    return cleaned or fallback


def _attachment_dir(config: ServerConfig, output_dir: Optional[str]) -> Path:
    if output_dir:
        return Path(output_dir).expanduser().resolve()
    instance_name = (urlparse(config.instance_url).hostname or "instance").split(".")[0]
    return Path.cwd() / "temp" / instance_name / "attachments"


def _get_attachment_meta(
    config: ServerConfig, auth_manager: AuthManager, sys_id: str
) -> Optional[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_attachment",
        query=f"sys_id={sys_id}",
        fields=_ATTACH_FIELDS,
        limit=1,
        offset=0,
        no_count=True,
    )
    return rows[0] if rows else None


def _list_record_attachments(
    config: ServerConfig, auth_manager: AuthManager, table: str, record_sys_id: str
) -> List[Dict[str, Any]]:
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table="sys_attachment",
        query=f"table_name={table}^table_sys_id={record_sys_id}",
        fields=_ATTACH_FIELDS,
        limit=MAX_ATTACHMENTS_LISTED,
        offset=0,
        no_count=True,
    )
    return rows


def _resolve_record_sys_id(
    config: ServerConfig, auth_manager: AuthManager, table: str, record: str
) -> tuple[Optional[str], Optional[str]]:
    """Resolve a record reference to a sys_id. A 32-hex value is already one;
    otherwise look it up by display number (the `number` field)."""
    if _is_sys_id(record):
        return record, None
    if not table:
        return None, "table is required to resolve a record number to a sys_id."
    rows, _ = sn_query_page(
        config,
        auth_manager,
        table=table,
        query=f"number={record}",
        fields="sys_id,number",
        limit=1,
        offset=0,
        no_count=True,
    )
    if rows:
        return rows[0].get("sys_id"), None
    return None, f"No {table} record matched number '{record}'. Pass a sys_id directly."


def _download_one(
    config: ServerConfig,
    auth_manager: AuthManager,
    meta: Dict[str, Any],
    out_dir: Path,
    max_bytes: int,
    filename_override: Optional[str],
) -> Dict[str, Any]:
    sys_id = meta.get("sys_id", "")
    file_name = meta.get("file_name") or ""
    size_bytes = int(meta.get("size_bytes") or 0)

    if size_bytes and size_bytes > max_bytes:
        return {
            "success": False,
            "sys_id": sys_id,
            "file_name": file_name,
            "size_bytes": size_bytes,
            "message": (
                f"'{file_name}' is {size_bytes / 1024 / 1024:.1f} MB, over the cap. "
                "Raise max_size_mb to download it."
            ),
        }

    url = f"{config.instance_url}/api/now/attachment/{sys_id}/file"
    try:
        resp = auth_manager.make_request("GET", url, timeout=120)
    except Exception as exc:  # noqa: BLE001 — surfaced in the result
        return {"success": False, "sys_id": sys_id, "message": f"File request failed: {exc}"}

    if resp.status_code >= 400:
        return {
            "success": False,
            "sys_id": sys_id,
            "status_code": resp.status_code,
            "message": f"File download failed ({resp.status_code}).",
            "details": _safe_json(resp),
        }

    # The /file endpoint streams the raw bytes. A JSON content-type here (when the
    # attachment itself is not JSON) means an error wrapper slipped through — do
    # not write that to disk as if it were the file.
    response_ctype = (resp.headers.get("Content-Type") or "").lower()
    expected_ctype = (meta.get("content_type") or "").lower()
    if "application/json" in response_ctype and "application/json" not in expected_ctype:
        return {
            "success": False,
            "sys_id": sys_id,
            "message": "Expected file bytes but got a JSON response (likely an error).",
            "details": _safe_json(resp),
        }

    content = resp.content or b""
    safe_name = _safe_attachment_name(
        filename_override or file_name, fallback=f"attachment_{sys_id}"
    )
    out_path = out_dir / safe_name
    try:
        atomic_write_bytes(out_path, content)
    except Exception as exc:  # noqa: BLE001 — surfaced in the result
        return {"success": False, "sys_id": sys_id, "message": f"Failed to write to disk: {exc}"}

    return {
        "success": True,
        "sys_id": sys_id,
        "saved_path": str(out_path),
        "file_name": file_name or safe_name,
        "content_type": meta.get("content_type"),
        "size_bytes": len(content),
        "table_name": meta.get("table_name"),
        "table_sys_id": meta.get("table_sys_id"),
    }


@register_tool(
    "download_attachment",
    params=DownloadAttachmentParams,
    description="Download ServiceNow attachment file(s) to disk by attachment_sys_id, or table+record. Read from saved_path.",
    serialization="raw_dict",
    return_type=dict,
)
def download_attachment(
    config: ServerConfig, auth_manager: AuthManager, params: DownloadAttachmentParams
) -> Dict[str, Any]:
    out_dir = _attachment_dir(config, params.output_dir)
    max_bytes = max(1, params.max_size_mb) * 1024 * 1024
    sys_id = (params.attachment_sys_id or "").strip()
    table = (params.table or "").strip()
    record = (params.record or "").strip()

    # --- Mode A: explicit attachment sys_id -------------------------------
    if sys_id:
        meta = _get_attachment_meta(config, auth_manager, sys_id)
        if meta is None:
            return {"success": False, "message": f"No sys_attachment record for sys_id '{sys_id}'."}

        # Scope/consistency guard: if a parent was also named, the attachment must
        # actually belong to it — otherwise refuse rather than grab the wrong file.
        owner_table = meta.get("table_name") or ""
        if table and owner_table and table != owner_table:
            return {
                "success": False,
                "message": (
                    f"Attachment belongs to table '{owner_table}', not '{table}'. "
                    "Refusing — verify you have the right attachment."
                ),
            }
        if record:
            rec_sys_id, err = _resolve_record_sys_id(
                config, auth_manager, table or owner_table, record
            )
            if rec_sys_id and meta.get("table_sys_id") and rec_sys_id != meta.get("table_sys_id"):
                return {
                    "success": False,
                    "message": (
                        f"Attachment is not on record '{record}' "
                        f"(it belongs to {owner_table} {meta.get('table_sys_id')}). Refusing."
                    ),
                }

        result = _download_one(config, auth_manager, meta, out_dir, max_bytes, params.filename)
        if result.get("success"):
            result["safety_notice"] = (
                "File written to disk. Read it from saved_path; raw bytes not returned to context."
            )
        return result

    # --- Mode B: resolve from parent record -------------------------------
    if table and record:
        rec_sys_id, err = _resolve_record_sys_id(config, auth_manager, table, record)
        if err or not rec_sys_id:
            return {"success": False, "message": err or f"Could not resolve record '{record}'."}

        attachments = _list_record_attachments(config, auth_manager, table, rec_sys_id)
        if not attachments:
            return {
                "success": True,
                "downloaded": 0,
                "table": table,
                "record_sys_id": rec_sys_id,
                "message": f"No attachments on {table} '{record}'.",
            }

        # Many attachments + no download_all → list, don't guess. Conservative:
        # avoid silently pulling 20 files; let the caller pick or opt into all.
        if len(attachments) > 1 and not params.download_all:
            return {
                "success": True,
                "downloaded": 0,
                "multiple": True,
                "table": table,
                "record_sys_id": rec_sys_id,
                "attachments": [
                    {
                        "sys_id": a.get("sys_id"),
                        "file_name": a.get("file_name"),
                        "content_type": a.get("content_type"),
                        "size_bytes": int(a.get("size_bytes") or 0),
                    }
                    for a in attachments
                ],
                "message": (
                    f"{len(attachments)} attachments found. Call again with "
                    "attachment_sys_id=<one>, or download_all=true to fetch all."
                ),
            }

        single = len(attachments) == 1
        results = [
            _download_one(
                config,
                auth_manager,
                a,
                out_dir,
                max_bytes,
                params.filename if single else None,
            )
            for a in attachments
        ]
        downloaded = sum(1 for r in results if r.get("success"))
        return {
            "success": True,
            "downloaded": downloaded,
            "requested": len(results),
            "table": table,
            "record_sys_id": rec_sys_id,
            "files": results,
            "safety_notice": (
                "Files written to disk. Read them from saved_path; raw bytes not returned."
            ),
        }

    return {
        "success": False,
        "message": "Provide attachment_sys_id, or table + record (sys_id or number).",
    }
