"""
Local source synchronization tools for ServiceNow MCP.
Diff and push locally edited portal sources back to ServiceNow
with conflict detection.
"""

import difflib
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils import json_fast
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .portal_tools import (
    UpdatePortalComponentParams,
    _fetch_portal_component_record,
    _safe_name,
    update_portal_component,
)
from .push_safety import assess_push_risk, describe_attribution
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

TABLE_FILE_FIELD_MAP: Dict[str, Dict[str, str]] = {
    "sp_widget": WIDGET_FILE_FIELD_MAP,
    "sp_angular_provider": {".script.js": "script"},
    "sys_script_include": {".script.js": "script"},
    # Business Rules are folder-based: behaviour lives across script + condition,
    # so a single-file model can't round-trip the condition the way SIs can.
    "sys_script": {"script.js": "script", "condition.js": "condition"},
    "sp_header_footer": {
        "template.html": "template",
        "css.scss": "css",
    },
    "sp_css": {".css.scss": "css"},
    "sp_ng_template": {".template.html": "template"},
    "sys_ui_page": {
        "html.html": "html",
        "client_script.js": "client_script",
        "processing_script.js": "processing_script",
    },
}

FOLDER_TABLES: Set[str] = {"sp_widget", "sp_header_footer", "sys_ui_page", "sys_script"}
SINGLE_FILE_TABLES: Set[str] = {
    "sp_angular_provider",
    "sys_script_include",
    "sp_css",
    "sp_ng_template",
}

# The downloaders (download_app_sources / download_portal_sources) always write
# a folder per record — <table>/<name>/<field>.<ext> — even for the tables we
# historically pushed as a single flat "<name>.<suffix>" file. That divergence
# is why a freshly downloaded provider/SI tree could not be pushed by local
# path and forced a record-lookup + update_code fallback. Accept the folder
# layout these tables actually ship in; the flat layout stays supported for
# back-compat. Both writer conventions for client_script are tolerated.
SINGLE_FILE_FOLDER_FIELD_MAP: Dict[str, Dict[str, str]] = {
    "sp_angular_provider": {
        "script.js": "script",
        "client_script.client.js": "client_script",
        "client_script.js": "client_script",
    },
    "sys_script_include": {"script.js": "script"},
    "sp_css": {"css.scss": "css"},
    "sp_ng_template": {"template.html": "template"},
}


def _folder_layout_field_map(table_name: str) -> Optional[Dict[str, str]]:
    """Return the on-disk ``filename -> field`` map for a table's FOLDER layout.

    Folder tables use their real-filename entries from TABLE_FILE_FIELD_MAP
    (the suffix-style ".xxx" keys belong to the flat single-file layout and are
    skipped). Single-file tables use the folder map above. Returns None for an
    unknown table so callers can fall through to flat-layout handling.
    """
    if table_name in FOLDER_TABLES:
        return {
            fn: field
            for fn, field in TABLE_FILE_FIELD_MAP.get(table_name, {}).items()
            if not fn.startswith(".")
        }
    if table_name in SINGLE_FILE_TABLES:
        return SINGLE_FILE_FOLDER_FIELD_MAP.get(table_name, {})
    return None


SUPPORTED_TABLES: Set[str] = {
    "sp_widget",
    "sp_angular_provider",
    "sys_script_include",
    "sys_script",
    "sp_header_footer",
    "sp_css",
    "sp_ng_template",
    "sys_ui_page",
}

MAX_DIFF_LINES = 120


def _normalize_for_compare(text: str) -> str:
    """Line-ending–insensitive view of *text* for change detection.

    ServiceNow normalizes EOLs on store, so a CRLF<->LF-only delta is NOT a real
    change. A raw ``local == remote`` check is byte-sensitive and would flag such
    a delta as 'modified' — yet the rendered diff uses ``splitlines()`` (which
    collapses EOL differences), so it comes back EMPTY. That mismatch produced the
    phantom "status: modified, diff: '', local_lines == remote_lines" report.
    Comparing on the same ``splitlines()`` basis the diff uses keeps the two
    consistent and stops phantom pushes of pure line-ending noise.
    """
    return "\n".join(text.splitlines())


# ---------------------------------------------------------------------------
# Pydantic Parameter Models
# ---------------------------------------------------------------------------
class DiffLocalComponentParams(BaseModel):
    """Parameters for diffing local source files against remote ServiceNow."""

    path: str = Field(
        default=...,
        description="Local file, widget dir, or download root (file→diff, root→summary).",
    )
    context_lines: int = Field(
        default=3,
        description="Number of context lines in unified diff output (default 3)",
    )


class PushLocalComponentParams(BaseModel):
    """Parameters for pushing local file changes to ServiceNow."""

    path: str = Field(
        default=...,
        description="Local path from a download; <table>/<name>/<file> folder layout.",
    )
    force: bool = Field(
        default=False,
        description="Override a conflict (remote changed since download) and push anyway. Default false.",
    )
    cross_instance_deploy: bool = Field(
        default=False,
        description="Deploy local source to a DIFFERENT instance than its origin; target record re-resolved by name.",
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


def _find_manifest_json(start: Path) -> Dict[str, Any]:
    """Walk up from *start* looking for _manifest.json. Return parsed content."""
    current = start if start.is_dir() else start.parent
    for _ in range(10):
        candidate = current / "_manifest.json"
        if candidate.exists():
            try:
                return json_fast.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
        parent = current.parent
        if parent == current:
            break
        current = parent
    return {}


def _resolve_origin_url(scope_root: Path) -> str:
    """Best-effort origin instance URL for a downloaded source tree.

    Portal downloads record it in _settings.json ('url'); app-source downloads
    record it in _manifest.json ('instance'). Prefer settings, fall back to the
    manifest so app-only downloads are still provenance-checked against the push
    target. Empty when neither file records an origin (push proceeds with a
    warning rather than a hard block)."""
    settings = _find_settings_json(scope_root)
    url = str(settings.get("url") or "").strip()
    if url:
        return url
    manifest = _find_manifest_json(scope_root)
    return str(manifest.get("instance") or "").strip()


# Surfaced (not raised) when a local source has no recorded origin instance.
# Provenance-less trees can't be cross-checked, so the push is allowed but the
# response flags that the target couldn't be verified.
_ORIGIN_UNVERIFIED_MSG = (
    "Origin instance not recorded for this local source (no _settings.json or "
    "_manifest.json found). Could not confirm it was downloaded from the instance "
    "being written to. Re-download to record provenance if unsure."
)


def _read_sync_meta(table_dir: Path) -> Dict[str, Dict[str, str]]:
    """Read _sync_meta.json from a table directory. Returns empty dict if missing."""
    path = table_dir / "_sync_meta.json"
    if not path.exists():
        return {}
    try:
        data = json_fast.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        # ValueError covers both stdlib json.JSONDecodeError and orjson.JSONDecodeError.
        return {}


def _read_map_json(table_dir: Path) -> Dict[str, str]:
    """Read _map.json from a table directory. Returns empty dict if missing."""
    path = table_dir / "_map.json"
    if not path.exists():
        return {}
    try:
        data = json_fast.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
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
    """Resolve a local file or directory to its ServiceNow component identity.

    Folder layout (what the downloaders write for EVERY table — <table>/<name>/<file>):
      .../sp_widget/<folder>/script.js            -> (sp_widget, script)
      .../sp_angular_provider/<name>/script.js    -> (sp_angular_provider, script)
      .../sys_script_include/<name>/script.js     -> (sys_script_include, script)

    Flat layout (legacy single-file, still accepted for back-compat):
      .../sp_angular_provider/<name>.script.js    -> (sp_angular_provider, script)
      .../sp_css/<name>.css.scss                  -> (sp_css, css)
      .../sp_ng_template/<name>.template.html     -> (sp_ng_template, template)
    """
    path = path.expanduser().resolve()

    # Case 1: Directory -> a record folder (<table>/<name>/) in either a
    # folder-based table or a single-file table downloaded in folder layout.
    if path.is_dir():
        table_dir = path.parent
        table_name = table_dir.name
        file_field_map = _folder_layout_field_map(table_name)
        if file_field_map is None:
            raise ValueError(
                f"Directory push is only supported for known tables "
                f"({', '.join(sorted(FOLDER_TABLES | SINGLE_FILE_TABLES))}). "
                f"Got: {table_name}"
            )
        folder_name = path.name
        map_data = _read_map_json(table_dir)
        # _map.json keys are original names; folder names are _safe_name(original).
        # Fall back to reverse lookup so "My Widget [v2]" → "My_Widget_v2" still resolves.
        sys_id = map_data.get(folder_name) or _reverse_lookup_map(map_data, folder_name)
        if not sys_id:
            raise ValueError(
                f"Component '{folder_name}' not found in {table_dir / '_map.json'}. "
                f"Re-download sources first."
            )
        fields: Dict[str, Path] = {}
        for filename, field_name in file_field_map.items():
            fpath = path / filename
            if fpath.exists():
                fields[field_name] = fpath
        if not fields:
            raise ValueError(f"No editable source files found in {path}")
        scope_root = table_dir.parent
        return _ResolvedComponent(
            table=table_name,
            sys_id=sys_id,
            name=folder_name,
            fields=fields,
            scope_root=scope_root,
            instance_url=_resolve_origin_url(scope_root),
        )

    # Case 2: File
    if not path.is_file():
        raise ValueError(f"Path does not exist: {path}")

    parent = path.parent
    grandparent = parent.parent

    # Case 2a: File inside a record folder (<table>/<name>/<file>) — folder-based
    # tables AND single-file tables downloaded in folder layout.
    #   e.g. .../sp_widget/<folder>/script.js
    #   e.g. .../sp_angular_provider/<name>/script.js   (folder layout)
    if _folder_layout_field_map(grandparent.name) is not None:
        table_name = grandparent.name
        folder_name = parent.name
        table_dir = grandparent
        filename = path.name
        file_field_map = _folder_layout_field_map(table_name) or {}
        _field_name_opt = file_field_map.get(filename)
        if not _field_name_opt:
            supported = ", ".join(sorted(file_field_map))
            raise ValueError(f"Unknown file '{filename}' for {table_name}. Supported: {supported}")
        field_name = _field_name_opt
        map_data = _read_map_json(table_dir)
        sys_id = map_data.get(folder_name) or _reverse_lookup_map(map_data, folder_name)
        if not sys_id:
            raise ValueError(f"Component '{folder_name}' not found in {table_dir / '_map.json'}")
        scope_root = table_dir.parent
        return _ResolvedComponent(
            table=table_name,
            sys_id=sys_id,
            name=folder_name,
            fields={field_name: path},
            scope_root=scope_root,
            instance_url=_resolve_origin_url(scope_root),
        )

    # Case 2b: Single file in a single-file table directory
    #   e.g. .../sp_angular_provider/<name>.script.js
    #   e.g. .../sp_css/<name>.css.scss
    if parent.name in SINGLE_FILE_TABLES:
        table_name = parent.name
        table_dir = parent
        stem = path.name

        file_field_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
        matched_field = None
        component_name = None
        for suffix_pattern, field_name in file_field_map.items():
            if suffix_pattern.startswith(".") and stem.endswith(suffix_pattern):
                matched_field = field_name
                component_name = stem[: -len(suffix_pattern)]
                break

        if not matched_field or not component_name:
            raise ValueError(
                f"Cannot parse filename '{stem}' for table {table_name}. "
                f"Expected suffix: {', '.join(file_field_map.keys())}"
            )

        map_data = _read_map_json(table_dir)
        sys_id = _reverse_lookup_map(map_data, component_name)
        if not sys_id:
            raise ValueError(f"Component '{component_name}' not found in {table_dir / '_map.json'}")
        original_name = _reverse_lookup_name(map_data, component_name)
        scope_root = table_dir.parent
        return _ResolvedComponent(
            table=table_name,
            sys_id=sys_id,
            name=original_name or component_name,
            fields={matched_field: path},
            scope_root=scope_root,
            instance_url=_resolve_origin_url(scope_root),
        )

    raise ValueError(
        f"Cannot resolve '{path}' to a ServiceNow component.\n"
        f"Expected layout:\n"
        f"  - Folder layout (as downloaded, all tables): <table>/<name>/<file>\n"
        f"    e.g. sp_widget/<name>/script.js, sp_angular_provider/<name>/script.js\n"
        f"  - Flat layout (legacy single-file): <table>/<name>.<suffix> for "
        f"{', '.join(sorted(SINGLE_FILE_TABLES))}\n"
        f"    e.g. sp_angular_provider/<name>.script.js\n"
        f"Tip: run diff_local_component on the parent scope dir to list "
        f"actual file paths that exist locally."
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


def _resolve_target_by_name(
    config: ServerConfig, auth_manager: AuthManager, table: str, name: str
) -> List[Dict[str, str]]:
    """Look up a record on the TARGET instance by its name — used for
    cross-instance deploy so we push to the target's OWN sys_id instead of the
    origin's (which may not exist / may be a different record on the target). The
    name is the stable identity across instances; returns all matches so the
    caller can require exactly one (0 = not there, >1 = ambiguous)."""
    safe_name = name.replace("^", "").replace("=", "")
    try:
        resp = sn_query(
            config,
            auth_manager,
            GenericQueryParams(
                table=table,
                query=f"name={safe_name}",
                fields="sys_id,name",
                limit=5,
                offset=0,
                display_value=False,
            ),
        )
        rows = resp.get("results", []) if isinstance(resp, dict) else []
    except Exception:
        logger.debug("Target name lookup failed for %s name=%s", table, name, exc_info=True)
        return []
    return [r for r in rows if isinstance(r, dict)]


def _push_actor_username(config: ServerConfig, auth_manager: AuthManager) -> str:
    """Best-effort current user_name, in the same string form ServiceNow stores
    in ``sys_updated_by`` — so a push can tell 'my own later edit' from 'someone
    else changed it'.

    The configured username lives on the ACTIVE sub-config (basic/oauth/browser),
    not on AuthConfig itself. Empty when unknown (e.g. api_key, or SSO browser
    auth with no configured username) — and that's deliberately safe: an unknown
    'me' makes any identified remote editor compare as 'not me', so the stronger
    cross-user gate applies rather than letting force silently overwrite."""
    auth = getattr(config, "auth", None)
    for sub in ("basic", "oauth", "browser"):
        name = getattr(getattr(auth, sub, None), "username", None)
        if name:
            return str(name).strip()
    # Fallbacks: a top-level username (test doubles) or the auth manager.
    return str(
        getattr(auth, "username", None) or getattr(auth_manager, "username", None) or ""
    ).strip()


# Live current-user, cached per instance. Successes only (a transient failure
# retries next push instead of permanently hedging).
_CURRENT_USER_CACHE: Dict[str, str] = {}


def _resolve_current_user(config: ServerConfig, auth_manager: AuthManager) -> str:
    """Ask the live session who it is: GET /api/now/ui/user/current_user.

    A valid session always knows its user (it's how the UI greets you), so an
    SSO/browser login with no configured username is still identifiable — we just
    ask the server. Cheap, cached. '' on any failure → caller hedges, never
    falsely accuses.
    """
    base = config.instance_url.rstrip("/")
    cached = _CURRENT_USER_CACHE.get(base)
    if cached:
        return cached
    name = ""
    try:
        response = auth_manager.make_request(
            "GET", f"{base}/api/now/ui/user/current_user", timeout=config.timeout
        )
        payload = response.json() if hasattr(response, "json") else {}
        result = payload.get("result", payload) if isinstance(payload, dict) else {}
        if isinstance(result, dict):
            name = str(result.get("user_name") or result.get("name") or "").strip()
    except Exception as exc:  # noqa: BLE001 - identity is best-effort
        logger.debug("current_user lookup failed: %s", exc)
    if name:
        _CURRENT_USER_CACHE[base] = name
    return name


def _resolve_push_actor(config: ServerConfig, auth_manager: AuthManager) -> tuple:
    """Return (username, confirmed). The configured username or a live session
    lookup are both trusted identities. Only when BOTH fail do we return
    ('', False) so the push gate HEDGES instead of blaming a coworker."""
    name = _push_actor_username(config, auth_manager)
    if name:
        return name, True
    live = _resolve_current_user(config, auth_manager)
    if live:
        return live, True
    return "", False


def _validate_instance_url(resolved: _ResolvedComponent, config: ServerConfig) -> None:
    """Ensure local files belong to the instance this write will hit.

    On a mismatch, the local file records WHERE it came from, so the fix is not
    "re-download" — it's "push it back to that origin". Guide the caller to the
    single safe target: the cross-instance write gate (instance + confirm_instance).
    """
    if resolved.instance_url and resolved.instance_url.rstrip("/") != config.instance_url.rstrip(
        "/"
    ):
        origin = resolved.instance_url.rstrip("/")
        active = config.instance_url.rstrip("/")
        raise ValueError(
            f"Instance mismatch: this local component is from '{origin}', but the active "
            f"instance is '{active}' — operating against the active one targets the WRONG "
            f"instance, so it's blocked. The local file records its origin, so route the "
            f"call to it (alias for '{origin}' — see list_instances): for a read/diff pass "
            f"instance=<alias>; for a push pass instance=<alias> confirm_instance=<alias> "
            f"confirm='approve' (scope is aligned automatically). Do NOT edit config or "
            f"re-download just to change the target."
        )


def _display_str(value: Any) -> str:
    """Readable string from a field that may be a {'value','display_value'} dict
    (display_value preferred) or a plain string."""
    if isinstance(value, dict):
        return str(value.get("display_value") or value.get("value") or "")
    return str(value or "")


def _active_update_sets(
    config: ServerConfig, auth_manager: AuthManager, scope_value: str
) -> List[Dict[str, str]]:
    """Best-effort: in-progress update sets in a scope, with their owners.

    Surfaces who may be holding the update set when a push is rejected. Returns
    [] on any error (read ACL, bad scope, etc.) so it never masks the original
    failure. scope_value is the component's sys_scope sys_id.
    """
    if not scope_value:
        return []
    try:
        resp = sn_query(
            config,
            auth_manager,
            GenericQueryParams(
                table="sys_update_set",
                query=f"state=in progress^application={scope_value}",
                fields="name,sys_created_by,sys_updated_by,sys_updated_on",
                limit=10,
                offset=0,
                display_value=True,
            ),
        )
    except Exception as exc:
        logger.warning("Could not fetch active update sets: %s", exc)
        return []
    return [
        {
            "name": _display_str(row.get("name")),
            "created_by": _display_str(row.get("sys_created_by")),
            "updated_by": _display_str(row.get("sys_updated_by")),
            "updated_on": _display_str(row.get("sys_updated_on")),
        }
        for row in (resp.get("results") or [])
    ]


def _batch_fetch_updated_on(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    sys_ids: List[str],
) -> Dict[str, Dict[str, str]]:
    """Batch-fetch sys_updated_on + sys_updated_by for many sys_ids.

    Returns {sys_id: {"on": <timestamp>, "by": <user_name>}}. The "by" surfaces
    who last changed the remote — directly useful when a diff reports drift.
    """
    if not sys_ids:
        return {}
    result: Dict[str, Dict[str, str]] = {}
    for i in range(0, len(sys_ids), 100):
        chunk = sys_ids[i : i + 100]
        query = f"sys_idIN{','.join(chunk)}"
        params = GenericQueryParams(
            table=table,
            query=query,
            fields="sys_id,sys_updated_on,sys_updated_by",
            limit=len(chunk),
            offset=0,
            display_value=False,
        )
        response = sn_query(config, auth_manager, params)
        for row in response.get("results") or []:
            sid = str(row.get("sys_id") or "")
            if sid:
                result[sid] = {
                    "on": str(row.get("sys_updated_on") or ""),
                    "by": _display_str(row.get("sys_updated_by")),
                }
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
    origin_url = _resolve_origin_url(root)
    if origin_url and origin_url.rstrip("/") != config.instance_url.rstrip("/"):
        return {
            "error": (
                f"Instance mismatch: directory is from '{origin_url}' "
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
            remote_meta = _batch_fetch_updated_on(config, auth_manager, table_name, all_sys_ids)

            for name, sys_id in map_data.items():
                meta = sync_meta.get(name, {})
                local_updated_on = meta.get("sys_updated_on", "")
                downloaded_at = meta.get("downloaded_at", "")
                rmeta = remote_meta.get(sys_id, {})
                remote_updated_on = rmeta.get("on", "")
                remote_updated_by = rmeta.get("by", "")
                has_sync_meta = bool(local_updated_on)

                # Folder layout (<table>/<name>/<field>.<ext>) is what the
                # downloaders write for every table, so check it first. Single-
                # file tables also accept the historical flat "<name>.<suffix>".
                safe = _safe_name(name)
                folder = table_dir / safe
                folder_map = _folder_layout_field_map(table_name) or {}
                local_files = [str(folder / fn) for fn in folder_map if (folder / fn).exists()]
                if not local_files and table_name in SINGLE_FILE_TABLES:
                    flat_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
                    for suffix_pattern in flat_map:
                        if suffix_pattern.startswith("."):
                            fpath = table_dir / f"{safe}{suffix_pattern}"
                            if fpath.exists():
                                local_files.append(str(fpath))

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

                component = {
                    "name": name,
                    "table": table_name,
                    "sys_id": sys_id,
                    "status": status,
                    "local_files": sorted(local_files),
                    "remote_updated_on": remote_updated_on,
                    "local_updated_on": local_updated_on,
                }
                # Surface who last changed the remote only on drift (token economy).
                if remote_updated_by and status in ("conflict", "remote_newer"):
                    component["remote_updated_by"] = remote_updated_by
                components.append(component)

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
    description="Diff local edits vs remote. Run before update_remote_from_local (review) or re-download (freshness).",
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

    remote_fields = list(resolved.fields.keys()) + [
        "sys_updated_on",
        "sys_updated_by",
        "sys_created_by",
    ]
    try:
        remote_record = _fetch_portal_component_record(
            config, auth_manager, resolved.table, resolved.sys_id, remote_fields, full=True
        )
    except ValueError as e:
        return {"error": str(e)}

    table_dir = resolved.scope_root / resolved.table
    sync_meta = _read_sync_meta(table_dir)
    meta = sync_meta.get(resolved.name, {})
    local_updated_on = meta.get("sys_updated_on", "")
    remote_updated_on = str(remote_record.get("sys_updated_on") or "")
    # sys_updated_by is a string (user_name) field — readable as-is.
    remote_updated_by = _display_str(remote_record.get("sys_updated_by"))
    # Free attribution corroboration (same fetch + local baseline) so a handoff /
    # spoofed editor is visible at REVIEW time, before any push. No extra API.
    attribution = describe_attribution(
        baseline_by=meta.get("sys_updated_by", ""),
        current_by=remote_updated_by,
        created_by=_display_str(remote_record.get("sys_created_by")),
    )
    conflict_warning = None
    if local_updated_on and remote_updated_on and remote_updated_on > local_updated_on:
        by = f" by {remote_updated_by}" if remote_updated_by else ""
        conflict_warning = (
            f"Changed on the server at {remote_updated_on}{by}, after your download "
            f"(your copy is from {local_updated_on}). Someone edited it since you "
            f"downloaded — review before pushing."
        )

    diffs: List[Dict[str, Any]] = []
    for field_name, file_path in resolved.fields.items():
        if not file_path.exists():
            continue
        local_content = file_path.read_text(encoding="utf-8")
        remote_content = str(remote_record.get(field_name) or "")

        # Compare on a line-ending–normalized basis (same as the diff render) so a
        # pure CRLF<->LF delta is not reported as a phantom "modified".
        if _normalize_for_compare(local_content) == _normalize_for_compare(remote_content):
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

    result: Dict[str, Any] = {
        "mode": "diff",
        "component": {
            "table": resolved.table,
            "sys_id": resolved.sys_id,
            "name": resolved.name,
        },
        "conflict_warning": conflict_warning,
        "diffs": diffs,
    }
    # Surface attribution only when it's NOT plain-consistent — token-lean: a
    # clean record adds nothing, a handoff/shared one shows the evidence.
    if attribution["attribution"] != "consistent":
        result["attribution"] = attribution
    if conflict_warning and remote_updated_by:
        result["remote_updated_by"] = remote_updated_by
    if not resolved.instance_url:
        result["origin_unverified"] = _ORIGIN_UNVERIFIED_MSG
    return result


def _build_update_data_and_magnitude(resolved, remote_record):
    """Local-only: changed fields + (changed_lines, total_lines) for risk scoring.

    No network. Line-ending normalized so a pure CRLF<->LF delta is neither
    pushed nor counted as a change. changed_lines approximates the edit size via
    difflib opcodes (added/removed lines per modified field).
    """
    update_data: Dict[str, str] = {}
    changed_lines = 0
    total_lines = 0
    for field_name, file_path in resolved.fields.items():
        remote_content = str(remote_record.get(field_name) or "")
        total_lines += len(remote_content.splitlines())
        if not file_path.exists():
            continue
        local_content = file_path.read_text(encoding="utf-8")
        if _normalize_for_compare(local_content) != _normalize_for_compare(remote_content):
            update_data[field_name] = local_content
            matcher = difflib.SequenceMatcher(
                None, remote_content.splitlines(), local_content.splitlines()
            )
            changed_lines += sum(
                max(i2 - i1, j2 - j1)
                for tag, i1, i2, j1, j2 in matcher.get_opcodes()
                if tag != "equal"
            )
    return update_data, changed_lines, total_lines


# ---------------------------------------------------------------------------
# Tool 2: update_remote_from_local
# ---------------------------------------------------------------------------
@register_tool(
    "update_remote_from_local",
    params=PushLocalComponentParams,
    description="Push local edits to ServiceNow. Run diff_local_component first to review.",
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

    # Cross-instance deploy gate. Local source records its origin instance; when
    # the push target differs, we do NOT blindly trust the origin's sys_id (it may
    # be absent or a DIFFERENT record on the target). Instead, with explicit
    # opt-in, re-resolve the target record BY NAME on the target instance and push
    # to its own sys_id — works whether or not the two instances share sys_ids,
    # and never touches the wrong record (0/many matches stop it). Without opt-in,
    # inform rather than hard-wall (don't force a re-download).
    origin = (resolved.instance_url or "").rstrip("/")
    active = config.instance_url.rstrip("/")
    is_cross_instance = bool(origin and origin != active)
    cross_instance_deploy = False

    if is_cross_instance:
        if not params.cross_instance_deploy:
            return {
                "error": "CROSS_INSTANCE",
                "message": (
                    f"Local source is from '{origin}', but the target is '{active}'. To deploy "
                    f"across instances pass cross_instance_deploy=true — the target record is "
                    f"re-resolved BY NAME on '{active}' (its own sys_id), so it works whether or "
                    f"not the instances share sys_ids and never hits the wrong record. (Or "
                    f"re-download from '{active}' to edit it there directly.)"
                ),
                "origin_instance": origin,
                "target_instance": active,
                "component": {"table": resolved.table, "name": resolved.name},
            }
        matches = _resolve_target_by_name(config, auth_manager, resolved.table, resolved.name)
        if not matches:
            return {
                "error": "TARGET_NOT_FOUND",
                "message": (
                    f"No '{resolved.name}' record found on '{active}' ({resolved.table}). "
                    f"Cross-instance deploy updates an existing record only — it never creates."
                ),
                "component": {"table": resolved.table, "name": resolved.name},
            }
        if len(matches) > 1:
            return {
                "error": "TARGET_AMBIGUOUS",
                "message": (
                    f"{len(matches)} records named '{resolved.name}' on '{active}' "
                    f"({resolved.table}) — can't pick the deploy target unambiguously."
                ),
                "candidates": [{"sys_id": m.get("sys_id"), "name": m.get("name")} for m in matches],
            }
        # Rebind to the TARGET's own sys_id (new object — never mutate resolved).
        resolved = _ResolvedComponent(
            resolved.table,
            str(matches[0].get("sys_id") or ""),
            resolved.name,
            resolved.fields,
            resolved.scope_root,
            active,
        )
        cross_instance_deploy = True
    else:
        try:
            _validate_instance_url(resolved, config)
        except ValueError as e:
            return {"error": str(e)}

    # 1. Fetch remote content + sys_updated_on (+ sys_scope so we can align the
    #    session scope before writing — see the pre-write scope alignment below).
    all_fields = list(resolved.fields.keys()) + [
        "sys_updated_on",
        "sys_updated_by",
        "sys_created_by",
        "sys_scope",
    ]
    try:
        remote_record = _fetch_portal_component_record(
            config, auth_manager, resolved.table, resolved.sys_id, all_fields
        )
    except ValueError as e:
        return {"error": str(e)}

    # 2. Baseline-drift verification gate — TIME-INDEPENDENT. Compares the remote's
    #    CURRENT sys_updated_on against the value recorded in _sync_meta at
    #    download, so it surfaces an overwrite whether it happened 3 minutes or 3
    #    DAYS after your download (the 10-min concurrent-edit window can't). The
    #    point is VERIFICATION, not a hard block: it stops a blind push by showing
    #    WHO changed it and WHEN, so force=true is a deliberate "yes, overwrite
    #    that" — never silent. force overrides either case; CONFLICT_OTHER_USER
    #    just makes "this is someone else's edit" loud. (Pushing to the wrong
    #    INSTANCE is the separate, hard _validate_instance_url block above.)
    table_dir = resolved.scope_root / resolved.table
    sync_meta = _read_sync_meta(table_dir)
    meta = sync_meta.get(resolved.name, {})
    local_updated_on = meta.get("sys_updated_on", "")
    remote_updated_on = str(remote_record.get("sys_updated_on") or "")
    remote_updated_by = str(remote_record.get("sys_updated_by") or "").strip()
    # Resolve WHO we are with confidence. A live session knows its user, so when
    # the configured username is absent (SSO/browser) we ASK the server rather
    # than guess — only a genuine resolution failure leaves identity unconfirmed.
    me, me_confirmed = _resolve_push_actor(config, auth_manager)

    # The baseline lives in _sync_meta from the ORIGIN download, so it's only
    # meaningful for a same-instance round-trip. For a cross-instance deploy the
    # target was re-resolved by name (already verified), so skip the drift gate.
    drifted = not cross_instance_deploy and bool(
        local_updated_on and remote_updated_on and remote_updated_on > local_updated_on
    )

    # Local-only magnitude + deterministic risk score. Built BEFORE the gate so a
    # blocked push and a forced push both surface the same "what you're about to
    # overwrite" picture. No network here — keeps the gate's no-network invariant.
    update_data, _changed_lines, _total_lines = _build_update_data_and_magnitude(
        resolved, remote_record
    )
    risk = assess_push_risk(
        me=me,
        remote_updated_by=remote_updated_by,
        drifted=drifted,
        changed_lines=_changed_lines,
        total_lines=_total_lines,
        me_confirmed=me_confirmed,
        # Free corroboration from the SAME fetch + the local download baseline:
        # who created it, and who owned it when you downloaded. No extra API.
        baseline_by=meta.get("sys_updated_by", ""),
        created_by=str(remote_record.get("sys_created_by") or "").strip(),
    )
    # CONFLICT_OTHER_USER is asserted ONLY when identity is confirmed AND differs
    # — never on an unconfirmed guess (that was the false "someone else committed
    # your update set" bug). Unconfirmed-but-drifted still blocks as CONFLICT.
    confirmed_other = risk["other_user"]

    if drifted:
        if not params.force:
            component_info = {
                "table": resolved.table,
                "sys_id": resolved.sys_id,
                "name": resolved.name,
            }
            error_code = "CONFLICT_OTHER_USER" if confirmed_other else "CONFLICT"
            message = (
                f"{risk['message']} (server: {remote_updated_on}, your copy: {local_updated_on}). "
                f"Use force=true to push anyway, or re-download to get the latest first."
            )
            return {
                "error": error_code,
                "message": message,
                "risk": risk,
                "remote_updated_by": remote_updated_by,
                "remote_updated_on": remote_updated_on,
                "local_downloaded_on": local_updated_on,
                "component": component_info,
            }
        if confirmed_other:
            logger.warning(
                "force=true overwriting %s's edit on %s/%s (%s, updated %s)",
                remote_updated_by,
                resolved.table,
                resolved.name,
                resolved.sys_id,
                remote_updated_on,
            )

    # 3. update_data was built above (with the magnitude used for risk scoring).
    if not update_data:
        return {
            "message": "No changes to push — local files match remote.",
            "component": {
                "table": resolved.table,
                "sys_id": resolved.sys_id,
                "name": resolved.name,
            },
        }

    # 3b. Align the session scope to the component's scope BEFORE writing. A REST
    # write to a scoped record is rejected (403 cross-scope) when the session's
    # current app is a different scope — even though the same user can save it in
    # the in-scope UI. The component's scope is known from the record we just
    # read, so set it proactively (browser auth only; best-effort — if it can't
    # switch, the write still attempts and the 403 path below explains why).
    from servicenow_mcp.tools.session_context_tools import _is_browser_auth, set_application_scope

    if _is_browser_auth(config):
        sc = remote_record.get("sys_scope")
        scope_sys_id = str(sc.get("value") or "") if isinstance(sc, dict) else str(sc or "")
        if scope_sys_id:
            switched = set_application_scope(config, auth_manager, scope_sys_id)
            if not switched.get("success"):
                logger.info(
                    "Pre-write scope align to %s did not confirm: %s",
                    scope_sys_id,
                    switched.get("error"),
                )

    # 4. Delegate to existing update_portal_component
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
            "success": False,
            "error": f"Push failed: {e}",
        }

    # 4b. ServiceNow-side rejection: update_portal_component returns an error
    # dict on HTTP >= 400 (it does NOT raise). Treat that as a failure — do NOT
    # update _sync_meta (a poisoned meta makes the next diff falsely report "no
    # drift", hiding that the remote never changed), and return actionable
    # guidance instead of a bare ACL string the caller has to guess at.
    status = result.get("status")
    if result.get("error") or (isinstance(status, int) and status >= 400):
        detail = str(result.get("error", "")).lower()
        is_acl = status == 403 or "acl" in detail or "security constraint" in detail

        # For ACL/403, internally resolve who holds the scope's in-progress update
        # set(s) so the caller sees the likely culprit without a manual lookup.
        active_sets: List[Dict[str, str]] = []
        if is_acl:
            scope_value = ""
            try:
                rec = _fetch_portal_component_record(
                    config, auth_manager, resolved.table, resolved.sys_id, ["sys_scope"]
                )
                sc = rec.get("sys_scope")
                scope_value = str(sc.get("value") or "") if isinstance(sc, dict) else str(sc or "")
            except Exception as exc:
                logger.warning("Could not resolve component scope for 403 diagnosis: %s", exc)
            active_sets = _active_update_sets(config, auth_manager, scope_value)

        if is_acl:
            hint = (
                "HTTP 403 ACL Exception — the write reached ServiceNow but was rejected. "
                "Likely causes, in order: (1) the target update set is locked, closed, or "
                "held by another user (see active_update_sets below for owners); (2) the "
                "account lacks sp_admin / write ACL on this table — verify roles via sn_health; "
                "(3) scoped-app protection or wrong scope. Local files and _sync_meta are "
                "UNCHANGED — free/switch the update set (or use a privileged session), then retry."
            )
            # Service Portal tables carry protections BEYOND the table role ACL.
            # The user's account can hold sp_admin and the update set can be open,
            # yet a Table-API write to an sp_* script field still 403s because the
            # request lacks the SP Designer context (Referer/source check) or the
            # record/field has an instance-specific protection policy or
            # condition-scripted field ACL. This commonly differs per instance
            # (works on dev, blocked on test) even with identical roles.
            if resolved.table.startswith("sp_"):
                hint += (
                    f" NOTE: '{resolved.table}' is a Service Portal table — its write is "
                    "gated by protections layered on top of role/ACL (script-field source-"
                    "context checks, sys_policy record protection, condition-scripted field "
                    "ACLs) that the generic Table API path does not satisfy and that can "
                    "differ per instance even with sp_admin. If roles + update set check out, "
                    "edit this record in the SP Designer UI on that instance, or compare the "
                    "record's ACLs/protection policy between the working and blocked instances."
                )
        else:
            hint = (
                "Remote rejected the write. Local files and _sync_meta are UNCHANGED; "
                "resolve the error and retry."
            )
        response: Dict[str, Any] = {
            "success": False,
            "error": result.get("error", "Push rejected by ServiceNow."),
            "status": status,
            "component": {
                "table": resolved.table,
                "sys_id": resolved.sys_id,
                "name": resolved.name,
            },
            "fields_attempted": list(update_data.keys()),
            "sync_meta_updated": False,
            "hint": hint,
        }
        if active_sets:
            response["active_update_sets"] = active_sets
        return response

    # 5. Update _sync_meta.json with new remote timestamp
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

    # 6. Enrich result (reached only on a confirmed successful push)
    result["success"] = True
    result["risk"] = risk
    result["local_sync"] = {
        "pushed_from": str(path),
        "fields_pushed": list(update_data.keys()),
        "sync_meta_updated": True,
    }
    if not resolved.instance_url:
        result["origin_unverified"] = _ORIGIN_UNVERIFIED_MSG
    return result
