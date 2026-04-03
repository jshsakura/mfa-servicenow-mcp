"""
Configuration module for the ServiceNow MCP server.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel


class AuthType(str, Enum):
    """Authentication types supported by the ServiceNow MCP server."""

    BASIC = "basic"
    OAUTH = "oauth"
    API_KEY = "api_key"
    BROWSER = "browser"


class BasicAuthConfig(BaseModel):
    """Configuration for basic authentication."""

    username: str
    password: str


class OAuthConfig(BaseModel):
    """Configuration for OAuth authentication."""

    client_id: str
    client_secret: str
    username: str
    password: str
    token_url: Optional[str] = None


class ApiKeyConfig(BaseModel):
    """Configuration for API key authentication."""

    api_key: str
    header_name: str = "X-ServiceNow-API-Key"


class BrowserAuthConfig(BaseModel):
    """Configuration for browser-based authentication."""

    username: Optional[str] = None
    password: Optional[str] = None
    login_url: Optional[str] = None
    probe_path: str = "/api/now/table/sys_user?sysparm_limit=1&sysparm_fields=sys_id"
    headless: bool = False
    timeout_seconds: int = 120
    user_data_dir: Optional[str] = None
    session_ttl_minutes: int = 30


class AuthConfig(BaseModel):
    """Authentication configuration."""

    type: AuthType
    basic: Optional[BasicAuthConfig] = None
    oauth: Optional[OAuthConfig] = None
    api_key: Optional[ApiKeyConfig] = None
    browser: Optional[BrowserAuthConfig] = None


class ServerConfig(BaseModel):
    """Server configuration."""

    instance_url: str
    auth: AuthConfig
    debug: bool = False
    timeout: int = 30
    connect_timeout: int = 10
    script_execution_api_resource_path: Optional[str] = None

    @property
    def api_url(self) -> str:
        """Get the API URL for the ServiceNow instance."""
        return f"{self.instance_url}/api/now"

    @property
    def request_timeout(self) -> tuple[int, int]:
        """Return (connect_timeout, read_timeout) tuple for requests library."""
        return (self.connect_timeout, self.timeout)
