"""
Authentication manager for the ServiceNow MCP server.
"""

import base64
import logging
import re
import time
from typing import Dict, Optional
from urllib.parse import urlparse

import requests

from ..utils.config import AuthConfig, AuthType, BrowserAuthConfig

logger = logging.getLogger(__name__)


class AuthManager:
    """
    Authentication manager for ServiceNow API.

    This class handles authentication with the ServiceNow API using
    different authentication methods.
    """

    def __init__(self, config: AuthConfig, instance_url: Optional[str] = None):
        """
        Initialize the authentication manager.

        Args:
            config: Authentication configuration.
            instance_url: ServiceNow instance URL.
        """
        self.config = config
        self.instance_url = instance_url
        self.token: Optional[str] = None
        self.token_type: Optional[str] = None
        self.token_expires_at: Optional[float] = None
        self._browser_cookie_header: Optional[str] = None
        self._browser_cookie_expires_at: Optional[float] = None
        self._browser_session_key: Optional[str] = None
        self._browser_last_validated_at: Optional[float] = None
        self._browser_validation_interval_seconds: int = 30

    def get_headers(self) -> Dict[str, str]:
        """
        Get the authentication headers for API requests.

        Returns:
            Dict[str, str]: Headers to include in API requests.
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self.config.type == AuthType.BASIC:
            if not self.config.basic:
                raise ValueError("Basic auth configuration is required")

            auth_str = f"{self.config.basic.username}:{self.config.basic.password}"
            encoded = base64.b64encode(auth_str.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"

        elif self.config.type == AuthType.OAUTH:
            if not self.token or self._is_token_expired():
                self._get_oauth_token()

            headers["Authorization"] = f"{self.token_type} {self.token}"

        elif self.config.type == AuthType.API_KEY:
            if not self.config.api_key:
                raise ValueError("API key configuration is required")

            headers[self.config.api_key.header_name] = self.config.api_key.api_key

        elif self.config.type == AuthType.BROWSER:
            if not self.config.browser:
                raise ValueError("Browser auth configuration is required")
            if not self._browser_cookie_header or self._is_browser_session_expired():
                # 세션 만료 시 사용자가 직접 로그인할 수 있도록 브라우저 표시
                force_interactive = self._is_browser_session_expired()
                if force_interactive:
                    logger.info("Browser session expired. Opening browser for re-authentication...")
                self._login_with_browser(self.config.browser, force_interactive=force_interactive)
            elif self._should_validate_browser_session():
                if not self._is_browser_session_valid(self.config.browser):
                    logger.info(
                        "Browser session is no longer valid on ServiceNow. "
                        "Opening browser for interactive re-authentication..."
                    )
                    self.invalidate_browser_session()
                    self._login_with_browser(self.config.browser, force_interactive=True)
            headers["Cookie"] = self._browser_cookie_header or ""

        return headers

    def _is_token_expired(self) -> bool:
        if self.token_expires_at is None:
            return False
        return time.time() >= self.token_expires_at

    def _is_browser_session_expired(self) -> bool:
        if self._browser_cookie_expires_at is None:
            return False
        return time.time() >= self._browser_cookie_expires_at

    def _should_validate_browser_session(self) -> bool:
        if not self._browser_cookie_header:
            return False
        if self._browser_last_validated_at is None:
            return True
        return (
            time.time() - self._browser_last_validated_at
        ) >= self._browser_validation_interval_seconds

    def _is_browser_session_valid(self, browser_config: BrowserAuthConfig) -> bool:
        if not self.instance_url or not self._browser_cookie_header:
            return False

        probe_url = f"{self.instance_url}/api/now/table/sys_user"
        probe_params = {"sysparm_limit": 1, "sysparm_fields": "sys_id"}
        probe_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Cookie": self._browser_cookie_header,
        }

        try:
            response = requests.get(
                probe_url,
                params=probe_params,
                headers=probe_headers,
                timeout=min(int(browser_config.timeout_seconds), 30),
            )
        except requests.RequestException as exc:
            logger.warning(
                f"Browser session validation probe failed due to network/request issue: {exc}. "
                "Keeping current session and continuing."
            )
            return True

        self._browser_last_validated_at = time.time()

        if response.status_code in (401, 403):
            return False

        location = response.headers.get("Location", "").lower()
        if response.is_redirect and "login.do" in location:
            return False

        return True

    def _get_oauth_token(self):
        """
        Get an OAuth token from ServiceNow.

        Raises:
            ValueError: If OAuth configuration is missing or token request fails.
        """
        if not self.config.oauth:
            raise ValueError("OAuth configuration is required")
        oauth_config = self.config.oauth

        # Determine token URL
        token_url = oauth_config.token_url
        if not token_url:
            if not self.instance_url:
                raise ValueError("Instance URL is required for OAuth authentication")
            instance_parts = self.instance_url.split(".")
            if len(instance_parts) < 2:
                raise ValueError(f"Invalid instance URL: {self.instance_url}")
            instance_name = instance_parts[0].split("//")[-1]
            token_url = f"https://{instance_name}.service-now.com/oauth_token.do"

        # Prepare Authorization header
        auth_str = f"{oauth_config.client_id}:{oauth_config.client_secret}"
        auth_header = base64.b64encode(auth_str.encode()).decode()
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Try client_credentials grant first
        data_client_credentials = {"grant_type": "client_credentials"}

        logger.info("Attempting client_credentials grant...")
        response = requests.post(token_url, headers=headers, data=data_client_credentials)

        logger.info(f"client_credentials response status: {response.status_code}")

        if response.status_code == 200:
            token_data = response.json()
            self.token = token_data.get("access_token")
            self.token_type = token_data.get("token_type", "Bearer")
            expires_in = token_data.get("expires_in")
            if isinstance(expires_in, (int, float)):
                self.token_expires_at = time.time() + float(expires_in)
            return

        # Try password grant if client_credentials failed
        if oauth_config.username and oauth_config.password:
            data_password = {
                "grant_type": "password",
                "username": oauth_config.username,
                "password": oauth_config.password,
            }

            logger.info("Attempting password grant...")
            response = requests.post(token_url, headers=headers, data=data_password)

            logger.info(f"password grant response status: {response.status_code}")

            if response.status_code == 200:
                token_data = response.json()
                self.token = token_data.get("access_token")
                self.token_type = token_data.get("token_type", "Bearer")
                expires_in = token_data.get("expires_in")
                if isinstance(expires_in, (int, float)):
                    self.token_expires_at = time.time() + float(expires_in)
                return

        raise ValueError(
            "Failed to get OAuth token using both client_credentials and password grants."
        )

    def refresh_token(self):
        """Refresh the OAuth token if using OAuth authentication."""
        if self.config.type == AuthType.OAUTH:
            self._get_oauth_token()

    def _login_with_browser(
        self, browser_config: BrowserAuthConfig, force_interactive: bool = False
    ):
        instance_url = self.instance_url
        if not instance_url:
            raise ValueError("Instance URL is required for browser authentication")

        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise ValueError(
                "Playwright is required for browser authentication. "
                "Install with: pip install playwright && playwright install chromium"
            ) from exc

        login_url = browser_config.login_url or f"{instance_url}/login.do"
        timeout_ms = int(browser_config.timeout_seconds) * 1000
        instance_url_pattern = re.compile(re.escape(instance_url) + r"/.*")
        instance_host = (urlparse(instance_url).hostname or "").lower()

        # 세션 만료 시 강제로 브라우저 표시 (headless 설정 무시)
        use_headless = browser_config.headless and not force_interactive

        if use_headless and not self._browser_cookie_header:
            raise ValueError(
                "Initial MFA/SSO bootstrap should run with headless=false for interactive login"
            )
        with sync_playwright() as playwright:
            if browser_config.user_data_dir:
                context = playwright.chromium.launch_persistent_context(
                    browser_config.user_data_dir,
                    headless=use_headless,
                )
                page = context.pages[0] if context.pages else context.new_page()
            else:
                browser = playwright.chromium.launch(headless=use_headless)
                context = browser.new_context()
                page = context.new_page()

            page.goto(login_url, timeout=timeout_ms, wait_until="load")

            username = browser_config.username
            password = browser_config.password

            if username and password:
                user_selector = "input#user_name, input[name='user_name']"
                pass_selector = (
                    "input#user_password, input[name='user_password'], input[type='password']"
                )
                login_selector = "button#sysverb_login, input#sysverb_login, button[type='submit']"

                if page.locator(user_selector).count() > 0:
                    page.fill(user_selector, username)
                if page.locator(pass_selector).count() > 0:
                    page.fill(pass_selector, password)
                if page.locator(login_selector).count() > 0:
                    page.click(login_selector)
                elif page.locator(pass_selector).count() > 0:
                    page.locator(pass_selector).press("Enter")

            try:
                page.wait_for_url(instance_url_pattern, timeout=timeout_ms)
            except Exception:
                logger.info(
                    "Browser login waiting for manual completion (MFA/SSO). "
                    "Please complete login in the opened browser window."
                )
                page.wait_for_url(instance_url_pattern, timeout=timeout_ms)

            cookies = context.cookies(instance_url)
            if not cookies:
                raise ValueError("Browser login succeeded but no cookies were captured")

            filtered = []
            for cookie in cookies:
                domain = str(cookie.get("domain", "")).lstrip(".").lower()
                secure = bool(cookie.get("secure", False))
                if not domain.endswith(instance_host):
                    continue
                if instance_url.startswith("https://") and not secure:
                    continue
                filtered.append(cookie)

            if not filtered:
                raise ValueError("No instance-scoped secure cookies captured after login")

            cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in filtered])
            self._browser_cookie_header = cookie_header
            self._browser_cookie_expires_at = time.time() + (
                browser_config.session_ttl_minutes * 60
            )
            self._browser_session_key = (
                f"{instance_host}:{browser_config.username or 'interactive'}"
            )
            self._browser_last_validated_at = time.time()

            context.close()

    def invalidate_browser_session(self):
        """Invalidate the current browser session, forcing re-authentication on next request."""
        logger.info("Browser session invalidated")
        self._browser_cookie_header = None
        self._browser_cookie_expires_at = None
        self._browser_last_validated_at = None

    def make_request(
        self,
        method: str,
        url: str,
        max_retries: int = 1,
        **kwargs,
    ) -> requests.Response:
        """
        Make an authenticated HTTP request with automatic retry on 401.

        For Browser Auth, 401 responses trigger session invalidation and
        re-authentication before retry.

        Args:
            method: HTTP method (GET, POST, PATCH, PUT, DELETE).
            url: Request URL.
            max_retries: Maximum number of retries on 401 (default: 1).
            **kwargs: Additional arguments passed to requests.request().

        Returns:
            requests.Response: The HTTP response.

        Raises:
            requests.RequestException: If the request fails after all retries.
        """
        # Get auth headers
        headers = kwargs.pop("headers", {})
        headers.update(self.get_headers())
        kwargs["headers"] = headers

        # Make initial request
        response = requests.request(method, url, **kwargs)

        # Handle 401 Unauthorized - retry with fresh session for Browser Auth
        if response.status_code == 401 and max_retries > 0:
            if self.config.type == AuthType.BROWSER:
                logger.warning(
                    "Received 401 Unauthorized. Invalidating browser session and retrying..."
                )
                # Invalidate current session
                self.invalidate_browser_session()

                # Get fresh headers (triggers re-login for Browser Auth)
                headers = kwargs.get("headers", {})
                headers.update(self.get_headers())
                kwargs["headers"] = headers

                # Retry request
                response = requests.request(method, url, **kwargs)
            else:
                logger.warning(
                    f"Received 401 Unauthorized with {self.config.type.value} auth. "
                    "Check your credentials."
                )

        return response
