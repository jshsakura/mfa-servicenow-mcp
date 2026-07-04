"""Append-only local journal of every confirmed remote write.

The enterprise-trust artifact: guards prevent accidents, the journal PROVES
what happened — when, as whom, against which instance, which tool/record,
with which arguments, and how it ended. One JSONL file per instance host
(mirrors the LOG_FILE host-separation policy) under
``~/.mfa_servicenow_mcp/write_journal/``.

Design constraints:
- Best-effort and fire-and-forget: journaling can NEVER fail or slow a write
  (no network, one append syscall, blanket exception guard).
- Compact: long string arguments (source bodies) are stored as sha256+length,
  never inline — the journal stays greppable and small; content itself is
  recoverable from baselines/server history.
- Simple rotation: when a host file exceeds the cap it is renamed to ``.1``
  (one generation kept) and a fresh file starts.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_MAX_BYTES = 5 * 1024 * 1024
_INLINE_STR_LIMIT = 200


def _journal_dir() -> Path:
    return Path.home() / ".mfa_servicenow_mcp" / "write_journal"


def _compact_value(value: Any) -> Any:
    """Journal-safe view of one argument value (hash long bodies, recurse)."""
    if isinstance(value, str):
        if len(value) <= _INLINE_STR_LIMIT:
            return value
        return {
            "sha256": hashlib.sha256(value.encode("utf-8", "replace")).hexdigest(),
            "length": len(value),
        }
    if isinstance(value, dict):
        return {str(k): _compact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_compact_value(v) for v in value[:20]]
    return value


def record_write(
    instance_url: str,
    user: str,
    tool: str,
    arguments: Dict[str, Any],
    outcome: str,
    error: Optional[str] = None,
    target_alias: Optional[str] = None,
) -> None:
    """Append one write-event line. Never raises, never does network I/O."""
    try:
        host = urlparse(instance_url).hostname or "unknown"
        entry: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "instance": instance_url,
            "user": user or "",
            "tool": tool,
            "args": _compact_value(dict(arguments or {})),
            "outcome": outcome,
        }
        if error:
            entry["error"] = error[:500]
        if target_alias:
            entry["instance_alias"] = target_alias
        journal_dir = _journal_dir()
        journal_dir.mkdir(parents=True, exist_ok=True)
        path = journal_dir / f"{host}.jsonl"
        try:
            if path.exists() and path.stat().st_size > _MAX_BYTES:
                path.replace(path.with_suffix(".jsonl.1"))
        except OSError:
            pass
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — journaling must never break a write
        logger.warning("write_journal: failed to record %s: %s", tool, exc)
