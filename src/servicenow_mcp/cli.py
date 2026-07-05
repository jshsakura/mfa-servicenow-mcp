"""
Command-line interface for the ServiceNow MCP server.
"""

import argparse
import json
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path


def _maybe_use_bundled_chromium() -> None:
    """If a ms-play*/ directory sits next to the running executable and
    holds at least one chromium-* subdir, point Playwright at it via
    PLAYWRIGHT_BROWSERS_PATH for this process.

    Matches the `ms-play*` glob (not just exact `ms-playwright/`) so users
    can extract the bundled zip with whatever default name their unzip
    tool produces (`ms-playwright-chromium-linux-x64-1.13.7/`, …) without
    having to rename it. Skipped when:
      - PLAYWRIGHT_BROWSERS_PATH is already set (user override wins), or
      - no sibling directory with a chromium-* subdir exists (uvx/dev
        mode → Playwright falls back to its standard cache, which is
        what we want there).
    """
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    exe_dir = Path(sys.executable).resolve().parent
    for candidate in sorted(exe_dir.glob("ms-play*")):
        if not candidate.is_dir():
            continue
        if any(candidate.glob("chromium-*")):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)
            return


_maybe_use_bundled_chromium()

from .server import ServiceNowMCP  # noqa: E402
from .utils.config import (  # noqa: E402
    ApiKeyConfig,
    AuthConfig,
    AuthType,
    BasicAuthConfig,
    BrowserAuthConfig,
    OAuthConfig,
    ServerConfig,
)
from .utils.instances import (  # noqa: E402
    ACTIVE_INSTANCE_ENV,
    INSTANCE_CONFIG_ENV,
    build_instance_definition,
    load_instance_config_env,
    resolve_auth_type,
    resolve_env_reference,
    select_active_alias,
)
from .version import __version__  # noqa: E402

# Opt-in file logging: stderr-only by default (preserves the v1.11.47
# decision to let users manage log paths via shell redirect). When
# LOG_FILE is set, also write to that path with rotation so a runaway
# session can't fill the disk.
#
# If LOG_FILE points to a directory (or ends with a path separator),
# auto-append a host-tagged filename so multiple instances running
# concurrently don't interleave into the same file. This restores the
# v1.11.46 host-tagging idea on top of the v1.11.47 opt-in default.


def _instance_host_slug() -> str:
    url = os.getenv("SERVICENOW_INSTANCE_URL", "")
    if not url:
        return "default"
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except (TypeError, ValueError):
        return "default"
    if not host:
        return "default"
    return re.sub(r"[^A-Za-z0-9._-]", "_", host)


def configure_logging(force: bool = False) -> None:
    """Configure root logging (stderr + optional rotating LOG_FILE).

    Called explicitly from ``main()`` with ``force=True``. Keeping this OUT of
    module import means ``import servicenow_mcp.cli`` has no logging side effect:
    embedders/tests/other launchers that import this module keep their own
    logging config. With ``force=False`` we no-op when the root logger already
    has handlers, so we never stomp on a host application's configuration.

    Opt-in file logging: stderr-only by default (preserves the v1.11.47 decision
    to let users manage log paths via shell redirect). When LOG_FILE is set, also
    write there with rotation so a runaway session can't fill the disk. If
    LOG_FILE points to a directory (or ends with a separator), auto-append a
    host-tagged filename so concurrent instances don't interleave into one file.
    """
    root_logger = logging.getLogger()
    if root_logger.handlers and not force:
        return

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file_path = os.getenv("LOG_FILE")
    if log_file_path:
        try:
            log_file_path = os.path.expanduser(log_file_path)
            if os.path.isdir(log_file_path) or log_file_path.endswith(os.sep):
                log_file_path = os.path.join(
                    log_file_path, f"servicenow-mcp_{_instance_host_slug()}.log"
                )
            log_dir = os.path.dirname(log_file_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            handlers.append(
                logging.handlers.RotatingFileHandler(
                    log_file_path,
                    maxBytes=10_000_000,
                    backupCount=3,
                    encoding="utf-8",
                )
            )
        except OSError:
            # Silent fallback to stderr-only — never block startup on log path issues.
            pass

    # Wire handlers onto the root logger directly. logging.basicConfig is a
    # no-op when the root logger already has handlers, and importing .server
    # pulls in mcp/anyio which can register a default handler first — so
    # basicConfig would silently drop our RotatingFileHandler (the
    # v1.12.8/v1.12.9 symptom). Reset and re-attach explicitly so we don't
    # depend on import-order luck.
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    root_logger.setLevel(logging.INFO)
    for existing_handler in list(root_logger.handlers):
        root_logger.removeHandler(existing_handler)
    for handler in handlers:
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)


logger = logging.getLogger(__name__)


_PACKAGE_NAME = "mfa-servicenow-mcp"
_PYPI_URL = f"https://pypi.org/pypi/{_PACKAGE_NAME}/json"

# ${ENV_NAME} indirection — canonical implementation lives in utils.instances
# so the server's named-instance contexts resolve the same way.
_resolve_env_reference = resolve_env_reference


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


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _default_http_allowed_hosts(host: str, port: int) -> list[str]:
    hosts = {
        host,
        f"{host}:{port}",
        "localhost",
        f"localhost:{port}",
        "127.0.0.1",
        f"127.0.0.1:{port}",
        "::1",
        f"[::1]:{port}",
    }
    if host in {"0.0.0.0", "::"}:
        hosts.update({"0.0.0.0", f"0.0.0.0:{port}", "::", f"[::]:{port}"})
    return sorted(hosts)


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

    # MCP transport
    transport_group = parser.add_argument_group("MCP Transport")
    transport_group.add_argument(
        "--transport",
        choices=["stdio", "http"],
        help="MCP transport to run: stdio (default) or streamable HTTP",
        default=os.environ.get("SERVICENOW_MCP_TRANSPORT", "stdio"),
    )
    transport_group.add_argument(
        "--http-host",
        help="Host for --transport http",
        default=os.environ.get("SERVICENOW_MCP_HTTP_HOST", "127.0.0.1"),
    )
    transport_group.add_argument(
        "--http-port",
        type=int,
        help="Port for --transport http",
        default=int(os.environ.get("SERVICENOW_MCP_HTTP_PORT", "8000")),
    )
    transport_group.add_argument(
        "--http-path",
        help="MCP endpoint path for --transport http",
        default=os.environ.get("SERVICENOW_MCP_HTTP_PATH", "/mcp"),
    )
    transport_group.add_argument(
        "--http-json-response",
        action="store_true",
        help="Return JSON responses instead of SSE streams for HTTP requests",
        default=_env_bool("SERVICENOW_MCP_HTTP_JSON_RESPONSE", False),
    )
    transport_group.add_argument(
        "--http-allowed-hosts",
        help="Comma-separated allowed Host headers for HTTP DNS rebinding protection",
        default=os.environ.get("SERVICENOW_MCP_HTTP_ALLOWED_HOSTS"),
    )
    transport_group.add_argument(
        "--http-disable-dns-rebinding-protection",
        action="store_true",
        help="Disable HTTP DNS rebinding protection. Use only behind trusted network controls.",
        default=_env_bool("SERVICENOW_MCP_HTTP_DISABLE_DNS_REBINDING_PROTECTION", False),
    )
    transport_group.add_argument(
        "--http-auth-token",
        help=(
            "Bearer token required on every HTTP MCP request. Mandatory for a "
            "non-loopback --http-host; optional (but enforced when set) on loopback."
        ),
        default=os.environ.get("SERVICENOW_MCP_HTTP_AUTH_TOKEN"),
    )

    # Authentication
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument(
        "--auth-type",
        choices=["basic", "oauth", "api_key", "browser"],
        help="Authentication type",
        default=os.environ.get("SERVICENOW_AUTH_TYPE", "browser"),
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
        default=int(os.environ.get("SERVICENOW_BROWSER_TIMEOUT", "90")),
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

    # Instance URL validation. SERVICENOW_INSTANCE_CONFIG is an opt-in layer:
    # without SERVICENOW_ACTIVE_INSTANCE, legacy SERVICENOW_INSTANCE_URL behavior
    # wins so existing single-instance installs do not change.
    instance_entries = load_instance_config_env(os.getenv(INSTANCE_CONFIG_ENV))
    active_alias = select_active_alias(
        instance_entries,
        active_alias=os.getenv(ACTIVE_INSTANCE_ENV),
        legacy_instance_url=args.instance_url or os.getenv("SERVICENOW_INSTANCE_URL"),
    )
    active_entry = (
        build_instance_definition(active_alias, instance_entries[active_alias])
        if active_alias
        else None
    )

    instance_url = active_entry.url if active_entry else args.instance_url
    if not instance_url:
        # Attempt to load from .env if not provided via args/env vars directly in parse_args
        instance_url = os.getenv("SERVICENOW_INSTANCE_URL")
        if not instance_url:
            raise ValueError(
                "ServiceNow instance URL is required (--instance-url or SERVICENOW_INSTANCE_URL env var)"
            )

    # Create authentication configuration based on args.
    # Browser (headless) is the default. Per-profile username/password select
    # WHO (prefill + declared owner), never the auth type — an explicit
    # auth_type on the entry is the only way to change it. Mirrors
    # server._auth_for_instance_entry so active and named instances behave alike.
    active_raw = active_entry.raw if active_entry and active_entry.raw else {}
    auth_type_value = resolve_auth_type(active_raw, args.auth_type)
    auth_type = AuthType(auth_type_value.lower())
    # This will hold the final AuthConfig instance for ServerConfig
    final_auth_config: AuthConfig

    if auth_type == AuthType.BASIC:
        username = _pick_first_resolved(
            active_raw.get("username"),
            args.username,
            os.getenv("SERVICENOW_USERNAME"),
        )
        password = _pick_first_resolved(
            active_raw.get("password"),
            args.password,
            os.getenv("SERVICENOW_PASSWORD"),
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
        client_id = (
            active_raw.get("client_id") or args.client_id or os.getenv("SERVICENOW_CLIENT_ID")
        )
        client_secret = (
            active_raw.get("client_secret")
            or args.client_secret
            or os.getenv("SERVICENOW_CLIENT_SECRET")
        )
        username = _pick_first_resolved(
            active_raw.get("username"),
            args.username,
            os.getenv("SERVICENOW_USERNAME"),
        )  # Needed for password grant
        password = _pick_first_resolved(
            active_raw.get("password"),
            args.password,
            os.getenv("SERVICENOW_PASSWORD"),
        )  # Needed for password grant
        token_url = (
            active_raw.get("token_url") or args.token_url or os.getenv("SERVICENOW_TOKEN_URL")
        )

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
        api_key = active_raw.get("api_key") or args.api_key or os.getenv("SERVICENOW_API_KEY")
        api_key_header = (
            active_raw.get("api_key_header")
            or args.api_key_header
            or os.getenv("SERVICENOW_API_KEY_HEADER", "X-ServiceNow-API-Key")
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
            active_raw.get("username"),
            args.browser_username,
            os.getenv("SERVICENOW_BROWSER_USERNAME"),
            os.getenv("SERVICENOW_USERNAME"),
        )
        browser_password = _pick_first_resolved(
            active_raw.get("password"),
            args.browser_password,
            os.getenv("SERVICENOW_BROWSER_PASSWORD"),
            os.getenv("SERVICENOW_PASSWORD"),
        )
        browser_login_url = (
            active_raw.get("login_url")
            or args.browser_login_url
            or os.getenv("SERVICENOW_BROWSER_LOGIN_URL")
        )
        _explicit_probe = (
            active_raw.get("probe_path")
            or args.browser_probe_path
            or os.getenv("SERVICENOW_BROWSER_PROBE_PATH")
        )
        if _explicit_probe:
            browser_probe_path = _explicit_probe
        else:
            # ============================================================
            # DO NOT CHANGE THIS DEFAULT — sys_user_preference is mandatory.
            # ============================================================
            # History (READ THIS BEFORE TOUCHING):
            #   2026-04-22 (commit 2959b87) introduced a "clever" default
            #   that built `/api/now/table/sys_user?sysparm_query=user_name=...`
            #   when a username was set. The reasoning sounded good — every
            #   user can read their own sys_user record, so 200 unambiguously
            #   means valid session, 401 means expired. WRONG.
            #
            #   Many ServiceNow instances (a hardened customer instance was
            #   the first confirmed case) deny regular users read on the sys_user
            #   table entirely, OR the row-level "Read for self" ACL doesn't
            #   apply to list/query API calls. Result: probe always returns
            #   401, polling loop never confirms login, browser window stays
            #   open until wait_budget expires, user closes it manually,
            #   LLM auto-retries → infinite loop.
            #
            #   Cost of this regression: 8 patch versions (v1.10.16-v1.10.24)
            #   chasing downstream symptoms before stderr log identified the
            #   real cause. v1.11.0 is the first release where the auth flow
            #   is correct end-to-end on instances without sys_user read.
            #
            # WHY sys_user_preference IS THE RIGHT CHOICE:
            #   - ServiceNow stores per-user UI settings (theme, favorites,
            #     etc.) in sys_user_preference. The UI cannot function if a
            #     logged-in user cannot read their own preferences, so
            #     virtually every instance grants this read.
            #   - 200 unambiguously = valid session.
            #   - 401 unambiguously = expired session (NOT ACL).
            #
            # IF THIS PROBE EVER FAILS in a hardened instance:
            #   - User can override with SERVICENOW_BROWSER_PROBE_PATH.
            #   - Recommended fallbacks (priority order):
            #       /api/now/ui/user/current_user
            #       /login_locale.do          (loose; redirect = expired)
            #   - DO NOT add an auto-fallback chain or a username-based
            #     query here. Keep this default boring and predictable.
            # ============================================================
            browser_probe_path = (
                "/api/now/table/sys_user_preference?sysparm_limit=1&sysparm_fields=sys_id"
            )
        browser_headless = str(active_raw.get("headless", args.browser_headless)).lower() == "true"
        browser_timeout = (
            active_raw.get("timeout_seconds")
            or args.browser_timeout
            or int(os.getenv("SERVICENOW_BROWSER_TIMEOUT", "90"))
        )
        browser_user_data_dir = (
            active_raw.get("user_data_dir")
            or args.browser_user_data_dir
            or os.getenv("SERVICENOW_BROWSER_USER_DATA_DIR")
        )
        browser_session_ttl = (
            active_raw.get("session_ttl_minutes")
            or args.browser_session_ttl
            or int(os.getenv("SERVICENOW_BROWSER_SESSION_TTL", "30"))
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

    # Create the final ServerConfig
    # Ensure ServerConfig model expects 'auth' as a nested object
    return ServerConfig(
        instance_url=instance_url,  # Add instance_url directly here
        auth=final_auth_config,  # Pass the correctly structured AuthConfig instance
        # Include other server config fields if they exist on ServerConfig model
        debug=args.debug,
        timeout=args.timeout,
    )


def _start_parent_watchdog() -> None:
    """Exit when the parent process dies (defends against ghost MCP servers).

    The MCP host (Claude Code, Codex, etc.) launches us with stdin/stdout
    pipes. If the host crashes abruptly, the OS *should* close stdin and
    we *should* exit cleanly — but in practice ghost servers accumulate
    when the host dies in a way that doesn't drop the pipes (e.g. parent
    forks, original parent dies, child holds the pipes open). One observed
    incident left 16 zombie servicenow-mcp processes consuming memory and
    holding locks across multiple Claude Code sessions.

    This watchdog polls os.getppid() every 5 seconds. On both Linux and
    macOS, when the original parent dies the kernel reparents the process
    to PID 1 (init/launchd), so the ppid changes and we self-exit.
    """
    parent_pid = os.getppid()
    if parent_pid <= 1:
        return  # Already orphaned / running detached — nothing to watch.

    def _watch() -> None:
        while True:
            time.sleep(5)
            try:
                current = os.getppid()
            except Exception:
                return
            if current != parent_pid or current <= 1:
                logger.info(
                    "Parent process exited (was %d, now %d). Shutting down to "
                    "avoid becoming a ghost server.",
                    parent_pid,
                    current,
                )
                os._exit(0)

    thread = threading.Thread(target=_watch, daemon=True, name="parent-watchdog")
    thread.start()


async def arun_server(server_instance):
    """Runs the given MCP server instance using stdio transport."""
    from mcp.server.stdio import stdio_server

    _start_parent_watchdog()
    logger.info("Starting server with stdio transport...")
    async with stdio_server() as streams:
        # Get initialization options from the low-level server
        init_options = server_instance.create_initialization_options()
        await server_instance.run(streams[0], streams[1], init_options)
    logger.info("Stdio server finished.")


async def arun_http_server(server_instance, args):
    """Runs the given MCP server instance using Streamable HTTP transport."""
    from contextlib import asynccontextmanager

    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    from servicenow_mcp.utils.http_auth import is_authorized, resolve_http_auth_token

    path = args.http_path if str(args.http_path).startswith("/") else f"/{args.http_path}"
    # Fail closed BEFORE binding: a non-loopback host with no token is refused.
    auth_token = resolve_http_auth_token(args.http_host, getattr(args, "http_auth_token", None))
    allowed_hosts = _split_csv(args.http_allowed_hosts) or _default_http_allowed_hosts(
        args.http_host, args.http_port
    )
    security_settings = TransportSecuritySettings(
        enable_dns_rebinding_protection=not args.http_disable_dns_rebinding_protection,
        allowed_hosts=allowed_hosts,
    )
    session_manager = StreamableHTTPSessionManager(
        server_instance,
        json_response=args.http_json_response,
        stateless=False,
        security_settings=security_settings,
        session_idle_timeout=1800,
    )

    class StreamableHTTPApp:
        async def __call__(self, scope, receive, send):
            # Bearer gate on the MCP surface only (never on /health). Constant-time
            # compared. Non-HTTP scopes (lifespan) pass straight through.
            if auth_token is not None and scope.get("type") == "http":
                header_map = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
                auth_header = header_map.get("authorization", b"").decode("latin-1")
                if not is_authorized(auth_header, auth_token):
                    await JSONResponse(
                        {"error": "unauthorized", "detail": "Bearer token required or invalid."},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )(scope, receive, send)
                    return
            await session_manager.handle_request(scope, receive, send)

    async def health(_request):
        return JSONResponse({"status": "ok", "transport": "http", "mcp_path": path})

    @asynccontextmanager
    async def lifespan(_app):
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/health", endpoint=health, methods=["GET"]),
            Mount(path, app=StreamableHTTPApp()),
        ],
        lifespan=lifespan,
    )

    _start_parent_watchdog()
    logger.info(
        "Starting server with Streamable HTTP transport on http://%s:%s%s",
        args.http_host,
        args.http_port,
        path,
    )
    config = uvicorn.Config(
        app,
        host=args.http_host,
        port=args.http_port,
        log_level="debug" if args.debug else "info",
    )
    server = uvicorn.Server(config)
    await server.serve()


def _parse_version(value: str) -> tuple:
    """Parse 'x.y.z' into a comparable int tuple. Non-numeric suffixes per
    segment are dropped (e.g. '2rc1' -> 2); unparseable segments become 0."""
    parts = []
    for segment in str(value).split("."):
        digits = ""
        for ch in segment:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _is_strictly_newer(latest: str, current: str) -> bool:
    """True only when *latest* is a higher version than *current*.

    Guards against the build running AHEAD of PyPI (e.g. a freshly tagged
    1.14.13 while PyPI still serves 1.14.12) — which a plain ``!=`` mistook for
    an available upgrade and advised a downgrade.
    """
    try:
        return _parse_version(latest) > _parse_version(current)
    except Exception:
        return False


def _check_for_updates() -> None:
    """Check PyPI for a newer version and log a warning if available."""
    try:
        current = __version__
        req = urllib.request.Request(_PYPI_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            latest = json.loads(resp.read())["info"]["version"]
        if _is_strictly_newer(latest, current):
            logger.warning(
                f"New version available: {latest} (current: {current}). "
                f"Upgrade: uvx {_PACKAGE_NAME}@latest  or  pip install -U {_PACKAGE_NAME}"
            )
    except Exception:
        pass


def _warn_if_chromium_missing(args) -> None:
    """Detect a missing Playwright Chromium binary and surface a clear warning.

    Does NOT install — a ~150 MB download inside MCP startup would stall the
    handshake long enough for hosts (e.g. Codex) to time out and report
    "connection closed: initialize response". The user installs Chromium
    explicitly via `servicenow-mcp setup` or the documented one-liner.
    """
    auth_type = _pick_first_resolved(args.auth_type, os.getenv("SERVICENOW_AUTH_TYPE"))
    if auth_type != "browser":
        return

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Raises if the binary is missing or the version mismatches.
            p.chromium.executable_path  # noqa: B018
    except Exception:
        logger.warning(
            "Playwright Chromium not available for browser auth. "
            "Install it before the first tool call:\n"
            "  uvx --with playwright playwright install chromium"
        )


def main():
    """Main entry point for the CLI."""
    # Configure logging first thing — force=True so the CLI always owns the root
    # logger regardless of any handler an imported module registered. Done before
    # load_dotenv() to match the prior import-time behavior (LOG_FILE is read
    # from the real environment, not from .env).
    configure_logging(force=True)

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

        # Startup banner. Stops "is the new version actually running?"
        # debugging dead-ends — print the version into stderr where every
        # log session has it on the first line.
        logger.info("mfa-servicenow-mcp version: %s", __version__)

        # Propagate --tool-package to env so server.py picks it up
        if args.tool_package:
            os.environ["MCP_TOOL_PACKAGE"] = args.tool_package

        # Check for newer version (non-blocking, silent on failure)
        _check_for_updates()

        # Warn if Chromium is missing — do NOT auto-install (would stall handshake)
        _warn_if_chromium_missing(args)

        # Create server configuration
        config = create_config(args)
        # Log the instance URL being used (mask sensitive parts of config if needed)
        logger.info(f"Initializing ServiceNow MCP server for instance: {config.instance_url}")

        # Create server controller instance
        mcp_controller = ServiceNowMCP(config)

        # Get the low-level server instance to run
        server_to_run = mcp_controller.start()

        # Run the server using anyio and the selected transport
        import anyio

        if args.transport == "http":
            anyio.run(arun_http_server, server_to_run, args)
        else:
            anyio.run(arun_server, server_to_run)

    except ValueError as e:
        logger.error(f"Configuration or runtime error: {e}")
        sys.exit(1)

    except Exception as e:
        logger.exception(f"Unexpected error starting or running server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
