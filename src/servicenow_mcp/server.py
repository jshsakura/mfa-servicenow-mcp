"""
ServiceNow MCP Server

This module provides the main implementation of the ServiceNow MCP server.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Union

import mcp.types as types
import yaml
from mcp.server.lowlevel import Server
from pydantic import ValidationError

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.tool_utils import get_tool_definitions

logger = logging.getLogger(__name__)

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


def serialize_tool_output(result: Any, tool_name: str) -> str:
    """Serializes tool output to a string, preferably JSON indented."""
    try:
        if isinstance(result, str):
            # If it's already a string, assume it's intended as such
            # Try to parse/re-dump JSON for consistent formatting if it looks like JSON
            try:
                parsed = json.loads(result)
                return json.dumps(parsed, indent=2)
            except json.JSONDecodeError:
                return result  # Return as is if not valid JSON
        elif isinstance(result, dict):
            # Dump dicts to JSON
            return json.dumps(result, indent=2)
        elif hasattr(result, "model_dump_json"):
            try:
                return result.model_dump_json(indent=2)
            except TypeError:
                return json.dumps(result.model_dump(), indent=2)
        elif hasattr(result, "model_dump"):
            return json.dumps(result.model_dump(), indent=2)
        else:
            # Absolute fallback: convert to string
            logger.warning(
                f"Could not serialize result for tool '{tool_name}' to JSON, falling back to str(). Type: {type(result)}"
            )
            return str(result)
    except Exception as e:
        logger.error(f"Error during serialization for tool '{tool_name}': {e}", exc_info=True)
        # Return an error message string formatted as JSON
        return json.dumps(
            {"error": f"Serialization failed for tool {tool_name}", "details": str(e)}, indent=2
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
        self.mcp_server = Server("ServiceNow")  # Use low-level Server
        self.name = "ServiceNow"

        self.package_definitions: Dict[str, List[str]] = {}
        self.enabled_tool_names: List[str] = []
        self.current_package_name: str = "none"
        self._load_package_config()
        self._determine_enabled_tools()

        # Auto-discover all tool definitions via @register_tool decorators
        self.tool_definitions = get_tool_definitions()

        self._register_handlers()

    def _register_handlers(self):
        """Register the list_tools and call_tool handlers."""
        self.mcp_server.list_tools()(self._list_tools_impl)
        self.mcp_server.call_tool()(self._call_tool_impl)
        logger.info("Registered list_tools and call_tool handlers.")

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
            from importlib.resources import files

            pkg_file = files("servicenow_mcp.config").joinpath("tool_packages.yaml")
            loaded_config = yaml.safe_load(pkg_file.read_text(encoding="utf-8"))
            if isinstance(loaded_config, dict):
                self.package_definitions = {str(k).lower(): v for k, v in loaded_config.items()}
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

    async def _list_tools_impl(self) -> List[types.Tool]:
        """Implementation for the list_tools MCP endpoint."""
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
                    schema = params_model.model_json_schema()
                    tool_list.append(
                        types.Tool(name=tool_name, description=description, inputSchema=schema)
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to generate schema for tool '{tool_name}': {e}", exc_info=True
                    )

        logger.debug(f"Listing {len(tool_list)} tools for package '{self.current_package_name}'.")
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
            RuntimeError: If tool execution or serialization fails.
        """
        logger.info(f"Received call_tool request for tool '{name}'")
        # Handle the introspection tool separately
        if name == "list_tool_packages":
            if self.current_package_name == "none":
                raise ValueError(
                    "Tool 'list_tool_packages' is not available in the 'none' package."
                )
            result_dict = self._list_tool_packages_impl()
            serialized_string = json.dumps(result_dict, indent=2)
            # Return a list with a TextContent object
            return [types.TextContent(type="text", text=serialized_string)]

        # Check if the tool exists and is enabled
        if name not in self.tool_definitions:
            raise ValueError(f"Unknown tool: {name}")
        if name not in self.enabled_tool_names:
            raise ValueError(
                f"Tool '{name}' is not enabled in the current package '{self.current_package_name}'."
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

        # Execute the tool implementation function (in a thread to avoid blocking the event loop)
        try:
            result = await asyncio.to_thread(impl_func, self.config, self.auth_manager, params)
            logger.debug(f"Raw result type from tool '{name}': {type(result)}")
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}", exc_info=True)
            error_result = {"success": False, "error": str(e), "tool": name}
            serialized_string = json.dumps(error_result, indent=2)
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
