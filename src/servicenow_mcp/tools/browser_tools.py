"""Browser screenshot tools — full-page capture via Playwright."""

import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..auth.auth_manager import AuthManager
from ..utils.config import ServerConfig
from ..utils.registry import register_tool
from .flow_designer_tools import _is_browser_auth

logger = logging.getLogger(__name__)


class CaptureScreenshotParams(BaseModel):
    path: str = Field(
        ...,
        description="ServiceNow path to capture, e.g. /sp or /now/nav/ui/classic/params/target/incident_list.do",
    )
    full_page: bool = Field(
        default=True, description="Capture full scrollable page height (default True)"
    )
    output_path: Optional[str] = Field(
        default=None, description="Absolute file path to save PNG. Defaults to system temp dir."
    )
    wait_ms: int = Field(
        default=2000, description="Wait ms after page load before capture (default 2000)"
    )
    viewport_width: int = Field(default=1440, description="Viewport width in pixels (default 1440)")
    viewport_height: int = Field(default=900, description="Viewport height in pixels (default 900)")


@register_tool(
    "capture_screenshot",
    params=CaptureScreenshotParams,
    description="Full-page screenshot of a ServiceNow page. Browser auth only. Returns saved file path.",
    serialization="raw_dict",
    return_type=dict,
)
def capture_screenshot(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CaptureScreenshotParams,
) -> Dict[str, Any]:
    if not _is_browser_auth(config):
        return {"success": False, "error": "capture_screenshot requires browser auth"}

    browser_config = config.browser
    if not browser_config:
        return {"success": False, "error": "No browser config available"}

    url = f"{config.instance_url.rstrip('/')}/{params.path.lstrip('/')}"

    if params.output_path:
        out = Path(params.output_path)
    else:
        ts = int(time.time())
        out = Path(tempfile.gettempdir()) / f"sn_screenshot_{ts}.png"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"success": False, "error": "playwright not installed"}

    user_data_dir = auth_manager._resolve_user_data_dir(browser_config)

    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                user_data_dir,
                headless=True,
                viewport={"width": params.viewport_width, "height": params.viewport_height},
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = context.new_page()
                page.goto(url, timeout=30000, wait_until="networkidle")
                if params.wait_ms > 0:
                    page.wait_for_timeout(params.wait_ms)
                page.screenshot(path=str(out), full_page=params.full_page)
                actual_size = out.stat().st_size
            finally:
                context.close()
    except Exception as e:
        logger.error("Screenshot failed for %s: %s", url, e)
        return {"success": False, "error": str(e), "url": url}

    return {
        "success": True,
        "file": str(out),
        "size_bytes": actual_size,
        "url": url,
        "full_page": params.full_page,
    }
