"""manage_widget_dependency — unified CRUD for Service Portal widget
dependencies and Angular providers.

Read actions (list/get) delegate to the internal resolvers that used to be
standalone tools (get_provider_dependency_map, resolve_widget_chain,
resolve_page_dependencies). Write actions touch ONLY the dependency/provider
records and their m2m links to a widget — never the widget body. Widget /
provider script bodies stay with manage_portal_component, which is local-first
(download -> edit -> diff -> push); this tool is direct remote structure CRUD.
"""

import logging
from typing import Any, ClassVar, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool

logger = logging.getLogger(__name__)

# Record tables (the dependency/provider definitions).
RECORD_TABLE = {"provider": "sp_angular_provider", "dependency": "sp_dependency"}
# Junction tables (widget <-> record links). NOTE: the provider junction table
# name varies by ServiceNow release, so link/unlink/list resolve it at runtime
# via _m2m_table_for() -> resolve_angular_provider_m2m(); this dict's provider
# entry is only a fallback default (the canonical modern name).
M2M_TABLE = {
    "provider": "m2m_sp_ng_pro_sp_widget",
    "dependency": "m2m_sp_widget_dependency",
}
# The reference column on each junction table that points at the record.
M2M_REF_FIELD = {"provider": "sp_angular_provider", "dependency": "sp_dependency"}


def _m2m_table_for(config: ServerConfig, auth_manager: AuthManager, target: str) -> str:
    """Junction table for a link target. The provider junction is resolved
    against the live instance (its name differs by ServiceNow release)."""
    if target == "provider":
        from .portal_dev_tools import resolve_angular_provider_m2m

        return resolve_angular_provider_m2m(config, auth_manager)
    return M2M_TABLE[target]


MAX_DEP_WIDGETS = 30
M2M_IN_CHUNK = 50


class ManageWidgetDependencyParams(BaseModel):
    """Manage widget Angular providers & CSS/JS dependencies.

    Required per action:
      list:   widget_ids|scope|developer (provider/dependency) or page_id (page)
      get:    record_id, or widget_id for a source chain
      create: name
      update: record_id + (name|module|fields)
      delete: record_id
      link:   widget_id + record_id
      unlink: widget_id + record_id
    """

    action: str = Field(..., description="list|get|create|update|delete|link|unlink")
    target: str = Field(default="provider", description="provider|dependency|page (page=read only)")

    widget_ids: Optional[List[str]] = Field(
        default=None, description="Widget sys_id/id/name filter"
    )
    widget_id: Optional[str] = Field(default=None, description="Single widget for get/link/unlink")
    page_id: Optional[str] = Field(default=None, description="Page sys_id or path (target=page)")
    record_id: Optional[str] = Field(default=None, description="Provider/dependency sys_id")
    scope: Optional[str] = Field(default=None, description="App scope filter (list)")
    developer: Optional[str] = Field(default=None, description="sys_updated_by filter (list)")

    name: Optional[str] = Field(default=None, description="Record name (create/update)")
    module: Optional[str] = Field(default=None, description="Angular module name (sp_dependency)")
    fields: Optional[Dict[str, Any]] = Field(default=None, description="Extra record fields")

    include_source: bool = Field(default=False, description="Include script bodies (read)")
    include_si_refs: bool = Field(default=True, description="Extract Script Include refs (read)")
    depth: int = Field(default=2, description="Chain depth 1-3 (source/page read)")
    max_widgets: int = Field(default=10, description="Max widgets to process (list)")
    save_to_disk: bool = Field(default=False, description="Save page sources to ./temp (page)")
    dry_run: bool = Field(default=False)

    _VALID_ACTIONS: ClassVar[frozenset] = frozenset(
        {"list", "get", "create", "update", "delete", "link", "unlink"}
    )
    _VALID_TARGETS: ClassVar[frozenset] = frozenset({"provider", "dependency", "page"})

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset(
            {
                "target",
                "widget_ids",
                "page_id",
                "scope",
                "developer",
                "include_source",
                "include_si_refs",
                "depth",
                "max_widgets",
                "save_to_disk",
            }
        ),
        "get": frozenset({"target", "record_id", "widget_id", "include_source", "depth"}),
        "create": frozenset({"target", "name", "module", "fields", "dry_run"}),
        "update": frozenset({"target", "record_id", "name", "module", "fields", "dry_run"}),
        "delete": frozenset({"target", "record_id", "dry_run"}),
        "link": frozenset({"target", "widget_id", "record_id", "dry_run"}),
        "unlink": frozenset({"target", "widget_id", "record_id", "dry_run"}),
    }

    @model_validator(mode="after")
    def _validate(self) -> "ManageWidgetDependencyParams":
        if self.action not in self._VALID_ACTIONS:
            raise ValueError(f"action must be one of {sorted(self._VALID_ACTIONS)}")
        if self.target not in self._VALID_TARGETS:
            raise ValueError(f"target must be one of {sorted(self._VALID_TARGETS)}")

        write_actions = {"create", "update", "delete", "link", "unlink"}
        if self.action in write_actions and self.target == "page":
            raise ValueError("target='page' is read-only (list/get).")

        if self.action == "list":
            if self.target == "page":
                if not self.page_id:
                    raise ValueError("page_id is required for action='list' target='page'")
            elif not (self.widget_ids or self.scope or self.developer):
                raise ValueError("one of widget_ids/scope/developer is required for action='list'")
        elif self.action == "get":
            if not (self.record_id or self.widget_id):
                raise ValueError("record_id or widget_id is required for action='get'")
        elif self.action == "create":
            if not self.name:
                raise ValueError("name is required for action='create'")
        elif self.action == "update":
            if not self.record_id:
                raise ValueError("record_id is required for action='update'")
            if not (self.name or self.module or self.fields):
                raise ValueError("name, module, or fields is required for action='update'")
        elif self.action == "delete":
            if not self.record_id:
                raise ValueError("record_id is required for action='delete'")
        elif self.action in ("link", "unlink"):
            if not (self.widget_id and self.record_id):
                raise ValueError(f"widget_id and record_id are required for action='{self.action}'")
        return self


def _ref_value(value: Any) -> str:
    """Flatten a reference field that may be a {'value': ..., 'display_value': ...} dict.

    Prefers the 'value' (sys_id) key when present — even if empty — so a blank
    reference never silently leaks the display name into a sys_id query.
    """
    if isinstance(value, dict):
        if "value" in value:
            return str(value.get("value") or "")
        return str(value.get("display_value") or "")
    return str(value or "")


def _escape(value: str) -> str:
    return str(value).replace("^", "^^").replace("=", r"\=").replace("@", r"\@")


def _widget_refs(params: ManageWidgetDependencyParams) -> List[str]:
    """All widget references from widget_ids and a single widget_id (get)."""
    refs = list(params.widget_ids or [])
    if params.widget_id and params.widget_id not in refs:
        refs.append(params.widget_id)
    return refs


def _widget_filter_query(params: ManageWidgetDependencyParams) -> Optional[str]:
    parts: List[str] = []
    refs = _widget_refs(params)
    if refs:
        ids = ",".join(refs)
        parts.append(f"sys_idIN{ids}^ORidIN{ids}^ORnameIN{ids}")
    if params.scope:
        parts.append(f"sys_scope.scope={_escape(params.scope)}")
    if params.developer:
        parts.append(f"sys_updated_by={_escape(params.developer)}")
    return "^".join(parts) if parts else None


def _table_write(
    config: ServerConfig,
    auth_manager: AuthManager,
    table: str,
    action: str,
    sys_id: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Table-API create/update/delete, mirroring sn_write's HTTP contract."""
    from .sn_api import _safe_json

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "table": table,
            "action": action,
            "sys_id": sys_id,
            "fields": fields,
            "message": "Preview only — no changes committed.",
        }

    base = f"{config.instance_url}/api/now/table/{table}"
    try:
        if action == "create":
            resp = auth_manager.make_request("POST", base, json=fields, timeout=config.timeout)
        elif action == "update":
            resp = auth_manager.make_request(
                "PATCH", f"{base}/{sys_id}", json=fields, timeout=config.timeout
            )
        else:  # delete
            resp = auth_manager.make_request("DELETE", f"{base}/{sys_id}", timeout=config.timeout)
        resp.raise_for_status()
    except Exception as exc:
        return {
            "success": False,
            "table": table,
            "action": action,
            "sys_id": sys_id,
            "error": f"{action} failed: {exc}",
            "hint": (
                "Verify the record_id exists (action=get) and that the active "
                "instance allows writes. For a sys_id lookup use action=list."
            ),
        }

    body = _safe_json(resp) if action != "delete" else {}
    new_sys_id = sys_id or (body.get("result") or {}).get("sys_id")
    return {
        "success": True,
        "table": table,
        "action": action,
        "sys_id": new_sys_id,
        "result": body.get("result") if action != "delete" else None,
        "message": f"{action} on {table} succeeded (sys_id={new_sys_id}).",
    }


def _resolve_widget_sys_id(
    config: ServerConfig, auth_manager: AuthManager, widget_ref: Optional[str]
) -> Optional[str]:
    from .portal_dev_tools import _sn_get

    if not widget_ref:
        return None
    query = f"sys_id={widget_ref}^ORid={widget_ref}^ORname={widget_ref}"
    rows, _ = _sn_get(config, auth_manager, "sp_widget", query, "sys_id", limit=1)
    if rows:
        return _ref_value(rows[0].get("sys_id"))
    return None


def _build_record_fields(params: ManageWidgetDependencyParams) -> Dict[str, Any]:
    """Merge convenience params (name/module) with the raw `fields` escape hatch.

    `fields` is applied LAST so the caller can override anything explicitly.
    `module` is a sp_dependency-only column; ignored for providers (a provider
    has no module — pass it via `fields` if a future column ever needs it).
    """
    out: Dict[str, Any] = {}
    if params.name:
        out["name"] = params.name
    if params.module and params.target == "dependency":
        out["module"] = params.module
    if params.fields:
        out.update(params.fields)
    return out


def _get_record(
    config: ServerConfig, auth_manager: AuthManager, table: str, record_id: str
) -> Dict[str, Any]:
    """Fetch a single provider/dependency record by sys_id (action=get)."""
    from .portal_dev_tools import _compact_record, _sn_get

    fields = "sys_id,name,sys_scope,sys_updated_on,sys_updated_by"
    if table == "sp_dependency":
        fields += ",module"
    rows, _ = _sn_get(config, auth_manager, table, f"sys_id={record_id}", fields, limit=1)
    if not rows:
        return {
            "success": False,
            "table": table,
            "error": f"{table} record '{record_id}' not found.",
            "hint": "Use action=list to find valid sys_ids.",
        }
    # _compact_record strips empty fields + flattens display_value (token saving).
    return {"success": True, "table": table, "record": _compact_record(rows[0])}


def _list_dependencies(
    config: ServerConfig, auth_manager: AuthManager, params: ManageWidgetDependencyParams
) -> Dict[str, Any]:
    """Widget -> CSS/JS dependency (sp_dependency) metadata map."""
    from .portal_dev_tools import _chunk, _sn_get

    widget_query = _widget_filter_query(params)
    if not widget_query:
        return {
            "success": False,
            "error": "widget_ids, scope, or developer is required.",
            "hint": "Provide widget_ids=[...] (sys_id/id/name) or a scope/developer filter.",
        }

    safe_max = min(max(1, params.max_widgets), MAX_DEP_WIDGETS)
    api_calls = 0
    try:
        widgets, _ = _sn_get(
            config, auth_manager, "sp_widget", widget_query, "sys_id,name", limit=safe_max
        )
        api_calls += 1
    except Exception as exc:
        return {
            "success": False,
            "error": f"Failed to fetch widgets: {exc}",
            "hint": (
                "Check the widget filter and that the active instance is reachable. "
                "If the instance is unreachable, answer OFFLINE from a prior download "
                "(0 API) with query_local_graph(question='used_by'|'uses'|'impact', "
                "name=<widget>)."
            ),
            "offline_alternative": "query_local_graph",
        }

    widget_ids = [_ref_value(w.get("sys_id")) for w in widgets if w.get("sys_id")]
    name_by_id = {_ref_value(w.get("sys_id")): w.get("name", "") for w in widgets}

    warnings: List[str] = []
    widget_dep_map: Dict[str, List[str]] = {}
    all_dep_ids: List[str] = []
    for chunk in _chunk(widget_ids, M2M_IN_CHUNK):
        try:
            rows, _ = _sn_get(
                config,
                auth_manager,
                "m2m_sp_widget_dependency",
                "sp_widgetIN" + ",".join(chunk),
                "sys_id,sp_widget,sp_dependency",
                limit=500,
            )
            api_calls += 1
        except Exception as exc:
            logger.warning("m2m_sp_widget_dependency chunk fetch failed: %s", exc)
            warnings.append(f"dependency link lookup failed for {len(chunk)} widget(s): {exc}")
            continue
        for row in rows:
            w_id = _ref_value(row.get("sp_widget"))
            d_id = _ref_value(row.get("sp_dependency"))
            if w_id and d_id:
                widget_dep_map.setdefault(w_id, []).append(d_id)
                if d_id not in all_dep_ids:
                    all_dep_ids.append(d_id)

    deps_by_id: Dict[str, Dict[str, Any]] = {}
    for chunk in _chunk(all_dep_ids, M2M_IN_CHUNK):
        try:
            rows, _ = _sn_get(
                config,
                auth_manager,
                "sp_dependency",
                "sys_idIN" + ",".join(chunk),
                "sys_id,name,module",
                limit=len(chunk),
            )
            api_calls += 1
        except Exception as exc:
            logger.warning("sp_dependency detail fetch failed: %s", exc)
            warnings.append(f"dependency detail lookup failed for {len(chunk)} record(s): {exc}")
            continue
        for d in rows:
            deps_by_id[_ref_value(d.get("sys_id"))] = {
                "sys_id": _ref_value(d.get("sys_id")),
                "name": d.get("name", ""),
                "module": d.get("module", ""),
            }

    dependency_map = [
        {
            "widget": {"sys_id": w_id, "name": name_by_id.get(w_id, "")},
            "dependencies": [
                deps_by_id.get(d_id, {"sys_id": d_id}) for d_id in widget_dep_map[w_id]
            ],
        }
        for w_id in widget_ids
        if w_id in widget_dep_map
    ]
    result: Dict[str, Any] = {
        "success": True,
        "summary": {
            "widgets": len(widgets),
            "dependencies": len(all_dep_ids),
            "api_calls": api_calls,
        },
        "dependency_map": dependency_map,
    }
    if warnings:
        result["warnings"] = warnings
    return result


def _read(
    config: ServerConfig, auth_manager: AuthManager, params: ManageWidgetDependencyParams
) -> Dict[str, Any]:
    if params.target == "page":
        from .portal_tools import ResolvePageDependenciesParams, resolve_page_dependencies

        return resolve_page_dependencies(
            config,
            auth_manager,
            ResolvePageDependenciesParams(
                page_id=params.page_id or "",
                depth=params.depth,
                save_to_disk=params.save_to_disk,
            ),
        )

    # Single record detail by sys_id (action=get, record_id only).
    if params.record_id and not params.widget_id:
        return _get_record(config, auth_manager, RECORD_TABLE[params.target], params.record_id)

    # Explicit source bodies for a single widget (the only trigger for the
    # heavy source chain — plain list/get stay metadata-only for token economy).
    if params.include_source:
        wid = params.widget_id or (params.widget_ids[0] if params.widget_ids else None)
        if not wid:
            return {
                "success": False,
                "error": "widget_id (or one widget_ids) is required with include_source.",
                "hint": "Set widget_id=<sys_id|id|name>, or drop include_source for the metadata graph.",
            }
        from .portal_tools import ResolveWidgetChainParams, resolve_widget_chain

        return resolve_widget_chain(
            config, auth_manager, ResolveWidgetChainParams(widget_id=wid, depth=params.depth)
        )

    # Metadata graph (no script bodies). widget_id (get) folds into the filter.
    if params.target == "provider":
        from .portal_dev_tools import GetProviderDependencyMapParams, get_provider_dependency_map

        return get_provider_dependency_map(
            config,
            auth_manager,
            GetProviderDependencyMapParams(
                widget_ids=_widget_refs(params) or None,
                scope=params.scope,
                developer=params.developer,
                include_script_include_refs=params.include_si_refs,
                max_widgets=params.max_widgets,
            ),
        )

    # target == "dependency" — _widget_filter_query already folds in widget_id.
    return _list_dependencies(config, auth_manager, params)


def _link(
    config: ServerConfig, auth_manager: AuthManager, params: ManageWidgetDependencyParams
) -> Dict[str, Any]:
    from .portal_dev_tools import _sn_get

    m2m = _m2m_table_for(config, auth_manager, params.target)
    ref_field = M2M_REF_FIELD[params.target]
    w_sys = _resolve_widget_sys_id(config, auth_manager, params.widget_id)
    if not w_sys:
        return {
            "success": False,
            "error": f"Widget '{params.widget_id}' not found.",
            "hint": "Pass a valid widget sys_id, id, or name. Use action=list to discover widgets.",
        }

    query = f"sp_widget={w_sys}^{ref_field}={params.record_id}"
    existing, _ = _sn_get(config, auth_manager, m2m, query, "sys_id", limit=1)
    if existing:
        out = {
            "success": True,
            "table": m2m,
            "action": "link",
            "noop": True,
            "sys_id": _ref_value(existing[0].get("sys_id")),
            "message": "Link already exists — no change.",
        }
        if params.dry_run:
            out["dry_run"] = True
        return out
    return _table_write(
        config,
        auth_manager,
        m2m,
        "create",
        fields={"sp_widget": w_sys, ref_field: params.record_id},
        dry_run=params.dry_run,
    )


def _unlink(
    config: ServerConfig, auth_manager: AuthManager, params: ManageWidgetDependencyParams
) -> Dict[str, Any]:
    from .portal_dev_tools import _sn_get

    m2m = _m2m_table_for(config, auth_manager, params.target)
    ref_field = M2M_REF_FIELD[params.target]
    w_sys = _resolve_widget_sys_id(config, auth_manager, params.widget_id)
    if not w_sys:
        return {
            "success": False,
            "error": f"Widget '{params.widget_id}' not found.",
            "hint": "Pass a valid widget sys_id, id, or name. Use action=list to discover widgets.",
        }

    query = f"sp_widget={w_sys}^{ref_field}={params.record_id}"
    rows, _ = _sn_get(config, auth_manager, m2m, query, "sys_id", limit=100)
    if not rows:
        return {
            "success": True,
            "table": m2m,
            "action": "unlink",
            "noop": True,
            "message": "No matching link.",
        }
    if params.dry_run:
        return {
            "success": True,
            "dry_run": True,
            "table": m2m,
            "action": "unlink",
            "message": f"Would delete {len(rows)} link row(s).",
        }
    deleted: List[str] = []
    failed: List[str] = []
    for row in rows:
        sid = _ref_value(row.get("sys_id"))
        res = _table_write(config, auth_manager, m2m, "delete", sys_id=sid)
        (deleted if res.get("success") else failed).append(sid)
    result: Dict[str, Any] = {
        "success": not failed,
        "table": m2m,
        "action": "unlink",
        "deleted": deleted,
    }
    if failed:
        result["failed"] = failed
        result["error"] = f"{len(failed)} of {len(rows)} link row(s) failed to delete."
    return result


@register_tool(
    name="manage_widget_dependency",
    params=ManageWidgetDependencyParams,
    description="CRUD + link/unlink for widget Angular providers & CSS/JS dependencies. Use action=list first for sys_ids.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_widget_dependency(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageWidgetDependencyParams,
) -> Dict[str, Any]:
    if params.action in ("list", "get"):
        return _read(config, auth_manager, params)

    if params.action == "link":
        return _link(config, auth_manager, params)
    if params.action == "unlink":
        return _unlink(config, auth_manager, params)

    table = RECORD_TABLE[params.target]
    if params.action == "create":
        result = _table_write(
            config,
            auth_manager,
            table,
            "create",
            fields=_build_record_fields(params),
            dry_run=params.dry_run,
        )
        if result.get("success") and not result.get("dry_run"):
            result["next"] = (
                f"Record created. Attach it to a widget with action=link, "
                f"target={params.target}, widget_id=<widget>, record_id={result.get('sys_id')}."
            )
        return result
    if params.action == "update":
        return _table_write(
            config,
            auth_manager,
            table,
            "update",
            sys_id=params.record_id,
            fields=_build_record_fields(params),
            dry_run=params.dry_run,
        )
    # delete
    return _table_write(
        config, auth_manager, table, "delete", sys_id=params.record_id, dry_run=params.dry_run
    )
