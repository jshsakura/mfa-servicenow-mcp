"""
ServiceNow MCP Server

This module provides the main implementation of the ServiceNow MCP server.
"""

import contextlib
import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional, Union

import anyio
import mcp.types as types
import yaml
from mcp.server.lowlevel import Server
from pydantic import AnyUrl, ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.resources.skill_resources import build_tool_to_skills_map, load_skills
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.chromium import check_chromium_install_hint
from servicenow_mcp.utils.config import (
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    OAuthConfig,
    ServerConfig,
)
from servicenow_mcp.utils.instances import (
    ACTIVE_INSTANCE_ENV,
    INSTANCE_CONFIG_ENV,
    build_instance_definition,
    coerce_bool,
    load_instance_config_env,
    safe_instance_url,
    select_active_alias,
)
from servicenow_mcp.utils.progress import use_progress_emitter
from servicenow_mcp.utils.tool_utils import get_tool_definitions

logger = logging.getLogger(__name__)

FastMCP = Server

# Tools heavy enough that streaming mid-call progress is worth a worker thread.
# MUST be pure data tools — NEVER browser/auth tools, which have to run on the
# event-loop thread (Playwright requires the thread that created its loop). The
# whitelist is the hard guarantee behind that invariant; see CLAUDE.md's note on
# why asyncio.to_thread() was removed for the default dispatch path.
PROGRESS_STREAMING_TOOLS = frozenset({"download_app_sources", "audit_local_sources"})

# Deprecated tool name -> current name. Routed at call time but NOT advertised in
# list_tools, so an old name keeps working without cluttering the tool surface.
_DEPRECATED_TOOL_ALIASES = {"download_sources": "download_server_sources"}


def _should_stream_progress(name: str, progress_token: Optional[Union[str, int]]) -> bool:
    """Stream progress only when the client subscribed (token present) AND the
    tool is a whitelisted heavy data tool. Everything else keeps the legacy
    synchronous on-loop path — zero behaviour change."""
    return progress_token is not None and name in PROGRESS_STREAMING_TOOLS


# Define path for the configuration file
TOOL_PACKAGE_CONFIG_PATH = os.getenv("TOOL_PACKAGE_CONFIG_PATH", "config/tool_packages.yaml")

MUTATING_TOOL_PREFIXES = (
    "create_",
    "update_",
    "delete_",
    "remove_",
    "add_",
    "move_",
    "activate_",
    "deactivate_",
    "commit_",
    "publish_",
    "submit_",
    "approve_",
    "reject_",
    "resolve_",
    "reorder_",
    "execute_",
    "assign_",
    # All manage_X tools are write bundles. Read-only sub-actions (e.g. future
    # manage_user.action='list') get exempted via the per-action allowlist
    # below — keep this list tight to that.
    "manage_",
)
# manage_<X>: per-tool set of action values that are read-only (no confirm).
# Bundles whose actions are all writes (incident/change/kb_article/changeset/
# script_include/workflow) don't appear here — the prefix gate applies.
MANAGE_READ_ACTIONS: Dict[str, set[str]] = {
    "manage_incident": {"get"},
    "manage_change": {"get"},
    "manage_changeset": {"get"},
    "manage_user": {"get", "list"},
    "manage_group": {"list"},
    "manage_workflow": {"list", "get", "list_versions", "get_activities"},
    "manage_script_include": {"list", "get"},
    "manage_widget_dependency": {"list", "get"},
    "manage_catalog": {"list_items", "get_item", "list_categories", "list_item_variables"},
    "manage_kb_article": {"list_kbs", "list_articles", "get_article", "list_categories"},
    "manage_flow_designer": {
        "list",
        "get_detail",
        "get_executions",
        "compare",
        "edit_status",
        "get_action_source",
    },
    "manage_project": {"list"},
    "manage_epic": {"list"},
    "manage_scrum_task": {"list"},
    "manage_story": {"list", "list_dependencies"},
}
# Tools that need confirmation but don't match a prefix above.
MUTATING_TOOL_NAMES = {"sn_batch", "sn_write"}

INSTANCE_HELPER_TOOLS = {"list_instances", "compare_instances"}

CONFIRM_FIELD = "confirm"
CONFIRM_VALUE = "approve"
# Strong, target-naming approval for a SINGLE cross-instance write: must equal
# the `instance=` alias. Routes exactly one write to a named non-active instance
# (via a scoped active-swap so guards + write + echo all see the target), then
# the active instance is restored. No persistent state to forget to revert.
CONFIRM_INSTANCE_FIELD = "confirm_instance"

# Reserved arg: route a single read-only call to a named non-active instance.
# Stripped before the tool's Pydantic model sees it (like CONFIRM_FIELD).
INSTANCE_FIELD = "instance"

_TOOL_SCHEMA_CACHE: Dict[tuple[type[Any], str], Dict[str, Any]] = {}


def _parse_package_entry(entry: Any) -> tuple[str, Optional[frozenset[str]]] | None:
    """Parse one tool_packages.yaml list element.

    Accepts ``"tool_name"`` (no restriction) or
    ``{"tool_name": {"actions": [...]}}`` (action allowlist). Returns
    ``None`` for malformed entries.
    """
    if isinstance(entry, str):
        return entry, None
    if isinstance(entry, dict) and len(entry) == 1:
        tool_name, restriction = next(iter(entry.items()))
        if not isinstance(tool_name, str) or not isinstance(restriction, dict):
            return None
        actions = restriction.get("actions")
        if actions is None:
            return tool_name, None
        if not isinstance(actions, list) or not all(isinstance(a, str) for a in actions):
            return None
        return tool_name, frozenset(actions) if actions else None
    return None


def _flatten_package_entries(
    entries: List[Any],
) -> tuple[List[str], Dict[str, Optional[frozenset[str]]]]:
    """Split raw YAML entries into a name list + action map. Last entry wins
    on duplicates (rare; YAML is hand-edited)."""
    names: List[str] = []
    actions: Dict[str, Optional[frozenset[str]]] = {}
    for entry in entries:
        parsed = _parse_package_entry(entry)
        if parsed is None:
            logger.warning("Skipping malformed package entry: %r", entry)
            continue
        tool_name, allowlist = parsed
        if tool_name not in actions:
            names.append(tool_name)
        actions[tool_name] = allowlist
    return names, actions


@lru_cache(maxsize=1)
def _load_packaged_package_definitions() -> Dict[str, List[Any]]:
    """Load packaged tool definitions once for installed/default usage.

    Returns the raw YAML form (mix of strings and single-key dicts) per
    package. Flattening to a name list + action map happens later in
    ``_load_yaml_config`` / instance state, so callers always see the same
    raw shape regardless of whether the YAML was loaded via importlib or
    from disk.
    """
    from importlib.resources import files

    pkg_file = files("servicenow_mcp.config").joinpath("tool_packages.yaml")
    loaded_config = yaml.safe_load(pkg_file.read_text(encoding="utf-8"))
    if not isinstance(loaded_config, dict):
        raise ValueError(f"Expected dict package config, got {type(loaded_config)}")
    result = {str(k).lower(): v for k, v in loaded_config.items()}
    # Resolve _extends inheritance — concatenate raw entry lists; flattening
    # happens later so dict-form entries (action allowlists) survive intact.
    for pkg_name, pkg_def in list(result.items()):
        if isinstance(pkg_def, dict) and "_extends" in pkg_def:
            base = list(result.get(pkg_def["_extends"], []))
            result[pkg_name] = base + pkg_def.get("_tools", [])
    return result


_MAX_DEFAULT_STR = 60  # Long string defaults are *dropped* (never truncated)
_INCLUDE_SKILL_HINTS_ENV = "MCP_INCLUDE_SKILL_HINTS"

# Schema verbosity: minimal (no descriptions), compact (default), full (all details).
_SCHEMA_DETAIL_ENV = "MCP_SCHEMA_DETAIL"
_SCHEMA_DETAIL_MINIMAL = "minimal"
_SCHEMA_DETAIL_COMPACT = "compact"
_SCHEMA_DETAIL_FULL = "full"

# Fields whose name is self-explanatory — description is redundant for the LLM.
# Keep this list VERY conservative: name must be unambiguous across every tool that
# uses it. Anything domain-specific (e.g. "scope", "name") stays descripted.
_SELF_EXPLANATORY_FIELDS = frozenset(
    {
        "dry_run",
        "sys_id",
        "count_only",
        "limit",
        "offset",
        "page_size",
        "only_active",
        "include_schema",
        "active",
        "query",
        "table",
        "fields",
        "order",
    }
)


def _compact_schema(schema: Any, *, _top_level: bool = False) -> Any:
    """Strip Pydantic noise from JSON schema to minimize LLM context tokens.

    Removes: title, long defaults (str/list), verbose anyOf, long descriptions,
    redundant top-level boilerplate, and descriptions of universally-understood
    parameter names (dry_run, limit, etc.).
    """
    if isinstance(schema, list):
        return [_compact_schema(i) for i in schema]
    if not isinstance(schema, dict):
        return schema

    # Flatten anyOf nullable (Optional[X] → X)
    if "anyOf" in schema:
        types = schema["anyOf"]
        non_null = [t for t in types if t.get("type") != "null"]
        if len(non_null) == 1:
            merged = {k: v for k, v in schema.items() if k != "anyOf"}
            merged.update(non_null[0])
            return _compact_schema(merged, _top_level=_top_level)

    result: Dict[str, Any] = {}
    for k, v in schema.items():
        if k == "title":
            continue
        # Drop empty required arrays at top level (noise)
        if _top_level and k == "required" and isinstance(v, list) and not v:
            continue
        # Drop additionalProperties=false — MCP clients assume it
        if k == "additionalProperties" and v is False:
            continue
        # Drop self-evident defaults: None/False/0/empty-list/empty-dict.
        # These add no information the LLM can't infer from the description/type.
        # Non-empty list/dict defaults are preserved because they often carry
        # domain meaning (e.g. default source_types=["widget"]).
        if k == "default" and (v is None or v is False or v == 0 or v == [] or v == {}):
            continue
        # Drop long string defaults entirely — never truncate.
        # A truncated default is a value the LLM might copy-paste back, so
        # "…" inside a regex/path/JSON would corrupt the tool call. Dropping
        # the key signals "omit to use server-side default".
        if k == "default" and isinstance(v, str) and len(v) > _MAX_DEFAULT_STR:
            continue
        # Param descriptions are forwarded verbatim. Truncating them silently
        # dropped routing hints (e.g. "use portal tracing/search tools when ...")
        # and changed semantic meaning (e.g. dropped "or sys_id of the parent
        # table" from a parent-id description), causing the LLM to mis-route
        # tool calls. CLAUDE.md asks authors to keep descriptions ≤80 chars,
        # but enforce that at author time, not by silent truncation here.
        # Recurse into properties with per-field filler stripping
        if k == "properties" and isinstance(v, dict):
            result[k] = {
                prop_name: _strip_field_filler(prop_name, _compact_schema(prop_schema))
                for prop_name, prop_schema in v.items()
            }
            continue
        result[k] = _compact_schema(v)
    return result


def _strip_field_filler(field_name: str, field_schema: Any) -> Any:
    """Remove description for universally-understood field names."""
    if not isinstance(field_schema, dict):
        return field_schema
    if _is_self_explanatory_field(field_name, field_schema) and "description" in field_schema:
        field_schema = {k: v for k, v in field_schema.items() if k != "description"}
    return field_schema


def _is_self_explanatory_field(field_name: str, field_schema: Dict[str, Any]) -> bool:
    """Return True when the field name/type already tells the LLM enough."""
    if field_name in _SELF_EXPLANATORY_FIELDS:
        return True

    field_type = field_schema.get("type")
    if field_type == "boolean" and (
        field_name.startswith("include_") or field_name.endswith("_only")
    ):
        return True
    if field_type == "integer" and (field_name.startswith("max_") or field_name.startswith("min_")):
        return True
    return False


def _get_schema_detail() -> str:
    """Read schema verbosity level from env. Returns 'minimal', 'compact', or 'full'."""
    return os.getenv(_SCHEMA_DETAIL_ENV, _SCHEMA_DETAIL_COMPACT).strip().lower()


def _narrow_action_enum(schema: Dict[str, Any], allowed: frozenset[str]) -> Dict[str, Any]:
    """Return a shallow copy of ``schema`` with the ``action`` enum reduced
    to ``allowed``. Returns the original ref when narrowing is a no-op."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return schema
    action_schema = properties.get("action")
    if not isinstance(action_schema, dict):
        return schema
    existing = action_schema.get("enum")
    if not isinstance(existing, list):
        return schema
    narrowed = [v for v in existing if v in allowed]
    if narrowed == existing:
        return schema
    return {
        **schema,
        "properties": {**properties, "action": {**action_schema, "enum": narrowed}},
    }


def _narrow_action_schema(
    schema: Dict[str, Any],
    allowed: frozenset[str],
    fields_by_action: Optional[Dict[str, frozenset[str]]],
) -> Dict[str, Any]:
    """Narrow action enum + drop properties not used by any allowed action.

    When ``fields_by_action`` maps each action to its fieldset, properties not
    referenced by any allowed action are dropped from the schema. Fields not
    appearing in the mapping at all are preserved (treated as universally
    applicable) so undeclared fields don't silently disappear.
    """
    schema = _narrow_action_enum(schema, allowed)
    if not fields_by_action:
        return schema
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return schema

    declared: set[str] = set()
    for fs in fields_by_action.values():
        declared |= set(fs)
    used: set[str] = {"action"}
    for act in allowed:
        used |= set(fields_by_action.get(act, frozenset()))

    narrowed_props = {
        name: ps for name, ps in properties.items() if name not in declared or name in used
    }
    if narrowed_props == properties:
        return schema

    new_schema = {**schema, "properties": narrowed_props}
    required = schema.get("required")
    if isinstance(required, list):
        new_schema["required"] = [r for r in required if r in narrowed_props]
    return new_schema


def _get_tool_schema(params_model: type[Any]) -> Dict[str, Any]:
    """Cache compacted Pydantic schema for LLM-optimal context usage.

    Cache key includes the MCP_SCHEMA_DETAIL level so runtime changes
    (e.g. tests flipping the env var) don't return stale schemas.
    """
    detail = _get_schema_detail()
    cache_key = (params_model, detail)
    cached_schema = _TOOL_SCHEMA_CACHE.get(cache_key)
    if cached_schema is None:
        raw = params_model.model_json_schema()
        if detail == _SCHEMA_DETAIL_FULL:
            cached_schema = raw
        else:
            cached_schema = _compact_schema(raw, _top_level=True)
            if detail == _SCHEMA_DETAIL_MINIMAL:
                # Strip ALL property descriptions — field names + types are enough.
                props = cached_schema.get("properties", {})
                for prop_schema in props.values():
                    if isinstance(prop_schema, dict):
                        prop_schema.pop("description", None)
        # Remove top-level docstring (tool description covers this)
        cached_schema.pop("description", None)
        # Strip docstrings that survived inside $defs/definitions (nested
        # Pydantic submodels). They restate model-level docstrings the LLM
        # doesn't need — leaf field descriptions are still preserved.
        if detail != _SCHEMA_DETAIL_FULL:
            for defs_key in ("$defs", "definitions"):
                sub = cached_schema.get(defs_key)
                if isinstance(sub, dict):
                    for sub_schema in sub.values():
                        if isinstance(sub_schema, dict):
                            sub_schema.pop("description", None)
        _TOOL_SCHEMA_CACHE[cache_key] = cached_schema
    return cached_schema


def _compact_json(obj: Any) -> str:
    """Dump *obj* to compact JSON with no indentation or extra whitespace.

    Uses orjson (via json_fast) when available for 2-4x faster serialization.
    """
    return json_fast.dumps(obj)


def serialize_tool_output(result: Any, tool_name: str) -> str:
    """Serialize tool output to compact JSON for LLM token efficiency.

    No indentation or extra whitespace — saves 20-30% tokens on typical responses.
    """
    try:
        if isinstance(result, str):
            # Fast path: if string looks like compact JSON already, return as-is.
            # Avoids an expensive parse→re-serialize round-trip.
            stripped = result.lstrip()
            if stripped and stripped[0] in ("{", "["):
                if " : " not in result and "\n" not in result:
                    return result
                # Has whitespace — re-compact it
                try:
                    return _compact_json(json_fast.loads(result))
                except Exception:
                    return result
            return result
        elif isinstance(result, dict):
            return _compact_json(result)
        elif hasattr(result, "model_dump_json"):
            try:
                return result.model_dump_json()
            except TypeError:
                return _compact_json(result.model_dump())
        elif hasattr(result, "model_dump"):
            return _compact_json(result.model_dump())
        else:
            logger.warning(
                f"Could not serialize result for tool '{tool_name}' to JSON, falling back to str(). Type: {type(result)}"
            )
            return str(result)
    except Exception as e:
        logger.error(f"Error during serialization for tool '{tool_name}': {e}", exc_info=True)
        return _compact_json(
            {"error": f"Serialization failed for tool {tool_name}", "details": str(e)}
        )


class ServiceNowMCP:
    """
    ServiceNow MCP Server implementation.

    This class provides a Model Context Protocol (MCP) server for ServiceNow,
    allowing LLMs to interact with ServiceNow data and functionality.
    It supports loading specific tool packages via the MCP_TOOL_PACKAGE env var.
    """

    def __init__(self, config: Union[Dict, ServerConfig]):
        """
        Initialize the ServiceNow MCP server.

        Args:
            config: Server configuration, either as a dictionary or ServerConfig object.
        """
        if isinstance(config, dict):
            self.config = ServerConfig(**config)
        else:
            self.config = config

        self.auth_manager = AuthManager(self.config.auth, self.config.instance_url)
        self.mcp_server: Server = FastMCP("ServiceNow")  # Use low-level Server
        self.name = "ServiceNow"
        self.instance_entries = load_instance_config_env(os.getenv(INSTANCE_CONFIG_ENV))
        self.active_instance_alias = select_active_alias(
            self.instance_entries,
            active_alias=os.getenv(ACTIVE_INSTANCE_ENV),
            legacy_instance_url=os.getenv("SERVICENOW_INSTANCE_URL"),
        )
        self.instance_contexts: Dict[str, Dict[str, Any]] = self._build_instance_contexts()
        self.active_instance_meta = self._active_instance_meta()

        self.package_definitions: Dict[str, List[str]] = {}
        # Per-package per-tool action allowlists. Populated when YAML uses the
        # dict form ({tool: {actions: [...]}}). None or missing entry = no
        # restriction.
        self.package_action_maps: Dict[str, Dict[str, Optional[frozenset[str]]]] = {}
        # Active (post-merge) allowlists for the currently selected package(s).
        self._active_action_allowlists: Dict[str, Optional[frozenset[str]]] = {}
        self.enabled_tool_names: List[str] = []
        self.current_package_name: str = "none"
        self._tool_list_cache: List[types.Tool] | None = None
        self._include_skill_hints = os.getenv(_INCLUDE_SKILL_HINTS_ENV, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._skill_entries = load_skills()
        self._tool_to_skills = build_tool_to_skills_map()
        self._load_package_config()
        self._determine_enabled_tools()

        # Lazy-discover only the tool modules needed for the active package.
        # Skips importing unused modules for faster startup.
        self.tool_definitions = get_tool_definitions(
            enabled_names=set(self.enabled_tool_names) if self.enabled_tool_names else None
        )

        self._register_handlers()
        self._register_tools()
        self._register_resources()

    def _register_tools(self):
        tool_decorator = getattr(self.mcp_server, "tool", None)
        if not callable(tool_decorator):
            return

        for tool_name, definition in self.tool_definitions.items():
            # Only register tools that are in the enabled list for the current package
            if tool_name not in self.enabled_tool_names:
                continue

            impl_func, _params_model, _return_annotation, description, _serialization = definition
            try:
                decorator = tool_decorator(name=tool_name, description=description)
                if callable(decorator):
                    decorator(impl_func)
            except Exception:
                logger.debug(
                    "Legacy tool registration shim failed for %s", tool_name, exc_info=True
                )

    def _register_resources(self):
        resource_decorator = getattr(self.mcp_server, "resource", None)
        if not callable(resource_decorator):
            return

        for resource_path in ("catalog://items", "catalog://categories", "catalog://{item_id}"):
            try:
                resource_decorator(resource_path)
            except Exception:
                logger.debug(
                    "Legacy resource registration shim failed for %s", resource_path, exc_info=True
                )

    def _register_handlers(self):
        """Register the list_tools, call_tool, and resource handlers."""
        self.mcp_server.list_tools()(self._list_tools_impl)
        self.mcp_server.call_tool()(self._call_tool_impl)
        self.mcp_server.list_resources()(self._list_resources_impl)
        self.mcp_server.read_resource()(self._read_resource_impl)
        self.mcp_server.list_resource_templates()(self._list_resource_templates_impl)
        logger.info("Registered list_tools, call_tool, and resource handlers.")

    def _build_instance_contexts(self) -> Dict[str, Dict[str, Any]]:
        """Build named instance contexts for read-only comparison helpers.

        Legacy single-instance mode has no named peers. The active server config
        remains the source of truth for ordinary tools.
        """
        contexts: Dict[str, Dict[str, Any]] = {}
        for alias, entry in self.instance_entries.items():
            definition = build_instance_definition(alias, entry)
            config = ServerConfig(
                instance_url=definition.url,
                auth=self._auth_for_instance_entry(entry),
                debug=self.config.debug,
                timeout=self.config.timeout,
                connect_timeout=self.config.connect_timeout,
                script_execution_api_resource_path=self.config.script_execution_api_resource_path,
            )
            contexts[alias] = {
                "alias": alias,
                "definition": definition,
                "config": config,
                "auth_manager": AuthManager(config.auth, config.instance_url),
            }
        return contexts

    def _auth_for_instance_entry(self, entry: Dict[str, Any]) -> AuthConfig:
        """Return auth config for a named instance, falling back to active auth."""
        base = self.config.auth
        auth_type = str(entry.get("auth_type") or base.type.value).lower()
        parsed = AuthType(auth_type)
        if parsed == AuthType.BROWSER:
            base_browser = base.browser or BrowserAuthConfig()
            return AuthConfig(
                type=parsed,
                browser=BrowserAuthConfig(
                    username=entry.get("username", base_browser.username),
                    password=entry.get("password", base_browser.password),
                    login_url=entry.get("login_url", base_browser.login_url),
                    probe_path=entry.get("probe_path", base_browser.probe_path),
                    headless=coerce_bool(entry.get("headless"), base_browser.headless),
                    timeout_seconds=int(entry.get("timeout_seconds", base_browser.timeout_seconds)),
                    user_data_dir=entry.get("user_data_dir", base_browser.user_data_dir),
                    session_ttl_minutes=int(
                        entry.get("session_ttl_minutes", base_browser.session_ttl_minutes)
                    ),
                ),
            )
        if parsed == AuthType.BASIC:
            base_basic = base.basic
            username = entry.get("username", base_basic.username if base_basic else None)
            password = entry.get("password", base_basic.password if base_basic else None)
            if not username or not password:
                raise ValueError("Named basic-auth instance requires username and password")
            return AuthConfig(
                type=parsed,
                basic=BasicAuthConfig(username=str(username), password=str(password)),
            )
        if parsed == AuthType.API_KEY:
            base_api = base.api_key
            api_key = entry.get("api_key", base_api.api_key if base_api else None)
            header = entry.get("api_key_header", base_api.header_name if base_api else None)
            if not api_key:
                raise ValueError("Named api_key instance requires api_key")
            return AuthConfig(
                type=parsed,
                api_key=ApiKeyConfig(
                    api_key=str(api_key),
                    header_name=str(header or "X-ServiceNow-API-Key"),
                ),
            )
        if parsed == AuthType.OAUTH:
            base_oauth = base.oauth
            client_id = entry.get("client_id", base_oauth.client_id if base_oauth else None)
            client_secret = entry.get(
                "client_secret", base_oauth.client_secret if base_oauth else None
            )
            username = entry.get("username", base_oauth.username if base_oauth else None)
            password = entry.get("password", base_oauth.password if base_oauth else None)
            token_url = entry.get("token_url", base_oauth.token_url if base_oauth else None)
            if not client_id or not client_secret or not username or not password:
                raise ValueError("Named oauth instance requires OAuth credentials")
            return AuthConfig(
                type=parsed,
                oauth=OAuthConfig(
                    client_id=str(client_id),
                    client_secret=str(client_secret),
                    username=str(username),
                    password=str(password),
                    token_url=str(token_url) if token_url else None,
                ),
            )
        return base

    def _active_instance_meta(self) -> Dict[str, Any]:
        if self.active_instance_alias and self.active_instance_alias in self.instance_contexts:
            definition = self.instance_contexts[self.active_instance_alias]["definition"]
            return {
                "alias": definition.alias,
                "allow_writes": definition.allow_writes,
                "url": definition.url,
            }
        return {
            "alias": "default",
            "allow_writes": True,
            "url": self.config.instance_url,
        }

    def _load_package_config(self):
        """Load tool package definitions from the YAML configuration file."""
        # Priority 1: Environment variable with absolute path
        config_path = os.getenv("TOOL_PACKAGE_CONFIG_PATH")

        if config_path:
            logger.info(f"Loading tool package config from env: {config_path}")
            self._load_yaml_config(config_path)
            self._finalize_package_definitions()
            return

        # Priority 2: importlib.resources (works reliably in pip-installed packages)
        try:
            raw = _load_packaged_package_definitions()
            # raw values may include dict-form entries; copy so we don't mutate
            # the lru_cache result during finalization.
            self.package_definitions = {k: list(v) for k, v in raw.items()}
            logger.info(
                f"Successfully loaded {len(self.package_definitions)} package definitions via importlib.resources"
            )
            self._finalize_package_definitions()
            return
        except Exception:
            logger.debug("importlib.resources lookup failed, falling back to file paths")

        # Priority 3: File-system fallback (development / editable installs)
        repo_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "tool_packages.yaml")
        )
        pkg_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "config", "tool_packages.yaml")
        )
        fallback = repo_path if os.path.exists(repo_path) else pkg_path
        self._load_yaml_config(fallback)
        self._finalize_package_definitions()

    def _finalize_package_definitions(self):
        """Flatten raw YAML entries into name lists + per-tool action maps."""
        flattened: Dict[str, List[str]] = {}
        action_maps: Dict[str, Dict[str, Optional[frozenset[str]]]] = {}
        for pkg_name, raw_entries in self.package_definitions.items():
            if not isinstance(raw_entries, list):
                flattened[pkg_name] = []
                action_maps[pkg_name] = {}
                continue
            names, actions = _flatten_package_entries(raw_entries)
            flattened[pkg_name] = names
            action_maps[pkg_name] = actions
        self.package_definitions = flattened
        self.package_action_maps = action_maps

    def _load_yaml_config(self, config_path: str):
        """Load and parse a YAML tool-package config file."""
        logger.info(f"Attempting to load tool package config from: {config_path}")
        try:
            if not os.path.exists(config_path):
                logger.error(f"Tool package config file NOT FOUND at {config_path}")
                self.package_definitions = {}
                return

            with open(config_path, "r") as f:
                loaded_config = yaml.safe_load(f)
                if isinstance(loaded_config, dict):
                    self.package_definitions = {str(k).lower(): v for k, v in loaded_config.items()}
                    # Resolve _extends inheritance: {_extends: "parent", _tools: [...]}
                    for pkg_name, pkg_def in list(self.package_definitions.items()):
                        if isinstance(pkg_def, dict):
                            parent = pkg_def.get("_extends")
                            if parent is None:
                                continue
                            base = list(self.package_definitions.get(str(parent), []))
                            extra = pkg_def.get("_tools", [])
                            self.package_definitions[pkg_name] = base + extra
                    logger.info(
                        f"Successfully loaded {len(self.package_definitions)} package definitions from {config_path}"
                    )
                else:
                    logger.error(
                        f"Invalid format in {config_path}: Expected dict, got {type(loaded_config)}"
                    )
                    self.package_definitions = {}
        except Exception as e:
            logger.exception(f"Unexpected error loading tool package config: {e}")
            self.package_definitions = {}

    def _determine_enabled_tools(self):
        """Determine which tool packages and tools to enable based on environment variable.

        MCP_TOOL_PACKAGE accepts either a single package name ("service_desk") or a
        comma-separated list ("standard,workflow_write,incident_ops"). When multiple
        packages are given, their tool sets are merged (preserving order, de-duplicated).
        Unknown package names emit a warning and are skipped — the merge continues so
        one typo does not wipe out the session.
        """
        # Tool surface is global: one MCP_TOOL_PACKAGE per server process.
        # Per-instance tool packages were removed — only one instance is ever
        # active at a time, so an alias-scoped package was effectively global
        # anyway (and implied a per-instance profile that never coexisted).
        # Per-instance differentiation is allow_writes, enforced at call time.
        env_package = os.getenv("MCP_TOOL_PACKAGE")
        if env_package:
            raw = env_package.strip()
            logger.info(f"MCP_TOOL_PACKAGE found: '{raw}'")
        else:
            raw = "standard"
            logger.info("MCP_TOOL_PACKAGE not set, defaulting to 'standard'")

        requested = [p.strip().lower() for p in raw.split(",") if p.strip()]

        if len(requested) == 1:
            name = requested[0]
            if name in self.package_definitions:
                self.current_package_name = name
                self.enabled_tool_names = self.package_definitions[name]
                self._active_action_allowlists = dict(self.package_action_maps.get(name, {}))
                logger.info(f"Loaded package '{name}' with {len(self.enabled_tool_names)} tools.")
                return
            # Single unknown package → same fallback behavior as before
            self.current_package_name = "none"
            self.enabled_tool_names = []
            self._active_action_allowlists = {}
            available = list(self.package_definitions.keys())
            logger.warning(
                f"Requested package '{name}' not found. Available: {available}. "
                "Loading 'none' (no tools enabled)."
            )
            return

        # Multi-package merge
        merged: List[str] = []
        seen: set = set()
        resolved_names: List[str] = []
        merged_allowlists: Dict[str, Optional[frozenset[str]]] = {}
        for name in requested:
            if name not in self.package_definitions:
                logger.warning(f"Skipping unknown package '{name}' in multi-package config")
                continue
            resolved_names.append(name)
            for t in self.package_definitions[name]:
                if t not in seen:
                    merged.append(t)
                    seen.add(t)
            # Action-allowlist merge: least-restrictive wins. If any package
            # opens an action up (None or larger set), the merged profile must
            # match — combining packages should never make a profile stricter
            # than any of its parts.
            for tool, allowlist in self.package_action_maps.get(name, {}).items():
                if tool not in merged_allowlists:
                    merged_allowlists[tool] = allowlist
                    continue
                existing = merged_allowlists[tool]
                if existing is None or allowlist is None:
                    merged_allowlists[tool] = None
                else:
                    merged_allowlists[tool] = existing | allowlist

        if not resolved_names:
            self.current_package_name = "none"
            self.enabled_tool_names = []
            self._active_action_allowlists = {}
            logger.warning(
                f"No valid packages in '{raw}'. Loading 'none'. "
                f"Available: {list(self.package_definitions.keys())}"
            )
            return

        self.current_package_name = "+".join(resolved_names)
        self.enabled_tool_names = merged
        self._active_action_allowlists = merged_allowlists
        logger.info(
            f"Loaded {len(resolved_names)} packages ({self.current_package_name}) "
            f"with {len(self.enabled_tool_names)} merged tools."
        )

    @staticmethod
    def _is_blocked_mutating_tool(tool_name: str) -> bool:
        return tool_name.startswith(MUTATING_TOOL_PREFIXES) or tool_name in MUTATING_TOOL_NAMES

    @staticmethod
    def _tool_requires_confirmation(tool_name: str) -> bool:
        return ServiceNowMCP._is_blocked_mutating_tool(tool_name)

    @staticmethod
    def _inject_confirmation_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        # Shallow copy top-level and only the mutable sub-keys we modify,
        # avoiding an expensive copy.deepcopy of the entire Pydantic schema.
        schema_with_confirm = {**schema}
        properties = {**schema.get("properties", {})}
        # No description: the field name `confirm`, the single-value enum
        # ["approve"], and the tool description's "(confirm='approve')" suffix
        # already say everything. Repeated on every write tool, every request —
        # dropping it is a systematic per-package saving.
        properties[CONFIRM_FIELD] = {
            "type": "string",
            "enum": [CONFIRM_VALUE],
        }
        schema_with_confirm["properties"] = properties
        required = list(schema.get("required", []))
        if CONFIRM_FIELD not in required:
            required.append(CONFIRM_FIELD)
        schema_with_confirm["required"] = required
        return schema_with_confirm

    def _inject_instance_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Advertise the optional read-only `instance` arg on read tools.

        Only called in multi-instance mode for non-write tools. Lets the LLM
        target a named non-active instance for a single read without switching
        the server's active instance. The enum is the configured alias list.
        """
        aliases = sorted(self.instance_contexts)
        schema_with_instance = {**schema}
        properties = {**schema.get("properties", {})}
        # No per-tool description — it would repeat on every read tool, every
        # request. The field name + alias enum are self-explanatory, and the
        # one-time multi-instance `instructions` block carries the steer
        # (default-to-active, no fan-out). Keeps the per-request schema lean.
        properties[INSTANCE_FIELD] = {"type": "string", "enum": aliases}
        schema_with_instance["properties"] = properties
        return schema_with_instance

    def _augment_tool_description(self, tool_name: str, description: str) -> str:
        """Append confirmation notice and skill guide hint (if any) to description."""
        if self._tool_requires_confirmation(tool_name):
            description = f"{description} (confirm='approve')"
        # Append skill guide hint — lightweight pointer, ~5 tokens.
        # Skip generic tools referenced by 3+ skills (e.g. sn_query) — hint would be arbitrary.
        skill_uris = self._tool_to_skills.get(tool_name)
        if self._include_skill_hints and skill_uris and len(skill_uris) <= 2:
            description = f"{description} → {skill_uris[0]}"
        return description

    # ------------------------------------------------------------------
    # Resource handlers (skills as MCP resources)
    # ------------------------------------------------------------------

    async def _list_resources_impl(self) -> List[types.Resource]:
        """Return all skill guides as MCP resources."""
        resources: List[types.Resource] = []
        for uri, name, description, category, _tools, content in self._skill_entries:
            resources.append(
                types.Resource(
                    uri=AnyUrl(uri),
                    name=f"{category}/{name}",
                    description=description,
                    mimeType="text/markdown",
                    size=len(content.encode("utf-8")),
                )
            )
        return resources

    async def _list_resource_templates_impl(self) -> List[types.ResourceTemplate]:
        """Advertise the skill URI template for discovery."""
        if not self._skill_entries:
            return []
        return [
            types.ResourceTemplate(
                uriTemplate="skill://{category}/{name}",
                name="Skill Guide",
                description="Workflow guide for ServiceNow operations. Pull on-demand for SOP details.",
                mimeType="text/markdown",
            )
        ]

    async def _read_resource_impl(self, uri) -> list:
        """Read a single skill guide by URI."""
        uri_str = str(uri)
        for skill_uri, _name, _desc, _cat, _tools, content in self._skill_entries:
            if skill_uri == uri_str:
                return [types.TextResourceContents(uri=uri, text=content, mimeType="text/markdown")]
        raise ValueError(f"Resource not found: {uri_str}")

    async def _list_tools_impl(self) -> List[types.Tool]:
        """Implementation for the list_tools MCP endpoint."""
        if self._tool_list_cache is not None:
            return list(self._tool_list_cache)

        tool_list: List[types.Tool] = []

        logger.info(
            f"Listing tools for package '{self.current_package_name}'. Enabled tool count: {len(self.enabled_tool_names)}"
        )
        if not self.enabled_tool_names and self.current_package_name != "none":
            logger.warning(
                f"No tools enabled for package '{self.current_package_name}'! Check tool_packages.yaml names."
            )

        # Add the introspection tool if not 'none' package
        if self.current_package_name != "none":
            # (introspection tool code remains)
            tool_list.append(
                types.Tool(
                    name="list_tool_packages",
                    description="Lists available tool packages and the currently loaded one.",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                )
            )
            if self.instance_contexts:
                tool_list.append(
                    types.Tool(
                        name="list_instances",
                        description="List configured ServiceNow instances and the active instance.",
                        inputSchema={"type": "object", "properties": {}},
                    )
                )
                tool_list.append(
                    types.Tool(
                        name="compare_instances",
                        description="Read-only compare records across two configured instances.",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                                "table": {"type": "string"},
                                "key_field": {"type": "string"},
                                "query": {"type": "string"},
                                "fields": {"type": "string"},
                                "ignore_fields": {"type": "array", "items": {"type": "string"}},
                                "limit": {"type": "integer", "default": 100},
                                "output": {
                                    "type": "string",
                                    "enum": ["summary", "compact", "full"],
                                    "default": "compact",
                                },
                                "normalize_strings": {"type": "boolean", "default": True},
                            },
                            "required": ["source", "target", "table", "key_field", "fields"],
                        },
                    )
                )

        # Iterate through defined tools and add enabled ones
        for tool_name, definition in self.tool_definitions.items():
            if tool_name in self.enabled_tool_names:
                (
                    _impl_func,
                    params_model,
                    _return_annotation,
                    description,
                    _serialization,
                ) = definition
                try:
                    schema = _get_tool_schema(params_model)
                    allowed = self._active_action_allowlists.get(tool_name)
                    if allowed is not None:
                        fields_by_action = getattr(params_model, "_FIELDS_BY_ACTION", None)
                        schema = _narrow_action_schema(schema, allowed, fields_by_action)
                    if self._tool_requires_confirmation(tool_name):
                        schema = self._inject_confirmation_schema(schema)
                    elif self.instance_contexts:
                        # Multi-instance: let read tools target a named instance.
                        # Write tools (confirmation-requiring) are excluded — they
                        # only ever run against the active instance.
                        schema = self._inject_instance_schema(schema)
                    tool_list.append(
                        types.Tool(
                            name=tool_name,
                            description=self._augment_tool_description(tool_name, description),
                            inputSchema=schema,
                        )
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to generate schema for tool '{tool_name}': {e}", exc_info=True
                    )

        logger.debug(f"Listing {len(tool_list)} tools for package '{self.current_package_name}'.")
        self._tool_list_cache = tool_list
        return tool_list

    async def _call_tool_impl(self, name: str, arguments: dict) -> list[types.TextContent]:
        """
        Implementation for the call_tool MCP endpoint.
        Handles argument parsing, tool execution, result serialization (to string),
        and returning a list containing a single TextContent object.

        Args:
            name: The name of the tool to call.
            arguments: The arguments for the tool as a dictionary.

        Returns:
            A list containing a single TextContent object with the tool output.

        Raises:
            ValueError: If the tool is unknown, disabled, or if arguments are invalid.
        """
        logger.info(f"Received call_tool request for tool '{name}'")
        # Back-compat: route deprecated tool names to their replacement WITHOUT
        # listing the old name (keeps the tool surface clean; old callers/allowlists
        # still work). The renamed tool's clearer name is the only one advertised.
        if name in _DEPRECATED_TOOL_ALIASES:
            new_name = _DEPRECATED_TOOL_ALIASES[name]
            logger.info("Tool '%s' is deprecated; routing to '%s'.", name, new_name)
            name = new_name
        # Handle the introspection tool separately
        if name == "list_tool_packages":
            if self.current_package_name == "none":
                raise ValueError(
                    "Tool 'list_tool_packages' is not available in the 'none' package."
                )
            result_dict = self._list_tool_packages_impl()
            serialized_string = json_fast.dumps(result_dict)
            # Return a list with a TextContent object
            return [types.TextContent(type="text", text=serialized_string)]
        if name == "list_instances":
            if not self.instance_contexts:
                raise ValueError("Tool 'list_instances' is available only in multi-instance mode.")
            return [
                types.TextContent(
                    type="text",
                    text=json_fast.dumps(self._list_instances_impl()),
                )
            ]
        if name == "compare_instances":
            if not self.instance_contexts:
                raise ValueError(
                    "Tool 'compare_instances' is available only in multi-instance mode."
                )
            return [
                types.TextContent(
                    type="text",
                    text=json_fast.dumps(self._compare_instances_impl(arguments)),
                )
            ]

        # Check enabled-set FIRST. With lazy discovery `tool_definitions` only
        # holds enabled tools, so the "Unknown tool" check below would eclipse
        # the friendlier "available in <pkg>" message if we checked it first.
        if name not in self.enabled_tool_names:
            available_in = [
                pkg
                for pkg, tools in self.package_definitions.items()
                if tools and name in tools and pkg != "none"
            ]
            if available_in:
                raise ValueError(
                    f"Tool '{name}' is not available in the current package '{self.current_package_name}'. "
                    f"This tool is available in: {available_in}. "
                    f"Switch by setting MCP_TOOL_PACKAGE environment variable. "
                    f"Alternatively, use sn_query for basic read operations."
                )
            # Tool name is genuinely unknown OR registered but not packaged
            if name not in self.tool_definitions:
                raise ValueError(f"Unknown tool: {name}")
            raise ValueError(
                f"Tool '{name}' exists but is not included in any active package. "
                f"Use sn_query to access the underlying table directly."
            )
        if name not in self.tool_definitions:
            raise ValueError(f"Unknown tool: {name}")

        # Reserved `instance` arg: route this one read-only call to a named
        # non-active instance (e.g. peek at test while active is dev). Write
        # tools are never redirected — switching write targets needs a server
        # restart with SERVICENOW_ACTIVE_INSTANCE. Resolve + strip here so the
        # tool's Pydantic model never sees `instance`.
        call_config = self.config
        call_auth_manager = self.auth_manager
        # Set when an authorized single-call cross-instance write routes to a
        # named non-active instance; used to scope the guards + echo to it.
        cross_instance_ctx: Optional[Dict[str, Any]] = None
        target_alias = arguments.pop(INSTANCE_FIELD, None)
        if target_alias is not None:
            target_alias = str(target_alias).strip()
            ctx = self.instance_contexts.get(target_alias)
            if not ctx:
                available = sorted(self.instance_contexts) or ["(none configured)"]
                raise ValueError(
                    f"instance '{target_alias}' is not configured. "
                    f"Set it in SERVICENOW_INSTANCE_CONFIG. Available: {available}."
                )
            if self._is_read_only_call(name, arguments):
                # Read-only: route this single call to the named instance.
                call_config = ctx["config"]
                call_auth_manager = ctx["auth_manager"]
            elif target_alias != self.active_instance_alias:
                # Single-call cross-instance write. Allowed ONLY with a strong,
                # target-naming approval (confirm_instance == target) AND the
                # target allowing writes. Routed below via a scoped active-swap so
                # the write guards, the write, and the echo ALL see the target —
                # never "guard dev, write test". The active instance is restored
                # right after this call (no persistent swap to forget to revert).
                confirm_instance = str(arguments.get(CONFIRM_INSTANCE_FIELD, "")).strip()
                if confirm_instance != target_alias:
                    raise ValueError(
                        f"'{name}' would write to the NON-active instance '{target_alias}' "
                        f"(active is '{self.active_instance_alias}'). This needs explicit "
                        f"acknowledgement of the target: pass {CONFIRM_INSTANCE_FIELD}="
                        f"'{target_alias}' AND {CONFIRM_FIELD}='{CONFIRM_VALUE}'. Only this one "
                        "write goes there; the active instance is restored afterwards. Do NOT "
                        "edit config/env to switch instances."
                    )
                if not ctx["definition"].allow_writes:
                    raise ValueError(
                        f"Instance '{target_alias}' is read-only (allow_writes=false); "
                        "cannot write to it."
                    )
                cross_instance_ctx = ctx
                call_config = ctx["config"]
                call_auth_manager = ctx["auth_manager"]
            # else: write naming the already-active instance — accept it as-is
            # (no redirect needed; falls through to the active config).

        # Per-package action allowlist: defense-in-depth against an LLM
        # invoking an action the schema didn't advertise. Runs before the
        # confirm gate so out-of-allowlist calls fail cleanly even if
        # confirm='approve' was passed.
        allowed_actions = self._active_action_allowlists.get(name)
        if allowed_actions is not None:
            action_val = arguments.get("action")
            if action_val not in allowed_actions:
                raise ValueError(
                    f"Action '{action_val}' is not available for '{name}' "
                    f"in package '{self.current_package_name}'. "
                    f"Allowed: {sorted(allowed_actions)}."
                )

        if not self._active_instance_allows_tool_write(name, arguments):
            raise ValueError(
                f"Active instance '{self.active_instance_meta.get('alias')}' is read-only "
                "(allow_writes=false). This is fixed at server startup and CANNOT be changed "
                "at runtime. Do NOT edit .mcp.json / config / env files to flip allow_writes "
                "or switch SERVICENOW_ACTIVE_INSTANCE — it has no effect until a restart and "
                "is not a valid workaround. Ask the user to restart the server with the target "
                "instance active (allow_writes=true), or to make the change directly in ServiceNow."
            )

        # Write guards: block writes against wrong/denied/bloated update sets,
        # raw Flow Designer table writes, and publish-class actions without
        # extra confirmation. Read-only calls skip this. Runs before confirm
        # so unsafe writes fail with a specific, actionable message.
        from servicenow_mcp.policies import (
            run_post_confirm_guards,
            run_write_guards,
            strip_guard_fields,
            update_set_context,
        )
        from servicenow_mcp.policies.write_guards import strip_post_confirm_fields

        with self._scoped_active_instance(cross_instance_ctx):
            run_write_guards(self, name, arguments)
        arguments = strip_guard_fields(arguments)

        # Safety check for mutating actions: require confirmation
        requires_confirmation = self._is_blocked_mutating_tool(name)
        # manage_X tools: bypass confirm for declared read-only sub-actions.
        # This keeps the prefix-based gate simple while still letting the
        # bundle host list/get without per-call confirm friction.
        if requires_confirmation and name.startswith("manage_"):
            read_actions = MANAGE_READ_ACTIONS.get(name)
            if read_actions and arguments.get("action") in read_actions:
                requires_confirmation = False

        if requires_confirmation:
            confirmation = str(arguments.get(CONFIRM_FIELD, "")).lower().strip()
            if confirmation != CONFIRM_VALUE:
                raise ValueError(
                    f"This action for '{name}' will modify or delete data. "
                    f"To proceed, please add the parameter {CONFIRM_FIELD}='{CONFIRM_VALUE}' to your request "
                    "to confirm you want to execute this."
                )
            logger.info("Executing confirmed action: tool=%s", name)

        # Post-confirm network guards (concurrent-edit G3/G8, duplicate-create
        # G9) run HERE — after the confirm gate — so an unconfirmed mutation is
        # rejected above without any network call. They make one live remote read
        # to block a blind overwrite of a concurrent edit or a silent duplicate.
        with self._scoped_active_instance(cross_instance_ctx):
            run_post_confirm_guards(self, name, arguments)
        arguments = strip_post_confirm_fields(arguments)

        # Strip the confirmation fields before passing to the tool
        arguments = {
            k: v for k, v in arguments.items() if k not in (CONFIRM_FIELD, CONFIRM_INSTANCE_FIELD)
        }

        # Get tool definition (we don't need the serialization hint anymore)
        definition = self.tool_definitions[name]
        impl_func, params_model, _return_annotation, _description, _serialization = definition

        # Validate and parse arguments using the Pydantic model
        try:
            params = params_model(**arguments)
            logger.debug(f"Parsed arguments for tool '{name}': {params}")
        except ValidationError as e:
            logger.error(f"Invalid arguments for tool '{name}': {e}", exc_info=True)
            raise ValueError(f"Invalid arguments for tool '{name}': {e}") from e
        except Exception as e:
            logger.error(
                f"Unexpected error parsing arguments for tool '{name}': {e}", exc_info=True
            )
            raise ValueError(f"Failed to parse arguments for tool '{name}': {e}") from e

        # Execute the tool implementation function.
        # DEFAULT: synchronously on the event-loop thread. asyncio.to_thread() was
        # removed from the default path because Playwright (browser auth) requires
        # execution on the thread that created its event loop — a separate thread
        # crashes MFA/SSO login flows. Whitelisted heavy DATA tools (no Playwright)
        # may opt into a worker thread to stream progress; see _invoke_impl.
        try:
            result = await self._invoke_impl(
                name, impl_func, call_config, call_auth_manager, params
            )
            logger.debug(f"Raw result type from tool '{name}': {type(result)}")
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}", exc_info=True)
            error_str = str(e)
            # Detect auth-related failures and provide actionable guidance to the LLM
            is_auth_error = any(
                marker in error_str.lower()
                for marker in [
                    "browser session expired",
                    "browser login",
                    "re-authentication",
                    "mfa",
                    "login is currently in progress",
                ]
            )
            if is_auth_error:
                error_result = {
                    "success": False,
                    "error": error_str,
                    "error_type": "auth_session_expired",
                    "tool": name,
                    "action_required": (
                        "The ServiceNow browser session needs re-authentication. "
                        "A browser window should open (or has opened) for the user to complete MFA/SSO login. "
                        "Please inform the user and retry this tool call after they complete authentication. "
                        "Do NOT repeatedly call tools while authentication is pending."
                    ),
                }
            else:
                error_result = {"success": False, "error": error_str, "tool": name}
            serialized_string = json_fast.dumps(error_result)
            return [types.TextContent(type="text", text=serialized_string)]

        # Multi-instance visibility: stamp the instance this call actually hit
        # so a wrong-target action can't pass silently. New dict — never mutate
        # the tool result. Echo wins on the (practically impossible) key clash so
        # the stamp always reflects reality.
        echo = self._instance_echo(name, arguments, target_alias)
        if echo and isinstance(result, dict):
            result = {**result, **echo}

        # Awareness (non-blocking): stamp which update set + scope this write
        # landed in, so a write captured into the wrong set — e.g. one another
        # terminal switched the session to — is fully visible rather than silent.
        # Writes only; new dict (never mutate the tool result); fail-open.
        if isinstance(result, dict) and not self._is_read_only_call(name, arguments):
            with self._scoped_active_instance(cross_instance_ctx):
                us_ctx = update_set_context(self, name, arguments, result)
            if us_ctx:
                result = {**result, "update_set_context": us_ctx}

        # Serialize the result to a string (preferably JSON) using the helper
        serialized_string = serialize_tool_output(result, name)
        logger.debug(f"Serialized value for tool '{name}': {serialized_string[:500]}...")

        # Return a list with a TextContent object
        return [types.TextContent(type="text", text=serialized_string)]

    def _progress_channel(self):
        """Return (progress_token, session) for the in-flight request, or
        (None, None) when there is no request context or the client did not
        request progress (no progressToken in the call's _meta)."""
        try:
            ctx = self.mcp_server.request_context
        except LookupError:
            return None, None
        meta = getattr(ctx, "meta", None)
        token = getattr(meta, "progressToken", None) if meta is not None else None
        if token is None:
            return None, None
        return token, getattr(ctx, "session", None)

    async def _invoke_impl(self, name, impl_func, call_config, call_auth_manager, params):
        """Dispatch a tool, streaming progress when it is worthwhile and safe.

        Default path (everything except whitelisted heavy data tools, or any tool
        when the client did not subscribe): run synchronously on the event-loop
        thread — preserves the browser-auth invariant (Playwright needs its
        creating thread).

        Streaming path (whitelisted DATA tool + subscribed client): run in a
        worker thread and bridge each emit_progress() call back to the loop as an
        MCP progress notification. A failed notification never breaks the tool.
        """
        progress_token, session = self._progress_channel()
        if session is None or not _should_stream_progress(name, progress_token):
            return impl_func(call_config, call_auth_manager, params)

        def _report(progress, total, message):
            # Runs in the worker thread; hop back to the loop to send the notice.
            try:
                anyio.from_thread.run(
                    session.send_progress_notification,
                    progress_token,
                    progress,
                    total,
                    message,
                )
            except Exception:  # noqa: BLE001 - progress must never break the tool
                logger.debug("send_progress_notification failed; ignoring", exc_info=True)

        def _worker():
            with use_progress_emitter(_report):
                return impl_func(call_config, call_auth_manager, params)

        return await anyio.to_thread.run_sync(_worker)

    @contextlib.contextmanager
    def _scoped_active_instance(self, ctx: Optional[Dict[str, Any]]):
        """Temporarily make `ctx`'s instance the active one, then restore.

        Used to scope an authorized single-call cross-instance write so the
        write guards and the update-set echo read the SAME instance the write
        targets — never "guard the active instance, write a different one". A
        no-op when ctx is None. Restores on every exit path (return or raise),
        so the active instance is never left swapped. Safe because tool dispatch
        is serialized on the event-loop thread (impl funcs run synchronously).
        """
        if ctx is None:
            yield
            return
        saved = (
            self.config,
            self.auth_manager,
            self.active_instance_alias,
            self.active_instance_meta,
        )
        try:
            self.config = ctx["config"]
            self.auth_manager = ctx["auth_manager"]
            self.active_instance_alias = ctx["definition"].alias
            self.active_instance_meta = self._active_instance_meta()
            yield
        finally:
            (
                self.config,
                self.auth_manager,
                self.active_instance_alias,
                self.active_instance_meta,
            ) = saved

    def _is_read_only_call(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        if tool_name in MANAGE_READ_ACTIONS:
            return arguments.get("action") in MANAGE_READ_ACTIONS[tool_name]
        return not self._is_blocked_mutating_tool(tool_name)

    def _active_instance_allows_tool_write(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        if self._is_read_only_call(tool_name, arguments):
            return True
        return bool(self.active_instance_meta.get("allow_writes", True))

    def _instance_echo(
        self, tool_name: str, arguments: Dict[str, Any], target_alias: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Stamp which instance a call actually hit (multi-instance mode only).

        Deterministic visibility, not an LLM-supplied arg, so the model can't
        ignore or spoof it: every write echoes its target instance, and any read
        routed elsewhere via `instance=` echoes its source. This lets a
        wrong-instance action surface in the response instead of relying on the
        LLM to track the active target. Returns None in legacy single-instance
        mode (no ambiguity, no token cost).
        """
        if not self.instance_contexts:
            return None
        if self._is_read_only_call(tool_name, arguments):
            # Only reads explicitly redirected to a non-active peer are ambiguous.
            if not target_alias or target_alias == self.active_instance_alias:
                return None
            ctx = self.instance_contexts.get(target_alias)
            if not ctx:
                return None
            definition = ctx["definition"]
            return {
                "instance_source": {
                    "alias": definition.alias,
                    "host": safe_instance_url(definition.url),
                }
            }
        # An authorized single-call cross-instance write echoes its ACTUAL
        # target (the active instance was already restored by now), so the
        # response makes "this write landed on test, not dev" explicit.
        if target_alias and target_alias != self.active_instance_alias:
            ctx = self.instance_contexts.get(target_alias)
            if ctx:
                definition = ctx["definition"]
                return {
                    "instance_target": {
                        "alias": definition.alias,
                        "host": safe_instance_url(definition.url),
                        "cross_instance": True,
                    }
                }
        # Otherwise the write went to the active instance.
        meta = self.active_instance_meta
        return {
            "instance_target": {
                "alias": meta.get("alias"),
                "host": safe_instance_url(str(meta.get("url", ""))),
            }
        }

    def _list_instances_impl(self) -> Dict[str, Any]:
        instances = []
        for alias, ctx in self.instance_contexts.items():
            definition = ctx["definition"]
            # Explicit, no-network auth state per instance so the caller sees
            # which instance needs a login without trial-and-error sn_health
            # probes. `session_cached` = local cookies held (verified live on
            # use), `no_session` = login required, `credentials` = non-browser.
            auth_status = "unknown"
            auth_manager = ctx.get("auth_manager")
            session_status = getattr(auth_manager, "session_status", None)
            if callable(session_status):
                try:
                    auth_status = session_status()
                except Exception:
                    auth_status = "unknown"
            instances.append(
                {
                    "alias": alias,
                    "active": alias == self.active_instance_alias,
                    "allow_writes": definition.allow_writes,
                    "auth_status": auth_status,
                    "host": safe_instance_url(definition.url),
                }
            )
        return {
            "success": True,
            "active_instance": self.active_instance_meta.get("alias"),
            "tool_package": self.current_package_name,
            "instances": instances,
            "ordinary_tools_route_to": self.active_instance_meta.get("alias"),
            "compare_instances": "read_only",
            "read_other_instance": (
                "Pass instance=<alias> to any read tool (e.g. sn_query, sn_health) to run "
                "that single read against a non-active instance. Writes stay on the active instance."
            ),
        }

    @staticmethod
    def _record_key_value(record: Dict[str, Any], key_field: str) -> str:
        value = record.get(key_field)
        if isinstance(value, dict):
            value = value.get("value") or value.get("display_value")
        return str(value or "")

    @staticmethod
    def _normalize_compare_value(value: Any, *, normalize_strings: bool) -> Any:
        if isinstance(value, str) and normalize_strings:
            return "\n".join(line.rstrip() for line in value.replace("\r\n", "\n").split("\n"))
        if isinstance(value, dict):
            return {
                key: ServiceNowMCP._normalize_compare_value(
                    val, normalize_strings=normalize_strings
                )
                for key, val in sorted(value.items())
            }
        if isinstance(value, list):
            return [
                ServiceNowMCP._normalize_compare_value(item, normalize_strings=normalize_strings)
                for item in value
            ]
        return value

    @staticmethod
    def _truncate_compare_value(value: Any, max_len: int = 1200) -> Any:
        if not isinstance(value, str) or len(value) <= max_len:
            return value
        return value[:max_len] + f"... (truncated, original length: {len(value)})"

    def _compare_instances_impl(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from servicenow_mcp.tools.sn_api import sn_query_page

        source = str(arguments.get("source") or "").strip()
        target = str(arguments.get("target") or "").strip()
        table = str(arguments.get("table") or "").strip()
        key_field = str(arguments.get("key_field") or "").strip()
        fields = str(arguments.get("fields") or "").strip()
        query = str(arguments.get("query") or "").strip()
        limit = min(max(int(arguments.get("limit") or 100), 1), 500)
        output = str(arguments.get("output") or "compact").strip().lower()
        normalize_strings = coerce_bool(arguments.get("normalize_strings"), True)
        ignore_fields = set(arguments.get("ignore_fields") or [])
        if output not in {"summary", "compact", "full"}:
            raise ValueError("output must be one of: summary, compact, full")
        for required_name, value in {
            "source": source,
            "target": target,
            "table": table,
            "key_field": key_field,
            "fields": fields,
        }.items():
            if not value:
                raise ValueError(f"{required_name} is required")
        if source not in self.instance_contexts or target not in self.instance_contexts:
            raise ValueError(f"Unknown instance alias. Available: {sorted(self.instance_contexts)}")

        field_names = [f.strip() for f in fields.split(",") if f.strip()]
        if key_field not in field_names:
            field_names.insert(0, key_field)
        effective_fields = ",".join(dict.fromkeys(field_names))

        def fetch(alias: str) -> List[Dict[str, Any]]:
            ctx = self.instance_contexts[alias]
            rows, _total = sn_query_page(
                ctx["config"],
                ctx["auth_manager"],
                table=table,
                query=query,
                fields=effective_fields,
                limit=limit,
                offset=0,
                display_value="all",
                fail_silently=False,
            )
            return rows

        source_rows = fetch(source)
        target_rows = fetch(target)
        source_by_key = {
            self._record_key_value(row, key_field): row
            for row in source_rows
            if self._record_key_value(row, key_field)
        }
        target_by_key = {
            self._record_key_value(row, key_field): row
            for row in target_rows
            if self._record_key_value(row, key_field)
        }
        source_keys = set(source_by_key)
        target_keys = set(target_by_key)
        shared_keys = sorted(source_keys & target_keys)
        compared_fields = [f for f in field_names if f != key_field and f not in ignore_fields]

        changed = []
        for key in shared_keys:
            srow = source_by_key[key]
            trow = target_by_key[key]
            changed_fields = []
            diffs: Dict[str, Dict[str, Any]] = {}
            for field in compared_fields:
                sval = self._normalize_compare_value(
                    srow.get(field), normalize_strings=normalize_strings
                )
                tval = self._normalize_compare_value(
                    trow.get(field), normalize_strings=normalize_strings
                )
                if sval != tval:
                    changed_fields.append(field)
                    if output == "full":
                        diffs[field] = {
                            "source": self._truncate_compare_value(sval),
                            "target": self._truncate_compare_value(tval),
                        }
            if changed_fields:
                item: Dict[str, Any] = {"key": key, "fields_changed": changed_fields}
                if output == "full":
                    item["diffs"] = diffs
                changed.append(item)

        result: Dict[str, Any] = {
            "success": True,
            "source": source,
            "target": target,
            "table": table,
            "key_field": key_field,
            "query": query,
            "compared_fields": compared_fields,
            "source_count": len(source_rows),
            "target_count": len(target_rows),
            "matched": len(shared_keys),
            "changed_count": len(changed),
            "only_in_source_count": len(source_keys - target_keys),
            "only_in_target_count": len(target_keys - source_keys),
        }
        if output != "summary":
            result.update(
                {
                    "only_in_source": sorted(source_keys - target_keys)[:50],
                    "only_in_target": sorted(target_keys - source_keys)[:50],
                    "changed": changed[:50],
                    "truncated": {
                        "changed": len(changed) > 50,
                        "only_in_source": len(source_keys - target_keys) > 50,
                        "only_in_target": len(target_keys - source_keys) > 50,
                    },
                }
            )
        return result

    def _list_tool_packages_impl(self) -> Dict[str, Any]:
        """Implementation logic for the list_tool_packages tool."""
        available_packages = list(self.package_definitions.keys())
        return {
            "current_package": self.current_package_name,
            "available_packages": available_packages,
            "active_instance": self.active_instance_meta.get("alias"),
            "message": (
                f"Currently loaded package: '{self.current_package_name}'. "
                f"Set MCP_TOOL_PACKAGE env var to one of {available_packages} to switch."
            ),
        }

    def start(self) -> Server:
        """
        Prepares and returns the configured low-level MCP Server instance.

        The caller (e.g., cli.py) is responsible for obtaining the server
        instance from this method and running it within an appropriate
        async transport context (e.g., mcp.server.stdio.stdio_server).

        Returns:
            The configured mcp.server.lowlevel.Server instance.
        """
        logger.info(
            "ServiceNowMCP instance configured. Returning low-level server instance for external execution."
        )
        # Canonical local-sync workflow, stated once via MCP `instructions`
        # (cheaper than repeating it in every sync tool's description) so the
        # LLM stops fumbling the edit/diff/push order or touching only one file.
        # Gated to packages that actually expose the push tool — core/standard
        # users never see sync tools, so they shouldn't pay for this hint.
        if "update_remote_from_local" in self.enabled_tool_names:
            sync_flow = (
                "Local source edit flow: (1) download the component to disk, "
                "(2) edit the file(s) — a widget has template.html, css.scss, "
                "client_script.js, link.js AND script.js; change every file the task "
                "needs, not just script.js, (3) run diff_local_component to review, "
                "(4) update_remote_from_local to push. Never push without diffing first."
            )
            existing = getattr(self.mcp_server, "instructions", None) or ""
            self.mcp_server.instructions = f"{existing}\n\n{sync_flow}" if existing else sync_flow

        # After a local download+audit, the relationship graphs live on disk.
        # Tell the LLM so it answers relationship questions by reading those
        # files instead of re-querying the instance with the live resolvers.
        # Gated to packages that expose the audit tool. Non-prescriptive: live
        # resolvers stay valid when no local dump exists (not everyone downloads
        # first), this just makes the offline option discoverable.
        if "audit_local_sources" in self.enabled_tool_names:
            offline_hint = (
                "Local analysis reuse: once download_app_sources + audit_local_sources "
                "have run, relationship data is on disk under the scope root — "
                "_graph.json (widget→Angular provider), _page_graph.json (page→widget), "
                "_cross_references.json (SI/table call chains). For those questions read "
                "the files directly instead of re-calling the live resolver "
                "(manage_widget_dependency action=list). "
                "audit_local_sources' offline_analysis field names the exact file per question."
            )
            existing = getattr(self.mcp_server, "instructions", None) or ""
            self.mcp_server.instructions = (
                f"{existing}\n\n{offline_hint}" if existing else offline_hint
            )

        # Flow/Action Designer stores published+draft version copies in the
        # *_base and *_snapshot tables under the SAME name/internal_name as the
        # live record. Without this note the LLM reads two same-named rows from
        # sys_hub_action_type_base (or *_snapshot) and wrongly reports a
        # "duplicate". Gated to flow packages so others don't pay for it.
        if "manage_flow_designer" in self.enabled_tool_names:
            snapshot_note = (
                "Flow/Action Designer versioning: the *_base and *_snapshot tables "
                "(e.g. sys_hub_action_type_base, sys_hub_flow_snapshot) hold published/draft "
                "version copies sharing the SAME name/internal_name as the live record — "
                "multiple same-named rows there are versions, NOT duplicates. Query the "
                "*_definition table (e.g. sys_hub_action_type_definition) for the one live record."
            )
            existing = getattr(self.mcp_server, "instructions", None) or ""
            self.mcp_server.instructions = (
                f"{existing}\n\n{snapshot_note}" if existing else snapshot_note
            )

        # Multi-instance only: steer default-to-active reads. The `instance`
        # arg on read tools otherwise reads as an invitation to fan out (e.g.
        # health-checking test while dev is active), which forces a separate
        # instance login and slows the response. One-time here, not repeated
        # per read tool per request.
        if len(self.instance_contexts) > 1:
            multi_instance_steer = (
                "Multiple ServiceNow instances are configured but only one is active. "
                "Default every read to the active instance — do NOT fan out (e.g. don't "
                "also health-check or query the others). Pass the read tools' optional "
                "instance=<alias> arg ONLY when the user explicitly names a non-active one. "
                "Writes default to the active instance. To write to a NON-active instance "
                "for a single call, pass BOTH instance=<alias> AND confirm_instance=<alias> "
                "(the same alias) plus confirm='approve' — that one write is routed there and "
                "the active instance is restored afterwards; only works if that instance has "
                "allow_writes=true. NEVER edit .mcp.json / config / env files to switch "
                "instances or flip allow_writes: that has no effect until a restart and is not "
                "a valid workaround. If the target is read-only, ask the user to change it in "
                "config and restart, or to apply the change directly in ServiceNow."
            )
            existing = getattr(self.mcp_server, "instructions", None) or ""
            self.mcp_server.instructions = (
                f"{existing}\n\n{multi_instance_steer}" if existing else multi_instance_steer
            )

        # When browser auth is selected and Chromium is missing, surface a
        # clear notice through MCP `instructions` so the client/LLM sees the
        # exact remediation command on the initialize response — instead of
        # silently failing on the first browser tool call.
        if self.config.auth and self.config.auth.type.value == "browser":
            chromium_notice = check_chromium_install_hint()
            if chromium_notice:
                existing = getattr(self.mcp_server, "instructions", None) or ""
                self.mcp_server.instructions = (
                    f"{existing}\n\n{chromium_notice}" if existing else chromium_notice
                )
        return self.mcp_server
