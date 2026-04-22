"""
Command-line interface for the ServiceNow MCP server.
"""

import argparse
import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request

from .server import ServiceNowMCP
from .utils.config import (
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    OAuthConfig,
    ServerConfig,
)
from .version import __version__

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


_PACKAGE_NAME = "mfa-servicenow-mcp"
_PYPI_URL = f"https://pypi.org/pypi/{_PACKAGE_NAME}/json"

_ENV_REF_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _resolve_env_reference(value: str | None) -> str | None:
    """Resolve ${ENV_NAME} style values to the actual environment value."""
    if not value:
        return value
    stripped = value.strip()
    match = _ENV_REF_PATTERN.match(stripped)
    if not match:
        return value
    env_name = match.group(1)
    resolved = os.getenv(env_name)
    # Guard against self-referential placeholder values like:
    # SERVICENOW_USERNAME="${SERVICENOW_USERNAME}"
    if not resolved or resolved.strip() == stripped:
        return None
    return resolved


def _pick_first_resolved(*values: str | None) -> str | None:
    """
    Pick the first non-empty value after ${ENV_NAME} resolution.
    Unresolved ${...} values are treated as missing and skipped.
    """
    for value in values:
        resolved = _resolve_env_reference(value)
        if resolved:
            return resolved
    return None


def parse_args():
    """Parse command-line arguments."""
    from servicenow_mcp.version import get_version

    parser = argparse.ArgumentParser(description="ServiceNow MCP Server")
    parser.add_argument("--version", action="version", version=f"%(prog)s {get_version()}")

    # Server configuration
    parser.add_argument(
        "--instance-url",
        help="ServiceNow instance URL (e.g., https://instance.service-now.com)",
        default=os.environ.get("SERVICENOW_INSTANCE_URL"),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
        default=os.environ.get("SERVICENOW_DEBUG", "false").lower() == "true",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        help="Request timeout in seconds",
        default=int(os.environ.get("SERVICENOW_TIMEOUT", "30")),
    )

    # Authentication
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument(
        "--auth-type",
        choices=["basic", "oauth", "api_key", "browser"],
        help="Authentication type",
        default=os.environ.get("SERVICENOW_AUTH_TYPE", "basic"),
    )

    # Basic auth
    basic_group = parser.add_argument_group("Basic Authentication")
    basic_group.add_argument(
        "--username",
        help="ServiceNow username",
        default=os.environ.get("SERVICENOW_USERNAME"),
    )
    basic_group.add_argument(
        "--password",
        help="ServiceNow password",
        default=os.environ.get("SERVICENOW_PASSWORD"),
    )

    # OAuth
    oauth_group = parser.add_argument_group("OAuth Authentication")
    oauth_group.add_argument(
        "--client-id",
        help="OAuth client ID",
        default=os.environ.get("SERVICENOW_CLIENT_ID"),
    )
    oauth_group.add_argument(
        "--client-secret",
        help="OAuth client secret",
        default=os.environ.get("SERVICENOW_CLIENT_SECRET"),
    )
    oauth_group.add_argument(
        "--token-url",
        help="OAuth token URL",
        default=os.environ.get("SERVICENOW_TOKEN_URL"),
    )

    # API Key
    api_key_group = parser.add_argument_group("API Key Authentication")
    api_key_group.add_argument(
        "--api-key",
        help="ServiceNow API key",
        default=os.environ.get("SERVICENOW_API_KEY"),
    )
    api_key_group.add_argument(
        "--api-key-header",
        help="API key header name",
        default=os.environ.get("SERVICENOW_API_KEY_HEADER", "X-ServiceNow-API-Key"),
    )

    # Browser auth
    browser_group = parser.add_argument_group("Browser Authentication")
    browser_group.add_argument(
        "--browser-username",
        help="ServiceNow username for browser login",
        default=os.environ.get("SERVICENOW_BROWSER_USERNAME"),
    )
    browser_group.add_argument(
        "--browser-password",
        help="ServiceNow password for browser login",
        default=os.environ.get("SERVICENOW_BROWSER_PASSWORD"),
    )
    browser_group.add_argument(
        "--browser-login-url",
        help="Login URL for browser authentication",
        default=os.environ.get("SERVICENOW_BROWSER_LOGIN_URL"),
    )
    browser_group.add_argument(
        "--browser-probe-path",
        help="Probe path used to validate browser-authenticated API sessions",
        default=os.environ.get("SERVICENOW_BROWSER_PROBE_PATH"),
    )
    browser_group.add_argument(
        "--browser-headless",
        help="Run browser in headless mode (true/false)",
        default=os.environ.get("SERVICENOW_BROWSER_HEADLESS", "false"),
    )
    browser_group.add_argument(
        "--browser-timeout",
        type=int,
        help="Browser login timeout in seconds",
        default=int(os.environ.get("SERVICENOW_BROWSER_TIMEOUT", "120")),
    )
    browser_group.add_argument(
        "--browser-user-data-dir",
        help="User data directory for persistent browser sessions",
        default=os.environ.get("SERVICENOW_BROWSER_USER_DATA_DIR"),
    )
    browser_group.add_argument(
        "--browser-session-ttl",
        type=int,
        help="Minutes to keep browser session cookies before re-login",
        default=int(os.environ.get("SERVICENOW_BROWSER_SESSION_TTL", "30")),
    )

    # Tool package
    parser.add_argument(
        "--tool-package",
        help="Tool package to load (e.g., standard, portal_developer, platform_developer, service_desk, full)",
        default=os.environ.get("MCP_TOOL_PACKAGE"),
    )

    # Script execution API resource path
    script_execution_group = parser.add_argument_group("Script Execution API")
    script_execution_group.add_argument(
        "--script-execution-api-resource-path",
        help="Script execution API resource path",
        default=os.environ.get("SCRIPT_EXECUTION_API_RESOURCE_PATH"),
    )

    return parser.parse_args()


def create_config(args) -> ServerConfig:
    """
    Create server configuration from command-line arguments.

    Args:
        args: Command-line arguments.

    Returns:
        ServerConfig: Server configuration.

    Raises:
        ValueError: If required configuration is missing.
    """
    # NOTE: This assumes the ServerConfig model takes instance_url, auth, debug, timeout etc.
    # The ServiceNowMCP class now expects a ServerConfig object matching this.

    # Instance URL validation
    instance_url = args.instance_url
    if not instance_url:
        # Attempt to load from .env if not provided via args/env vars directly in parse_args
        instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
        if not instance_url:
            raise ValueError(
                "ServiceNow instance URL is required (--instance-url or SERVICENOW_INSTANCE_URL env var)"
            )

    # Create authentication configuration based on args
    auth_type = AuthType(args.auth_type.lower())
    # This will hold the final AuthConfig instance for ServerConfig
    final_auth_config: AuthConfig

    if auth_type == AuthType.BASIC:
        username = _pick_first_resolved(args.username, os.getenv("SERVICENOW_USERNAME"))
        password = _pick_first_resolved(
            args.password, os.getenv("SERVICENOW_PASSWORD")
        )  # Get password from arg or env
        if not username or not password:
            raise ValueError(
                "Username and password are required for basic authentication "
                "(--username/SERVICENOW_USERNAME, --password/SERVICENOW_PASSWORD)"
            )
        # Create the specific config (without instance_url)
        basic_cfg = BasicAuthConfig(
            username=username,
            password=password,
        )
        # Create the main AuthConfig wrapper
        final_auth_config = AuthConfig(type=auth_type, basic=basic_cfg)

    elif auth_type == AuthType.OAUTH:
        # Simplified - assuming password grant for now based on previous args
        client_id = args.client_id or os.getenv("SERVICENOW_CLIENT_ID")
        client_secret = args.client_secret or os.getenv("SERVICENOW_CLIENT_SECRET")
        username = _pick_first_resolved(
            args.username, os.getenv("SERVICENOW_USERNAME")
        )  # Needed for password grant
        password = _pick_first_resolved(
            args.password, os.getenv("SERVICENOW_PASSWORD")
        )  # Needed for password grant
        token_url = args.token_url or os.getenv("SERVICENOW_TOKEN_URL")

        if not client_id or not client_secret or not username or not password:
            raise ValueError(
                "Client ID, client secret, username, and password are required for OAuth password grant"
                " (--client-id/SERVICENOW_CLIENT_ID, etc.)"
            )
        if not token_url:
            # Attempt to construct default if not provided
            token_url = f"{instance_url}/oauth_token.do"
            logger.warning(f"OAuth token URL not provided, defaulting to: {token_url}")

        # Create the specific config (without instance_url)
        oauth_cfg = OAuthConfig(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            token_url=token_url,
        )
        # Create the main AuthConfig wrapper
        final_auth_config = AuthConfig(type=auth_type, oauth=oauth_cfg)

    elif auth_type == AuthType.API_KEY:
        api_key = args.api_key or os.getenv("SERVICENOW_API_KEY")
        api_key_header = args.api_key_header or os.getenv(
            "SERVICENOW_API_KEY_HEADER", "X-ServiceNow-API-Key"
        )
        if not api_key:
            raise ValueError(
                "API key is required for API key authentication (--api-key or SERVICENOW_API_KEY)"
            )
        # Create the specific config (without instance_url)
        api_key_cfg = ApiKeyConfig(
            api_key=api_key,
            header_name=api_key_header,
        )
        # Create the main AuthConfig wrapper
        final_auth_config = AuthConfig(type=auth_type, api_key=api_key_cfg)
    elif auth_type == AuthType.BROWSER:
        browser_username = _pick_first_resolved(
            args.browser_username,
            os.getenv("SERVICENOW_BROWSER_USERNAME"),
            os.getenv("SERVICENOW_USERNAME"),
        )
        browser_password = _pick_first_resolved(
            args.browser_password,
            os.getenv("SERVICENOW_BROWSER_PASSWORD"),
            os.getenv("SERVICENOW_PASSWORD"),
        )
        browser_login_url = args.browser_login_url or os.getenv("SERVICENOW_BROWSER_LOGIN_URL")
        _explicit_probe = args.browser_probe_path or os.getenv("SERVICENOW_BROWSER_PROBE_PATH")
        if _explicit_probe:
            browser_probe_path = _explicit_probe
        elif browser_username:
            # Build a user-specific probe so the endpoint always returns 200 for valid
            # sessions. Listing all sys_user records requires admin and returns 401 for
            # regular users, making it impossible to distinguish "session expired" from
            # "ACL restriction" when the probe returns 401.
            _enc = urllib.parse.quote(browser_username, safe="")
            browser_probe_path = (
                f"/api/now/table/sys_user"
                f"?sysparm_query=user_name%3D{_enc}&sysparm_limit=1&sysparm_fields=sys_id"
            )
        else:
            browser_probe_path = (
                "/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id"
            )
        browser_headless = str(args.browser_headless).lower() == "true"
        browser_timeout = args.browser_timeout or int(
            os.getenv("SERVICENOW_BROWSER_TIMEOUT", "120")
        )
        browser_user_data_dir = args.browser_user_data_dir or os.getenv(
            "SERVICENOW_BROWSER_USER_DATA_DIR"
        )
        browser_session_ttl = args.browser_session_ttl or int(
            os.getenv("SERVICENOW_BROWSER_SESSION_TTL", "30")
        )

        browser_cfg = BrowserAuthConfig(
            username=browser_username,
            password=browser_password,
            login_url=browser_login_url,
            probe_path=browser_probe_path,
            headless=browser_headless,
            timeout_seconds=browser_timeout,
            user_data_dir=browser_user_data_dir,
            session_ttl_minutes=browser_session_ttl,
        )
        final_auth_config = AuthConfig(type=auth_type, browser=browser_cfg)
    else:
        # Should not happen if choices are enforced by argparse
        raise ValueError(f"Unsupported authentication type: {args.auth_type}")

    # Script execution path
    script_execution_api_resource_path = args.script_execution_api_resource_path or os.getenv(
        "SCRIPT_EXECUTION_API_RESOURCE_PATH"
    )
    if not script_execution_api_resource_path:
        logger.warning(
            "Script execution API resource path not set (--script-execution-api-resource-path or SCRIPT_EXECUTION_API_RESOURCE_PATH). ExecuteScriptInclude tool may fail."
        )

    # Create the final ServerConfig
    # Ensure ServerConfig model expects 'auth' as a nested object
    return ServerConfig(
        instance_url=instance_url,  # Add instance_url directly here
        auth=final_auth_config,  # Pass the correctly structured AuthConfig instance
        # Include other server config fields if they exist on ServerConfig model
        debug=args.debug,
        timeout=args.timeout,
        script_execution_api_resource_path=script_execution_api_resource_path,
    )


async def arun_server(server_instance):
    """Runs the given MCP server instance using stdio transport."""
    from mcp.server.stdio import stdio_server

    logger.info("Starting server with stdio transport...")
    async with stdio_server() as streams:
        # Get initialization options from the low-level server
        init_options = server_instance.create_initialization_options()
        await server_instance.run(streams[0], streams[1], init_options)
    logger.info("Stdio server finished.")


def _check_for_updates() -> None:
    """Check PyPI for a newer version and log a warning if available."""
    try:
        current = __version__
        req = urllib.request.Request(_PYPI_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            latest = json.loads(resp.read())["info"]["version"]
        if latest != current:
            logger.warning(
                f"New version available: {latest} (current: {current}). "
                f"Upgrade: uvx {_PACKAGE_NAME}@latest  or  pip install -U {_PACKAGE_NAME}"
            )
    except Exception:
        pass


def _ensure_playwright_browser(args) -> None:
    """Auto-install Playwright Chromium if browser auth is selected and binary is missing."""
    auth_type = _pick_first_resolved(args.auth_type, os.getenv("SERVICENOW_AUTH_TYPE"))
    if auth_type != "browser":
        return

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Try to get chromium executable path — raises if not installed
            p.chromium.executable_path  # noqa: B018
    except Exception:
        logger.info("Chromium not found. Installing automatically...")
        try:
            import subprocess

            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=True,
                timeout=120,
            )
            logger.info("Chromium installed successfully.")
        except Exception as exc:
            logger.warning(f"Auto-install failed: {exc}. Run manually: playwright install chromium")


def main():
    """Main entry point for the CLI."""
    # Load environment variables from .env file
    from dotenv import load_dotenv

    load_dotenv()

    if len(sys.argv) > 1 and sys.argv[1] in {"setup", "remove", "uninstall"}:
        from servicenow_mcp import setup_installer

        action = sys.argv[1]
        if action == "uninstall":
            action = "remove"

        try:
            raise SystemExit(setup_installer.main(sys.argv[2:], action=action))
        except ValueError as e:
            logger.error(f"{action.capitalize()} error: {e}")
            raise SystemExit(1) from e

    try:
        # Parse command-line arguments
        args = parse_args()

        # Configure logging level based on debug flag
        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)
            logger.info("Debug logging enabled.")
        else:
            logging.getLogger().setLevel(logging.INFO)

        # Propagate --tool-package to env so server.py picks it up
        if args.tool_package:
            os.environ["MCP_TOOL_PACKAGE"] = args.tool_package

        # Check for newer version (non-blocking, silent on failure)
        _check_for_updates()

        # Auto-install Playwright Chromium if browser auth is selected
        _ensure_playwright_browser(args)

        # Create server configuration
        config = create_config(args)
        # Log the instance URL being used (mask sensitive parts of config if needed)
        logger.info(f"Initializing ServiceNow MCP server for instance: {config.instance_url}")

        # Create server controller instance
        mcp_controller = ServiceNowMCP(config)

        # Get the low-level server instance to run
        server_to_run = mcp_controller.start()

        # Run the server using anyio and the stdio transport
        import anyio

        anyio.run(arun_server, server_to_run)

    except ValueError as e:
        logger.error(f"Configuration or runtime error: {e}")
        sys.exit(1)

    except Exception as e:
        logger.exception(f"Unexpected error starting or running server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
