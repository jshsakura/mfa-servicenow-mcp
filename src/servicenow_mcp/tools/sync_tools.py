"""
Local source synchronization tools for ServiceNow MCP.
Diff and push locally edited portal sources back to ServiceNow
with conflict detection and automatic snapshot-based rollback.
"""

import difflib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Set

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils import json_fast
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .portal_tools import (
    UpdatePortalComponentParams,
    _fetch_portal_component_record,
    _safe_name,
    _write_portal_component_snapshot,
    update_portal_component,
)
from .sn_api import GenericQueryParams, sn_query

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File-to-field mapping for widget directories
# ---------------------------------------------------------------------------
WIDGET_FILE_FIELD_MAP: Dict[str, str] = {
    "template.html": "template",
    "script.js": "script",
    "client_script.js": "client_script",
    "link.js": "link",
    "css.scss": "css",
}

SUPPORTED_TABLES: Set[str] = {"sp_widget", "sp_angular_provider", "sys_script_include"}

MAX_DIFF_LINES = 120


# ---------------------------------------------------------------------------
# Pydantic Parameter Models
# ---------------------------------------------------------------------------
class DiffLocalComponentParams(BaseModel):
    """Parameters for diffing local source files against remote ServiceNow."""

    path: str = Field(
        ...,
        description=(
            "Path to a local file, widget directory, or download root directory. "
            "File/widget dir: returns detailed unified diff. "
            "Download root (contains _settings.json or scope dirs): returns change summary for all components."
        ),
    )
    context_lines: int = Field(
        3,
        description="Number of context lines in unified diff output (default 3)",
    )


class PushLocalComponentParams(BaseModel):
    """Parameters for pushing local file changes to ServiceNow."""

    path: str = Field(
        ...,
        description="Path to a local file (e.g. script.js) or widget directory to push",
    )
    force: bool = Field(
        False,
        description="Force push even if remote is newer than local download. Default false.",
    )
    skip_snapshot: bool = Field(
        False,
        description="Skip pre-push snapshot creation. Default false (snapshot is always created).",
    )


# ---------------------------------------------------------------------------
# Resolved component data structure
# ---------------------------------------------------------------------------
class _ResolvedComponent:
    __slots__ = ("table", "sys_id", "name", "fields", "scope_root", "instance_url")

    def __init__(
        self,
        table: str,
        sys_id: str,
        name: str,
        fields: Dict[str, Path],
        scope_root: Path,
        instance_url: str,
    ):
        self.table = table
        self.sys_id = sys_id
        self.name = name
        self.fields = fields  # field_name -> local file path
        self.scope_root = scope_root
        self.instance_url = instance_url


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------
def _find_settings_json(start: Path) -> Dict[str, Any]:
    """Walk up from *start* looking for _settings.json. Return parsed content."""
    current = start if start.is_dir() else start.parent
    for _ in range(10):
        candidate = current / "_settings.json"
        if candidate.exists():
            return json_fast.loads(candidate.read_text(encoding="utf-8"))
        parent = current.parent
        if parent == current:
            break
        current = parent
    return {}


def _read_sync_meta(table_dir: Path) -> Dict[str, Dict[str, str]]:
    """Read _sync_meta.json from a table directory. Returns empty dict if missing."""
    path = table_dir / "_sync_meta.json"
    if not path.exists():
        return {}
    try:
        data = json_fast.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_map_json(table_dir: Path) -> Dict[str, str]:
    """Read _map.json from a table directory. Returns empty dict if missing."""
    path = table_dir / "_map.json"
    if not path.exists():
        return {}
    try:
        data = json_fast.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_sync_meta(table_dir: Path, meta: Dict[str, Dict[str, str]]) -> None:
    """Write _sync_meta.json to a table directory."""
    path = table_dir / "_sync_meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_fast.dumps(meta), encoding="utf-8")


def _is_download_root(path: Path) -> bool:
    """Check if path looks like a download root (has _settings.json or scope subdirs with tables)."""
    if (path / "_settings.json").exists():
        return True
    for child in path.iterdir():
        if child.is_dir():
            for table in SUPPORTED_TABLES:
                if (child / table / "_map.json").exists():
                    return True
    return False


def _resolve_local_path(path: Path) -> _ResolvedComponent:
    """Resolve a local file or widget directory to its ServiceNow component identity.

    Supported structures:
      .../sp_widget/<folder>/script.js        -> (sp_widget, field from filename)
      .../sp_widget/<folder>/                 -> (sp_widget, all editable fields)
      .../sp_angular_provider/<name>.script.js -> (sp_angular_provider, script)
      .../sys_script_include/<name>.script.js  -> (sys_script_include, script)
    """
    path = path.expanduser().resolve()

    # Case 1: widget directory
    if path.is_dir():
        table_dir = path.parent
        if table_dir.name != "sp_widget":
            raise ValueError(
                f"Directory push is only supported for widget folders under sp_widget/. "
                f"Got: {path}"
            )
        folder_name = path.name
        map_data = _read_map_json(table_dir)
        sys_id = map_data.get(folder_name)
        if not sys_id:
            raise ValueError(
                f"Widget '{folder_name}' not found in {table_dir / '_map.json'}. "
                f"Re-download sources first."
            )
        fields: Dict[str, Path] = {}
        for filename, field_name in WIDGET_FILE_FIELD_MAP.items():
            fpath = path / filename
            if fpath.exists():
                fields[field_name] = fpath
        if not fields:
            raise ValueError(f"No editable source files found in {path}")
        scope_root = table_dir.parent
        settings = _find_settings_json(scope_root)
        return _ResolvedComponent(
            table="sp_widget",
            sys_id=sys_id,
            name=folder_name,
            fields=fields,
            scope_root=scope_root,
            instance_url=settings.get("url", ""),
        )

    # Case 2: single file
    if not path.is_file():
        raise ValueError(f"Path does not exist: {path}")

    parent = path.parent
    grandparent = parent.parent

    # Widget file: .../sp_widget/<folder>/<filename>
    if grandparent.name == "sp_widget":
        table = "sp_widget"
        folder_name = parent.name
        table_dir = grandparent
        filename = path.name
        field_name = WIDGET_FILE_FIELD_MAP.get(filename)
        if not field_name:
            raise ValueError(
                f"Unknown widget file '{filename}'. "
                f"Supported: {', '.join(sorted(WIDGET_FILE_FIELD_MAP))}"
            )
        map_data = _read_map_json(table_dir)
        sys_id = map_data.get(folder_name)
        if not sys_id:
            raise ValueError(f"Widget '{folder_name}' not found in {table_dir / '_map.json'}")
        scope_root = table_dir.parent
        settings = _find_settings_json(scope_root)
        return _ResolvedComponent(
            table=table,
            sys_id=sys_id,
            name=folder_name,
            fields={field_name: path},
            scope_root=scope_root,
            instance_url=settings.get("url", ""),
        )

    # Provider or SI file: .../sp_angular_provider/<name>.script.js
    if parent.name in ("sp_angular_provider", "sys_script_include"):
        table = parent.name
        table_dir = parent
        stem = path.name
        if stem.endswith(".script.js"):
            component_name = stem[: -len(".script.js")]
        else:
            component_name = path.stem
        map_data = _read_map_json(table_dir)
        sys_id = _reverse_lookup_map(map_data, component_name)
        if not sys_id:
            raise ValueError(f"Component '{component_name}' not found in {table_dir / '_map.json'}")
        original_name = _reverse_lookup_name(map_data, component_name)
        scope_root = table_dir.parent
        settings = _find_settings_json(scope_root)
        return _ResolvedComponent(
            table=table,
            sys_id=sys_id,
            name=original_name or component_name,
            fields={"script": path},
            scope_root=scope_root,
            instance_url=settings.get("url", ""),
        )

    raise ValueError(
        f"Cannot resolve '{path}' to a ServiceNow component. "
        f"Expected path under sp_widget/, sp_angular_provider/, or sys_script_include/"
    )


def _reverse_lookup_map(map_data: Dict[str, str], safe_name: str) -> str | None:
    """Find sys_id by matching _safe_name(key) == safe_name."""
    for key, sys_id in map_data.items():
        if _safe_name(key) == safe_name or key == safe_name:
            return sys_id
    return None


def _reverse_lookup_name(map_data: Dict[str, str], safe_name: str) -> str | None:
    """Find original name key by matching _safe_name(key) == safe_name."""
    for key in map_data:
        if _safe_name(key) == safe_name or key == safe_name:
            return key
    return None


def _validate_instance_url(resolved: _ResolvedComponent, config: ServerConfig) -> None:
    """Ensure local files belong to the currently connected instance."""
    if resolved.instance_url and resolved.instance_url.rstrip("/") != config.instance_url.rstrip(
        "/"
    ):
        raise ValueError(
            f"Instance mismatch: local files are from '{resolved.instance_url}' "
            f"but current connection is '{config.instance_url}'. "
            f"Re-download from the correct instance first."
        )


def _batch_fetch_updated_on(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    sys_ids: List[str],
) -> Dict[str, str]:
    """Batch-fetch sys_updated_on for multiple sys_ids in one API call."""
    if not sys_ids:
        return {}
    result: Dict[str, str] = {}
    for i in range(0, len(sys_ids), 100):
        chunk = sys_ids[i : i + 100]
        query = f"sys_idIN{','.join(chunk)}"
        params = GenericQueryParams(
            table=table,
            query=query,
            fields="sys_id,sys_updated_on",
            limit=len(chunk),
            offset=0,
            display_value=False,
        )
        response = sn_query(config, auth_manager, params)
        for row in response.get("results") or []:
            sid = str(row.get("sys_id") or "")
            if sid:
                result[sid] = str(row.get("sys_updated_on") or "")
    return result


def _find_table_dirs(root: Path, table_name: str) -> List[Path]:
    """Find all directories containing _map.json for a given table under root."""
    found: List[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        candidate = child / table_name
        if candidate.is_dir() and (candidate / "_map.json").exists():
            found.append(candidate)
    direct = root / table_name
    if direct.is_dir() and (direct / "_map.json").exists() and direct not in found:
        found.append(direct)
    return found


def _scan_download_root(
    config: ServerConfig,
    auth_manager: AuthManager,
    root: Path,
) -> Dict[str, Any]:
    """Scan a download root directory and return change summary for all components."""
    settings = _find_settings_json(root)
    if settings.get("url") and settings["url"].rstrip("/") != config.instance_url.rstrip("/"):
        return {
            "error": (
                f"Instance mismatch: directory is from '{settings['url']}' "
                f"but current connection is '{config.instance_url}'"
            )
        }

    components: List[Dict[str, Any]] = []

    for table_name in sorted(SUPPORTED_TABLES):
        table_dirs = _find_table_dirs(root, table_name)
        for table_dir in table_dirs:
            map_data = _read_map_json(table_dir)
            sync_meta = _read_sync_meta(table_dir)
            if not map_data:
                continue

            all_sys_ids = list(map_data.values())
            remote_timestamps = _batch_fetch_updated_on(
                config, auth_manager, table_name, all_sys_ids
            )

            for name, sys_id in map_data.items():
                meta = sync_meta.get(name, {})
                local_updated_on = meta.get("sys_updated_on", "")
                downloaded_at = meta.get("downloaded_at", "")
                remote_updated_on = remote_timestamps.get(sys_id, "")
                has_sync_meta = bool(local_updated_on)

                if table_name == "sp_widget":
                    folder = table_dir / _safe_name(name)
                    local_files = [
                        str(folder / fn) for fn in WIDGET_FILE_FIELD_MAP if (folder / fn).exists()
                    ]
                else:
                    safe = _safe_name(name)
                    fpath = table_dir / f"{safe}.script.js"
                    local_files = [str(fpath)] if fpath.exists() else []

                if not local_files:
                    continue

                local_modified = False
                if downloaded_at:
                    try:
                        dl_time = datetime.fromisoformat(downloaded_at.replace("Z", "+00:00"))
                        for fp in local_files:
                            mtime = datetime.fromtimestamp(Path(fp).stat().st_mtime, tz=UTC)
                            if mtime > dl_time:
                                local_modified = True
                                break
                    except (ValueError, OSError):
                        pass

                remote_newer = (
                    has_sync_meta and remote_updated_on and remote_updated_on > local_updated_on
                )

                if remote_newer and local_modified:
                    status = "conflict"
                elif remote_newer:
                    status = "remote_newer"
                elif local_modified:
                    status = "local_modified"
                elif not has_sync_meta:
                    status = "unknown"
                else:
                    status = "unchanged"

                components.append(
                    {
                        "name": name,
                        "table": table_name,
                        "sys_id": sys_id,
                        "status": status,
                        "local_files": sorted(local_files),
                        "remote_updated_on": remote_updated_on,
                        "local_updated_on": local_updated_on,
                    }
                )

    status_counts: Dict[str, int] = {}
    for c in components:
        s = c["status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "mode": "scan",
        "directory": str(root),
        "instance": config.instance_url,
        "components": components,
        "summary": {"total": len(components), **status_counts},
    }


# ---------------------------------------------------------------------------
# Tool 1: diff_local_component
# ---------------------------------------------------------------------------
@register_tool(
    "diff_local_component",
    params=DiffLocalComponentParams,
    description=(
        "Compare local portal source files against remote ServiceNow. "
        "Give a download root directory for a compact change scan across all components. "
        "Give a specific file or widget folder for a detailed unified diff. "
        "Never dumps full source — only diffs and status summaries."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def diff_local_component(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: DiffLocalComponentParams,
) -> Dict[str, Any]:
    path = Path(params.path).expanduser().resolve()

    if not path.exists():
        return {"error": f"Path does not exist: {path}"}

    # Directory mode: if this is a download root, scan all components
    if path.is_dir() and _is_download_root(path):
        return _scan_download_root(config, auth_manager, path)

    # Component mode: detailed diff for a specific file or widget dir
    try:
        resolved = _resolve_local_path(path)
    except ValueError as e:
        return {"error": str(e)}

    try:
        _validate_instance_url(resolved, config)
    except ValueError as e:
        return {"error": str(e)}

    remote_fields = list(resolved.fields.keys()) + ["sys_updated_on"]
    try:
        remote_record = _fetch_portal_component_record(
            config, auth_manager, resolved.table, resolved.sys_id, remote_fields
        )
    except ValueError as e:
        return {"error": str(e)}

    table_dir = resolved.scope_root / resolved.table
    sync_meta = _read_sync_meta(table_dir)
    meta = sync_meta.get(resolved.name, {})
    local_updated_on = meta.get("sys_updated_on", "")
    remote_updated_on = str(remote_record.get("sys_updated_on") or "")
    conflict_warning = None
    if local_updated_on and remote_updated_on and remote_updated_on > local_updated_on:
        conflict_warning = (
            f"Remote was updated at {remote_updated_on}, "
            f"after your download (remote was {local_updated_on} at download time). "
            f"Someone else may have modified this component."
        )

    diffs: List[Dict[str, Any]] = []
    for field_name, file_path in resolved.fields.items():
        if not file_path.exists():
            continue
        local_content = file_path.read_text(encoding="utf-8")
        remote_content = str(remote_record.get(field_name) or "")

        if local_content == remote_content:
            diffs.append({"field": field_name, "status": "unchanged"})
            continue

        diff_lines = list(
            difflib.unified_diff(
                remote_content.splitlines(),
                local_content.splitlines(),
                fromfile=f"remote/{field_name}",
                tofile=f"local/{field_name}",
                lineterm="",
                n=params.context_lines,
            )
        )
        if len(diff_lines) > MAX_DIFF_LINES:
            diff_lines = diff_lines[:MAX_DIFF_LINES] + ["... [DIFF TRUNCATED FOR CONTEXT SAFETY]"]

        diffs.append(
            {
                "field": field_name,
                "status": "modified",
                "diff": "\n".join(diff_lines),
                "local_lines": len(local_content.splitlines()),
                "remote_lines": len(remote_content.splitlines()),
            }
        )

    return {
        "mode": "diff",
        "component": {
            "table": resolved.table,
            "sys_id": resolved.sys_id,
            "name": resolved.name,
        },
        "conflict_warning": conflict_warning,
        "diffs": diffs,
    }


# ---------------------------------------------------------------------------
# Tool 2: update_remote_from_local
# ---------------------------------------------------------------------------
@register_tool(
    "update_remote_from_local",
    params=PushLocalComponentParams,
    description=(
        "Push local file changes to ServiceNow. Auto-creates a snapshot of the "
        "remote state before pushing (for rollback). Refuses if remote has been "
        "modified since your download unless force=true."
    ),
    serialization="raw_dict",
    return_type=dict,
)
def update_remote_from_local(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: PushLocalComponentParams,
) -> Dict[str, Any]:
    path = Path(params.path).expanduser().resolve()

    try:
        resolved = _resolve_local_path(path)
    except ValueError as e:
        return {"error": str(e)}

    try:
        _validate_instance_url(resolved, config)
    except ValueError as e:
        return {"error": str(e)}

    # 1. Fetch remote content + sys_updated_on
    all_fields = list(resolved.fields.keys()) + ["sys_updated_on"]
    try:
        remote_record = _fetch_portal_component_record(
            config, auth_manager, resolved.table, resolved.sys_id, all_fields
        )
    except ValueError as e:
        return {"error": str(e)}

    # 2. Conflict check
    table_dir = resolved.scope_root / resolved.table
    sync_meta = _read_sync_meta(table_dir)
    meta = sync_meta.get(resolved.name, {})
    local_updated_on = meta.get("sys_updated_on", "")
    remote_updated_on = str(remote_record.get("sys_updated_on") or "")

    if local_updated_on and remote_updated_on and remote_updated_on > local_updated_on:
        if not params.force:
            return {
                "error": "CONFLICT",
                "message": (
                    "Remote has been modified since your download. "
                    "Use force=true to override, or re-download first."
                ),
                "remote_updated_on": remote_updated_on,
                "local_downloaded_on": local_updated_on,
                "component": {
                    "table": resolved.table,
                    "sys_id": resolved.sys_id,
                    "name": resolved.name,
                },
            }

    # 3. Build update_data from local files (only changed fields)
    update_data: Dict[str, str] = {}
    for field_name, file_path in resolved.fields.items():
        if not file_path.exists():
            continue
        local_content = file_path.read_text(encoding="utf-8")
        remote_content = str(remote_record.get(field_name) or "")
        if local_content != remote_content:
            update_data[field_name] = local_content

    if not update_data:
        return {
            "message": "No changes to push — local files match remote.",
            "component": {
                "table": resolved.table,
                "sys_id": resolved.sys_id,
                "name": resolved.name,
            },
        }

    # 4. Auto-snapshot remote state before push
    snapshot_path = None
    if not params.skip_snapshot:
        try:
            snapshot_path = _write_portal_component_snapshot(
                config,
                resolved.table,
                resolved.sys_id,
                remote_record,
                list(update_data.keys()),
            )
        except Exception as e:
            logger.warning("Failed to create pre-push snapshot: %s", e)

    # 5. Delegate to existing update_portal_component
    try:
        result = update_portal_component(
            config,
            auth_manager,
            UpdatePortalComponentParams(
                table=resolved.table,
                sys_id=resolved.sys_id,
                update_data=update_data,
            ),
        )
    except Exception as e:
        return {
            "error": f"Push failed: {e}",
            "snapshot": str(snapshot_path) if snapshot_path else None,
        }

    # 6. Update _sync_meta.json with new remote timestamp
    try:
        updated_record = _fetch_portal_component_record(
            config, auth_manager, resolved.table, resolved.sys_id, ["sys_updated_on"]
        )
        new_updated_on = str(updated_record.get("sys_updated_on") or "")
        now_iso = datetime.now(UTC).isoformat()
        full_sync_meta = _read_sync_meta(table_dir)
        full_sync_meta[resolved.name] = {
            "sys_id": resolved.sys_id,
            "sys_updated_on": new_updated_on,
            "downloaded_at": now_iso,
        }
        _write_sync_meta(table_dir, full_sync_meta)
    except Exception as e:
        logger.warning("Failed to update _sync_meta.json after push: %s", e)

    # 7. Enrich result
    result["local_sync"] = {
        "pushed_from": str(path),
        "fields_pushed": list(update_data.keys()),
        "snapshot": str(snapshot_path) if snapshot_path else None,
        "sync_meta_updated": True,
    }
    return result
