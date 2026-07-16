"""
Local source synchronization tools for ServiceNow MCP.
Diff and push locally edited portal sources back to ServiceNow
with conflict detection.
"""

import difflib
import logging
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils import json_fast
from ..utils.baseline import (
    cleanup_remote_sidecar,
    is_baseline_artifact,
    read_baseline_for,
    remote_sidecar_path_for,
    write_baseline_for,
)
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .portal_tools import (
    UpdatePortalComponentParams,
    _fetch_portal_component_record,
    _safe_name,
    update_portal_component,
)
from .push_safety import assess_push_risk, describe_attribution
from .sn_api import GenericQueryParams, resolve_live_username, sn_query
from .sn_batch import batch_get

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
    # Headers/footers ARE widgets schema-wise (same five code fields) — the old
    # template+css-only map forced server-script edits through raw field writes.
    "sp_header_footer": WIDGET_FILE_FIELD_MAP,
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
    "sys_ws_operation",
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
    # Scripted REST resource: only operation_script is a downloaded source file.
    # relative_path / operation_uri are metadata — edit those via the sys_id path
    # (manage_portal_component), not file-based sync.
    "sys_ws_operation": {"operation_script.js": "operation_script"},
}


# Tables that are downloadable as source but must NOT be diffed/pushed by path.
# sys_update_xml is an update-set payload snapshot, not editable source — its
# body is managed by the update-set machinery, never hand-edited on disk.
_DIFF_PUSH_EXCLUDE_TABLES: Set[str] = {"sys_update_xml"}


@lru_cache(maxsize=1)
def _derived_folder_field_maps() -> Dict[str, Dict[str, str]]:
    """``table -> {filename: field}`` DERIVED from source_tools.SOURCE_CONFIG.

    The generic downloader writes one folder per record as ``<field><ext>``
    files (contract pinned by test_source_layout_contract), so the uploader's
    folder map is fully determined by each table's source_fields — no second
    hand-list to drift. This makes every downloadable code table diffable and
    pushable by path (previously only 9 of ~22 were), instead of forcing a
    record-lookup + update_code fallback for the rest.

    Lazy + cached: SOURCE_CONFIG lives in the ~3800-line source_tools module,
    which must stay out of sync-only tool startups (see _target_qualifier_fields).
    """
    from ..utils.source_layout import field_filename
    from .source_tools import SOURCE_CONFIG

    maps: Dict[str, Dict[str, str]] = {}
    for cfg in SOURCE_CONFIG.values():
        table = cfg["table"]
        fields = cfg.get("source_fields") or []
        if table in _DIFF_PUSH_EXCLUDE_TABLES or not fields:
            continue
        # First entry per table wins; hand-authored maps below still override.
        maps.setdefault(table, {field_filename(f): f for f in fields})
    return maps


def _folder_layout_field_map(table_name: str) -> Optional[Dict[str, str]]:
    """Return the on-disk ``filename -> field`` map for a table's FOLDER layout.

    Folder tables use their real-filename entries from TABLE_FILE_FIELD_MAP
    (the suffix-style ".xxx" keys belong to the flat single-file layout and are
    skipped). Single-file tables use the folder map above. Any OTHER downloadable
    table falls back to the map derived from SOURCE_CONFIG. Returns None only for
    a table that isn't downloadable source at all.
    """
    if table_name in FOLDER_TABLES:
        return {
            fn: field
            for fn, field in TABLE_FILE_FIELD_MAP.get(table_name, {}).items()
            if not fn.startswith(".")
        }
    if table_name in SINGLE_FILE_TABLES:
        return SINGLE_FILE_FOLDER_FIELD_MAP.get(table_name, {})
    return _derived_folder_field_maps().get(table_name)


# Hand-authored core (special filenames / back-compat). The full push/diff
# surface is this UNION the SOURCE_CONFIG-derived tables — use
# _all_supported_tables() for enumeration.
SUPPORTED_TABLES: Set[str] = {
    "sp_widget",
    "sp_angular_provider",
    "sys_script_include",
    "sys_script",
    "sp_header_footer",
    "sp_css",
    "sp_ng_template",
    "sys_ui_page",
    "sys_ws_operation",
}


@lru_cache(maxsize=1)
def _all_supported_tables() -> frozenset:
    """Every table diffable/pushable by path: hand-authored core + derived."""
    return frozenset(SUPPORTED_TABLES | set(_derived_folder_field_maps()))


MAX_DIFF_LINES = 120
# Context lines for the line diff embedded in a CONFLICT response (P1-1) — kept
# tight so a blocked push shows what changed without bloating the rejection.
_CONFLICT_DIFF_CONTEXT = 3


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
    compare_to: Optional[str] = Field(
        default=None,
        description="2nd download root to diff against instead of remote (dev-vs-test, no network).",
    )
    verdict: bool = Field(
        default=False,
        description="Status-only: verdict + changed-line counts, no diff bodies; dirs scan all.",
    )


class PushLocalComponentParams(BaseModel):
    """Parameters for pushing local file changes to ServiceNow."""

    path: str = Field(
        default=...,
        description="Local path from a download; <table>/<name>/<file> folder layout.",
    )
    force: bool = Field(
        default=False,
        description="Override a conflict (remote changed since download) and push anyway.",
    )
    confirm_overwrite_updated_on: Optional[str] = Field(
        default=None,
        description="With force: the remote sys_updated_on you reviewed; re-blocks if it moved.",
    )
    cross_instance_deploy: bool = Field(
        default=False,
        description="Deploy to a DIFFERENT instance than origin; target re-resolved by name.",
    )


# ---------------------------------------------------------------------------
# Resolved component data structure
# ---------------------------------------------------------------------------
class _ResolvedComponent:
    __slots__ = (
        "table",
        "sys_id",
        "name",
        "fields",
        "scope_root",
        "instance_url",
        "remote_name",
        "qualifier",
    )

    def __init__(
        self,
        table: str,
        sys_id: str,
        name: str,
        fields: Dict[str, Path],
        scope_root: Path,
        instance_url: str,
        remote_name: Optional[str] = None,
        qualifier: Optional[tuple] = None,
    ):
        self.table = table
        self.sys_id = sys_id
        # `name` is the local folder key — used for _sync_meta.json / _map.json
        # lookups, so it MUST stay equal to the on-disk folder name.
        self.name = name
        self.fields = fields  # field_name -> local file path
        self.scope_root = scope_root
        self.instance_url = instance_url
        # ServiceNow identity for cross-instance target resolution. Differs from
        # `name` when the folder was qualified (e.g. sys_ws_operation folder
        # 'RequestAPI.Get_Request_Status' but the record's own name is 'Get
        # Request Status'). Defaults to name for the common unqualified case.
        self.remote_name = remote_name if remote_name is not None else name
        # (field, value) that disambiguates remote_name among same-named records
        # on the target — e.g. ('web_service_definition.name', 'RequestAPI'). None
        # when the name alone is a unique target identity.
        self.qualifier = qualifier


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


def _read_metadata_sys_id(record_dir: Path) -> str:
    """Exact sys_id from a record folder's metadata file.

    Collision-proof: operation/script names are NOT globally unique (two web
    services can each have a 'get' operation), so a name -> _map.json lookup can
    resolve the WRONG record. The per-folder metadata carries this record's own
    sys_id, written at download time. '' when absent (fall back to _map.json).

    Reads BOTH formats: source downloads write _metadata.json; the PORTAL
    download (download_portal_sources / download_app_sources) writes _widget.json
    with a top-level "sys_id". Reading only the first made push silently fall
    back to the name-keyed _map.json for every portal/bulk-downloaded widget,
    bypassing the collision-proof sys_id that was sitting right there. So the
    resolution path differed by which downloader wrote the folder; both now count.
    """
    for fname in ("_metadata.json", "_widget.json"):
        meta = record_dir / fname
        if not meta.is_file():
            continue
        try:
            data = json_fast.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            sys_id = str(data.get("sys_id") or "").strip()
            if sys_id:
                return sys_id
    return ""


@lru_cache(maxsize=1)
def _target_qualifier_fields() -> Dict[str, str]:
    """Tables whose folder was qualified by a parent → the qualifying field.

    DERIVED from source_tools.SOURCE_CONFIG (folder_qualifier_field), never
    hand-mirrored — adding a qualifier to a new type automatically routes its
    cross-instance push. The dot-walk field both names the parent and
    disambiguates the record among same-named siblings on a target instance.
    Import is lazy + cached: the 3800-line source_tools module must not become
    a startup cost for packages that enable only sync tools.
    """
    from .source_tools import SOURCE_CONFIG

    return {
        cfg["table"]: cfg["folder_qualifier_field"]
        for cfg in SOURCE_CONFIG.values()
        if cfg.get("folder_qualifier_field")
    }


def _read_metadata_field(record_dir: Path, field: str) -> str:
    """Read one field from a record folder's _metadata.json/_widget.json.

    Used for the record's own ServiceNow `name` and parent qualifier — both stored
    at download time (they are summary_fields). '' when absent."""
    for fname in ("_metadata.json", "_widget.json"):
        meta = record_dir / fname
        if not meta.is_file():
            continue
        try:
            data = json_fast.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            val = str(data.get(field) or "").strip()
            if val:
                return val
    return ""


def _safe_rel_path(name: str) -> str:
    """Sanitize a record's folder path SEGMENT BY SEGMENT.

    A qualified record's folder is a relative path ('<qualifier>/<name>'), so
    running _safe_name over the whole string would fold its separator into an
    underscore and point at a directory that does not exist. Plain names are
    unaffected, so this is a safe drop-in for the historical single-segment call.
    """
    return "/".join(_safe_name(seg) for seg in name.split("/") if seg)


def _resolve_table_dir(record_dir: Path) -> Optional[Tuple[str, Path]]:
    """(table, table_dir) for a record folder, read from its own _metadata.json.

    Deriving the table from ``record_dir.parent.name`` assumed a fixed depth
    (<table>/<name>/), which broke the moment a qualified type nested its records
    (<table>/<qualifier>/<name>/): the parent is then the QUALIFIER, and a push
    either rejected the record or — when a qualifier happened to share a real
    table's name (a business rule on 'sys_script_include') — resolved the WRONG
    table. The record's metadata carries its own table, so depth stops mattering.

    Reads 'source_table', NOT 'table': client_script and ui_action carry a summary
    field named 'table' (the table they TARGET), which overwrites 'table' in the
    metadata. Trusting it would resolve a client script into its target table's
    directory. Legacy trees predate 'source_table', so 'table' remains the
    fallback — harmless there, because a shadowed value never matches an ancestor.

    Walks up to the nearest ancestor named for that table. Returns None when the
    metadata is absent (legacy trees) or the ancestor is missing, so callers can
    fall back to the historical parent-name heuristic.
    """
    table = _read_metadata_field(record_dir, "source_table") or _read_metadata_field(
        record_dir, "table"
    )
    if not table:
        return None
    for ancestor in record_dir.parents:
        if ancestor.name == table:
            return table, ancestor
    return None


def _resolve_remote_identity(
    record_dir: Path, table: str, folder_name: str
) -> Tuple[str, Optional[tuple]]:
    """The record's ServiceNow name + optional (field, value) qualifier for
    cross-instance target lookup. Falls back to the folder name when metadata is
    absent (legacy/unqualified folders keep working)."""
    remote_name = _read_metadata_field(record_dir, "name") or folder_name
    qualifier: Optional[tuple] = None
    qfield = _target_qualifier_fields().get(table)
    if qfield:
        qvalue = _read_metadata_field(record_dir, qfield)
        if qvalue:
            qualifier = (qfield, qvalue)
    return remote_name, qualifier


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


def _record_sync_meta(
    table_dir: Path, name: str, sys_id: str, updated_on: str, updated_by: str
) -> None:
    """Record one component's in-sync watermark: WHEN the server was last known
    good AND WHO last touched it.

    ``sys_updated_by`` is not decoration — it is the baseline owner the next diff
    compares the current editor against. Omitting it leaves the previous owner
    standing, so your own completed push reads as someone taking the record over.
    Only call this when the local copy provably equals the remote body.
    """
    meta = _read_sync_meta(table_dir)
    # Immutable update: build a new mapping rather than mutating the loaded one.
    _write_sync_meta(
        table_dir,
        {
            **meta,
            name: {
                "sys_id": sys_id,
                "sys_updated_on": updated_on,
                "sys_updated_by": updated_by,
                "downloaded_at": datetime.now(UTC).isoformat(),
            },
        },
    )


def _is_download_root(path: Path) -> bool:
    """Check if path looks like a download root (has _settings.json or scope subdirs with tables)."""
    if (path / "_settings.json").exists():
        return True
    for child in path.iterdir():
        if child.is_dir():
            for table in _all_supported_tables():
                if (child / table / "_map.json").exists():
                    return True
    return False


def _resolve_local_path(path: Path) -> _ResolvedComponent:
    """Resolve a local file or directory to its ServiceNow component identity.

    Folder layout (what the downloaders write for EVERY table — <table>/<name>/<file>):
      .../sp_widget/<folder>/script.js            -> (sp_widget, script)
      .../sp_angular_provider/<name>/script.js    -> (sp_angular_provider, script)
      .../sys_script_include/<name>/script.js     -> (sys_script_include, script)

    Qualified types nest one level deeper (<table>/<qualifier>/<name>/<file>), so
    the table is read from the record's _metadata.json — never from the parent
    directory's name. See _resolve_table_dir.
      .../sys_script/<collection>/<name>/script.js          -> (sys_script, script)
      .../sys_ws_operation/<web_service>/<name>/...         -> (sys_ws_operation, ...)

    Flat layout (legacy single-file, still accepted for back-compat):
      .../sp_angular_provider/<name>.script.js    -> (sp_angular_provider, script)
      .../sp_css/<name>.css.scss                  -> (sp_css, css)
      .../sp_ng_template/<name>.template.html     -> (sp_ng_template, template)
    """
    path = path.expanduser().resolve()

    # Hard stop for internal 3-way artifacts: pushing a baseline snapshot or a
    # .remote conflict sidecar would upload the WRONG body under the component's
    # identity — exactly the "stale source pushed" accident this layer prevents.
    if is_baseline_artifact(path):
        raise ValueError(
            f"'{path.name}' is a baseline snapshot or '.remote' conflict sidecar — an internal "
            f"comparison artifact, not the component. Edit and push the main field file next to "
            f"it; the sidecar is the server's version saved during a conflict for manual merge."
        )

    # Case 1: Directory -> a record folder (<table>/<name>/) in either a
    # folder-based table or a single-file table downloaded in folder layout.
    if path.is_dir():
        resolved_dir = _resolve_table_dir(path)
        if resolved_dir is not None:
            table_name, table_dir = resolved_dir
        else:
            table_dir = path.parent
            table_name = table_dir.name
        file_field_map = _folder_layout_field_map(table_name)
        if file_field_map is None:
            raise ValueError(
                f"File-based push doesn't cover '{table_name}' (file-path tables: "
                f"{', '.join(sorted(_all_supported_tables()))}). This is a "
                f"file-path limit, NOT 'uneditable' — edit it by sys_id instead: "
                f"manage_portal_component(action='update_code', table='{table_name}', "
                f"sys_id=..., update_data={{...}})."
            )
        folder_name = path.relative_to(table_dir).as_posix()
        map_data = _read_map_json(table_dir)
        # Prefer this record's own sys_id from _metadata.json (collision-proof);
        # _map.json keys are original names; folder names are _safe_name(original),
        # so fall back to direct then reverse lookup.
        sys_id = (
            _read_metadata_sys_id(path)
            or map_data.get(folder_name)
            or _reverse_lookup_map(map_data, folder_name)
        )
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
        remote_name, qualifier = _resolve_remote_identity(path, table_name, folder_name)
        return _ResolvedComponent(
            table=table_name,
            sys_id=sys_id,
            name=folder_name,
            fields=fields,
            scope_root=scope_root,
            instance_url=_resolve_origin_url(scope_root),
            remote_name=remote_name,
            qualifier=qualifier,
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
    resolved_dir = _resolve_table_dir(parent)
    if resolved_dir is not None and _folder_layout_field_map(resolved_dir[0]) is None:
        resolved_dir = None  # metadata names a table we cannot push by path
    if resolved_dir is None and _folder_layout_field_map(grandparent.name) is not None:
        resolved_dir = (grandparent.name, grandparent)
    if resolved_dir is not None:
        table_name, table_dir = resolved_dir
        folder_name = parent.relative_to(table_dir).as_posix()
        filename = path.name
        file_field_map = _folder_layout_field_map(table_name) or {}
        _field_name_opt = file_field_map.get(filename)
        if not _field_name_opt:
            supported = ", ".join(sorted(file_field_map))
            raise ValueError(
                f"File-based push doesn't recognize '{filename}' for {table_name} "
                f"(known files: {supported}). If it's a metadata field (not a downloaded "
                f"file), edit it by sys_id: manage_portal_component(action='update_code', "
                f"table='{table_name}', sys_id=..., update_data={{...}})."
            )
        field_name = _field_name_opt
        map_data = _read_map_json(table_dir)
        # Prefer the record's own _metadata.json sys_id (collision-proof) over the
        # name-keyed _map.json — see _read_metadata_sys_id.
        sys_id = (
            _read_metadata_sys_id(parent)
            or map_data.get(folder_name)
            or _reverse_lookup_map(map_data, folder_name)
        )
        if not sys_id:
            raise ValueError(f"Component '{folder_name}' not found in {table_dir / '_map.json'}")
        scope_root = table_dir.parent
        remote_name, qualifier = _resolve_remote_identity(parent, table_name, folder_name)
        return _ResolvedComponent(
            table=table_name,
            sys_id=sys_id,
            name=folder_name,
            fields={field_name: path},
            scope_root=scope_root,
            instance_url=_resolve_origin_url(scope_root),
            remote_name=remote_name,
            qualifier=qualifier,
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
    """Find sys_id by matching _safe_rel_path(key) == safe_name."""
    for key, sys_id in map_data.items():
        if _safe_rel_path(key) == safe_name or key == safe_name:
            return sys_id
    return None


def _reverse_lookup_name(map_data: Dict[str, str], safe_name: str) -> str | None:
    """Find original name key by matching _safe_rel_path(key) == safe_name."""
    for key in map_data:
        if _safe_rel_path(key) == safe_name or key == safe_name:
            return key
    return None


def _resolve_target_by_name(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    name: str,
    qualifier: Optional[tuple] = None,
) -> List[Dict[str, str]]:
    """Look up a record on the TARGET instance by its name — used for
    cross-instance deploy so we push to the target's OWN sys_id instead of the
    origin's (which may not exist / may be a different record on the target). The
    name is the stable identity across instances; returns all matches so the
    caller can require exactly one (0 = not there, >1 = ambiguous).

    `qualifier` is an optional (field, value) pair that disambiguates a name which
    is unique only within a parent (e.g. a sys_ws_operation 'end' is unique only
    within its web service). Without it, same-named children read as ambiguous."""
    safe_name = name.replace("^", "").replace("=", "")
    query = f"name={safe_name}"
    if qualifier:
        qfield, qvalue = qualifier
        query += f"^{qfield}={str(qvalue).replace('^', '').replace('=', '')}"
    try:
        resp = sn_query(
            config,
            auth_manager,
            GenericQueryParams(
                table=table,
                query=query,
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


def _resolve_current_user(config: ServerConfig, auth_manager: AuthManager) -> str:
    """Live current-user for push attribution. Thin wrapper over the shared,
    TTL-cached ``resolve_live_username`` (see sn_api) so push attribution and
    sn_health identity can't drift in parse/cache/error semantics."""
    return resolve_live_username(config, auth_manager)


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
        # Lead with the fix: the observed failure mode is the LLM re-issuing the
        # same call ~12× because the actionable hint was buried mid-message. The
        # FIRST sentence must be the exact retry.
        raise ValueError(
            f"Retry this call with instance=<alias> — the alias for '{origin}' "
            f"(run list_instances to find it). For a push, add confirm_instance=<alias> "
            f"confirm='approve'. Reason: this local component is from '{origin}' but the "
            f"active instance is '{active}', so the active one is the WRONG target and is "
            f"blocked. Do NOT edit config or re-download to change the target."
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


def _record_update_set_hold(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    sys_id: str,
    me: str,
) -> Optional[Dict[str, str]]:
    """The newest update set that CURRENTLY holds a change to this record, if it
    is still open and owned by a DIFFERENT user.

    Record-level *membership* check (sys_update_xml) decided against the LIVE
    remote — not the local download baseline and not the time-window concurrent
    guard. So it catches a record locked in someone else's open update set even
    when that edit is old, and reports it as released once that set is committed.
    That is the whole point: a hold that was true at download but committed by
    push time must NOT keep reading as a conflict.

    Returns None on any uncertainty (no entry, committed/released, same user,
    read error) so it never masks the real failure or blocks a clean push.
    """
    if not (table and sys_id):
        return None
    try:
        resp = sn_query(
            config,
            auth_manager,
            GenericQueryParams(
                table="sys_update_xml",
                query=f"name={table}_{sys_id}",
                fields="update_set.name,update_set.state,sys_updated_by",
                orderby="-sys_updated_on",
                limit=1,
                offset=0,
                display_value=True,
            ),
        )
    except Exception as exc:  # best-effort diagnostic; never mask the real failure
        logger.warning("Could not resolve update-set hold for %s/%s: %s", table, sys_id, exc)
        return None
    rows = resp.get("results") or []
    if not rows:
        return None
    row = rows[0]
    state = _display_str(row.get("update_set.state")).strip().lower()
    set_name = _display_str(row.get("update_set.name")).strip()
    holder = _display_str(row.get("sys_updated_by")).strip()
    # A committed/closed set no longer holds the record — the change is released,
    # so this is NOT a live hold (the "A committed, nobody holds it now" case).
    if state in ("complete", "committed", "closed", "ignore"):
        return None
    if not set_name:
        return None
    # Your own open update set is not a cross-user hold.
    if me and holder and holder == me.strip():
        return None
    return {
        "update_set": set_name,
        "held_by": holder or "unknown",
        "state": state or "in progress",
    }


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
    return _batch_fetch_updated_on_multi(config, auth_manager, {table: sys_ids}).get(table, {})


def _batch_fetch_updated_on_multi(
    config: ServerConfig,
    auth_manager: AuthManager,
    ids_by_table: Dict[str, List[str]],
) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Timestamps/attribution for MANY tables' sys_ids in ONE round trip.

    Returns {table: {sys_id: {"on":…, "by":…}}}. Every table's sys_idIN chunks
    ride one batch POST (the _verdict_scan recipe — issue #68 item 1: the
    default directory scan used to pay one batch per table dir); a chunk the
    batch did not service falls back to a direct query, never a half state.
    """
    specs: List[Tuple[str, str]] = []
    chunk_index: Dict[str, Tuple[str, List[str]]] = {}
    for table, sys_ids in ids_by_table.items():
        chunks = [sys_ids[i : i + 100] for i in range(0, len(sys_ids), 100)]
        for i, chunk in enumerate(chunks):
            rid = f"{table}:{i}"
            chunk_index[rid] = (table, chunk)
            specs.append((rid, _table_chunk_url(table, chunk, [])))
    if not specs:
        return {}
    batch = batch_get(config, auth_manager, specs)
    result: Dict[str, Dict[str, Dict[str, str]]] = {}
    for rid, (table, chunk) in chunk_index.items():
        served = (batch or {}).get(rid)
        rows: Optional[List[Dict[str, Any]]] = None
        if served and served.get("status_code") == 200 and isinstance(served.get("body"), dict):
            rows = served["body"].get("result")
        if rows is None:
            params = GenericQueryParams(
                table=table,
                query=f"sys_idIN{','.join(chunk)}",
                fields="sys_id,sys_updated_on,sys_updated_by",
                limit=len(chunk),
                offset=0,
                display_value=False,
            )
            rows = sn_query(config, auth_manager, params).get("results") or []
        per_table = result.setdefault(table, {})
        for row in rows:
            sid = str(row.get("sys_id") or "")
            if sid:
                per_table[sid] = {
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
        # Lead with the fix (read-only diff): the LLM otherwise retries the same
        # call repeatedly. First sentence = the exact retry.
        return {
            "error": (
                f"Retry this diff with instance=<alias> — the alias for '{origin_url}' "
                f"(run list_instances to find it). Reason: this directory is from "
                f"'{origin_url}' but the current connection is '{config.instance_url}'."
            )
        }

    components: List[Dict[str, Any]] = []

    # Collect → fuse → judge (the _verdict_scan shape): gather every table
    # dir's ids first, fetch ALL tables' timestamps in one batch round trip,
    # then judge per component. Previously each (table, dir) paid its own
    # batch call — T round trips for a T-table scope (issue #68 item 1).
    dir_entries: List[Tuple[str, Path, Dict[str, str], Dict[str, Dict[str, str]]]] = []
    ids_by_table: Dict[str, List[str]] = {}
    for table_name in sorted(_all_supported_tables()):
        for table_dir in _find_table_dirs(root, table_name):
            map_data = _read_map_json(table_dir)
            if not map_data:
                continue
            dir_entries.append((table_name, table_dir, map_data, _read_sync_meta(table_dir)))
            seen = ids_by_table.setdefault(table_name, [])
            seen.extend(sid for sid in map_data.values() if sid not in seen)

    remote_by_table = _batch_fetch_updated_on_multi(config, auth_manager, ids_by_table)

    for table_name, table_dir, map_data, sync_meta in dir_entries:
        remote_meta = remote_by_table.get(table_name, {})
        for name, sys_id in map_data.items():
            meta = sync_meta.get(name, {})
            local_updated_on = meta.get("sys_updated_on", "")
            downloaded_at = meta.get("downloaded_at", "")
            rmeta = remote_meta.get(sys_id, {})
            remote_updated_on = rmeta.get("on", "")
            remote_updated_by = rmeta.get("by", "")
            has_sync_meta = bool(local_updated_on)

            # Folder layout (<table>/<name>/<field>.<ext>, or
            # <table>/<qualifier>/<name>/<field>.<ext> for qualified types) is
            # what the downloaders write for every table, so check it first.
            # Single-file tables also accept the historical flat "<name>.<suffix>".
            safe = _safe_rel_path(name)
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


def _component_field_files(table_dir: Path, name: str, table_name: str) -> Dict[str, Path]:
    """field_name -> on-disk file for one downloaded component. Local-only, no network."""
    fields: Dict[str, Path] = {}
    safe = _safe_rel_path(name)
    folder = table_dir / safe
    folder_map = _folder_layout_field_map(table_name) or {}
    for filename, field_name in folder_map.items():
        fpath = folder / filename
        if fpath.exists():
            fields[field_name] = fpath
    if not fields and table_name in SINGLE_FILE_TABLES:
        flat_map = TABLE_FILE_FIELD_MAP.get(table_name, {})
        for suffix_pattern, field_name in flat_map.items():
            if suffix_pattern.startswith("."):
                fpath = table_dir / f"{safe}{suffix_pattern}"
                if fpath.exists():
                    fields[field_name] = fpath
    return fields


def _enumerate_local_components(root: Path) -> Dict[Tuple[str, str], Dict[str, Path]]:
    """(table, name) -> {field: file path} for every downloaded component under root."""
    out: Dict[Tuple[str, str], Dict[str, Path]] = {}
    for table_name in sorted(_all_supported_tables()):
        for table_dir in _find_table_dirs(root, table_name):
            for name in _read_map_json(table_dir):
                fields = _component_field_files(table_dir, name, table_name)
                if fields:
                    out[(table_name, name)] = fields
    return out


def _diff_field_files(
    left_fields: Dict[str, Path],
    right_fields: Dict[str, Path],
    context_lines: int,
    *,
    with_bodies: bool,
) -> List[Dict[str, Any]]:
    """Diff two field->Path maps on disk. with_bodies=False returns status only."""
    diffs: List[Dict[str, Any]] = []
    for field_name in sorted(set(left_fields) | set(right_fields)):
        lp = left_fields.get(field_name)
        rp = right_fields.get(field_name)
        left = lp.read_text(encoding="utf-8") if lp and lp.exists() else None
        right = rp.read_text(encoding="utf-8") if rp and rp.exists() else None
        if left is None:
            diffs.append({"field": field_name, "status": "only_in_right"})
            continue
        if right is None:
            diffs.append({"field": field_name, "status": "only_in_left"})
            continue
        if _normalize_for_compare(left) == _normalize_for_compare(right):
            diffs.append({"field": field_name, "status": "unchanged"})
            continue
        entry: Dict[str, Any] = {"field": field_name, "status": "modified"}
        if with_bodies:
            diff_lines = list(
                difflib.unified_diff(
                    right.splitlines(),
                    left.splitlines(),
                    fromfile=f"right/{field_name}",
                    tofile=f"left/{field_name}",
                    lineterm="",
                    n=context_lines,
                )
            )
            if len(diff_lines) > MAX_DIFF_LINES:
                diff_lines = diff_lines[:MAX_DIFF_LINES] + [
                    "... [DIFF TRUNCATED FOR CONTEXT SAFETY]"
                ]
            entry["diff"] = "\n".join(diff_lines)
            entry["left_lines"] = len(left.splitlines())
            entry["right_lines"] = len(right.splitlines())
        diffs.append(entry)
    return diffs


def _diff_local_roots(left: Path, right: Path, context_lines: int) -> Dict[str, Any]:
    """Diff two download roots component-by-component, no network. Summary only.

    'left' is `path`, 'right' is `compare_to`. Bodies stay on disk — per-component
    status + which fields differ (names), not the diff text. Drill into one
    component with path=<that file/dir>, compare_to=<right root> for full bodies.
    """
    left_comps = _enumerate_local_components(left)
    right_comps = _enumerate_local_components(right)
    components: List[Dict[str, Any]] = []
    for table, name in sorted(set(left_comps) | set(right_comps)):
        lf = left_comps.get((table, name))
        rf = right_comps.get((table, name))
        if lf is None:
            components.append({"table": table, "name": name, "status": "only_in_right"})
            continue
        if rf is None:
            components.append({"table": table, "name": name, "status": "only_in_left"})
            continue
        field_diffs = _diff_field_files(lf, rf, context_lines, with_bodies=False)
        changed = [d["field"] for d in field_diffs if d["status"] != "unchanged"]
        comp: Dict[str, Any] = {
            "table": table,
            "name": name,
            "status": "different" if changed else "identical",
        }
        if changed:
            comp["changed_fields"] = changed
        components.append(comp)
    status_counts: Dict[str, int] = {}
    for c in components:
        status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
    return {
        "mode": "compare_local_roots",
        "left": str(left),
        "right": str(right),
        "components": components,
        "summary": {"total": len(components), **status_counts},
    }


def _diff_local_component_vs_root(
    path: Path, right_root: Path, context_lines: int
) -> Dict[str, Any]:
    """Diff one local component (path) against its counterpart in another root. No network."""
    try:
        resolved = _resolve_local_path(path)
    except ValueError as e:
        return {"error": str(e)}
    right_dirs = _find_table_dirs(right_root, resolved.table)
    right_fields: Dict[str, Path] = {}
    for table_dir in right_dirs:
        right_fields = _component_field_files(table_dir, resolved.name, resolved.table)
        if right_fields:
            break
    if not right_fields:
        return {
            "error": (
                f"'{resolved.name}' ({resolved.table}) not found under compare_to root "
                f"{right_root}. Download the same scope there first."
            )
        }
    # Mirror the field scope of `path`: a single-file path resolves to one field,
    # a whole record dir to all — don't surface the other side's extra fields.
    right_fields = {f: p for f, p in right_fields.items() if f in resolved.fields}
    diffs = _diff_field_files(resolved.fields, right_fields, context_lines, with_bodies=True)
    return {
        "mode": "compare_local_component",
        "left": str(path),
        "right": str(right_root),
        "component": {"table": resolved.table, "name": resolved.name},
        "diffs": diffs,
    }


def _diff_against_compare_to(path: Path, compare_to: Path, context_lines: int) -> Dict[str, Any]:
    """Route a compare_to diff: root-vs-root (summary) or component-vs-root (bodies)."""
    if not compare_to.exists():
        return {"error": f"compare_to path does not exist: {compare_to}"}
    if not compare_to.is_dir():
        return {"error": f"compare_to must be a download root directory, not a file: {compare_to}"}
    if path.is_dir() and _is_download_root(path):
        if not _is_download_root(compare_to):
            return {"error": f"compare_to must be a download root when path is one: {compare_to}"}
        return _diff_local_roots(path, compare_to, context_lines)
    return _diff_local_component_vs_root(path, compare_to, context_lines)


def _server_moved_fields(
    resolved: "_ResolvedComponent", remote_record: Dict[str, Any]
) -> Tuple[List[str], bool]:
    """CONTENT truth for the conflict gate: which fields the SERVER actually
    changed since your last download/push. Returns (moved_fields, verifiable).

    ``sys_updated_on`` is only a HINT. It also bumps for YOUR OWN push, a re-save,
    or an edit to an unrelated field on the same record — so a timestamp-only gate
    reports "someone changed this" on a perfectly clean round-trip, which is the
    false alarm this replaces (editing the same file twice in one session tripped
    it every time). The pristine ``_baseline/`` snapshot holds exactly what the
    server had at your last download or successful push, so hashing the remote
    BODY against it answers the real question: is there a server-side change you
    have not seen?

    This is a CONTENT check, not a trust check — being the last editor never
    excuses the comparison; identity only shapes the wording afterwards.

    ``verifiable`` is False when no field has a baseline (legacy tree downloaded
    before baselines existed). The caller MUST then fall back to the timestamp —
    never to a silent "no conflict".
    """
    moved: List[str] = []
    verifiable = False
    for field_name, fpath in sorted(resolved.fields.items()):
        baseline = read_baseline_for(fpath)
        if baseline is None:
            continue
        verifiable = True
        remote_content = _normalize_for_compare(str(remote_record.get(field_name) or ""))
        if remote_content != _normalize_for_compare(baseline):
            moved.append(field_name)
    return moved, verifiable


def _assess_server_drift(
    resolved: "_ResolvedComponent",
    remote_record: Dict[str, Any],
    local_updated_on: str,
    remote_updated_on: str,
) -> Dict[str, Any]:
    """Did the server move? Content decides; the timestamp is the fallback.

    Returns {drifted, moved_fields, verifiable, timestamp_moved, timestamp_only}.
    ``timestamp_only`` — the stamp advanced but every body still matches your
    baseline — is the benign case: a stale watermark, not a conflict.
    """
    timestamp_moved = bool(
        local_updated_on and remote_updated_on and remote_updated_on > local_updated_on
    )
    moved_fields, verifiable = _server_moved_fields(resolved, remote_record)
    drifted = bool(moved_fields) if verifiable else timestamp_moved
    return {
        "drifted": drifted,
        "moved_fields": moved_fields,
        "verifiable": verifiable,
        "timestamp_moved": timestamp_moved,
        "timestamp_only": timestamp_moved and verifiable and not moved_fields,
    }


def _baseline_three_way(
    resolved: "_ResolvedComponent", remote_record: Dict[str, Any]
) -> Dict[str, Any]:
    """Separate YOUR local edits from the SERVER's changes using the pristine
    baseline recorded at download/push time. Empty dict when no baseline exists
    (legacy tree) or nothing diverged. Field names only — token-lean."""
    yours: List[str] = []
    theirs: List[str] = []
    both_applied: List[str] = []
    diverged: List[str] = []
    sidecars: List[str] = []
    for field_name, fpath in sorted(resolved.fields.items()):
        baseline = read_baseline_for(fpath)
        if baseline is None or not fpath.exists():
            continue
        try:
            local = fpath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        local_n = _normalize_for_compare(local)
        baseline_n = _normalize_for_compare(baseline)
        remote_n = _normalize_for_compare(str(remote_record.get(field_name) or ""))
        if local_n == baseline_n and remote_n == baseline_n:
            continue
        if local_n != baseline_n and remote_n == baseline_n:
            yours.append(field_name)
        elif local_n == baseline_n:
            theirs.append(field_name)
        elif local_n == remote_n:
            both_applied.append(field_name)
        else:
            diverged.append(field_name)
        sidecar = remote_sidecar_path_for(fpath)
        if sidecar.exists():
            sidecars.append(sidecar.name)
    out: Dict[str, Any] = {}
    if yours:
        out["your_local_edits"] = yours
    if theirs:
        out["server_changed_local_untouched"] = theirs
    if both_applied:
        out["local_already_matches_new_server"] = both_applied
    if diverged:
        out["diverged_both_changed"] = diverged
    if sidecars:
        out["conflict_sidecars_on_disk"] = sidecars
    return out


# ---------------------------------------------------------------------------
# Verdict mode: token-lean live verification. The remote BODY is fetched and
# compared inside the MCP (network only) — the LLM context receives verdicts
# and line counts, never source text. Verdicts (baseline-attributed):
#   identical | local_ahead (your edits) | remote_ahead (server moved) |
#   diverged (both) | changed_no_baseline (differs, legacy tree — can't
#   attribute) | missing_remote
# ---------------------------------------------------------------------------
_VERDICT_ATTENTION_CAP = 200


def _count_changed_lines(left: str, right: str) -> int:
    """Lines added+removed between two bodies (n=0 unified diff)."""
    changed = 0
    for line in difflib.unified_diff(left.splitlines(), right.splitlines(), lineterm="", n=0):
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            changed += 1
    return changed


def _field_state(local: str, baseline: Optional[str], remote: str) -> str:
    local_n = _normalize_for_compare(local)
    remote_n = _normalize_for_compare(remote)
    if local_n == remote_n:
        return "in_sync"
    if baseline is None:
        return "changed_no_baseline"
    baseline_n = _normalize_for_compare(baseline)
    if baseline_n == local_n:
        return "remote_ahead"
    if baseline_n == remote_n:
        return "local_ahead"
    return "diverged"


def _aggregate_verdict(states: Set[str]) -> str:
    """Component verdict from its non-in_sync field states."""
    if not states:
        return "identical"
    if "diverged" in states or {"local_ahead", "remote_ahead"} <= states:
        return "diverged"
    if "changed_no_baseline" in states:
        return "changed_no_baseline"
    return next(iter(states))


def _remote_record_state(record: Dict[str, Any]) -> Dict[str, str]:
    """Server-side edit evidence — echoed on EVERY result so 'unchanged' can
    never be mistaken for 'nothing happened on the server'."""
    return {
        "updated_on": str(record.get("sys_updated_on") or ""),
        "updated_by": _display_str(record.get("sys_updated_by")),
        "mod_count": str(record.get("sys_mod_count") or ""),
    }


def _component_field_verdicts(
    fields: Dict[str, Path], remote_record: Dict[str, Any]
) -> Tuple[Dict[str, Any], Set[str], List[str]]:
    """(non-in_sync field rows, their states, conflict sidecars on disk)."""
    field_rows: Dict[str, Any] = {}
    states: Set[str] = set()
    sidecars: List[str] = []
    for field_name, fpath in sorted(fields.items()):
        if not fpath.exists():
            continue
        try:
            local = fpath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        remote_text = str(remote_record.get(field_name) or "")
        state = _field_state(local, read_baseline_for(fpath), remote_text)
        sidecar = remote_sidecar_path_for(fpath)
        if sidecar.exists():
            sidecars.append(sidecar.name)
        if state == "in_sync":
            continue
        states.add(state)
        field_rows[field_name] = {
            "state": state,
            "changed_lines": _count_changed_lines(local, remote_text),
        }
    return field_rows, states, sidecars


def _table_source_fields(table_name: str) -> List[str]:
    """Union of field names this table stores on disk (folder + flat layouts)."""
    fields: Set[str] = set((_folder_layout_field_map(table_name) or {}).values())
    fields.update(TABLE_FILE_FIELD_MAP.get(table_name, {}).values())
    return sorted(fields)


def _table_chunk_url(table: str, chunk: List[str], fields: List[str]) -> str:
    """Relative Table-API GET url for one sys_idIN chunk (Batch API sub-request)."""
    field_list = ",".join(
        dict.fromkeys(["sys_id", *fields, "sys_updated_on", "sys_updated_by", "sys_mod_count"])
    )
    query = urlencode(
        {
            "sysparm_query": f"sys_idIN{','.join(chunk)}",
            "sysparm_fields": field_list,
            "sysparm_limit": str(len(chunk)),
            "sysparm_display_value": "false",
            "sysparm_exclude_reference_link": "true",
        }
    )
    return f"/api/now/table/{table}?{query}"


def _fetch_records_chunk(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    chunk: List[str],
    fields: List[str],
) -> List[Dict[str, Any]]:
    """Single-chunk direct fetch (fallback path when the Batch API is out).

    Raw GET, NOT sn_query: the verdict scan compares source BODIES, so a field
    >50k chars must not be clipped by sn_query's truncate_results (a context-
    budget safeguard). The primary Batch API path already reads raw/untruncated;
    this fallback must match it or a >50KB body would falsely verdict as drifted.
    """
    url = f"{config.instance_url.rstrip('/')}{_table_chunk_url(table, chunk, fields)}"
    headers = auth_manager.get_headers()
    resp = auth_manager.make_request("GET", url, headers=headers)
    if resp.status_code >= 400:
        raise ValueError(
            f"Failed to fetch {table} chunk: HTTP {resp.status_code} — {resp.text[:200]}"
        )
    return resp.json().get("result") or []


def _verdict_scan(config: ServerConfig, auth_manager: AuthManager, root: Path) -> Dict[str, Any]:
    """Batch verdict for every component under *root* (download root, scope
    root, or table dir). Bodies are compared in the MCP; only verdicts return.

    Remote fetches for ALL tables are fused into ONE HTTP round trip via the
    Batch API when the instance supports it; otherwise each chunk falls back
    to a direct query — same results, old latency.
    """
    started = time.perf_counter()
    attention: List[Dict[str, Any]] = []
    checked = 0
    in_sync = 0
    skipped_origin: List[Dict[str, str]] = []

    # Pass 1: collect scannable (table, dir, map) work items — no network.
    work: List[Tuple[str, Path, Dict[str, str]]] = []
    for table_name in sorted(_all_supported_tables()):
        table_dirs = _find_table_dirs(root, table_name)
        # The path may BE a table dir (.../sys_script_include) — scan it directly.
        if root.name == table_name and (root / "_map.json").exists() and root not in table_dirs:
            table_dirs.append(root)
        for table_dir in table_dirs:
            map_data = _read_map_json(table_dir)
            if not map_data:
                continue
            origin = _resolve_origin_url(table_dir)
            if origin and origin.rstrip("/") != config.instance_url.rstrip("/"):
                skipped_origin.append(
                    {"table": table_name, "path": str(table_dir), "origin": origin}
                )
                continue
            work.append((table_name, table_dir, map_data))

    # Pass 2: fetch every table's records — Batch API first (1 round trip for
    # the WHOLE scan), per-chunk direct queries only for what it didn't serve.
    http_requests = 0
    chunk_specs: List[Tuple[str, int, List[str]]] = []  # (rid, work_idx, chunk)
    for idx, (_table_name, _table_dir, map_data) in enumerate(work):
        ids = sorted({str(sid) for sid in map_data.values() if sid})
        for j in range(0, len(ids), 50):
            chunk_specs.append((str(len(chunk_specs)), idx, ids[j : j + 50]))
    batch_result = None
    if chunk_specs:
        batch_result = batch_get(
            config,
            auth_manager,
            [
                (rid, _table_chunk_url(work[idx][0], chunk, _table_source_fields(work[idx][0])))
                for rid, idx, chunk in chunk_specs
            ],
        )
        if batch_result is not None:
            http_requests += 1
    remote_by_work: Dict[int, Dict[str, Dict[str, Any]]] = {i: {} for i in range(len(work))}
    for rid, idx, chunk in chunk_specs:
        served = (batch_result or {}).get(rid)
        rows: Optional[List[Dict[str, Any]]] = None
        if served and served.get("status_code") == 200 and isinstance(served.get("body"), dict):
            rows = served["body"].get("result")
        if rows is None:
            table_name = work[idx][0]
            try:
                rows = _fetch_records_chunk(
                    config, auth_manager, table_name, chunk, _table_source_fields(table_name)
                )
            except (ValueError, OSError) as exc:
                # A failed fallback chunk must not abort the whole scan — its
                # records simply go unresolved and surface as 'missing_remote'.
                logger.warning("verdict scan: chunk fetch failed for %s: %s", table_name, exc)
                rows = []
            http_requests += 1
        for rec in rows or []:
            sid = str(rec.get("sys_id") or "")
            if sid:
                remote_by_work[idx][sid] = rec

    # Pass 3: verdicts (pure local content comparison).
    for idx, (table_name, table_dir, map_data) in enumerate(work):
        remote_by_id = remote_by_work[idx]
        for name in sorted(map_data):
            sys_id = str(map_data.get(name) or "")
            fields = _component_field_files(table_dir, name, table_name)
            if not fields:
                continue
            checked += 1
            remote_record = remote_by_id.get(sys_id)
            if remote_record is None:
                attention.append({"table": table_name, "name": name, "verdict": "missing_remote"})
                continue
            field_rows, states, sidecars = _component_field_verdicts(fields, remote_record)
            if not field_rows:
                in_sync += 1
                continue
            row: Dict[str, Any] = {
                "table": table_name,
                "name": name,
                "verdict": _aggregate_verdict(states),
                "fields": field_rows,
                "remote": _remote_record_state(remote_record),
            }
            if sidecars:
                row["conflict_sidecars"] = sidecars
            attention.append(row)
    result: Dict[str, Any] = {
        "mode": "verdict",
        "root": str(root),
        "components_checked": checked,
        "in_sync": in_sync,
        "needs_attention": attention[:_VERDICT_ATTENTION_CAP],
        # Speed evidence: how long the scan took and how many HTTP round trips
        # it cost (1 = the whole scan rode a single Batch API call).
        "took_ms": int((time.perf_counter() - started) * 1000),
        "http_requests": http_requests,
    }
    if len(attention) > _VERDICT_ATTENTION_CAP:
        result["truncated"] = (
            f"{len(attention) - _VERDICT_ATTENTION_CAP} more component(s) need attention — "
            f"narrow the path (scope or table dir) to see the rest."
        )
    if skipped_origin:
        result["skipped_other_instance"] = skipped_origin
        result["skipped_hint"] = (
            "These trees were downloaded from a DIFFERENT instance than the active one — "
            "verdicts against the wrong server would be misleading. Route the call with "
            "instance=<alias> (see list_instances), or compare across instances with "
            "compare_instances."
        )
    return result


# ---------------------------------------------------------------------------
# Tool 1: diff_local_component
# ---------------------------------------------------------------------------
@register_tool(
    "diff_local_component",
    params=DiffLocalComponentParams,
    description="Diff local edits vs remote, or vs a 2nd root (compare_to); verdict=True for status-only.",
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

    # compare_to mode: diff against a 2nd local download root (dev-vs-test),
    # not the live remote. Pure local — no network, no auth needed.
    if params.compare_to:
        compare_to = Path(params.compare_to).expanduser().resolve()
        return _diff_against_compare_to(path, compare_to, params.context_lines)

    # Verdict mode on a directory: batch-verify every component under it
    # (download root, scope root, or table dir). A record folder falls through
    # to the single-component verdict below.
    if params.verdict and path.is_dir():
        try:
            _resolve_local_path(path)
        except ValueError:
            return _verdict_scan(config, auth_manager, path)

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
        "sys_mod_count",
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
    me, me_confirmed = _resolve_push_actor(config, auth_manager)
    # Free attribution corroboration (same fetch + local baseline) so a handoff /
    # spoofed editor is visible at REVIEW time, before any push. No extra API.
    # 'me' is passed so YOUR OWN edit is never reported as an ownership handoff.
    attribution = describe_attribution(
        baseline_by=meta.get("sys_updated_by", ""),
        current_by=remote_updated_by,
        created_by=_display_str(remote_record.get("sys_created_by")),
        me=me,
        me_confirmed=me_confirmed,
    )
    # Content decides, the timestamp only hints — a bump with identical bodies
    # (your own push, a re-save) is a stale watermark, not "someone edited it".
    drift = _assess_server_drift(resolved, remote_record, local_updated_on, remote_updated_on)
    conflict_warning = None
    if drift["drifted"]:
        if attribution["self_edit"]:
            who = "You changed this on the server"
        elif remote_updated_by:
            who = f"{remote_updated_by} changed this on the server"
        else:
            who = "This changed on the server"
        fields = ", ".join(drift["moved_fields"]) if drift["moved_fields"] else "unverified"
        conflict_warning = (
            f"{who} at {remote_updated_on}, after your download (your local copy is from "
            f"{local_updated_on}; changed on the server: {fields}). Nothing has been "
            f"overwritten — review the diff before pushing."
        )

    # The stamp moved but every body still matches your baseline — say so plainly
    # instead of leaving a bare timestamp gap the reader has to interpret as a
    # conflict. (Typical cause: your own push, or an edit to a non-source field.)
    stale_watermark = None
    if drift["timestamp_only"]:
        stale_watermark = (
            f"The record's sys_updated_on moved to {remote_updated_on}, but every source body "
            f"is byte-identical to your baseline — no server-side source change. Not a conflict."
        )

    # 3-way separation (baseline-aware): tells YOUR edits apart from the
    # SERVER's changes so a mixed diff never has to be untangled by eye.
    three_way = _baseline_three_way(resolved, remote_record)

    # Verdict mode: status + line counts only, never diff bodies.
    if params.verdict:
        field_rows, states, sidecars = _component_field_verdicts(resolved.fields, remote_record)
        vres: Dict[str, Any] = {
            "mode": "verdict",
            "component": {
                "table": resolved.table,
                "sys_id": resolved.sys_id,
                "name": resolved.name,
            },
            "verdict": _aggregate_verdict(states),
            "remote": _remote_record_state(remote_record),
        }
        if field_rows:
            vres["fields"] = field_rows
        if sidecars:
            vres["conflict_sidecars"] = sidecars
        if three_way:
            vres["three_way"] = three_way
        if conflict_warning:
            vres["conflict_warning"] = conflict_warning
        if stale_watermark:
            vres["stale_watermark"] = stale_watermark
        if attribution["attribution"] != "consistent":
            vres["attribution"] = attribution
        if not resolved.instance_url:
            vres["origin_unverified"] = _ORIGIN_UNVERIFIED_MSG
        return vres

    diffs = _compute_field_diffs(resolved, remote_record, params.context_lines)

    result: Dict[str, Any] = {
        "mode": "diff",
        "component": {
            "table": resolved.table,
            "sys_id": resolved.sys_id,
            "name": resolved.name,
        },
        "conflict_warning": conflict_warning,
        "diffs": diffs,
        # Server-side edit evidence on EVERY diff — an all-'unchanged' result
        # must never read as "the server never moved" (it may mean a deploy
        # updated both sides; three_way/attribution carry the rest).
        "remote": _remote_record_state(remote_record),
    }
    if three_way:
        result["three_way"] = three_way
    if stale_watermark:
        result["stale_watermark"] = stale_watermark
    # Surface attribution only when it's NOT plain-consistent — token-lean: a
    # clean record adds nothing, a handoff/shared one shows the evidence.
    if attribution["attribution"] != "consistent":
        result["attribution"] = attribution
    if conflict_warning and remote_updated_by:
        result["remote_updated_by"] = remote_updated_by
    if not resolved.instance_url:
        result["origin_unverified"] = _ORIGIN_UNVERIFIED_MSG
    return result


def _compute_field_diffs(
    resolved, remote_record: Dict[str, Any], context_lines: int
) -> List[Dict[str, Any]]:
    """Per-field unified line diff (remote -> local), line-ending normalized.

    Read-only and network-free: callers pass an already-fetched remote_record.
    A pure CRLF<->LF delta reads as 'unchanged'; oversized diffs are truncated to
    MAX_DIFF_LINES for context safety. Shared by diff_local_component (review) and
    the push CONFLICT response, so a blocked push shows WHAT would change without a
    second round-trip — never a dead-end.
    """
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
                n=context_lines,
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
    return diffs


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
    description="Push one local edit back to ServiceNow (diff_local_component first). Targeted refresh, not bulk dev→test promotion.",
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
        matches = _resolve_target_by_name(
            config, auth_manager, resolved.table, resolved.remote_name, resolved.qualifier
        )
        # A qualifier that scopes the record to its parent (e.g. web service) —
        # shown in messages so the operator sees WHICH 'end' this is.
        qual_hint = (
            f" ({resolved.qualifier[0]}={resolved.qualifier[1]})" if resolved.qualifier else ""
        )
        if not matches:
            return {
                "error": "TARGET_NOT_FOUND",
                "message": (
                    f"No '{resolved.remote_name}'{qual_hint} record found on '{active}' "
                    f"({resolved.table}). Cross-instance deploy updates an existing record only "
                    f"— it never creates."
                ),
                "component": {"table": resolved.table, "name": resolved.remote_name},
            }
        if len(matches) > 1:
            return {
                "error": "TARGET_AMBIGUOUS",
                "message": (
                    f"{len(matches)} records named '{resolved.remote_name}'{qual_hint} on "
                    f"'{active}' ({resolved.table}) — can't pick the deploy target unambiguously."
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
            remote_name=resolved.remote_name,
            qualifier=resolved.qualifier,
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
        # full=True: raw untruncated GET. The default sn_query path clips any
        # field >50k chars (truncate_results), so a long body (e.g. a >50KB
        # widget client_script) would come back capped and compare against the
        # FULL local copy as a bogus "~100% replacement" conflict — the exact
        # asymmetry that made diff (full=True) and push disagree on the same
        # record. The comparison read MUST be untruncated, like diff_local_component.
        remote_record = _fetch_portal_component_record(
            config, auth_manager, resolved.table, resolved.sys_id, all_fields, full=True
        )
    except ValueError as e:
        return {"error": str(e)}

    # NOTE: no pre-flight protection BLOCK here. A Protected record
    # (sys_policy='read') limits the API but not necessarily this caller/scope (the
    # same record is UI-editable), so we never pre-refuse on our own guess — the
    # actual write goes through update_portal_component, which warns and lets the
    # SERVER decide. A genuine rejection surfaces there as a 403 with guidance.

    # 2. Baseline-drift verification gate — CONTENT-FIRST and TIME-INDEPENDENT.
    #    The question is "did the SERVER BODY move since my baseline", and only the
    #    pristine `_baseline/` snapshot can answer it: sys_updated_on also bumps for
    #    my own push, a re-save, or an edit to an unrelated field, and gating on the
    #    stamp alone turned a normal edit->push->edit-again round-trip into a fake
    #    "someone changed this" every time. So we hash the remote bodies against the
    #    baseline; the stamp is only the fallback when no baseline exists (legacy
    #    tree) — never a silent pass. Being the last editor yourself does NOT skip
    #    the comparison; it only changes the wording (see assess_push_risk).
    #    The point is VERIFICATION, not a hard block: it stops a blind push by
    #    showing WHAT moved, WHO moved it and WHEN, so force=true is a deliberate
    #    "yes, overwrite that" — never silent. (Pushing to the wrong INSTANCE is the
    #    separate, hard _validate_instance_url block above.)
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

    # The baseline lives in _sync_meta / _baseline from the ORIGIN download, so it
    # is only meaningful for a same-instance round-trip. For a cross-instance deploy
    # the target was re-resolved by name (already verified), so skip the drift gate.
    drift = _assess_server_drift(resolved, remote_record, local_updated_on, remote_updated_on)
    drifted = not cross_instance_deploy and drift["drifted"]

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

    # Force-CAS: force approves overwriting exactly the version the caller
    # REVIEWED. If the server moved again between review and push, the approval
    # is stale — re-block with fresh info instead of overwriting an unseen edit.
    # ServiceNow's own sys_update_version history covers recovery of the
    # overwritten body, so no local backup is taken.
    if params.force and params.confirm_overwrite_updated_on:
        if params.confirm_overwrite_updated_on != remote_updated_on:
            by = f" by {remote_updated_by}" if remote_updated_by else ""
            return {
                "error": "FORCE_CONFIRM_STALE",
                "message": (
                    f"You approved overwriting the version of {params.confirm_overwrite_updated_on}, "
                    f"but the server is now at {remote_updated_on}{by} — it changed again after "
                    f"your review. Look at the fresh diff below, then re-push with "
                    f"confirm_overwrite_updated_on='{remote_updated_on}' if you still mean it."
                ),
                "risk": risk,
                "remote_updated_by": remote_updated_by,
                "remote_updated_on": remote_updated_on,
                "component": {
                    "table": resolved.table,
                    "sys_id": resolved.sys_id,
                    "name": resolved.name,
                },
                "diffs": _compute_field_diffs(resolved, remote_record, _CONFLICT_DIFF_CONTEXT),
            }

    if drifted:
        if not params.force:
            component_info = {
                "table": resolved.table,
                "sys_id": resolved.sys_id,
                "name": resolved.name,
            }
            error_code = "CONFLICT_OTHER_USER" if confirmed_other else "CONFLICT"
            # LIVE re-check: the drift gate compares against the local download
            # baseline, which can be stale. Frame the decision on the CURRENT
            # remote hold, not on who held it at download time — a hold that was
            # true at download but has since been committed must read as released.
            live_hold = _record_update_set_hold(
                config, auth_manager, resolved.table, resolved.sys_id, me
            )
            if live_hold:
                live_note = (
                    f" LIVE: still held by '{live_hold['held_by']}' in the uncommitted update "
                    f"set '{live_hold['update_set']}' — force=true would overwrite their "
                    "in-progress work."
                )
            else:
                live_note = (
                    " LIVE: no one is holding this record now (the change that moved it is "
                    "committed/released). If your local copy is the intended final, this is a "
                    "clean fast-forward — force=true is safe."
                )
            message = (
                f"{risk['message']} (server: {remote_updated_on}, your copy: {local_updated_on})."
                f"{live_note} To overwrite exactly this reviewed version, push again with "
                f"force=true confirm_overwrite_updated_on='{remote_updated_on}' (re-blocks if "
                f"the server moves again; the overwritten body stays recoverable in the "
                f"server's version history). Or re-download to take the latest instead."
            )
            return {
                "error": error_code,
                "message": message,
                "risk": risk,
                "remote_updated_by": remote_updated_by,
                "remote_updated_on": remote_updated_on,
                "local_downloaded_on": local_updated_on,
                "record_hold": live_hold,
                "component": component_info,
                # WHICH bodies the server actually moved (content-verified), so the
                # block is never a bare timestamp assertion the caller must trust.
                "server_changed_fields": drift["moved_fields"],
                "drift_verified_by": "content" if drift["verifiable"] else "timestamp",
                # P1-1: the line-level diff of what THIS push would overwrite, from
                # the already-fetched remote_record (no extra round-trip). Lets the
                # caller decide force=true vs re-download without re-diffing.
                "diffs": _compute_field_diffs(resolved, remote_record, _CONFLICT_DIFF_CONTEXT),
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
        result_nc: Dict[str, Any] = {
            "message": "No changes to push — local files match remote.",
            "component": {
                "table": resolved.table,
                "sys_id": resolved.sys_id,
                "name": resolved.name,
            },
        }
        # The watermark lagged while the bodies never diverged (a stamp bump from
        # your own push / an unrelated field). Local provably equals remote here —
        # update_data is empty — so advancing it is safe and stops the phantom
        # "changed on the server" from resurfacing on every later diff.
        if drift["timestamp_only"] and not cross_instance_deploy:
            _record_sync_meta(
                table_dir, resolved.name, resolved.sys_id, remote_updated_on, remote_updated_by
            )
            result_nc["stale_watermark_refreshed"] = remote_updated_on
        return result_nc

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

        # Record-level LIVE hold: is THIS record currently held in someone else's
        # uncommitted update set? (Membership — not the scope-wide list above, and
        # not the local download baseline.) This is the signal a human sees in the
        # UI banner "modified in update set X by <user>, not committed" — the one
        # the time-window concurrent guard misses when the edit is old.
        record_hold: Optional[Dict[str, str]] = None
        if is_acl:
            record_hold = _record_update_set_hold(
                config, auth_manager, resolved.table, resolved.sys_id, me
            )

        if is_acl:
            # Report the FACTS, not a guessed cause. A Table-API 403 does not tell
            # us WHY, so we lead with what is certain, name the most-likely cause
            # for this table type, and give a remedy that holds regardless of cause.
            # The record_hold is surfaced as CONTEXT — an open update set tracks
            # changes, it does not by itself lock a record against a write, so it is
            # deliberately NOT presented as the cause (that sent users chasing the
            # wrong fix).
            is_sp = resolved.table.startswith("sp_")
            parts = [
                f"HTTP 403: ServiceNow received the Table-API write to "
                f"{resolved.table}/{resolved.sys_id} on '{active}' and rejected it. Local files "
                "and _sync_meta are UNCHANGED. A Table-API 403 does not report its own cause."
            ]
            if is_sp:
                parts.append(
                    f"Most likely cause: '{resolved.table}' is a Service Portal table whose write "
                    "is gated by protections beyond role/ACL — a script-field source-context "
                    "(Referer) check, sys_policy record protection, or a condition-scripted field "
                    "ACL — that the generic Table API cannot satisfy. This routinely passes on one "
                    "instance and 403s on another with identical roles (works on dev, blocked on "
                    "test)."
                )
            else:
                parts.append(
                    "Likely cause: the account lacks write ACL on this table/scope on the target "
                    "instance — verify roles. The session scope was already aligned, so do NOT "
                    "blindly retry."
                )
            if record_hold:
                parts.append(
                    f"Context (NOT a confirmed cause): this record was last changed by "
                    f"'{record_hold['held_by']}' in the still-open update set "
                    f"'{record_hold['update_set']}'. An open update set only TRACKS changes; it "
                    "does not by itself lock a record against a Table-API write — so do not assume "
                    "closing it will unblock this push."
                )
            remedy = (
                "Reliable paths (independent of the exact cause): "
                + (
                    "edit this record in the SP Designer UI on that instance (the UI carries the "
                    "source-context the Table API lacks), or "
                    if is_sp
                    else "edit this record in the ServiceNow UI on that instance, or "
                )
                + "promote via an Update Set — commit the change on the source (manage_changeset), "
                "then retrieve + commit it on the target in the UI."
            )
            parts.append(remedy)
            hint = " ".join(parts)
        else:
            hint = (
                "Remote rejected the write. Local files and _sync_meta are UNCHANGED; "
                "resolve the error and retry."
            )
        response: Dict[str, Any] = {
            "success": False,
            "error": result.get("error", "Push rejected by ServiceNow."),
            "status": status,
            "target_instance": active,
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
        if record_hold:
            response["record_hold"] = record_hold
        return response

    # 5. Post-write LANDING VERIFICATION. A non-error return from the Table API
    #    does NOT prove the field content persisted: sp_* Service Portal tables can
    #    accept the write, return success, yet silently drop a script field
    #    (source-context / protection-policy checks that differ per instance —
    #    "works on dev, silently no-ops on test"). sys_mod_count bumping is NOT
    #    proof the content landed. So we re-read the ACTUAL pushed fields and
    #    recompute the same diff that decided the push: if any field we just pushed
    #    still differs from local, the write did not land — report success:false
    #    LOUDLY and do NOT poison _sync_meta/baseline (a poisoned baseline makes the
    #    next diff falsely say "no drift", hiding the non-landing forever).
    #    sys_updated_by rides this same re-read at no extra cost — it becomes the
    #    baseline OWNER recorded in step 5b.
    verify_fields = list(update_data.keys()) + ["sys_updated_on", "sys_updated_by"]
    fresh_remote: Optional[Dict[str, Any]] = None
    try:
        # full=True: same untruncated read as the pre-push gate — a >50k field
        # clipped by sn_query would still differ from the full local copy after a
        # perfect push and raise a false WRITE_NOT_LANDED.
        fresh_remote = _fetch_portal_component_record(
            config, auth_manager, resolved.table, resolved.sys_id, verify_fields, full=True
        )
    except ValueError as e:
        logger.warning("Post-write landing verification could not re-read record: %s", e)

    if fresh_remote is not None:
        still_diff, _, _ = _build_update_data_and_magnitude(resolved, fresh_remote)
        not_landed = [f for f in update_data if f in still_diff]
        if not_landed:
            return {
                "success": False,
                "landed": False,
                "error": "WRITE_NOT_LANDED",
                "message": (
                    f"ServiceNow accepted the write (no HTTP error) but {len(not_landed)} "
                    f"field(s) did NOT persist on '{active}': {', '.join(not_landed)}. This is the "
                    f"silent non-landing sp_* Service Portal tables exhibit when a write is "
                    f"accepted but a protection / source-context check drops the field content — "
                    f"sys_mod_count may have bumped anyway, which is NOT proof of landing. Local "
                    f"files and _sync_meta are UNCHANGED. Edit this record in the SP Designer UI on "
                    f"'{active}', or promote via an Update Set instead of a per-record Table-API write."
                ),
                "target_instance": active,
                "fields_not_landed": not_landed,
                "component": {
                    "table": resolved.table,
                    "sys_id": resolved.sys_id,
                    "name": resolved.name,
                },
                "sync_meta_updated": False,
            }

    # 5b. Landing confirmed (or unverifiable) → record the new baseline watermark:
    #     the timestamp AND the editor. Dropping sys_updated_by here is what made a
    #     settled push re-litigate itself: the next diff compared the current editor
    #     (you) against a baseline owner still holding the ORIGINAL author's name,
    #     and reported an "ownership change" for the edit you had just made.
    try:
        _record_sync_meta(
            table_dir,
            resolved.name,
            resolved.sys_id,
            str((fresh_remote or {}).get("sys_updated_on") or ""),
            _display_str((fresh_remote or {}).get("sys_updated_by")) or me,
        )
    except Exception as e:
        logger.warning("Failed to update _sync_meta.json after push: %s", e)

    # The pushed local content is the new common ancestor for 3-way download
    # decisions; a leftover .remote conflict sidecar is resolved by this push.
    try:
        for field_name, fpath in resolved.fields.items():
            if field_name in update_data and fpath.exists():
                write_baseline_for(fpath, fpath.read_text(encoding="utf-8"))
                cleanup_remote_sidecar(fpath)
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("Failed to refresh baseline snapshots after push: %s", e)

    # 6. Enrich result (reached only on a confirmed successful push). target_instance
    #    is echoed at top level so the operator/LLM SEES which instance actually
    #    received the write — the whole point of the multi-instance safety story is
    #    that "where did it land" must never be implicit. landed reflects whether the
    #    post-write re-read confirmed the content (True) or could not be verified
    #    (re-read failed → "unverified"), never a bare optimistic success.
    result["success"] = True
    result["landed"] = True if fresh_remote is not None else "unverified"
    result["target_instance"] = active
    result["risk"] = risk
    result["local_sync"] = {
        "pushed_from": str(path),
        "fields_pushed": list(update_data.keys()),
        "sync_meta_updated": True,
    }
    if not resolved.instance_url:
        result["origin_unverified"] = _ORIGIN_UNVERIFIED_MSG
    return result
