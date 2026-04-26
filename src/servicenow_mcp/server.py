"""
ServiceNow MCP Server

This module provides the main implementation of the ServiceNow MCP server.
"""

import logging
import os
from functools import lru_cache
from typing import Any, Dict, List, Union

import mcp.types as types
import yaml
from mcp.server.lowlevel import Server
from pydantic import AnyUrl, ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.resources.skill_resources import build_tool_to_skills_map, load_skills
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.tool_utils import get_tool_definitions

logger = logging.getLogger(__name__)

FastMCP = Server

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
}
# Tools that need confirmation but don't match a prefix above.
MUTATING_TOOL_NAMES = {"sn_batch", "sn_write"}

CONFIRM_FIELD = "confirm"
CONFIRM_VALUE = "approve"

_TOOL_SCHEMA_CACHE: Dict[tuple[type[Any], str], Dict[str, Any]] = {}


@lru_cache(maxsize=1)
def _load_packaged_package_definitions() -> Dict[str, List[str]]:
    """Load packaged tool definitions once for installed/default usage."""
    from importlib.resources import files

    pkg_file = files("servicenow_mcp.config").joinpath("tool_packages.yaml")
    loaded_config = yaml.safe_load(pkg_file.read_text(encoding="utf-8"))
    if not isinstance(loaded_config, dict):
        raise ValueError(f"Expected dict package config, got {type(loaded_config)}")
    result = {str(k).lower(): v for k, v in loaded_config.items()}
    # Resolve _extends inheritance
    for pkg_name, pkg_def in list(result.items()):
        if isinstance(pkg_def, dict) and "_extends" in pkg_def:
            base = list(result.get(pkg_def["_extends"], []))
            result[pkg_name] = base + pkg_def.get("_tools", [])
    return result


_MAX_DEFAULT_STR = 60  # Truncate long string defaults
_MAX_PARAM_DESC = 80  # Truncate long parameter descriptions
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

    result = {}
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
        # Truncate verbose param descriptions
        if k == "description" and isinstance(v, str) and len(v) > _MAX_PARAM_DESC:
            result[k] = v[:_MAX_PARAM_DESC].rstrip() + "…"
            continue
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

        self.package_definitions: Dict[str, List[str]] = {}
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

    def _load_package_config(self):
        """Load tool package definitions from the YAML configuration file."""
        # Priority 1: Environment variable with absolute path
        config_path = os.getenv("TOOL_PACKAGE_CONFIG_PATH")

        if config_path:
            logger.info(f"Loading tool package config from env: {config_path}")
            self._load_yaml_config(config_path)
            return

        # Priority 2: importlib.resources (works reliably in pip-installed packages)
        try:
            self.package_definitions = _load_packaged_package_definitions()
            logger.info(
                f"Successfully loaded {len(self.package_definitions)} package definitions via importlib.resources"
            )
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
                logger.info(f"Loaded package '{name}' with {len(self.enabled_tool_names)} tools.")
                return
            # Single unknown package → same fallback behavior as before
            self.current_package_name = "none"
            self.enabled_tool_names = []
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
        for name in requested:
            if name not in self.package_definitions:
                logger.warning(f"Skipping unknown package '{name}' in multi-package config")
                continue
            resolved_names.append(name)
            for t in self.package_definitions[name]:
                if t not in seen:
                    merged.append(t)
                    seen.add(t)

        if not resolved_names:
            self.current_package_name = "none"
            self.enabled_tool_names = []
            logger.warning(
                f"No valid packages in '{raw}'. Loading 'none'. "
                f"Available: {list(self.package_definitions.keys())}"
            )
            return

        self.current_package_name = "+".join(resolved_names)
        self.enabled_tool_names = merged
        logger.info(
            f"Loaded {len(resolved_names)} packages ({self.current_package_name}) "
            f"with {len(self.enabled_tool_names)} merged tools."
        )

    @staticmethod
    def _is_blocked_mutating_tool(tool_name: str) -> bool:
        return tool_name.startswith(MUTATING_TOOL_PREFIXES) or tool_name in MUTATING_TOOL_NAMES

    @staticmethod
    def _tool_requires_confirmation(tool_name: str) -> bool:
        return ServiceNowMCP._is_blocked_mutating_tool(tool_name) or tool_name == "sn_nl"

    @staticmethod
    def _inject_confirmation_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        # Shallow copy top-level and only the mutable sub-keys we modify,
        # avoiding an expensive copy.deepcopy of the entire Pydantic schema.
        schema_with_confirm = {**schema}
        properties = {**schema.get("properties", {})}
        properties[CONFIRM_FIELD] = {
            "type": "string",
            "enum": [CONFIRM_VALUE],
            "description": "Pass 'approve' for writes.",
        }
        schema_with_confirm["properties"] = properties
        required = list(schema.get("required", []))
        if CONFIRM_FIELD not in required:
            required.append(CONFIRM_FIELD)
        schema_with_confirm["required"] = required
        return schema_with_confirm

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
                    if self._tool_requires_confirmation(tool_name):
                        schema = self._inject_confirmation_schema(schema)
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

        # Safety check for mutating actions: require confirmation
        requires_confirmation = self._is_blocked_mutating_tool(name) or (
            name == "sn_nl" and bool(arguments.get("execute", False))
        )
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

        # Strip the confirmation field before passing to the tool
        arguments = {k: v for k, v in arguments.items() if k != CONFIRM_FIELD}

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

        # Execute the tool implementation function synchronously.
        # NOTE: asyncio.to_thread() was removed because Playwright (browser auth)
        # requires execution on the thread that created its event loop. Running in
        # a separate thread causes crashes during MFA/SSO login flows.
        try:
            result = impl_func(self.config, self.auth_manager, params)
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

        # Serialize the result to a string (preferably JSON) using the helper
        serialized_string = serialize_tool_output(result, name)
        logger.debug(f"Serialized value for tool '{name}': {serialized_string[:500]}...")

        # Return a list with a TextContent object
        return [types.TextContent(type="text", text=serialized_string)]

    def _list_tool_packages_impl(self) -> Dict[str, Any]:
        """Implementation logic for the list_tool_packages tool."""
        available_packages = list(self.package_definitions.keys())
        return {
            "current_package": self.current_package_name,
            "available_packages": available_packages,
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
        # The actual running of the server (server.run(...)) must happen
        # within an async context managed by the caller (e.g., using anyio
        # and a specific transport like stdio_server or SseServerTransport).
        return self.mcp_server
