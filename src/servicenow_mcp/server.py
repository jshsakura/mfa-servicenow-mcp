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
from pydantic import ValidationError

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
)

CONFIRM_FIELD = "confirm"
CONFIRM_VALUE = "approve"

_TOOL_SCHEMA_CACHE: Dict[type[Any], Dict[str, Any]] = {}


@lru_cache(maxsize=1)
def _load_packaged_package_definitions() -> Dict[str, List[str]]:
    """Load packaged tool definitions once for installed/default usage."""
    from importlib.resources import files

    pkg_file = files("servicenow_mcp.config").joinpath("tool_packages.yaml")
    loaded_config = yaml.safe_load(pkg_file.read_text(encoding="utf-8"))
    if not isinstance(loaded_config, dict):
        raise ValueError(f"Expected dict package config, got {type(loaded_config)}")
    return {str(k).lower(): v for k, v in loaded_config.items()}


def _get_tool_schema(params_model: type[Any]) -> Dict[str, Any]:
    """Cache Pydantic schema generation across server instances."""
    cached_schema = _TOOL_SCHEMA_CACHE.get(params_model)
    if cached_schema is None:
        cached_schema = params_model.model_json_schema()
        _TOOL_SCHEMA_CACHE[params_model] = cached_schema
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
        """Determine which tool package and tools to enable based on environment variable."""
        # Get raw environment variable
        env_package = os.getenv("MCP_TOOL_PACKAGE")

        if env_package:
            requested_package = env_package.strip().lower()
            logger.info(
                f"MCP_TOOL_PACKAGE environment variable found: '{env_package}' (normalized to '{requested_package}')"
            )
        else:
            requested_package = "standard"
            logger.info("MCP_TOOL_PACKAGE environment variable not set, defaulting to 'standard'")

        # Check if the requested package exists in our definitions
        if requested_package in self.package_definitions:
            self.current_package_name = requested_package
            self.enabled_tool_names = self.package_definitions[requested_package]
            logger.info(
                f"Successfully loaded package '{self.current_package_name}' with {len(self.enabled_tool_names)} tools."
            )
        else:
            # Fallback to none if an invalid package was requested
            self.current_package_name = "none"
            self.enabled_tool_names = []
            available = list(self.package_definitions.keys())
            logger.warning(
                f"Requested package '{requested_package}' not found in configuration. "
                f"Available packages: {available}. Loading 'none' (no tools enabled)."
            )

    @staticmethod
    def _is_blocked_mutating_tool(tool_name: str) -> bool:
        return tool_name.startswith(MUTATING_TOOL_PREFIXES)

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
            "description": (
                "Required only for operations that modify data. Pass 'approve' to confirm intent."
            ),
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
            description = f"{description} Requires confirm='approve' for write/destructive actions."
        # Append skill guide hint — lightweight pointer, ~5 tokens.
        # Skip generic tools referenced by 3+ skills (e.g. sn_query) — hint would be arbitrary.
        skill_uris = self._tool_to_skills.get(tool_name)
        if skill_uris and len(skill_uris) <= 2:
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
                    uri=uri,
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

        # Check if the tool exists and is enabled
        if name not in self.tool_definitions:
            raise ValueError(f"Unknown tool: {name}")
        if name not in self.enabled_tool_names:
            # Find which packages DO include this tool
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
            else:
                raise ValueError(
                    f"Tool '{name}' exists but is not included in any active package. "
                    f"Use sn_query to access the underlying table directly."
                )

        # Safety check for mutating actions: require confirmation
        requires_confirmation = self._is_blocked_mutating_tool(name) or (
            name == "sn_nl" and bool(arguments.get("execute", False))
        )

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
