"""Turn raw page events into something worth putting in a context window.

The raw drain from probe.py can be hundreds of events. Almost none of them are
interesting, and the interesting ones are interesting as a *pattern* — "this
POST went out twice, 23ms apart" — not as a list. So this module reports counts
and judgments, writes the full material to disk, and names the file.

Grouping rules, in order of how much they save:

1. Repeated console messages collapse to one line with a count. A digest loop
   emitting the same error 400 times is one line here.
2. Network calls are reported as totals plus anomalies (failures, duplicates).
   A page that made 40 clean XHRs is "40 XHRs, none failed".
3. Bodies never appear. A hash decides whether two calls carried the same
   payload; a 200-character head lets a human recognize it.
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

MAX_CONSOLE_GROUPS = 5
MAX_ANOMALIES = 5

# Two identical calls further apart than this are a user clicking twice on
# purpose, not a double-submit bug.
DUPLICATE_WINDOW_MS = 5_000

# Digits and hex runs are the noise that stops otherwise-identical messages
# from grouping (sys_ids, row indexes, timestamps).
_SYS_ID_RE = re.compile(r"\b[0-9a-f]{32}\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+\b")


def _normalize_message(message: str) -> str:
    normalized = _SYS_ID_RE.sub("<sys_id>", message or "")
    return _NUMBER_RE.sub("<n>", normalized).strip()


def _path_of(url: str) -> str:
    """Path without origin or query — the identity a duplicate call shares."""
    without_query = (url or "").split("?", 1)[0].split("#", 1)[0]
    if "://" in without_query:
        without_query = "/" + without_query.split("://", 1)[1].split("/", 1)[-1]
    return without_query or "/"


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------


def summarize_console(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    errors = warnings = 0

    for event in events:
        if event.get("kind") not in ("console", "error"):
            continue
        level = str(event.get("level") or "error")
        if level == "error":
            errors += 1
        elif level == "warn":
            warnings += 1

        message = str(event.get("msg") or "")
        key = (level, _normalize_message(message))
        group = groups.setdefault(
            key,
            {
                "level": level,
                "msg": message[:300],
                "count": 0,
                "source": str(event.get("source") or "") or None,
                "line": event.get("line") or None,
            },
        )
        group["count"] += 1

    ranked = sorted(groups.values(), key=lambda item: item["count"], reverse=True)
    return {
        "errors": errors,
        "warnings": warnings,
        "top": ranked[:MAX_CONSOLE_GROUPS],
        "groups_omitted": max(0, len(ranked) - MAX_CONSOLE_GROUPS),
    }


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------


def _duplicate_groups(calls: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Same method, same path, same payload, close together.

    GETs are excluded: re-fetching is normal and rarely the bug. The question
    this answers is whether the CLIENT sent a write twice — which, paired with
    how many records the server actually created, is what separates a
    double-submit from a server-side duplicate insert.
    """
    buckets: Dict[Tuple[str, str, Optional[str]], List[Dict[str, Any]]] = {}
    for call in calls:
        method = str(call.get("method") or "GET").upper()
        if method == "GET":
            continue
        request = call.get("req") or {}
        key = (method, _path_of(str(call.get("url") or "")), request.get("hash"))
        buckets.setdefault(key, []).append(call)

    duplicates: List[Dict[str, Any]] = []
    for (method, path, payload_hash), group in buckets.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda item: item.get("t") or 0)
        gaps = [
            int((ordered[i].get("t") or 0) - (ordered[i - 1].get("t") or 0))
            for i in range(1, len(ordered))
        ]
        close = [gap for gap in gaps if gap <= DUPLICATE_WINDOW_MS]
        if not close:
            continue
        head = (group[0].get("req") or {}).get("head")
        duplicates.append(
            {
                "method": method,
                "path": path,
                "count": len(ordered),
                "min_gap_ms": min(close),
                "same_payload": payload_hash is not None,
                "statuses": sorted({int(call.get("status") or 0) for call in ordered}),
                "payload_head": (str(head)[:120] if head else None),
            }
        )

    return sorted(duplicates, key=lambda item: item["count"], reverse=True)[:MAX_ANOMALIES]


def summarize_network(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    calls = [event for event in events if event.get("kind") == "xhr"]
    failed = [call for call in calls if not (200 <= int(call.get("status") or 0) < 400)]

    return {
        "xhr": len(calls),
        "failed": len(failed),
        "failures": [
            {
                "method": str(call.get("method") or "GET").upper(),
                "path": _path_of(str(call.get("url") or "")),
                "status": int(call.get("status") or 0),
                "ms": int(call.get("ms") or 0),
                "error": (str(call["error"])[:160] if call.get("error") else None),
            }
            for call in failed[:MAX_ANOMALIES]
        ],
        "duplicates": _duplicate_groups(calls),
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def build_verdict(console: Dict[str, Any], network: Dict[str, Any], *, watched: float) -> str:
    """One line, stated as a finding rather than a data dump.

    Mirrors the repo's existing `verdict=True` idiom: the judgment comes first
    and the evidence is available if it is questioned.
    """
    parts: List[str] = []

    duplicates = network.get("duplicates") or []
    if duplicates:
        first = duplicates[0]
        payload = "identical payload" if first["same_payload"] else "different payloads"
        parts.append(
            f"{first['method']} {first['path']} sent {first['count']}x "
            f"{first['min_gap_ms']}ms apart ({payload}) - the client fired it more than once"
        )

    if console.get("errors"):
        top = (console.get("top") or [{}])[0]
        detail = f": {top.get('msg', '')[:80]}" if top.get("msg") else ""
        parts.append(f"{console['errors']} console error(s){detail}")

    if network.get("failed"):
        parts.append(f"{network['failed']} failed request(s)")

    if not parts:
        window = f" over {watched:.0f}s" if watched else ""
        return f"No errors, no failed requests, no duplicate calls{window} ({network.get('xhr', 0)} XHRs)."
    return "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def write_artifacts(directory: str, events: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Persist the full event list and return its path. Never returned inline."""
    if not events:
        return None
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"events-{int(time.time() * 1000)}.json")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(list(events), handle, ensure_ascii=False, indent=1)
    except OSError as exc:  # pragma: no cover - artifacts are best effort
        logger.debug("Could not write debug artifacts: %s", exc)
        return None
    return path


def compact(raw: Dict[str, Any], *, artifacts_dir: str) -> Dict[str, Any]:
    """Full compaction pass: raw drain in, context-sized report out."""
    events: Iterable[Dict[str, Any]] = raw.get("events") or []
    events = [event for event in events if isinstance(event, dict)]

    console = summarize_console(events)
    network = summarize_network(events)
    watched = float(raw.get("watched_seconds") or 0.0)

    report: Dict[str, Any] = {
        "url": raw.get("url"),
        "title": raw.get("title"),
        "verdict": build_verdict(console, network, watched=watched),
        "console": console,
        "network": network,
        "next_seq": int(raw.get("seq") or 0),
        # Which tab those numbers belong to. The caller keys its high-water mark
        # by this: seq counts from 1 in every tab, so a mark without a tab is a
        # number waiting to be applied to the wrong one. See browser/cursor.py.
        "tab_id": str(raw.get("tab_id") or ""),
        "new_events": len(events),
    }

    dropped = int(raw.get("dropped") or 0)
    if dropped:
        # Never let truncation pass for completeness.
        report["dropped_events"] = dropped

    if raw.get("screenshot"):
        report["screenshot"] = raw["screenshot"]
        # Only the summary — how many screens, how tall, what was left out. The
        # image itself stays on disk and never enters the response.
        if raw.get("screenshot_note"):
            report["screenshot_note"] = raw["screenshot_note"]
    if raw.get("styles"):
        report["styles"] = raw["styles"]

    artifacts = write_artifacts(artifacts_dir, events)
    if artifacts:
        report["artifacts"] = artifacts
    return report


__all__ = [
    "DUPLICATE_WINDOW_MS",
    "MAX_ANOMALIES",
    "MAX_CONSOLE_GROUPS",
    "build_verdict",
    "compact",
    "summarize_console",
    "summarize_network",
    "write_artifacts",
]
