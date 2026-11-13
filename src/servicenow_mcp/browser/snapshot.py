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
from typing import Any, Dict, List, Optional, Tuple

REF_PREFIX = "aria-ref="
# Snapshot refs as printed: e5, f1e2. No HTML tag has such a name, so a bare
# one is unambiguous as a selector.
_BARE_REF = re.compile(r"^(?:f\d+)?e\d+$")

# ~3k tokens. Measured after _lean on lab: classic form 4.5k chars, workspace
# records 8.5-10.4k, a 20-row list 24.5k. A list is data the API reads; the
# answer to an outline over this is a region by its ref, not a longer reply.
MAX_SNAPSHOT_CHARS = 12000
_INDENT = re.compile(r"^( *)")
# Pointing at an element needs its role, name and ref. Measured on four lab
# pages (list, classic form, two workspaces), a third or more of Playwright's
# outline was none of those:
# - a link's href (`- /url: ...`, long on ServiceNow) and `[cursor=pointer]`;
# - aria-hidden decoration, and icon-font glyphs (private-use code points)
#   printed as text;
# - nameless wrappers (`generic`, `region`, `list`...): their children are
#   lifted one level, so nothing under them is lost;
# - a leaf that repeats text its ancestor already names (the screen-reader
#   copy of a button's label).
_URL_LINE = re.compile(r"^ *- /url: .*$")
_LINE = re.compile(r"^( *)- (.*)$")
_REF = re.compile(r" \[ref=[\w]+\]")
_GLYPHS = re.compile(r"[\s\ue000-\uf8ff\u200b]*")
# role [ref=eN] [states] : text   — with Playwright's optional YAML quoting.
_NODE = re.compile(
    r"^'?(?P<role>[a-z/]+)(?P<name> \"[^\"]*\")?(?P<attrs>(?: \[[^\]]*\])*)'?(?::(?P<text>.*))?$"
)
_WRAPPERS = frozenset(
    {"generic", "group", "region", "list", "listitem", "note", "paragraph", "text"}
)


def _lean(text: str) -> str:
    out: List[str] = []
    # (source indent, depth its children print at, the line they sit under)
    stack: List[Tuple[int, int, str]] = []
    skip_below: Optional[int] = None
    for line in text.splitlines():
        match = _LINE.match(line)
        if not match:
            continue
        indent, body = len(match.group(1)), match.group(2).replace(" [cursor=pointer]", "")
        if skip_below is not None:
            if indent > skip_below:
                continue
            skip_below = None
        if _URL_LINE.match(line):
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        depth, above = (stack[-1][1], stack[-1][2]) if stack else (0, "")
        node = _NODE.match(body)
        if node is None:  # a shape we do not parse is kept as it came
            out.append("  " * depth + "- " + body)
            stack.append((indent, depth + 1, body))
            continue
        if "[aria-hidden]" in (node.group("attrs") or ""):
            skip_below = indent
            continue
        text_part = (node.group("text") or "").strip().strip("\"'")
        if _GLYPHS.fullmatch(text_part):
            text_part = ""
        has_children = body.rstrip().endswith(":") and not text_part
        name = node.group("name")
        if node.group("role") in _WRAPPERS and not name and not text_part:
            stack.append((indent, depth, above))  # lifted: children print here
            continue
        if not has_children and not name and text_part and text_part in above:
            continue
        head = node.group("role") + (name or "") + (node.group("attrs") or "")
        printed = head + (": " + text_part if text_part else "") + (":" if has_children else "")
        out.append("  " * depth + "- " + printed)
        stack.append((indent, depth + 1, printed))
    return "\n".join(_drop_labels(out))


def _depth(line: str) -> int:
    return len(line) - len(line.lstrip(" ")) if line else -1


def _drop_labels(lines: List[str]) -> List[str]:
    """A form label (`- text: Caller`) whose next sibling's name already says it.

    Also closes a line whose children were all dropped: ``link "Open":`` with
    nothing under it reads as if something were missing.
    """
    kept = []
    for i, line in enumerate(lines):
        nxt_line = lines[i + 1] if i + 1 < len(lines) else ""
        if line.endswith(":") and _depth(nxt_line) <= _depth(line):
            line = line[:-1]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        label = re.match(r"^( *)- text: (.+)$", line)
        if label and nxt.startswith(label.group(1) + "- ") and '"' in nxt:
            named = nxt.split('"')[1]
            if label.group(2).strip() in named:
                continue
        kept.append(line)
    return kept


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
