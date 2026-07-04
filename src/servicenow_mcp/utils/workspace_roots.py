"""Auto-registry of download roots the server ACTUALLY used.

"Personal configuration" without a config knob: every source download records
the scope root it resolved (default ./temp/<inst>/<scope> or a caller's
output_dir) here, so offline surfaces (the sn_health workspace snapshot) look
where the user really downloads — never just an assumed ./temp.

Best-effort by design: recording or reading must never fail a download or a
health check. LRU-capped; entries whose directory no longer exists are pruned
on read.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from servicenow_mcp.utils.atomic_io import atomic_write_text

logger = logging.getLogger(__name__)

_MAX_ROOTS = 20


def _state_file() -> Path:
    # Same state dir the auth manager uses (~/.mfa_servicenow_mcp).
    return Path.home() / ".mfa_servicenow_mcp" / "download_roots.json"


def _read_state() -> Dict[str, str]:
    path = _state_file()
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning("workspace_roots: unreadable %s (%s) — treating as empty", path, exc)
        return {}


def record_download_root(root: Path) -> None:
    """Remember a download root (called by the download tools). Never raises."""
    try:
        key = str(Path(root).expanduser().resolve())
        state = _read_state()
        state[key] = datetime.now(timezone.utc).isoformat()
        if len(state) > _MAX_ROOTS:
            # LRU: drop the oldest entries beyond the cap.
            oldest = sorted(state, key=lambda k: state[k])[: len(state) - _MAX_ROOTS]
            state = {k: v for k, v in state.items() if k not in oldest}
        path = _state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(state, indent=0))
    except Exception as exc:  # noqa: BLE001 — recording must never fail a download
        logger.warning("workspace_roots: failed to record %s: %s", root, exc)


def known_download_roots() -> List[Path]:
    """Recorded roots that still exist on disk, newest first. Never raises."""
    try:
        state = _read_state()
        roots: List[Path] = []
        for key in sorted(state, key=lambda k: state[k], reverse=True):
            p = Path(key)
            if p.is_dir():
                roots.append(p)
        return roots
    except Exception as exc:  # noqa: BLE001
        logger.warning("workspace_roots: failed to list roots: %s", exc)
        return []
