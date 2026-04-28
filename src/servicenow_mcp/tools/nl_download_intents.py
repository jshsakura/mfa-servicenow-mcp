"""Natural-language intent resolver for download/export requests.

Pure parsing — no ServiceNow API calls, no I/O, no model loading. All regex
is pre-compiled at module import time so per-call cost stays in the tens of
microseconds. Resolver returns either a ready route, a structured
clarification, or ``None`` (signaling the caller to fall back to default NL
handling).

Phase 1 scope: widget + app only. Other source families follow the same shape.

Invariants (do not break when adding new families in Phase 2+):
  * No nested quantifiers in any pattern. Avoid catastrophic backtracking.
  * Existing regex patterns are append-only. Never tighten — only add new
    alternations or add new sibling patterns.
  * Resolver must remain pure: no I/O, no SN calls, no module-load side effects.
  * Public response shape (keys) is locked by test_nl_download_intents.py.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Defense against pathological inputs (e.g. user pastes a 100kB script and
# then asks "download this widget"). Intent keywords always live in the
# leading sentence in practice — first 2k chars is plenty.
_MAX_TEXT_LEN = 2000

# ---------------------------------------------------------------------------
# Pre-compiled patterns (module load time, never per call)
# ---------------------------------------------------------------------------

# EN download/export verbs (word-boundaried). KO verbs (no word boundaries
# in CJK) are added as raw alternatives.
_DOWNLOAD_INTENT_RE = re.compile(
    r"\b(download|downloads|downloading|downloaded"
    r"|export|exports|exporting|exported|pull)\b"
    r"|다운로드|다운\s*받|내려\s*받|내려받|내보내|익스포트|받아줘|받아주세요",
    re.IGNORECASE,
)

# Widget / portal-source markers (EN word-boundaried, KO bare).
# "portal source(s)" routes to download_portal_sources, NOT download_app_sources.
# "포털 소스" and bare "포털" are portal-source markers in KO context.
_WIDGET_MARKER_RE = re.compile(
    r"\b(widgets?|portal\s+widget|sp\s*widget|portal\s+sources?)\b|위젯|포털\s*소스?",
    re.IGNORECASE,
)

# App / scope / "whole app" markers.
# "전체 소스" = full app source → download_app_sources.
# "포털 소스" is intentionally excluded here — it lives in _WIDGET_MARKER_RE.
_APP_MARKER_RE = re.compile(
    r"\b(app|apps|application|applications|scope"
    r"|whole\s+app|entire\s+app|all\s+sources?|all\s+source\s+code)\b"
    r"|어플리케이션|어플|앱|스코프|전체\s*소스",
    re.IGNORECASE,
)

# ServiceNow custom-scope namespace pattern: x_<vendor>_<name>.
_SCOPE_RE = re.compile(r"\bx_[a-z0-9][a-z0-9_]{2,}\b", re.IGNORECASE)

# 32-char hex sys_id.
_SYS_ID_RE = re.compile(r"\b[0-9a-f]{32}\b", re.IGNORECASE)

# Quoted identifier — captures the inside of ", ', or `.
_QUOTED_RE = re.compile(r"""['"`]([^'"`]+)['"`]""")

# "All / every / whole" breadth markers. Drives clarification phrasing when
# the user clearly wants bulk download but didn't pin a scope.
_BREADTH_ALL_RE = re.compile(
    r"\b(all|every|whole|entire)\b|모든|전체|다\s*받|다\s*다운",
    re.IGNORECASE,
)

# Export verb specifically (subset of the broader intent regex). Used purely
# to echo the user's verb back in clarification questions.
_EXPORT_VERB_RE = re.compile(
    r"\b(export|exports|exporting|exported)\b|내보내|익스포트",
    re.IGNORECASE,
)

# Hard false-positive phrases — text contains a download/export verb but
# the request is unambiguously NOT a source download. Returning None here
# lets legacy sn_nl handle the request normally.
_FALSE_POSITIVE_RE = re.compile(
    r"\bpull\s+request(s)?\b"
    r"|\bdownload\s+(speed|bandwidth|rate|size|time)\b"
    r"|\bdata\s+export\b",
    re.IGNORECASE,
)

# File-format tokens. Only treated as a false-positive signal when the
# request also has no widget/app/scope anchor, since those signal table-API
# data export rather than source download.
_FILE_FORMAT_RE = re.compile(
    r"\b(csv|excel|xlsx|json|xml|pdf|tsv)\b",
    re.IGNORECASE,
)

# ASCII word that immediately follows "widget"/"위젯". The trailing word
# boundary on widgets? prevents the engine from matching "widget" inside
# "widgets" and then capturing the leftover "s" as a token.
_WIDGET_FOLLOWING_RE = re.compile(
    r"(?:widgets?\b|위젯)\s*[:\-]?\s*([A-Za-z0-9_][A-Za-z0-9_\-]*)",
    re.IGNORECASE,
)

# ASCII word that immediately precedes "widget".
_WIDGET_PRECEDING_RE = re.compile(
    r"\b([A-Za-z0-9_][A-Za-z0-9_\-]*)\s+widgets?\b",
    re.IGNORECASE,
)

# Stop words — never accept these as widget tokens. Keep lowercased.
_WIDGET_STOP_WORDS = frozenset(
    {
        # EN articles, determiners, generic nouns
        "the",
        "a",
        "an",
        "this",
        "that",
        "these",
        "those",
        "my",
        "our",
        "your",
        "all",
        "every",
        "any",
        "some",
        "another",
        "other",
        "such",
        "same",
        "portal",
        "sp",
        "service",
        "new",
        # EN prepositions / connectives
        "in",
        "of",
        "for",
        "from",
        "with",
        "within",
        "on",
        "to",
        "into",
        "and",
        "or",
        # EN download verbs (don't capture the verb as a token)
        "download",
        "downloads",
        "downloading",
        "downloaded",
        "export",
        "exports",
        "exporting",
        "exported",
        "pull",
        "get",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_download_intent(text: str) -> Optional[Dict[str, Any]]:
    """Detect download/export intent and return a route or clarification.

    Returns ``None`` when the text isn't a download request — the caller
    should fall through to its default NL handler. Otherwise returns a dict:

    Ready route::

        {
            "intent": "download",
            "target_type": "widget" | "app",
            "needs_clarification": False,
            "tool": "download_portal_sources" | "download_app_sources",
            "params": {...},
        }

    Clarification::

        {
            "intent": "download",
            "target_type": "widget" | "app" | "unknown",
            "needs_clarification": True,
            "missing": ["scope" | "widget_token" | "target_type"],
            "question": "...",
            "suggested_tool": "..." | None,
        }
    """
    if not text:
        return None

    # Cap input length so a giant pasted blob can't drag the resolver into
    # millisecond-scale regex scans. Intent keywords are always in the
    # leading sentence in practice.
    if len(text) > _MAX_TEXT_LEN:
        text = text[:_MAX_TEXT_LEN]

    # Cheap early-exit: no download/export verb anywhere → not our intent.
    if _DOWNLOAD_INTENT_RE.search(text) is None:
        return None

    # False-positive guard: known phrases that contain a download/export verb
    # but aren't source downloads. Hand off to legacy sn_nl.
    if _FALSE_POSITIVE_RE.search(text):
        return None

    is_export = _EXPORT_VERB_RE.search(text) is not None
    verb = "export" if is_export else "download"
    breadth_all = _BREADTH_ALL_RE.search(text) is not None

    has_widget = _WIDGET_MARKER_RE.search(text) is not None
    has_app_marker = _APP_MARKER_RE.search(text) is not None
    scope_match = _SCOPE_RE.search(text)
    scope = scope_match.group(0) if scope_match else None

    # A bare scope namespace (x_*) implies app target unless widget marker
    # was also said. "download x_my_app" → app download.
    if scope and not has_widget and not has_app_marker:
        has_app_marker = True

    # Widget takes precedence — it's the more specific marker.
    if has_widget:
        tokens = _extract_widget_tokens(text, scope=scope)

        params: Dict[str, Any] = {}
        if scope:
            params["scope"] = scope
        if tokens:
            params["widget_ids"] = tokens

        if params:
            return {
                "intent": verb,
                "target_type": "widget",
                "needs_clarification": False,
                "tool": "download_portal_sources",
                "params": params,
            }

        # Neither scope nor token. If the user clearly meant "all widgets",
        # the missing piece is scope, not a widget name. Otherwise ask for
        # the widget identifier.
        if breadth_all:
            return {
                "intent": verb,
                "target_type": "widget",
                "needs_clarification": True,
                "missing": ["scope"],
                "question": (
                    "Which application scope? Pulling every widget across the "
                    "whole instance is unsafe — provide a scope like x_my_app."
                ),
                "suggested_tool": "download_portal_sources",
            }
        return {
            "intent": verb,
            "target_type": "widget",
            "needs_clarification": True,
            "missing": ["widget_token"],
            "question": (
                "Which widget? Provide a widget name, id, or sys_id "
                f"(e.g. '{verb} widget \"my-widget\"')."
            ),
            "suggested_tool": "download_portal_sources",
        }

    if has_app_marker:
        if scope:
            return {
                "intent": verb,
                "target_type": "app",
                "needs_clarification": False,
                "tool": "download_app_sources",
                "params": {"scope": scope},
            }
        return {
            "intent": verb,
            "target_type": "app",
            "needs_clarification": True,
            "missing": ["scope"],
            "question": ("Which application scope? Provide a scope namespace " "like x_my_app."),
            "suggested_tool": "download_app_sources",
        }

    # Download verb but no anchor. If a file-format token (csv/excel/json/etc.)
    # is also in the text, this is almost certainly a table-data export
    # request, not a source download — hand off to legacy.
    if _FILE_FORMAT_RE.search(text):
        return None

    # Truly ambiguous.
    return {
        "intent": verb,
        "target_type": "unknown",
        "needs_clarification": True,
        "missing": ["target_type"],
        "question": (
            f"What should be {'exported' if is_export else 'downloaded'} — a "
            "specific widget or a whole app scope? Say 'widget <name>' or "
            "'app <scope>'."
        ),
        "suggested_tool": None,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _extract_widget_tokens(text: str, scope: Optional[str] = None) -> list[str]:
    """Pull every plausible widget identifier from ``text``.

    Sources (deduplicated, order-preserving):
        1. 32-char hex sys_ids
        2. Quoted strings (", ', `)
        3. Word(s) right after "widget"/"위젯"
        4. Word(s) right before "widget"

    Tokens that match the detected scope or that are stop-words are dropped.
    """
    seen: list[str] = []
    seen_lower: set[str] = set()
    scope_lower = scope.lower() if scope else None

    def _add(token: str) -> None:
        cleaned = token.strip()
        if not cleaned:
            return
        lower = cleaned.lower()
        if lower in _WIDGET_STOP_WORDS:
            return
        if scope_lower and lower == scope_lower:
            return
        if lower in seen_lower:
            return
        seen.append(cleaned)
        seen_lower.add(lower)

    for m in _SYS_ID_RE.finditer(text):
        _add(m.group(0))

    for m in _QUOTED_RE.finditer(text):
        _add(m.group(1))

    for m in _WIDGET_FOLLOWING_RE.finditer(text):
        _add(m.group(1))

    for m in _WIDGET_PRECEDING_RE.finditer(text):
        _add(m.group(1))

    return seen
