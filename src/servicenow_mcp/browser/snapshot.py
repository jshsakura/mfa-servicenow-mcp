"""The page as an outline of its elements, each with a ref a step can act on.

``inspect_debug_window(snapshot=...)`` returns Playwright's AI snapshot: the
accessibility tree (roles, names, values, states) with ``[ref=e5]`` on every
element, iframes and open shadow roots included (``f1e2`` = frame 1, element 2).
A step then takes ``selector="e5"``. The model stops guessing CSS for a page it
has never seen: it reads what is there and points at it.

A ref is a pointer into the LAST snapshot taken over this window's connection.
A navigation, or a later snapshot, can retire it; the act path then says so
instead of waiting (actions._resolve_ref).
"""

import re
from typing import Any, Dict

REF_PREFIX = "aria-ref="
# Snapshot refs as printed: e5, f1e2. No HTML tag has such a name, so a bare
# one is unambiguous as a selector.
_BARE_REF = re.compile(r"^(?:f\d+)?e\d+$")

# ~2k tokens. A classic form with its gsft_main frame runs well past this; the
# answer to that is a narrower snapshot (a region's ref), not a longer reply.
MAX_SNAPSHOT_CHARS = 8000
_INDENT = re.compile(r"^( *)")
# Pointing at an element needs its role, name and ref. A link's href (a whole
# `- /url: ...` line, long on ServiceNow) and the pointer-cursor flag do not
# change which element it is; on a list page they were most of the outline.
_URL_LINE = re.compile(r"^ *- /url: .*$\n?", re.MULTILINE)
_NOISE = re.compile(r" \[cursor=pointer\]")


def _lean(text: str) -> str:
    return _NOISE.sub("", _URL_LINE.sub("", text))


def as_selector(selector: str) -> str:
    """The selector a step resolves; a bare snapshot ref becomes ``aria-ref=``."""
    return REF_PREFIX + selector if _BARE_REF.match(selector) else selector


def _outline(text: str, budget: int) -> Dict[str, Any]:
    """The shallowest levels of ``text`` that fit ``budget``, with what was left out.

    Not a cut at a character count: each level is whole, so every line shown is
    a real element with its ref, and the deeper ones are reached by snapshotting
    that element (its ref) rather than by a longer reply.
    """
    lines = text.splitlines()
    depths = sorted({len(_INDENT.match(line).group(1)) // 2 for line in lines})  # type: ignore[union-attr]
    kept = ""
    shown_depth = -1
    for depth in depths:
        candidate = "\n".join(
            line
            for line in lines
            if len(_INDENT.match(line).group(1)) // 2 <= depth  # type: ignore[union-attr]
        )
        if len(candidate) > budget:
            break
        kept, shown_depth = candidate, depth
    return {"text": kept, "depth": shown_depth, "lines_total": len(lines)}


def take(page: Any, target: str) -> Dict[str, Any]:
    """Snapshot the page (``target='page'``) or one element (a selector or ref)."""
    try:
        if target == "page":
            text = page.aria_snapshot(mode="ai")
        else:
            locator = page.locator(as_selector(target))
            if not locator.count():
                return {"error": f"No element matched '{target}' to snapshot."}
            text = locator.first.aria_snapshot(mode="ai")
    except TypeError:
        return {
            "error": (
                "This Playwright has no AI snapshot (aria_snapshot mode='ai'). "
                "Upgrade playwright, then reconnect the MCP server."
            )
        }
    except Exception as exc:  # noqa: BLE001 - stale ref, detached frame, bad selector
        return {"error": f"Snapshot of '{target}' failed: {str(exc).splitlines()[0][:200]}"}

    text = _lean(str(text or ""))
    if len(text) <= MAX_SNAPSHOT_CHARS:
        return {"text": text, "complete": True}
    outline = _outline(text, MAX_SNAPSHOT_CHARS)
    return {
        "text": outline["text"],
        "complete": False,
        "note": (
            f"Full snapshot is {len(text)} chars / {outline['lines_total']} lines; shown to "
            f"depth {outline['depth']} only. Snapshot a region by its ref "
            "(snapshot='e12') for what is under it."
        ),
    }
