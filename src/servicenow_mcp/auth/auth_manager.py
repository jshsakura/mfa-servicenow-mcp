"""
Authentication manager for the ServiceNow MCP server.
"""

import base64
import logging
import threading
import time
from typing import Dict, Optional
from urllib.parse import parse_qsl, urljoin, urlparse

import requests

from ..utils.config import AuthConfig, AuthType, BrowserAuthConfig

logger = logging.getLogger(__name__)


def _is_login_page_url(url: str) -> bool:
    """Return True when the URL still indicates ServiceNow login flow."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    query = parsed.query.lower()
    # Explicit login/logout page markers
    login_markers = [
        "/login.do",
        "/auth_redirect.do",
        "/external_logout_complete.do",
        "/multi_factor_auth_view.do",
        "/multi_factor_auth_setup.do",
        "/external_login_complete.do",
        "/sys_auth_info.do",
    ]
    return (
        any(marker in path for marker in login_markers)
        or "sysparm_type=login" in query
        or "sysparm_reauth=true" in query
        or "sysparm_mfa_needed=true" in query
        or "sysparm_direct=true" in query
        or path == "/login"
        or path == "/auth"
    )


def _extract_cookie_names(cookie_header: Optional[str]) -> list[str]:
    if not cookie_header:
        return []
    names: list[str] = []
    for part in cookie_header.split(";"):
        token = part.strip()
        if not token or "=" not in token:
            continue
        names.append(token.split("=", 1)[0].strip())
    return names


def _cookie_header_to_dict(cookie_header: Optional[str]) -> dict[str, str]:
    if not cookie_header:
        return {}
    cookie_map: dict[str, str] = {}
    for part in cookie_header.split(";"):
        token = part.strip()
        if not token or "=" not in token:
            continue
        name, value = token.split("=", 1)
        key = name.strip()
        if not key:
            continue
        cookie_map[key] = value.strip()
    return cookie_map


def _has_servicenow_session_cookie(cookie_names: list[str]) -> bool:
    session_cookie_names = {
        "jsessionid",
        "glide_user_session",
        "glide_session_store",
        "glide_session",
        "glide_user_route",
        "glide_ss",
    }
    return any(name.lower() in session_cookie_names for name in cookie_names)


def _looks_like_instance_main_ui(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    # Common post-login ServiceNow UI routes.
    return any(
        marker in path for marker in ["/now/", "/navpage.do", "/home.do", "/sp"]
    ) or path in ("", "/")


def _response_indicates_login_redirect(response: requests.Response) -> bool:
    location = (response.headers.get("Location") or "").lower()
    response_url = str(response.url or "").lower()
    return (
        "login.do" in location
        or "sysparm_type=login" in location
        or _is_login_page_url(response_url)
    )


def _response_indicates_authenticated_session(response: requests.Response) -> bool:
    return not _response_indicates_login_redirect(response)


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
        self._browser_last_reauth_attempt_at: Optional[float] = None
        self._browser_user_agent: Optional[str] = None
        self._browser_validation_interval_seconds: int = 30
        self._browser_last_login_at: Optional[float] = None
        self._browser_post_login_grace_seconds: int = 90
        self._browser_reauth_cooldown_seconds: int = 120

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
                if self._try_restore_browser_session(self.config.browser):
                    headers["Cookie"] = self._browser_cookie_header or ""
                    if self._browser_user_agent:
                        headers["User-Agent"] = self._browser_user_agent
                    return headers
                # Browser auth is user-driven (MFA/SSO). Always keep interactive mode.
                if not self._can_attempt_browser_reauth():
                    raise ValueError(
                        "Browser re-auth attempted too frequently. "
                        "Skipping auto reopen to prevent login loop."
                    )
                logger.info("Opening browser in interactive mode for login/MFA.")
                self._mark_browser_reauth_attempt()
                try:
                    self._login_with_browser(self.config.browser, force_interactive=True)
                except Exception:
                    # Keep the re-auth attempt timestamp to respect cooldown even on failure
                    raise
            elif self._should_validate_browser_session():
                if not self._is_browser_session_valid(self.config.browser):
                    logger.info(
                        "Browser session is no longer valid on ServiceNow. "
                        "Opening browser for interactive re-authentication..."
                    )
                    self.invalidate_browser_session()
                    self._mark_browser_reauth_attempt()
                    try:
                        self._login_with_browser(self.config.browser, force_interactive=True)
                    except Exception:
                        raise
            headers["Cookie"] = self._browser_cookie_header or ""
            if self._browser_user_agent:
                headers["User-Agent"] = self._browser_user_agent

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
        if self._browser_last_login_at is not None:
            if (time.time() - self._browser_last_login_at) < self._browser_post_login_grace_seconds:
                return False
        if self._browser_last_validated_at is None:
            return True
        return (
            time.time() - self._browser_last_validated_at
        ) >= self._browser_validation_interval_seconds

    def _can_attempt_browser_reauth(self) -> bool:
        if self._browser_last_reauth_attempt_at is None:
            return True
        return (
            time.time() - self._browser_last_reauth_attempt_at
        ) >= self._browser_reauth_cooldown_seconds

    def _mark_browser_reauth_attempt(self) -> None:
        self._browser_last_reauth_attempt_at = time.time()

    def _clear_browser_reauth_attempt(self) -> None:
        self._browser_last_reauth_attempt_at = None

    def _is_browser_session_valid(self, browser_config: BrowserAuthConfig) -> bool:
        if not self.instance_url or not self._browser_cookie_header:
            return False

        try:
            response = self._probe_browser_api_with_cookie(
                self._browser_cookie_header,
                timeout_seconds=min(int(browser_config.timeout_seconds), 30),
                browser_config=browser_config,
            )
        except Exception as exc:
            logger.warning(
                "Browser session validation probe failed: %s. "
                "Marking session as invalid to be safe.",
                exc,
            )
            return False

        self._browser_last_validated_at = time.time()
        logger.debug(
            "Browser session probe result: status=%s redirect=%s url_host=%s",
            response.status_code,
            response.is_redirect,
            (urlparse(str(response.url)).hostname or "").lower(),
        )

        if not _response_indicates_authenticated_session(response):
            return False

        if response.status_code in (401, 403):
            logger.info(
                "Browser session probe is authenticated but unauthorized for probe path: "
                "status=%s probe_path=%s",
                response.status_code,
                browser_config.probe_path,
            )
            return True

        return True

    def _probe_browser_api_with_cookie(
        self,
        cookie_header: str,
        timeout_seconds: int,
        browser_config: BrowserAuthConfig,
    ) -> requests.Response:
        if not self.instance_url:
            raise ValueError("Instance URL is required for browser authentication")

        probe_target = browser_config.probe_path or "/api/now/table/sys_user"
        parsed_probe = urlparse(probe_target)
        probe_url = (
            probe_target
            if parsed_probe.scheme and parsed_probe.netloc
            else urljoin(f"{self.instance_url.rstrip('/')}/", probe_target.lstrip("/"))
        )
        parsed_url = urlparse(probe_url)
        probe_params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        if parsed_url.query:
            probe_url = parsed_url._replace(query="").geturl()
        probe_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._browser_user_agent:
            probe_headers["User-Agent"] = self._browser_user_agent
        probe_cookies = _cookie_header_to_dict(cookie_header)
        return requests.get(
            probe_url,
            params=probe_params,
            headers=probe_headers,
            cookies=probe_cookies,
            timeout=timeout_seconds,
            allow_redirects=False,
        )

    def _try_restore_browser_session(self, browser_config: BrowserAuthConfig) -> bool:
        if not self.instance_url or not browser_config.user_data_dir:
            return False
        instance_url = self.instance_url
        instance_host = (urlparse(instance_url).hostname or "").lower()
        timeout_ms = min(int(browser_config.timeout_seconds), 30) * 1000
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return False

        logger.info(
            "Attempting browser session restore from persistent profile: host=%s user_data_dir=%s",
            instance_host,
            browser_config.user_data_dir,
        )
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    browser_config.user_data_dir,
                    headless=browser_config.headless,
                )
                page = context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(instance_url, timeout=timeout_ms, wait_until="domcontentloaded")
                except Exception:
                    # Navigation can fail transiently; cookie probe below is authoritative.
                    pass
                # Capture User-Agent for session consistency
                self._browser_user_agent = page.evaluate("navigator.userAgent")
                cookies = context.cookies()
                cookie_header = self._build_instance_cookie_header(
                    cookies, instance_url, instance_host
                )
                context.close()
        except Exception as exc:
            logger.info("Browser session restore failed while opening profile: %s", exc)
            return False

        if not cookie_header:
            logger.info("Browser session restore skipped: no instance cookies found")
            return False

        try:
            probe = self._probe_browser_api_with_cookie(
                cookie_header,
                timeout_seconds=10,
                browser_config=browser_config,
            )
        except requests.RequestException as exc:
            logger.info("Browser session restore probe failed: %s", exc)
            return False

        if not _response_indicates_authenticated_session(probe):
            logger.info("Browser session restore probe unauthorized: status=%s", probe.status_code)
            return False
        if probe.status_code in (401, 403):
            logger.info(
                "Browser session restore probe hit ACL/role restriction: status=%s probe_path=%s",
                probe.status_code,
                browser_config.probe_path,
            )

        self._browser_cookie_header = cookie_header
        self._browser_cookie_expires_at = time.time() + (browser_config.session_ttl_minutes * 60)
        self._browser_session_key = instance_host
        self._browser_last_validated_at = time.time()
        self._browser_last_login_at = time.time()
        self._clear_browser_reauth_attempt()
        logger.info(
            "Browser session restored: session_key=%s cookie_count=%s cookie_names=%s ttl_minutes=%s",
            self._browser_session_key,
            len(_extract_cookie_names(self._browser_cookie_header)),
            ",".join(_extract_cookie_names(self._browser_cookie_header)),
            browser_config.session_ttl_minutes,
        )
        return True

    def _build_instance_cookie_header(
        self, cookies: list[dict], instance_url: str, instance_host: str
    ) -> Optional[str]:
        candidates: list[dict] = []
        for cookie in cookies:
            domain = str(cookie.get("domain", "")).lstrip(".").lower()
            # Accept both instance-scoped cookies (foo.instance.service-now.com)
            # and parent-domain cookies (.service-now.com) that apply to the instance.
            if not (domain.endswith(instance_host) or instance_host.endswith(domain)):
                continue
            # Some enterprise SSO chains issue required instance cookies without
            # the secure flag in browser context metadata. Keep domain-scoped
            # cookies and let server-side probe decide session validity.
            candidates.append(cookie)

        if not candidates:
            return None

        # Deduplicate by cookie name to avoid sending conflicting values from
        # parent + child domains. Prefer instance-specific domain cookies.
        def _priority(c: dict) -> tuple[int, int]:
            domain = str(c.get("domain", "")).lstrip(".").lower()
            is_instance_specific = 1 if domain.endswith(instance_host) else 0
            return (is_instance_specific, len(domain))

        deduped: dict[str, dict] = {}
        for cookie in sorted(candidates, key=_priority, reverse=True):
            name = str(cookie.get("name", "")).strip()
            if not name or name in deduped:
                continue
            deduped[name] = cookie

        return "; ".join([f"{c['name']}={c['value']}" for c in deduped.values()])

    def _is_instance_cookie(self, cookie: dict, instance_host: str) -> bool:
        domain = str(cookie.get("domain", "")).lstrip(".").lower()
        return bool(domain and domain.endswith(instance_host))

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
    ) -> None:
        """
        Run browser login safely when called from either sync or async contexts.

        Playwright Sync API cannot run inside an active asyncio event loop.
        MCP tool execution may happen while an event loop is active, so we
        offload Sync API usage to a separate thread in that case.
        """

        def _run_sync_login(interactive: bool) -> None:
            try:
                import asyncio

                loop = asyncio.get_running_loop()
                if loop.is_running():
                    error_holder: list[BaseException] = []

                    def _runner() -> None:
                        try:
                            self._login_with_browser_sync(browser_config, interactive)
                        except BaseException as exc:  # noqa: BLE001
                            error_holder.append(exc)

                    thread = threading.Thread(target=_runner, daemon=True)
                    thread.start()
                    thread.join()

                    if error_holder:
                        raise error_holder[0]
                    return
            except RuntimeError:
                # No running event loop in this thread; safe to execute sync API directly.
                pass

            self._login_with_browser_sync(browser_config, interactive)

        try:
            _run_sync_login(force_interactive)
        except ValueError as exc:
            error_text = str(exc).lower()
            should_fallback_to_interactive = (
                not force_interactive and "timed out waiting for browser login/mfa" in error_text
            )
            if should_fallback_to_interactive:
                logger.info(
                    "Automatic browser re-auth timed out. "
                    "Falling back to interactive re-auth with prefilled credentials."
                )
                _run_sync_login(True)
                return
            raise

    def _login_with_browser_sync(
        self, browser_config: BrowserAuthConfig, force_interactive: bool = False
    ) -> None:
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
        # In interactive MFA mode, allow enough time for user input/device approval.
        # Do not force a short cap that closes the browser mid-authentication.
        wait_budget_ms = max(timeout_ms, 300000) if force_interactive else timeout_ms
        instance_host = (urlparse(instance_url).hostname or "").lower()
        logger.info(
            "Starting browser auth flow: instance_host=%s login_host=%s timeout_seconds=%s mode=%s",
            instance_host,
            (urlparse(login_url).hostname or "").lower(),
            int(browser_config.timeout_seconds),
            "interactive" if force_interactive else "auto",
        )

        # 세션 만료 시 강제로 브라우저 표시 (headless 설정 무시)
        use_headless = browser_config.headless and not force_interactive

        if use_headless and not self._browser_cookie_header and not browser_config.user_data_dir:
            raise ValueError(
                "Initial MFA/SSO bootstrap should run with headless=false for interactive login "
                "unless SERVICENOW_BROWSER_USER_DATA_DIR is set."
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

            # Store the User-Agent from the browser to match in subsequent requests
            self._browser_user_agent = page.evaluate("navigator.userAgent")

            # For persistent profiles, keep existing cookies to allow session reuse.
            # For ephemeral contexts, clear only instance cookies to avoid stale session conflicts.
            if not browser_config.user_data_dir:
                existing_cookies = context.cookies()
                idp_cookies = [
                    cookie
                    for cookie in existing_cookies
                    if not self._is_instance_cookie(cookie, instance_host)
                ]
                context.clear_cookies()
                if idp_cookies:
                    context.add_cookies(idp_cookies)

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
                    if force_interactive:
                        logger.info(
                            "Interactive mode: credentials prefilled and login submitted. "
                            "Waiting for manual MFA completion."
                        )
                else:
                    if page.locator(pass_selector).count() > 0:
                        page.locator(pass_selector).press("Enter")
                    if force_interactive:
                        logger.info(
                            "Interactive mode: credentials prefilled and Enter submitted. "
                            "Waiting for manual MFA completion."
                        )

            logger.info(
                "Browser login waiting for manual completion (MFA/SSO). "
                "Please complete the login in the opened browser window."
            )

            # Keep browser open until cookie-based API probe confirms authenticated session.
            # Avoid closing too early on transient cookies while MFA/SSO is still in progress.
            start = time.time()
            login_confirmed = False
            successful_probes = 0
            stable_instance_ticks = 0
            saw_unauthorized_probe = False
            while (time.time() - start) * 1000 < wait_budget_ms:
                current_url = page.url
                current_host = (urlparse(current_url).hostname or "").lower()
                # Use full-context cookies; some IdP/ServiceNow flows keep auth
                # cookies on parent domains that may not be returned for a single URL filter.
                current_cookies = context.cookies()
                cookie_header = self._build_instance_cookie_header(
                    current_cookies, instance_url, instance_host
                )
                if cookie_header:
                    cookie_names = _extract_cookie_names(cookie_header)
                    if current_host == instance_host and not _is_login_page_url(current_url):
                        stable_instance_ticks += 1
                    else:
                        stable_instance_ticks = 0
                    try:
                        probe = self._probe_browser_api_with_cookie(
                            cookie_header,
                            timeout_seconds=min(int(browser_config.timeout_seconds), 5),
                            browser_config=browser_config,
                        )
                        # Require consecutive successful probes so we do not treat
                        # intermediate redirect/cookie states as completed MFA login.
                        # Also ensure the probe returned a clear authenticated status (200 or 403).
                        # A 401 (Unauthorized) or 3xx (Redirect) indicates login is still in progress.
                        if _response_indicates_authenticated_session(
                            probe
                        ) and probe.status_code in (200, 403):
                            resolved_url = str(probe.url)
                            resolved_host = (urlparse(resolved_url).hostname or "").lower()
                            if (
                                resolved_host == instance_host
                                and current_host == instance_host
                                and not _is_login_page_url(resolved_url)
                                and not _is_login_page_url(current_url)
                            ):
                                successful_probes += 1
                                logger.debug(
                                    "Browser auth probe success candidate: status=%s current_host=%s "
                                    "resolved_host=%s stable_ticks=%s successful_probes=%s cookie_count=%s",
                                    probe.status_code,
                                    current_host,
                                    resolved_host,
                                    stable_instance_ticks,
                                    successful_probes,
                                    len(cookie_names),
                                )
                                if successful_probes >= 2:
                                    logger.info(
                                        "Browser auth confirmed by probe: status=%s current_host=%s "
                                        "resolved_host=%s cookie_names=%s",
                                        probe.status_code,
                                        current_host,
                                        resolved_host,
                                        ",".join(cookie_names),
                                    )
                                    login_confirmed = True
                                    break
                            else:
                                successful_probes = 0
                        else:
                            saw_unauthorized_probe = True
                            logger.warning(
                                "Browser auth probe unauthorized: status=%s current_host=%s "
                                "stable_ticks=%s cookie_names=%s",
                                probe.status_code,
                                current_host,
                                stable_instance_ticks,
                                ",".join(cookie_names),
                            )
                            successful_probes = 0
                    except requests.RequestException:
                        # During MFA transitions network hiccups are possible; keep polling until timeout.
                        successful_probes = 0
                    # Fallback for environments where API probe is flaky/blocked after MFA.
                    # In interactive mode, trust stable main-UI state to avoid hanging forever.
                    if (
                        force_interactive
                        and stable_instance_ticks >= 8
                        and _looks_like_instance_main_ui(current_url)
                        and _has_servicenow_session_cookie(cookie_names)
                    ):
                        logger.info(
                            "Interactive browser auth confirmed by stable main UI: "
                            "current_url=%s stable_ticks=%s cookie_names=%s",
                            current_url,
                            stable_instance_ticks,
                            ",".join(cookie_names),
                        )
                        login_confirmed = True
                        break
                    if (
                        not force_interactive
                        and stable_instance_ticks >= 5
                        and _has_servicenow_session_cookie(cookie_names)
                    ):
                        logger.info(
                            "Browser auth confirmed by stable instance URL and session cookie: "
                            "current_host=%s stable_ticks=%s cookie_names=%s had_unauthorized_probe=%s",
                            current_host,
                            stable_instance_ticks,
                            ",".join(cookie_names),
                            saw_unauthorized_probe,
                        )
                        login_confirmed = True
                        break
                time.sleep(1)

            if not login_confirmed:
                if use_headless:
                    raise ValueError(
                        "Timed out waiting for browser login/MFA in headless mode. "
                        "If MFA prompt is required, run once with SERVICENOW_BROWSER_HEADLESS=false "
                        "to refresh session, then retry headless."
                    )
                raise ValueError(
                    "Timed out waiting for manual browser login/MFA completion. "
                    "Increase SERVICENOW_BROWSER_TIMEOUT and try again."
                )

            # Capture from full context for the same reason as in the polling loop.
            cookies = context.cookies()
            if not cookies:
                raise ValueError("Browser login succeeded but no cookies were captured")

            cookie_header = self._build_instance_cookie_header(cookies, instance_url, instance_host)
            if not cookie_header:
                raise ValueError("No instance-scoped secure cookies captured after login")
            self._browser_cookie_header = cookie_header
            self._browser_cookie_expires_at = time.time() + (
                browser_config.session_ttl_minutes * 60
            )
            self._browser_session_key = instance_host
            self._browser_last_validated_at = time.time()
            self._browser_last_login_at = time.time()
            self._clear_browser_reauth_attempt()
            # Final validation before closing browser: avoid storing UI-only cookies that
            # still fail API auth and cause immediate 401/reopen loops.
            final_probe = self._probe_browser_api_with_cookie(
                self._browser_cookie_header,
                timeout_seconds=10,
                browser_config=browser_config,
            )
            if not _response_indicates_authenticated_session(final_probe):
                self.invalidate_browser_session()
                # Include more detail for debugging auth failures
                probe_url = final_probe.url
                probe_text = final_probe.text[:200]
                raise ValueError(
                    f"Browser login completed, but API auth is still unauthorized. "
                    f"Status: {final_probe.status_code}, URL: {probe_url}, Response: {probe_text}"
                )
            if final_probe.status_code in (401, 403):
                logger.info(
                    "Browser login completed and session is authenticated, but probe path is unauthorized: "
                    "status=%s probe_path=%s",
                    final_probe.status_code,
                    browser_config.probe_path,
                )
            logger.info(
                "Browser session stored: session_key=%s cookie_count=%s cookie_names=%s ttl_minutes=%s",
                self._browser_session_key,
                len(_extract_cookie_names(self._browser_cookie_header)),
                ",".join(_extract_cookie_names(self._browser_cookie_header)),
                browser_config.session_ttl_minutes,
            )

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
        if self.config.type == AuthType.BROWSER:
            cookie_map = _cookie_header_to_dict(headers.get("Cookie"))
            if cookie_map:
                kwargs["cookies"] = cookie_map
                headers.pop("Cookie", None)
            elif "cookies" in kwargs:
                kwargs.pop("cookies", None)
        kwargs["headers"] = headers
        request_timeout = kwargs.get("timeout")
        request_host = (urlparse(url).hostname or "").lower()
        cookie_names = _extract_cookie_names(headers.get("Cookie"))
        start = time.monotonic()
        logger.info(
            "ServiceNow request start: method=%s host=%s timeout=%s auth_type=%s cookie_count=%s",
            method.upper(),
            request_host,
            request_timeout,
            self.config.type.value,
            len(cookie_names),
        )
        if cookie_names:
            logger.debug("ServiceNow request cookies: %s", ",".join(cookie_names))

        # Make initial request
        response = requests.request(method, url, **kwargs)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "ServiceNow request end: method=%s host=%s status=%s elapsed_ms=%s",
            method.upper(),
            request_host,
            response.status_code,
            elapsed_ms,
        )

        # Handle 401 Unauthorized - retry with fresh session for Browser Auth
        if response.status_code == 401 and max_retries > 0:
            if self.config.type == AuthType.BROWSER:
                # Only trigger browser re-auth when response indicates a login-session issue.
                # If this is a role/ACL 401, reopening browser creates an infinite login loop.
                if not _response_indicates_login_redirect(response):
                    logger.warning(
                        "Received 401 without login redirect indicators. "
                        "Skipping browser re-auth to avoid login loop (likely ACL/role issue). "
                        "Response: %s",
                        response.text[:200],
                    )
                    return response
                logger.warning(
                    "Received 401 Unauthorized. Invalidating browser session and retrying..."
                )
                # Invalidate current session
                self.invalidate_browser_session()

                # Get fresh headers (triggers re-login for Browser Auth)
                headers = kwargs.get("headers", {})
                headers.update(self.get_headers())
                cookie_map = _cookie_header_to_dict(headers.get("Cookie"))
                if cookie_map:
                    kwargs["cookies"] = cookie_map
                    headers.pop("Cookie", None)
                elif "cookies" in kwargs:
                    kwargs.pop("cookies", None)
                kwargs["headers"] = headers

                # Retry request
                retry_start = time.monotonic()
                response = requests.request(method, url, **kwargs)
                retry_elapsed_ms = int((time.monotonic() - retry_start) * 1000)
                logger.info(
                    "ServiceNow request retry end: method=%s host=%s status=%s elapsed_ms=%s",
                    method.upper(),
                    request_host,
                    response.status_code,
                    retry_elapsed_ms,
                )
            else:
                logger.warning(
                    f"Received 401 Unauthorized with {self.config.type.value} auth. "
                    "Check your credentials."
                )

        return response
