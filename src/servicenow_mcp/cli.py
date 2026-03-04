"""
Command-line interface for the ServiceNow MCP server.
"""

import argparse
import importlib
import logging
import os
import sys

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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="ServiceNow MCP Server")

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
        username = args.username or os.getenv("SERVICENOW_USERNAME")
        password = args.password or os.getenv("SERVICENOW_PASSWORD")  # Get password from arg or env
        if not username or not password:
            raise ValueError(
                "Username and password are required for basic authentication (--username/SERVICENOW_USERNAME, --password/SERVICENOW_PASSWORD)"
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
        username = args.username or os.getenv("SERVICENOW_USERNAME")  # Needed for password grant
        password = args.password or os.getenv("SERVICENOW_PASSWORD")  # Needed for password grant
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
        browser_username = args.browser_username or os.getenv("SERVICENOW_BROWSER_USERNAME")
        browser_password = args.browser_password or os.getenv("SERVICENOW_BROWSER_PASSWORD")
        browser_login_url = args.browser_login_url or os.getenv("SERVICENOW_BROWSER_LOGIN_URL")
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
    import importlib

    stdio_module = importlib.import_module("mcp.server.stdio")
    stdio_server = getattr(stdio_module, "stdio_server")

    logger.info("Starting server with stdio transport...")
    async with stdio_server() as streams:
        # Get initialization options from the low-level server
        init_options = server_instance.create_initialization_options()
        await server_instance.run(streams[0], streams[1], init_options)
    logger.info("Stdio server finished.")


def main():
    """Main entry point for the CLI."""
    # Load environment variables from .env file
    dotenv_module = importlib.import_module("dotenv")
    load_dotenv = getattr(dotenv_module, "load_dotenv")
    load_dotenv()

    try:
        # Parse command-line arguments
        args = parse_args()

        # Configure logging level based on debug flag
        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)
            logger.info("Debug logging enabled.")
        else:
            logging.getLogger().setLevel(logging.INFO)

        # Create server configuration
        config = create_config(args)
        # Log the instance URL being used (mask sensitive parts of config if needed)
        logger.info(f"Initializing ServiceNow MCP server for instance: {config.instance_url}")

        # Create server controller instance
        mcp_controller = ServiceNowMCP(config)

        # Get the low-level server instance to run
        server_to_run = mcp_controller.start()

        # Run the server using anyio and the stdio transport
        anyio_module = importlib.import_module("anyio")
        anyio_run = getattr(anyio_module, "run")
        anyio_run(arun_server, server_to_run)

    except ValueError as e:
        logger.error(f"Configuration or runtime error: {e}")
        sys.exit(1)

    except Exception as e:
        logger.exception(f"Unexpected error starting or running server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
