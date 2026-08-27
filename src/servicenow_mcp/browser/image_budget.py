"""How many PIXELS a screenshot may carry into a context window.

A screenshot costs a model its PIXEL COUNT, not its file size. The encoding
work next door — lossless WebP, a 64KB PNG down to 26KB — buys exactly nothing
here: the same pixels arrive whichever container holds them, so a 1729x847
viewport shot is about two thousand tokens either way. Bytes are a disk
concern. Pixels are the context bill, and nothing was capping them.

So the width is capped before the image is written. At the default 1024 a
viewport shot lands near seven hundred tokens — roughly a third of what it
cost — and stays legible for what a screenshot is actually for: layout,
overlap, rendering, "does this look right". Reading a VALUE off a screenshot
was never the cheap way to get one; `evaluate` was, at a few dozen tokens.

WIDTH, not the longer side. A stitched full-page capture is several screens
tall, so capping its longest edge would crush the width — the axis that
carries legibility — to a few hundred pixels. Height is already bounded
upstream by the tile cap (`scroll_shot.MAX_TILES`), which also says how much
of the page was left out.

Never upscales. A small element shot is already cheap, and stretching it would
spend tokens to add nothing.
"""

import logging
import os
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

DEFAULT_MAX_WIDTH = 1024

# Below this a UI screenshot stops being able to answer the visual questions it
# is kept for, so a smaller setting is treated as a misconfiguration and
# ignored rather than silently producing an unreadable image.
MIN_MAX_WIDTH = 320

_ENV_VAR = "SERVICENOW_SCREENSHOT_MAX_WIDTH"
_OFF = {"0", "off", "none", "false"}


def max_width() -> int:
    """Configured pixel-width cap; 0 disables capping entirely."""
    raw = str(os.environ.get(_ENV_VAR, "") or "").strip().lower()
    if not raw:
        return DEFAULT_MAX_WIDTH
    if raw in _OFF:
        return 0
    try:
        value = int(raw)
    except ValueError:
        logger.info("%s=%r is not a number; using %d.", _ENV_VAR, raw, DEFAULT_MAX_WIDTH)
        return DEFAULT_MAX_WIDTH
    if value < MIN_MAX_WIDTH:
        logger.info("%s=%d is below %d; using %d.", _ENV_VAR, value, MIN_MAX_WIDTH, MIN_MAX_WIDTH)
        return MIN_MAX_WIDTH
    return value


def fit(image: Any) -> Tuple[Any, Dict[str, str]]:
    """Downscale *image* to the width cap. Returns (image, what-was-done).

    The returned dict rides along to the caller so the reply states the size it
    actually produced instead of the size it intended — a resize that silently
    did not happen (Pillow missing a resampler, a cap turned off in the
    environment) must not be reported as one that did.
    """
    limit = max_width()
    try:
        width, height = int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 - a screenshot beats a measurement
        return image, {}
    if not limit or width <= limit or width <= 0:
        return image, {"pixels": f"{width}x{height}"}

    scaled_height = max(1, round(height * limit / width))
    try:
        from PIL import Image  # type: ignore[import-not-found]

        # Image.Resampling.LANCZOS, not the Image.LANCZOS alias: the alias is a
        # runtime shim the type stubs do not carry, so it type-checks as an
        # unknown attribute. Pillow is pinned >=10, where the enum is present.
        resized = image.resize((limit, scaled_height), Image.Resampling.LANCZOS)
    except Exception as exc:  # noqa: BLE001 - the full-size image is still an image
        logger.info("Could not downscale the screenshot, keeping full size: %s", exc)
        return image, {"pixels": f"{width}x{height}"}
    return resized, {
        "pixels": f"{limit}x{scaled_height}",
        "downscaled_from": f"{width}x{height}",
    }


__all__ = ["DEFAULT_MAX_WIDTH", "MIN_MAX_WIDTH", "fit", "max_width"]
