"""ServiceNow Batch API fusion (documented ``/api/now/v1/batch``).

Many-small-queries hot paths (verdict scans, watermark checks) pay ONE HTTP
round trip instead of N: the sub-requests ride a single POST and the server
fans them out internally. On a 150-300ms RTT link this turns a 20-query scan
from seconds into one round trip.

Availability is probed implicitly and cached per instance for the process
lifetime: a 404/405/400 on the batch endpoint marks the instance unsupported
and every caller falls back to its per-request path — same results, old
latency, no half-working states. Transient failures (network, 5xx) are NOT
cached so one hiccup doesn't disable the fast path forever.

Documented API — safe for basic/OAuth/API-key auth (no undocumented-endpoint
exception needed; see CLAUDE.md auth separation).
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.utils import json_fast
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)

_BATCH_PATH = "/api/now/v1/batch"
# instance_url -> False when the endpoint is structurally absent/blocked.
# Only structural rejections are cached; transient errors keep retrying.
_batch_unsupported: Dict[str, bool] = {}

_STRUCTURAL_REJECTIONS = {400, 404, 405, 501}


def reset_batch_support_cache() -> None:
    """Test hook: forget per-instance availability verdicts."""
    _batch_unsupported.clear()


def batch_get(
    config: ServerConfig,
    auth_manager: AuthManager,
    requests_by_id: List[Tuple[str, str]],
    timeout: int = 60,
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Execute GET sub-requests in ONE round trip.

    ``requests_by_id``: (id, relative_url) pairs — relative_url like
    ``/api/now/table/incident?sysparm_query=...``.

    Returns ``{id: {"status_code": int, "body": parsed-JSON-or-None,
    "headers": {lowercase-name: value}}}`` for every SERVICED sub-request.
    Ids the server did not service are simply absent — the caller falls back
    per-id. Returns ``None`` when the Batch API itself is unavailable (caller
    must fall back entirely).
    """
    if not requests_by_id:
        return {}
    instance = config.instance_url.rstrip("/")
    if _batch_unsupported.get(instance):
        return None

    payload = {
        "batch_request_id": "1",
        "rest_requests": [
            {
                "id": str(rid),
                "url": rel_url,
                "method": "GET",
                "headers": [{"name": "Accept", "value": "application/json"}],
            }
            for rid, rel_url in requests_by_id
        ],
    }
    try:
        response = auth_manager.make_request(
            "POST", f"{instance}{_BATCH_PATH}", json=payload, timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001 — transient; caller falls back, no caching
        logger.warning("batch_get: request failed (falling back): %s", exc)
        return None

    status = getattr(response, "status_code", None)
    if status in _STRUCTURAL_REJECTIONS:
        logger.info("batch_get: %s on %s — Batch API unsupported, cached", status, instance)
        _batch_unsupported[instance] = True
        return None
    if status != 200:
        logger.warning("batch_get: HTTP %s (falling back, not cached)", status)
        return None

    try:
        serviced = response.json().get("serviced_requests") or []
    except ValueError as exc:
        logger.warning("batch_get: unparsable response (falling back): %s", exc)
        return None

    out: Dict[str, Dict[str, Any]] = {}
    for item in serviced:
        rid = str(item.get("id") or "")
        if not rid:
            continue
        body: Any = None
        raw = item.get("body")
        if isinstance(raw, str) and raw:
            try:
                body = json_fast.loads(base64.b64decode(raw))
            except (ValueError, TypeError) as exc:
                logger.warning("batch_get: sub-request %s body unparsable: %s", rid, exc)
        headers = {
            str(h.get("name") or "").lower(): str(h.get("value") or "")
            for h in (item.get("headers") or [])
            if isinstance(h, dict)
        }
        out[rid] = {
            "status_code": int(item.get("status_code") or 0),
            "body": body,
            "headers": headers,
        }
    return out
