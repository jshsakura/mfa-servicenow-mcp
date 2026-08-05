"""A full-page screenshot of the thing that actually scrolls.

Playwright's ``full_page=True`` grows the TOP document to its scroll height and
shoots that. On a portal page or a classic ``*.do`` url that is the right thing,
because the top document is the scroller.

On Next Experience it is a no-op, and measured rather than assumed: on
``/now/nav/ui/...`` the shell reports ``scrollHeight == innerHeight`` exactly —
it never scrolls. The classic UI it wraps sits in an iframe (inside a shadow
root) and that frame has its own scrollbar. So ``full`` returned one viewport
and called itself full: the caller asked to see a whole list and got the top of
it, with nothing saying so.

The fix is the obvious one and it changes nothing on the page: scroll the frame
that really scrolls, shoot each screen, stitch, and put the scroll position
back. No DOM is touched, no element is resized, no viewport is emulated — the
only thing that moves is a scroll offset, which is restored.

What is deliberate here:

- **The scroller is found, not assumed.** The biggest same-origin overflow wins;
  cross-origin frames are skipped because their scroll position is not ours to
  drive.
- **A cap that says so.** A page can be arbitrarily long, and stitching it is
  real memory. The tile count is bounded, and when the bound bites, the result
  SAYS which part was captured instead of handing back a shorter image that
  looks complete.
- **A growing page is reported, not hidden.** Scrolling triggers lazy loading,
  so the height read at the start can be wrong by the end. Whether it grew is
  part of the answer.
- **Failure degrades loudly.** Without Pillow, or on a frame that will not
  answer, this returns None and the caller falls back to the ordinary shot —
  which must then not be described as a full-page capture.
"""

import io
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Enough for a long list without turning one screenshot into hundreds of
# megabytes of Python image work. When it bites, the caller is told.
MAX_TILES = 12

# Layout settles and sticky headers re-paint after a scroll; without this the
# seam between two tiles catches a half-drawn row.
SETTLE_S = 0.25

_METRICS = """
(() => {
  const el = document.scrollingElement || document.documentElement;
  if (!el) return null;
  return {
    scrollH: el.scrollHeight,
    clientH: el.clientHeight,
    top: el.scrollTop,
  };
})()
"""


def _metrics(target: Any) -> Optional[Dict[str, float]]:
    try:
        reading = target.evaluate(_METRICS)
    except Exception as exc:  # noqa: BLE001 - a frame that will not answer is not a crash
        logger.debug("Could not read scroll metrics: %s", exc)
        return None
    if not isinstance(reading, dict) or not reading.get("clientH"):
        return None
    return {key: float(reading.get(key) or 0.0) for key in ("scrollH", "clientH", "top")}


def _overflows(metrics: Optional[Dict[str, float]]) -> bool:
    # One pixel of slack: sub-pixel layout routinely reports a scrollHeight a
    # hair over the client height on a page that does not scroll at all.
    return bool(metrics and metrics["scrollH"] > metrics["clientH"] + 1)


def page_scrolls(page: Any) -> bool:
    """Is the top document the scroller? Then Playwright already handles it."""
    return _overflows(_metrics(page))


def find_scrolling_frame(page: Any) -> Optional[Any]:
    """The same-origin frame with the most hidden content, or None.

    Cross-origin frames are skipped: we cannot read their metrics and driving
    another site's scroll position is not this feature's business.
    """
    try:
        frames = list(page.frames)
        main = page.main_frame
        main_url = str(page.url)
    except Exception as exc:  # noqa: BLE001 - a page without frames is normal
        logger.debug("Could not enumerate frames for a scrolling capture: %s", exc)
        return None

    from urllib.parse import urlparse

    main_host = (urlparse(main_url).hostname or "").lower()
    best: Optional[Any] = None
    best_overflow = 0.0
    for frame in frames:
        if frame is main:
            continue
        try:
            frame_url = str(frame.url)
        except Exception:  # noqa: BLE001 - detached
            continue
        if main_host and (urlparse(frame_url).hostname or "").lower() != main_host:
            continue
        metrics = _metrics(frame)
        if not _overflows(metrics):
            continue
        assert metrics is not None
        overflow = metrics["scrollH"] - metrics["clientH"]
        if overflow > best_overflow:
            best, best_overflow = frame, overflow
    return best


def _frame_box(frame: Any) -> Optional[Dict[str, float]]:
    """Where the frame sits in the top document's viewport, in CSS pixels."""
    try:
        element = frame.frame_element()
        box = element.bounding_box()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not locate the scrolling frame on the page: %s", exc)
        return None
    if not box or not box.get("height") or not box.get("width"):
        return None
    return {key: float(box[key]) for key in ("x", "y", "width", "height")}


def _scroll_to(frame: Any, offset: float) -> None:
    frame.evaluate(
        "(y) => { const el = document.scrollingElement || document.documentElement;"
        " if (el) el.scrollTop = y; }",
        offset,
    )


def capture(page: Any, *, destination: str, max_tiles: int = MAX_TILES) -> Optional[Dict[str, Any]]:
    """Shoot the scrolling frame in screens and stitch them into one image.

    Returns a summary, or None when there is nothing here this can do better
    than the ordinary screenshot (no inner scroller, no Pillow, a frame that
    would not answer). None means "fall back", never "it worked".
    """
    frame = find_scrolling_frame(page)
    if frame is None:
        return None
    metrics = _metrics(frame)
    box = _frame_box(frame)
    if not metrics or not box:
        return None

    client_h = metrics["clientH"]
    scroll_h = metrics["scrollH"]
    original_top = metrics["top"]
    # The frame's visible box can be shorter than its client height when the
    # shell clips it; the clip has to stay inside the viewport either way.
    tile_h = min(client_h, box["height"])
    if tile_h <= 1:
        return None

    wanted = int(scroll_h // tile_h) + (1 if scroll_h % tile_h else 0)
    planned = min(wanted, max_tiles)

    offsets: List[float] = []
    crops: List[float] = []
    for index in range(planned):
        raw_offset = index * tile_h
        offset = min(raw_offset, max(0.0, scroll_h - tile_h))
        # A final screen that lands short of a whole tile overlaps the previous
        # one; take the repeated band off its top rather than showing it twice.
        crops.append(max(0.0, raw_offset - offset))
        offsets.append(offset)

    clip = {
        "x": box["x"],
        "y": box["y"],
        "width": box["width"],
        "height": tile_h,
    }

    tiles: List[bytes] = []
    try:
        for offset in offsets:
            _scroll_to(frame, offset)
            time.sleep(SETTLE_S)
            tiles.append(page.screenshot(clip=clip))
    except Exception as exc:  # noqa: BLE001 - a partial capture is not worth raising over
        logger.info("A scrolling capture did not complete: %s", exc)
        if not tiles:
            return None
    finally:
        try:
            _scroll_to(frame, original_top)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not restore the frame's scroll position: %s", exc)

    size = _stitch_tiles(tiles, crops=crops, css_tile_height=tile_h, destination=destination)
    if size is None:
        return None

    after = _metrics(frame)
    grew_to = after["scrollH"] if after and after["scrollH"] > scroll_h + 1 else 0.0
    summary: Dict[str, Any] = {
        "path": size["path"],
        "tiles": len(tiles),
        "width": size["width"],
        "height": size["height"],
        "css_height": round(scroll_h),
    }
    if planned < wanted or len(tiles) < wanted:
        summary["truncated"] = (
            f"captured {len(tiles)} of {wanted} screens ({round(len(tiles) * tile_h)}px "
            f"of {round(scroll_h)}px) — the rest of the page is not in this image"
        )
    if grew_to:
        summary["grew_while_scrolling"] = (
            f"the frame grew from {round(scroll_h)}px to {round(grew_to)}px while "
            "being scrolled (lazy loading), so the bottom may still be missing"
        )
    return summary


def _stitch_tiles(
    tiles: List[bytes], *, crops: List[float], css_tile_height: float, destination: str
) -> Optional[Dict[str, Any]]:
    """Join tiles top to bottom, cropping each one's repeated band."""
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        logger.info("Pillow is not installed, so a scrolling capture cannot be stitched.")
        return None
    if not tiles:
        return None

    images: List[Any] = []
    try:
        for index, raw in enumerate(tiles):
            opened = Image.open(io.BytesIO(raw))
            opened.load()
            image: Any = opened.convert("RGB")
            cut = crops[index] if index < len(crops) else 0.0
            if cut > 0:
                # Screenshots come back at the device pixel ratio, so the crop
                # is computed in the image's own pixels, not in CSS ones.
                scale = image.height / max(1.0, css_tile_height)
                offset = int(round(cut * scale))
                if 0 < offset < image.height:
                    image = image.crop((0, offset, image.width, image.height))
            images.append(image)

        width = max(image.width for image in images)
        height = sum(image.height for image in images)
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        cursor = 0
        for image in images:
            canvas.paste(image, (0, cursor))
            cursor += image.height
        # Lossless WebP: identical pixels, ~60% fewer bytes than the PNG. It
        # matters most here — a stitched page is several screens tall. See
        # capture._write_image for the measurements.
        target = os.path.splitext(destination)[0] + ".webp"
        canvas.save(target, "WEBP", lossless=True, method=6)
        return {"width": width, "height": height, "path": target}
    except Exception as exc:  # noqa: BLE001 - a failed stitch falls back, never raises
        logger.info("Could not stitch a scrolling capture: %s", exc)
        return None
    finally:
        for image in images:
            try:
                image.close()
            except Exception:  # noqa: BLE001
                pass


__all__ = [
    "MAX_TILES",
    "capture",
    "find_scrolling_frame",
    "page_scrolls",
]
